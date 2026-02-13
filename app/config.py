from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class Settings:
    """Configuration statique du serveur API."""
    secret_key: str = "CHANGE_ME_DEV_SECRET"
    jwt_algorithm: str = "HS256"
    jwt_exp_minutes: int = 60 * 24

    exchanges: List[str] = ("binance", "okx")
    symbols: List[str] = (
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
        "ADAUSDT",
        "XRPUSDT",
    )

    kline_intervals_seconds: List[int] = (1, 10, 60, 300)

    storage_path: str = "data/state.json"


SETTINGS = Settings()


def split_symbol(symbol: str) -> tuple[str, str]:
    """Decoupe une paire en (base, quote)."""
    if symbol.endswith("USDT"):
        return symbol[:-4], "USDT"
    if symbol.endswith("USD"):
        return symbol[:-3], "USD"
    if symbol.endswith("USDC"):
        return symbol[:-4], "USDC"
    return symbol[:-3], symbol[-3:]
