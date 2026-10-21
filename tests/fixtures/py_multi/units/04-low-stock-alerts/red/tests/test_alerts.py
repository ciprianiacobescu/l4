from inventory.alerts import low_stock
from inventory.stock import Stock


def test_lists_skus_below_threshold_sorted():
    stock = Stock()
    stock.add("B2", 1)
    stock.add("A1", 2)
    stock.add("C3", 50)
    assert low_stock(stock, 5) == ["A1", "B2"]


def test_empty_stock_has_no_alerts():
    assert low_stock(Stock(), 5) == []
