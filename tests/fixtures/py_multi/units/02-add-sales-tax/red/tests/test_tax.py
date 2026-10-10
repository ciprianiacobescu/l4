from shop.tax import add_tax


def test_add_tax_in_basis_points():
    assert add_tax(1000, 825) == 1083


def test_zero_rate_changes_nothing():
    assert add_tax(1000, 0) == 1000
