"""Stock levels per SKU."""


class Stock:
    def __init__(self) -> None:
        self._levels: dict[str, int] = {}

    def add(self, sku: str, qty: int) -> None:
        self._levels[sku] = self._levels.get(sku, 0) + qty

    def on_hand(self, sku: str) -> int:
        return self._levels.get(sku, 0)

    def reserve(self, sku: str, qty: int) -> None:
        if qty > self.on_hand(sku):
            raise ValueError("not enough stock")
        self._levels[sku] -= qty

    def skus(self) -> list[str]:
        return list(self._levels)
