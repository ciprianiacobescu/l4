"""gate-flake-rerun 1.1 (L4-VER-076, SCN-VER-288..297): step 3 runs a failed gate again when its only failures are a
few pre-existing tests. `settle` is driven with scripted outcomes (a fake `again(name)` and a fake workbench that
records the events: no sandbox); `pre_existing` runs on a small real git repository."""

from collections.abc import Callable
from pathlib import Path

import pytest

from l4.exitcodes import ExitCode, L4Exit
from l4.gates.junit import TestCase, TestReport
from l4.gates.runner import GateResult
from l4.verifier import gate_repeat
from l4.verifier.gate_repeat import FLAKY_TITLE, MAX_REPEAT_FAILURES, pre_existing, repeat_name, settle
from l4.verifier.gates import ALTERED, E2eGateOutcome, TestGateOutcome, _judged
from l4.verifier.types import Severity

COMMAND = "pytest e2e"
A = "e2e.test_signin::test_form"
B = "e2e.test_signin::test_menu"
N = "tests.test_cart::test_new_total"  # a red test of the unit
RED = {N}
ROUND = 4


class Bench:
    """A workbench as `settle` and `_judged` use it: `out_dir` (a log is named relative to its parent) and `emit`."""

    def __init__(self, tmp_path: Path) -> None:
        self.out_dir = tmp_path / ".l4-out" / "x"
        self.events: list[tuple[str, dict]] = []

    def emit(self, event_type: str, /, **data) -> None:
        self.events.append((event_type, data))


@pytest.fixture
def wb(tmp_path: Path) -> Bench:
    return Bench(tmp_path)


def outcome(
    wb: Bench, name: str, statuses: dict[str, str], *, reason: str | None = None, collection: tuple[str, ...] = (),
    report: bool = True, status: str | None = None, key: str = "e2e",
) -> TestGateOutcome:  # fmt: skip
    """The outcome `_judged` gives for a run whose report holds `statuses` (id -> passed/failed/error/skipped)."""
    cases = {i: TestCase(i, s, message="boom" if s in ("failed", "error") else "") for i, s in statuses.items()}
    rep = TestReport(cases, list(collection)) if report else None
    failing = any(s in ("failed", "error") for s in statuses.values())
    executed = any(s != "skipped" for s in statuses.values())
    default = "fail" if failing or not executed or collection or not report else "pass"
    run_status = status or default
    why = reason if reason is not None else ("" if run_status == "pass" else "exit code 1")
    log = wb.out_dir / f"{name}.log"
    result = GateResult(name, run_status, why, 0 if run_status == "pass" else 1, log, rep)  # type: ignore[arg-type]
    return _judged(wb, name, COMMAND, f"gates.{key}.reports", result)  # type: ignore[arg-type]


class Again:
    """The callable that runs the gate again: records the names it is called with, answers from a script."""

    def __init__(self, script: list[TestGateOutcome]) -> None:
        self.script, self.names = list(script), []

    def __call__(self, name: str) -> TestGateOutcome:
        self.names.append(name)
        return self.script.pop(0)


def never_red(test_id: str) -> bool:
    return test_id not in RED


def run_settle(wb, first, script, *, runs=3, must=(), is_pre_existing: Callable[[str], bool] = never_red, gate="e2e"):
    again = Again(script)
    out = settle(
        wb, first, gate=gate, command=COMMAND, must_contain=set(must), again=again, is_pre_existing=is_pre_existing,
        runs=runs, round_no=ROUND,
    )  # fmt: skip
    return out, again


def titles(out: TestGateOutcome) -> list[tuple[str, str]]:
    return [(f.severity.value, f.title) for f in out.findings]


# --- names ------------------------------------------------------------------------------------------------------------


def test_the_names_of_the_repeats():
    assert repeat_name("e2e", 1) == "e2e-repeat-1" and repeat_name("test", 12) == "test-repeat-12"
    assert gate_repeat.is_repeat("test-repeat-2") and gate_repeat.is_repeat("e2e-repeat-10")
    assert not any(
        gate_repeat.is_repeat(n) for n in ("test", "e2e", "base-tests-repeat", "e2e-repeat-", "x-test-repeat-1")
    )
    assert MAX_REPEAT_FAILURES == 5


# --- the repeat loop --------------------------------------------------------------------------------------------------


def test_a_pre_existing_e2e_test_that_fails_once_and_passes_on_the_repeat_is_a_minor_finding(wb):  # SCN-VER-288
    plain = outcome(wb, "e2e", {A: "failed", B: "passed"})
    first = E2eGateOutcome(plain.gate, plain.report, plain.findings, snapshot="<html>")
    second = outcome(wb, "e2e-repeat-1", {A: "passed", B: "passed"})
    out, again = run_settle(wb, first, [second])
    assert again.names == ["e2e-repeat-1"]
    assert out.ok and isinstance(out, E2eGateOutcome) and out.snapshot == "<html>"
    [finding] = out.findings
    assert (finding.severity, finding.source, finding.title) == (
        Severity.MINOR,
        "deterministic",
        FLAKY_TITLE.format(gate="e2e"),
    )
    assert finding.title == "a pre-existing test is flaky in the e2e gate"
    assert finding.detail == f"{A} (failed in run 1, passed in run 2)" and finding.log == first.gate.log
    assert out.report.tests[A].status == "passed" and out.report.tests[A] is second.report.tests[A]
    assert out.report.tests[B] is first.report.tests[B]
    assert out.gate.status == "flaky" and out.gate.name == "e2e" and out.gate.log == first.gate.log
    [row] = out.repeats
    assert (row.name, row.status) == ("e2e-repeat-1", "pass")
    assert out.repeat_note == f"e2e: 2 runs (L4-VER-076); flaky: {A}"
    event = {"round": ROUND, "gate": "e2e", "runs": 2, "flaky": [A], "failing": [], "stopped": "passed"}
    assert wb.events == [("verify.gate_repeat", event)]


def test_a_pre_existing_test_that_fails_in_every_run_stays_a_blocker_after_flaky_repeats_runs(wb):  # SCN-VER-289
    first = outcome(wb, "e2e", {A: "failed"})
    script = [outcome(wb, f"e2e-repeat-{n}", {A: "failed"}) for n in (1, 2, 3)]
    out, again = run_settle(wb, first, script, runs=3)
    assert again.names == ["e2e-repeat-1", "e2e-repeat-2"] and len(again.script) == 1
    assert not out.ok and out.gate.status == "fail"
    [finding] = out.findings
    assert (finding.severity, finding.title, finding.id) == (Severity.BLOCKER, "e2e gate failed", first.findings[0].id)
    assert finding.detail == f"`{COMMAND}` failed (3 runs); failing: {A}" and finding.log == first.gate.log
    assert [r.name for r in out.repeats] == ["e2e-repeat-1", "e2e-repeat-2"]
    assert out.repeat_note == f"e2e: 3 runs (L4-VER-076); still failing: {A}"
    [(_, event)] = wb.events
    assert (event["runs"], event["flaky"], event["failing"], event["stopped"]) == (3, [], [A], "limit")


def test_a_failing_red_test_of_the_unit_is_never_repeated(wb):  # SCN-VER-290
    first = outcome(wb, "e2e", {A: "failed", N: "failed"})
    out, again = run_settle(wb, first, [])
    assert out is first and again.names == [] and wb.events == []
    assert titles(out) == [("blocker", "e2e gate failed")]


def test_flaky_repeats_one_makes_no_repeat(wb):  # SCN-VER-292
    first = outcome(wb, "e2e", {A: "failed"})
    out, again = run_settle(wb, first, [], runs=1)
    assert out is first and again.names == [] and wb.events == []


def test_two_runs_allow_one_repeat(wb):
    first = outcome(wb, "e2e", {A: "failed"})
    out, again = run_settle(
        wb, first, [outcome(wb, "e2e-repeat-1", {A: "failed"}), outcome(wb, "x", {A: "passed"})], runs=2
    )
    assert again.names == ["e2e-repeat-1"] and not out.ok
    assert out.findings[0].detail.endswith(f"failed (2 runs); failing: {A}")


def test_the_repeats_stop_after_the_run_in_which_the_last_candidate_passes(wb):
    first = outcome(wb, "e2e", {A: "failed", B: "failed"})
    script = [
        outcome(wb, "e2e-repeat-1", {A: "passed", B: "failed"}),
        outcome(wb, "e2e-repeat-2", {A: "passed", B: "passed"}),
    ]
    out, again = run_settle(wb, first, script, runs=5)
    assert again.names == ["e2e-repeat-1", "e2e-repeat-2"]
    assert out.ok and out.gate.status == "flaky"
    [finding] = out.findings
    assert (
        finding.detail
        == f"{A} (failed in run 1, passed in runs 2 and 3), {B} (failed in runs 1 and 2, passed in run 3)"
    )
    [(_, event)] = wb.events
    assert (event["runs"], event["flaky"], event["stopped"]) == (3, [A, B], "passed")


def test_a_test_that_fails_only_in_a_repeat_is_flaky_when_pre_existing(wb):  # SCN-VER-293
    first = outcome(wb, "e2e", {A: "failed", B: "passed"})
    second = outcome(wb, "e2e-repeat-1", {A: "passed", B: "failed"})
    out, again = run_settle(wb, first, [second])
    assert again.names == ["e2e-repeat-1"] and out.ok and out.gate.status == "flaky"
    [finding] = out.findings
    assert finding.detail == f"{A} (failed in run 1, passed in run 2), {B} (failed in run 2, passed in run 1)"
    assert out.report.tests[A].status == "passed" and out.report.tests[B].status == "passed"
    [(_, event)] = wb.events
    assert (event["runs"], event["flaky"], event["failing"], event["stopped"]) == (2, [A, B], [], "passed")


def test_a_red_test_that_fails_only_in_a_repeat_is_not_trusted(wb):  # SCN-VER-293
    first = outcome(wb, "e2e", {A: "failed", N: "passed"})
    second = outcome(wb, "e2e-repeat-1", {A: "passed", N: "failed"})
    out, again = run_settle(wb, first, [second, outcome(wb, "never", {A: "passed"})])
    assert again.names == ["e2e-repeat-1"] and not out.ok
    assert titles(out) == [("blocker", "e2e gate failed"), ("minor", "a pre-existing test is flaky in the e2e gate")]
    blocker, minor = out.findings
    assert blocker.detail == f"`{COMMAND}` failed (2 runs); failing: {N}" and minor.detail.startswith(A)
    assert N not in minor.detail
    assert out.gate.status == "fail" and out.report.tests[A].status == "passed"
    assert out.report.tests[N].status == "failed"  # a test that still fails is failing in the report that is handed on
    [(_, event)] = wb.events
    assert (event["flaky"], event["failing"], event["stopped"]) == ([A], [N], "not_pre_existing")


def test_flaky_tests_and_a_test_that_never_passed_give_both_findings(wb):
    first = outcome(wb, "e2e", {A: "failed", B: "failed"})
    second = outcome(wb, "e2e-repeat-1", {A: "passed", B: "failed"})
    third = outcome(wb, "e2e-repeat-2", {A: "passed", B: "failed"})
    out, again = run_settle(wb, first, [second, third])
    assert again.names == ["e2e-repeat-1", "e2e-repeat-2"]
    assert titles(out) == [("blocker", "e2e gate failed"), ("minor", "a pre-existing test is flaky in the e2e gate")]
    assert out.findings[0].detail == f"`{COMMAND}` failed (3 runs); failing: {B}"
    assert out.gate.status == "fail" and not out.ok
    assert out.repeat_note == f"e2e: 3 runs (L4-VER-076); flaky: {A}; still failing: {B}"
    [(_, event)] = wb.events
    assert (event["flaky"], event["failing"], event["stopped"]) == ([A], [B], "limit")


def test_the_flaky_finding_lists_five_ids_and_counts_the_rest(wb):
    failing = [f"e2e.test_a::test_{n}" for n in range(MAX_REPEAT_FAILURES)]
    others = [f"e2e.test_b::test_{n}" for n in range(3)]  # pass in the first run, fail in the repeat
    first = outcome(wb, "e2e", {**{i: "failed" for i in failing}, **{i: "passed" for i in others}})
    second = outcome(wb, "e2e-repeat-1", {**{i: "passed" for i in failing}, **{i: "failed" for i in others}})
    out, _ = run_settle(wb, first, [second])
    assert out.ok
    assert out.findings[0].detail.count("(failed in run") == 5 and out.findings[0].detail.endswith("(+3 more)")
    [(_, event)] = wb.events
    assert event["flaky"] == sorted([*failing, *others])


@pytest.mark.parametrize(
    ("repeat", "must"),
    [
        (dict(report=False), ()),  # no report was read
        (dict(statuses={A: "passed"}, collection=("e2e.test_other",), status="fail"), ()),  # a collection error
        (dict(statuses={A: "passed"}), (N,)),  # a must_contain id the repeat's report does not hold
        (dict(statuses={}, reason="vacuous: 0 tests executed"), ()),  # nothing executed
        (dict(statuses={A: "skipped"}), ()),  # nothing executed
        (dict(statuses={A: "passed"}, status="fail", reason="exit code 1"), ()),  # exit code failed, every test passing
    ],
    ids=["no-report", "collection-error", "must-contain-missing", "empty", "all-skipped", "exit-code-only"],
)
def test_a_repeat_with_no_usable_report_ends_the_repeats(wb, repeat, must):  # SCN-VER-294
    first = outcome(wb, "e2e", {A: "failed", **{i: "passed" for i in must}})
    repeat = {"statuses": {}, **repeat}
    second = outcome(wb, "e2e-repeat-1", repeat.pop("statuses"), **repeat)
    out, again = run_settle(wb, first, [second, outcome(wb, "never", {A: "passed"})], must=must)
    assert again.names == ["e2e-repeat-1"]
    assert titles(out) == [("blocker", "e2e gate failed")] and not out.ok
    assert A in out.findings[0].detail and out.findings[0].log == first.gate.log
    [(_, event)] = wb.events
    assert (event["runs"], event["flaky"], event["failing"], event["stopped"]) == (2, [], [A], "unusable")
    assert out.report.tests[A].status == "failed"  # the unusable run's cases count for nothing
    assert [r.name for r in out.repeats] == ["e2e-repeat-1"]


def test_an_unusable_repeat_does_not_take_back_a_flaky_verdict_of_an_earlier_one(wb):  # SCN-VER-294
    first = outcome(wb, "e2e", {A: "failed", B: "failed"})
    second = outcome(wb, "e2e-repeat-1", {A: "passed", B: "failed"})
    third = outcome(wb, "e2e-repeat-2", {}, report=False)
    out, again = run_settle(wb, first, [second, third], runs=5)
    assert again.names == ["e2e-repeat-1", "e2e-repeat-2"]
    assert out.findings[0].detail == f"`{COMMAND}` failed (3 runs); failing: {B}"
    assert out.findings[1].detail == f"{A} (failed in run 1, passed in run 2)"
    [(_, event)] = wb.events
    assert (event["flaky"], event["failing"], event["stopped"]) == ([A], [B], "unusable")


def test_a_repeat_whose_report_is_altered_adds_that_blocker_and_stops(wb):  # SCN-VER-294
    first = outcome(wb, "e2e", {A: "failed"})
    second = outcome(wb, "e2e-repeat-1", {A: "passed"}, status="fail", reason=f"{ALTERED}: junit.xml")
    assert [f.title for f in second.findings] == [ALTERED]
    out, again = run_settle(wb, first, [second, outcome(wb, "never", {A: "passed"})])
    assert again.names == ["e2e-repeat-1"] and not out.ok
    assert titles(out) == [("blocker", "e2e gate failed"), ("blocker", ALTERED)]
    [(_, event)] = wb.events
    assert (event["flaky"], event["failing"], event["stopped"]) == ([], [A], "unusable")


# --- when the first run is not repeated -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("first", "must"),
    [
        (dict(statuses={A: "passed"}, collection=("e2e.test_other",)), ()),
        (dict(statuses={A: "failed"}, collection=("e2e.test_other",)), ()),
        (dict(statuses={A: "skipped"}), ()),
        (dict(statuses={}), ()),
        (dict(statuses={A: "failed"}, report=False), ()),
        (dict(statuses={A: "failed"}, reason=f"{ALTERED}: junit.xml"), ()),
        (dict(statuses={A: "failed"}), (N,)),  # a must_contain id is missing from the report
        (dict(statuses={A: "passed"}, status="fail"), ()),  # failed on its exit code alone
        (dict(statuses={A: "passed"}), ()),  # a passing gate
        (dict(statuses={f"e2e.test_{n}::test_x": "failed" for n in range(MAX_REPEAT_FAILURES + 1)}), ()),
    ],
    ids=[
        "collection-error-pass",
        "collection-error-failing",
        "nothing-executed",
        "empty",
        "no-report",
        "altered",
        "must-contain-missing",
        "exit-code-only",
        "passed",
        "six-failures",
    ],
)
def test_a_gate_that_failed_another_way_is_not_repeated(wb, first, must):  # SCN-VER-296
    first = {"statuses": {}, **first}
    out, again = run_settle(wb, outcome(wb, "e2e", first.pop("statuses"), **first), [], must=must)
    assert again.names == [] and wb.events == [] and out.repeats == []


def test_five_failing_pre_existing_tests_are_repeated(wb):  # SCN-VER-296
    ids = [f"e2e.test_{n}::test_x" for n in range(MAX_REPEAT_FAILURES)]
    out, again = run_settle(
        wb, outcome(wb, "e2e", {i: "failed" for i in ids}), [outcome(wb, "r", {i: "passed" for i in ids})]
    )
    assert again.names == ["e2e-repeat-1"] and out.ok


def test_a_failing_test_whose_file_is_not_found_is_not_repeated(wb):  # SCN-VER-296
    first = outcome(wb, "e2e", {A: "failed", B: "failed"})
    out, again = run_settle(wb, first, [], is_pre_existing=lambda t: t != B)
    assert out is first and again.names == []


def test_the_test_gate_is_repeated_too(wb):
    test_id = "tests.test_a::test_x"
    first = outcome(wb, "test", {test_id: "failed", N: "passed"}, key="test")
    second = outcome(wb, "test-repeat-1", {test_id: "passed", N: "passed"}, key="test")
    out, again = run_settle(wb, first, [second], gate="test", must={N})
    assert again.names == ["test-repeat-1"] and out.ok
    assert out.findings[0].title == "a pre-existing test is flaky in the test gate"
    assert out.report.tests[N] is first.report.tests[N] and out.report.tests[test_id] is second.report.tests[test_id]
    assert wb.events[0][1]["gate"] == "test"


def test_a_repeat_that_misses_a_must_contain_id_is_unusable(wb):
    test_id = "tests.test_a::test_x"
    first = outcome(wb, "test", {test_id: "failed", N: "passed"}, key="test")
    second = outcome(wb, "test-repeat-1", {test_id: "passed"}, key="test")  # the new test did not run in it
    out, _ = run_settle(wb, first, [second], gate="test", must={N})
    assert not out.ok and wb.events[0][1]["stopped"] == "unusable"


# --- the server of a repeat -------------------------------------------------------------------------------------------


def test_a_server_that_never_gets_ready_in_a_repeat_is_not_swallowed(wb):  # SCN-VER-297
    first = outcome(wb, "e2e", {A: "failed"})

    def again(name: str) -> TestGateOutcome:
        raise L4Exit(ExitCode.INTERNAL_ERROR, "gates.e2e: the server was not ready")

    with pytest.raises(L4Exit) as err:
        settle(
            wb,
            first,
            gate="e2e",
            command=COMMAND,
            must_contain=set(),
            again=again,
            is_pre_existing=never_red,
            runs=3,
            round_no=ROUND,
        )
    assert err.value.code == ExitCode.INTERNAL_ERROR and wb.events == []


# --- pre_existing -----------------------------------------------------------------------------------------------------


class CountingGit:
    """The `Git` a test hands `pre_existing`, counting the commands it runs."""

    def __init__(self, git) -> None:
        self._git, self.calls = git, 0

    def run_bytes(self, *args: str) -> bytes:
        self.calls += 1
        return self._git.run_bytes(*args)

    def __getattr__(self, name):
        return getattr(self._git, name)


@pytest.fixture
def repo(tmp_path, raw, git_for):
    """A base with two Python test files, a TypeScript spec and a source file; the head changes `tests/test_cart.py`
    (a harness commit), `e2e/other.spec.ts` (a person's commit) and adds `tests/test_new.py`."""
    root = tmp_path / "repo"
    root.mkdir()
    raw(root, "init", "-q")

    def write(files: dict[str, str]) -> None:
        for path, text in files.items():
            (root / path).parent.mkdir(parents=True, exist_ok=True)
            (root / path).write_text(text)

    write(
        {
            "tests/test_cart.py": "def test_total(): pass\n",
            "tests/test_signin.py": "def test_form(): pass\n",
            "e2e/signin.spec.ts": "test('sign in shows the form', () => {})\n",
            "e2e/other.spec.ts": "test('x', () => {})\n",
            "src/app.py": "x = 1\n",
        }
    )
    raw(root, "add", "-A")
    raw(root, "commit", "-q", "-m", "base")
    base = raw(root, "rev-parse", "HEAD").strip()
    write({"tests/test_cart.py": "def test_total(): assert 1\n", "tests/test_new.py": "def test_new(): pass\n"})
    raw(root, "add", "-A")
    raw(root, "-c", "user.name=harness", "commit", "-q", "-m", "harness commit")
    write({"e2e/other.spec.ts": "test('x', () => { /* edited */ })\n"})
    raw(root, "add", "-A")
    raw(root, "-c", "user.name=a person", "commit", "-q", "-m", "person commit")
    return root, base, raw(root, "rev-parse", "HEAD").strip(), git_for(root)


def test_a_test_in_a_file_the_head_does_not_change_is_pre_existing(repo):
    root, base, head, git = repo
    check = pre_existing(git, base, head, {"tests.test_new::test_new"})
    assert check("tests.test_signin::test_form")  # a pytest id (a dotted module)
    assert check("e2e.signin.spec.ts::sign in shows the form")  # a TypeScript reporter id (dots for slashes)
    assert check("e2e/signin.spec.ts::sign in shows the form")  # the path itself


def test_a_test_in_a_file_a_commit_of_the_unit_changed_is_not_pre_existing(repo):  # SCN-VER-291
    root, base, head, git = repo
    check = pre_existing(git, base, head, set())
    assert not check("tests.test_cart::test_total")  # a harness commit changed the file
    assert not check("e2e.other.spec.ts::x")  # a person's commit changed the file
    assert not check("tests.test_new::test_new")  # the unit added the file


def test_a_red_test_a_test_with_no_file_and_a_go_id_are_not_pre_existing(repo):
    root, base, head, git = repo
    check = pre_existing(git, base, head, {"tests.test_signin::test_form"})
    assert not check("tests.test_signin::test_form")  # a red test of the unit, whatever its file
    assert not check("tests.test_signin::test_form (n=1)")  # a subtest of it: folded to the test
    assert not check("tests.test_gone::test_x")  # no file
    assert not check("example.com/pkg/cart::TestTotal")  # a Go id is not mapped
    assert pre_existing(git, base, head, set())("tests.test_signin::test_form")


def test_an_id_that_matches_a_changed_and_an_unchanged_path_prefers_the_changed_one(tmp_path, raw, git_for):
    root = tmp_path / "ambiguous"
    root.mkdir()
    raw(root, "init", "-q")
    for path in ("a/e2e/spec.test.ts", "b/e2e/spec.test.ts"):
        (root / path).parent.mkdir(parents=True)
        (root / path).write_text("test('x', () => {})\n")
    raw(root, "add", "-A")
    raw(root, "commit", "-q", "-m", "base")
    base = raw(root, "rev-parse", "HEAD").strip()
    (root / "b/e2e/spec.test.ts").write_text("test('x', () => { /* edited */ })\n")
    raw(root, "add", "-A")
    raw(root, "commit", "-q", "-m", "head")
    head = raw(root, "rev-parse", "HEAD").strip()
    # `e2e.spec.test.ts` ends two paths; the one the unit changed is chosen, so the test is the unit's
    assert not pre_existing(git_for(root), base, head, set())("e2e.spec.test.ts::x")


def test_the_tree_and_the_diff_are_read_once_on_the_first_call_only(repo):
    root, base, head, git = repo
    counting = CountingGit(git)
    check = pre_existing(counting, base, head, set())
    assert counting.calls == 0
    check("tests.test_signin::test_form")
    after_first = counting.calls
    assert after_first == 2  # ls-tree and diff
    check("tests.test_cart::test_total")
    check("e2e.signin.spec.ts::sign in shows the form")
    assert counting.calls == after_first


def test_a_git_error_makes_every_test_not_pre_existing(repo):
    root, base, head, git = repo
    check = pre_existing(git, "0" * 40, head, set())
    assert not check("tests.test_signin::test_form")
