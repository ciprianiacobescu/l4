"""Prices in cents."""


def unit_price(base_cents: int, qty: int) -> int:
    if qty < 1:
        raise ValueError("qty must be at least 1")
    return base_cents * qty
