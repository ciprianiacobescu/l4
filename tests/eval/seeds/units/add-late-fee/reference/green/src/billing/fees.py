def late_fee_cents(balance_cents: int, days_late: int) -> int:
    if days_late <= 5:
        return 0
    return 200
