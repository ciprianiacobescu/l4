def reorder_quantity(on_hand: int, target: int) -> int:
    return max(target - on_hand, 0)
