from __future__ import annotations

import os
import ssl
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
    allow_insecure_ssl: bool = os.getenv("ALLOW_INSECURE_SSL", "false").lower() in {"1", "true", "yes", "on"}


SETTINGS = Settings()


def build_ssl_context() -> ssl.SSLContext:
    """Construit le SSL pour les connexions sortantes."""
    context = ssl.create_default_context()
    if SETTINGS.allow_insecure_ssl:
        # Reserve au developpement local quand un proxy reseau casse la chaine TLS.
        # En production, la verification SSL doit rester active.
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context


def split_symbol(symbol: str) -> tuple[str, str]:
    """Decoupe une paire en (base, quote)."""
    if symbol.endswith("USDT"):
        return symbol[:-4], "USDT"
    if symbol.endswith("USD"):
        return symbol[:-3], "USD"
    if symbol.endswith("USDC"):
        return symbol[:-4], "USDC"
    return symbol[:-3], symbol[-3:]
