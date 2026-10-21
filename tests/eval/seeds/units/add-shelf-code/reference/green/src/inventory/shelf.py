def shelf_code(aisle: int, slot: int) -> str:
    if aisle < 1 or slot < 1:
        raise ValueError("aisle and slot must be at least 1")
    return f"A{aisle:02d}-S{slot:02d}"
