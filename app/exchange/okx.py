from __future__ import annotations

import asyncio
import logging
import json
import time
from typing import List

import websockets

from ..market import handle_best_touch, handle_trade


OKX_WS = "wss://ws.okx.com:8443/ws/v5/public"
logger = logging.getLogger(__name__)


def _okx_symbol(symbol: str) -> str:
    """Convertit un symbole interne en instrument OKX."""
    if symbol.endswith("USDT"):
        return symbol[:-4] + "-USDT"
    if symbol.endswith("USDC"):
        return symbol[:-4] + "-USDC"
    if symbol.endswith("USD"):
        return symbol[:-3] + "-USD"
    return symbol


async def _listen(symbols: List[str]) -> None:
    """Ecoute les tickers et trades OKX."""
    args = []
    for sym in symbols:
        inst = _okx_symbol(sym)
        args.append({"channel": "tickers", "instId": inst})
        args.append({"channel": "trades", "instId": inst})

    while True:
        try:
            async with websockets.connect(OKX_WS, ping_interval=20, ping_timeout=20) as ws:
                logger.info("okx connecte")
                await ws.send(json.dumps({"op": "subscribe", "args": args}))
                async for msg in ws:
                    data = json.loads(msg)
                    if "data" not in data:
                        continue
                    channel = data.get("arg", {}).get("channel")
                    for item in data.get("data", []):
                        inst = item.get("instId", "")
                        symbol = inst.replace("-", "")
                        if channel == "tickers":
                            bid = float(item.get("bidPx", 0))
                            ask = float(item.get("askPx", 0))
                            ts = float(item.get("ts", 0)) / 1000.0 if item.get("ts") else time.time()
                            await handle_best_touch("okx", symbol, bid, ask, ts)
                        elif channel == "trades":
                            price = float(item.get("px", 0))
                            qty = float(item.get("sz", 0))
                            ts = float(item.get("ts", 0)) / 1000.0 if item.get("ts") else time.time()
                            await handle_trade("okx", symbol, price, qty, ts)
        except Exception:
            logger.info("okx reconnexion...")
            await asyncio.sleep(2)


async def run(symbols: List[str]) -> None:
    """Demarre l'ecoute OKX pour tous les symboles."""
    await _listen(symbols)
