"""One failure, one task (fix-chore-e2e, L4-VER-069): a `new tests failed` finding that names only tests a failed gate
finding of the same round already names joins that finding's task."""

from l4.verifier.fixunit import plan_fix_unit
from l4.verifier.types import Finding, Severity, Verdict

from .test_fixunit import FAMILY, result

X, Z, W = "e2e.test_cart::test_x", "e2e.test_cart::test_z", "e2e.test_cart::test_w"
U = "tests.test_pricing::test_total"


def blocker(title: str, detail: str) -> Finding:
    return Finding(Severity.BLOCKER, title, detail, "deterministic")


def round_with(*findings: Finding, failures: dict[str, str]):
    """`failures`: failing test id -> the gate it failed in."""
    r = result(Verdict.FAIL, list(findings))
    r.failures = {i: {"gate": gate, "kind": "other", "message": "m"} for i, gate in failures.items()}
    return r


def plan(r):
    return plan_fix_unit(FAMILY, r, [], ordinal=1, fix_minor=False)


def test_the_new_tests_finding_of_the_same_failures_joins_the_gate_findings_task():  # SCN-VER-255
    gate, new = blocker("e2e gate failed", "`pytest e2e` failed"), blocker("new tests failed", f"{X}, {Z}")
    [group] = plan(round_with(gate, new, failures={X: "e2e", Z: "e2e"})).groups
    assert set(group.ids) == {gate.id, new.id} and group.chore and group.criteria == ()
    assert group.title.startswith("e2e gate failed")


def test_it_joins_whatever_the_order_of_the_findings():
    gate, new = blocker("e2e gate failed", "x"), blocker("new tests errored", f"{Z}")
    [group] = plan(round_with(new, gate, failures={X: "e2e", Z: "e2e"})).groups
    assert group.ids == (gate.id, new.id) and group.title.startswith("e2e gate failed")


def test_a_unit_gate_finding_takes_its_own_new_tests_finding_too():
    gate, new = blocker("test gate failed", "x"), blocker("new tests failed", U)
    [group] = plan(round_with(gate, new, failures={U: "test", X: "e2e"})).groups
    assert set(group.ids) == {gate.id, new.id}


def test_a_new_tests_finding_naming_a_test_the_gate_finding_does_not_keeps_its_task():  # SCN-VER-256
    gate, new = blocker("e2e gate failed", "x"), blocker("new tests failed", f"{X}, {W}")
    groups = plan(round_with(gate, new, failures={X: "e2e", Z: "e2e"})).groups
    assert [g.ids for g in groups] == [(gate.id,), (new.id,)]


def test_ids_of_two_gates_are_not_one_failure():
    gates = [blocker("test gate failed", "x"), blocker("e2e gate failed", "y")]
    new = blocker("new tests failed", f"{U}, {X}")  # one id in each gate: no single finding holds them all
    groups = plan(round_with(*gates, new, failures={U: "test", X: "e2e"})).groups
    assert sorted(len(g.ids) for g in groups) == [1, 1, 1]


def test_a_cut_list_is_not_proof_and_keeps_its_task():
    gate = blocker("e2e gate failed", "x")
    ids = [f"e2e.t::t{n}" for n in range(8)]
    new = blocker("new tests failed", ", ".join(ids[:5]) + " and 3 more")
    groups = plan(round_with(gate, new, failures=dict.fromkeys(ids, "e2e"))).groups
    assert [g.ids for g in groups] == [(gate.id,), (new.id,)]


def test_a_round_without_a_failures_map_keeps_both_tasks():
    gate, new = blocker("e2e gate failed", "x"), blocker("new tests failed", X)
    assert len(plan(round_with(gate, new, failures={})).groups) == 2


def test_a_new_tests_finding_alone_keeps_its_task():
    new = blocker("new tests failed", X)
    assert [g.ids for g in plan(round_with(new, failures={X: "e2e"})).groups] == [(new.id,)]
