from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .models import OrderStatus


@dataclass
class Order:
    """Representation d'un ordre en memoire."""
    token_id: str
    username: str
    symbol: str
    side: str
    price: float
    quantity: float
    status: str = OrderStatus.open.value
    filled_price: Optional[float] = None
    reason: Optional[str] = None
    reserved_amount: float = 0.0
    created_at: float = 0.0


@dataclass
class Balance:
    """Solde d'un compte pour un seul actif."""
    total: float = 0.0
    available: float = 0.0


@dataclass
class User:
    """Enregistrement utilisateur avec mot de passe hashe."""
    username: str
    password_hash: str


@dataclass
class MarketState:
    """Snapshot best touch pour un symbole/exchange."""
    best_bid: Optional[float] = None
    best_ask: Optional[float] = None
    exchange: str = ""
    timestamp: float = 0.0


@dataclass
class AppState:
    """Etat global de l'application en memoire."""
    users: Dict[str, User] = field(default_factory=dict)
    balances: Dict[str, Dict[str, Balance]] = field(default_factory=dict)
    orders: Dict[str, Order] = field(default_factory=dict)
    open_orders_by_symbol: Dict[str, List[str]] = field(default_factory=dict)

    best_touch: Dict[str, Dict[str, MarketState]] = field(default_factory=dict)
    last_trade: Dict[str, Dict[str, float]] = field(default_factory=dict)

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


STATE = AppState()
