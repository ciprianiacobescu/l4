from inventory.stock import Stock


def low_stock(stock: Stock, threshold: int) -> list[str]:
    return sorted(sku for sku in stock.skus() if stock.on_hand(sku) < threshold)
