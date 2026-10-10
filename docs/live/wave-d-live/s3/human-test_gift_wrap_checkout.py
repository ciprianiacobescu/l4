"""A person's check of the gift-wrap fee that also runs from a plain checkout (no installed package)."""

import sys
from decimal import Decimal
from pathlib import Path

# a plain checkout has no installed `pricing`: put src/ first on the path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pricing.gift_wrap import gift_wrap_fee  # noqa: E402 - the import needs the sys.path line above


def test_one_wrapped_unit_costs_one_fifty():
    assert gift_wrap_fee(1) == Decimal("1.50")
