"""Confirmation by a base run (L4-IMP-003, SCN-IMP-80..86): a pre-satisfied criterion that neither an earlier red nor
the zero-value run confirms is confirmed when its new test fails BY ASSERTION against the unit base code."""

import hashlib
from pathlib import Path

import pytest

from l4.agents.fake import Step
from l4.gates.runner import GateResult
from l4.implementer import base_run, tdd
from l4.implementer.base_run import confirmed_by_base_run
from l4.implementer.discrimination import PreSatisfied, run_with_code_of, unit_base
from l4.implementer.tdd import run_red
from l4.implementer.workbench import Workbench
from l4.specs.base import Task

from .conftest import KNOWN, UNKNOWN, Bench, result

TASK = Task("1.1", "1.1", "1.1 Ignore negative prices", False, " ", 0, 1, 3)
PRICING = "src/pytdd/pricing.py"
HEAD_PRICING = "def total(prices: list[float]) -> float:\n    return round(sum(p for p in prices if p > 0), 2)\n"
HEAD_PRICING_CLAMP = HEAD_PRICING + "\n\ndef clamp(value: float) -> float:\n    return max(value, 0.0)\n"
HEADER = 'import pytest\n\nfrom pytdd import total\n\n\n@pytest.mark.l4("{c}")\n'
FAILS_AT_BASE = HEADER.format(c=KNOWN) + "def test_new_total():\n    assert total([5.0, -2.0]) == 5.0\n"
PASSES_AT_BASE = HEADER.format(c=KNOWN) + "def test_new_total():\n    assert total([2.0, 2.0]) == 4.0\n"
ERRORS_AT_BASE = (
    HEADER.format(c=KNOWN)
    + "def test_new_total():\n    from pytdd.pricing import clamp\n\n    assert clamp(-1.0) == 0.0\n"
)
NEW_ID = "tests.test_new::test_new_total"
OTHER = HEADER.format(c=UNKNOWN) + "def test_other_total():\n    assert total([5.0]) == 5.0\n"
OTHER_ID = "tests.test_new::test_other_total"


def step(text: str = FAILS_AT_BASE, *, criteria=(KNOWN,)) -> Step:
    return Step(writes={"tests/test_new.py": text}, structured=result("red", criteria_ids=list(criteria)))


def commit_head(bench: Bench, files: dict[str, str]) -> None:
    """An earlier task's green: a commit on the unit branch after the unit base."""
    for path, text in files.items():
        (bench.wb.worktree / path).write_text(text)
    bench.wb.commit("green for 1.1", task="0.9", attempt=1, phase="green", tdd="green")


@pytest.fixture
def zero(monkeypatch):
    """The zero-value run confirms nothing (as for a project it cannot read); records what it received."""
    seen: list[dict] = []

    def fake(wb, candidates):
        seen.append({c: list(t) for c, t in candidates.items()})
        return (
            PreSatisfied({}, {c: tuple(t) for c, t in candidates.items()}, "unconfirmed")
            if candidates
            else PreSatisfied()
        )

    monkeypatch.setattr(tdd, "confirm_pre_satisfied", fake)
    return seen


@pytest.fixture
def based(monkeypatch):
    """Records the calls of the real base run."""
    calls: list[dict] = []
    real = tdd.confirmed_by_base_run

    def spy(wb, candidates, new_ids):
        calls.append({c: list(t) for c, t in candidates.items()})
        return real(wb, candidates, new_ids)

    monkeypatch.setattr(tdd, "confirmed_by_base_run", spy)
    return calls


def test_a_test_that_fails_by_assertion_at_the_unit_base_confirms_the_criterion(make_bench, zero, based):
    """SCN-IMP-80: the live case, task 1.1's green made 1.2's criterion true."""
    bench: Bench = make_bench([step()])
    commit_head(bench, {PRICING: HEAD_PRICING})
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "already_satisfied", outcome.reason
    assert zero == [{KNOWN: [NEW_ID]}]  # earlier red, then the zero-value run, then the base run on what is left
    assert based == [{KNOWN: [NEW_ID]}]
    sha = unit_base(bench.wb)
    assert sha == bench.wb.git.rev_parse("main")
    proof = bench.events("task.red_ok")[-1]["criteria"][KNOWN]
    assert proof == {
        "tests": [NEW_ID], "proof": "pre_satisfied", "discriminating": [NEW_ID], "via": "base_run", "base_sha": sha,
    }  # fmt: skip
    pre = bench.events("criterion.pre_satisfied")[-1]
    assert (pre["criterion"], pre["via"]) == (KNOWN, "base_run")


def failed(bench: Bench) -> str:
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "failed" and outcome.reason.startswith("not discriminating: "), outcome.reason
    assert [e for e in bench.events("criterion.pre_satisfied") if e["task"] == TASK.key] == []
    return outcome.reason


def test_an_error_at_the_base_is_not_confirmation(make_bench, zero, based):
    """SCN-IMP-81: a missing export is an error, not an assertion."""
    bench: Bench = make_bench([step(ERRORS_AT_BASE)])
    commit_head(bench, {PRICING: HEAD_PRICING_CLAMP})
    assert failed(bench).startswith(f"not discriminating: {KNOWN}")
    assert based == [{KNOWN: [NEW_ID]}]


def test_a_changed_dependency_manifest_skips_the_base_run(make_bench, zero, monkeypatch):
    """SCN-IMP-82."""
    monkeypatch.setattr(base_run, "run_with_code_of", lambda *a, **k: pytest.fail("the base run must be skipped"))
    bench: Bench = make_bench([step()])
    pyproject = bench.wb.worktree / "pyproject.toml"
    commit_head(bench, {PRICING: HEAD_PRICING, "pyproject.toml": pyproject.read_text() + "\n# new dependency\n"})
    reason = failed(bench)
    assert reason.startswith(f"not discriminating: {KNOWN}") and "pyproject.toml" in reason


def test_a_test_that_passes_at_the_base_too_is_not_confirmed(make_bench, zero, based):
    """SCN-IMP-83: the criterion was satisfied before the unit."""
    bench: Bench = make_bench([step(PASSES_AT_BASE)])
    commit_head(bench, {PRICING: HEAD_PRICING})
    failed(bench)
    assert based == [{KNOWN: [NEW_ID]}]


def test_the_failure_names_only_the_criteria_nothing_confirmed(make_bench, zero, based):
    """SCN-IMP-84: mixed."""
    bench: Bench = make_bench(
        [step(FAILS_AT_BASE + "\n\n" + OTHER[OTHER.index("@pytest") :], criteria=(KNOWN, UNKNOWN))]
    )
    commit_head(bench, {PRICING: HEAD_PRICING})
    reason = failed(bench)
    assert reason.startswith(f"not discriminating: {UNKNOWN} (") and KNOWN not in reason, reason


def test_the_zero_value_run_that_confirms_everything_leaves_no_base_run(make_bench, monkeypatch, based):
    """SCN-IMP-85: Python as today."""
    monkeypatch.setattr(
        tdd, "confirm_pre_satisfied", lambda wb, cands: PreSatisfied({c: tuple(t) for c, t in cands.items()})
    )
    bench: Bench = make_bench([step()])
    commit_head(bench, {PRICING: HEAD_PRICING})
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "already_satisfied", outcome.reason
    assert based == []
    assert "via" not in bench.events("task.red_ok")[-1]["criteria"][KNOWN]


def snapshot(root: Path) -> dict[str, tuple[str, int]]:
    skip = {".git", ".venv", ".l4-out", ".l4", "__pycache__"}  # the harness appends to its own ledger
    found = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if skip & set(relative.parts) or not path.is_file():
            continue
        found[relative.as_posix()] = (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mode)
    return found


def porcelain(bench: Bench) -> list[str]:
    lines = bench.wb.git.run("status", "--porcelain", "--untracked-files=all").stdout.splitlines()
    return [line for line in lines if ".l4/" not in line]  # the harness appends to its ledger


def agent_state(bench: Bench) -> None:
    """Head differs from the base; the worktree adds the step's test, edits a production file and adds a stub."""
    commit_head(bench, {PRICING: HEAD_PRICING, "src/pytdd/helper.py": "VALUE = 1\n"})
    wt = bench.wb.worktree
    (wt / "tests" / "test_new.py").write_text(FAILS_AT_BASE)
    (wt / PRICING).write_text(HEAD_PRICING_CLAMP)
    (wt / "src" / "pytdd" / "stub.py").write_text("def f():\n    raise NotImplementedError\n")


@pytest.mark.parametrize("mode", ["confirmed", "skipped", "gate_error"])
def test_the_worktree_is_byte_identical_after_the_base_run(make_bench, monkeypatch, mode):
    """SCN-IMP-86: restored whether the run confirmed, was skipped, or the gate raised."""
    bench: Bench = make_bench([])
    tdd.run_setup(bench.wb)
    agent_state(bench)
    if mode == "skipped":
        (bench.wb.worktree / "package.json").write_text("{}\n")
    before = snapshot(bench.wb.worktree)
    status = porcelain(bench)
    if mode == "gate_error":

        def boom(self, *args, **kwargs):
            raise RuntimeError("gate blew up")

        monkeypatch.setattr(Workbench, "run_gate", boom)
        with pytest.raises(RuntimeError, match="gate blew up"):
            confirmed_by_base_run(bench.wb, {KNOWN: [NEW_ID]}, {NEW_ID})
    else:
        got = confirmed_by_base_run(bench.wb, {KNOWN: [NEW_ID]}, {NEW_ID})
        assert bool(got.confirmed) == (mode == "confirmed"), got
    assert snapshot(bench.wb.worktree) == before
    assert porcelain(bench) == status


MIDDLEWARE = "src/pytdd/middleware.py"
MIDDLEWARE_SRC = "def wrap(x: int) -> int:\n    return x\n"
TEST_MIDDLEWARE = "tests/test_middleware.py"
TEST_MIDDLEWARE_SRC = "from pytdd.middleware import wrap\n\n\ndef test_wrap():\n    assert wrap(1) == 1\n"


def test_scn_imp_301_the_base_run_goes_on_past_an_unrelated_test_that_imports_an_added_module(make_bench, zero, based):
    """The base run sets the added module aside, so an unrelated test file that imports it fails collection; without
    --continue-on-collection-errors pytest collected nothing (exit 2) and the base run confirmed nothing."""
    bench: Bench = make_bench([step()])
    commit_head(
        bench,
        {PRICING: HEAD_PRICING, MIDDLEWARE: MIDDLEWARE_SRC, TEST_MIDDLEWARE: TEST_MIDDLEWARE_SRC},
    )
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "already_satisfied", outcome.reason
    proof = bench.events("task.red_ok")[-1]["criteria"][KNOWN]
    assert proof["via"] == "base_run" and proof["discriminating"] == [NEW_ID]


def test_run_with_code_of_returns_the_gate_result(make_bench):
    bench: Bench = make_bench([])
    tdd.run_setup(bench.wb)
    commit_head(
        bench,
        {PRICING: HEAD_PRICING, MIDDLEWARE: MIDDLEWARE_SRC, TEST_MIDDLEWARE: TEST_MIDDLEWARE_SRC},
    )
    (bench.wb.worktree / "tests" / "test_new.py").write_text(FAILS_AT_BASE)
    base = unit_base(bench.wb)
    paths, why = base_run._plan(bench.wb, base)
    assert why == "" and MIDDLEWARE in paths
    got = run_with_code_of(bench.wb, base, paths, name="test-base-run")
    assert isinstance(got, GateResult)
    assert got.report is not None
    assert "tests.test_middleware" in got.report.collection_errors
    assert NEW_ID in got.report.tests
