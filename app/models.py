from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=3)
    password: str = Field(..., min_length=6)


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class DepositRequest(BaseModel):
    asset: str
    amount: float = Field(..., gt=0)


class OrderSide(str, Enum):
    buy = "buy"
    sell = "sell"


class OrderRequest(BaseModel):
    token_id: str = Field(..., min_length=3)
    symbol: str
    side: OrderSide
    price: float = Field(..., gt=0)
    quantity: float = Field(..., gt=0)


class OrderStatus(str, Enum):
    open = "open"
    filled = "filled"
    cancelled = "cancelled"
    rejected = "rejected"


class OrderResponse(BaseModel):
    token_id: str
    status: OrderStatus
    reason: Optional[str] = None


class BalanceLine(BaseModel):
    asset: str
    total: float
    available: float


class BalanceResponse(BaseModel):
    balances: List[BalanceLine]


class InfoResponse(BaseModel):
    assets: List[str]
    pairs: List[str]


class OrderStatusResponse(BaseModel):
    token_id: str
    status: OrderStatus
    symbol: str
    side: OrderSide
    price: float
    quantity: float
    filled_price: Optional[float] = None
    reason: Optional[str] = None


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
