"""The base run's scope and limit (L4-IMP-097, SCN-IMP-526..532): the unit's other test files are at the unit base for
the run, and the run stops after twice the step's own test run."""

import hashlib
import os
from pathlib import Path

import pytest

from l4.agents.fake import Step
from l4.config.schema import duration_seconds
from l4.gates.runner import GateResult
from l4.implementer import base_run, tdd
from l4.implementer.base_run import confirmed_by_base_run
from l4.implementer.discrimination import PreSatisfied
from l4.implementer.tdd import run_red
from l4.implementer.workbench import Workbench

from .conftest import KNOWN, UNKNOWN, Bench
from .test_already_satisfied_no_test import no_test
from .test_base_run import (
    FAILS_AT_BASE,
    HEAD_PRICING,
    HEADER,
    NEW_ID,
    PRICING,
    TASK,
    commit_head,
    porcelain,
    snapshot,
    step,
)
from .test_earlier_red import commit_old

EARLIER_PATH = "tests/test_earlier.py"
EARLIER = HEADER.format(c=UNKNOWN) + "def test_earlier_total():\n    assert total([5.0]) == 5.0\n"
NEW_PATH = "tests/test_new.py"
LINK = "link:../src/pytdd/linked_cases.py"
PRICING_TESTS = "tests/test_pricing.py"  # exists at the unit base (the fixture's)


def sleeper(seconds: int) -> str:
    return f"sh -c 'sleep {seconds}'"


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def commit_files(bench: Bench, files: dict[str, str]) -> None:
    """An earlier task's commit that may add files in new folders."""
    for path in files:
        (bench.wb.worktree / path).parent.mkdir(parents=True, exist_ok=True)
    commit_head(bench, files)


def sha_of(path: Path) -> str | None:
    if path.is_symlink():
        return "link:" + os.readlink(path)
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


@pytest.fixture
def zero(monkeypatch):
    """The zero-value run confirms nothing (as for a project it cannot read): the base run decides."""

    def fake(wb, candidates, *, real=None):
        unconfirmed = {c: tuple(t) for c, t in candidates.items()}
        return PreSatisfied({}, unconfirmed, "unconfirmed") if candidates else PreSatisfied()

    monkeypatch.setattr(tdd, "confirm_pre_satisfied", fake)


class Watch:
    """What the work tree holds while the gate `test-base-run` runs: path -> sha256 (None: absent), per run."""

    def __init__(self) -> None:
        self.paths: list[str] = []
        self.during: list[dict[str, str | None]] = []
        self.limits: list[int | None] = []


@pytest.fixture
def watch(monkeypatch) -> Watch:
    seen = Watch()
    real_gate = Workbench.run_gate

    def spy(self, name, command, **kwargs):
        if name == "test-base-run":
            seen.during.append({p: sha_of(self.worktree / p) for p in seen.paths})
            seen.limits.append(kwargs.get("timeout_s"))
        return real_gate(self, name, command, **kwargs)

    monkeypatch.setattr(Workbench, "run_gate", spy)
    return seen


def scope_event(bench: Bench) -> dict:
    events = bench.events("base_run.scope")
    assert len(events) == 1, events
    return events[0]


def confirmed_via_base_run(bench: Bench) -> None:
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "already_satisfied", outcome.reason
    assert bench.events("task.red_ok")[-1]["criteria"][KNOWN]["via"] == "base_run"


def test_run_gate_takes_a_limit_of_its_own(make_bench):
    """D3: `timeout_s` replaces `gates.timeout` for one gate."""
    bench: Bench = make_bench([])
    got = bench.wb.run_gate("slow", sleeper(5), timeout_s=1)
    assert (got.status, got.timed_out, got.reason) == ("fail", True, "timed out after 1s")
    assert 0.9 < got.seconds < 4


def test_run_gate_without_a_limit_of_its_own_uses_the_gates_timeout(make_bench):
    bench: Bench = make_bench([], timeout="2s", test_timeout="0s")
    got = bench.wb.run_gate("slow", sleeper(5))
    assert (got.timed_out, got.reason) == (True, "timed out after 2s")


def test_scn_imp_526_an_earlier_tasks_test_file_is_set_aside_and_the_candidate_is_confirmed(make_bench, zero, watch):
    bench: Bench = make_bench([step()])
    commit_files(bench, {PRICING: HEAD_PRICING, EARLIER_PATH: EARLIER})
    watch.paths = [EARLIER_PATH, NEW_PATH]
    confirmed_via_base_run(bench)
    assert watch.during == [{EARLIER_PATH: None, NEW_PATH: digest(FAILS_AT_BASE)}]
    event = scope_event(bench)
    assert (event["aside"], event["kept"], event["unscoped"]) == ([EARLIER_PATH], [NEW_PATH], "")
    assert event["decided"] == 1 and event["more"] == 0
    assert sha_of(bench.wb.worktree / EARLIER_PATH) == digest(EARLIER)  # back after the run


def test_scn_imp_527_a_pre_existing_test_file_the_unit_changed_stays_as_the_work_tree_holds_it(make_bench, zero, watch):
    bench: Bench = make_bench([step()])
    base_text = (bench.wb.worktree / PRICING_TESTS).read_text()
    head_text = base_text + "\n\ndef test_total_of_one():\n    assert total([1.0]) == 1.0\n"
    commit_files(bench, {PRICING: HEAD_PRICING, PRICING_TESTS: head_text})
    watch.paths = [PRICING_TESTS]
    confirmed_via_base_run(bench)
    assert watch.during == [{PRICING_TESTS: digest(head_text)}]  # a runner may write snapshots next to it
    event = scope_event(bench)
    assert (event["aside"], event["kept"], event["unscoped"]) == ([], [NEW_PATH], "")
    assert "at_base" not in event
    assert sha_of(bench.wb.worktree / PRICING_TESTS) == digest(head_text)


CANDIDATE = f'@pytest.mark.l4("{KNOWN}")\ndef test_new_total():\n    assert total([5.0, -2.0]) == 5.0\n'


def test_scn_imp_528_a_file_that_holds_a_candidate_and_earlier_tests_stays_whole(make_bench, zero, watch):
    whole = EARLIER + "\n\n" + CANDIDATE
    bench: Bench = make_bench([Step(writes={EARLIER_PATH: whole}, structured=step().structured)])
    commit_files(bench, {PRICING: HEAD_PRICING, EARLIER_PATH: EARLIER})
    watch.paths = [EARLIER_PATH]
    confirmed_via_base_run(bench)
    assert watch.during == [{EARLIER_PATH: digest(whole)}]  # the earlier test is still in it
    event = scope_event(bench)
    assert (event["kept"], event["aside"]) == ([EARLIER_PATH], [])


def test_scn_imp_529_support_files_fixtures_and_files_without_tests_stay(make_bench, zero, watch):
    files = {
        PRICING: HEAD_PRICING,
        EARLIER_PATH: EARLIER,
        "tests/conftest.py": "# shared fixtures\n",
        "tests/fixtures/data.json": '{"a": 1}\n',
        "tests/helpers/util.py": "VALUE = 1\n",  # a test support file (tdd.test_support_globs)
        "tests/shapes.py": "SHAPE = 1\n",  # under a test glob, holds no reported test
    }
    bench: Bench = make_bench([step()])
    commit_files(bench, files)
    watch.paths = [p for p in files if p != PRICING]
    confirmed_via_base_run(bench)
    stays = {p: digest(t) for p, t in files.items() if p not in (PRICING, EARLIER_PATH)}
    assert watch.during == [{EARLIER_PATH: None, **stays}]
    assert scope_event(bench)["aside"] == [EARLIER_PATH]


def test_scn_imp_530_a_candidate_whose_file_is_not_found_sets_nothing_aside(make_bench, zero, watch, monkeypatch):
    bench: Bench = make_bench([step()])
    commit_files(bench, {PRICING: HEAD_PRICING, EARLIER_PATH: EARLIER})
    real_locate = base_run.file_of_id
    monkeypatch.setattr(
        base_run, "file_of_id", lambda test_id, *a, **k: None if test_id == NEW_ID else real_locate(test_id, *a, **k)
    )
    watch.paths = [EARLIER_PATH]
    confirmed_via_base_run(bench)  # the run of L4-IMP-003 as it was
    assert watch.during == [{EARLIER_PATH: digest(EARLIER)}]
    event = scope_event(bench)
    assert event["unscoped"] == f"the file of {NEW_ID} was not found"
    assert (event["kept"], event["aside"]) == ([], [])


def test_scn_imp_530_a_run_with_no_head_report_sets_nothing_aside(make_bench):
    bench: Bench = make_bench([])
    tdd.run_setup(bench.wb)
    commit_files(bench, {PRICING: HEAD_PRICING, EARLIER_PATH: EARLIER})
    (bench.wb.worktree / NEW_PATH).write_text(FAILS_AT_BASE)
    before = snapshot(bench.wb.worktree)
    got = confirmed_by_base_run(bench.wb, {KNOWN: [NEW_ID]}, {NEW_ID})
    assert got.confirmed == {KNOWN: (NEW_ID,)}
    assert scope_event(bench)["unscoped"] == "no head report"
    assert snapshot(bench.wb.worktree) == before


def test_a_linked_test_file_makes_the_run_unscoped_and_stays_a_link(make_bench, zero, watch):
    bench: Bench = make_bench([step()])
    wt = bench.wb.worktree
    (wt / "src/pytdd/linked_cases.py").write_text("def test_linked():\n    assert True\n")
    (wt / "tests").mkdir(exist_ok=True)
    os.symlink("../src/pytdd/linked_cases.py", wt / "tests/test_linked.py")
    commit_files(bench, {PRICING: HEAD_PRICING, EARLIER_PATH: EARLIER})
    watch.paths = [EARLIER_PATH, "tests/test_linked.py"]
    confirmed_via_base_run(bench)
    assert watch.during == [
        {EARLIER_PATH: digest(EARLIER), "tests/test_linked.py": "link:../src/pytdd/linked_cases.py"}
    ]
    event = scope_event(bench)
    assert "tests/test_linked.py" in event["unscoped"] and event["aside"] == []
    assert event["kept"] == []  # an unscoped run keeps nothing apart
    assert sha_of(wt / "tests/test_linked.py") == LINK


def test_a_test_file_under_a_protected_path_stays(make_bench, zero, watch):
    protected = "tests/migrations/test_migration.py"  # `**/migrations/**` is in odd.forbidden_paths
    text = HEADER.format(c=UNKNOWN) + "def test_migration_total():\n    assert total([5.0]) == 5.0\n"
    bench: Bench = make_bench([step()])
    commit_files(bench, {PRICING: HEAD_PRICING, EARLIER_PATH: EARLIER, protected: text})
    watch.paths = [EARLIER_PATH, protected]
    confirmed_via_base_run(bench)
    assert watch.during == [{EARLIER_PATH: None, protected: digest(text)}]
    assert scope_event(bench)["aside"] == [EARLIER_PATH]


def head_state(bench: Bench) -> str:
    """An earlier task's commit (production code, one added and one changed test file) and the step's new test in the
    work tree; returns the changed file's head content."""
    tdd.run_setup(bench.wb)
    head_text = (
        bench.wb.worktree / PRICING_TESTS
    ).read_text() + "\n\ndef test_one():\n    assert total([1.0]) == 1.0\n"
    commit_files(bench, {PRICING: HEAD_PRICING, EARLIER_PATH: EARLIER, PRICING_TESTS: head_text})
    (bench.wb.worktree / NEW_PATH).write_text(FAILS_AT_BASE)
    return head_text


@pytest.mark.parametrize("mode", ["confirmed", "timed_out", "gate_error"])
def test_scn_imp_532_the_work_tree_is_the_same_after_a_scoped_base_run(make_bench, monkeypatch, mode):
    bench: Bench = make_bench([])
    head_text = head_state(bench)
    gate = bench.wb.run_gate("test", bench.wb.cfg.gates.test.command, reports=bench.wb.cfg.gates.test.reports)
    assert gate.report is not None and NEW_ID in gate.report.tests
    before, status = snapshot(bench.wb.worktree), porcelain(bench)
    during: list[dict] = []
    real_gate = Workbench.run_gate

    def spy(self, name, command, **kwargs):
        if name != "test-base-run":
            return real_gate(self, name, command, **kwargs)
        during.append({p: sha_of(self.worktree / p) for p in (EARLIER_PATH, PRICING_TESTS)})
        if mode == "gate_error":
            raise RuntimeError("gate blew up")
        if mode == "timed_out":
            return GateResult(name, "fail", "timed out after 1s", None, Path("/nonexistent.log"), timed_out=True)
        return real_gate(self, name, command, **kwargs)

    monkeypatch.setattr(Workbench, "run_gate", spy)
    if mode == "gate_error":
        with pytest.raises(RuntimeError, match="gate blew up"):
            confirmed_by_base_run(bench.wb, {KNOWN: [NEW_ID]}, {NEW_ID}, real=gate.report)
    else:
        got = confirmed_by_base_run(bench.wb, {KNOWN: [NEW_ID]}, {NEW_ID}, real=gate.report)
        assert bool(got.confirmed) == (mode == "confirmed"), got
    assert during == [{EARLIER_PATH: None, PRICING_TESTS: digest(head_text)}]  # the scope was on during the run
    assert snapshot(bench.wb.worktree) == before and porcelain(bench) == status
    assert [e for e in bench.events("guard.violation") if e.get("rule") == "restore failed"] == []


def run_with_timeouts(monkeypatch, calls: list[int | None]) -> None:
    """`run_with_code_of` as a run that never finishes: it is stopped at the limit it is given, like the runner does."""

    def fake(wb, sha, paths=None, *, name, extra_env=None, timeout_s=None):
        calls.append(timeout_s)
        return GateResult(name, "fail", f"timed out after {timeout_s}s", None, Path("/nonexistent.log"), timed_out=True)

    monkeypatch.setattr(base_run, "run_with_code_of", fake)


@pytest.mark.parametrize(
    ("head", "limit"),
    [(200.0, 400), (10.0, 300), (1200.0, 1800), (0.0, 1800)],
    ids=["twice the step run", "at least 300s", "at most gates.timeout", "step run unknown"],
)
def test_scn_imp_531_the_base_run_stops_at_its_own_limit(make_bench, monkeypatch, head, limit):
    bench: Bench = make_bench([], timeout="30m", test_timeout="0s")
    calls: list[int | None] = []
    run_with_timeouts(monkeypatch, calls)
    got = confirmed_by_base_run(bench.wb, {KNOWN: [NEW_ID]}, {NEW_ID}, head_seconds=head)
    assert calls == [limit]
    assert scope_event(bench)["timeout_s"] == limit
    assert got.confirmed == {} and set(got.inconclusive) == {KNOWN}  # the run decides nothing
    why = got.inconclusive[KNOWN]
    assert f"timed out after {limit}s" in why
    assert ("the base run's own limit" in why) == (limit < 1800)  # at gates.timeout the reason is the runner's own


def test_scn_imp_531_the_reason_names_the_limit_and_the_hold_says_so(make_bench, monkeypatch):
    bench: Bench = make_bench([], timeout="30m", test_timeout="0s")
    run_with_timeouts(monkeypatch, [])
    got = confirmed_by_base_run(bench.wb, {KNOWN: [NEW_ID]}, {NEW_ID}, head_seconds=200.0)
    assert (
        "timed out after 400s: the base run's own limit (twice the step's test run, or the step's test run plus one "
        "test's limit, at least 300s)" in got.inconclusive[KNOWN]
    )
    zero = PreSatisfied({}, {}, "", {KNOWN: "the zero-value run could not decide"})
    assert "the base run's own limit" in base_run.combine(zero, got).message


@pytest.mark.parametrize(
    ("test_timeout", "head", "limit"),
    [("auto", 200.0, 800), ("auto", 10.0, 610), ("auto", 1000.0, 1800), ("5m", 200.0, 500), ("5m", 400.0, 800)],
    ids=["auto per-test limit", "auto, short run", "capped at gates.timeout", "5m plus run", "twice the run wins"],
)
def test_scn_imp_531_the_limit_leaves_room_for_one_tests_own_limit(make_bench, monkeypatch, test_timeout, head, limit):
    """`gates.timeout: 30m`; the `auto` per-test limit is 10 minutes."""
    bench: Bench = make_bench([], timeout="30m", test_timeout=test_timeout)
    calls: list[int | None] = []
    run_with_timeouts(monkeypatch, calls)
    confirmed_by_base_run(bench.wb, {KNOWN: [NEW_ID]}, {NEW_ID}, head_seconds=head)
    assert calls == [limit]
    assert scope_event(bench)["timeout_s"] == limit


def test_scn_imp_531_a_limit_is_never_above_gates_timeout(make_bench, monkeypatch):
    bench: Bench = make_bench([], timeout="2m", test_timeout="0s")
    calls: list[int | None] = []
    run_with_timeouts(monkeypatch, calls)
    confirmed_by_base_run(bench.wb, {KNOWN: [NEW_ID]}, {NEW_ID}, head_seconds=10.0)
    assert calls == [120]  # the floor of 300s gives way to gates.timeout


@pytest.mark.parametrize("path", ["new tests", "no new test"])
def test_scn_imp_531_run_red_passes_the_step_test_gate_time(make_bench, zero, monkeypatch, path):
    if path == "new tests":
        bench: Bench = make_bench([step()])
        commit_files(bench, {PRICING: HEAD_PRICING})
    else:
        bench = make_bench([no_test()])
        commit_old(bench)
    seen: list[float] = []
    real_run = tdd.confirmed_by_base_run

    def spy(wb, candidates, new_ids, **kwargs):
        seen.append(kwargs["head_seconds"])
        return real_run(wb, candidates, new_ids, **kwargs)

    monkeypatch.setattr(tdd, "confirmed_by_base_run", spy)
    run_red(bench.wb, TASK, attempt=1)
    assert len(seen) == 1 and seen[0] > 0, seen


def head_run(bench: Bench) -> tuple[str, object]:
    """`head_state` and the head run's report."""
    head_text = head_state(bench)
    gate = bench.wb.run_gate("test", bench.wb.cfg.gates.test.command, reports=bench.wb.cfg.gates.test.reports)
    assert gate.report is not None and NEW_ID in gate.report.tests
    return head_text, gate.report


def violations(bench: Bench) -> list[tuple[str | None, str | None]]:
    return [(e.get("rule"), e.get("path")) for e in bench.events("guard.violation")]


def act_during_the_gate(monkeypatch, action) -> list[int]:
    """`action(worktree)` runs after the real gate of `test-base-run` (test code acts during the run); the list holds
    how many `base_run.scope` events were in the ledger when the gate was called."""
    real_gate = Workbench.run_gate
    scopes: list[int] = []

    def spy(self, name, command, **kwargs):
        if name != "test-base-run":
            return real_gate(self, name, command, **kwargs)
        ledger = self.ref.path / ".l4" / "ledger"
        scopes.append(sum(text.count('"base_run.scope"') for text in (f.read_text() for f in ledger.glob("*.jsonl"))))
        done = real_gate(self, name, command, **kwargs)
        action(self.worktree)
        return done

    monkeypatch.setattr(Workbench, "run_gate", spy)
    return scopes


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads any folder")
def test_a_bytecode_folder_the_tests_made_unreadable_does_not_stop_the_restore(make_bench, monkeypatch):
    """A refused `__pycache__` cleanup is recorded and the rest is put back: every file is back byte for byte."""
    bench: Bench = make_bench([])
    head_text, report = head_run(bench)
    caches = [bench.wb.worktree / "tests" / "__pycache__", bench.wb.worktree / "src" / "pytdd" / "__pycache__"]

    def lock(root: Path) -> None:
        for cache in caches:
            cache.mkdir(exist_ok=True)
            os.chmod(cache, 0)

    act_during_the_gate(monkeypatch, lock)
    try:
        confirmed_by_base_run(bench.wb, {KNOWN: [NEW_ID]}, {NEW_ID}, real=report)  # must not raise
    finally:
        for cache in caches:
            os.chmod(cache, 0o755)
    root = bench.wb.worktree
    assert sha_of(root / EARLIER_PATH) == digest(EARLIER)  # set aside for the run
    assert sha_of(root / PRICING) == digest(HEAD_PRICING)  # swapped to its base content for the run
    assert sha_of(root / PRICING_TESTS) == digest(head_text)
    assert sha_of(root / NEW_PATH) == digest(FAILS_AT_BASE)
    refused = violations(bench)
    # the refusal names the cache folder, not the file, which was put back
    assert ("restore failed", "tests/__pycache__") in refused and ("restore failed", "src/pytdd/__pycache__") in refused
    assert not {path for _, path in refused} & {EARLIER_PATH, PRICING, PRICING_TESTS}


@pytest.mark.parametrize("what", ["recreate_aside", "rewrite_production", "delete_production"])
def test_a_gate_that_rewrites_deletes_or_recreates_a_scoped_file_leaves_it_back(make_bench, monkeypatch, what):
    bench: Bench = make_bench([])
    _, report = head_run(bench)
    before, status = snapshot(bench.wb.worktree), porcelain(bench)

    def act(root: Path) -> None:
        if what == "recreate_aside":
            (root / EARLIER_PATH).write_text("planted by the gate\n")
        elif what == "rewrite_production":
            (root / PRICING).write_text("garbage\n")
        else:
            (root / PRICING).unlink()

    scopes = act_during_the_gate(monkeypatch, act)
    confirmed_by_base_run(bench.wb, {KNOWN: [NEW_ID]}, {NEW_ID}, real=report)
    assert snapshot(bench.wb.worktree) == before and porcelain(bench) == status
    assert violations(bench) == []
    assert scopes == [1]  # `base_run.scope` is recorded before the gate runs


def test_a_support_file_that_holds_a_reported_test_stays(make_bench, watch):
    bench: Bench = make_bench([])
    tdd.run_setup(bench.wb)
    support = "tests/helpers/test_selfcheck.py"  # `**/tests/helpers/**` is a support glob, `**/test_*.*` a test glob
    text = HEADER.format(c=UNKNOWN) + "def test_selfcheck():\n    assert total([1.0]) == 1.0\n"
    commit_files(bench, {PRICING: HEAD_PRICING, support: text, "tests/helpers/__init__.py": ""})
    (bench.wb.worktree / NEW_PATH).write_text(FAILS_AT_BASE)
    gate = bench.wb.run_gate("test", bench.wb.cfg.gates.test.command, reports=bench.wb.cfg.gates.test.reports)
    assert gate.report is not None and "tests.helpers.test_selfcheck::test_selfcheck" in gate.report.tests
    watch.paths = [support]
    confirmed_by_base_run(bench.wb, {KNOWN: [NEW_ID]}, {NEW_ID}, real=gate.report)
    assert watch.during == [{support: digest(text)}]
    assert scope_event(bench)["aside"] == []


def test_a_file_whose_only_report_entry_is_a_collection_error_is_set_aside(make_bench, watch):
    bench: Bench = make_bench([])
    tdd.run_setup(bench.wb)
    broken = "tests/test_broken.py"
    text = "import no_such_module_anywhere\n\n\ndef test_x():\n    pass\n"
    commit_files(bench, {PRICING: HEAD_PRICING, broken: text})
    (bench.wb.worktree / NEW_PATH).write_text(FAILS_AT_BASE)
    gate = bench.wb.run_gate(
        "test", bench.wb.cfg.gates.test.command, reports=bench.wb.cfg.gates.test.reports,
        extra_env={"PYTEST_ADDOPTS": "--continue-on-collection-errors"},
    )  # fmt: skip
    assert gate.report is not None and gate.report.collection_errors, gate.reason
    watch.paths = [broken]
    confirmed_by_base_run(bench.wb, {KNOWN: [NEW_ID]}, {NEW_ID}, real=gate.report)
    assert watch.during == [{broken: None}]
    assert scope_event(bench)["aside"] == [broken]
    assert sha_of(bench.wb.worktree / broken) == digest(text)


def test_a_file_that_cannot_be_removed_is_not_listed_as_set_aside(make_bench, monkeypatch):
    bench: Bench = make_bench([])
    _, report = head_run(bench)
    monkeypatch.setattr(base_run, "_unlink", lambda wb, rel, where: None)  # the removal was refused
    confirmed_by_base_run(bench.wb, {KNOWN: [NEW_ID]}, {NEW_ID}, real=report)
    assert scope_event(bench)["aside"] == []


def test_the_limit_reaches_run_gate(make_bench, monkeypatch):
    """The chain `confirmed_by_base_run` -> `run_with_code_of` -> `Workbench.run_gate` carries the limit."""
    bench: Bench = make_bench([])
    _, report = head_run(bench)
    limits: list[int | None] = []
    real_gate = Workbench.run_gate

    def spy(self, name, command, **kwargs):
        if name == "test-base-run":
            limits.append(kwargs.get("timeout_s"))
        return real_gate(self, name, command, **kwargs)

    monkeypatch.setattr(Workbench, "run_gate", spy)
    confirmed_by_base_run(bench.wb, {KNOWN: [NEW_ID]}, {NEW_ID}, real=report, head_seconds=200.0)
    gates = bench.wb.cfg.gates
    expected = min(
        duration_seconds(gates.timeout), max(300, 400, 200 + gates.test_timeout_seconds())
    )  # twice the run, the run plus one test's limit, at least 300s
    assert limits == [expected] and expected > 300
