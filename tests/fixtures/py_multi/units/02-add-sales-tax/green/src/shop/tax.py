def add_tax(amount: int, rate_bp: int) -> int:
    return amount + (amount * rate_bp + 5000) // 10000
