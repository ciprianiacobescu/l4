"""L4-EVAL-021, 022: deltas per profile, the threshold, the judge rules, and which cells enter a rate."""

from l4.eval.compare import compare

from ._cards import impl, judge, sample_card

UNITS = ["add-late-fee", "add-reorder-quantity", "add-shelf-code", "add-tip-amount"]
IMPL_UNITS = UNITS[1:]


def impl_cells(profile: str, passes: list[bool], **over):
    return [impl(profile, u, "pass" if ok else "fail", **over) for u, ok in zip(IMPL_UNITS, passes, strict=False)]


def row(result, role: str, profile: str):
    return next(r for r in result.rows if r["role"] == role and r["profile"] == profile)


def test_identical_scorecards_are_ok_with_zero_deltas() -> None:
    card = sample_card(impl_cells("p", [True, True, False]))
    result = compare(card, card, max_drop=0.2)
    r = row(result, "implementer", "p")
    assert r["status"] == "ok" and r["delta"] == 0.0 and r["old_rate"] == r["new_rate"] == 0.6667
    assert result.regressed is False


def test_a_drop_larger_than_max_drop_regresses_strictly() -> None:
    old = sample_card(impl_cells("p", [True, True, True]))
    new = sample_card(impl_cells("p", [True, True, False]))  # 1.0 -> 0.6667: a drop of 0.3333
    assert row(compare(old, new, max_drop=0.2), "implementer", "p")["status"] == "regressed"
    assert row(compare(old, new, max_drop=0.34), "implementer", "p")["status"] == "ok"
    assert row(compare(old, new, max_drop=0.3333), "implementer", "p")["status"] == "regressed"
    result = compare(old, new, max_drop=0.2)
    assert result.regressed is True and row(result, "implementer", "p")["delta"] == -0.3333


def test_the_default_gate_fails_one_lost_cell_of_four() -> None:
    four = [impl("p", u, "pass") for u in UNITS]
    one_lost = [*four[:3], impl("p", UNITS[3], "fail")]
    assert (
        row(compare(sample_card(four), sample_card(one_lost), max_drop=0.20), "implementer", "p")["status"]
        == "regressed"
    )
    assert row(compare(sample_card(four), sample_card(one_lost), max_drop=0.25), "implementer", "p")["status"] == "ok"


def test_a_gain_larger_than_max_drop_is_improved() -> None:
    old = sample_card(impl_cells("p", [False, False, True]))
    new = sample_card(impl_cells("p", [True, True, True]))
    assert row(compare(old, new, max_drop=0.2), "implementer", "p")["status"] == "improved"


def test_new_and_gone_profiles() -> None:
    old = sample_card([*impl_cells("a", [True] * 3), *impl_cells("b", [True] * 3)])
    new = sample_card([*impl_cells("a", [True] * 3), *impl_cells("c", [True] * 3)])
    result = compare(old, new, max_drop=0.2)
    assert row(result, "implementer", "b")["status"] == "gone" and row(result, "implementer", "c")["status"] == "new"
    assert row(result, "implementer", "a")["status"] == "ok"
    assert result.regressed is False  # neither fails the gate by itself


def test_the_other_deltas() -> None:
    old = sample_card([
        impl("p", "add-shelf-code", "pass", wall=100.0, attempts={"red": 1, "green": 1}, cost_usd=1.0),
        impl("p", "add-tip-amount", "pass", wall=100.0, attempts={"red": 1, "green": 1}, cost_usd=1.0),
    ])  # fmt: skip
    new = sample_card([
        impl("p", "add-shelf-code", "pass", wall=150.0, attempts={"red": 2, "green": 1}, cost_usd=1.5),
        impl("p", "add-tip-amount", "pass", wall=150.0, attempts={"red": 2, "green": 3}, cost_usd=2.0),
    ])  # fmt: skip
    r = row(compare(old, new, max_drop=0.2), "implementer", "p")
    assert r["attempts_delta"] == {"red": 1.0, "green": 1.0}
    assert r["wall_delta_pct"] == 50.0
    assert r["cost_delta"] == 1.5
    assert r["agreement_delta"] is None


def test_cost_delta_is_null_when_a_side_has_no_cost() -> None:
    old = sample_card([impl("p", "add-shelf-code", "pass")])
    new = sample_card([impl("p", "add-shelf-code", "pass", cost_usd=1.0)])
    assert row(compare(old, new, max_drop=0.2), "implementer", "p")["cost_delta"] is None


# --- line 27: the judge rules
def judge_cells(profile: str, agree: list[bool]):
    return [judge(profile, u, "pass" if a else "fail", agreement=a) for u, a in zip(UNITS, agree, strict=False)]


def test_a_judge_regresses_when_agreement_drops() -> None:
    old = sample_card(judge_cells("j", [True, True, True, True]))
    new = sample_card(judge_cells("j", [True, True, True, False]))
    r = row(compare(old, new, max_drop=0.2), "judge", "j")
    assert r["agreement_delta"] == -0.25 and r["status"] == "regressed"


def test_a_judge_that_passes_the_defect_unit_it_held_back_regresses_at_any_threshold() -> None:
    held = judge("j", "add-late-fee", "pass", verdict="NEEDS_HUMAN", expected_verdict="NEEDS_HUMAN", agreement=True)
    missed = judge("j", "add-late-fee", "fail", verdict="PASS", expected_verdict="NEEDS_HUMAN", agreement=False,
                   missed_defect=True)  # fmt: skip
    others = [judge("j", u, "pass") for u in UNITS[1:]]
    old, new = sample_card([held, *others]), sample_card([missed, *others])
    result = compare(old, new, max_drop=1.0)  # the threshold would let a total loss through
    r = row(result, "judge", "j")
    assert r["status"] == "regressed" and r["missed_defects"] == ["add-late-fee"]
    assert result.regressed is True and result.missed_defects == [("j", "add-late-fee")]


def test_a_judge_that_already_missed_the_defect_before_is_not_newly_missing_it() -> None:
    missed = judge("j", "add-late-fee", "fail", verdict="PASS", expected_verdict="NEEDS_HUMAN", agreement=False,
                   missed_defect=True)  # fmt: skip
    card = sample_card([missed])
    assert compare(card, card, max_drop=0.2).missed_defects == []


# --- line 28: which cells enter a rate
def test_only_cells_in_both_scorecards_enter_the_rate() -> None:
    old = sample_card([impl("p", "add-shelf-code", "pass"), impl("p", "add-tip-amount", "pass"),
                       impl("p", "add-reorder-quantity", "fail")])  # fmt: skip
    new = sample_card([impl("p", "add-shelf-code", "pass"), impl("p", "add-tip-amount", "invalid"),
                       impl("p", "add-reorder-quantity", "fail")])  # fmt: skip
    r = row(compare(old, new, max_drop=0.2), "implementer", "p")
    # the tip cell was rate limited in the new run: it is dropped from both sides, the rest is compared
    assert r["matched_cells"] == 2 and r["old_rate"] == 0.5 and r["new_rate"] == 0.5 and r["status"] == "ok"


def test_a_cell_missing_from_one_side_is_not_compared() -> None:
    old = sample_card([impl("p", "add-shelf-code", "pass"), impl("p", "add-tip-amount", "fail")])
    new = sample_card([impl("p", "add-shelf-code", "pass")])
    r = row(compare(old, new, max_drop=0.2), "implementer", "p")
    assert r["matched_cells"] == 1 and r["old_rate"] == 1.0 and r["new_rate"] == 1.0


def test_a_profile_mostly_invalid_in_either_scorecard_is_unrated_and_does_not_fail() -> None:
    good = [impl("p", u, "pass") for u in IMPL_UNITS]
    mostly_invalid = [
        impl("p", IMPL_UNITS[0], "fail"),
        impl("p", IMPL_UNITS[1], "invalid"),
        impl("p", IMPL_UNITS[2], "invalid"),
    ]
    for old, new in ((good, mostly_invalid), (mostly_invalid, good)):
        result = compare(sample_card(old), sample_card(new), max_drop=0.2)
        assert row(result, "implementer", "p")["status"] == "unrated" and result.regressed is False


def test_exactly_half_invalid_is_still_rated() -> None:
    half = [impl("p", "add-shelf-code", "pass"), impl("p", "add-tip-amount", "invalid")]
    one = [impl("p", "add-shelf-code", "fail"), impl("p", "add-tip-amount", "pass")]
    assert row(compare(sample_card(one), sample_card(half), max_drop=0.2), "implementer", "p")["status"] != "unrated"


def test_no_matched_rated_cell_is_unrated() -> None:
    old = sample_card([impl("p", "add-shelf-code", "pass")])
    new = sample_card([impl("p", "add-tip-amount", "pass")])
    assert row(compare(old, new, max_drop=0.2), "implementer", "p")["status"] == "unrated"


# --- review of M1.14: the gate cannot pass on missing data
def test_an_incomplete_scorecard_is_refused_on_either_side() -> None:
    import pytest

    from l4.eval.scorecard import build_scorecard
    from l4.exitcodes import ExitCode, L4Exit

    from ._cards import ENV, SEEDS

    full = sample_card(impl_cells("p", [True, True, True]))
    partial = build_scorecard(impl_cells("p", [True]), ENV, SEEDS, complete=False)  # a killed or busy-stopped run
    for old, new in ((full, partial), (partial, full)):
        with pytest.raises(L4Exit, match="incomplete") as info:
            compare(old, new, max_drop=0.2)
        assert info.value.code == ExitCode.USAGE_ERROR


def test_a_comparison_of_unrated_rows_only_compared_nothing() -> None:
    good = [impl("p", u, "pass") for u in IMPL_UNITS]
    all_invalid = [impl("p", u, "invalid") for u in IMPL_UNITS]
    result = compare(sample_card(good), sample_card(all_invalid), max_drop=0.2)
    assert result.compared == 0 and result.failed is False
    assert compare(sample_card(good), sample_card(good), max_drop=0.2).compared == 1


MISSED = dict(verdict="PASS", expected_verdict="NEEDS_HUMAN", agreement=False, missed_defect=True)


def test_a_missed_defect_regresses_when_the_baseline_has_no_rated_cell_for_it() -> None:
    """The baseline's defect cell was rate limited: the miss in the new run is not matched, yet it is evidence."""
    limited = judge("j", "add-late-fee", "invalid", invalid_reason="rate_limited", agreement=None, verdict=None)
    others = [judge("j", u, "pass") for u in UNITS[1:]]
    result = compare(
        sample_card([limited, *others]), sample_card([judge("j", "add-late-fee", "fail", **MISSED), *others]), 1.0
    )
    r = row(result, "judge", "j")
    assert r["status"] == "regressed" and r["missed_defects"] == ["add-late-fee"]
    assert result.failed is True


def test_a_missed_defect_regresses_a_profile_that_is_otherwise_unrated() -> None:
    old = sample_card([judge("j", u, "pass") for u in UNITS])
    invalid = [judge("j", u, "invalid", invalid_reason="rate_limited", agreement=None) for u in UNITS[1:]]
    new = sample_card([judge("j", "add-late-fee", "fail", **MISSED), *invalid])  # 3 of 4 invalid: unrated
    r = row(compare(old, new, max_drop=0.2), "judge", "j")
    assert r["status"] == "regressed" and r["missed_defects"] == ["add-late-fee"]
