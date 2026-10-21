from shop.pricing import apply_discount, unit_price
from shop.tax import add_tax


def cart_total(lines: list[tuple[int, int]], code: str | None, rate_bp: int) -> int:
    subtotal = sum(unit_price(base, qty) for base, qty in lines)
    if code is not None:
        subtotal = apply_discount(subtotal, code)
    return add_tax(subtotal, rate_bp)
