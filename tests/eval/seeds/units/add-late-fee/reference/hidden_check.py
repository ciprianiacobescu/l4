"""The reviewer's check of add-late-fee, never copied into a worktree: run it with pytest against the project with the
reference green applied (`PYTHONPATH=src pytest reference/hidden_check.py`). The defect is real and deterministic:
the reference ignores the balance (the fee is always 200 cents) and never rejects a negative balance."""

import pytest
from billing.fees import late_fee_cents


def test_the_fee_is_two_percent_of_the_balance():
    assert late_fee_cents(25000, 9) == 500
    assert late_fee_cents(10050, 9) == 201


def test_a_negative_balance_is_rejected():
    with pytest.raises(ValueError):
        late_fee_cents(-1, 9)
