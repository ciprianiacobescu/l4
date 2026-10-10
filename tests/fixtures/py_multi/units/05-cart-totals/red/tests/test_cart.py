from shop.cart import cart_total


def test_total_with_discount_and_tax():
    assert cart_total([(100, 2), (50, 4)], "SAVE10", 1000) == 396


def test_total_without_code():
    assert cart_total([(100, 1)], None, 0) == 100
