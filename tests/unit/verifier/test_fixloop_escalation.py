"""Every escalation of the fix loop records its cause (L4-OPS-005, SCN-OPS-10), and a repeated failure ends the loop
at once (L4-OPS-007, SCN-OPS-12, SCN-OPS-13)."""

import dataclasses
import json
from pathlib import Path

import pytest

from l4.state.ledger import LedgerEvent
from l4.verifier import fixloop
from l4.verifier.fixloop import failure_set, repeated_failure
from l4.verifier.types import GateLine, Verdict, VerifyResult

from ..implementer.conftest import green_step
from . import test_ladder_fix as ladder_fix
from .test_ladder_fix import FIX_UNIT, chore_fix, noqa_green, red_step

no_fix_loop = ladder_fix.no_fix_loop  # the fixtures of the fix loop's end-to-end suite
with_verifier = ladder_fix.with_verifier

BOT = ("l4-bot", "l4-bot@users.noreply.invalid")


def gate(name: str, status: str = "fail", reason: str = "exit code 1") -> dict:
    return {"name": name, "command": name, "status": status, "reason": reason, "log": None}


# --- the failure set (D7) ----------------------------------------------------------------------------------------


def test_the_failure_set_names_failed_gates_failing_tests_and_the_exit_code_of_a_gate_with_no_report():
    gates = [gate("lint", "pass", ""), gate("test", reason="exit code 1; failing: a")]
    tests = {"tests.test_a::test_x": "failed", "tests.test_a::test_y": "passed", "tests.test_b::test_z": "error"}
    assert failure_set(gates, tests) == {"test", "tests.test_a::test_x", "tests.test_b::test_z"}
    assert failure_set([gate("test", reason="exit code 3")], {}) == {"test", "test:exit 3"}
    assert failure_set([gate("lint")], {}) == {"lint", "lint:exit 1"}
    assert failure_set([gate("test", reason="report missing: gates.test.reports is empty")], {}) == {
        "test",
        "test:report missing: gates.test.reports is empty",
    }


def test_a_round_with_no_failed_gate_has_an_empty_failure_set():
    assert failure_set([gate("lint", "pass", "")], {"t::a": "passed"}) == frozenset()


# --- the comparison with the previous round ----------------------------------------------------------------------


def commit(git, repo: Path, author: tuple[str, str], subject: str, *, trailer: bool = True) -> str:
    git.run("add", "-A")
    extra = ["--trailer", "L4-Run: r-1"] if trailer else []
    git.run("-c", f"user.name={author[0]}", "-c", f"user.email={author[1]}", "commit", "-q", "-m", subject, *extra)
    return git.run("rev-parse", "HEAD").stdout.strip()


@pytest.fixture
def unit(tmp_path: Path, git_for):
    repo = tmp_path / "repo"
    repo.mkdir()
    git = git_for(repo)
    git.run("init", "-q", "-b", "main")
    (repo / "a.txt").write_text("a")
    head = commit(git, repo, BOT, "base")
    path = repo / "u"
    path.mkdir()
    return git, repo, path, head


def previous(path: Path, head: str, gates: list[dict], tests: dict | None = None, *, verdict: str = "FAIL", n: int = 1):
    folder = path / ".l4" / "evidence" / f"round-{n}"
    folder.mkdir(parents=True, exist_ok=True)
    body = {"round": n, "verdict": verdict, "head_sha": head, "gates": gates, "tests": tests or {}}
    (folder / "verdict.json").write_text(json.dumps(body))


def current(head: str, gates: list[dict], tests: dict | None = None, n: int = 2) -> VerifyResult:
    result = VerifyResult("u", n, Verdict.FAIL, "b", head)
    result.gates = [GateLine(g["name"], g["command"], g["status"], g["reason"], g["log"]) for g in gates]
    result.tests = tests or {}
    return result


def test_the_same_crashed_test_gate_twice_is_a_repeat(unit):  # SCN-OPS-12
    git, repo, path, head = unit
    crash = [gate("test", reason="exit code 3")]
    previous(path, head, crash)
    (repo / "b.txt").write_text("fix")
    now = commit(git, repo, BOT, "fix(u): task")
    detail = repeated_failure(path, git, [], current(now, crash))
    assert detail == "round 2 failed the same way as round 1: test, test:exit 3"


def test_a_different_failing_test_is_not_a_repeat(unit):  # SCN-OPS-13
    git, repo, path, head = unit
    previous(path, head, [gate("test")], {"t::a": "failed"})
    assert repeated_failure(path, git, [], current(head, [gate("test")], {"t::b": "failed"})) is None


def test_an_empty_failure_set_is_never_a_repeat(unit):
    git, _, path, head = unit
    previous(path, head, [gate("lint", "pass", "")])
    assert repeated_failure(path, git, [], current(head, [gate("lint", "pass", "")])) is None


def test_a_round_without_a_previous_round_or_after_a_non_fail_round_is_not_a_repeat(unit):
    git, _, path, head = unit
    crash = [gate("test", reason="exit code 3")]
    assert repeated_failure(path, git, [], current(head, crash)) is None
    previous(path, head, crash, verdict="NEEDS_HUMAN")
    assert repeated_failure(path, git, [], current(head, crash)) is None


def test_a_commit_of_a_person_between_the_rounds_gives_the_next_round(unit):
    git, repo, path, head = unit
    crash = [gate("test", reason="exit code 3")]
    previous(path, head, crash)
    (repo / "b.txt").write_text("person")
    commit(git, repo, ("alice", "alice@example.invalid"), "I fixed it", trailer=False)
    (repo / "c.txt").write_text("harness")
    now = commit(git, repo, BOT, "docs(u): verification round 2")
    assert repeated_failure(path, git, [], current(now, crash)) is None


def test_an_unknown_previous_head_is_not_a_repeat(unit):
    git, _, path, head = unit
    crash = [gate("test", reason="exit code 3")]
    previous(path, "0" * 40, crash)
    assert repeated_failure(path, git, [], current(head, crash)) is None


def event(kind: str, seq: int, **data) -> LedgerEvent:
    from datetime import UTC, datetime

    return LedgerEvent(datetime.now(UTC), "r", "u", seq, kind, data)


def test_a_retry_after_the_previous_round_gives_the_next_round(unit):
    git, _, path, head = unit
    crash = [gate("test", reason="exit code 3")]
    previous(path, head, crash)
    events = [event("verify.verdict", 1, round=1, verdict="FAIL")]
    assert repeated_failure(path, git, events, current(head, crash)) is not None
    for kind in ("unit.retried", "unit.resumed"):
        assert repeated_failure(path, git, [*events, event(kind, 2)], current(head, crash)) is None


def test_the_detail_is_cut_to_200_characters(unit):
    git, _, path, head = unit
    tests = {f"tests.test_module_{i}::test_case_{i}": "failed" for i in range(30)}
    previous(path, head, [gate("test")], tests)
    detail = repeated_failure(path, git, [], current(head, [gate("test")], tests))
    assert detail is not None and detail.startswith("round 2 failed the same way as round 1: ")
    assert len(detail.split(": ", 1)[1]) <= 200


# --- the causes, end to end ---------------------------------------------------------------------------------------


@pytest.fixture
def escalation(monkeypatch):
    """What `after_verdict` left in `ctx.shared["escalation"]` at each call."""
    seen: list = []
    import l4.verifier.ladder as ladder

    original = ladder.after_verdict

    def spy(ctx, wb, result, trigger):
        out = original(ctx, wb, result, trigger)
        seen.append(ctx.shared.get("escalation"))
        return out

    monkeypatch.setattr(ladder, "after_verdict", spy)
    return seen


def test_the_fix_round_limit_sets_its_code_and_its_text(run_l4, valid_spec, with_verifier, escalation):
    with_verifier(max_fix_rounds=0)
    run = run_l4([red_step(), noqa_green()])
    assert run.code == 13
    assert escalation[-1] == ("fix_rounds_exhausted", "fix rounds used 0/0")


def test_a_fix_unit_that_cannot_be_created_sets_its_code(run_l4, valid_spec, monkeypatch, escalation):
    from l4.specs.base import FixUnitInvalid
    from l4.verifier.fixloop import FamilyProvider

    def broken(self, *args, **kwargs):
        raise FixUnitInvalid("nope")

    monkeypatch.setattr(FamilyProvider, "create_fix_unit", broken)
    run = run_l4([red_step(), noqa_green()])
    assert run.code == 13
    code, detail = escalation[-1]
    assert code == "fix_unit_not_created" and detail.startswith("the fix unit could not be created: ")


def test_a_repeated_failure_escalates_with_same_failure_and_writes_no_second_fix_unit(
    run_l4, valid_spec, escalation
):  # SCN-OPS-12
    run = run_l4([red_step(), green_step(), chore_fix(), chore_fix()], lint=["sh -c 'echo broken; exit 1'"])
    assert run.code == 13 and run.triggers()[-1] == "verify_fail_exhausted"
    assert [e["verdict"] for e in run.events("verify.verdict")] == ["FAIL", "FAIL"]
    assert len(run.events("fix.spawned")) == 1  # no fix unit 2
    code, detail = escalation[-1]
    assert code == "same_failure"
    assert detail == "round 2 failed the same way as round 1: lint, lint:exit 1"


def test_a_framework_without_fix_units_sets_its_code(run_l4, valid_spec, monkeypatch, escalation):
    monkeypatch.setattr(fixloop.FamilyProvider, "can_fix", property(lambda self: False))
    run = run_l4([red_step(), noqa_green()])
    assert run.code == 13
    assert escalation[-1] == ("no_fix_units", "openspec has no fix units")


def test_a_round_with_no_convertible_finding_sets_its_code(run_l4, valid_spec, monkeypatch, escalation):  # SCN-OPS-10
    original = fixloop.plan_fix_unit
    monkeypatch.setattr(fixloop, "plan_fix_unit", lambda *a, **k: dataclasses.replace(original(*a, **k), groups=()))
    run = run_l4([red_step(), noqa_green()])
    assert run.code == 13
    detail = "no finding of this round can be converted into a fix task"
    assert escalation[-1] == ("no_convertible_finding", detail)


# --- the fixer runs what the verifier runs (L4-OPS-012) -----------------------------------------------------------

COVERAGE_ONLY = (
    "import sys\n\n\ndef test_runs_without_the_coverage_plugin():\n"
    '    assert "coverage" not in sys.modules, "coverage.py is loaded by the coverage plugin"\n'
)


@pytest.fixture
def coverage_only_test(tdd_repo, raw) -> None:
    """The repository holds a test that passes unless the coverage plugin is loaded (a green step may not add tests)."""
    (tdd_repo.repo / "tests" / "test_coverage_only.py").write_text(COVERAGE_ONLY)
    raw(tdd_repo.repo, "add", "-A")
    raw(tdd_repo.repo, "commit", "-q", "-m", "a test that sees the coverage plugin")
    raw(tdd_repo.repo, "push", "-q", "origin", "main")


def test_a_failure_that_only_the_coverage_plugin_causes_reaches_the_fixer(
    run_l4, valid_spec, coverage_only_test
):  # SCN-OPS-19
    run = run_l4([red_step(), noqa_green(), chore_fix(), chore_fix()], implementer={"max_task_attempts": 2})
    fix_gates = [e for e in run.events("gate.finished") if e.get("fix_unit") == FIX_UNIT and e["name"] == "test"]
    assert fix_gates and fix_gates[0]["status"] == "fail"
    assert "test_runs_without_the_coverage_plugin" in run.adapter.requests[3].prompt  # the retry prompt
