from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Dict

from .state import Balance, Order, STATE, User
from .config import SETTINGS


_storage_lock = asyncio.Lock()


def _state_path() -> Path:
    """Retourne le chemin du fichier d'etat."""
    return Path(SETTINGS.storage_path)


def _ensure_dir(path: Path) -> None:
    """Cree les dossiers parents pour un chemin."""
    path.parent.mkdir(parents=True, exist_ok=True)


async def save_state() -> None:
    """Persiste utilisateurs, soldes et ordres sur disque."""
    async with _storage_lock:
        data = {
            "users": {u: {"password_hash": user.password_hash} for u, user in STATE.users.items()},
            "balances": {
                u: {asset: {"total": bal.total, "available": bal.available} for asset, bal in assets.items()}
                for u, assets in STATE.balances.items()
            },
            "orders": {
                tid: {
                    "token_id": o.token_id,
                    "username": o.username,
                    "symbol": o.symbol,
                    "side": o.side,
                    "price": o.price,
                    "quantity": o.quantity,
                    "status": o.status,
                    "filled_price": o.filled_price,
                    "reason": o.reason,
                    "reserved_amount": o.reserved_amount,
                    "created_at": o.created_at,
                }
                for tid, o in STATE.orders.items()
            },
            "open_orders_by_symbol": STATE.open_orders_by_symbol,
        }

        path = _state_path()
        _ensure_dir(path)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")


async def load_state() -> None:
    """Charge utilisateurs, soldes et ordres depuis le disque."""
    path = _state_path()
    if not path.exists():
        return

    raw = json.loads(path.read_text(encoding="utf-8"))

    STATE.users = {u: User(username=u, password_hash=v["password_hash"]) for u, v in raw.get("users", {}).items()}
    STATE.balances = {}
    for u, assets in raw.get("balances", {}).items():
        STATE.balances[u] = {asset: Balance(**vals) for asset, vals in assets.items()}

    STATE.orders = {}
    for tid, o in raw.get("orders", {}).items():
        STATE.orders[tid] = Order(**o)

    STATE.open_orders_by_symbol = raw.get("open_orders_by_symbol", {})
