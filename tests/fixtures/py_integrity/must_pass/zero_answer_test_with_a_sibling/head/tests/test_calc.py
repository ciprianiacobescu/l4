from pkg.calc import add


def test_zero():
    assert add(0, 0) == 0


def test_real():
    assert add(1, 2) == 3
