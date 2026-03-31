from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


# Auth

class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, description="Nom d'utilisateur (3 caractères min)")
    password: str = Field(..., min_length=6, description="Mot de passe (6 caractères min)")


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"



# Deposit

class DepositRequest(BaseModel):
    asset: str = Field(..., description="Actif à créditer (ex: USDT, BTC)")
    amount: float = Field(..., gt=0, description="Montant à déposer (doit être > 0)")



# Orders

class OrderSide(str, Enum):
    buy = "buy"
    sell = "sell"


class OrderType(str, Enum):
    limit = "limit"
    market = "market"


class OrderRequest(BaseModel):
    token_id: str = Field(..., min_length=3, description="Identifiant unique de l'ordre (fourni par le client)")
    symbol: str = Field(..., description="Paire de trading")
    side: OrderSide = Field(..., description="Sens de l'ordre : buy ou sell")
    price: float = Field(..., gt=0, description="Prix limite")
    quantity: float = Field(..., gt=0, description="Quantité à trader")
    order_type: OrderType = Field(OrderType.limit, description="Type d'ordre : limit (défaut) ou market")


class OrderModifyRequest(BaseModel):
    """Corps pour PUT /orders/{token_id} – au moins un champ requis."""
    price: Optional[float] = Field(None, gt=0, description="Nouveau prix limite")
    quantity: Optional[float] = Field(None, gt=0, description="Nouvelle quantité")


class OrderStatus(str, Enum):
    open = "open"
    filled = "filled"
    cancelled = "cancelled"
    rejected = "rejected"


class OrderResponse(BaseModel):
    token_id: str
    status: OrderStatus
    filled_price: Optional[float] = None
    reason: Optional[str] = None


class OrderStatusResponse(BaseModel):
    token_id: str
    status: OrderStatus
    symbol: str
    side: OrderSide
    price: float
    quantity: float
    filled_price: Optional[float] = None
    reason: Optional[str] = None



# Balance

class BalanceLine(BaseModel):
    asset: str
    total: float
    available: float


class BalanceResponse(BaseModel):
    balances: List[BalanceLine]



# Info

class InfoResponse(BaseModel):
    assets: List[str]
    pairs: List[str]



# WebSocket evenements

class BestTouch(BaseModel):
    symbol: str
    best_bid: Optional[float]
    best_ask: Optional[float]
    best_bid_exchange: Optional[str]
    best_ask_exchange: Optional[str]


class TradeEvent(BaseModel):
    symbol: str
    exchange: str
    price: float
    quantity: float
    timestamp: float


class KlineEvent(BaseModel):
    symbol: str
    exchange: str
    interval: str
    start: float
    end: float
    open: float
    high: float
    low: float
    close: float
    volume: float


class EwmaEvent(BaseModel):
    symbol: str
    exchange: str
    half_life: float
    value: float
    timestamp: float
