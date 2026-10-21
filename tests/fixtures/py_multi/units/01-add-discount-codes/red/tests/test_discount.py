import pytest
from shop.pricing import apply_discount


def test_save10_takes_ten_percent():
    assert apply_discount(1000, "SAVE10") == 900


def test_unknown_code_is_rejected():
    with pytest.raises(ValueError):
        apply_discount(1000, "NOPE")
