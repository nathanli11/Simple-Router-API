import asyncio
import json
import math
import unittest

from app.ws_server import Subscription, WSConnection, WSHub, _interval_label


class DummyWebSocket:
    def __init__(self) -> None:
        self.messages = []

    async def send_text(self, text: str) -> None:
        self.messages.append(json.loads(text))


class TestWSServer(unittest.TestCase):
    def test_interval_label(self) -> None:
        self.assertEqual(_interval_label(1), "1s")
        self.assertEqual(_interval_label(10), "10s")
        self.assertEqual(_interval_label(60), "1m")
        self.assertEqual(_interval_label(300), "5m")

    def test_broadcast_best_touch_filters_by_symbol(self) -> None:
        async def run() -> None:
            hub = WSHub()

            ws_1 = DummyWebSocket()
            ws_2 = DummyWebSocket()
            conn_1 = WSConnection(
                websocket=ws_1,
                username="u1",
                subs=[Subscription(stream="best_touch", symbol="BTCUSDT", exchange="all")],
            )
            conn_2 = WSConnection(
                websocket=ws_2,
                username="u2",
                subs=[Subscription(stream="best_touch", symbol="ETHUSDT", exchange="all")],
            )

            await hub.add(conn_1)
            await hub.add(conn_2)
            await hub.broadcast_best_touch("BTCUSDT", 100.0, 101.0, "binance", "okx")

            self.assertEqual(len(ws_1.messages), 1)
            self.assertEqual(ws_1.messages[0]["type"], "best_touch")
            self.assertEqual(ws_1.messages[0]["data"]["symbol"], "BTCUSDT")
            self.assertEqual(ws_2.messages, [])

        asyncio.run(run())

    def test_broadcast_kline_filters_exchange_and_interval(self) -> None:
        async def run() -> None:
            hub = WSHub()

            ws_ok = DummyWebSocket()
            ws_bad_exchange = DummyWebSocket()
            ws_bad_interval = DummyWebSocket()

            conn_ok = WSConnection(
                websocket=ws_ok,
                username="ok",
                subs=[Subscription(stream="klines", symbol="BTCUSDT", exchange="binance", interval="1m")],
            )
            conn_bad_exchange = WSConnection(
                websocket=ws_bad_exchange,
                username="badex",
                subs=[Subscription(stream="klines", symbol="BTCUSDT", exchange="okx", interval="1m")],
            )
            conn_bad_interval = WSConnection(
                websocket=ws_bad_interval,
                username="badint",
                subs=[Subscription(stream="klines", symbol="BTCUSDT", exchange="binance", interval="5m")],
            )

            class Candle:
                start = 1.0
                end = 2.0
                open = 10.0
                high = 12.0
                low = 9.0
                close = 11.0
                volume = 100.0

            await hub.add(conn_ok)
            await hub.add(conn_bad_exchange)
            await hub.add(conn_bad_interval)
            await hub.broadcast_kline("BTCUSDT", "binance", 60, Candle)

            self.assertEqual(len(ws_ok.messages), 1)
            self.assertEqual(ws_ok.messages[0]["type"], "klines")
            self.assertEqual(ws_bad_exchange.messages, [])
            self.assertEqual(ws_bad_interval.messages, [])

        asyncio.run(run())

    def test_update_ewma_initializes_then_smooths(self) -> None:
        async def run() -> None:
            hub = WSHub()
            ws = DummyWebSocket()
            conn = WSConnection(
                websocket=ws,
                username="u1",
                subs=[Subscription(stream="ewma", symbol="BTCUSDT", exchange="all", half_life=10.0)],
            )

            await hub.add(conn)
            await hub.update_ewma_on_trade("BTCUSDT", "binance", 100.0, 1000.0)
            await hub.update_ewma_on_trade("BTCUSDT", "binance", 110.0, 1010.0)

            self.assertEqual(len(ws.messages), 2)
            self.assertEqual(ws.messages[0]["data"]["value"], 100.0)

            alpha = 1 - math.exp(-math.log(2) * 10.0 / 10.0)
            expected = (1 - alpha) * 100.0 + alpha * 110.0
            self.assertEqual(ws.messages[1]["data"]["value"], expected)

        asyncio.run(run())

    def test_update_ewma_respects_exchange_filter(self) -> None:
        async def run() -> None:
            hub = WSHub()
            ws = DummyWebSocket()
            conn = WSConnection(
                websocket=ws,
                username="u1",
                subs=[Subscription(stream="ewma", symbol="BTCUSDT", exchange="okx", half_life=10.0)],
            )

            await hub.add(conn)
            await hub.update_ewma_on_trade("BTCUSDT", "binance", 100.0, 1000.0)
            self.assertEqual(ws.messages, [])

        asyncio.run(run())
