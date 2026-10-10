"""Prices in cents."""


def unit_price(base_cents: int, qty: int) -> int:
    if qty < 1:
        raise ValueError("qty must be at least 1")
    return base_cents * qty


CODES = {"SAVE10": 10}


def apply_discount(amount: int, code: str) -> int:
    if code not in CODES:
        raise ValueError("unknown discount code")
    return amount - amount * CODES[code] // 100


def bulk_price(base_cents: int, qty: int) -> int:
    total = unit_price(base_cents, qty)
    return total - total * 5 // 100 if qty >= 10 else total
