from inventory.stock import Stock


def test_add_and_on_hand():
    stock = Stock()
    stock.add("A1", 5)
    stock.add("A1", 2)
    assert stock.on_hand("A1") == 7


def test_unknown_sku_is_zero():
    assert Stock().on_hand("nope") == 0
