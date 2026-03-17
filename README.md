# Projet API – Market Data Router & Paper Trading

## Prérequis
- Python 3.10+
- Accès réseau (WebSocket vers Binance et OKX)

## Installation
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Lancer le serveur
```bash
uvicorn app.main:app --reload
```

Swagger: `http://127.0.0.1:8000/docs`

## Configuration
Les symboles et paramètres sont définis dans `app/config.py`:
- `symbols` (au moins 5 paires)
- `kline_intervals_seconds`
- `secret_key` (JWT)

## Endpoints REST
Public:
- `POST /register` – crée un utilisateur
- `POST /login` – retourne un JWT
- `GET /info` – assets et paires disponibles

Authentifiés (Bearer JWT):
- `POST /deposit` – déposer des fonds
- `POST /orders` – soumettre un ordre limite
- `GET /orders/{token_id}` – statut d’un ordre
- `DELETE /orders/{token_id}` – annuler un ordre
- `GET /balance` – soldes (total + disponible)

## WebSocket Client
Endpoint: `ws://127.0.0.1:8000/ws`

1. Authentification (premier message):
```json
{"action":"auth","token":"<JWT>"}
```

2. Souscriptions:
```json
{"action":"subscribe","stream":"best_touch","symbol":"BTCUSDT","exchange":"all"}
{"action":"subscribe","stream":"trades","symbol":"BTCUSDT","exchange":"binance"}
{"action":"subscribe","stream":"klines","symbol":"BTCUSDT","exchange":"all","interval":"1m"}
{"action":"subscribe","stream":"ewma","symbol":"BTCUSDT","exchange":"all","half_life":30}
```

Streams disponibles:
- `best_touch`
- `trades`
- `klines` (intervals: `1s`, `10s`, `1m`, `5m`)
- `ewma` (demande `half_life`)

## Exemple client
```bash
python3 client_example.py
```

## Persistance
L’état est enregistré dans `data/state.json` et rechargé au démarrage.

## Notes
- Les données de marché proviennent des WebSockets publiques Binance/OKX.
- Les klines et EWMA sont calculés uniquement à partir des flux WebSocket.
