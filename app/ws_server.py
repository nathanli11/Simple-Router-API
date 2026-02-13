from __future__ import annotations

import asyncio
import json
import math
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from fastapi import WebSocket

from .models import BestTouch, EwmaEvent, KlineEvent, TradeEvent


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
        """Envoie un message JSON au client."""
        await self.websocket.send_text(json.dumps(payload))


class WSHub:
    """Gere les connexions WebSocket et la diffusion."""
    def __init__(self) -> None:
        self._connections: List[WSConnection] = []
        self._lock = asyncio.Lock()

    async def add(self, conn: WSConnection) -> None:
        """Enregistre une nouvelle connexion."""
        async with self._lock:
            self._connections.append(conn)

    async def remove(self, conn: WSConnection) -> None:
        """Supprime une connexion."""
        async with self._lock:
            if conn in self._connections:
                self._connections.remove(conn)

    async def broadcast_best_touch(self, symbol: str, best_bid: Optional[float], best_ask: Optional[float],
                                   bid_ex: Optional[str], ask_ex: Optional[str]) -> None:
        """Diffuse les mises a jour best touch."""
        msg = {"type": "best_touch", "data": BestTouch(
            symbol=symbol,
            best_bid=best_bid,
            best_ask=best_ask,
            best_bid_exchange=bid_ex,
            best_ask_exchange=ask_ex,
        ).model_dump()}
        await self._broadcast(msg, "best_touch", symbol, None, None)

    async def broadcast_trade(self, symbol: str, exchange: str, price: float, qty: float, ts: float) -> None:
        """Diffuse les mises a jour des trades."""
        msg = {"type": "trades", "data": TradeEvent(
            symbol=symbol, exchange=exchange, price=price, quantity=qty, timestamp=ts
        ).model_dump()}
        await self._broadcast(msg, "trades", symbol, exchange, None)

    async def broadcast_kline(self, symbol: str, exchange: str, interval: int, candle) -> None:
        """Diffuse les mises a jour de bougies."""
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
        await self._broadcast(msg, "klines", symbol, exchange, interval_label)

    async def update_ewma_on_trade(self, symbol: str, exchange: str, price: float, ts: float) -> None:
        """Met a jour l'EWMA pour les souscriptions correspondantes."""
        async with self._lock:
            conns = list(self._connections)
        for conn in conns:
            for sub in conn.subs:
                if sub.stream != "ewma":
                    continue
                if sub.symbol != symbol:
                    continue
                if sub.exchange != "all" and sub.exchange != exchange:
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

    async def _broadcast(self, msg: Dict[str, Any], stream: str, symbol: str,
                         exchange: Optional[str], interval_label: Optional[str]) -> None:
        """Envoie le message aux souscriptions correspondantes."""
        async with self._lock:
            conns = list(self._connections)
        for conn in conns:
            for sub in conn.subs:
                if sub.stream != stream:
                    continue
                if sub.symbol != symbol:
                    continue
                if exchange and sub.exchange not in (exchange, "all"):
                    continue
                if interval_label and sub.interval != interval_label:
                    continue
                await conn.send(msg)


WS_HUB = WSHub()


def _interval_label(interval: int) -> str:
    """Convertit les secondes d'intervalle en label (ex: 1m)."""
    if interval >= 60:
        return f"{interval // 60}m"
    return f"{interval}s"
