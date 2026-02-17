import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app.models import OrderStatus
from app.state import Balance, Order, STATE, User
from app import storage


def _reset_state() -> None:
    STATE.users.clear()
    STATE.balances.clear()
    STATE.orders.clear()
    STATE.open_orders_by_symbol.clear()
    STATE.best_touch.clear()
    STATE.last_trade.clear()


class TestStorage(unittest.TestCase):
    def setUp(self) -> None:
        _reset_state()

    def test_save_and_load_state_roundtrip(self) -> None:
        STATE.users["alice"] = User(username="alice", password_hash="hash")
        STATE.balances["alice"] = {
            "USDT": Balance(total=1000.0, available=800.0),
            "BTC": Balance(total=0.5, available=0.1),
        }
        STATE.orders["ord-1"] = Order(
            token_id="ord-1",
            username="alice",
            symbol="BTCUSDT",
            side="buy",
            price=50000.0,
            quantity=0.01,
            status=OrderStatus.open.value,
            reserved_amount=500.0,
            created_at=123.0,
        )
        STATE.open_orders_by_symbol["BTCUSDT"] = ["ord-1"]

        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "nested" / "state.json"
            with patch("app.storage._state_path", return_value=target):
                import asyncio

                asyncio.run(storage.save_state())
                self.assertTrue(target.exists())

                raw = json.loads(target.read_text(encoding="utf-8"))
                self.assertEqual(raw["users"]["alice"]["password_hash"], "hash")
                self.assertEqual(raw["balances"]["alice"]["USDT"]["total"], 1000.0)

                _reset_state()
                asyncio.run(storage.load_state())

        self.assertIn("alice", STATE.users)
        self.assertEqual(STATE.balances["alice"]["USDT"].available, 800.0)
        self.assertEqual(STATE.orders["ord-1"].symbol, "BTCUSDT")
        self.assertEqual(STATE.open_orders_by_symbol["BTCUSDT"], ["ord-1"])

    def test_load_state_missing_file_is_noop(self) -> None:
        STATE.users["existing"] = User(username="existing", password_hash="x")

        with TemporaryDirectory() as tmp:
            missing = Path(tmp) / "does_not_exist.json"
            with patch("app.storage._state_path", return_value=missing):
                import asyncio

                asyncio.run(storage.load_state())

        self.assertIn("existing", STATE.users)
