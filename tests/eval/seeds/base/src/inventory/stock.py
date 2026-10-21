"""Stock helpers of the eval base project."""


def units_short(on_hand: int, wanted: int) -> int:
    """How many units are missing to serve `wanted` from `on_hand`."""
    return max(wanted - on_hand, 0)
