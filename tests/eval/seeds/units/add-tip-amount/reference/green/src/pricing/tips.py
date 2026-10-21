def tip_cents(total_cents: int, percent: int) -> int:
    return (total_cents * percent + 50) // 100
