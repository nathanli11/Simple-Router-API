from __future__ import annotations

import asyncio
import logging
from typing import List

from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .auth import create_access_token, decode_access_token, hash_password, verify_password
from .config import SETTINGS, split_symbol
from .models import (
    BalanceResponse,
    DepositRequest,
    InfoResponse,
    LoginRequest,
    OrderRequest,
    OrderResponse,
    OrderStatusResponse,
    RegisterRequest,
    TokenResponse,
)
from .paper import cancel_order, deposit, get_order, place_order
from .state import Balance, STATE, User
from .storage import load_state, save_state
from .ws_server import Subscription, WSConnection, WS_HUB
from .market import kline_tick_loop
from .exchange import binance, okx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Market Data Router & Paper Trading API")
security = HTTPBearer()


async def _get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> str:
    """Resout l'utilisateur courant a partir du token Bearer."""
    token = credentials.credentials
    username = decode_access_token(token)
    if not username:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return username


@app.on_event("startup")
async def startup() -> None:
    """Charge l'etat persiste et lance les taches de fond."""
    await load_state()
    logger.info("etat charge")
    asyncio.create_task(kline_tick_loop())
    asyncio.create_task(binance.run(list(SETTINGS.symbols)))
    asyncio.create_task(okx.run(list(SETTINGS.symbols)))


@app.post("/register", response_model=TokenResponse)
async def register(req: RegisterRequest) -> TokenResponse:
    """Cree un nouvel utilisateur et retourne un JWT."""
    async with STATE.lock:
        if req.username in STATE.users:
            raise HTTPException(status_code=400, detail="user already exists")
        STATE.users[req.username] = User(username=req.username, password_hash=hash_password(req.password))
        STATE.balances.setdefault(req.username, {})

    await save_state()
    token = create_access_token(req.username)
    return TokenResponse(access_token=token)


@app.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest) -> TokenResponse:
    """Authentifie un utilisateur et retourne un JWT."""
    async with STATE.lock:
        user = STATE.users.get(req.username)
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="invalid credentials")
    return TokenResponse(access_token=create_access_token(req.username))


@app.get("/info", response_model=InfoResponse)
async def info() -> InfoResponse:
    """Retourne les actifs et paires disponibles."""
    assets = sorted({split_symbol(sym)[0] for sym in SETTINGS.symbols} | {split_symbol(sym)[1] for sym in SETTINGS.symbols})
    return InfoResponse(assets=assets, pairs=list(SETTINGS.symbols))


@app.post("/deposit")
async def do_deposit(req: DepositRequest, username: str = Depends(_get_current_user)) -> dict:
    """Depose des fonds sur le compte paper trading."""
    await deposit(username, req.asset, req.amount)
    return {"status": "ok"}


@app.post("/orders", response_model=OrderResponse)
async def submit_order(req: OrderRequest, username: str = Depends(_get_current_user)) -> OrderResponse:
    """Soumet un nouvel ordre limite."""
    if req.symbol not in SETTINGS.symbols:
        raise HTTPException(status_code=400, detail="invalid symbol")
    ok, order, reason = await place_order(username, req.token_id, req.symbol, req.side.value, req.price, req.quantity)
    if not ok:
        raise HTTPException(status_code=400, detail=reason)
    return OrderResponse(token_id=req.token_id, status=order.status)


@app.get("/orders/{token_id}", response_model=OrderStatusResponse)
async def order_status(token_id: str, username: str = Depends(_get_current_user)) -> OrderStatusResponse:
    """Retourne le statut d'un ordre."""
    order = await get_order(username, token_id)
    if not order:
        raise HTTPException(status_code=404, detail="order not found")
    return OrderStatusResponse(
        token_id=order.token_id,
        status=order.status,
        symbol=order.symbol,
        side=order.side,
        price=order.price,
        quantity=order.quantity,
        filled_price=order.filled_price,
        reason=order.reason,
    )


@app.delete("/orders/{token_id}")
async def cancel(token_id: str, username: str = Depends(_get_current_user)) -> dict:
    """Annule un ordre ouvert."""
    ok, reason = await cancel_order(username, token_id)
    if not ok:
        raise HTTPException(status_code=400, detail=reason)
    return {"status": "cancelled"}


@app.get("/balance", response_model=BalanceResponse)
async def balance(username: str = Depends(_get_current_user)) -> BalanceResponse:
    """Retourne les soldes total et disponible."""
    async with STATE.lock:
        user_bal = STATE.balances.get(username, {})
    balances: List[Balance] = []
    assets = sorted({split_symbol(sym)[0] for sym in SETTINGS.symbols} | {split_symbol(sym)[1] for sym in SETTINGS.symbols})
    for asset in assets:
        bal = user_bal.get(asset, Balance())
        balances.append({"asset": asset, "total": bal.total, "available": bal.available})
    return BalanceResponse(balances=balances)


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket) -> None:
    """Endpoint WebSocket pour les souscriptions client."""
    await websocket.accept()
    conn = None
    try:
        auth_msg = await websocket.receive_json()
        if auth_msg.get("action") != "auth":
            await websocket.close(code=1008)
            return
        token = auth_msg.get("token")
        username = decode_access_token(token or "")
        if not username:
            await websocket.close(code=1008)
            return

        conn = WSConnection(websocket=websocket, username=username)
        await WS_HUB.add(conn)
        await websocket.send_json({"type": "auth", "status": "ok"})

        while True:
            msg = await websocket.receive_json()
            action = msg.get("action")
            if action == "subscribe":
                sub = Subscription(
                    stream=msg.get("stream"),
                    symbol=msg.get("symbol"),
                    exchange=msg.get("exchange", "all"),
                    interval=msg.get("interval"),
                    half_life=msg.get("half_life"),
                )
                conn.subs.append(sub)
                await websocket.send_json({"type": "subscribed", "stream": sub.stream, "symbol": sub.symbol})
            elif action == "unsubscribe":
                stream = msg.get("stream")
                symbol = msg.get("symbol")
                conn.subs = [s for s in conn.subs if not (s.stream == stream and s.symbol == symbol)]
                await websocket.send_json({"type": "unsubscribed", "stream": stream, "symbol": symbol})
            else:
                await websocket.send_json({"type": "error", "message": "unknown action"})
    except WebSocketDisconnect:
        pass
    finally:
        if conn is not None:
            try:
                await WS_HUB.remove(conn)
            except Exception:
                pass
