from pytdd import total


def test_total_adds_prices():
    assert total([1.25, 2.5]) == 3.75


def test_total_of_nothing_is_zero():
    assert total([]) == 0
