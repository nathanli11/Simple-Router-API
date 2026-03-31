"""Tests unitaires pour app/paper.py (moteur de paper trading)."""
from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from app.state import Balance, MarketState, Order, STATE, User
from app.paper import (
    cancel_order,
    deposit,
    execute_on_best_touch,
    get_order,
    modify_order,
    place_order,
)


def _reset_state() -> None:
    STATE.users.clear()
    STATE.balances.clear()
    STATE.orders.clear()
    STATE.open_orders_by_symbol.clear()
    STATE.best_touch.clear()
    STATE.last_trade.clear()


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestDeposit(unittest.TestCase):
    def setUp(self) -> None:
        _reset_state()
        STATE.users["alice"] = User(username="alice", password_hash="x")
        STATE.balances["alice"] = {}

    @patch("app.paper.save_state", new_callable=AsyncMock)
    def test_deposit_increases_balance(self, _save) -> None:
        run(deposit("alice", "USDT", 1000.0))
        bal = STATE.balances["alice"]["USDT"]
        self.assertEqual(bal.total, 1000.0)
        self.assertEqual(bal.available, 1000.0)

    @patch("app.paper.save_state", new_callable=AsyncMock)
    def test_deposit_cumulative(self, _save) -> None:
        run(deposit("alice", "USDT", 500.0))
        run(deposit("alice", "USDT", 300.0))
        bal = STATE.balances["alice"]["USDT"]
        self.assertEqual(bal.total, 800.0)
        self.assertEqual(bal.available, 800.0)


class TestPlaceLimitOrder(unittest.TestCase):
    def setUp(self) -> None:
        _reset_state()
        STATE.users["alice"] = User(username="alice", password_hash="x")
        STATE.balances["alice"] = {
            "USDT": Balance(total=1000.0, available=1000.0),
            "BTC": Balance(total=1.0, available=1.0),
        }

    @patch("app.paper.save_state", new_callable=AsyncMock)
    def test_buy_limit_order_reserves_funds(self, _save) -> None:
        ok, order, reason = run(place_order("alice", "ord-1", "BTCUSDT", "buy", 50000.0, 0.01))
        self.assertTrue(ok)
        self.assertEqual(order.status, "open")
        # 0.01 BTC * 50000 = 500 USDT réservés
        self.assertAlmostEqual(STATE.balances["alice"]["USDT"].available, 500.0)
        self.assertAlmostEqual(STATE.balances["alice"]["USDT"].total, 1000.0)

    @patch("app.paper.save_state", new_callable=AsyncMock)
    def test_sell_limit_order_reserves_base_asset(self, _save) -> None:
        ok, order, reason = run(place_order("alice", "ord-2", "BTCUSDT", "sell", 60000.0, 0.5))
        self.assertTrue(ok)
        self.assertAlmostEqual(STATE.balances["alice"]["BTC"].available, 0.5)
        self.assertAlmostEqual(STATE.balances["alice"]["BTC"].total, 1.0)

    @patch("app.paper.save_state", new_callable=AsyncMock)
    def test_insufficient_balance_rejected(self, _save) -> None:
        # Tente d'acheter pour 2000 USDT alors qu'il n'en a que 1000
        ok, order, reason = run(place_order("alice", "ord-3", "BTCUSDT", "buy", 50000.0, 0.05))
        self.assertFalse(ok)
        self.assertIsNone(order)
        self.assertIn("insuffisant", reason.lower())

    @patch("app.paper.save_state", new_callable=AsyncMock)
    def test_duplicate_token_id_rejected(self, _save) -> None:
        run(place_order("alice", "ord-dup", "BTCUSDT", "buy", 50000.0, 0.01))
        ok, order, reason = run(place_order("alice", "ord-dup", "BTCUSDT", "buy", 50000.0, 0.001))
        self.assertFalse(ok)
        self.assertIn("token_id", reason.lower())

    @patch("app.paper.save_state", new_callable=AsyncMock)
    def test_order_added_to_open_orders(self, _save) -> None:
        run(place_order("alice", "ord-open", "BTCUSDT", "buy", 50000.0, 0.01))
        self.assertIn("ord-open", STATE.open_orders_by_symbol.get("BTCUSDT", []))


class TestCancelOrder(unittest.TestCase):
    def setUp(self) -> None:
        _reset_state()
        STATE.users["alice"] = User(username="alice", password_hash="x")
        STATE.balances["alice"] = {
            "USDT": Balance(total=1000.0, available=500.0),
        }
        # Ordre déjà dans le state (réserve de 500 USDT)
        STATE.orders["ord-c"] = Order(
            token_id="ord-c", username="alice", symbol="BTCUSDT",
            side="buy", price=50000.0, quantity=0.01,
            status="open", reserved_amount=500.0,
        )
        STATE.open_orders_by_symbol["BTCUSDT"] = ["ord-c"]

    @patch("app.paper.save_state", new_callable=AsyncMock)
    def test_cancel_releases_funds(self, _save) -> None:
        ok, reason = run(cancel_order("alice", "ord-c"))
        self.assertTrue(ok)
        self.assertEqual(STATE.orders["ord-c"].status, "cancelled")
        # Les 500 USDT réservés sont libérés
        self.assertAlmostEqual(STATE.balances["alice"]["USDT"].available, 1000.0)

    @patch("app.paper.save_state", new_callable=AsyncMock)
    def test_cancel_removes_from_open_orders(self, _save) -> None:
        run(cancel_order("alice", "ord-c"))
        self.assertNotIn("ord-c", STATE.open_orders_by_symbol.get("BTCUSDT", []))

    @patch("app.paper.save_state", new_callable=AsyncMock)
    def test_cancel_nonexistent_order(self, _save) -> None:
        ok, reason = run(cancel_order("alice", "inexistant"))
        self.assertFalse(ok)
        self.assertIn("introuvable", reason.lower())

    @patch("app.paper.save_state", new_callable=AsyncMock)
    def test_cancel_already_cancelled_fails(self, _save) -> None:
        STATE.orders["ord-c"].status = "cancelled"
        ok, reason = run(cancel_order("alice", "ord-c"))
        self.assertFalse(ok)

    @patch("app.paper.save_state", new_callable=AsyncMock)
    def test_cancel_other_user_order_fails(self, _save) -> None:
        ok, reason = run(cancel_order("bob", "ord-c"))
        self.assertFalse(ok)


class TestModifyOrder(unittest.TestCase):
    def setUp(self) -> None:
        _reset_state()
        STATE.users["alice"] = User(username="alice", password_hash="x")
        STATE.balances["alice"] = {
            "USDT": Balance(total=1000.0, available=500.0),
        }
        STATE.orders["ord-m"] = Order(
            token_id="ord-m", username="alice", symbol="BTCUSDT",
            side="buy", price=50000.0, quantity=0.01,
            status="open", reserved_amount=500.0,
        )
        STATE.open_orders_by_symbol["BTCUSDT"] = ["ord-m"]

    @patch("app.paper.save_state", new_callable=AsyncMock)
    def test_modify_price_down_releases_funds(self, _save) -> None:
        # Baisse le prix → moins de fonds réservés → libère la différence
        ok, order, reason = run(modify_order("alice", "ord-m", new_price=40000.0, new_quantity=None))
        self.assertTrue(ok)
        self.assertAlmostEqual(order.price, 40000.0)
        # Nouveau coût : 40000 * 0.01 = 400 → libère 100 USDT
        self.assertAlmostEqual(STATE.balances["alice"]["USDT"].available, 600.0)

    @patch("app.paper.save_state", new_callable=AsyncMock)
    def test_modify_quantity_up_requires_more_funds(self, _save) -> None:
        # Augmente la quantité → besoin de plus de fonds
        # Disponible: 500, nouveau coût: 50000 * 0.02 = 1000 → delta = 500 → OK
        ok, order, reason = run(modify_order("alice", "ord-m", new_price=None, new_quantity=0.02))
        self.assertTrue(ok)
        self.assertAlmostEqual(order.quantity, 0.02)

    @patch("app.paper.save_state", new_callable=AsyncMock)
    def test_modify_insufficient_funds_rejected(self, _save) -> None:
        # Augmente trop → pas assez de fonds disponibles
        ok, order, reason = run(modify_order("alice", "ord-m", new_price=None, new_quantity=0.1))
        self.assertFalse(ok)

    @patch("app.paper.save_state", new_callable=AsyncMock)
    def test_modify_no_fields_rejected(self, _save) -> None:
        ok, order, reason = run(modify_order("alice", "ord-m", new_price=None, new_quantity=None))
        self.assertFalse(ok)

    @patch("app.paper.save_state", new_callable=AsyncMock)
    def test_modify_filled_order_rejected(self, _save) -> None:
        STATE.orders["ord-m"].status = "filled"
        ok, order, reason = run(modify_order("alice", "ord-m", new_price=45000.0, new_quantity=None))
        self.assertFalse(ok)


class TestExecuteOnBestTouch(unittest.TestCase):
    def setUp(self) -> None:
        _reset_state()
        STATE.users["alice"] = User(username="alice", password_hash="x")
        STATE.balances["alice"] = {
            "USDT": Balance(total=1000.0, available=500.0),
            "BTC": Balance(total=0.0, available=0.0),
        }

    @patch("app.paper.save_state", new_callable=AsyncMock)
    def test_buy_order_filled_when_ask_below_limit(self, _save) -> None:
        STATE.orders["ord-buy"] = Order(
            token_id="ord-buy", username="alice", symbol="BTCUSDT",
            side="buy", price=50000.0, quantity=0.01,
            status="open", reserved_amount=500.0,
        )
        STATE.open_orders_by_symbol["BTCUSDT"] = ["ord-buy"]

        # best_ask = 49000 < 50000 → doit être exécuté
        run(execute_on_best_touch("BTCUSDT", best_bid=48000.0, best_ask=49000.0))

        order = STATE.orders["ord-buy"]
        self.assertEqual(order.status, "filled")
        self.assertAlmostEqual(order.filled_price, 49000.0)
        # BTC crédité
        self.assertAlmostEqual(STATE.balances["alice"]["BTC"].total, 0.01)

    @patch("app.paper.save_state", new_callable=AsyncMock)
    def test_buy_order_not_filled_when_ask_above_limit(self, _save) -> None:
        STATE.orders["ord-buy2"] = Order(
            token_id="ord-buy2", username="alice", symbol="BTCUSDT",
            side="buy", price=50000.0, quantity=0.01,
            status="open", reserved_amount=500.0,
        )
        STATE.open_orders_by_symbol["BTCUSDT"] = ["ord-buy2"]

        # best_ask = 51000 > 50000 → ne doit PAS être exécuté
        run(execute_on_best_touch("BTCUSDT", best_bid=50000.0, best_ask=51000.0))

        self.assertEqual(STATE.orders["ord-buy2"].status, "open")

    @patch("app.paper.save_state", new_callable=AsyncMock)
    def test_sell_order_filled_when_bid_above_limit(self, _save) -> None:
        STATE.balances["alice"]["BTC"] = Balance(total=0.5, available=0.0)
        STATE.orders["ord-sell"] = Order(
            token_id="ord-sell", username="alice", symbol="BTCUSDT",
            side="sell", price=50000.0, quantity=0.01,
            status="open", reserved_amount=0.01,
        )
        STATE.open_orders_by_symbol["BTCUSDT"] = ["ord-sell"]

        # best_bid = 51000 > 50000 → doit être exécuté
        run(execute_on_best_touch("BTCUSDT", best_bid=51000.0, best_ask=52000.0))

        order = STATE.orders["ord-sell"]
        self.assertEqual(order.status, "filled")
        self.assertAlmostEqual(order.filled_price, 51000.0)

    @patch("app.paper.save_state", new_callable=AsyncMock)
    def test_no_crash_when_no_open_orders(self, _save) -> None:
        # Ne doit pas lever d'exception
        run(execute_on_best_touch("BTCUSDT", best_bid=50000.0, best_ask=50100.0))


class TestGetOrder(unittest.TestCase):
    def setUp(self) -> None:
        _reset_state()
        STATE.orders["ord-g"] = Order(
            token_id="ord-g", username="alice", symbol="BTCUSDT",
            side="buy", price=50000.0, quantity=0.01, status="open",
        )

    def test_get_own_order(self) -> None:
        order = run(get_order("alice", "ord-g"))
        self.assertIsNotNone(order)
        self.assertEqual(order.token_id, "ord-g")

    def test_get_other_user_order_returns_none(self) -> None:
        order = run(get_order("bob", "ord-g"))
        self.assertIsNone(order)

    def test_get_nonexistent_order_returns_none(self) -> None:
        order = run(get_order("alice", "nope"))
        self.assertIsNone(order)


if __name__ == "__main__":
    unittest.main()
