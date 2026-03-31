from __future__ import annotations

import time
from typing import Optional, Tuple

from .config import split_symbol
from .state import Balance, Order, STATE
from .storage import save_state



# outils


def _get_balance(username: str, asset: str) -> Balance:
    """Retourne (et cree si besoin) un solde."""
    return STATE.balances.setdefault(username, {}).setdefault(asset, Balance())


def _reserve_for_order(
    username: str, side: str, symbol: str, price: float, qty: float
) -> Tuple[bool, float, str]:
    """Reserve les fonds pour un ordre limite."""
    base, quote = split_symbol(symbol)
    if side == "buy":
        cost = price * qty
        bal = _get_balance(username, quote)
        if bal.available < cost:
            return False, 0.0, f"Solde {quote} insuffisant (disponible: {bal.available:.6f}, requis: {cost:.6f})"
        bal.available -= cost
        return True, cost, ""
    else:
        bal = _get_balance(username, base)
        if bal.available < qty:
            return False, 0.0, f"Solde {base} insuffisant (disponible: {bal.available:.6f}, requis: {qty:.6f})"
        bal.available -= qty
        return True, qty, ""


def _release_reserve(username: str, side: str, symbol: str, reserved: float) -> None:
    """Libere les fonds dispo."""
    base, quote = split_symbol(symbol)
    asset = quote if side == "buy" else base
    _get_balance(username, asset).available += reserved


def _apply_fill(
    username: str, side: str, symbol: str,
    price: float, qty: float, reserved: float,
) -> None:
    """Applique l'execution aux soldes total et disponible."""
    base, quote = split_symbol(symbol)
    if side == "buy":
        cost = price * qty
        _get_balance(username, quote).total -= cost
        base_bal = _get_balance(username, base)
        base_bal.total += qty
        base_bal.available += qty
        # Rend l'excedent si execution a meilleur prix
        if reserved > cost:
            _get_balance(username, quote).available += (reserved - cost)
    else:
        _get_balance(username, base).total -= qty
        quote_bal = _get_balance(username, quote)
        quote_bal.total += price * qty
        quote_bal.available += price * qty


def _best_touch_price(symbol: str, side: str) -> Optional[float]:
    """Retourne le prix courant du best touch pour execution market."""
    per_symbol = STATE.best_touch.get(symbol, {})
    if not per_symbol:
        return None
    if side == "buy":
        asks = [st.best_ask for st in per_symbol.values() if st.best_ask]
        return min(asks) if asks else None
    else:
        bids = [st.best_bid for st in per_symbol.values() if st.best_bid]
        return max(bids) if bids else None



# API publique

async def deposit(username: str, asset: str, amount: float) -> None:
    """Credite un depot sur le compte."""
    async with STATE.lock:
        bal = _get_balance(username, asset)
        bal.total += amount
        bal.available += amount
    await save_state()


async def place_order(
    username: str,
    token_id: str,
    symbol: str,
    side: str,
    price: float,
    qty: float,
    order_type: str = "limit",
) -> Tuple[bool, Optional[Order], str]:
    """
    Cree un ordre limite ou market.

    - **limit** : reserve les fonds et attend l'execution.
    - **market** : execute immediatement au best touch disponible.
    """
    async with STATE.lock:
        if token_id in STATE.orders:
            return False, None, "token_id deja utilise"

        if order_type == "market":
            fill_price = _best_touch_price(symbol, side)
            if fill_price is None:
                return False, None, "Aucun prix de marche disponible pour l'execution immediate"

            # Pour un market order on verifie les soldes mais on ne reserve rien
            base, quote = split_symbol(symbol)
            if side == "buy":
                cost = fill_price * qty
                bal = _get_balance(username, quote)
                if bal.available < cost:
                    return False, None, f"Solde {quote} insuffisant"
                bal.available -= cost
            else:
                bal = _get_balance(username, base)
                if bal.available < qty:
                    return False, None, f"Solde {base} insuffisant"
                bal.available -= qty

            order = Order(
                token_id=token_id,
                username=username,
                symbol=symbol,
                side=side,
                price=fill_price,
                quantity=qty,
                reserved_amount=0.0,
                created_at=time.time(),
                status="filled",
                filled_price=fill_price,
                order_type="market",
            )
            _apply_fill(username, side, symbol, fill_price, qty, 0.0)
            STATE.orders[token_id] = order

        else:
            # Ordre limite classique
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
                order_type="limit",
            )
            STATE.orders[token_id] = order
            STATE.open_orders_by_symbol.setdefault(symbol, []).append(token_id)

    await save_state()
    return True, order, ""


async def cancel_order(username: str, token_id: str) -> Tuple[bool, str]:
    """Annule un ordre ouvert et libere les fonds."""
    async with STATE.lock:
        order = STATE.orders.get(token_id)
        if not order or order.username != username:
            return False, "Ordre introuvable"
        if order.status != "open":
            return False, f"Impossible d'annuler un ordre au statut '{order.status}'"

        order.status = "cancelled"
        _release_reserve(username, order.side, order.symbol, order.reserved_amount)
        STATE.open_orders_by_symbol[order.symbol] = [
            tid for tid in STATE.open_orders_by_symbol.get(order.symbol, [])
            if tid != token_id
        ]

    await save_state()
    return True, ""


async def modify_order(
    username: str,
    token_id: str,
    new_price: Optional[float],
    new_quantity: Optional[float],
) -> Tuple[bool, Optional[Order], str]:
    """
    Modifie le prix et/ou la quantite d'un ordre ouvert.

    Les fonds reserves sont recalcules : 
    - si la modification necessite plus de fonds, on verifie la disponibilite 
    - si elle en necessite moins, on libere l'excedent.
    """
    if new_price is None and new_quantity is None:
        return False, None, "Au moins un champ (price ou quantity) doit etre fourni"

    async with STATE.lock:
        order = STATE.orders.get(token_id)
        if not order or order.username != username:
            return False, None, "Ordre introuvable"
        if order.status != "open":
            return False, None, f"Impossible de modifier un ordre au statut '{order.status}'"

        target_price = new_price if new_price is not None else order.price
        target_qty = new_quantity if new_quantity is not None else order.quantity

        base, quote = split_symbol(order.symbol)
        if order.side == "buy":
            new_cost = target_price * target_qty
            old_cost = order.reserved_amount
            delta = new_cost - old_cost
            bal = _get_balance(username, quote)
            if delta > 0 and bal.available < delta:
                return False, None, f"Solde {quote} insuffisant pour la modification"
            bal.available -= delta
            order.reserved_amount = new_cost
        else:
            old_qty = order.reserved_amount
            delta = target_qty - old_qty
            bal = _get_balance(username, base)
            if delta > 0 and bal.available < delta:
                return False, None, f"Solde {base} insuffisant pour la modification"
            bal.available -= delta
            order.reserved_amount = target_qty

        order.price = target_price
        order.quantity = target_qty

    await save_state()
    return True, order, ""


async def get_order(username: str, token_id: str) -> Optional[Order]:
    """Retourne un ordre s'il appartient a l'utilisateur."""
    async with STATE.lock:
        order = STATE.orders.get(token_id)
        if not order or order.username != username:
            return None
        return order


async def execute_on_best_touch(
    symbol: str,
    best_bid: Optional[float],
    best_ask: Optional[float],
) -> None:
    """Execute les ordres limites dont le prix croise le best touch."""
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
            STATE.open_orders_by_symbol[order.symbol] = [
                tid for tid in STATE.open_orders_by_symbol.get(order.symbol, [])
                if tid != token_id
            ]

        await save_state()
