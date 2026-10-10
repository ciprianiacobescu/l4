import pytest
from pkg.calc import add


def test_add():
    assert add(1, 2) == 3


@pytest.mark.skip(reason="later")
def test_add_zero():
    assert add(0, 0) == 0
