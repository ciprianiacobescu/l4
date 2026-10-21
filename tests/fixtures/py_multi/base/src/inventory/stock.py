"""Stock levels per SKU."""


class Stock:
    def __init__(self) -> None:
        self._levels: dict[str, int] = {}

    def add(self, sku: str, qty: int) -> None:
        self._levels[sku] = self._levels.get(sku, 0) + qty

    def on_hand(self, sku: str) -> int:
        return self._levels.get(sku, 0)
