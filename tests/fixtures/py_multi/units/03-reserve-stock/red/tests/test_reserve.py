import pytest
from inventory.stock import Stock


def test_reserve_reduces_what_is_available():
    stock = Stock()
    stock.add("A1", 5)
    stock.reserve("A1", 3)
    assert stock.on_hand("A1") == 2


def test_cannot_reserve_more_than_on_hand():
    stock = Stock()
    stock.add("A1", 1)
    with pytest.raises(ValueError):
        stock.reserve("A1", 2)
