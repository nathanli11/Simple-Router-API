from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from fastapi import WebSocket

from .models import BestTouch, EwmaEvent, KlineEvent, TradeEvent

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Structures de données
# ---------------------------------------------------------------------------

@dataclass
class Subscription:
    """Requete de souscription client."""
    stream: str
    symbol: str
    exchange: str = "all"
    interval: Optional[str] = None
    half_life: Optional[float] = None


@dataclass
class EwmaState:
    """Etat EWMA par souscription."""
    value: Optional[float] = None
    last_ts: Optional[float] = None


@dataclass
class WSConnection:
    """Connexion WebSocket active avec souscriptions."""
    websocket: WebSocket
    username: str
    subs: List[Subscription] = field(default_factory=list)
    ewma_state: Dict[Tuple[str, str, float], EwmaState] = field(default_factory=dict)

    async def send(self, payload: Dict[str, Any]) -> None:
        """Envoie un message JSON au client (silencieux si connexion fermee)."""
        try:
            await self.websocket.send_text(json.dumps(payload))
        except Exception:
            pass  # La connexion sera nettoyée par le gestionnaire principal


# ---------------------------------------------------------------------------
# Validation des souscriptions
# ---------------------------------------------------------------------------

VALID_STREAMS = {"best_touch", "trades", "klines", "ewma"}
VALID_EXCHANGES = {"all", "binance", "okx"}
VALID_INTERVALS = {"1s", "10s", "1m", "5m"}


def _validate_subscription(msg: Dict[str, Any]) -> Tuple[bool, str, Optional[Subscription]]:
    """Valide un message de souscription et retourne (ok, erreur, sub)."""
    stream = msg.get("stream")
    symbol = msg.get("symbol")
    exchange = msg.get("exchange", "all")

    if not stream:
        return False, "champ 'stream' manquant", None
    if stream not in VALID_STREAMS:
        return False, f"stream invalide '{stream}', attendu: {sorted(VALID_STREAMS)}", None
    if not symbol or not isinstance(symbol, str):
        return False, "champ 'symbol' manquant ou invalide", None
    if exchange not in VALID_EXCHANGES:
        return False, f"exchange invalide '{exchange}', attendu: {sorted(VALID_EXCHANGES)}", None

    interval = msg.get("interval")
    half_life = msg.get("half_life")

    if stream == "klines":
        if not interval:
            return False, "champ 'interval' requis pour le stream klines", None
        if interval not in VALID_INTERVALS:
            return False, f"interval invalide '{interval}', attendu: {sorted(VALID_INTERVALS)}", None

    if stream == "ewma":
        if half_life is None:
            return False, "champ 'half_life' requis pour le stream ewma", None
        try:
            half_life = float(half_life)
            if half_life <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return False, "half_life doit etre un nombre strictement positif", None

    sub = Subscription(
        stream=stream,
        symbol=symbol.upper(),
        exchange=exchange,
        interval=interval,
        half_life=half_life,
    )
    return True, "", sub


# ---------------------------------------------------------------------------
# Hub WebSocket
# ---------------------------------------------------------------------------

class WSHub:
    """Gere les connexions WebSocket et la diffusion."""

    def __init__(self) -> None:
        self._connections: List[WSConnection] = []
        self._lock = asyncio.Lock()

    async def add(self, conn: WSConnection) -> None:
        async with self._lock:
            self._connections.append(conn)

    async def remove(self, conn: WSConnection) -> None:
        async with self._lock:
            if conn in self._connections:
                self._connections.remove(conn)

    # ------------------------------------------------------------------
    # Diffusion best touch
    # ------------------------------------------------------------------

    async def broadcast_best_touch(
        self,
        symbol: str,
        best_bid: Optional[float],
        best_ask: Optional[float],
        bid_ex: Optional[str],
        ask_ex: Optional[str],
        source_exchange: str = "",
        src_bid: Optional[float] = None,
        src_ask: Optional[float] = None,
    ) -> None:
        agg_msg = {"type": "best_touch", "data": BestTouch(
            symbol=symbol,
            best_bid=best_bid,
            best_ask=best_ask,
            best_bid_exchange=bid_ex,
            best_ask_exchange=ask_ex,
        ).model_dump()}
        src_msg = {"type": "best_touch", "data": BestTouch(
            symbol=symbol,
            best_bid=src_bid,
            best_ask=src_ask,
            best_bid_exchange=source_exchange or None,
            best_ask_exchange=source_exchange or None,
        ).model_dump()} if source_exchange else None

        async with self._lock:
            conns = list(self._connections)
        for conn in conns:
            for sub in conn.subs:
                if sub.stream != "best_touch" or sub.symbol != symbol:
                    continue
                if sub.exchange == "all":
                    await conn.send(agg_msg)
                elif sub.exchange == source_exchange and src_msg:
                    await conn.send(src_msg)

    # ------------------------------------------------------------------
    # Diffusion trades
    # ------------------------------------------------------------------

    async def broadcast_trade(self, symbol: str, exchange: str, price: float, qty: float, ts: float) -> None:
        msg = {"type": "trades", "data": TradeEvent(
            symbol=symbol, exchange=exchange, price=price, quantity=qty, timestamp=ts
        ).model_dump()}
        await self._broadcast(msg, "trades", symbol, exchange, None)

    # ------------------------------------------------------------------
    # Diffusion klines
    # ------------------------------------------------------------------

    async def broadcast_kline(self, symbol: str, exchange: str, interval: int, candle) -> None:
        interval_label = _interval_label(interval)
        msg = {"type": "klines", "data": KlineEvent(
            symbol=symbol,
            exchange=exchange,
            interval=interval_label,
            start=candle.start,
            end=candle.end,
            open=candle.open,
            high=candle.high,
            low=candle.low,
            close=candle.close,
            volume=candle.volume,
        ).model_dump()}
        await self._broadcast(msg, "klines", symbol, exchange, interval_label, strict_exchange=True)

    # ------------------------------------------------------------------
    # Mise à jour et diffusion EWMA
    # ------------------------------------------------------------------

    async def update_ewma_on_trade(self, symbol: str, exchange: str, price: float, ts: float) -> None:
        async with self._lock:
            conns = list(self._connections)
        for conn in conns:
            for sub in conn.subs:
                if sub.stream != "ewma" or sub.symbol != symbol or sub.exchange != exchange:
                    continue
                if not sub.half_life:
                    continue
                key = (symbol, sub.exchange, sub.half_life)
                state = conn.ewma_state.setdefault(key, EwmaState())
                if state.value is None:
                    state.value = price
                    state.last_ts = ts
                else:
                    dt = max(0.0, ts - (state.last_ts or ts))
                    alpha = 1 - math.exp(-math.log(2) * dt / sub.half_life) if sub.half_life > 0 else 1.0
                    state.value = (1 - alpha) * state.value + alpha * price
                    state.last_ts = ts
                msg = {"type": "ewma", "data": EwmaEvent(
                    symbol=symbol,
                    exchange=sub.exchange,
                    half_life=sub.half_life,
                    value=state.value,
                    timestamp=ts,
                ).model_dump()}
                await conn.send(msg)

    # ------------------------------------------------------------------
    # Utilitaire interne de diffusion
    # ------------------------------------------------------------------

    async def _broadcast(
        self,
        msg: Dict[str, Any],
        stream: str,
        symbol: str,
        exchange: Optional[str],
        interval_label: Optional[str],
        *,
        strict_exchange: bool = False,
    ) -> None:
        async with self._lock:
            conns = list(self._connections)
        for conn in conns:
            for sub in conn.subs:
                if sub.stream != stream or sub.symbol != symbol:
                    continue
                if strict_exchange:
                    if sub.exchange != exchange:
                        continue
                else:
                    if exchange and sub.exchange not in (exchange, "all"):
                        continue
                if interval_label and sub.interval != interval_label:
                    continue
                await conn.send(msg)


WS_HUB = WSHub()


def _interval_label(interval: int) -> str:
    if interval >= 60:
        return f"{interval // 60}m"
    return f"{interval}s"
