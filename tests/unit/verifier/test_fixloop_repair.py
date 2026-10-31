"""own-test-repair (L4-IMP-091): `decide_fix` hands the planner the failing tests that qualify and the end of the gate
log, and the fix unit it plans carries them (a repair marker, a task that says the test may be right)."""

from types import SimpleNamespace

from l4.config.schema import L4Config
from l4.redact import Redactor
from l4.specs.fixmark import chore_kind, read_fix_marker
from l4.verifier import fixloop
from l4.verifier.fixloop import FamilyProvider, decide_fix
from l4.verifier.repairs import RepairTest
from l4.verifier.types import Finding, Severity, Verdict, VerifyResult

from .test_fixloop_ci import UNIT_ID, UNIT_REL, World
from .test_fixloop_ci import world as world  # fixture

X, W = "e2e.test_a::test_x", "e2e.test_a::test_w"


def decide(world: World, out: object, monkeypatch, candidates: dict[str, RepairTest], failures: dict, log: str | None):
    (out / "out" / "gates" / "run").mkdir(parents=True)  # type: ignore[operator]
    if log is not None:
        (out / "out" / "gates" / "run" / "e2e.log").write_text(log)  # type: ignore[operator]
    gate = Finding(Severity.BLOCKER, "e2e gate failed", "`pytest e2e` failed", "deterministic", log="gates/run/e2e.log")
    result = VerifyResult(UNIT_ID, 2, Verdict.FAIL, "b" * 40, world.head())
    result.findings, result.failures = [gate], failures
    monkeypatch.setattr(fixloop, "repair_candidates", lambda wb, failing: candidates)
    family = FamilyProvider(world.provider, world.parent)
    services = SimpleNamespace(ref=world.parent, git=world.git, worktree=world.repo, ledger=world.writer)
    ctx = SimpleNamespace(cfg=L4Config(), services=services, shared={})
    wb = SimpleNamespace(
        provider=family, ref=world.parent, git=world.git, unit_rel=UNIT_REL, worktree=world.repo,
        out_dir=out / "out" / "x", redactor=Redactor({"T": "supersecretvalue99"}),
    )  # fmt: skip
    decide_fix(ctx, wb, result)  # type: ignore[arg-type]
    return result, gate


def record(test_id: str) -> dict[str, str]:
    return {"gate": "e2e", "kind": "other", "message": f"Error in {test_id}"}


def candidate(test_id: str) -> RepairTest:
    return RepairTest(test_id, "e2e/test_a.py", test_id.split("::")[1], "e2e", "other", "m")


def test_a_round_whose_failing_tests_all_qualify_plans_a_repair_chore_with_the_log_end(world, tmp_path, monkeypatch):
    result, gate = decide(world, tmp_path, monkeypatch, {X: candidate(X)}, {X: record(X)}, "x" * 3000 + "THE TAIL")
    assert result.fix is not None and result.fix.action == "spawn" and result.fix.plan is not None
    [group] = result.fix.plan.groups
    assert group.repair and group.chore and group.ids == (gate.id,)
    assert "End of the gate log:" in group.detail and group.detail.count("x") < 700 and "THE TAIL" in group.detail
    fix = world.provider.create_fix_unit(world.parent, 1, result.fix.plan.groups, result.fix.plan.delta)
    assert read_fix_marker(fix.path).repairs == (gate.id,)  # type: ignore[union-attr]
    assert chore_kind(fix.path, f"1.1 e2e gate failed ({gate.id})") == "repair"


def test_one_failing_test_that_does_not_qualify_keeps_a_plain_fix_chore(world, tmp_path, monkeypatch):  # SCN-IMP-459
    result, _ = decide(world, tmp_path, monkeypatch, {X: candidate(X)}, {X: record(X), W: record(W)}, "log")
    assert result.fix is not None and result.fix.plan is not None
    [group] = result.fix.plan.groups
    assert group.chore and not group.repair


def test_a_missing_log_is_no_excerpt_and_no_failure(world, tmp_path, monkeypatch):
    result, _ = decide(world, tmp_path, monkeypatch, {X: candidate(X)}, {X: record(X)}, None)
    assert result.fix is not None and result.fix.plan is not None
    [group] = result.fix.plan.groups
    assert group.repair and "End of the gate log" not in group.detail


def test_the_log_is_redacted_before_it_enters_the_task(world, tmp_path, monkeypatch):
    result, _ = decide(world, tmp_path, monkeypatch, {X: candidate(X)}, {X: record(X)}, "key=supersecretvalue99 failed")
    assert result.fix is not None and result.fix.plan is not None
    [group] = result.fix.plan.groups
    assert group.repair and "supersecretvalue99" not in group.detail and "End of the gate log: key=" in group.detail
