import json
import random
from importlib import resources

from l4.eval.scorecard import SCHEMA_ID, build_scorecard, canonical_json, cell_result
from l4.schemacheck import validate

ENV = {"started_at": "2026-10-07T10:00:00Z", "harness_commit": "abc", "k": 1}
SEEDS = {"sha256": "f" * 64, "units": ["add-late-fee", "add-shelf-code"]}


def impl(profile: str, unit: str, status: str, k: int = 0, wall: float = 10.0, **extra):
    base = {
        "role": "implementer", "profile": profile, "unit": unit, "k": k, "status": status, "invalid_reason": None,
        "wall_s": wall, "attempts": {"red": 1, "green": 1}, "halted_at": None, "breaker": None, "blocked": False,
        "verdict": "PASS", "cost_usd": None, "input_tokens": 0, "output_tokens": 0, "errors": [], "returncode": 0,
    }  # fmt: skip
    if status == "invalid":
        base.update(invalid_reason="rate_limited", attempts=None, verdict=None)
    base.update(extra)
    return cell_result(base)


def judge(profile: str, unit: str, status: str, agreement: bool = True, k: int = 0, wall: float = 5.0, **extra):
    base = {
        "role": "judge", "profile": profile, "unit": unit, "k": k, "status": status, "invalid_reason": None,
        "wall_s": wall, "verdict": "PASS", "expected_verdict": "PASS", "agreement": agreement, "findings": 0,
        "worst_severity": None, "missed_defect": False, "cost_usd": 0.5, "input_tokens": 1, "output_tokens": 1,
        "errors": [], "returncode": 0,
    }  # fmt: skip
    base.update(extra)
    return cell_result(base)


def schema() -> dict:
    return json.loads(resources.files("l4.eval").joinpath("scorecard.schema.json").read_text(encoding="utf-8"))


def cells():
    return [
        impl("p1", "add-shelf-code", "pass"), impl("p1", "add-tip-amount", "pass", wall=30.0),
        impl("p1", "add-reorder-quantity", "fail", halted_at="green", errors=[{"kind": "schema", "detail": "x"}],
             attempts={"red": 1, "green": 3}),
        impl("p1", "add-late-fee", "invalid"),
        judge("j1", "add-late-fee", "pass", verdict="NEEDS_HUMAN", expected_verdict="NEEDS_HUMAN", findings=2),
        judge("j1", "add-shelf-code", "fail", agreement=False, verdict="NEEDS_HUMAN"),
    ]  # fmt: skip


def test_the_body_is_deterministic_whatever_the_order_of_the_cells() -> None:
    first = canonical_json(build_scorecard(cells(), ENV, SEEDS))
    shuffled = cells()
    random.Random(7).shuffle(shuffled)
    assert canonical_json(build_scorecard(shuffled, ENV, SEEDS)) == first
    assert first == canonical_json(build_scorecard(cells(), ENV, SEEDS))


def test_cells_are_sorted_by_role_profile_unit_k() -> None:
    card = build_scorecard(cells(), ENV, SEEDS)
    keys = [(c["role"], c["profile"], c["unit"], c["k"]) for c in card["cells"]]
    assert keys == sorted(keys)
    assert card["cells"][0]["cell_key"] == "implementer|p1|add-late-fee|0"


def test_the_hash_ignores_started_at_and_nothing_else() -> None:
    a = build_scorecard(cells(), ENV, SEEDS)
    b = build_scorecard(cells(), {**ENV, "started_at": "2030-01-01T00:00:00Z"}, SEEDS)
    c = build_scorecard(cells(), {**ENV, "harness_commit": "def"}, SEEDS)
    assert a["scorecard_sha256"] == b["scorecard_sha256"] != c["scorecard_sha256"]
    assert a["env"]["started_at"] != b["env"]["started_at"]


def test_the_scorecard_validates_against_its_schema() -> None:
    card = build_scorecard(cells(), ENV, SEEDS)
    assert card["schema"] == SCHEMA_ID == "l4/eval-scorecard@1"
    assert validate(card, schema()) == []
    assert validate({**card, "schema": "l4/eval-scorecard@2"}, schema())
    bad = json.loads(canonical_json(card))
    bad["cells"][0]["status"] = "maybe"
    assert validate(bad, schema())


def test_a_partial_scorecard_says_so() -> None:
    assert build_scorecard(cells()[:1], ENV, SEEDS, complete=False)["complete"] is False
    assert build_scorecard(cells(), ENV, SEEDS)["complete"] is True


def test_an_empty_scorecard_is_valid() -> None:
    card = build_scorecard([], ENV, SEEDS, complete=False)
    assert validate(card, schema()) == [] and card["profiles"] == []


# --- line 15
def profile(card: dict, role: str, name: str) -> dict:
    return next(p for p in card["profiles"] if p["role"] == role and p["profile"] == name)


def test_the_pass_rate_leaves_invalid_cells_out() -> None:
    cs = [
        impl("p", "add-shelf-code", "pass"), impl("p", "add-tip-amount", "pass"),
        impl("p", "add-reorder-quantity", "fail"), impl("p", "add-late-fee", "invalid"),
    ]  # fmt: skip
    agg = profile(build_scorecard(cs, ENV, SEEDS), "implementer", "p")
    assert (agg["cells"], agg["pass"], agg["fail"], agg["invalid"]) == (4, 2, 1, 1)
    assert agg["pass_rate"] == 0.6667


def test_a_profile_with_no_rated_cell_has_a_null_rate() -> None:
    agg = profile(build_scorecard([impl("p", "add-shelf-code", "invalid")], ENV, SEEDS), "implementer", "p")
    assert agg["pass_rate"] is None and agg["median_wall_s"] is None and agg["attempts_mean"] is None


def test_median_wall_and_mean_attempts_cover_the_rated_cells_only() -> None:
    cs = [
        impl("p", "a", "pass", wall=10.0, attempts={"red": 1, "green": 1}),
        impl("p", "b", "pass", wall=30.0, attempts={"red": 3, "green": 2}),
        impl("p", "c", "fail", wall=20.0, attempts={"red": 2, "green": 0}),
        impl("p", "d", "invalid", wall=999.0),
    ]
    agg = profile(build_scorecard(cs, ENV, SEEDS), "implementer", "p")
    assert agg["median_wall_s"] == 20.0
    assert agg["attempts_mean"] == {"red": 2.0, "green": 1.0}


def test_agreement_rate_and_cost_and_errors() -> None:
    cs = [
        judge("j", "a", "pass", cost_usd=0.5), judge("j", "b", "fail", agreement=False, cost_usd=0.25),
        judge("j", "c", "pass", cost_usd=None),
        judge("j", "d", "invalid", errors=[{"kind": "rate_limit", "detail": "429"}]),
    ]  # fmt: skip
    agg = profile(build_scorecard(cs, ENV, SEEDS), "judge", "j")
    assert agg["agreement_rate"] == 0.6667
    assert agg["cost_usd"] == 1.25  # money spent on an invalid cell is still spent
    assert agg["errors"] == {"rate_limit": 1}
    assert agg["attempts_mean"] is None


def test_cost_is_null_when_no_cell_reported_one() -> None:
    agg = profile(build_scorecard([impl("p", "a", "pass")], ENV, SEEDS), "implementer", "p")
    assert agg["cost_usd"] is None


def test_errors_are_counted_by_class() -> None:
    cs = [impl("p", "a", "fail", errors=[{"kind": "schema", "detail": "1"}, {"kind": "schema", "detail": "2"}]),
          impl("p", "b", "fail", errors=[{"kind": "timeout", "detail": "t"}])]  # fmt: skip
    assert profile(build_scorecard(cs, ENV, SEEDS), "implementer", "p")["errors"] == {"schema": 2, "timeout": 1}


def test_a_profile_used_in_both_roles_is_two_rows() -> None:
    cs = [impl("x", "a", "pass"), judge("x", "a", "pass")]
    card = build_scorecard(cs, ENV, SEEDS)
    assert [(p["role"], p["profile"]) for p in card["profiles"]] == [("implementer", "x"), ("judge", "x")]
