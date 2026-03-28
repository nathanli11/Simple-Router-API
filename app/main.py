from __future__ import annotations

import asyncio
import json
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
    OrderModifyRequest,
    OrderRequest,
    OrderResponse,
    OrderStatusResponse,
    RegisterRequest,
    TokenResponse,
)
from .paper import cancel_order, deposit, get_order, modify_order, place_order
from .state import Balance, STATE, User
from .storage import load_state, save_state
from .ws_server import Subscription, WSConnection, WS_HUB, _validate_subscription
from .market import kline_tick_loop
from .exchange import binance, okx

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Market Data Router & Paper Trading API",
    description=(
        "Agrege les données de marché en temps réel depuis Binance et OKX. "
        "Expose des streams WebSocket (best_touch, trades, klines, ewma) "
        "et un moteur de paper trading avec ordres limites."
    ),
    version="1.1.0",
)
security = HTTPBearer()


# ---------------------------------------------------------------------------
# Authentification
# ---------------------------------------------------------------------------

async def _get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> str:
    """Resout l'utilisateur courant a partir du token Bearer."""
    username = decode_access_token(credentials.credentials)
    if not username:
        raise HTTPException(status_code=401, detail="Token invalide ou expire")
    return username


# ---------------------------------------------------------------------------
# Cycle de vie
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def startup() -> None:
    """Charge l'etat persiste et lance les taches de fond."""
    await load_state()
    logger.info("Etat charge depuis le disque")
    asyncio.create_task(kline_tick_loop())
    asyncio.create_task(binance.run(list(SETTINGS.symbols)))
    asyncio.create_task(okx.run(list(SETTINGS.symbols)))


# ---------------------------------------------------------------------------
# Routes publiques
# ---------------------------------------------------------------------------

@app.post("/register", response_model=TokenResponse, tags=["Auth"])
async def register(req: RegisterRequest) -> TokenResponse:
    """Cree un nouvel utilisateur et retourne un JWT."""
    async with STATE.lock:
        if req.username in STATE.users:
            raise HTTPException(status_code=400, detail="Nom d'utilisateur deja pris")
        STATE.users[req.username] = User(
            username=req.username,
            password_hash=hash_password(req.password),
        )
        STATE.balances.setdefault(req.username, {})
    await save_state()
    return TokenResponse(access_token=create_access_token(req.username))


@app.post("/login", response_model=TokenResponse, tags=["Auth"])
async def login(req: LoginRequest) -> TokenResponse:
    """Authentifie un utilisateur et retourne un JWT."""
    async with STATE.lock:
        user = STATE.users.get(req.username)
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Identifiants invalides")
    return TokenResponse(access_token=create_access_token(req.username))


@app.get("/info", response_model=InfoResponse, tags=["Market"])
async def info() -> InfoResponse:
    """Retourne les actifs et paires de trading disponibles."""
    assets = sorted(
        {split_symbol(sym)[0] for sym in SETTINGS.symbols}
        | {split_symbol(sym)[1] for sym in SETTINGS.symbols}
    )
    return InfoResponse(assets=assets, pairs=list(SETTINGS.symbols))


# ---------------------------------------------------------------------------
# Routes authentifiees – Paper trading
# ---------------------------------------------------------------------------

@app.post("/deposit", tags=["Trading"])
async def do_deposit(
    req: DepositRequest,
    username: str = Depends(_get_current_user),
) -> dict:
    """Depose des fonds sur le compte paper trading."""
    valid_assets = (
        {split_symbol(sym)[0] for sym in SETTINGS.symbols}
        | {split_symbol(sym)[1] for sym in SETTINGS.symbols}
    )
    if req.asset not in valid_assets:
        raise HTTPException(
            status_code=400,
            detail=f"Actif invalide. Valeurs attendues : {sorted(valid_assets)}",
        )
    await deposit(username, req.asset, req.amount)
    return {"status": "ok"}


@app.post("/orders", response_model=OrderResponse, tags=["Trading"])
async def submit_order(
    req: OrderRequest,
    username: str = Depends(_get_current_user),
) -> OrderResponse:
    """Soumet un ordre limite ou market.

    - **limit** : conserve l'ordre jusqu'a ce que le prix croise le best touch.
    - **market** : execute immediatement au meilleur prix disponible (bonus).
    """
    if req.symbol not in SETTINGS.symbols:
        raise HTTPException(status_code=400, detail="Symbole inconnu")
    ok, order, reason = await place_order(
        username, req.token_id, req.symbol,
        req.side.value, req.price, req.quantity,
        order_type=req.order_type.value if req.order_type else "limit",
    )
    if not ok:
        raise HTTPException(status_code=400, detail=reason)
    return OrderResponse(token_id=req.token_id, status=order.status, filled_price=order.filled_price)


@app.get("/orders/{token_id}", response_model=OrderStatusResponse, tags=["Trading"])
async def order_status(
    token_id: str,
    username: str = Depends(_get_current_user),
) -> OrderStatusResponse:
    """Retourne le statut detaille d'un ordre."""
    order = await get_order(username, token_id)
    if not order:
        raise HTTPException(status_code=404, detail="Ordre introuvable")
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


@app.put("/orders/{token_id}", response_model=OrderStatusResponse, tags=["Trading"])
async def update_order(
    token_id: str,
    req: OrderModifyRequest,
    username: str = Depends(_get_current_user),
) -> OrderStatusResponse:
    """Modifie le prix et/ou la quantite d'un ordre ouvert (bonus).

    Les fonds reserves sont recalcules automatiquement.
    """
    ok, order, reason = await modify_order(
        username, token_id,
        new_price=req.price,
        new_quantity=req.quantity,
    )
    if not ok:
        raise HTTPException(status_code=400, detail=reason)
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


@app.delete("/orders/{token_id}", tags=["Trading"])
async def cancel(
    token_id: str,
    username: str = Depends(_get_current_user),
) -> dict:
    """Annule un ordre ouvert et libere les fonds reserves."""
    ok, reason = await cancel_order(username, token_id)
    if not ok:
        raise HTTPException(status_code=400, detail=reason)
    return {"status": "cancelled"}


@app.get("/balance", response_model=BalanceResponse, tags=["Trading"])
async def balance(username: str = Depends(_get_current_user)) -> BalanceResponse:
    """Retourne les soldes total et disponible pour tous les actifs."""
    async with STATE.lock:
        user_bal = STATE.balances.get(username, {})
    assets = sorted(
        {split_symbol(sym)[0] for sym in SETTINGS.symbols}
        | {split_symbol(sym)[1] for sym in SETTINGS.symbols}
    )
    balances: List[Balance] = []
    for asset in assets:
        bal = user_bal.get(asset, Balance())
        balances.append({"asset": asset, "total": bal.total, "available": bal.available})
    return BalanceResponse(balances=balances)


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------

@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket) -> None:
    """
    Endpoint WebSocket temps réel.

    **Protocole :**
    1. Envoyer `{"action": "auth", "token": "<JWT>"}` en premier.
    2. Envoyer des messages `subscribe` / `unsubscribe`.

    **Streams disponibles :** `best_touch`, `trades`, `klines`, `ewma`.
    """
    await websocket.accept()
    conn: WSConnection | None = None
    try:
        # --- Authentification obligatoire en premier message ---
        try:
            auth_msg = await asyncio.wait_for(websocket.receive_json(), timeout=10.0)
        except asyncio.TimeoutError:
            await websocket.close(code=1008, reason="Timeout d'authentification")
            return
        except Exception:
            await websocket.close(code=1003, reason="Message d'authentification invalide")
            return

        if auth_msg.get("action") != "auth":
            await websocket.send_json({"type": "error", "message": "Le premier message doit etre une authentification"})
            await websocket.close(code=1008)
            return

        token = auth_msg.get("token", "")
        username = decode_access_token(token)
        if not username:
            await websocket.send_json({"type": "error", "message": "Token invalide ou expire"})
            await websocket.close(code=1008)
            return

        conn = WSConnection(websocket=websocket, username=username)
        await WS_HUB.add(conn)
        await websocket.send_json({"type": "auth", "status": "ok", "username": username})

        # --- Boucle principale des messages ---
        while True:
            try:
                raw = await websocket.receive_text()
            except WebSocketDisconnect:
                break

            # Désérialisation robuste : on répond avec une erreur si le JSON est malformé
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await conn.send({"type": "error", "message": "Message JSON invalide"})
                continue

            if not isinstance(msg, dict):
                await conn.send({"type": "error", "message": "Le message doit etre un objet JSON"})
                continue

            action = msg.get("action")

            if action == "subscribe":
                ok, err, sub = _validate_subscription(msg)
                if not ok:
                    await conn.send({"type": "error", "message": err})
                    continue
                # Evite les doublons de souscription identique
                already = any(
                    s.stream == sub.stream
                    and s.symbol == sub.symbol
                    and s.exchange == sub.exchange
                    and s.interval == sub.interval
                    and s.half_life == sub.half_life
                    for s in conn.subs
                )
                if not already:
                    conn.subs.append(sub)
                await conn.send({
                    "type": "subscribed",
                    "stream": sub.stream,
                    "symbol": sub.symbol,
                    "exchange": sub.exchange,
                })

            elif action == "unsubscribe":
                stream = msg.get("stream")
                symbol = msg.get("symbol")
                if not stream or not symbol:
                    await conn.send({"type": "error", "message": "Champs 'stream' et 'symbol' requis pour unsubscribe"})
                    continue
                before = len(conn.subs)
                conn.subs = [
                    s for s in conn.subs
                    if not (s.stream == stream and s.symbol == symbol)
                ]
                removed = before - len(conn.subs)
                await conn.send({
                    "type": "unsubscribed",
                    "stream": stream,
                    "symbol": symbol,
                    "removed": removed,
                })

            elif action == "ping":
                await conn.send({"type": "pong"})

            else:
                await conn.send({
                    "type": "error",
                    "message": f"Action inconnue '{action}'. Actions valides : subscribe, unsubscribe, ping",
                })

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.exception("Erreur WebSocket inattendue: %s", exc)
    finally:
        if conn is not None:
            try:
                await WS_HUB.remove(conn)
            except Exception:
                pass
