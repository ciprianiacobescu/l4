from inventory.stock import units_short


def test_units_short():
    assert units_short(3, 5) == 2
    assert units_short(9, 5) == 0
