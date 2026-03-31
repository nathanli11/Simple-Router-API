from __future__ import annotations

import asyncio
import json
import logging
import ssl
import time
from typing import List

import websockets

from ..config import build_ssl_context
from ..market import handle_best_touch, handle_trade


BINANCE_WS = "wss://stream.binance.com:9443/stream?streams="
logger = logging.getLogger(__name__)
SSL_CONTEXT = build_ssl_context()


def _stream_name(symbol: str) -> str:
    """Convertit un symbole en nom de stream Binance."""
    return symbol.lower()


def _combined_stream(symbols: List[str], channel: str) -> str:
    """Construit l'URL de stream combinee Binance."""
    streams = "/".join([f"{_stream_name(sym)}@{channel}" for sym in symbols])
    return BINANCE_WS + streams


async def _listen_book_ticker(symbols: List[str]) -> None:
    """Mises a jour best bid/ask."""
    url = _combined_stream(symbols, "bookTicker")
    while True:
        try:
            async with websockets.connect(
                url,
                ping_interval=20,
                ping_timeout=20,
                ssl=SSL_CONTEXT,
            ) as ws:
                logger.info("binance bookTicker connecte")
                async for msg in ws:
                    data = json.loads(msg)
                    payload = data.get("data", {})
                    symbol = payload.get("s")
                    if not symbol:
                        continue
                    bid = float(payload.get("b", 0))
                    ask = float(payload.get("a", 0))
                    ts = time.time()
                    await handle_best_touch("binance", symbol, bid, ask, ts)
        except ssl.SSLError as e:
            logger.exception("binance bookTicker erreur SSL: %s", e)
            await asyncio.sleep(2)
        except Exception as e:
            logger.exception("binance bookTicker erreur reseau/websocket: %s", e)
            await asyncio.sleep(2)


async def _listen_trades(symbols: List[str]) -> None:
    """Mises a jour des trades."""
    url = _combined_stream(symbols, "trade")
    while True:
        try:
            async with websockets.connect(
                url,
                ping_interval=20,
                ping_timeout=20,
                ssl=SSL_CONTEXT,
            ) as ws:
                logger.info("binance trade connecte")
                async for msg in ws:
                    data = json.loads(msg)
                    payload = data.get("data", {})
                    symbol = payload.get("s")
                    if not symbol:
                        continue
                    price = float(payload.get("p", 0))
                    qty = float(payload.get("q", 0))
                    ts = payload.get("T", 0) / 1000.0
                    await handle_trade("binance", symbol, price, qty, ts)
        except ssl.SSLError as e:
            logger.exception("binance trade erreur SSL: %s", e)
            await asyncio.sleep(2)
        except Exception as e:
            logger.exception("binance trade erreur reseau/websocket: %s", e)
            await asyncio.sleep(2)


async def run(symbols: List[str]) -> None:
    """Demarre les listeners Binance pour tous les symboles."""
    await asyncio.gather(
        _listen_book_ticker(symbols),
        _listen_trades(symbols),
    )
