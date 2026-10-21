"""Money helpers of the eval base project."""


def to_cents(amount: str) -> int:
    """`"12.34"` is `1234`; the amount has exactly two decimals."""
    whole, _, frac = amount.partition(".")
    if len(frac) != 2 or not whole.lstrip("-").isdigit() or not frac.isdigit():
        raise ValueError("amount must look like 12.34")
    sign = -1 if whole.startswith("-") else 1
    return sign * (abs(int(whole)) * 100 + int(frac))
