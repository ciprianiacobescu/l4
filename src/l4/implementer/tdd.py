"""One red or green agent step and its checks (SPEC L4-IMP-002, L4-IMP-006, L4-IMP-007).

Every step: `gates.setup` (G2), the agent in the agent sandbox, the protected-path revert, the checks, and only then a
checkpoint commit. Red is valid iff every new test fails and nothing that passed at the base fails. Green is valid iff
every red test passes and nothing that passed at the base fails. Both phases also run `gates.lint` and
`gates.typecheck`: a gate that passed at the step base must still pass (red, so a lint error is never frozen into a
test file; green), one that already failed at the base is a `gate.static_baseline_failed` warning.
Red also rebuilds production files (`stubs`), checks failure kinds and criteria, and proves each criterion
discriminating (`discrimination`). M1: implementer-tdd-loop 1.9 (repair prompt), 1.25 (TDD exemptions), the scratch
checkout of the red commit for green (a).
"""

import hashlib
import logging
import re
import shlex
import shutil
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal

from l4.accepted import read_accepted
from l4.agents.activity import ActivityWatch, Beat, ago, beat_text
from l4.agents.base import PermissionPolicy, RunRequest, RunResult, denial_facts
from l4.ci.failing_step import (
    STEP_GATE_PREFIX,
    ChoreCiStep,
    chore_ci_steps,
    last_ci_steps,
    reproduction,
)
from l4.ci.gitlab_jobs import GITLAB_CI_RELPATH
from l4.clarifier.inject import RenderedAnswers, render_answer_blocks
from l4.config.schema import duration_seconds
from l4.evidence.scope import file_kind
from l4.exitcodes import ExitCode, L4Exit
from l4.fsutil import UnsafeFile, reject_symlinks
from l4.gates.coverage import cov_env, is_python_gate, project_python
from l4.gates.e2e import e2e_configured, e2e_test_dir
from l4.gates.hang import TIMEOUT_MARKER, HungTest, hung_tests
from l4.gates.junit import TestCase, TestReport
from l4.gates.runner import GateResult
from l4.gates.trace import trace_env
from l4.implementer import resultalias
from l4.implementer.base_run import VIA as BASE_VIA
from l4.implementer.base_run import BaseRunResult, confirmed_by_base_run, failure_message
from l4.implementer.discrimination import (
    PROOF_PRE_SATISFIED,
    PROOF_RED_ASSERTION,
    PROOF_ZERO_VALUE,
    PreSatisfied,
    _test_file,
    confirm_pre_satisfied,
    discriminate_extra,
    fails_at_red,
    fails_on_zero,
    head_stub_modules,
    no_assertion_failure,
    unit_base,
    vacuity_check,
)
from l4.implementer.earlier_red import VIA, EarlierRed, confirmed_by_earlier_red
from l4.implementer.excerpt import failure_excerpt, lint_excerpt
from l4.implementer.guards import (
    IGNORE_FILE_GLOBS,
    FreezeManifest,
    appended_only,
    build_manifest,
    manifest_at_head,
    restore_frozen,
    restore_test_paths,
)
from l4.implementer.normalize import StepFacts, find_result, normalize
from l4.implementer.opened import check_opened, unit_modules
from l4.implementer.prompt import PromptContext, collect_sources, data_block, defuse, render_prompt, result_values_line
from l4.implementer.reopen import is_reopened, pending_stale
from l4.implementer.result import (
    RESULT_SCHEMA,
    ImplementerResult,
    ResultInvalid,
    ResultQuestion,
    TraceRules,
    check_criteria,
    parse_result,
    trace_rules,
)
from l4.implementer.resultalias import RESULT_ALIAS_PATH
from l4.implementer.retrynote import RetryNote, note_block, retry_note
from l4.implementer.stubs import ProductionGuard, enforce_red_scope, restore_to_base
from l4.implementer.tasks import task_scope, tick_completed_parents
from l4.implementer.unfreeze import Unfreeze, named_by_task, unfrozen
from l4.implementer.uvseed import ensure_uv_seed
from l4.implementer.workbench import PreviousAttempt, Workbench
from l4.memory.inject import Injection, inject_for_task, task_paths
from l4.sandbox.env import build_agent_env
from l4.security.protected import glob_match, revert_protected
from l4.specs.base import Framework, Marker, Task
from l4.specs.criteria import trace_ids
from l4.specs.fixmark import read_fix_marker
from l4.specs.followup import read_follow_up_marker
from l4.specs.kiro import parse_kiro_tasks
from l4.specs.markers import MAX_TASKS_BYTES
from l4.specs.openspec import parse_openspec_tasks
from l4.specs.questions import QUESTIONS_FILENAME, QuestionsFile
from l4.specs.tasks_text import task_context
from l4.state.ledger import LedgerEvent, read_ledger
from l4.verifier.scan import task_tags
from l4.yolo.digest import RevisionMissing, unit_digest

log = logging.getLogger("l4.implementer")
beat_log = logging.getLogger("l4")  # the progress trace's logger: the heartbeat line looks like its lines
Phase = Literal["red", "green", "single"]
Status = Literal["ok", "failed", "blocked"]
LIMIT_STATUSES = ("quota", "rate_limited", "auth")
MAX_LISTED = 5
HANG_EXIT = 70  # the exit code `l4_trace` ends a run with after a hard hang
HANG_FRAME_CHARS = 1500
MAX_LOG_READ_CHARS = 200_000
CI_REASON_LINES = 15  # the end of a failing CI step's output that the retry prompt shows


class SetupFailed(L4Exit):
    """`gates.setup` failed: the environment is not ready (exit 3). The phase does not change, so a rerun resumes."""

    def __init__(self, message: str) -> None:
        super().__init__(ExitCode.DOCTOR_FAILED, message)


class BaselineFailed(Exception):
    """The test gate cannot run at the step base: no report, a timeout or a collection error. The unit is halted."""


class RoleLimit(Exception):
    """The agent reported a usage limit or lost its login mid-run: the role is unavailable (exit 12)."""

    def __init__(self, result: RunResult) -> None:
        super().__init__(result.detail or result.status)
        self.result = result


Excerpter = Callable[[TestReport, Sequence[str]], str]  # (report, test ids) -> the bounded, redacted failure text


@dataclass(frozen=True)
class RedVerdict:
    ok: bool
    reason: str = ""
    excerpt: str = ""  # why the named tests failed (L4-IMP-008): for the next prompt only, not the ledger


@dataclass
class StepOutcome:
    kind: Status
    result: ImplementerResult | None = None
    reason: str = ""
    excerpt: str = ""  # harness text for the next prompt (the allowed result values after `result invalid`)
    dropped_questions: int = 0  # malformed questions that the normalization dropped from a `blocked` result

    @property
    def blocked_summary(self) -> str:
        """The summary that becomes the one question of a `blocked` step with none (L4-IMP-021)."""
        summary = self.result.summary if self.result else ""
        if not self.dropped_questions:
            return summary
        return f"{summary} ({self.dropped_questions} malformed questions were dropped)"


@dataclass
class RedOutcome:
    status: Status | Literal["already_satisfied"]
    reason: str = ""
    sha: str | None = None
    new_ids: frozenset[str] = frozenset()
    manifest: FreezeManifest | None = None
    base_report: TestReport | None = None
    questions: Sequence[ResultQuestion] = field(default_factory=list)
    summary: str = ""
    criteria: dict[str, dict[str, Any]] = field(default_factory=dict)  # criterion -> {tests, proof}
    excerpt: str = ""  # the failure text behind `reason`, for the next prompt
    superseded: frozenset[str] = frozenset()  # stale tests (L4-OPS-015) this red step removed or broke on purpose


@dataclass(frozen=True)
class StaleTests:
    """The tests a reopened task's red step may replace (L4-OPS-015): base test id -> the stale criterion ids it traces,
    and the changes (`reopen.stale_changes`) the red prompt shows."""

    tests: Mapping[str, tuple[str, ...]]
    changes: tuple[Mapping[str, Any], ...]


@dataclass
class GreenOutcome:
    status: Status
    reason: str = ""
    sha: str | None = None
    questions: Sequence[ResultQuestion] = field(default_factory=list)
    summary: str = ""
    excerpt: str = ""  # the failure text behind `reason`, for the next prompt
    hung: tuple[HungTest, ...] = ()  # tests of the gate run that hit the per-test limit (SPEC L4-GAT-004)


def gate_hung(gate: GateResult) -> list[HungTest]:
    """The tests that hit `gates.test_timeout` in this gate run. The log is read only when the run ended without a
    complete report (a hard hang ends it), so a normal run costs nothing."""
    log = ""
    if gate.report is None or gate.timed_out or gate.exit_code == HANG_EXIT:
        try:
            log = gate.log_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            log = ""
    return hung_tests(gate.report, log)


def hang_reason(hung: Sequence[HungTest]) -> str:
    return (
        f"{'a test' if len(hung) == 1 else 'tests'} hung and hit the per-test limit (gates.test_timeout): "
        f"{_list([h.id for h in hung])}"
    )


def hang_excerpt(hung: Sequence[HungTest]) -> str:
    """Where each hung test was waiting, for the next prompt (bounded)."""
    return "\n\n".join(f"{h.id} was waiting here:\n{h.frame[-HANG_FRAME_CHARS:]}" for h in hung if h.frame)


def _matches(globs: Sequence[str], path: str) -> bool:
    return any(glob_match(glob, path) for glob in globs)


def _list(ids: Sequence[str]) -> str:
    shown = ", ".join(sorted(ids)[:MAX_LISTED])
    return shown + (f" (+{len(ids) - MAX_LISTED} more)" if len(ids) > MAX_LISTED else "")


def new_test_ids(base: TestReport, head: TestReport) -> set[str]:
    return set(head.tests) - set(base.tests)


def stale_tests(base: TestReport, stale_ids: Collection[str]) -> dict[str, tuple[str, ...]]:
    """The tests of the base report whose trace (`trace_ids`: the `l4` marker and the ids in the name, L4-CRT-002)
    holds a stale criterion id, each with those ids (L4-OPS-015, design D14 "Stale tests"). Nothing for no stale id."""
    if not stale_ids:
        return {}
    found = {i: tuple(sorted(trace_ids(c) & set(stale_ids))) for i, c in base.tests.items()}
    return {i: ids for i, ids in found.items() if ids}


def stale_for(wb: Workbench, task: Task, base: TestReport) -> StaleTests | None:
    """The stale tests of `task` at the base of its red step: those that trace an id `tasks.reopened` recorded for it
    (`pending_stale`) and no `task.done` has cleared. None when there are none: every other test stays protected."""
    changes = pending_stale(_ledger_events(wb), task.key)
    tests = stale_tests(base, {str(c["old_id"]) for c in changes})
    return StaleTests(tests, tuple(changes)) if tests else None


def unchanged_criteria(wb: Workbench, task: Task, base: TestReport) -> frozenset[str]:
    """The criteria whose tests already exist and that a spec edit left alone, for the red step of a reopened task
    (L4-OPS-015): the ids the base tests trace, less the NEW ids of the changed criteria. Empty for a task no
    `tasks.reopened` holds open: a normal red step needs a new test for every criterion it cites."""
    events = _ledger_events(wb)
    if not is_reopened(events, task.key):
        return frozenset()
    changed = {str(c["new_id"]) for c in pending_stale(events, task.key) if c.get("new_id")}
    return frozenset({i for case in base.tests.values() for i in trace_ids(case)} - changed)


def _first_line(case: TestCase) -> str:
    return (case.message.splitlines() or [case.status])[0][:80]


_IMPORT_ADVICE = (
    "A test that blocks an import on purpose sees the code under test raise it: catch `ImportError` (and "
    "`SystemExit`) in the test and call `pytest.fail(...)` with what should have happened"
)
_ERROR_NAME = re.compile(r"\b(?:\w+\.)*([A-Z]\w*(?:Error|Exit|Exception))\b")


def _error_name(case: TestCase) -> str:
    found = _ERROR_NAME.search((case.message.splitlines() or [""])[0])
    return found.group(1) if found else ""


def _red_advice(head: TestReport, wrong: Sequence[str], rules: TraceRules | None = None) -> str:
    """The retry advice for tests that fail by the wrong kind of error, by exception name, each piece once (live
    M1.8 job 5561: an import error was told to add a guarded stub for a TypeError). The wording follows the test
    gate (`rules`, from `trace_rules`; pytest when absent); the import advice is Python's and only pytest gets it."""
    rules = rules or trace_rules("pytest")
    pytest_gate = rules.advice_other == trace_rules("pytest").advice_other
    imports = {"ImportError", "ModuleNotFoundError", "SystemExit"} if pytest_gate else set()
    names = {_error_name(head.tests[i]) for i in wrong}
    advice = []
    if names & imports:
        advice.append(_IMPORT_ADVICE)
    if "TypeError" in names:
        advice.append(rules.advice_guarded)
    if names - imports - {"TypeError"}:
        advice.append(rules.advice_other)
    return ". ".join(advice)


NO_NEW_TEST = (
    "no new test: no test with a new name was added. Editing or re-tagging an existing test creates no new test; "
    "write a new test function (a new name) for each criterion. If the behaviour already exists, the new tests pass "
    "against it: report `tdd_exemption: already_satisfied` and the harness checks that they discriminate"
)


def classify_red(
    base: TestReport,
    head: TestReport,
    *,
    test_files_changed: bool,
    tests_added: Sequence[str] = (),
    failure_kinds: bool = False,
    allowed_passing: Collection[str] = (),
    excerpt: Excerpter | None = None,
    rules: TraceRules | None = None,
    superseded: Collection[str] = (),
) -> RedVerdict:
    """The failure reasons, in order (design D3.4); the first that holds is returned. `superseded`: the stale tests
    of a reopened task (`stale_tests`, L4-OPS-015) may be gone or fail, they are not regressions. `allowed_passing`:
    the new tests of a confirmed pre-satisfied criterion may pass. `failure_kinds`: every other new test must fail by
    assertion or with the stub's NotImplementedError; any other error is reported by name (SPEC check 3). `excerpt`
    turns the named tests into the failure text of the retry prompt."""

    def why(ids: Sequence[str]) -> str:
        return excerpt(head, ids) if excerpt is not None else ""

    new = new_test_ids(base, head)
    broken_modules = set(head.collection_errors) - set(base.collection_errors)
    if not new and not test_files_changed and not tests_added and not broken_modules:
        return RedVerdict(False, "no tests added")
    regressed = sorted(
        i for i in base.ids_with("passed")
        if (i not in head.tests or head.tests[i].status != "passed") and i not in superseded
    )  # fmt: skip
    if not new and not broken_modules and regressed:  # live M1.11 job 5810: an existing test edited in place
        return RedVerdict(
            False,
            f"no new test: existing tests were changed and now fail: {_list(regressed)}. A red test is a new test "
            "with a new name; a test that passed at the base must still pass",
            why(regressed),
        )
    if broken_modules:
        return RedVerdict(False, f"tests not collected individually: {_list(sorted(broken_modules))}")
    if not new:  # every test was collected, but none has a name the base did not have (Kiro e2e H2, task 2.2)
        return RedVerdict(False, NO_NEW_TEST)
    passing = sorted(i for i in new if head.tests[i].status in ("passed", "skipped") and i not in allowed_passing)
    if passing:
        return RedVerdict(False, f"new tests passed before implementation: {_list(passing)}")
    hung = sorted(
        i for i in new if head.tests[i].status in ("failed", "error") and TIMEOUT_MARKER in head.tests[i].message
    )
    if hung:  # `Failed: l4-test-timeout:` reads as an assertion, but a test that hangs in red proves nothing (W-D1)
        return RedVerdict(
            False,
            f"new tests hang instead of failing: {_list(hung)}. A red test fails fast: bound every blocking read and "
            "let the missing behaviour fail an assertion or raise NotImplementedError",
            why(hung),
        )
    wrong = sorted(
        i for i in new if head.tests[i].status in ("failed", "error") and head.tests[i].failure_kind in (None, "other")
    )
    if failure_kinds and wrong:
        shown = "; ".join(f"{i} ({_first_line(head.tests[i])})" for i in wrong[:MAX_LISTED])
        return RedVerdict(
            False,
            f"new tests fail with an error that is neither an assertion nor NotImplementedError: {shown}. "
            + _red_advice(head, wrong, rules),
            why(wrong),
        )
    if regressed:
        return RedVerdict(False, f"red broke existing tests: {_list(regressed)}", why(regressed))
    return RedVerdict(True)


def green_failures(
    base: TestReport, red_ids: Sequence[str], gate: GateResult, superseded: Collection[str] = ()
) -> tuple[str, list[str]]:
    """Why the green gate run is not acceptable (empty when it is), and the ids of the tests the reason names.
    `superseded`: the stale tests the red step replaced (L4-OPS-015) are not regressions."""
    report = gate.report
    if hung := gate_hung(gate):
        return hang_reason(hung), [h.id for h in hung]
    if gate.timed_out:
        return gate.reason, []
    if report is None:
        return f"the test gate produced no readable report ({gate.reason})", []
    if report.collection_errors:
        return f"tests not collected: {_list(report.collection_errors)}", []
    if report.executed == 0:
        return "vacuous: 0 tests executed", []
    failing = [i for i in red_ids if i not in report.tests or report.tests[i].status != "passed"]
    if failing:
        return f"red tests still failing: {_list(failing)}", failing
    regressed = [
        i for i in base.ids_with("passed")
        if (i not in report.tests or report.tests[i].status != "passed") and i not in superseded
    ]  # fmt: skip
    if regressed:
        return f"green broke existing tests: {_list(regressed)}", regressed
    known = set(base.tests) | set(red_ids)
    added = [i for i, c in report.tests.items() if i not in known and c.status in ("failed", "error")]
    if added:  # SPEC 7.2 green (b): no new failures relative to the base
        return f"new failing tests added in green: {_list(added)}", added
    return "", []


def check_green(base: TestReport, red_ids: Sequence[str], gate: GateResult) -> str:
    """Why the green gate run is not acceptable; empty when it is."""
    return green_failures(base, red_ids, gate)[0]


def excerpter(wb: Workbench) -> Excerpter:
    """The failure text of named tests of a report, as the retry prompt shows it (decision 1): paths relative to the
    worktree, the gate's tmp root masked, the workbench's redactor applied."""
    return lambda report, ids: failure_excerpt(
        report, ids, worktree=wb.worktree, tmp_root=wb.unit_cache / "gate-tmp", redact=wb.redactor.redact_text
    )


def run_setup(wb: Workbench) -> None:
    """G2: dependencies are installed before the baseline and before every agent step, with the network shared and
    the unit's cache writable, because the agent sandbox cannot download and `uv run` cannot write its cache.
    Not repeated at a HEAD it already ran at when no agent has touched the checkout since."""
    head = wb.head()
    if wb.setup_at == head:
        return
    if not wb.seed_checked:  # a unit whose uv cache is new starts from the project's seed (M1.11 W10)
        wb.seed_checked = True
        ensure_uv_seed(wb)
    for command in wb.cfg.gates.setup:
        result = wb.run_gate("setup", command, network=True)
        if result.status != "pass":
            raise SetupFailed(f"gates.setup failed ({result.reason}); see {result.log_path}")
    wb.setup_at = head
    check_coverage_after_setup(wb)


def check_coverage_after_setup(wb: Workbench) -> None:
    """COV-001 once the project environment exists (live M1.6 job 5535: the CI doctor runs before `gates.setup` creates
    `.venv`, so its check said `skip`). The first `gates.setup` of a workbench is followed by one `import coverage` with
    the interpreter the unit gate runs, as a gate (the same sandbox as the tests). The answer is a `doctor.check` event
    and a console line; it never fails the run (a missing coverage.py makes diff coverage `not_run` with its own
    reason, and the evidence says so)."""
    if wb.coverage_checked or wb.cfg.verifier.evidence.diff_coverage.mode == "off" or not wb.cfg.gates.setup:
        return  # no setup commands: the environment is the repository's own, which the doctor looked at already
    wb.coverage_checked = True
    path = wb.host_env.get("PATH")
    python = project_python(wb.cfg, wb.worktree, lambda name: shutil.which(name, path=path))
    if python is None and not is_python_gate(wb.cfg.gates.test.command):
        status, message = "skip", "no python test gate: diff coverage does not apply"
    elif python is None:
        status, message = "skip", "no project interpreter after gates.setup (gates.test.command or .venv/bin/python)"
    else:
        shown = python.relative_to(wb.worktree).as_posix() if python.is_relative_to(wb.worktree) else str(python)
        done = wb.run_gate("coverage-check", shlex.join([shown, "-c", "import coverage"]))
        if done.status == "pass":
            status, message = "pass", f"coverage.py imports in {shown}"
        else:
            status = "fail"
            message = f"coverage.py is not importable by {shown}: diff coverage will be recorded not_run"
    if status == "fail":
        log.warning("%s: COV-001: %s; add coverage to the project's dev dependencies", wb.ref.id, message)
    wb.emit("doctor.check", id="COV-001", status=status, message=message, when="after gates.setup")


def run_static_gates(wb: Workbench, *, tag: str = "") -> dict[tuple[str, str], str]:
    """Every `gates.lint` and `gates.typecheck` command, none skipped: {(gate, command): failure text}, empty when all
    pass. The text carries the head and the summary line of the (already redacted) log, bounded and with repeated
    lines kept once (`lint_excerpt`), so the agent can fix what the linter said."""
    failures: dict[tuple[str, str], str] = {}
    for name, commands in (("lint", wb.cfg.gates.lint), ("typecheck", wb.cfg.gates.typecheck)):
        for command in commands:
            result = wb.run_gate(f"{name}{tag}", command)
            if result.status != "pass":
                log_text = result.log_path.read_text(encoding="utf-8", errors="replace")[-MAX_LOG_READ_CHARS:]
                failures[(name, command)] = (
                    f"{name} gate `{command}` failed ({result.reason}):\n{lint_excerpt(log_text)}"
                )
    return failures


def static_baseline(wb: Workbench, base_sha: str) -> dict[tuple[str, str], str]:
    """L4-IMP-002/003: the static gates at the step base, once per commit. A gate that fails here is not the agent's
    to fix: only a gate that passed at the base can make a step fail."""
    if base_sha not in wb.static_baselines:
        with wb.at_clean_head():
            wb.static_baselines[base_sha] = run_static_gates(wb, tag="-baseline")
    return wb.static_baselines[base_sha]


def worse_static_gates(wb: Workbench, base_sha: str, phase: Phase) -> str:
    """Failure text of the static gates that passed at `base_sha` and fail now; empty when nothing got worse. Gates
    that already failed at the base are recorded as a `gate.static_baseline_failed` warning and do not count."""
    inherited = static_baseline(wb, base_sha)
    now = run_static_gates(wb)
    for key, text in now.items():
        if key in inherited:
            wb.emit("gate.static_baseline_failed", phase=phase, name=key[0], command=key[1], output=text)
    return "\n".join(text for key, text in now.items() if key not in inherited)


def baseline(wb: Workbench, base_sha: str) -> TestReport:
    """The test gate at the step base, once per commit. Failing tests are recorded, not fatal: red compares sets."""
    if base_sha in wb.baselines:
        return wb.baselines[base_sha]
    with wb.at_clean_head():
        run_setup(wb)
        gate = wb.run_gate("baseline", wb.cfg.gates.test.command, reports=wb.cfg.gates.test.reports)
    if gate.report is None:
        raise BaselineFailed(f"the test gate cannot run at the base: {gate.reason}")
    if gate.report.collection_errors:
        raise BaselineFailed(f"tests do not collect at the base: {_list(gate.report.collection_errors)}")
    wb.baselines[base_sha] = gate.report
    return gate.report


def _answers(wb: Workbench, task: Task) -> RenderedAnswers:
    """The answered questions that hold this task, read from the file as it is now (SPEC L4-CLR-006)."""
    file = QuestionsFile.load(wb.ref.path / QUESTIONS_FILENAME)
    if file is None:
        return RenderedAnswers("", ())
    scope = task_scope(wb.provider.tasks(wb.ref), task.key)
    return render_answer_blocks(file.questions, wb.redactor.redact_text, tasks=scope)


MAX_REASON = 1000  # one failure headline of an escalation block, cut (escalate-and-note D9)


def _escalation_block(previous: PreviousAttempt) -> tuple[tuple[str, str], ...]:
    """The block for the profile that an escalation gave the step to: who failed, how often, and why, oldest first."""
    clean = (re.sub(r"[^A-Za-z0-9._-]", "_", v) for v in (previous.profile, previous.phase or ""))
    who, phase = clean
    lines = [
        f"The agent before you (profile {previous.profile}) failed the {previous.phase} step of this task "
        f"{len(previous.failures)} times, so the harness gave the step to you. Its uncommitted changes were "
        "discarded; the commits already on the branch are kept. You start from the checkout as it is now, in a new "
        "session, with no transcript of those attempts. The harness rejected them for these reasons, oldest first:",
        *(f"{n}. ({profile}) {reason[:MAX_REASON]}" for n, (profile, reason) in enumerate(previous.failures, 1)),
    ]
    attrs = f'kind="previous-attempt" profile="{who}" reason="escalation" phase="{phase}"'
    return (("previous attempt", f"<l4:data {attrs}>\n{defuse(chr(10).join(lines))}\n</l4:data>"),)


def _previous_attempt_block(wb: Workbench, task: Task, phase: str | None = None) -> tuple[tuple[str, str], ...]:
    """After a mid-run fallback, the task's next step starts in a fresh session: say who ran before and why it
    stopped (implementer-tdd-loop 2.25, reduced: no transcript). After an escalation, only the steps of the phase
    that failed are told (escalate-and-note D9)."""
    previous = wb.previous_attempt
    if previous is None or previous.task != task.key:
        return ()
    if previous.why == "escalation":
        return _escalation_block(previous) if previous.phase == phase else ()
    text = (
        f"The agent before you (profile {previous.profile}) stopped on a {previous.limit_kind} limit while working "
        "on this task. Its uncommitted changes were discarded; the commits already on the branch are kept. You start "
        "from the checkout as it is now, in a new session, with no transcript of that attempt."
    )
    who, why = (re.sub(r"[^A-Za-z0-9._-]", "_", v) for v in (previous.profile, previous.limit_kind))
    block = f'<l4:data kind="previous-attempt" profile="{who}" limit="{why}">\n{defuse(text)}\n</l4:data>'
    return (("previous attempt", block),)


ACCEPTED_RULE = (
    "The specification of this unit has these gaps, which a person accepted. Where the specification is silent, follow "
    "the person's reason. Say in notes_for_verifier how you handled each one, by its id."
)


def accepted_block(items: Sequence[Mapping[str, Any]]) -> str:
    """The data block `accepted review findings` (L4-YOLO-028): the rule, then per item the person's reason and the
    findings as `F-... [criterion] text`. Empty when there are no findings."""
    lines: list[str] = []
    for item in items:
        findings = item.get("findings") or ()
        if not findings:
            continue
        who = f" ({item['by']})" if item.get("by") else ""
        lines += ["", f"Reason{who}: {item['reason']}"]
        lines += [f"{f['id']} [{f['criterion']}] {f['text']}" for f in findings]
    return data_block("accepted review findings", "\n".join([ACCEPTED_RULE, *lines])) if lines else ""


def _accepted(wb: Workbench) -> tuple[tuple[str, str], ...]:
    """The accepted review findings the run wrote into the unit folder (`.l4/review-accepted.json`) as a block."""
    block = accepted_block(read_accepted(wb.ref.path))
    return (("accepted review findings", block),) if block else ()


def _lessons(wb: Workbench, task: Task) -> Injection:
    """The lessons that apply to the task, as a data block (SPEC L4-MEM-003); one `lessons.injected` event when any."""
    paths = task_paths(task.title, [*wb.branch_changed_files(), *wb.changed_files()])
    injection = inject_for_task(wb.worktree, wb.cfg.memory, paths, writer=wb, redact=wb.redactor.redact_text)
    for problem in injection.skipped:
        log.warning("%s: lessons: %s", wb.ref.id, problem.message)
    return injection


def _note_sha(note: RetryNote, redact: Callable[[str], str]) -> str:
    """The hash of the note block, of its redacted text (SCN-OPS-28)."""
    return hashlib.sha256(note_block(note, redact=redact)[1].encode("utf-8")).hexdigest()


def _prompt(
    wb: Workbench,
    role: Phase,
    task: Task,
    previous_failure: str | None,
    unfreeze: Unfreeze | None = None,
    adds_tests: bool = False,
    stale: StaleTests | None = None,
) -> str:
    answers = _answers(wb, task)
    lessons = _lessons(wb, task)
    redact = wb.redactor.redact_text
    note = retry_note(_ledger_events(wb), task.key, wb.event_context.get("fix_unit"), redact=redact)  # D11
    ctx = PromptContext(
        unit_id=wb.ref.id, adapter=wb.selected.profile.adapter or "", task_key=task.key, task_title=task.title,
        task_links=task.links,
        sources=collect_sources(wb.ref.path), criteria=tuple(wb.provider.criteria(wb.ref)),
        gate_command=wb.cfg.gates.test.command, previous_failure=previous_failure,
        result_path=Path(RESULT_ALIAS_PATH) if wb.impl.capabilities().schema_mode == "prompt_contract" else None,
        context_budget_tokens=wb.cfg.implementer.context_budget_tokens,
        static_gate_commands=(*wb.cfg.gates.lint, *wb.cfg.gates.typecheck), run_ledger=wb.ledger_rel,
        e2e_dir=e2e_test_dir(wb.cfg.gates.e2e, wb.worktree) if e2e_configured(wb.cfg) else None,
        e2e_base_url_env=wb.cfg.verifier.playwright.base_url_env,
        unfrozen=tuple((p, g.question) for g in unfreeze.grants if g.question for p in g.paths) if unfreeze else (),
        named=tuple(sorted({p for g in unfreeze.grants if g.reason == "named_by_task" for p in g.paths}))
        if unfreeze
        else (),
        adds_tests=adds_tests,
        stale_tests=tuple(sorted(stale.tests)) if stale else (), stale_changes=tuple(stale.changes) if stale else (),
        data_blocks=(
            *((("answered questions", answers.text),) if answers.text else ()),
            *((("lessons", lessons.block),) if lessons.block else ()),
            *_accepted(wb),
            *_previous_attempt_block(wb, task, role),
            *((note_block(note, redact=redact),) if note is not None else ()),
        ),
    )  # fmt: skip
    rendered = render_prompt(role, ctx)
    text = wb.redactor.redact_text(rendered.text)  # L4-OBS-002: prompts too; the hash is of what is sent
    wb.emit(
        "prompt.rendered", role=role, task=task.key, sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        template_version=rendered.template_version, sources=list(rendered.sources),
        answers=[{"id": qid, "answer_sha256": digest} for qid, digest in answers.consumed],  # L4-QMD-006
        lessons=list(lessons.ids),
        **({"retry_note": {"event": note.event, "ts": note.ts, "sha256": _note_sha(note, redact)}} if note else {}),
    )  # fmt: skip
    return text


def agent_step(
    wb: Workbench, role: Phase, task: Task, attempt: int, previous_failure: str | None,
    unfreeze: Unfreeze | None = None, *, adds_tests: bool = False, stale: StaleTests | None = None,
) -> StepOutcome:  # fmt: skip
    """Run the implementer once in the agent sandbox, put protected paths back, and read its result. Raises
    `RoleLimit` when the agent says it is out of quota or logged out."""
    base = wb.head()  # the revert resets to this commit: it must be taken before the agent runs
    spec = wb.agent_spec()
    tmp = wb.reset_agent_tmp()
    trace = trace_env(wb.cfg.gates.test_timeout_seconds())
    extra = {c.env: str(c.path) for c in wb.caches} | dict(getattr(wb.impl, "extra_env", {})) | trace
    key = re.sub(r"[^A-Za-z0-9._-]", "_", task.key)
    stem, again = f"{key}-{role}-{attempt}", 1
    while (published := wb.agent_log_paths(stem)[1]).exists() or published.with_suffix(".prompt.md").exists():
        again += 1  # the task ran again in this run (a clarifier answered): keep the earlier step's files too
        stem = f"{key}-{role}-{attempt}-r{again}"
    raw_events, published = wb.agent_log_paths(stem)
    prompt = _prompt(wb, role, task, previous_failure, unfreeze, adds_tests, stale)
    wb.publish_prompt(published, prompt)
    # L4-IMP-019: a prompt-contract adapter hands over the object as written; the harness alone validates it
    prompt_contract = wb.impl.capabilities().schema_mode == "prompt_contract"
    env = build_agent_env(wb.host_env, spec, extra=extra)
    impl_cfg = wb.cfg.implementer
    fix_unit = wb.event_context.get("fix_unit")
    tag = f"[{fix_unit}] " if isinstance(fix_unit, str) and fix_unit else ""
    profile = wb.selected.profile_name

    def on_beat(beat: Beat) -> None:  # L4-IMP-023: a console and log line, never a ledger event
        beat_log.info(
            "%s %stask %s %s attempt %s: %s %s", wb.ref.id, tag, task.key, role, attempt, profile, beat_text(beat)
        )

    idle_s = duration_seconds(impl_cfg.idle_timeout)
    watch = ActivityWatch(duration_seconds(impl_cfg.heartbeat), on_beat)  # clock: time.monotonic, the runner's
    request = RunRequest(
        profile=wb.selected.profile, role="implementer", cwd=wb.worktree,
        prompt=prompt, result_path=tmp / "result.json", raw_events_path=raw_events,
        env=env, result_schema=None if prompt_contract else RESULT_SCHEMA, mcp_servers=wb.mcp_servers(env),
        permission_policy=PermissionPolicy("implement", gate_prefix=wb.cfg.gates.test.command),
        wrap=lambda argv, env, cwd=None: wb.sandbox.wrap(argv, spec, env, cwd),
        stall_timeout_s=float(idle_s) if idle_s else None, watch=watch, host_env=wb.host_env,
    )  # fmt: skip
    try:
        resultalias.link(wb.worktree, tmp)  # the short path a prompt-contract adapter writes its result to (MAG)
        with wb.wip_snapshots(task.key, role, attempt) as box:
            run = wb.impl.run(request)
            box.status = run.status
    finally:
        try:
            resultalias.drop(wb.worktree)  # before the revert, any gate and any commit: it is never part of the work
        finally:  # a drop that fails must not skip the revert of the protected paths
            wb.publish_agent_logs(raw_events, published)
            wb.setup_at = None  # the agent may have changed the environment: the next step installs again
            # also on an exception: whatever the agent left behind must not be committed or folded by a later step
            wb.settle_serena_project(base)
            revert_protected(wb.git, wb.protected, base, events=wb, excludes=wb.excludes)
            wb.restore_ledger(task=task.key, phase=role, attempt=attempt)
    if watch.stopped_idle_s is not None:  # L4-IMP-024: before `agent.finished`
        wb.emit(
            "agent.idle", task=task.key, phase=role, attempt=attempt, profile=profile,
            silent_s=round(watch.stopped_idle_s), tool_calls=watch.snapshot(watch.clock()).tool_calls,
        )  # fmt: skip
    wb.emit(
        "agent.finished", task=task.key, phase=role, status=run.status, exit_code=run.exit_code, detail=run.detail,
        model=run.model_resolved, input_tokens=run.usage.input_tokens, output_tokens=run.usage.output_tokens,
        **denial_facts(run), **context_peak_facts(run),
    )  # fmt: skip
    for rejected in run.tool_rejections:  # SPEC §8.3: a policy-rejected call the JSON stream omits
        wb.emit("agent.tool_rejected", task=task.key, phase=role, **rejected)
    if run.session_id:
        wb.emit("agent.session", profile=wb.selected.profile_name, session_id=run.session_id)
    if run.usage.cost_usd is not None:
        wb.emit("budget.cost", usd=run.usage.cost_usd, profile=wb.selected.profile_name, task=task.key)
    if run.usage.credits is not None:  # plan credits, labelled with their source: never summed into the dollars
        wb.emit(
            "budget.cost", credits=round(run.usage.credits, 6), credits_source=run.usage.credits_source,
            profile=wb.selected.profile_name, task=task.key,
        )  # fmt: skip
    if run.status in LIMIT_STATUSES:
        raise RoleLimit(run)
    if run.status != "ok" and run.result_problem is None:
        reason = f"the agent step ended with status {run.status}: {run.detail or 'no detail'}"
        if run.status == "timeout":
            reason = (
                f"the agent showed no activity for {impl_cfg.idle_timeout} (implementer.idle_timeout), so L4 stopped it"
                if watch.stopped_idle_s is not None
                else f"the agent step reached its time limit ({ago(request.timeout_s)})"
            )
        # a prompt-contract adapter validated the result file (`agents/contract.py`): its detail names the paths
        invalid = run.status != "timeout" and (run.detail or "").startswith("result invalid")
        return StepOutcome("failed", reason=reason, excerpt=result_values_line(RESULT_SCHEMA, role) if invalid else "")
    values = result_values_line(RESULT_SCHEMA, role)
    found = find_result(run)
    if found is None:  # D7: the only result failure
        missing = "no result file and no result object in the final message"
        if not prompt_contract:
            missing = f"{run.detail + '; ' if run.detail else ''}no result object in the final message"
        reason = f"the agent's result is invalid: no result was delivered ({missing})"
        return StepOutcome("failed", reason=reason, excerpt=values)
    changed = sorted(p for p in wb.changed_files() if p != wb.ledger_rel)
    normalized = normalize(found, StepFacts(role, task.key, changed, run.last_message))
    if normalized.fixes:
        wb.emit(
            "result.normalized", task=task.key, phase=role, attempt=attempt, source=found.source,
            fixes=[fix.as_event() for fix in normalized.fixes],
        )  # fmt: skip
    try:
        result = parse_result(normalized.obj)
    except ResultInvalid as exc:  # a defect of the normalizer: the attempt fails, the gates never see it
        return StepOutcome("failed", reason=f"the agent's result is invalid: {exc}", excerpt=values)
    if result.status == "blocked":
        dropped = sum(f.count or 0 for f in normalized.fixes if f.field == "questions" and f.fix == "dropped")
        return StepOutcome("blocked", result, dropped_questions=dropped)
    return StepOutcome("ok", result)


def context_peak_facts(run: RunResult) -> dict[str, Any]:
    """L4-FAC-011: the largest context the run reached, for the fields that the adapter reports."""
    usage = run.usage
    return {
        key: value
        for key, value in (
            ("context_peak_tokens", usage.context_peak_tokens), ("context_peak_percent", usage.context_peak_percent),
        )
        if value is not None
    }  # fmt: skip


def _suppressions(result: ImplementerResult) -> list[dict[str, Any]]:
    return [declared.model_dump() for declared in result.suppressions]


def _red_commit_message(wb: Workbench, task: Task, *, already_satisfied: bool) -> str:
    what = f"{task.key} already satisfied" if already_satisfied else f"red for {task.key}"
    return f"test({wb.ref.name}): {what} [skip ci]"


def red_note(base_report: TestReport) -> Callable[[TestReport], dict]:
    """Design D9: the keys that `gate.finished` of a red test gate gets. `{"red_new_failing": n}` when at least one
    test fails and every failing test is new and failed by assertion or `NotImplementedError` without the hang marker,
    and the report has no collection error that the base report lacks; else `{}`. It changes no verdict."""

    def note(report: TestReport) -> dict:
        failing = sorted(i for i in report.tests if report.tests[i].status in ("failed", "error"))
        if not failing or set(report.collection_errors) - set(base_report.collection_errors):
            return {}
        new = new_test_ids(base_report, report)
        for i in failing:
            case = report.tests[i]
            if i not in new or case.failure_kind in (None, "other") or TIMEOUT_MARKER in case.message:
                return {}
        return {"red_new_failing": len(failing)}

    return note


def run_red(wb: Workbench, task: Task, *, attempt: int, previous_failure: str | None = None) -> RedOutcome:
    """One red attempt, with the checks in SPEC order (L4-IMP-002): the protected-path revert (in `agent_step`), the
    stub guard, run (a) with its failure kinds, the criteria, the pre-satisfied confirmation, run (b), the static
    gates; only then the commit."""
    base = wb.head()
    base_report = baseline(wb, base)
    static_baseline(wb, base)  # before the agent runs: the worktree is exactly the base
    run_setup(wb)
    stale = stale_for(wb, task, base_report)  # L4-OPS-015: the tests of the old text of a changed criterion
    step = agent_step(wb, "red", task, attempt, previous_failure, stale=stale)
    if step.kind != "ok":
        wb.discard_changes()
        return _red_exit(step)
    assert step.result is not None
    result = step.result
    tdd = wb.cfg.tdd
    scope = enforce_red_scope(wb, task, base)
    guard = ProductionGuard(wb, base)  # test code run by the gates must not move production files after this point

    def tampered(where: str) -> RedOutcome | None:
        notes = guard.check(where)
        if not notes:
            return None
        wb.discard_changes()
        return RedOutcome(
            "failed",
            "test code changed production files while a gate ran (a test may not write outside its own files): "
            + "; ".join(notes[:5]),
        )

    run_setup(wb)  # an agent-edited environment must not decide the gate
    changed = wb.changed_files()
    test_files = any(_matches(tdd.test_globs, p) or _matches(tdd.test_support_globs, p) for p in changed)
    gate = wb.run_gate("test", wb.cfg.gates.test.command, reports=wb.cfg.gates.test.reports, note=red_note(base_report))
    if (out := tampered("test run")) is not None:
        return out
    if gate.report is None:
        wb.discard_changes()
        return RedOutcome("failed", f"the test gate produced no readable report ({gate.reason})")
    report = gate.report
    new_ids = new_test_ids(base_report, report)
    family = {c.id for c in wb.provider.criteria(wb.ref)}
    tracing: dict[str, tuple[str, ...]] = {}
    pre_satisfied: dict[str, tuple[str, ...]] = {}
    confirmation = PreSatisfied()
    based = BaseRunResult()
    earlier: dict[str, EarlierRed] = {}
    if family and new_ids and not set(report.collection_errors) - set(base_report.collection_errors):
        check = check_criteria(
            result,
            family,
            {i: report.tests[i] for i in new_ids},
            trace_hint=trace_rules(wb.cfg.gates.test.command).hint,
            exempt=unchanged_criteria(wb, task, base_report),
        )
        for test in check.untraced:
            wb.emit("test.untraced", task=task.key, test=test)
        if check.error:
            wb.discard_changes()
            return RedOutcome("failed", check.error)
        tracing = check.tracing
        passing = {c: t for c, t in tracing.items() if all(report.tests[i].status == "passed" for i in t)}
        earlier = confirmed_by_earlier_red(wb, passing, report, new_ids)  # L4-IMP-003: no zero-value run for these
        confirmation = confirm_pre_satisfied(wb, {c: t for c, t in passing.items() if c not in earlier})
        if (out := tampered("pre-satisfied confirmation")) is not None:
            return out
        if confirmation.unconfirmed:  # whatever the zero-value run left (all of it, or part): last, the base run
            based = confirmed_by_base_run(wb, confirmation.unconfirmed, new_ids)
            if (out := tampered("base run")) is not None:
                return out
        if message := failure_message(confirmation, based):
            wb.discard_changes()
            return RedOutcome("failed", message)
        pre_satisfied = passing
        for criterion, tests in pre_satisfied.items():
            via = {"via": VIA} if criterion in earlier else {"via": BASE_VIA} if criterion in based.confirmed else {}
            wb.emit("criterion.pre_satisfied", task=task.key, criterion=criterion, tests=list(tests), **via)
    allowed = {t for tests in pre_satisfied.values() for t in tests}
    verdict = classify_red(
        base_report, report, test_files_changed=test_files,
        failure_kinds=True, allowed_passing=allowed, excerpt=excerpter(wb),
        rules=trace_rules(wb.cfg.gates.test.command), superseded=stale.tests if stale else (),
    )  # fmt: skip
    if not verdict.ok:
        wb.discard_changes()
        return RedOutcome("failed", verdict.reason, excerpt=verdict.excerpt)
    # a stale test that is gone or fails now was replaced on purpose; one that still passes is simply kept
    replaced = frozenset(
        t for t in (stale.tests if stale else ()) if t not in report.tests or report.tests[t].status != "passed"
    )

    def record_superseded() -> None:
        if replaced and stale:
            wb.emit(
                "tests.superseded", task=task.key, tests=sorted(replaced),
                criteria=sorted({c for t in replaced for c in stale.tests[t]}),
            )  # fmt: skip

    # `tests` trace the criterion; `discriminating` are the ones the zero-value run showed to look at the answer
    # a criterion confirmed by an earlier red names that red's tests (`discriminating`), `via` and the newest red's
    # commit and task; `tests` stay this step's own, which `classify_red` allows to pass
    proofs: dict[str, dict[str, Any]] = {
        criterion: {
            "tests": list(tests),
            "proof": PROOF_PRE_SATISFIED,
            "discriminating": list(
                earlier[criterion].tests
                if criterion in earlier
                else based.confirmed[criterion]
                if criterion in based.confirmed
                else confirmation.confirmed[criterion]
            ),
            **(
                {"via": VIA, "red_sha": earlier[criterion].red_sha, "red_task": earlier[criterion].red_task}
                if criterion in earlier
                else {"via": BASE_VIA, "base_sha": based.base_sha}
                if criterion in based.confirmed
                else {}
            ),
        }
        for criterion, tests in pre_satisfied.items()
    }
    open_criteria = {c: t for c, t in tracing.items() if c not in pre_satisfied}
    discriminating: Mapping[str, Sequence[str]] = {}
    zeroed = list(scope.stub_files)
    if open_criteria and not zeroed:  # no stub added by red: the ones that HEAD holds answer run (b)
        zeroed = head_stub_modules(wb, sorted({t for tests in open_criteria.values() for t in tests}))
    if open_criteria and zeroed:
        vacuity = vacuity_check(wb, zeroed, open_criteria)
        if (out := tampered("vacuity check")) is not None:
            return out
        if vacuity.message:
            wb.discard_changes()
            return RedOutcome("failed", vacuity.message)
        discriminating = vacuity.proofs
    elif open_criteria and (message := no_assertion_failure(report, open_criteria)):
        wb.discard_changes()
        return RedOutcome("failed", message)
    for criterion, tests in open_criteria.items():
        failing = [t for t in tests if fails_on_zero(report.tests.get(t))]
        proofs[criterion] = {
            "tests": list(tests),
            "proof": PROOF_ZERO_VALUE if zeroed else PROOF_RED_ASSERTION,
            "discriminating": list(discriminating.get(criterion) or failing),
        }
    worse = worse_static_gates(wb, base, "red")  # a lint error in a test file would be frozen and deadlock green
    if (out := tampered("static gates")) is not None:
        return out
    if worse:
        wb.discard_changes()
        return RedOutcome("failed", worse)
    new_tests = frozenset(new_ids)
    notes = result.notes_for_verifier  # the schema caps it at 2000 characters
    if tracing and not open_criteria:  # every cited criterion is pre-satisfied: the harness has proved it (L4-IMP-003)
        for path in scope.stub_files:
            restore_to_base(wb, base, path)  # a stub no test needs is not left behind
        guard.release(scope.stub_files)
        if scope.stub_files:  # a test may import a stub symbol it never calls: the restored head must still run
            final = wb.run_gate("test-restored", wb.cfg.gates.test.command, reports=wb.cfg.gates.test.reports)
            if (out := tampered("restored test run")) is not None:
                return out
            report = final.report
            if (
                report is None
                or report.collection_errors
                or any((c := report.tests.get(i)) is None or c.status != "passed" for i in new_ids)
            ):
                wb.discard_changes()
                return RedOutcome(
                    "failed",
                    "the new tests do not pass without the stubs you added: they import a name only a stub "
                    "defines (remove the unused import), or the stub is needed and the criterion is not "
                    "already satisfied",
                )
        if (out := tampered("before the already-satisfied commit")) is not None:
            return out
        wb.provider.set_marker(wb.ref, task.key, Marker.DONE)
        parents = tick_completed_parents(wb.provider, wb.ref)
        # contract C22, as for red and green: the proof travels inside the commit and names the base; the sha follows
        wb.restore_ledger()
        record_superseded()
        wb.emit(
            "task.red_ok", task=task.key, base=base, tests=sorted(new_tests), frozen=[], notes=notes,
            criteria=proofs, suppressions=_suppressions(result), tdd="already-satisfied",
        )  # fmt: skip
        wb.emit(
            "task.done", task=task.key, base=base, parents=parents, notes=notes, tdd="already-satisfied",
            suppressions=_suppressions(result),
        )  # fmt: skip
        sha = wb.commit(
            _red_commit_message(wb, task, already_satisfied=True),
            task=task.key, attempt=attempt, phase="red", tdd="already-satisfied",
        )  # fmt: skip
        wb.emit("task.red_committed", task=task.key, base=base, sha=sha)
        wb.emit("task.green_committed", task=task.key, base=base, sha=sha)
        wb.push()
        return RedOutcome(
            "already_satisfied", sha=sha, new_ids=new_tests, base_report=base_report, criteria=proofs,
            superseded=replaced,
        )  # fmt: skip
    if (out := tampered("before the red commit")) is not None:
        return out
    # The proof is recorded BEFORE the commit so that it travels inside it: a run killed right after the push has
    # nothing else on the branch to resume from (the ledger tail after a commit is only ever a local file).
    # The event names the step base instead of the red sha, which does not exist yet.
    wb.restore_ledger()
    wb.git.run("add", "-A", config=wb.exclude_config)
    tree = wb.git.run("write-tree").stdout.strip()
    frozen = build_manifest(wb.git, tree, base, test_globs=tdd.test_globs, support_globs=tdd.test_support_globs)
    record_superseded()
    wb.emit(
        "task.red_ok", task=task.key, base=base, tests=sorted(new_tests), frozen=sorted(frozen.files), notes=notes,
        criteria=proofs, suppressions=_suppressions(result),
    )  # fmt: skip
    sha = wb.commit(
        _red_commit_message(wb, task, already_satisfied=False), task=task.key, attempt=attempt, phase="red", tdd="red"
    )
    wb.emit("task.red_committed", task=task.key, base=base, sha=sha)  # contract C22: the sha, which the commit lacked
    manifest = replace(frozen, red_sha=sha)
    wb.push()
    return RedOutcome(
        "ok", sha=sha, new_ids=new_tests, manifest=manifest, base_report=base_report, criteria=proofs,
        superseded=replaced,
    )  # fmt: skip


def _last_checkpoint(wb: Workbench) -> tuple[str, str, str] | None:
    """(commit, task, tdd) of this unit's newest commit that carries an `L4-TDD` trailer, looking past ledger
    commits."""
    fmt = "%H%x01" + "%x01".join(f"%(trailers:key=L4-{k},valueonly,separator=%x2c)" for k in ("Unit", "Task", "TDD"))
    log = wb.git.run("log", "--max-count=50", f"--format={fmt}%x02").stdout
    for record in filter(None, (r.strip("\n") for r in log.split("\x02"))):
        sha, unit, task, tdd = (part.strip() for part in record.split("\x01"))
        if tdd and unit == wb.ref.id:
            return sha, task, tdd
    return None


def resume_red(wb: Workbench, task: Task) -> RedOutcome | None:
    """A run that died between the red commit and the green commit left the red checkpoint on the unit branch:
    redoing red there would fail ("no tests added"), so the task resumes at green. Needs the `task.red_ok` event of
    the earlier run for the new test ids: it is inside the red commit, so it survives any kill.
    M1: state-vcs-locks 1.22/1.23 (`step_key`, `reconcile`)."""
    last = _last_checkpoint(wb)
    if last is None or last[1:] != (task.key, "red"):
        return None
    sha = last[0]
    # a fix unit's events go to its parent's run ledger, which is where the earlier run wrote `task.red_ok`
    ledger_unit = wb.worktree / Path(wb.ledger_rel).parents[2]
    ledger = read_ledger(ledger_unit).events
    fix_unit = wb.event_context.get("fix_unit")
    base = wb.git.rev_parse(f"{sha}~1")
    event = next(
        (
            e for e in reversed(ledger)
            if e.type == "task.red_ok" and e.data.get("task") == task.key and e.data.get("base") == base
            and e.data.get("fix_unit") == fix_unit
        ),
        None,
    )  # fmt: skip
    if event is None:
        return None
    new_ids = frozenset(str(i) for i in event.data.get("tests", []))
    with wb.at_clean_head():
        run_setup(wb)
        gate = wb.run_gate("baseline", wb.cfg.gates.test.command, reports=wb.cfg.gates.test.reports)
    if gate.report is None or gate.report.collection_errors:
        raise BaselineFailed(f"the test gate cannot run at the red checkpoint: {gate.reason or 'collection errors'}")
    base = TestReport({i: c for i, c in gate.report.tests.items() if i not in new_ids})
    tdd = wb.cfg.tdd
    manifest = build_manifest(wb.git, sha, f"{sha}~1", test_globs=tdd.test_globs, support_globs=tdd.test_support_globs)
    wb.emit("task.red_resumed", task=task.key, sha=sha)
    return RedOutcome("ok", sha=sha, new_ids=new_ids, manifest=manifest, base_report=base)


def _red_exit(step: StepOutcome) -> RedOutcome:
    if step.kind == "blocked":
        assert step.result is not None
        return RedOutcome("blocked", questions=step.result.questions, summary=step.blocked_summary)
    return RedOutcome("failed", step.reason, excerpt=step.excerpt)


def fix_gate_env(wb: Workbench) -> dict[str, str] | None:
    """The environment of the test gate in the green step of a fix unit's task (L4-OPS-012, D12): the verifier's
    coverage plugin, so that a failure only the measurement causes reaches the fixer as an ordinary failed gate, with
    its log. Its output goes to a private folder of the step (`.l4-out/fix-cov`, the one place the gate sandbox can
    write) and is never read: only the gate's pass or fail is used. None for any other unit, for a gate that does not
    run Python, and when `.l4-out/fix-cov` is a symlink (repository content: nothing is written through it)."""
    if read_fix_marker(wb.ref.path) is None or not is_python_gate(wb.cfg.gates.test.command):
        return None
    try:
        reject_symlinks(wb.worktree, ".l4-out", "fix-cov")
    except UnsafeFile as exc:
        log.warning("%s: the fix gate runs without coverage: %s", wb.ref.id, exc)
        return None
    unit = wb.ref.path.resolve().relative_to(wb.worktree.resolve()).as_posix()
    roots = wb.cfg.verifier.evidence.module_roots
    packages = set()
    for path in {*wb.branch_changed_files(), *wb.changed_files()}:
        parts = path.split("/")
        if path.endswith(".py") and ".." not in parts and file_kind(path, unit, wb.cfg) == "code":
            packages.add("/".join(parts[:2]) if parts[0] in roots and len(parts) > 2 else parts[0])
    out = wb.worktree / ".l4-out" / "fix-cov"
    shutil.rmtree(out, ignore_errors=True)
    try:
        return cov_env(out, sorted(packages))
    except (ValueError, OSError) as exc:  # an unsafe path name: the gate runs as before
        log.warning("%s: the fix gate runs without coverage: %s", wb.ref.id, exc)
        return None


def run_green(
    wb: Workbench, task: Task, red: RedOutcome, *, attempt: int, previous_failure: str | None = None
) -> GreenOutcome:
    assert red.manifest is not None and red.base_report is not None
    base = wb.head()
    run_setup(wb)
    static_baseline(wb, base)
    human, named, source = _unfreeze_parts(wb, task, red.manifest)
    unfreeze = _combine(human, named)
    manifest = red.manifest
    if unfreeze.paths:  # these frozen files are named by a human answer or by the task's own text: the task's to change
        manifest = replace(manifest, files={p: f for p, f in manifest.files.items() if p not in unfreeze.paths})
    if human.paths:
        wb.emit(
            "task.unfrozen", task=task.key, paths=list(human.paths), reason="human_answer", question=human.question,
            answer_sha256=human.answer_sha256, red_sha=red.manifest.red_sha,
            kept=[{"path": p, "why": why} for p, why in human.kept],
        )  # fmt: skip
    if named.paths or named.kept:  # `kept` is recorded even when nothing opens: it is the only place that says why
        wb.emit(
            "task.unfrozen", task=task.key, paths=list(named.paths), reason="named_by_task", source=source,
            red_sha=red.manifest.red_sha, kept=[{"path": p, "why": why} for p, why in named.kept],
        )  # fmt: skip
    step = agent_step(wb, "green", task, attempt, previous_failure, unfreeze)
    if step.kind != "ok":
        wb.discard_changes()  # back to the red commit: it stays, the work of this attempt does not
        if step.kind == "blocked":
            assert step.result is not None
            return GreenOutcome("blocked", questions=step.result.questions, summary=step.blocked_summary)
        return GreenOutcome("failed", step.reason, excerpt=step.excerpt)
    _check_opened(wb, red, unfreeze, red.manifest)
    restore_frozen(wb.git, manifest, events=wb, excludes=wb.excludes)
    freeze_test_paths(wb, task, base, keep=unfreeze.paths, phase="green")
    run_setup(wb)  # `uv sync --frozen` removes what the agent installed: green passes on the locked environment
    gate = wb.run_gate("test", wb.cfg.gates.test.command, reports=wb.cfg.gates.test.reports, extra_env=fix_gate_env(wb))
    reason, named = green_failures(red.base_report, sorted(red.new_ids), gate, red.superseded)
    hung = gate_hung(gate) if reason else []
    excerpt = excerpter(wb)(gate.report, named) if reason and named and gate.report is not None else ""
    if hung:
        excerpt = hang_excerpt(hung) or excerpt
        wb.emit("gate.hung", task=task.key, tests=[h.id for h in hung], attempt=attempt)
    reason = reason or _undiscriminating(wb, red, unfreeze) or worse_static_gates(wb, base, "green")
    if reason:
        wb.discard_changes()
        return GreenOutcome("failed", reason, excerpt=excerpt, hung=tuple(hung))
    wb.provider.set_marker(wb.ref, task.key, Marker.DONE)
    parents = tick_completed_parents(wb.provider, wb.ref)
    assert step.result is not None
    # before the commit, like `task.red_ok`: the commit carries it, so a kill after it cannot lose the record
    wb.emit(
        "task.done", task=task.key, base=base, parents=parents, notes=step.result.notes_for_verifier,
        suppressions=_suppressions(step.result),
    )  # fmt: skip
    sha = wb.commit(
        f"feat({wb.ref.name}): {task.title} [skip ci]", task=task.key, attempt=attempt, phase="green", tdd="green"
    )
    wb.emit("task.green_committed", task=task.key, base=base, sha=sha)  # contract C22
    wb.push()
    return GreenOutcome("ok", sha=sha)


def freeze_test_paths(wb: Workbench, task: Task, base: str, *, keep: Collection[str] = (), phase: str) -> list[str]:
    """L4-IMP-006 (7): after green or a fix chore no path of the test or support globs differs from `base`, but the
    `keep` paths a human answer unfroze. A task with the human `[test-infra]` tag is exempt."""
    if "test-infra" in task_tags(task.title):
        return []
    tdd = wb.cfg.tdd
    return restore_test_paths(
        wb.git, base, test_globs=tdd.test_globs, support_globs=tdd.test_support_globs, keep=keep, events=wb,
        excludes=wb.excludes, phase=phase,
    )  # fmt: skip


def _freeze_refactor(wb: Workbench, task: Task, base: str) -> bool:
    """The step of a refactor chore: every changed path of the test or support globs goes back to `base` (a new one is
    removed), once, as `guard.restored{task, paths, reason: "feedback_refactor"}`. True when some other file changed."""
    tdd = wb.cfg.tdd
    globs = (*tdd.test_globs, *tdd.test_support_globs)
    changed = [p for p in sorted(set(wb.changed_files())) if p != wb.ledger_rel]
    frozen = [p for p in changed if _matches(globs, p)]
    for path in frozen:
        _put_back(wb, base, path, wb.git.run("cat-file", "-e", f"{base}:{path}", check=False).returncode == 0)
    if frozen:
        wb.emit("guard.restored", task=task.key, paths=frozen, reason="feedback_refactor")
    return len(frozen) < len(changed)


def proved_test_files(wb: Workbench) -> list[str]:
    """Every test or support file that a red step of the unit's family froze (`task.red_ok.frozen`), in any run: the
    files that carry the red-time proofs."""
    ledger_unit = wb.worktree / Path(wb.ledger_rel).parents[2]
    events = read_ledger(ledger_unit).events
    return sorted({str(f) for e in events if e.type == "task.red_ok" for f in e.data.get("frozen") or []})


def _ledger_events(wb: Workbench) -> list[LedgerEvent]:
    return read_ledger(wb.worktree / Path(wb.ledger_rel).parents[2]).events


def _log_text(gate: GateResult) -> str:
    try:
        return gate.log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def reproduce_ci_steps(wb: Workbench, base: str, findings: Sequence[str]) -> list[ChoreCiStep]:
    """Decision 4: run each failing CI step of the chore's findings at the clean base. A step that fails there the way
    it failed in CI (`reproduction`) becomes `reproduced` and a must-pass gate of the chore; any other is `skipped`
    with its reason, and the chore runs as before. One run per base commit; an unchanged decision is not recorded
    again."""
    events = _ledger_events(wb)
    steps = chore_ci_steps(events, findings)
    if not steps:
        return []
    recorded = last_ci_steps(events)
    must: list[ChoreCiStep] = []
    with wb.at_clean_head():
        run_setup(wb)
        for step in steps:
            key = (base, step.job)
            cached = wb.ci_reproductions.get(key)
            if cached is None:
                gate = wb.run_gate(f"{STEP_GATE_PREFIX}{step.job}", step.command)
                cached = reproduction(
                    exit_code=gate.exit_code, timed_out=gate.timed_out, reason=gate.reason, ci_tail=step.tail,
                    step=step.step or step.command, local_log=_log_text(gate),
                )  # fmt: skip
                wb.ci_reproductions[key] = cached
            status, why = cached
            last = recorded.get((step.head, step.job))
            if last is None or last.data.get("status") != status or last.data.get("reason") != why:
                wb.emit(
                    "ci.step", job=step.job, head=step.head, step=step.step, command=step.command, status=status,
                    reason=why, source=f"{GITLAB_CI_RELPATH}@{step.head[:10]}",
                )  # fmt: skip
            if status == "reproduced":
                must.append(replace(step, status="reproduced"))
    return must


def ci_steps_reason(wb: Workbench, steps: Sequence[ChoreCiStep]) -> str:
    """Why a reproduced CI step still fails after the chore (decision 4); empty when all pass. The text holds the last
    lines of the tool's output, so the retry prompt shows the error."""
    for step in steps:
        gate = wb.run_gate(f"{STEP_GATE_PREFIX}{step.job}", step.command)
        if gate.status != "pass":
            tail = "\n".join(_log_text(gate).strip().splitlines()[-CI_REASON_LINES:])
            return f"{STEP_GATE_PREFIX}{step.job} still fails ({gate.reason}): `{step.command}`\n{tail}"
    return ""


def _undiscriminating(wb: Workbench, red: RedOutcome, unfreeze: Unfreeze) -> str:
    """Decision 7: a corrected test must still fail against the red commit's code."""
    assert red.manifest is not None
    ids = sorted(i for i in red.new_ids if _test_file(wb, i) in unfreeze.paths)
    if not ids:
        return ""
    passing = fails_at_red(wb, red.manifest.red_sha, ids)
    return (
        f"the corrected test no longer discriminates: {_list(passing)} do not fail against the red commit's code"
        " (they pass, are skipped or did not run there)"
        if passing
        else ""
    )


def _regular_blob(wb: Workbench, rev: str, path: str) -> bytes | None:
    """`path` at `rev` when it is a regular file (never a symlink or a submodule) of at most `MAX_TASKS_BYTES`."""
    row = wb.git.run("ls-tree", rev, "--", path, check=False).stdout.split("\t")[0].split()
    if len(row) != 3 or row[1] != "blob" or row[0] not in ("100644", "100755"):
        return None
    data = wb.git.run_bytes("cat-file", "blob", row[2], check=False)
    return data if len(data) <= MAX_TASKS_BYTES else None


def _block_of(data: bytes, key: str, framework: Framework) -> str | None:
    """The text a person reviewed for the one task `key` of a `tasks.md` (its enclosing headings and its text block), or
    None when the file has none or several of that key."""
    tasks = parse_openspec_tasks(data) if framework is Framework.OPENSPEC else parse_kiro_tasks(data)
    found = [t for t in tasks if t.key == key]
    return task_context(data, found[0], framework) if len(found) == 1 else None


def named_task_text(wb: Workbench, task: Task) -> tuple[str, str] | None:
    """(source, text block) of a task whose text a person reviewed (D2 of unfreeze-and-answer), else None. The text is
    read at HEAD. Source `plan:<id>@<digest>`: the unit folder at HEAD has the digest that an active plan froze at
    activation. Source `base:<sha10>`: the same task key has the same text block on the fetched base branch. A fix unit
    and a follow-up unit have neither: the harness wrote their text."""
    unit_dir = wb.ref.path
    if read_fix_marker(unit_dir) is not None or read_follow_up_marker(unit_dir) is not None:
        return None
    path = f"{wb.unit_rel}/tasks.md"
    head = _regular_blob(wb, "HEAD", path)
    if head is None or (text := _block_of(head, task.key, wb.ref.framework)) is None:
        return None
    if wb.activated_digest and wb.activated_plan:
        try:
            digest = unit_digest(wb.git, "HEAD", wb.unit_rel)
        except RevisionMissing:  # FolderMissing is one
            digest = None
        if digest == wb.activated_digest:
            return f"plan:{wb.activated_plan}@{digest}", text
    ref = f"refs/remotes/origin/{wb.cfg.forge.base_branch}"
    sha = wb.git.rev_parse(ref)
    if sha is None or (base := _regular_blob(wb, ref, path)) is None:
        return None
    return (f"base:{sha[:10]}", text) if _block_of(base, task.key, wb.ref.framework) == text else None


def task_source(wb: Workbench, task: Task) -> str | None:
    """Whose reviewed text a task's own text block is (L4-IMP-014): `plan:<id>@<digest>`, `base:<sha10>` or None."""
    named = named_task_text(wb, task)
    return named[0] if named else None


def _unfreeze_parts(wb: Workbench, task: Task, manifest: FreezeManifest) -> tuple[Unfreeze, Unfreeze, str | None]:
    """(what human answers unfreeze, what the task's own text opens, that text's source)."""
    human = Unfreeze()
    file = QuestionsFile.load(wb.ref.path / QUESTIONS_FILENAME)
    if file is not None:
        events = _ledger_events(wb)
        if (own := read_ledger(wb.ref.path).events) and wb.ref.path != wb.worktree / Path(wb.ledger_rel).parents[2]:
            events = [*events, *own]  # a fix unit's answers are recorded where its own questions file is
        scope = task_scope(wb.provider.tasks(wb.ref), task.key)
        human = unfrozen(file.questions, events, scope, manifest)
    named = named_task_text(wb, task)
    if named is None:
        return human, Unfreeze(), None
    by_text = named_by_task(named[1], manifest, source=named[0])
    taken = set(human.paths)  # a person's answer wins: the path is listed once, under the answer
    grants = tuple(
        replace(g, paths=paths) for g in by_text.grants if (paths := tuple(p for p in g.paths if p not in taken))
    )
    return human, Unfreeze(grants, tuple((p, w) for p, w in by_text.kept if p not in taken)), named[0]


def _combine(human: Unfreeze, named: Unfreeze) -> Unfreeze:
    return Unfreeze((*human.grants, *named.grants), (*human.kept, *named.kept))


def unfreeze_for(wb: Workbench, task: Task, manifest: FreezeManifest) -> Unfreeze:
    """The frozen files of `manifest` that this task's green may change: what a human answer to a question holding
    this task names (decision 6; L4-IMP-015), and the support files its own reviewed text names (L4-IMP-014)."""
    human, named, _ = _unfreeze_parts(wb, task, manifest)
    return _combine(human, named)


def _symlinked_part(wb: Workbench, path: str) -> str | None:
    """The first component of `path` (a file or a parent folder) that is a symlink in the work tree."""
    parts = path.split("/")
    for i in range(len(parts)):
        if (wb.worktree.joinpath(*parts[: i + 1])).is_symlink():
            return "/".join(parts[: i + 1])
    return None


def _opened_problem(wb: Workbench, red_sha: str, path: str, *, by_text: bool, modules: Collection[str]) -> str | None:
    """Why the opened file `path` cannot stay (L4-IMP-016), or None. A symlink in the path, a deletion and the three
    rules of `check_opened`."""
    if _symlinked_part(wb, path) is not None:
        return "a symlink"
    target = wb.worktree / path
    if not target.exists():
        return "deleted"
    if not target.is_file():
        return "not a regular file"
    before = wb.git.run("show", f"{red_sha}:{path}", check=False).stdout
    return check_opened(
        before, target.read_text(encoding="utf-8", errors="replace"), named_by_task=by_text, unit_modules=modules
    )


def _check_opened(wb: Workbench, red: RedOutcome, unfreeze: Unfreeze, manifest: FreezeManifest) -> None:
    """After the agent step and before the frozen files are put back: each opened `.py` file keeps the three rules
    (all for a file the task's text opened, rule 3 for a support file a human answer unfroze). A file that breaks one is
    put back to its red version and recorded as `guard.violation{rule: "opened file"}`."""
    by_text = {p for g in unfreeze.grants if g.reason == "named_by_task" for p in g.paths}
    checked = sorted(
        p for p in unfreeze.paths if p.endswith(".py") and (p in by_text or manifest.files[p].kind == "support")
    )
    if not checked:
        return
    modules = unit_modules({*wb.branch_changed_files(), *wb.changed_files()}, wb.cfg)
    for path in checked:
        why = _opened_problem(wb, manifest.red_sha, path, by_text=path in by_text, modules=modules)
        if why is None:
            continue
        broken = _symlinked_part(wb, path)
        if broken is not None:
            wb.worktree.joinpath(broken).unlink()  # the link goes, and the red version of what it replaced comes back
        wb.git.run("checkout", manifest.red_sha, "--", f":(literal){broken or path}")
        wb.emit("guard.violation", rule="opened file", path=path, phase="green", why=why, action="restored")


# Why a unit's own test file was put back (`appended_only`): the next attempt's guard note says what may be appended.
_APPEND_RULE = (
    "to this unit's own test files only new tests may be appended: test functions and classes whose only decorators "
    "are pytest marks, imports and constant values, every existing statement as it is; a fixture, any other "
    "decorator, a module-level mark, an xunit setup or a value computed by a call goes in a new test file"
)


@dataclass
class TestChoreReview:
    __test__ = False  # not a pytest class

    kept: list[str] = field(default_factory=list)  # new or appended-to test files that stay
    non_test: list[str] = field(default_factory=list)  # changed files that are no test file: the attempt fails


def review_test_chore(wb: Workbench, base: str, own_tests: Collection[str]) -> TestChoreReview:
    """What a test chore (a coverage hold's task) may change (M1.11 decision 7): new test files stay, and so do new
    tests appended to the unit's own test files (`own_tests`: the files its red steps froze) when `appended_only`
    holds. Any other change to an existing test file is put back (`guard.test_tamper`), and a new or changed
    test-support file (`conftest.py`, fixtures, an ignore file) is put back too (`guard.violation`): an autouse fixture
    there would reach every existing test. A changed file that is no test file is reported, not touched: the caller
    fails the attempt."""
    tdd = wb.cfg.tdd
    support = (*tdd.test_support_globs, *IGNORE_FILE_GLOBS)
    review = TestChoreReview()
    for path in sorted(p for p in set(wb.changed_files()) if p != wb.ledger_rel):
        target = wb.worktree / path
        existed = wb.git.run("cat-file", "-e", f"{base}:{path}", check=False).returncode == 0
        if _matches(support, path):
            _put_back(wb, base, path, existed)
            wb.emit("guard.violation", path=path, rule="test support file", action="restored", phase="single")
        elif _matches(tdd.test_globs, path):
            if not existed or (path in own_tests and _appended(wb, base, path, target)):
                review.kept.append(path)
            else:
                _put_back(wb, base, path, existed)
                why = _APPEND_RULE if path in own_tests else ""
                wb.emit("guard.test_tamper", path=path, phase="single", **({"reason": why} if why else {}))
        else:
            review.non_test.append(path)
    return review


def _put_back(wb: Workbench, base: str, path: str, existed: bool) -> None:
    target = wb.worktree / path
    if not existed:
        target.unlink(missing_ok=True)
        return
    if target.is_symlink():
        target.unlink()
    wb.git.run("checkout", base, "--", f":(literal){path}")


def _appended(wb: Workbench, base: str, path: str, target: Path) -> bool:
    if target.is_symlink() or not target.is_file():
        return False
    before = wb.git.run("show", f"{base}:{path}", check=False).stdout
    return appended_only(before, target.read_text(encoding="utf-8", errors="replace"))


_CALLS_WRONG = re.compile(
    r"\b(wrong|bug|buggy|incorrect|broken|defect|should not|must not|shouldn't|mustn't|should be removed|"
    r"must be removed|instead of)\b",
    re.I,
)
_DECIDED = re.compile(r"Decided by \w+ in (?P<text>(?:Q-\d+:.*?))\. (?=[A-Z]|$)", re.S)


def decision_calling_code_wrong(wb: Workbench, findings: Sequence[str]) -> tuple[str, str] | None:
    """(question ids, decision text) of the human decision that opens a task of these findings, when it says that the
    code is wrong (M1.12 F1): read from the fix unit's proposal, where every finding line starts with the decision. A
    chore that may only add tests can then not pass honestly with tests that all pass against that code."""
    try:
        proposal = (wb.ref.path / "proposal.md").read_text(encoding="utf-8")
    except OSError:
        return None
    for line in proposal.splitlines():
        if not any(f in line for f in findings):
            continue
        found = _DECIDED.search(line)
        if found is not None and _CALLS_WRONG.search(found.group("text")):
            text = found.group("text")
            return ", ".join(dict.fromkeys(re.findall(r"Q-\d+", text.split(":", 1)[0] + ":"))) or "the decision", text
    return None


CRITERION_IN_TITLE = re.compile(r"\bC-[0-9a-f]{8}\b")  # a task of a fix unit that cites a criterion (W-C1)


def _discriminating_tests(wb: Workbench, added: Sequence[str]) -> tuple[list[str], str]:
    """(the added tests that look at the answer, the reason when none does). A tests chore that cites a criterion is
    checked as the verifier would a round later (`discriminate_extra`, L4-VER-009): a test counts when it fails by
    assertion when the project's functions answer their zero value, or on the unit base's code. A run that cannot
    decide (no unit base) accepts: the verifier still decides at verification."""
    base_sha = unit_base(wb)
    if base_sha is None:
        return [], ""
    outcome = discriminate_extra(wb, list(added), base_sha)
    if outcome.accepted:
        return sorted(outcome.accepted), ""
    shown = ", ".join(sorted(added)[:MAX_LISTED])
    return [], (
        "none of the tests you added looks at the answer: they pass when the project's functions answer their zero "
        f"value and on the unit's base code ({shown}). Assert the value the cited criterion's scenario names, through "
        "the interface the design names, so that a wrong implementation fails by assertion"
    )


def _already_done(wb: Workbench, task: Task, findings: Sequence[str], attempt: int) -> GreenOutcome:
    """The task of a retaken feedback item that has nothing left to change (review #8 follow-up): no file of the
    project changes; the task is ticked, the commit carries `L4-TDD: already-done` and the ledger says why, so that the
    parent is verified again and the judge looks at the item once more."""
    named = re.findall(r"\bFB-\d{3}\b", " ".join([task.title, *findings]))
    item = ", ".join(dict.fromkeys(named)) or ", ".join(findings)
    reason = f"retaken {item}: nothing left to change"
    wb.provider.set_marker(wb.ref, task.key, Marker.DONE)
    parents = tick_completed_parents(wb.provider, wb.ref)
    sha = wb.commit(
        f"fix({wb.ref.name}): {task.title} already done [skip ci]", task=task.key, attempt=attempt, phase="single",
        tdd="already-done",
    )  # fmt: skip
    wb.emit(
        "task.done", task=task.key, sha=sha, parents=parents, tdd="already-done", reason=reason,
        findings=list(findings),
    )  # fmt: skip
    wb.push()
    return GreenOutcome("ok", sha=sha)


def run_single(
    wb: Workbench,
    task: Task,
    findings: Sequence[str],
    *,
    attempt: int,
    previous_failure: str | None = None,
    kind: Literal["fix", "tests", "refactor"] = "fix",
    retake: bool = False,
) -> GreenOutcome:
    """A `[chore]` task of a fix unit (D8): one agent step with no red phase, for a finding that names no criterion.
    The checks are green's with an empty must-pass list: nothing that passed at the base may fail, no new failure
    appears, and the static gates that passed still pass. The commit carries `L4-TDD: exempt`, and the ledger says
    the harness exempted it (`task.tdd_exempt`), so the TDD history of the verifier skips it.
    `kind="tests"` (M1.11 W5): the chore of a rejected coverage hold adds tests. `single_tests.md` is its prompt, new
    test files and tests appended to the unit's own files are kept (`review_test_chore`), a change to anything else that
    is no test file fails the attempt, at least one new test must pass, and `task.tests_added` records them.
    `kind="refactor"` (L4-FBK-005, D5): a feedback task that changes structure and keeps behaviour. Whatever the step
    changed under the test or test-support globs is put back (`guard.restored`), at least one other file must change,
    and the gates then run against the original tests, which is the proof that behaviour is the same.
    `retake` (review #8 follow-up): every feedback item of the task was taken into an earlier fix unit (the marker's
    `retakes`), and the judge left it out of its reply or its reply was discarded, so the work may be done already. A
    refactor that changes no non-test file, or a test chore that adds no passing test, then completes the task with
    nothing committed but its tick (`_already_done`); a first take keeps failing (`nothing changed`, `no tests added`).
    M1: the failing tests of the finding as must-pass ids."""
    base = wb.head()
    base_report = baseline(wb, base)
    run_setup(wb)
    static_baseline(wb, base)
    ci_steps = reproduce_ci_steps(wb, base, findings)
    frozen = manifest_at_head(wb.git, base, proved_test_files(wb), support_globs=wb.cfg.tdd.test_support_globs)
    adds_tests = kind == "tests"
    own_tests = proved_test_files(wb) if adds_tests else []
    step = agent_step(wb, "single", task, attempt, previous_failure, adds_tests=adds_tests)
    if step.kind != "ok":
        wb.discard_changes()
        if step.kind == "blocked":
            assert step.result is not None
            return GreenOutcome("blocked", questions=step.result.questions, summary=step.blocked_summary)
        return GreenOutcome("failed", step.reason, excerpt=step.excerpt)
    kept: list[str] = []
    if adds_tests:
        review = review_test_chore(wb, base, own_tests)
        if review.non_test:
            wb.discard_changes()
            shown = ", ".join(sorted(review.non_test)[:MAX_LISTED])
            return GreenOutcome("failed", f"a test chore may add tests only: it changed non-test files: {shown}")
        kept = review.kept
    elif kind == "refactor" and not _freeze_refactor(wb, task, base):
        wb.discard_changes()
        if retake:
            return _already_done(wb, task, findings, attempt)
        return GreenOutcome("failed", "nothing changed")
    else:  # a chore has no red phase: the tests that carry the family's proofs are put back, as green does for its own
        restore_frozen(wb.git, frozen, events=wb, excludes=wb.excludes, phase="single")
        freeze_test_paths(wb, task, base, phase="single")
    run_setup(wb)
    gate = wb.run_gate("test", wb.cfg.gates.test.command, reports=wb.cfg.gates.test.reports, extra_env=fix_gate_env(wb))
    reason, named = green_failures(base_report, [], gate)
    excerpt = excerpter(wb)(gate.report, named) if reason and named and gate.report is not None else ""
    added = (
        sorted(i for i in new_test_ids(base_report, gate.report) if gate.report.tests[i].status == "passed")
        if adds_tests and gate.report is not None
        else []
    )
    if adds_tests and not reason and not added:
        if retake:
            wb.discard_changes()
            return _already_done(wb, task, findings, attempt)
        reason = "no tests added"
    elif adds_tests and not reason and attempt == 1 and (decided := decision_calling_code_wrong(wb, findings)):
        # the chore may not change the code, so tests that all pass against code the decision calls wrong assert what
        # the code does now (F1, MF-7); told once, the agent may explain in its notes, and the gate judges attempt 2
        reason = (
            f"these tests pass against the committed code, and the decision {decided[0]} says that code is wrong: "
            "this test asserts what the code does now; the decision above says otherwise. Add the test that asserts "
            "the decision (it fails now) and report status blocked with one question of kind technical that names "
            "that test and the decision, or say in notes_for_verifier why the decision does not apply to these tests."
        )
    reason = reason or worse_static_gates(wb, base, "green") or ci_steps_reason(wb, ci_steps)
    discriminating: list[str] | None = None
    if adds_tests and not reason and added and CRITERION_IN_TITLE.search(task.title):
        discriminating, reason = _discriminating_tests(wb, added)
    if reason:
        wb.discard_changes()
        return GreenOutcome("failed", reason, excerpt=excerpt)
    if adds_tests:  # before the commit, like `task.red_ok`: the commit carries the record the verifier reads (W6)
        proof = {} if discriminating is None else {"discriminating": discriminating}
        wb.emit("task.tests_added", task=task.key, files=sorted(kept), tests=added, **proof)
    wb.provider.set_marker(wb.ref, task.key, Marker.DONE)
    parents = tick_completed_parents(wb.provider, wb.ref)
    sha = wb.commit(
        f"fix({wb.ref.name}): {task.title} [skip ci]", task=task.key, attempt=attempt, phase="single", tdd="exempt"
    )
    assert step.result is not None
    wb.emit("task.tdd_exempt", task=task.key, sha=sha, kind="harness", finding=findings[0], findings=list(findings))
    wb.emit(
        "task.done", task=task.key, sha=sha, parents=parents, notes=step.result.notes_for_verifier, tdd="exempt",
        suppressions=_suppressions(step.result),
    )  # fmt: skip
    wb.push()
    return GreenOutcome("ok", sha=sha)
