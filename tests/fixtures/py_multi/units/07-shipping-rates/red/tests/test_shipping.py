import pytest
from shop.shipping import shipping_cost


@pytest.mark.parametrize("grams,cents", [(100, 300), (1000, 500), (5000, 900)])
def test_bands(grams: int, cents: int):
    assert shipping_cost(grams) == cents


def test_negative_weight_is_rejected():
    with pytest.raises(ValueError):
        shipping_cost(-1)
