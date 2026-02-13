from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Dict, Tuple

from .config import SETTINGS
from .state import MarketState, STATE
from .ws_server import WS_HUB
from .paper import execute_on_best_touch


@dataclass
class Candle:
    """Accumulateur de chandeliers."""
    start: float
    end: float
    open: float
    high: float
    low: float
    close: float
    volume: float


_KLINES: Dict[Tuple[str, str, int], Candle] = {}
_KLINES_LOCK = asyncio.Lock()


def _now() -> float:
    """Retourne l'heure courante (secondes)."""
    return time.time()


def _interval_start(ts: float, interval: int) -> float:
    """Calcule le debut de bougie pour un timestamp."""
    return ts - (ts % interval)


async def handle_best_touch(exchange: str, symbol: str, bid: float, ask: float, ts: float) -> None:
    """Met a jour le best touch et diffuse aux clients."""
    async with STATE.lock:
        per_symbol = STATE.best_touch.setdefault(symbol, {})
        per_symbol[exchange] = MarketState(best_bid=bid, best_ask=ask, exchange=exchange, timestamp=ts)

        best_bid = None
        best_bid_exchange = None
        best_ask = None
        best_ask_exchange = None
        for ex, st in per_symbol.items():
            if st.best_bid is not None and (best_bid is None or st.best_bid > best_bid):
                best_bid = st.best_bid
                best_bid_exchange = ex
            if st.best_ask is not None and (best_ask is None or st.best_ask < best_ask):
                best_ask = st.best_ask
                best_ask_exchange = ex

    await WS_HUB.broadcast_best_touch(symbol, best_bid, best_ask, best_bid_exchange, best_ask_exchange)
    await execute_on_best_touch(symbol, best_bid, best_ask)


async def handle_trade(exchange: str, symbol: str, price: float, qty: float, ts: float) -> None:
    """Met a jour l'etat et les streams derives (klines, EWMA)."""
    async with STATE.lock:
        STATE.last_trade.setdefault(symbol, {})[exchange] = price

    await WS_HUB.broadcast_trade(symbol, exchange, price, qty, ts)
    await _update_kline(symbol, exchange, price, qty, ts)
    await _update_kline(symbol, "all", price, qty, ts)
    await WS_HUB.update_ewma_on_trade(symbol, exchange, price, ts)
    await WS_HUB.update_ewma_on_trade(symbol, "all", price, ts)


async def _update_kline(symbol: str, exchange: str, price: float, qty: float, ts: float) -> None:
    """Accumulate et diffuse les mises a jour de bougies."""
    async with _KLINES_LOCK:
        for interval in SETTINGS.kline_intervals_seconds:
            key = (symbol, exchange, interval)
            start = _interval_start(ts, interval)
            end = start + interval
            candle = _KLINES.get(key)
            if candle is None or ts >= candle.end:
                candle = Candle(start=start, end=end, open=price, high=price, low=price, close=price, volume=qty)
                _KLINES[key] = candle
            else:
                candle.high = max(candle.high, price)
                candle.low = min(candle.low, price)
                candle.close = price
                candle.volume += qty

            await WS_HUB.broadcast_kline(symbol, exchange, interval, candle)


async def kline_tick_loop() -> None:
    """Assure une publication de bougie au moins chaque seconde."""
    while True:
        await asyncio.sleep(1)
        now = _now()
        async with _KLINES_LOCK:
            for (symbol, exchange, interval), candle in list(_KLINES.items()):
                if now >= candle.end:
                    new_start = candle.end
                    new_end = new_start + interval
                    _KLINES[(symbol, exchange, interval)] = Candle(
                        start=new_start,
                        end=new_end,
                        open=candle.close,
                        high=candle.close,
                        low=candle.close,
                        close=candle.close,
                        volume=0.0,
                    )
                await WS_HUB.broadcast_kline(symbol, exchange, interval, _KLINES[(symbol, exchange, interval)])
