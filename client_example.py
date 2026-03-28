"""
client_example.py – Démonstration complète de l'API Market Data Router.

Couvre :
  - Inscription / connexion
  - Dépôt de fonds
  - Ordres limites (place, status, cancel)
  - Ordre market (bonus)
  - Modification d'ordre (PUT, bonus)
  - Consultation des soldes
  - WebSocket : best_touch, trades, klines, ewma
  - Cas d'erreurs (requêtes malformées)
  - Ping WebSocket

Usage :
  python3 client_example.py
"""

import asyncio
import json
import time

import requests
import websockets

BASE_URL = "http://127.0.0.1:8000"
WS_URL   = "ws://127.0.0.1:8000/ws"

USERNAME = "demo_user"
PASSWORD = "demo_pass_123"


# ---------------------------------------------------------------------------
# Authentification
# ---------------------------------------------------------------------------

def register_or_login() -> str:
    """Inscrit un utilisateur ou fait un login s'il existe déjà."""
    resp = requests.post(f"{BASE_URL}/register", json={"username": USERNAME, "password": PASSWORD})
    if resp.status_code == 200:
        print("[register] Compte créé")
        return resp.json()["access_token"]
    resp = requests.post(f"{BASE_URL}/login", json={"username": USERNAME, "password": PASSWORD})
    resp.raise_for_status()
    print("[login] Connecté")
    return resp.json()["access_token"]


def header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Demo REST complète
# ---------------------------------------------------------------------------

def demo_rest(token: str) -> str:
    """Démontre toutes les routes REST et retourne un token_id pour la démo WS."""
    h = header(token)

    # --- Info ---
    print("\n=== GET /info ===")
    r = requests.get(f"{BASE_URL}/info")
    print(r.status_code, r.json())

    # --- Dépôts ---
    print("\n=== POST /deposit ===")
    r = requests.post(f"{BASE_URL}/deposit", json={"asset": "USDT", "amount": 50000}, headers=h)
    print("USDT:", r.status_code, r.json())
    r = requests.post(f"{BASE_URL}/deposit", json={"asset": "BTC",  "amount": 2},     headers=h)
    print("BTC: ", r.status_code, r.json())
    r = requests.post(f"{BASE_URL}/deposit", json={"asset": "ETH",  "amount": 10},    headers=h)
    print("ETH: ", r.status_code, r.json())

    # --- Actif invalide ---
    print("\n=== Dépôt actif invalide (doit renvoyer 400) ===")
    r = requests.post(f"{BASE_URL}/deposit", json={"asset": "INVALID", "amount": 100}, headers=h)
    print(r.status_code, r.json())

    # --- Solde initial ---
    print("\n=== GET /balance ===")
    r = requests.get(f"{BASE_URL}/balance", headers=h)
    print(r.status_code, r.json())

    # --- Ordre limite ---
    print("\n=== POST /orders (limit) ===")
    order_id = f"ord-limit-{int(time.time())}"
    r = requests.post(f"{BASE_URL}/orders", json={
        "token_id": order_id,
        "symbol":   "BTCUSDT",
        "side":     "buy",
        "price":    10000,
        "quantity": 0.5,
        "order_type": "limit",
    }, headers=h)
    print("Ordre limit:", r.status_code, r.json())

    # --- Statut ---
    print("\n=== GET /orders/{token_id} ===")
    r = requests.get(f"{BASE_URL}/orders/{order_id}", headers=h)
    print(r.status_code, r.json())

    # --- Modification (bonus PUT) ---
    print("\n=== PUT /orders/{token_id} (modifier le prix) ===")
    r = requests.put(f"{BASE_URL}/orders/{order_id}", json={"price": 9500}, headers=h)
    print(r.status_code, r.json())

    # --- Solde après modification (fonds réservés ajustés) ---
    print("\n=== /balance après modification ===")
    r = requests.get(f"{BASE_URL}/balance", headers=h)
    print(r.status_code, r.json())

    # --- Annulation ---
    print("\n=== DELETE /orders/{token_id} ===")
    r = requests.delete(f"{BASE_URL}/orders/{order_id}", headers=h)
    print(r.status_code, r.json())

    # --- Solde après annulation (fonds libérés) ---
    print("\n=== /balance après annulation ===")
    r = requests.get(f"{BASE_URL}/balance", headers=h)
    print(r.status_code, r.json())

    # --- Annulation d'un ordre déjà annulé (doit renvoyer 400) ---
    print("\n=== Annuler un ordre déjà annulé (doit renvoyer 400) ===")
    r = requests.delete(f"{BASE_URL}/orders/{order_id}", headers=h)
    print(r.status_code, r.json())

    # --- Ordre market (bonus) ---
    print("\n=== POST /orders (market) ===")
    market_id = f"ord-market-{int(time.time())}"
    r = requests.post(f"{BASE_URL}/orders", json={
        "token_id":   market_id,
        "symbol":     "BTCUSDT",
        "side":       "sell",
        "price":      1,       # ignoré pour les orders market
        "quantity":   0.01,
        "order_type": "market",
    }, headers=h)
    print("Ordre market:", r.status_code, r.json())

    # --- Ordre avec solde insuffisant (doit renvoyer 400) ---
    print("\n=== Ordre avec solde insuffisant (doit renvoyer 400) ===")
    r = requests.post(f"{BASE_URL}/orders", json={
        "token_id": f"ord-fail-{int(time.time())}",
        "symbol":   "BTCUSDT",
        "side":     "buy",
        "price":    999999,
        "quantity": 999,
        "order_type": "limit",
    }, headers=h)
    print(r.status_code, r.json())

    # --- token_id dupliqué (doit renvoyer 400) ---
    dup_id = f"ord-dup-{int(time.time())}"
    requests.post(f"{BASE_URL}/orders", json={
        "token_id": dup_id, "symbol": "ETHUSDT",
        "side": "buy", "price": 1000, "quantity": 0.1,
    }, headers=h)
    print("\n=== token_id dupliqué (doit renvoyer 400) ===")
    r = requests.post(f"{BASE_URL}/orders", json={
        "token_id": dup_id, "symbol": "ETHUSDT",
        "side": "buy", "price": 1000, "quantity": 0.1,
    }, headers=h)
    print(r.status_code, r.json())

    # Crée un ordre ouvert pour la démo WebSocket (prix très bas → ne se remplit pas)
    ws_order_id = f"ord-ws-{int(time.time())}"
    requests.post(f"{BASE_URL}/orders", json={
        "token_id": ws_order_id, "symbol": "BTCUSDT",
        "side": "buy", "price": 1000, "quantity": 0.01,
    }, headers=h)
    return ws_order_id


# ---------------------------------------------------------------------------
# Demo WebSocket complète
# ---------------------------------------------------------------------------

async def ws_demo(token: str):
    """
    Se connecte au WebSocket, souscrit à tous les streams,
    teste les erreurs (JSON malformé, action inconnue, subscribe invalide),
    et affiche les événements reçus.
    """
    async with websockets.connect(WS_URL) as ws:

        # --- Auth ---
        print("\n=== WS auth ===")
        await ws.send(json.dumps({"action": "auth", "token": token}))
        print("auth →", await ws.recv())

        # --- Ping ---
        print("\n=== WS ping ===")
        await ws.send(json.dumps({"action": "ping"}))
        print("ping →", await ws.recv())

        # --- JSON malformé (doit recevoir une erreur, pas crasher) ---
        print("\n=== WS JSON malformé ===")
        await ws.send("ceci n'est pas du JSON{{{")
        print("malformed →", await ws.recv())

        # --- Action inconnue ---
        print("\n=== WS action inconnue ===")
        await ws.send(json.dumps({"action": "teleporter"}))
        print("unknown action →", await ws.recv())

        # --- Subscribe avec stream invalide ---
        print("\n=== WS subscribe stream invalide ===")
        await ws.send(json.dumps({"action": "subscribe", "stream": "nonexistent", "symbol": "BTCUSDT"}))
        print("bad stream →", await ws.recv())

        # --- Subscribe sans symbol ---
        print("\n=== WS subscribe sans symbol ===")
        await ws.send(json.dumps({"action": "subscribe", "stream": "trades"}))
        print("no symbol →", await ws.recv())

        # --- Unsubscribe sans champs requis ---
        print("\n=== WS unsubscribe invalide ===")
        await ws.send(json.dumps({"action": "unsubscribe"}))
        print("bad unsubscribe →", await ws.recv())

        # --- Souscriptions valides ---
        print("\n=== WS souscriptions valides ===")
        subs = [
            {"action": "subscribe", "stream": "best_touch", "symbol": "BTCUSDT", "exchange": "all"},
            {"action": "subscribe", "stream": "best_touch", "symbol": "BTCUSDT", "exchange": "binance"},
            {"action": "subscribe", "stream": "best_touch", "symbol": "BTCUSDT", "exchange": "okx"},
            {"action": "subscribe", "stream": "trades",     "symbol": "BTCUSDT", "exchange": "binance"},
            {"action": "subscribe", "stream": "trades",     "symbol": "ETHUSDT", "exchange": "all"},
            {"action": "subscribe", "stream": "klines",     "symbol": "BTCUSDT", "exchange": "all",    "interval": "1s"},
            {"action": "subscribe", "stream": "klines",     "symbol": "BTCUSDT", "exchange": "all",    "interval": "1m"},
            {"action": "subscribe", "stream": "ewma",       "symbol": "BTCUSDT", "exchange": "all",    "half_life": 30},
            {"action": "subscribe", "stream": "ewma",       "symbol": "SOLUSDT", "exchange": "all",    "half_life": 10},
        ]
        for s in subs:
            await ws.send(json.dumps(s))
            print("sub →", await ws.recv())

        # --- Lecture d'événements de marché ---
        print("\n=== WS événements de marché (20 messages) ===")
        received = {"best_touch": 0, "trades": 0, "klines": 0, "ewma": 0}
        for _ in range(20):
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=5.0)
                data = json.loads(raw)
                t = data.get("type", "?")
                received[t] = received.get(t, 0) + 1
                print(f"  [{t}]", json.dumps(data.get("data", {}))[:120])
            except asyncio.TimeoutError:
                print("  (timeout – aucun message reçu)")
                break

        print("\nRécapitulatif types reçus :", received)

        # --- Unsubscribe ---
        print("\n=== WS unsubscribe best_touch BTCUSDT ===")
        await ws.send(json.dumps({"action": "unsubscribe", "stream": "best_touch", "symbol": "BTCUSDT"}))
        print("unsubscribe →", await ws.recv())


# ---------------------------------------------------------------------------
# Test d'authentification WS invalide
# ---------------------------------------------------------------------------

async def ws_auth_error_demo():
    """Vérifie que le serveur refuse les tokens invalides proprement."""
    print("\n=== WS token invalide ===")
    async with websockets.connect(WS_URL) as ws:
        await ws.send(json.dumps({"action": "auth", "token": "fake.token.here"}))
        print("bad token →", await ws.recv())


# ---------------------------------------------------------------------------
# Point d'entrée
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("Market Data Router – Demo Client")
    print("=" * 60)

    token = register_or_login()

    print("\n" + "=" * 60)
    print("REST API Demo")
    print("=" * 60)
    demo_rest(token)

    print("\n" + "=" * 60)
    print("WebSocket Demo")
    print("=" * 60)
    asyncio.run(ws_demo(token))
    asyncio.run(ws_auth_error_demo())

    print("\nDémo terminée.")
