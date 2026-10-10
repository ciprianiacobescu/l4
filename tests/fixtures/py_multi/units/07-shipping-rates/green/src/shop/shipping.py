def shipping_cost(grams: int) -> int:
    if grams < 0:
        raise ValueError("weight must not be negative")
    if grams <= 500:
        return 300
    if grams <= 2000:
        return 500
    return 900
