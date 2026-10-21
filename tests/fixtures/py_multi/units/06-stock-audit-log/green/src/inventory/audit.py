class AuditLog:
    def __init__(self) -> None:
        self._entries: list[tuple[str, int]] = []

    def record(self, sku: str, delta: int) -> None:
        self._entries.append((sku, delta))

    def entries(self) -> list[tuple[str, int]]:
        return list(self._entries)
