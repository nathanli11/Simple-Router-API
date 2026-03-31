"""Tests d'intégration pour les endpoints REST (app/main.py)."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.state import Balance, STATE, User
from app.auth import hash_password, create_access_token


def _reset_state() -> None:
    STATE.users.clear()
    STATE.balances.clear()
    STATE.orders.clear()
    STATE.open_orders_by_symbol.clear()
    STATE.best_touch.clear()
    STATE.last_trade.clear()


# Patch les tâches de fond au démarrage pour ne pas toucher aux exchanges réels
_patches = [
    patch("app.main.load_state", new_callable=AsyncMock),
    patch("app.main.save_state", new_callable=AsyncMock),
    patch("app.paper.save_state", new_callable=AsyncMock),
    patch("app.main.kline_tick_loop", new_callable=AsyncMock),
    patch("app.exchange.binance.run", new_callable=AsyncMock),
    patch("app.exchange.okx.run", new_callable=AsyncMock),
]

for p in _patches:
    p.start()

from app.main import app  # noqa: E402 – import après les patches

client = TestClient(app, raise_server_exceptions=True)


def _auth_header(username: str) -> dict:
    token = create_access_token(username)
    return {"Authorization": f"Bearer {token}"}


def _register_alice() -> None:
    """Inscrit alice directement dans le STATE (sans passer par l'API)."""
    STATE.users["alice"] = User(username="alice", password_hash=hash_password("password123"))
    STATE.balances["alice"] = {}


class TestRegister(unittest.TestCase):
    def setUp(self) -> None:
        _reset_state()

    def test_register_success(self) -> None:
        r = client.post("/register", json={"username": "newuser", "password": "pass1234"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("access_token", r.json())

    def test_register_duplicate_username(self) -> None:
        client.post("/register", json={"username": "dup", "password": "pass1234"})
        r = client.post("/register", json={"username": "dup", "password": "pass5678"})
        self.assertEqual(r.status_code, 400)

    def test_register_username_too_short(self) -> None:
        r = client.post("/register", json={"username": "ab", "password": "pass1234"})
        self.assertEqual(r.status_code, 422)

    def test_register_password_too_short(self) -> None:
        r = client.post("/register", json={"username": "validname", "password": "123"})
        self.assertEqual(r.status_code, 422)

    def test_register_missing_fields(self) -> None:
        r = client.post("/register", json={"username": "onlyuser"})
        self.assertEqual(r.status_code, 422)

    def test_register_empty_body(self) -> None:
        r = client.post("/register", json={})
        self.assertEqual(r.status_code, 422)


class TestLogin(unittest.TestCase):
    def setUp(self) -> None:
        _reset_state()
        _register_alice()

    def test_login_success(self) -> None:
        r = client.post("/login", json={"username": "alice", "password": "password123"})
        self.assertEqual(r.status_code, 200)
        self.assertIn("access_token", r.json())

    def test_login_wrong_password(self) -> None:
        r = client.post("/login", json={"username": "alice", "password": "wrong"})
        self.assertEqual(r.status_code, 401)

    def test_login_unknown_user(self) -> None:
        r = client.post("/login", json={"username": "ghost", "password": "pass"})
        self.assertEqual(r.status_code, 401)

    def test_login_missing_fields(self) -> None:
        r = client.post("/login", json={"username": "alice"})
        self.assertEqual(r.status_code, 422)


class TestInfo(unittest.TestCase):
    def test_info_returns_pairs_and_assets(self) -> None:
        r = client.get("/info")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("assets", data)
        self.assertIn("pairs", data)
        self.assertGreaterEqual(len(data["pairs"]), 5)
        self.assertIn("BTCUSDT", data["pairs"])

    def test_info_no_auth_required(self) -> None:
        r = client.get("/info")
        self.assertNotEqual(r.status_code, 401)


class TestDeposit(unittest.TestCase):
    def setUp(self) -> None:
        _reset_state()
        _register_alice()

    def test_deposit_valid_asset(self) -> None:
        r = client.post("/deposit", json={"asset": "USDT", "amount": 1000.0},
                        headers=_auth_header("alice"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "ok")

    def test_deposit_invalid_asset(self) -> None:
        r = client.post("/deposit", json={"asset": "DOGE", "amount": 100.0},
                        headers=_auth_header("alice"))
        self.assertEqual(r.status_code, 400)

    def test_deposit_zero_amount_rejected(self) -> None:
        r = client.post("/deposit", json={"asset": "USDT", "amount": 0},
                        headers=_auth_header("alice"))
        self.assertEqual(r.status_code, 422)

    def test_deposit_negative_amount_rejected(self) -> None:
        r = client.post("/deposit", json={"asset": "USDT", "amount": -100},
                        headers=_auth_header("alice"))
        self.assertEqual(r.status_code, 422)

    def test_deposit_without_auth(self) -> None:
        r = client.post("/deposit", json={"asset": "USDT", "amount": 100.0})
        self.assertIn(r.status_code, (401, 403))

    def test_deposit_invalid_token(self) -> None:
        r = client.post("/deposit", json={"asset": "USDT", "amount": 100.0},
                        headers={"Authorization": "Bearer invalid.token.here"})
        self.assertEqual(r.status_code, 401)


class TestBalance(unittest.TestCase):
    def setUp(self) -> None:
        _reset_state()
        _register_alice()
        STATE.balances["alice"]["USDT"] = Balance(total=1000.0, available=800.0)

    def test_balance_returns_all_assets(self) -> None:
        r = client.get("/balance", headers=_auth_header("alice"))
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn("balances", data)
        usdt = next((b for b in data["balances"] if b["asset"] == "USDT"), None)
        self.assertIsNotNone(usdt)
        self.assertAlmostEqual(usdt["total"], 1000.0)
        self.assertAlmostEqual(usdt["available"], 800.0)

    def test_balance_without_auth(self) -> None:
        r = client.get("/balance")
        self.assertIn(r.status_code, (401, 403))


class TestOrders(unittest.TestCase):
    def setUp(self) -> None:
        _reset_state()
        _register_alice()
        STATE.balances["alice"] = {
            "USDT": Balance(total=10000.0, available=10000.0),
            "BTC": Balance(total=1.0, available=1.0),
        }

    def test_place_limit_order_success(self) -> None:
        r = client.post("/orders", json={
            "token_id": "tok1", "symbol": "BTCUSDT",
            "side": "buy", "price": 50000.0, "quantity": 0.01,
        }, headers=_auth_header("alice"))
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["token_id"], "tok1")
        self.assertEqual(data["status"], "open")

    def test_place_order_unknown_symbol(self) -> None:
        r = client.post("/orders", json={
            "token_id": "tok2", "symbol": "DOGEUSDT",
            "side": "buy", "price": 1.0, "quantity": 100.0,
        }, headers=_auth_header("alice"))
        self.assertEqual(r.status_code, 400)

    def test_place_order_invalid_side(self) -> None:
        r = client.post("/orders", json={
            "token_id": "tok3", "symbol": "BTCUSDT",
            "side": "hold", "price": 50000.0, "quantity": 0.01,
        }, headers=_auth_header("alice"))
        self.assertEqual(r.status_code, 422)

    def test_place_order_zero_price_rejected(self) -> None:
        r = client.post("/orders", json={
            "token_id": "tok4", "symbol": "BTCUSDT",
            "side": "buy", "price": 0, "quantity": 0.01,
        }, headers=_auth_header("alice"))
        self.assertEqual(r.status_code, 422)

    def test_place_order_zero_quantity_rejected(self) -> None:
        r = client.post("/orders", json={
            "token_id": "tok5", "symbol": "BTCUSDT",
            "side": "buy", "price": 50000.0, "quantity": 0,
        }, headers=_auth_header("alice"))
        self.assertEqual(r.status_code, 422)

    def test_place_order_insufficient_balance(self) -> None:
        STATE.balances["alice"]["USDT"] = Balance(total=100.0, available=100.0)
        r = client.post("/orders", json={
            "token_id": "tok6", "symbol": "BTCUSDT",
            "side": "buy", "price": 50000.0, "quantity": 1.0,
        }, headers=_auth_header("alice"))
        self.assertEqual(r.status_code, 400)

    def test_place_order_duplicate_token_id(self) -> None:
        client.post("/orders", json={
            "token_id": "dup", "symbol": "BTCUSDT",
            "side": "buy", "price": 50000.0, "quantity": 0.01,
        }, headers=_auth_header("alice"))
        r = client.post("/orders", json={
            "token_id": "dup", "symbol": "BTCUSDT",
            "side": "buy", "price": 50000.0, "quantity": 0.001,
        }, headers=_auth_header("alice"))
        self.assertEqual(r.status_code, 400)

    def test_place_order_without_auth(self) -> None:
        r = client.post("/orders", json={
            "token_id": "tok7", "symbol": "BTCUSDT",
            "side": "buy", "price": 50000.0, "quantity": 0.01,
        })
        self.assertIn(r.status_code, (401, 403))

    def test_get_order_status(self) -> None:
        client.post("/orders", json={
            "token_id": "tok8", "symbol": "BTCUSDT",
            "side": "buy", "price": 50000.0, "quantity": 0.01,
        }, headers=_auth_header("alice"))
        r = client.get("/orders/tok8", headers=_auth_header("alice"))
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["token_id"], "tok8")
        self.assertEqual(data["status"], "open")

    def test_get_nonexistent_order(self) -> None:
        r = client.get("/orders/nope", headers=_auth_header("alice"))
        self.assertEqual(r.status_code, 404)

    def test_cancel_order(self) -> None:
        client.post("/orders", json={
            "token_id": "tok9", "symbol": "BTCUSDT",
            "side": "buy", "price": 50000.0, "quantity": 0.01,
        }, headers=_auth_header("alice"))
        r = client.delete("/orders/tok9", headers=_auth_header("alice"))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["status"], "cancelled")

    def test_cancel_nonexistent_order(self) -> None:
        r = client.delete("/orders/ghost", headers=_auth_header("alice"))
        self.assertEqual(r.status_code, 400)

    def test_cancel_already_cancelled_order(self) -> None:
        client.post("/orders", json={
            "token_id": "t10", "symbol": "BTCUSDT",
            "side": "buy", "price": 50000.0, "quantity": 0.01,
        }, headers=_auth_header("alice"))
        client.delete("/orders/t10", headers=_auth_header("alice"))
        r = client.delete("/orders/t10", headers=_auth_header("alice"))
        self.assertEqual(r.status_code, 400)

    def test_modify_order(self) -> None:
        client.post("/orders", json={
            "token_id": "t11", "symbol": "BTCUSDT",
            "side": "buy", "price": 50000.0, "quantity": 0.01,
        }, headers=_auth_header("alice"))
        r = client.put("/orders/t11", json={"price": 45000.0},
                       headers=_auth_header("alice"))
        self.assertEqual(r.status_code, 200)
        self.assertAlmostEqual(r.json()["price"], 45000.0)

    def test_modify_order_empty_body(self) -> None:
        client.post("/orders", json={
            "token_id": "t12", "symbol": "BTCUSDT",
            "side": "buy", "price": 50000.0, "quantity": 0.01,
        }, headers=_auth_header("alice"))
        r = client.put("/orders/t12", json={},
                       headers=_auth_header("alice"))
        self.assertEqual(r.status_code, 400)

    def test_missing_token_id_in_order(self) -> None:
        r = client.post("/orders", json={
            "symbol": "BTCUSDT", "side": "buy",
            "price": 50000.0, "quantity": 0.01,
        }, headers=_auth_header("alice"))
        self.assertEqual(r.status_code, 422)


if __name__ == "__main__":
    unittest.main()
