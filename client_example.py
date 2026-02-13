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


def place_sample_orders(token: str):
    """Depose des fonds et place un ordre limite de demo."""
    headers = {"Authorization": f"Bearer {token}"}
    requests.post(f"{BASE_URL}/deposit", json={"asset": "USDT", "amount": 10000}, headers=headers)
    requests.post(f"{BASE_URL}/deposit", json={"asset": "BTC", "amount": 1}, headers=headers)

    order = {
        "token_id": f"ord-{int(time.time())}",
        "symbol": "BTCUSDT",
        "side": "buy",
        "price": 10000,
        "quantity": 0.1,
    }
    resp = requests.post(f"{BASE_URL}/orders", json=order, headers=headers)
    print("order submit", resp.status_code, resp.text)
    return order["token_id"]


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
    order_id = place_sample_orders(token)
    print("order id", order_id)
    asyncio.run(ws_demo(token))
