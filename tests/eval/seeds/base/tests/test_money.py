import pytest
from pricing.money import to_cents


def test_to_cents():
    assert to_cents("12.34") == 1234
    assert to_cents("-0.05") == -5


def test_to_cents_rejects_a_missing_fraction():
    with pytest.raises(ValueError):
        to_cents("12")
