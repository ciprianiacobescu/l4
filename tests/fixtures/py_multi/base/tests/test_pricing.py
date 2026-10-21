import pytest
from shop.pricing import unit_price


def test_unit_price_multiplies():
    assert unit_price(250, 3) == 750


def test_unit_price_rejects_zero_quantity():
    with pytest.raises(ValueError):
        unit_price(250, 0)
