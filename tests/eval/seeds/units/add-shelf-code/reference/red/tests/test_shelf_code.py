import pytest
from inventory.shelf import shelf_code


@pytest.mark.l4("C-7dc9fae5")
def test_the_code_is_zero_padded():
    assert shelf_code(3, 7) == "A03-S07"
    assert shelf_code(12, 34) == "A12-S34"


@pytest.mark.l4("C-fa2e5d61")
def test_an_aisle_below_one_is_rejected():
    with pytest.raises(ValueError):
        shelf_code(0, 7)
    with pytest.raises(ValueError):
        shelf_code(3, 0)
