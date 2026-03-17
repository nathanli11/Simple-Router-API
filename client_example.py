import asyncio
import json
import time

import requests
import websockets

BASE_URL = "http://127.0.0.1:8000"
WS_URL = "ws://127.0.0.1:8000/ws"

USERNAME = "demo_user"
PASSWORD = "demo_pass_123"


def register_or_login():
    """Inscrit un utilisateur ou fait un login si deja present."""
    resp = requests.post(f"{BASE_URL}/register", json={"username": USERNAME, "password": PASSWORD})
    if resp.status_code == 200:
        return resp.json()["access_token"]
    resp = requests.post(f"{BASE_URL}/login", json={"username": USERNAME, "password": PASSWORD})
    resp.raise_for_status()
    return resp.json()["access_token"]


def demo_rest(token: str) -> str:
    """Demonstre deposit, orders, cancel, status et balance."""
    headers = {"Authorization": f"Bearer {token}"}

    # Depot de fonds
    print("--- Deposit ---")
    r = requests.post(f"{BASE_URL}/deposit", json={"asset": "USDT", "amount": 10000}, headers=headers)
    print("deposit USDT", r.status_code, r.text)
    r = requests.post(f"{BASE_URL}/deposit", json={"asset": "BTC", "amount": 1}, headers=headers)
    print("deposit BTC", r.status_code, r.text)

    # Consulter les soldes
    print("\n--- Balance ---")
    r = requests.get(f"{BASE_URL}/balance", headers=headers)
    print("balance", r.status_code, r.text)

    # Placer un ordre
    print("\n--- Place order ---")
    order_id = f"ord-{int(time.time())}"
    order = {
        "token_id": order_id,
        "symbol": "BTCUSDT",
        "side": "buy",
        "price": 10000,
        "quantity": 0.1,
    }
    r = requests.post(f"{BASE_URL}/orders", json=order, headers=headers)
    print("order submit", r.status_code, r.text)

    # Verifier le statut de l'ordre
    print("\n--- Order status ---")
    r = requests.get(f"{BASE_URL}/orders/{order_id}", headers=headers)
    print("order status", r.status_code, r.text)

    # Annuler l'ordre
    print("\n--- Cancel order ---")
    r = requests.delete(f"{BASE_URL}/orders/{order_id}", headers=headers)
    print("cancel", r.status_code, r.text)

    # Re-verifier le statut apres annulation
    print("\n--- Order status after cancel ---")
    r = requests.get(f"{BASE_URL}/orders/{order_id}", headers=headers)
    print("order status", r.status_code, r.text)

    # Verifier les soldes apres annulation (fonds liberes)
    print("\n--- Balance after cancel ---")
    r = requests.get(f"{BASE_URL}/balance", headers=headers)
    print("balance", r.status_code, r.text)

    # Placer un second ordre pour la demo WebSocket
    order_id2 = f"ord-{int(time.time())}-2"
    requests.post(f"{BASE_URL}/orders", json={
        "token_id": order_id2, "symbol": "BTCUSDT",
        "side": "buy", "price": 10000, "quantity": 0.1,
    }, headers=headers)
    return order_id2


async def ws_demo(token: str):
    """Se connecte au WebSocket et souscrit a plusieurs streams."""
    async with websockets.connect(WS_URL) as ws:
        await ws.send(json.dumps({"action": "auth", "token": token}))
        print(await ws.recv())

        await ws.send(json.dumps({"action": "subscribe", "stream": "best_touch", "symbol": "BTCUSDT", "exchange": "all"}))
        await ws.send(json.dumps({"action": "subscribe", "stream": "trades", "symbol": "BTCUSDT", "exchange": "binance"}))
        await ws.send(json.dumps({"action": "subscribe", "stream": "klines", "symbol": "BTCUSDT", "exchange": "all", "interval": "1m"}))
        await ws.send(json.dumps({"action": "subscribe", "stream": "ewma", "symbol": "BTCUSDT", "exchange": "all", "half_life": 30}))

        for _ in range(8):
            msg = await ws.recv()
            print("ws", msg)


if __name__ == "__main__":
    token = register_or_login()
    print("\n===== REST API Demo =====")
    order_id = demo_rest(token)
    print("\n===== WebSocket Demo =====")
    asyncio.run(ws_demo(token))
