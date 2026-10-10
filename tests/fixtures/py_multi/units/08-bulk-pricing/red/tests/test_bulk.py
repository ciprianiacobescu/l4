from shop.pricing import bulk_price


def test_ten_or_more_get_five_percent_off():
    assert bulk_price(1000, 10) == 9500


def test_fewer_than_ten_pay_full_price():
    assert bulk_price(1000, 9) == 9000
