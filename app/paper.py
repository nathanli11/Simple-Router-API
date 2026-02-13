from __future__ import annotations

import time
from typing import Optional, Tuple

from .config import split_symbol
from .state import Balance, Order, STATE
from .storage import save_state


def _get_balance(username: str, asset: str) -> Balance:
    """Retourne (et cree si besoin) un solde."""
    user_bal = STATE.balances.setdefault(username, {})
    return user_bal.setdefault(asset, Balance())


def _reserve_for_order(username: str, side: str, symbol: str, price: float, qty: float) -> Tuple[bool, float, str]:
    """Reserve les fonds pour un ordre limite."""
    base, quote = split_symbol(symbol)
    if side == "buy":
        cost = price * qty
        bal = _get_balance(username, quote)
        if bal.available < cost:
            return False, 0.0, f"insufficient {quote} balance"
        bal.available -= cost
        return True, cost, ""
    else:
        bal = _get_balance(username, base)
        if bal.available < qty:
            return False, 0.0, f"insufficient {base} balance"
        bal.available -= qty
        return True, qty, ""


def _release_reserve(username: str, side: str, symbol: str, reserved: float) -> None:
    """Libere les fonds reserves dans le disponible."""
    base, quote = split_symbol(symbol)
    if side == "buy":
        bal = _get_balance(username, quote)
        bal.available += reserved
    else:
        bal = _get_balance(username, base)
        bal.available += reserved


def _apply_fill(username: str, side: str, symbol: str, price: float, qty: float, reserved: float) -> None:
    """Applique l'execution aux soldes."""
    base, quote = split_symbol(symbol)
    if side == "buy":
        quote_bal = _get_balance(username, quote)
        base_bal = _get_balance(username, base)
        cost = price * qty
        quote_bal.total -= cost
        base_bal.total += qty
        base_bal.available += qty
        # release any extra reserved due to better price
        if reserved > cost:
            quote_bal.available += (reserved - cost)
    else:
        base_bal = _get_balance(username, base)
        quote_bal = _get_balance(username, quote)
        base_bal.total -= qty
        quote_bal.total += price * qty
        quote_bal.available += price * qty


async def deposit(username: str, asset: str, amount: float) -> None:
    """Credite un depot sur le compte."""
    async with STATE.lock:
        bal = _get_balance(username, asset)
        bal.total += amount
        bal.available += amount
    await save_state()


async def place_order(username: str, token_id: str, symbol: str, side: str, price: float, qty: float) -> Tuple[bool, Optional[Order], str]:
    """Cree un ordre limite si les soldes le permettent."""
    async with STATE.lock:
        if token_id in STATE.orders:
            return False, None, "token_id already exists"

        ok, reserved, reason = _reserve_for_order(username, side, symbol, price, qty)
        if not ok:
            return False, None, reason

        order = Order(
            token_id=token_id,
            username=username,
            symbol=symbol,
            side=side,
            price=price,
            quantity=qty,
            reserved_amount=reserved,
            created_at=time.time(),
        )
        STATE.orders[token_id] = order
        STATE.open_orders_by_symbol.setdefault(symbol, []).append(token_id)

    await save_state()
    return True, order, ""


async def cancel_order(username: str, token_id: str) -> Tuple[bool, str]:
    """Annule un ordre ouvert et libere les fonds reserves."""
    async with STATE.lock:
        order = STATE.orders.get(token_id)
        if not order or order.username != username:
            return False, "order not found"
        if order.status != "open":
            return False, "order is not open"

        order.status = "cancelled"
        _release_reserve(username, order.side, order.symbol, order.reserved_amount)
        if order.symbol in STATE.open_orders_by_symbol:
            STATE.open_orders_by_symbol[order.symbol] = [
                tid for tid in STATE.open_orders_by_symbol[order.symbol] if tid != token_id
            ]

    await save_state()
    return True, ""


async def get_order(username: str, token_id: str) -> Optional[Order]:
    """Retourne un ordre s'il appartient a l'utilisateur."""
    async with STATE.lock:
        order = STATE.orders.get(token_id)
        if not order or order.username != username:
            return None
        return order


async def execute_on_best_touch(symbol: str, best_bid: Optional[float], best_ask: Optional[float]) -> None:
    """Execute les ordres dont le prix croise le best touch."""
    if best_bid is None and best_ask is None:
        return
    async with STATE.lock:
        order_ids = list(STATE.open_orders_by_symbol.get(symbol, []))

    for token_id in order_ids:
        async with STATE.lock:
            order = STATE.orders.get(token_id)
            if not order or order.status != "open":
                continue
            fill_price = None
            if order.side == "buy" and best_ask is not None and best_ask <= order.price:
                fill_price = best_ask
            if order.side == "sell" and best_bid is not None and best_bid >= order.price:
                fill_price = best_bid
            if fill_price is None:
                continue

            order.status = "filled"
            order.filled_price = fill_price
            _apply_fill(order.username, order.side, order.symbol, fill_price, order.quantity, order.reserved_amount)
            if order.symbol in STATE.open_orders_by_symbol:
                STATE.open_orders_by_symbol[order.symbol] = [
                    tid for tid in STATE.open_orders_by_symbol[order.symbol] if tid != token_id
                ]

        await save_state()
