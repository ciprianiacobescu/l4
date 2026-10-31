"""own-test-repair (L4-IMP-091): which findings of a round plan a `repair` chore. `repairable` is the set of test ids
that qualify (the git-based rule is `l4.verifier.repairs`); a finding is a repair only when every test id it fails on
is among them."""

from l4.verifier.fixunit import plan_fix_unit
from l4.verifier.types import Finding, Severity, Verdict

from .test_fixunit import FAMILY, result

X, Z, W = "e2e.test_cart::test_x", "e2e.test_cart::test_z", "e2e.test_cart::test_w"
U = "tests.test_pricing::test_total"


def blocker(title: str, detail: str) -> Finding:
    return Finding(Severity.BLOCKER, title, detail, "deterministic")


def round_with(*findings: Finding, failures: dict[str, tuple[str, str]], dropped: int = 0):
    """`failures`: failing test id -> (gate, kind)."""
    r = result(Verdict.FAIL, list(findings))
    r.failures = {i: {"gate": g, "kind": k, "message": f"msg of {i}"} for i, (g, k) in failures.items()}
    r.failures_dropped = dropped
    return r


def plan(r, repairable=()):
    return plan_fix_unit(FAMILY, r, [], ordinal=1, fix_minor=False, repairable=repairable)


def test_an_e2e_gate_finding_whose_every_failure_qualifies_is_a_repair_chore():  # SCN-IMP-453
    gate = blocker("e2e gate failed", "`pytest e2e` failed")
    [group] = plan(round_with(gate, failures={X: ("e2e", "other")}), {X}).groups
    assert group.repair and group.chore and group.criteria == ()
    assert X in group.detail and "other" in group.detail and "msg of" in group.detail
    assert "may be right" in group.detail and "product code" in group.detail


def test_without_a_repairable_set_nothing_is_a_repair():  # the default: SCN-IMP-461 for the planner
    gate = blocker("e2e gate failed", "x")
    [group] = plan(round_with(gate, failures={X: ("e2e", "other")})).groups
    assert not group.repair and group.chore


def test_one_failing_test_that_does_not_qualify_makes_the_finding_a_plain_fix():  # SCN-IMP-459, mixed finding
    gate = blocker("e2e gate failed", "x")
    [group] = plan(round_with(gate, failures={X: ("e2e", "other"), W: ("e2e", "other")}), {X}).groups
    assert not group.repair


def test_a_collection_error_of_the_gate_is_not_a_test_and_no_repair():
    gate = blocker("e2e gate failed", "x")
    r = round_with(gate, failures={X: ("e2e", "other"), "e2e/test_b.py": ("e2e", "collection")})
    [group] = plan(r, {X, "e2e/test_b.py"}).groups
    assert not group.repair


def test_failure_records_the_round_cut_make_the_finding_no_repair():
    gate = blocker("test gate failed", "x")
    [group] = plan(round_with(gate, failures={U: ("test", "other")}, dropped=3), {U}).groups
    assert not group.repair


def test_a_new_tests_finding_naming_only_qualifying_tests_is_a_repair():
    new = blocker("new tests failed", f"{X}, {Z}")
    [group] = plan(round_with(new, failures={X: ("e2e", "other"), Z: ("e2e", "error")}), {X, Z}).groups
    assert group.repair and group.ids == (new.id,)


def test_a_cut_list_of_a_new_tests_finding_is_no_repair():
    ids = [f"e2e.t::t{n}" for n in range(8)]
    new = blocker("new tests failed", ", ".join(ids[:5]) + " and 3 more")
    r = round_with(new, failures=dict.fromkeys(ids, ("e2e", "other")))
    [group] = plan(r, set(ids)).groups
    assert not group.repair


def test_a_joined_task_is_a_repair_only_when_both_findings_are():
    gate, new = blocker("e2e gate failed", "x"), blocker("new tests failed", f"{X}")
    [group] = plan(round_with(gate, new, failures={X: ("e2e", "other"), Z: ("e2e", "other")}), {X, Z}).groups
    assert set(group.ids) == {gate.id, new.id} and group.repair
    [group] = plan(round_with(gate, new, failures={X: ("e2e", "other"), Z: ("e2e", "other")}), {X}).groups
    assert not group.repair  # the gate finding fails on Z too, which does not qualify


def test_a_finding_of_another_title_is_no_repair():
    other = blocker("something else", "x")
    [group] = plan(round_with(other, failures={X: ("e2e", "other")}), {X}).groups
    assert not group.repair


def test_a_finding_that_cites_a_criterion_is_no_repair():
    gate = Finding(Severity.BLOCKER, "e2e gate failed", "x", "deterministic", "C-00000001")
    [group] = plan(round_with(gate, failures={X: ("e2e", "other")}), {X}).groups
    assert not group.repair and not group.chore


def test_the_detail_is_bounded_and_names_at_most_a_few_tests():
    ids = [f"e2e.test_cart::test_{n:03d}" for n in range(60)]
    gate = blocker("e2e gate failed", "x")
    r = round_with(gate, failures=dict.fromkeys(ids, ("e2e", "other")))
    [group] = plan(r, set(ids)).groups
    assert group.repair and len(group.detail) <= 2400 and "more" in group.detail
