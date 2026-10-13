import os


def _require_non_negative(on_hand: int) -> None:
    if on_hand < 0:
        raise ValueError(f"on_hand must be non-negative, got {on_hand}")


def _get_threshold() -> int:
    return int(os.environ.get("LOW_STOCK_THRESHOLD", "5"))


def low_stock_message(name: str, on_hand: int) -> str | None:
    _require_non_negative(on_hand)
    if on_hand < _get_threshold():
        return f"Restock {name}: {on_hand} left"
    return None
