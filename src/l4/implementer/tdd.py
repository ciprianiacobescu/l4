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

from l4 import deadline
from l4.accepted import read_accepted
from l4.agents.activity import ActivityWatch, Beat, ago, beat_text
from l4.agents.base import LimitSignal, PermissionPolicy, RunRequest, RunResult, denial_facts
from l4.ci.failing_step import (
    STEP_GATE_PREFIX,
    ChoreCiStep,
    chore_ci_job,
    chore_ci_steps,
    last_ci_steps,
    reproduction,
)
from l4.ci.gitlab_jobs import GITLAB_CI_RELPATH
from l4.clarifier.actor import answer_actor
from l4.clarifier.inject import RenderedAnswers, render_answer_blocks
from l4.config.schema import duration_seconds
from l4.evidence.scope import file_kind
from l4.exitcodes import ExitCode, L4Exit
from l4.fsutil import UnsafeFile, reject_symlinks
from l4.gates.coverage import cov_env, is_python_gate, project_python
from l4.gates.e2e import e2e_configured, e2e_test_dir
from l4.gates.hang import TIMEOUT_MARKER, HungTest, hung_tests
from l4.gates.junit import TestCase, TestReport, fold_subtest_id
from l4.gates.runner import GateResult
from l4.gates.trace import trace_env
from l4.implementer import resultalias
from l4.implementer.base_run import VIA as BASE_VIA
from l4.implementer.base_run import BaseRunResult, combine, confirmed_by_base_run
from l4.implementer.discrimination import (
    PROOF_PRE_SATISFIED,
    PROOF_RED_ASSERTION,
    PROOF_ZERO_VALUE,
    VIA_NOT_APPLICABLE,
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
from l4.implementer.gateconfig import config_files, revert_gate_config
from l4.implementer.guards import (
    IGNORE_FILE_GLOBS,
    FreezeManifest,
    appended_only,
    build_manifest,
    manifest_at_head,
    restore_frozen,
    restore_test_paths,
)
from l4.implementer.held import HeldCheck, Override, accepted_overrides
from l4.implementer.held_patch import (
    Refused,
    accepted_tests_block,
    arm_replay_guard,
    capture,
    close_replay_guard,
    find_replay,
    release_replay,
    replay_step,
    restore_replay,
)
from l4.implementer.named_tests import NamedTests, named_tests, test_id
from l4.implementer.normalize import StepFacts, find_result, normalize
from l4.implementer.opened import check_filled_helper, check_opened, unit_modules
from l4.implementer.prompt import PromptContext, data_block, defuse, render_prompt, result_values_line
from l4.implementer.reopen import is_reopened, pending_stale
from l4.implementer.result import (
    RESULT_SCHEMA,
    ImplementerResult,
    ResultInvalid,
    ResultQuestion,
    TraceRules,
    cap_universe,
    check_criteria,
    over_cap_text,
    parse_result,
    trace_rules,
)
from l4.implementer.resultalias import RESULT_ALIAS_PATH
from l4.implementer.retrynote import RetryNote, note_block, retry_note
from l4.implementer.stubs import ProductionGuard, enforce_red_scope, escaping_links, restore_to_base
from l4.implementer.tamper import Tampered, compare, facts_of, moved, names_test_id
from l4.implementer.tasks import task_scope, tick_completed_parents
from l4.implementer.unfreeze import Unfreeze, config_opened, named_by_task, unfrozen
from l4.implementer.unit_context import CHARS_PER_TOKEN, prompt_inputs
from l4.implementer.uvseed import ensure_uv_seed
from l4.implementer.workbench import PreviousAttempt, UnsafeWrite, Workbench
from l4.memory.inject import Injection, inject_for_task, task_paths
from l4.sandbox.env import build_agent_env, cache_env, gate_ci_env
from l4.security.protected import changed_paths, glob_match, revert_protected
from l4.specs.base import Framework, Marker, Task, UnitRef
from l4.specs.criteria import linked_criteria, own_criteria, trace_ids
from l4.specs.fixmark import read_fix_marker
from l4.specs.followup import read_follow_up_marker
from l4.specs.kiro import parse_kiro_tasks
from l4.specs.markers import MAX_TASKS_BYTES
from l4.specs.openspec import parse_openspec_tasks
from l4.specs.questions import QUESTIONS_FILENAME, QuestionsFile
from l4.specs.tasks_text import task_context
from l4.state.ledger import LedgerEvent, read_ledger
from l4.vcs.secretscan import step_secret_reason, worktree_secrets
from l4.verifier.scan import has_human_tag
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


class PlantedLink(Exception):
    """A gate run put a symbolic link on the path of a file the harness restores (L4-SEC-021). The harness removed it
    and wrote nothing through it, and discarded the attempt; the unit halts at once, like a secret in a push: code that
    plants a link in the worktree is not an attempt to retry but evidence for a person. `links` is the record."""

    def __init__(self, reason: str, links: Sequence[UnsafeWrite]) -> None:
        super().__init__(reason)
        self.links = tuple(links)


def stop_on_unsafe(wb: Workbench) -> str:
    """ "" when no harness write was refused in this attempt. A planted link discards the attempt and raises
    `PlantedLink`; any other refusal (`restore failed`) returns the reason that fails the attempt."""
    if links := wb.planted_links():
        reason = wb.unsafe_reason()
        wb.discard_changes()
        raise PlantedLink(reason, links)
    return wb.unsafe_reason()


MAX_LINKS_SHOWN = 5


def outside_links_reason(wb: Workbench, base: str, phase: str) -> str:
    """L4-SEC-020 part e: "" when the step leaves no symbolic link that points outside the worktree (an absolute target
    or one that climbs above the root) beyond what `base` already held. Else one `guard.violation` per link, and the
    reason that fails the attempt before its commit; the caller discards the changes."""
    found = escaping_links(wb, base)
    for path, target in found:
        wb.emit(
            "guard.violation", phase=phase, rule="link outside worktree", path=path, action="refused",
            target=target, why=f"it points to {target}, outside the worktree",
        )  # fmt: skip
    if not found:
        return ""
    shown = ", ".join(f"{path} -> {target}" for path, target in found[:MAX_LINKS_SHOWN])
    more = f" (+{len(found) - MAX_LINKS_SHOWN} more)" if len(found) > MAX_LINKS_SHOWN else ""
    return (
        f"the step left a symbolic link that points outside the worktree: {shown}{more}. A link that leaves the "
        "repository is never committed; nothing of this attempt is kept"
    )


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
    kind: Status | Literal["held"]
    result: ImplementerResult | None = None
    reason: str = ""
    excerpt: str = ""  # harness text for the next prompt (the allowed result values after `result invalid`)
    dropped_questions: int = 0  # malformed questions that the normalization dropped from a `blocked` result
    held: HeldCheck | None = None  # kind "held": an accepted step that cannot be replayed (L4-IMP-065)

    @property
    def blocked_summary(self) -> str:
        """The summary that becomes the one question of a `blocked` step with none (L4-IMP-021)."""
        summary = self.result.summary if self.result else ""
        if not self.dropped_questions:
            return summary
        return f"{summary} ({self.dropped_questions} malformed questions were dropped)"


@dataclass
class RedOutcome:
    status: Status | Literal["already_satisfied", "held"]
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
    held: HeldCheck | None = None  # status "held": a check L4 could not decide (L4-IMP-063)


@dataclass(frozen=True)
class StaleTests:
    """The tests a reopened task's red step may replace (L4-OPS-015): base test id -> the stale criterion ids it traces,
    and the changes (`reopen.stale_changes`) the red prompt shows."""

    tests: Mapping[str, tuple[str, ...]]
    changes: tuple[Mapping[str, Any], ...]


@dataclass
class GreenOutcome:
    status: Status | Literal["held"]
    reason: str = ""
    sha: str | None = None
    questions: Sequence[ResultQuestion] = field(default_factory=list)
    summary: str = ""
    excerpt: str = ""  # the failure text behind `reason`, for the next prompt
    hung: tuple[HungTest, ...] = ()  # tests of the gate run that hit the per-test limit (SPEC L4-GAT-004)
    held: HeldCheck | None = None  # status "held": the test-at-red run could not decide (L4-IMP-063)


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


def cited_criteria(provider: Any, ref: UnitRef, links: Sequence[str]) -> dict[str, str]:
    """id -> alias of the criteria a Kiro leaf's `_Requirements:_` links name, read on the task's OWN unit (a fix unit
    cites the numbers of its own `bugfix.md` items, never the parent's `Req 2.1`). Empty for an OpenSpec task, which
    has no links, and for links that name no criterion (L4-KSP-012, kiro-prompt-context D8)."""
    return {c.id: c.alias for c in linked_criteria(own_criteria(provider, ref), links)}


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


ALREADY_SATISFIED = "already_satisfied"  # what `tdd_exemption.reason` of a red step that adds no test starts with

NO_NEW_TEST = (
    "no new test: no test with a new name was added. Editing or re-tagging an existing test creates no new test; "
    "write a new test function (a new name) for each criterion. If the behaviour already exists, the new tests pass "
    "against it: report `tdd_exemption: already_satisfied` and the harness checks that they discriminate. If every "
    "criterion this task cites is already traced by passing tests (an earlier task wrote them), add no test and "
    'report `criteria_ids` and `tdd_exemption: {reason: "already_satisfied by <task>"}`'
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
    named_changed: Collection[tuple[str, str]] = (),
) -> RedVerdict:
    """The failure reasons, in order (design D3.4); the first that holds is returned. `superseded`: the stale tests
    of a reopened task (`stale_tests`, L4-OPS-015) may be gone or fail, they are not regressions. `named_changed`:
    `(path, name)` of the existing tests the task's reviewed text names and that this red step changed in place
    (L4-IMP-082): they may fail after red like a red test, so they are no regression either. `allowed_passing`:
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
        and not any(names_test_id(i, path, name) for path, name in named_changed)
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
    red_ids = list(dict.fromkeys(fold_subtest_id(i) for i in red_ids))  # a subtest is its test (L4-GAT-006)
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
        result = wb.run_gate("setup", command, network=True, builds_env=True)
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
    fix = wb.event_context.get("fix_unit")  # a fix unit's records are in its parent's ledger, under its name
    events, unit_git = (_answer_events(wb) if fix else read_ledger(wb.ref.path).events), wb.git.at(wb.ref.path)
    return render_answer_blocks(
        file.questions, wb.redactor.redact_text, tasks=scope,
        actor_of=lambda question: answer_actor(unit_git, wb.ref.path, question, events, fix_unit=fix),
    )  # fmt: skip


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
    stopped = f"stopped on a {previous.limit_kind} limit while working on this task"
    if previous.limit_kind == "silent":  # L4-IMP-087: it did nothing for the whole idle time
        idle = wb.cfg.implementer.idle_timeout
        stopped = f"went silent: no output for {idle}, so L4 stopped it, while working on this task"
    text = (
        f"The agent before you (profile {previous.profile}) {stopped}. "
        "Its uncommitted changes were discarded; the commits already on the branch are kept. You start "
        "from the checkout as it is now, in a new session, with no transcript of that attempt."
    )
    who, why = (re.sub(r"[^A-Za-z0-9._-]", "_", v) for v in (previous.profile, previous.limit_kind))
    block = f'<l4:data kind="previous-attempt" profile="{who}" limit="{why}">\n{defuse(text)}\n</l4:data>'
    return (("previous attempt", block),)


ACCEPTED_RULE = (
    "The specification of this unit has these gaps, which a person accepted. Where the specification is silent, follow "
    "the person's reason. Say in notes_for_verifier how you handled each one, by its id."
)


FORCE_RULE = (
    "A person accepted the specification of this unit without a readiness review: no model checked it before this "
    "run. Where the specification is silent or unclear, follow the person's reason."
)


def accepted_block(items: Sequence[Mapping[str, Any]]) -> str:
    """The data block `accepted review findings` (L4-YOLO-028, L4-YOLO-062): the rule, then per item the person's reason
    and the findings as `F-... [criterion] text`; an item a person force-accepted without a review has no findings and
    gives `Accepted without review (<by>): <reason>` under `FORCE_RULE`. Empty when there is nothing to say."""
    lines: list[str] = []
    forced = gaps = False
    for item in items:
        findings = item.get("findings") or ()
        who = f" ({item['by']})" if item.get("by") else ""
        if item.get("force") is True:
            forced = True
            lines += ["", f"Accepted without review{who}: {item['reason']}"]
        if not findings:
            continue
        gaps = True
        lines += ["", f"Reason{who}: {item['reason']}"]
        lines += [f"{f['id']} [{f['criterion']}] {f['text']}" for f in findings]
    rules = [*([FORCE_RULE] if forced else []), *([ACCEPTED_RULE] if gaps else [])]
    return data_block("accepted review findings", "\n".join([*rules, *lines])) if lines else ""


def _accepted(wb: Workbench) -> tuple[tuple[str, str], ...]:
    """The accepted review findings the run wrote into the unit folder (`.l4/review-accepted.json`) as a block."""
    block = accepted_block(read_accepted(wb.ref.path))
    return (("accepted review findings", block),) if block else ()


def _lessons(wb: Workbench, task: Task, changed: Sequence[str] | None = None) -> Injection:
    """The lessons that apply to the task, as a data block (SPEC L4-MEM-003); one `lessons.injected` event when any."""
    paths = task_paths(task.title, [*wb.branch_changed_files(), *wb.changed_files()] if changed is None else changed)
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
    attempt: int = 1,
    ci_job: str | None = None,
    named: NamedTests | None = None,
) -> str:
    answers = _answers(wb, task)
    changed = [*wb.branch_changed_files(), *wb.changed_files()]
    lessons = _lessons(wb, task, changed)
    own = getattr(wb.provider, "own_tasks", wb.provider.tasks)  # a fix unit's tasks.md holds its own tasks only
    inputs = prompt_inputs(
        root=wb.worktree, provider=wb.provider, ref=wb.ref, task=task, tasks=own(wb.ref), changed=changed,
        cfg=wb.cfg, profile_name=wb.selected.profile_name, profile=wb.selected.profile,
    )  # fmt: skip
    redact = wb.redactor.redact_text
    note = retry_note(_ledger_events(wb), task.key, wb.event_context.get("fix_unit"), redact=redact)  # D11
    ctx = PromptContext(
        unit_id=wb.ref.id, adapter=wb.selected.profile.adapter or "", task_key=task.key, task_title=task.title,
        task_links=task.links, source_files=inputs.source_files, conventions=inputs.conventions,
        task_block=inputs.task_block, unit_rel=inputs.unit_rel, budget_source=inputs.budget_source,
        criteria=inputs.criteria, own_criteria=inputs.own_criteria,
        gate_command=wb.cfg.gates.test.command, previous_failure=previous_failure,
        max_criteria_per_test=wb.cfg.verifier.max_criteria_per_test,
        result_path=Path(RESULT_ALIAS_PATH) if wb.impl.capabilities().schema_mode == "prompt_contract" else None,
        context_budget_tokens=inputs.budget_tokens, window_tokens=inputs.window_tokens,
        static_gate_commands=(*wb.cfg.gates.lint, *wb.cfg.gates.typecheck), run_ledger=wb.ledger_rel,
        e2e_dir=e2e_test_dir(wb.cfg.gates.e2e, wb.worktree) if e2e_configured(wb.cfg) else None,
        e2e_base_url_env=wb.cfg.verifier.playwright.base_url_env,
        unfrozen=tuple((p, g.question) for g in unfreeze.grants if g.question for p in g.paths) if unfreeze else (),
        named=tuple(sorted({p for g in unfreeze.grants if g.reason == "named_by_task" for p in g.paths}))
        if unfreeze
        else (),
        adds_tests=adds_tests,
        gate_env_ci=tuple(f"{name}={value}" for name, value in sorted(gate_ci_env(wb.host_env).items())),
        ci_job=ci_job if role == "single" else None,
        stale_tests=tuple(sorted(stale.tests)) if stale else (), stale_changes=tuple(stale.changes) if stale else (),
        named_existing=tuple(f"{path}::{name.replace('.', '::')}" for path, name in named.tests) if named else (),
        data_blocks=(
            *((("answered questions", answers.text),) if answers.text else ()),
            *((("lessons", lessons.block),) if lessons.block else ()),
            *_accepted(wb),
            *accepted_tests_block(wb, role, task),
            *_previous_attempt_block(wb, task, role),
            *((note_block(note, redact=redact),) if note is not None else ()),
        ),
    )  # fmt: skip
    rendered = render_prompt(role, ctx)
    text = wb.redactor.redact_text(rendered.text)  # L4-OBS-002: prompts too; the hash is of what is sent
    wb.emit(
        "prompt.rendered", role=role, task=task.key, sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        template_version=rendered.template_version, sources=list(rendered.sources),
        budget_tokens=rendered.budget_tokens, budget_source=rendered.budget_source, steering=inputs.steering,
        answers=[{"id": qid, "answer_sha256": digest} for qid, digest in answers.consumed],  # L4-QMD-006
        lessons=list(lessons.ids),
        **({"retry_note": {"event": note.event, "ts": note.ts, "sha256": _note_sha(note, redact)}} if note else {}),
    )  # fmt: skip
    if rendered.over_window and inputs.window_tokens:  # the never-cut parts alone do not fit: nothing can be squeezed
        wb.emit(
            "prompt.over_window", role=role, task=task.key, attempt=attempt, window_tokens=inputs.window_tokens,
            prompt_tokens=len(rendered.text) // CHARS_PER_TOKEN,
        )  # fmt: skip
    if rendered.cuts:  # L4-IMP-052: what the prompt does not show whole, by path
        wb.emit(
            "prompt.truncated", role=role, task=task.key, attempt=attempt, budget_tokens=rendered.budget_tokens,
            sources=[c.as_dict() for c in rendered.cuts],
        )  # fmt: skip
    return text


def agent_step(
    wb: Workbench, role: Phase, task: Task, attempt: int, previous_failure: str | None,
    unfreeze: Unfreeze | None = None, *, adds_tests: bool = False, stale: StaleTests | None = None,
    ci_job: str | None = None, named: NamedTests | None = None,
) -> StepOutcome:  # fmt: skip
    """Run the implementer once in the agent sandbox, put protected paths back, and read its result. Raises
    `RoleLimit` when the agent says it is out of quota or logged out."""
    base = wb.head()  # the revert resets to this commit: it must be taken before the agent runs
    granted = config_grant(wb, task, role)  # what a person's answer opens, before the agent runs
    spec = wb.agent_spec()
    tmp = wb.reset_agent_tmp()
    trace = trace_env(wb.cfg.gates.test_timeout_seconds())
    extra = cache_env(spec) | dict(getattr(wb.impl, "extra_env", {})) | trace  # the step's private caches (L4-SEC-039)
    key = re.sub(r"[^A-Za-z0-9._-]", "_", task.key)
    stem, again = f"{key}-{role}-{attempt}", 1
    while (published := wb.agent_log_paths(stem)[1]).exists() or published.with_suffix(".prompt.md").exists():
        again += 1  # the task ran again in this run (a clarifier answered): keep the earlier step's files too
        stem = f"{key}-{role}-{attempt}-r{again}"
    raw_events, published = wb.agent_log_paths(stem)
    prompt = _prompt(wb, role, task, previous_failure, unfreeze, adds_tests, stale, attempt, ci_job, named)
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
            stopped = run.status == "cancelled" and deadline.fired()  # not a signal from CI: the soft deadline
            box.status = "deadline" if stopped else run.status
    finally:
        try:
            resultalias.drop(wb.worktree)  # before the revert, any gate and any commit: it is never part of the work
        finally:  # a drop that fails must not skip the revert of the protected paths
            wb.publish_agent_logs(raw_events, published)
            wb.setup_at = None  # the agent may have changed the environment: the next step installs again
            # also on an exception: whatever the agent left behind must not be committed or folded by a later step
            wb.discard_scratch()
            wb.settle_serena_project(base)
            revert_protected(wb.git, wb.protected, base, events=wb, excludes=wb.excludes)
            revert_gate_config(wb, task, base, phase=role, opened=granted.paths, attempt=attempt)
            wb.restore_ledger(task=task.key, phase=role, attempt=attempt)
            # L4-SEC-036: what the step wrote into `.venv` or `node_modules` decides later verdicts and no guard sees
            # it: an environment that differs from the one setup built is removed, and setup builds it again
            wb.check_env(wb.worktree, phase=role, changed=wb.changed_files())
    silent = False
    if watch.stopped_idle_s is not None:  # L4-IMP-024: before `agent.finished`
        beat = watch.snapshot(watch.clock())
        # L4-IMP-087: no tool call seen by a stream reader, and a later profile to move to (a single profile counts)
        silent = run.status == "timeout" and beat.counts and beat.tool_calls == 0 and len(wb.cfg.roles.implementer) > 1
        wb.emit(
            "agent.idle", task=task.key, phase=role, attempt=attempt, profile=profile,
            silent_s=round(watch.stopped_idle_s), tool_calls=beat.tool_calls, silent=silent,
        )  # fmt: skip
    wb.emit(
        "agent.finished", task=task.key, phase=role, status=run.status, exit_code=run.exit_code, detail=run.detail,
        model=run.model_resolved, input_tokens=run.usage.input_tokens, output_tokens=run.usage.output_tokens,
        **denial_facts(run), **context_peak_facts(run),
    )  # fmt: skip
    wb.served_model = run.model_resolved  # who a question raised from this step is asked by (L4-DLG-002)
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
    if stopped:  # after the cleanup, `agent.finished` and the reported cost: `run_unit` hands the step back (D5)
        raise deadline.DeadlineReached("during", during="agent")
    if run.status in LIMIT_STATUSES:
        raise RoleLimit(run)
    if silent:  # a limit of kind `silent`: the limit path cools the profile and moves on, no failed attempt
        quiet = f"no output for {impl_cfg.idle_timeout}"
        signal = LimitSignal(
            wb.selected.profile.adapter or "unknown", wb.selected.profile.model, "silent", None, "run.idle", quiet
        )
        raise RoleLimit(replace(run, limit=signal, detail=quiet))
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
    if hits := worktree_secrets(wb.git, wb.redactor, changed):  # L4-SEC-008: before any gate or commit
        for hit in hits:
            wb.emit("guard.secret", path=hit.path, kind=hit.kind, task=task.key, phase=role, attempt=attempt)
        return StepOutcome("failed", reason=step_secret_reason(hits))
    return StepOutcome("ok", result)


def step_or_replay(
    wb: Workbench, role: Phase, task: Task, attempt: int, previous_failure: str | None,
    unfreeze: Unfreeze | None = None, *, adds_tests: bool = False, stale: StaleTests | None = None,
    ci_job: str | None = None, named: NamedTests | None = None,
) -> StepOutcome:  # fmt: skip
    """The step of `role`: an agent step, or, when a person accepted the question that held this step, the saved step
    replayed without an agent (L4-IMP-065). A saved step that cannot be replayed is a hold with a new question."""
    wb.commit_agent = None
    wb.replay_question = None  # an accept of a saved step takes effect only in its replay
    close_replay_guard(wb)
    wb.replay_links = {}
    wb.replay_expected = {}
    found = find_replay(wb, role, task, attempt=attempt)
    if found is None:
        return agent_step(
            wb,
            role,
            task,
            attempt,
            previous_failure,
            unfreeze,
            adds_tests=adds_tests,
            stale=stale,
            ci_job=ci_job,
            named=named,
        )
    if isinstance(found, Refused):
        return StepOutcome("held", held=found.held)
    return replay_step(wb, role, task, attempt, found)


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


_PREEXISTING_ADVICE = (
    "A red step adds new tests with new names. Leave every existing test as it is, and the fixtures, helpers, "
    "constants and marks it uses in its file: give a new fixture or helper a new name, or put the new tests in a new "
    "file. A statement that is not a plain definition (a call at import, a computed constant, a logger) reaches every "
    "test of its file: compute the value inside the new test, or put the new tests in a new file. If an existing test "
    "is wrong, report status blocked with a question that names it. A test that the task's text or a criterion names "
    "(path::name) may be changed in place; name it there if it must change."
)


def _preexisting_changes(wb: Workbench, task: Task, base: str, stale: StaleTests | None) -> list[Tampered]:
    """The tests that existed at `base` and that this red step changed, bound again or deleted, in the test files it
    changed (compared per test on the AST, L4-IMP-045..047; a deleted test that is the same definition in a new place
    is moved, not deleted). A `[test-infra]` task is exempt, and so are the stale tests of a reopened task."""
    if has_human_tag(wb.ref.path, task.title, "test-infra"):
        return []
    root, tdd = wb.worktree, wb.cfg.tdd
    changed = changed_paths(wb.git, base, excludes=wb.excludes)
    paths = sorted(p for p in changed if p.endswith(".py") and _matches(tdd.test_globs, p))

    def now(path: str) -> str | None:
        target = root / path
        if target.is_symlink() or not target.is_file():
            return None
        return target.read_text(encoding="utf-8", errors="replace")

    def then(path: str) -> str:
        if not changed[path]:
            return ""
        done = wb.git.run("show", f"{base}:{path}", check=False)
        return done.stdout if done.returncode == 0 else ""

    found: list[Tampered] = []
    deleted: dict[tuple[str, str], str] = {}
    added: dict[tuple[str, str], str] = {}
    for path in paths:
        before, after = then(path), now(path)
        was = facts_of(before) or {}
        for t in compare(path, before, after):
            if t.kind == "deleted":
                deleted[path, t.name] = (was[t.name].definition, was[t.name].closure)
            found.append(t)
        if after is not None and (new := facts_of(after)):
            added |= {
                (path, n): (f.definition, f.closure)
                for n, f in new.items()
                if f.test and not (n in was and was[n].test)
            }
    gone = moved(deleted, added)
    stale_ids = list(stale.tests) if stale else []
    return [
        t
        for t in found
        if (t.path, t.name) not in gone and not any(names_test_id(i, t.path, t.name) for i in stale_ids)
    ]


def split_named(found: Sequence[Tampered], named: NamedTests) -> tuple[list[Tampered], list[Tampered]]:
    """(still rejected, named tests changed in place). A named test red changed in place is allowed (L4-IMP-082); one
    that red deleted, bound again or left unparsable is not."""
    pairs = set(named.tests)
    allowed = [t for t in found if t.kind == "changed" and (t.path, t.name) in pairs]
    return [t for t in found if t not in allowed], allowed


def preexisting_test_changes(
    wb: Workbench, task: Task, base: str, stale: StaleTests | None, named: NamedTests | None = None
) -> list[Tampered]:
    """L4-IMP-048: the tests that existed at `base` and that this red step changed, bound again or deleted (see
    `_preexisting_changes`). `named`: a test the task's reviewed text names may be changed in place, never removed."""
    return split_named(_preexisting_changes(wb, task, base, stale), named or NamedTests())[0]


def _preexisting_reason(found: Sequence[Tampered]) -> str:
    shown = "; ".join(f"{t.path}::{t.name} ({t.why})" for t in found[:MAX_LISTED])
    more = f" (+{len(found) - MAX_LISTED} more)" if len(found) > MAX_LISTED else ""
    return f"red changed tests that existed before this step: {shown}{more}"


def _reject_preexisting(wb: Workbench, found: Sequence[Tampered]) -> RedOutcome:
    """The attempt fails: one `guard.test_tamper` per file, nothing kept, and a reason and an excerpt that say what to
    do (putting the file back would also drop the new tests the agent appended to it, and the guard never edits an
    agent's file in place, L4-IMP-002)."""
    for path in sorted({t.path for t in found}):
        mine = [t for t in found if t.path == path]
        wb.emit(
            "guard.test_tamper", phase="red", path=path, rule="pre-existing test", action="rejected",
            tests=[t.name for t in mine], why="; ".join(f"{t.name}: {t.why}" for t in mine),
        )  # fmt: skip
    wb.discard_changes()
    lines = "\n".join(f"- {t.path}::{t.name}: {t.why}" for t in found)
    return RedOutcome("failed", _preexisting_reason(found), excerpt=f"{_PREEXISTING_ADVICE}\n{lines}")


VIA_HUMAN_OVERRIDE = "human_override"
VIA_AGENT_OVERRIDE = "agent_override"  # an agent answered, where clarifier.answer_by_agents allows it
VIA_DELEGATE_OVERRIDE = "delegate_override"  # the delegate answered (L4-DLG-010)


def override_via(override: Override) -> str:
    if override.by == "delegate":
        return VIA_DELEGATE_OVERRIDE
    return VIA_AGENT_OVERRIDE if override.by == "agent" else VIA_HUMAN_OVERRIDE


def override_who(override: Override) -> dict[str, str]:
    """The model and the CLI of a delegate's accept, for the records the judge and the report read; nothing for
    anyone else (a person's and an agent's records are as they were)."""
    if override.by != "delegate":
        return {}
    return {k: v for k, v in (("model", override.model), ("cli", override.cli)) if v}


def _via(
    criterion: str,
    earlier: Mapping[str, EarlierRed],
    based: BaseRunResult,
    confirmation: PreSatisfied,
    overridden: Mapping[str, Override] | None = None,
) -> dict:
    """How a pre-satisfied criterion was confirmed, for `criterion.pre_satisfied`: nothing for the zero-value run."""
    if overridden and criterion in overridden:
        return {
            "via": override_via(overridden[criterion]),
            "question": overridden[criterion].question,
            **override_who(overridden[criterion]),
        }
    if criterion in earlier:
        return {"via": VIA}
    if criterion in confirmation.confirmed:
        return {}
    if criterion in based.confirmed:
        return {"via": BASE_VIA}
    return {"via": VIA_NOT_APPLICABLE} if criterion in confirmation.not_applicable else {}


def _runs_of(confirmation: PreSatisfied, based: BaseRunResult) -> tuple[str, ...]:
    """The gate runs a pre-satisfied check made, for the ledger and the question: the zero-value run (once, and once
    more for each rerun that kept functions) and the base run when it was made."""
    made = based.base_sha and not based.reason.startswith("base run skipped")
    return ("test-presatisfied",) * (1 + confirmation.reruns) + (("test-base-run",) if made else ())


def _kept_of(kept: Mapping[str, Sequence[str]]) -> tuple[str, ...]:
    return tuple(f"{path}::{qual}" for path, quals in kept.items() for qual in quals)[:50]


def _accept(wb: Workbench, task: Task, check: str, used: Mapping[str, Override], key: str = "criteria") -> None:
    """`check.accepted` for each question whose `accept` carried subjects of this step (design D8)."""
    by_question: dict[str, tuple[Override, list[str]]] = {}
    for subject, override in sorted(used.items()):
        by_question.setdefault(override.question, (override, []))[1].append(subject)
    for question, (override, subjects) in by_question.items():
        wb.emit("check.accepted", task=task.key, check=check, question=question, answer_sha256=override.answer_sha256,
                by=override.by, **override_who(override), **{key: subjects})  # fmt: skip


def _decide_pre_satisfied(
    wb: Workbench,
    task: Task,
    candidates: Mapping[str, Sequence[str]],
    confirmation: PreSatisfied,
    based: BaseRunResult,
    result: ImplementerResult,
    refuse: Callable[[], RedOutcome | None] = lambda: None,
) -> tuple[RedOutcome | None, dict[str, Override]]:
    """What the zero-value run and the base run leave of the pre-satisfied candidates (design D2, D3, D7, D8): a
    refuted criterion fails the attempt (the message lists the inconclusive ones apart); only inconclusive ones hold
    the task, except the ones a person's `accept` covers, which count on the evidence of the real run. Returns the
    outcome that ends the step, or None and the overrides that carried criteria. `refuse` runs right before a hold is
    taken: a step the tamper check refuses is never held, so a person is not asked to accept it (L4-IMP-065)."""
    decision = combine(confirmation, based)
    if decision.refuted:
        wb.discard_changes()
        return RedOutcome("failed", decision.message), {}
    if not decision.inconclusive:
        return None, {}
    overrides = {
        c: o
        for c, o in accepted_overrides(wb, task.key, "pre_satisfied").items()
        if c in candidates and o.covers(candidates[c])  # the answer was about those tests, not a later other one
    }
    open_ = sorted(c for c in decision.inconclusive if c not in overrides)
    if open_:
        if (refused := refuse()) is not None:
            return refused, {}
        held = HeldCheck(
            task.key, "red", "pre_satisfied", tuple(open_), tuple(sorted({t for c in open_ for t in candidates[c]})),
            decision.inconclusive[open_[0]], _runs_of(confirmation, based), _kept_of(confirmation.kept),
        )  # fmt: skip
        held = capture(wb, held, result)  # before the discard: an accept replays this step (L4-IMP-065)
        wb.discard_changes()
        return RedOutcome("held", held=held), {}
    return None, {c: overrides[c] for c in decision.inconclusive}


def run_red(wb: Workbench, task: Task, *, attempt: int, previous_failure: str | None = None) -> RedOutcome:
    """One red attempt, with the checks in SPEC order (L4-IMP-002): the protected-path revert (in `agent_step`), the
    stub guard, run (a) with its failure kinds, the criteria, the pre-satisfied confirmation, run (b), the static
    gates; only then the commit."""
    base = wb.head()
    base_report = baseline(wb, base)
    static_baseline(wb, base)  # before the agent runs: the worktree is exactly the base
    run_setup(wb)
    stale = stale_for(wb, task, base_report)  # L4-OPS-015: the tests of the old text of a changed criterion
    listed = named_tests(wb, task, base)  # L4-IMP-082: the existing tests the reviewed text lets red change in place
    step = step_or_replay(wb, "red", task, attempt, previous_failure, stale=stale, named=listed)
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
        if unsafe := stop_on_unsafe(wb):  # a planted link halts the unit (raised); a failed restore fails the attempt
            wb.discard_changes()
            return RedOutcome("failed", unsafe)
        if not notes:
            if (stuck := restore_replay(wb, where)) is not None:
                wb.discard_changes()
                return RedOutcome("failed", stuck)
            return None
        wb.discard_changes()
        return RedOutcome(
            "failed",
            "test code changed production files while a gate ran (a test may not write outside its own files): "
            + "; ".join(notes[:5]),
        )

    def refuse_tampering() -> RedOutcome | None:  # before a hold: the person is never shown a tampering step
        found = preexisting_test_changes(wb, task, base, stale, listed)
        return _reject_preexisting(wb, found) if found else None

    run_setup(wb)  # an agent-edited environment must not decide the gate
    arm_replay_guard(wb)  # a replayed step commits exactly its saved patch
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
    exempt = unchanged_criteria(wb, task, base_report)
    named = cited_criteria(wb.provider, wb.ref, task.links)  # L4-KSP-012: the leaf's own cited criteria
    required = {c for c in named if c not in exempt}
    proved_earlier: dict[str, EarlierRed] = {}
    existing: dict[str, tuple[str, ...]] = {}
    tracing: dict[str, tuple[str, ...]] = {}
    pre_satisfied: dict[str, tuple[str, ...]] = {}
    confirmation = PreSatisfied()
    based = BaseRunResult()
    earlier: dict[str, EarlierRed] = {}
    overridden: dict[str, Override] = {}  # criteria a person's `accept` carried (design D8)
    overridden_tests: dict[str, tuple[str, ...]] = {}
    if family and new_ids and not set(report.collection_errors) - set(base_report.collection_errors):
        # owner decision 4: a cited criterion that an earlier red of the unit proved, and whose tests pass now, needs
        # no copy among the new tests
        traced_new = set().union(*(trace_ids(report.tests[i]) for i in new_ids))
        passing_now = {
            i: trace_ids(case) for i, case in report.tests.items() if i not in new_ids and case.status == "passed"
        }
        existing = {c: tuple(sorted(i for i, ids in passing_now.items() if c in ids)) for c in required - traced_new}
        proved_earlier = confirmed_by_earlier_red(wb, {c: t for c, t in existing.items() if t}, report, new_ids)
        check = check_criteria(
            result,
            family,
            {i: report.tests[i] for i in new_ids},
            trace_hint=trace_rules(wb.cfg.gates.test.command).hint,
            exempt=exempt | set(proved_earlier),  # M2: an honest step may list a criterion an earlier red proved
            required=required - set(proved_earlier),
            aliases=named,
            links=", ".join(task.links),
        )
        for test in check.untraced:
            wb.emit("test.untraced", task=task.key, test=test)
        if check.error:
            wb.discard_changes()
            return RedOutcome("failed", check.error)
        if over := over_cap_text(
            {i: report.tests[i] for i in new_ids},
            cap_universe(wb.provider, family),
            wb.cfg.verifier.max_criteria_per_test,
        ):  # L4-VER-052: before any variant run
            wb.discard_changes()
            return RedOutcome("failed", over)
        tracing = check.tracing
        passing = {c: t for c, t in tracing.items() if all(report.tests[i].status == "passed" for i in t)}
        earlier = {**proved_earlier, **confirmed_by_earlier_red(wb, passing, report, new_ids)}  # L4-IMP-003
        confirmation = confirm_pre_satisfied(wb, {c: t for c, t in passing.items() if c not in earlier}, real=report)
        for criterion in proved_earlier:  # proved by tests that exist already: recorded like the no-new-test path
            wb.emit(
                "criterion.pre_satisfied", task=task.key, criterion=criterion, tests=list(existing[criterion]), via=VIA
            )
        if (out := tampered("pre-satisfied confirmation")) is not None:
            return out
        left = {c: passing[c] for c in (*confirmation.unconfirmed, *confirmation.inconclusive)}
        if left:  # whatever the zero-value run left (all of it, or part): last, the base run, which only confirms
            based = confirmed_by_base_run(wb, left, new_ids, real=report)
            if (out := tampered("base run")) is not None:
                return out
        out, overridden = _decide_pre_satisfied(wb, task, passing, confirmation, based, result, refuse_tampering)
        if out is not None:
            return out
        overridden_tests = {c: tuple(passing[c]) for c in overridden}
        _accept(wb, task, "pre_satisfied", overridden)
        pre_satisfied = passing
        for criterion, tests in pre_satisfied.items():
            wb.emit("criterion.pre_satisfied", task=task.key, criterion=criterion, tests=list(tests),
                    **_via(criterion, earlier, based, confirmation, overridden))  # fmt: skip
    # a stale test that is gone or fails now was replaced on purpose; one that still passes is simply kept
    replaced = frozenset(
        t for t in (stale.tests if stale else ()) if t not in report.tests or report.tests[t].status != "passed"
    )

    named_changed: list[Tampered] = []  # the named tests this red step changed in place, once the attempt is judged

    def record_superseded() -> None:
        if replaced and stale:
            wb.emit(
                "tests.superseded", task=task.key, tests=sorted(replaced),
                criteria=sorted({c for t in replaced for c in stale.tests[t]}), reason="stale",
            )  # fmt: skip
        if named_changed:
            wb.emit(
                "tests.superseded", task=task.key, tests=sorted({test_id(t.path, t.name) for t in named_changed}),
                criteria=[], reason="named_by_task", source=listed.source,
            )  # fmt: skip

    def proof_of(criterion: str, tests: Sequence[str]) -> dict[str, Any]:
        """`tests` trace the criterion; `discriminating` are the ones the zero-value run showed to look at the answer.
        A criterion confirmed by an earlier red names that red's tests (`discriminating`), `via` and the newest red's
        commit and task; `tests` stay this step's own, which `classify_red` allows to pass."""
        if criterion in overridden:
            return {
                "tests": list(tests), "proof": PROOF_PRE_SATISFIED, "discriminating": list(overridden_tests[criterion]),
                "via": override_via(overridden[criterion]), "question": overridden[criterion].question,
                "answer_sha256": overridden[criterion].answer_sha256, **override_who(overridden[criterion]),
            }  # fmt: skip
        return {
            "tests": list(tests),
            "proof": PROOF_PRE_SATISFIED,
            "discriminating": list(
                earlier[criterion].tests
                if criterion in earlier
                else confirmation.confirmed[criterion]
                if criterion in confirmation.confirmed
                else based.confirmed[criterion]
                if criterion in based.confirmed
                else confirmation.not_applicable[criterion]
            ),
            **(
                {"via": VIA, "red_sha": earlier[criterion].red_sha, "red_task": earlier[criterion].red_task}
                if criterion in earlier
                else {}
                if criterion in confirmation.confirmed
                else {"via": BASE_VIA, "base_sha": based.base_sha}
                if criterion in based.confirmed
                else {"via": VIA_NOT_APPLICABLE}
            ),
        }

    def finish_already_satisfied(proofs: dict[str, dict[str, Any]]) -> RedOutcome:
        """The commit of a task whose every cited criterion is pre-satisfied: the stubs go back to the base, the task
        is ticked, the proof travels inside the commit, no green step follows (L4-IMP-003)."""
        new_tests = frozenset(new_ids)
        notes = result.notes_for_verifier  # the schema caps it at 2000 characters
        for path in scope.stub_files:
            restore_to_base(wb, base, path)  # a stub no test needs is not left behind
        guard.release(scope.stub_files)
        release_replay(wb, scope.stub_files)
        if scope.stub_files:  # a test may import a stub symbol it never calls: the restored head must still run
            final = wb.run_gate("test-restored", wb.cfg.gates.test.command, reports=wb.cfg.gates.test.reports)
            if (out := tampered("restored test run")) is not None:
                return out
            final_report = final.report
            if (
                final_report is None
                or final_report.collection_errors
                or any((c := final_report.tests.get(i)) is None or c.status != "passed" for i in new_ids)
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
        if linked := outside_links_reason(wb, base, "red"):
            wb.discard_changes()
            return RedOutcome("failed", linked)
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

    reported = tuple(sorted(set(result.criteria_ids)))
    cited = tuple(sorted(set(reported) | required))  # L4-KSP-013: the leaf's cited criteria are proved too
    reason = result.tdd_exemption.reason.strip() if result.tdd_exemption else ""
    if (  # L4-IMP-003: no new test, no file changed, and the task says that tests of an earlier task already hold it
        reported and reason.startswith(ALREADY_SATISFIED) and not new_ids and not test_files and not scope.stub_files
        and not [p for p in changed if p != wb.ledger_rel]
        and not set(report.collection_errors) - set(base_report.collection_errors)
    ):  # fmt: skip
        if unknown := [c for c in cited if c not in family]:
            wb.discard_changes()
            return RedOutcome("failed", f"criteria that are not one of this unit's: {', '.join(unknown)}")
        candidates = {
            c: tuple(sorted(i for i, case in report.tests.items() if case.status == "passed" and c in trace_ids(case)))
            for c in cited
        }
        if bare := [c for c, tests in candidates.items() if not tests]:
            wb.discard_changes()
            return RedOutcome("failed", f"no test traces {', '.join(bare)} yet: write a new test for each")
        earlier = confirmed_by_earlier_red(wb, candidates, report, frozenset())
        confirmation = confirm_pre_satisfied(wb, {c: t for c, t in candidates.items() if c not in earlier}, real=report)
        if (out := tampered("pre-satisfied confirmation")) is not None:
            return out
        left = {c: candidates[c] for c in (*confirmation.unconfirmed, *confirmation.inconclusive)}
        if left:
            every = {t for tests in candidates.values() for t in tests}
            based = confirmed_by_base_run(wb, left, every, real=report)
            if (out := tampered("base run")) is not None:
                return out
        out, overridden = _decide_pre_satisfied(wb, task, candidates, confirmation, based, result, refuse_tampering)
        if out is not None:
            return out
        overridden_tests = {c: tuple(candidates[c]) for c in overridden}
        _accept(wb, task, "pre_satisfied", overridden)
        for criterion, tests in candidates.items():
            wb.emit("criterion.pre_satisfied", task=task.key, criterion=criterion, tests=list(tests),
                    **_via(criterion, earlier, based, confirmation, overridden))  # fmt: skip
        return finish_already_satisfied({c: proof_of(c, ()) for c in candidates})
    allowed = {t for tests in pre_satisfied.values() for t in tests}
    still_rejected = preexisting_test_changes(wb, task, base, stale, listed)
    named_in_place = split_named(_preexisting_changes(wb, task, base, stale), listed)[1] if listed.tests else []
    if broken := [t for t in still_rejected if (t.path, t.name) in set(listed.tests)]:
        return _reject_preexisting(wb, broken)  # a named test is changed in place, never removed: before the verdict
    verdict = classify_red(
        base_report, report, test_files_changed=test_files,
        failure_kinds=True, allowed_passing=allowed, excerpt=excerpter(wb),
        rules=trace_rules(wb.cfg.gates.test.command), superseded=stale.tests if stale else (),
        named_changed=[(t.path, t.name) for t in named_in_place],
    )  # fmt: skip
    if not verdict.ok:
        wb.discard_changes()
        return RedOutcome("failed", verdict.reason, excerpt=verdict.excerpt)
    if still_rejected:  # after classify_red: it keeps its reasons
        return _reject_preexisting(wb, still_rejected)
    named_changed[:] = named_in_place
    proofs = {criterion: proof_of(criterion, tests) for criterion, tests in pre_satisfied.items()}
    proofs.update({criterion: proof_of(criterion, ()) for criterion in proved_earlier})
    open_criteria = {c: t for c, t in tracing.items() if c not in pre_satisfied}
    discriminating: Mapping[str, Sequence[str]] = {}
    run_b_overrides: dict[str, Override] = {}  # run (b) criteria a person's `accept` carried
    zeroed = list(scope.stub_files)
    if open_criteria:  # L4-IMP-084: the stubs that HEAD holds (an earlier task's) answer run (b) with red's own
        head_stubs = head_stub_modules(wb, sorted({t for tests in open_criteria.values() for t in tests}))
        zeroed = sorted({*zeroed, *head_stubs})
    if open_criteria and zeroed:
        vacuity = vacuity_check(wb, zeroed, open_criteria, real=report)
        if (out := tampered("vacuity check")) is not None:
            return out
        if vacuity.reason or vacuity.vacuous:  # the agent's: the message lists the inconclusive ones apart
            wb.discard_changes()
            return RedOutcome("failed", vacuity.message)
        if vacuity.inconclusive:
            overrides = {
                c: o
                for c, o in accepted_overrides(wb, task.key, "vacuity").items()
                if c in open_criteria and o.covers(open_criteria[c])
            }
            open_ = sorted(c for c in vacuity.inconclusive if c not in overrides)
            if open_:
                held = HeldCheck(
                    task.key, "red", "vacuity", tuple(open_),
                    tuple(sorted({t for c in open_ for t in open_criteria[c]})), vacuity.inconclusive[open_[0]],
                    ("test-zero",),
                )  # fmt: skip
                held = capture(wb, held, result)  # before the discard: an accept replays this step (L4-IMP-065)
                wb.discard_changes()
                return RedOutcome("held", held=held)
            run_b_overrides = {c: overrides[c] for c in vacuity.inconclusive}
            _accept(wb, task, "vacuity", run_b_overrides)
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
        if criterion in run_b_overrides:  # counted on the evidence of the real run (run (b) could not decide)
            proofs[criterion] |= {
                "discriminating": list(tests), "via": override_via(run_b_overrides[criterion]),
                "question": run_b_overrides[criterion].question,
                "answer_sha256": run_b_overrides[criterion].answer_sha256,
                **override_who(run_b_overrides[criterion]),
            }  # fmt: skip
    worse = worse_static_gates(wb, base, "red")  # a lint error in a test file would be frozen and deadlock green
    if (out := tampered("static gates")) is not None:
        return out
    if worse:
        wb.discard_changes()
        return RedOutcome("failed", worse)
    new_tests = frozenset(new_ids)
    notes = result.notes_for_verifier  # the schema caps it at 2000 characters
    if tracing and not open_criteria:  # every cited criterion is pre-satisfied: the harness has proved it (L4-IMP-003)
        return finish_already_satisfied(proofs)
    if (out := tampered("before the red commit")) is not None:
        return out
    if linked := outside_links_reason(wb, base, "red"):
        wb.discard_changes()
        return RedOutcome("failed", linked)
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
    new_ids = frozenset(fold_subtest_id(str(i)) for i in event.data.get("tests", []))  # an older run: L4-GAT-006
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
    if step.kind == "held":
        assert step.held is not None
        return RedOutcome("held", held=step.held)
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
    for actor in ("human", "agent"):  # an agent's unfreeze is never recorded as a person's (L4-QMD-009, review 2 N2)
        people = Unfreeze(
            tuple(g for g in human.grants if g.reason == "human_answer" and g.by == actor),
            human.kept if actor == "human" else (),
        )
        if people.paths:
            wb.emit(
                "task.unfrozen", task=task.key, paths=list(people.paths), reason="human_answer", by=actor,
                question=people.question, answer_sha256=people.answer_sha256, red_sha=red.manifest.red_sha,
                kept=[{"path": p, "why": why} for p, why in people.kept],
            )  # fmt: skip
    for grant in (g for g in human.grants if g.reason == "delegate_answer"):  # L4-DLG-014: its own label
        wb.emit(
            "task.unfrozen", task=task.key, paths=list(grant.paths), reason="delegate_answer", question=grant.question,
            answer_sha256=grant.answer_sha256, by="delegate", profile=grant.profile, model=grant.model,
            red_sha=red.manifest.red_sha,
        )  # fmt: skip
    if named.paths or named.kept:  # `kept` is recorded even when nothing opens: it is the only place that says why
        wb.emit(
            "task.unfrozen", task=task.key, paths=list(named.paths), reason="named_by_task", source=source,
            red_sha=red.manifest.red_sha, kept=[{"path": p, "why": why} for p, why in named.kept],
        )  # fmt: skip
    step = step_or_replay(wb, "green", task, attempt, previous_failure, unfreeze)
    if step.kind != "ok":
        wb.discard_changes()  # back to the red commit: it stays, the work of this attempt does not
        if step.kind == "held":
            assert step.held is not None
            return GreenOutcome("held", held=step.held)
        if step.kind == "blocked":
            assert step.result is not None
            return GreenOutcome("blocked", questions=step.result.questions, summary=step.blocked_summary)
        return GreenOutcome("failed", step.reason, excerpt=step.excerpt)
    _check_opened(wb, red, unfreeze, red.manifest)
    put_back = restore_frozen(wb.git, manifest, events=wb, excludes=wb.excludes)
    put_back += freeze_test_paths(wb, task, base, keep=unfreeze.paths, phase="green")
    release_replay(wb, put_back)  # a replayed step keeps what the freeze put back: the patch's version is not expected
    run_setup(wb)  # gates.setup runs on an environment the harness rebuilt after the agent step (L4-SEC-036)
    arm_replay_guard(wb)  # a replayed step commits exactly its saved patch
    gate = wb.run_gate("test", wb.cfg.gates.test.command, reports=wb.cfg.gates.test.reports, extra_env=fix_gate_env(wb))
    stuck = restore_replay(wb, "test run")
    reason, named = green_failures(red.base_report, sorted(red.new_ids), gate, red.superseded)
    hung = gate_hung(gate) if reason else []
    excerpt = excerpter(wb)(gate.report, named) if reason and named and gate.report is not None else ""
    if hung:
        excerpt = hang_excerpt(hung) or excerpt
        wb.emit("gate.hung", task=task.key, tests=[h.id for h in hung], attempt=attempt)
    held: HeldCheck | None = None
    if not reason:
        reason, held = _undiscriminating(wb, red, unfreeze, gate.report, task)
    stuck = stuck or restore_replay(wb, "test-at-red run")
    if held is not None and (unsafe := stop_on_unsafe(wb)):  # a planted link or a failed restore wins over a hold
        held, reason = None, unsafe
    if held is not None:  # the test-at-red run could not decide: held, or counted on a person's `accept`
        overrides = accepted_overrides(wb, task.key, "at_red")
        open_ = sorted(t for t in held.tests if t not in overrides)
        if open_:
            assert step.result is not None
            kept = capture(wb, held.only(open_), step.result)  # before the discard: an accept replays this step
            wb.discard_changes()  # back to the red commit, which stays; the attempt is not counted
            return GreenOutcome("held", held=kept)
        _accept(wb, task, "at_red", {t: overrides[t] for t in held.tests}, key="tests")
    reason = reason or worse_static_gates(wb, base, "green") or stuck or restore_replay(wb, "before the green commit")
    reason = stop_on_unsafe(wb) or reason or outside_links_reason(wb, base, "green")
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
    if has_human_tag(wb.ref.path, task.title, "test-infra"):
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


def _undiscriminating(
    wb: Workbench, red: RedOutcome, unfreeze: Unfreeze, real: TestReport | None, task: Task
) -> tuple[str, HeldCheck | None]:
    """Decision 7: a corrected test must still fail against the red commit's code. Returns the reason it does not, or a
    hold when the `test-at-red` run could not decide (it ran no test or wrote no report, L4-IMP-060)."""
    assert red.manifest is not None
    ids = sorted(i for i in red.new_ids if _test_file(wb, i) in unfreeze.paths)
    if not ids:
        return "", None
    at_red = fails_at_red(wb, red.manifest.red_sha, ids, real=real)
    if at_red.inconclusive:
        held = HeldCheck(
            task.key, "green", "at_red", (), tuple(ids), at_red.inconclusive, ("test-at-red",),
        )  # fmt: skip
        return "", held
    passing = at_red.failing_not
    return (
        f"the corrected test no longer discriminates: {_list(passing)} do not fail against the red commit's code"
        " (they pass, are skipped or did not run there)"
        if passing
        else ""
    ), None


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


def _answer_events(wb: Workbench) -> list[LedgerEvent]:
    """The ledger events that record a person's answers: the run's, and a fix unit's own (its questions file lives in
    its own folder)."""
    events = _ledger_events(wb)
    if (own := read_ledger(wb.ref.path).events) and wb.ref.path != wb.worktree / Path(wb.ledger_rel).parents[2]:
        events = [*events, *own]
    return events


def config_grant(wb: Workbench, task: Task, phase: str) -> Unfreeze:
    """The gate and runner configuration files that a person's answer opens for this step (L4-IMP-041, D8), computed
    before the agent runs and recorded as `task.config_opened{task, phase, paths, question, answer_sha256, kept}`. A tag
    in the task title is read by `revert_gate_config` itself."""
    file = QuestionsFile.load(wb.ref.path / QUESTIONS_FILENAME)
    if file is None:
        return Unfreeze()
    scope = task_scope(wb.provider.tasks(wb.ref), task.key)
    got = config_opened(
        file.questions, _answer_events(wb), scope, config_files(wb.cfg, wb.worktree, wb.git), phase=phase
    )
    if got.paths or got.kept:
        wb.emit(
            "task.config_opened", task=task.key, phase=phase, paths=list(got.paths), question=got.question,
            answer_sha256=got.answer_sha256, kept=[{"path": p, "why": why} for p, why in got.kept],
        )  # fmt: skip
    return got


def _unfreeze_parts(wb: Workbench, task: Task, manifest: FreezeManifest) -> tuple[Unfreeze, Unfreeze, str | None]:
    """(what human answers unfreeze, what the task's own text opens, that text's source)."""
    human = Unfreeze()
    file = QuestionsFile.load(wb.ref.path / QUESTIONS_FILENAME)
    if file is not None:
        from l4.delegate.settings import delegate_settings

        scope = task_scope(wb.provider.tasks(wb.ref), task.key)
        switch = delegate_settings(wb.git, wb.cfg.forge.base_branch).delegate.unfreeze  # the base branch's (D15)
        human = unfrozen(
            file.questions,
            _answer_events(wb),
            scope,
            manifest,
            delegate_unfreeze=switch,
            fix_task=read_fix_marker(wb.ref.path) is not None,
        )
    named = named_task_text(wb, task)
    if named is None:
        return human, Unfreeze(), None

    def red_text(path: str) -> str | None:
        done = wb.git.run("show", f"{manifest.red_sha}:{path}", check=False)
        return done.stdout if done.returncode == 0 else None

    by_text = named_by_task(named[1], manifest, source=named[0], red_text=red_text)
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


def _opened_problem(
    wb: Workbench, red_sha: str, path: str, *, by_text: bool, modules: Collection[str], helper: bool = False
) -> str | None:
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
    after = target.read_text(encoding="utf-8", errors="replace")
    if helper:  # L4-IMP-083: a helper red added is filled in; its names and signatures stay
        return check_filled_helper(before, after, unit_modules=modules)
    return check_opened(before, after, named_by_task=by_text, unit_modules=modules)


def _check_opened(wb: Workbench, red: RedOutcome, unfreeze: Unfreeze, manifest: FreezeManifest) -> None:
    """After the agent step and before the frozen files are put back: each opened `.py` file keeps the three rules
    (all for a file the task's text opened, rule 3 for a support file a human answer unfroze). A file that breaks one is
    put back to its red version and recorded as `guard.violation{rule: "opened file"}`."""
    by_text = {p for g in unfreeze.grants if g.reason == "named_by_task" for p in g.paths}
    helpers = {p for g in unfreeze.grants if g.helper for p in g.paths}
    support = {p for p, f in manifest.files.items() if f.kind == "support"}
    checked = sorted(p for p in unfreeze.paths if p.endswith(".py") and (p in by_text or p in support))
    if not checked:
        return
    modules = unit_modules({*wb.branch_changed_files(), *wb.changed_files()}, wb.cfg)
    for path in checked:
        why = _opened_problem(
            wb, manifest.red_sha, path, by_text=path in by_text, modules=modules, helper=path in helpers
        )
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
    restored: list[str] = field(default_factory=list)  # paths put back to the base (a replay does not expect them)


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
            review.restored.append(path)
            wb.emit("guard.violation", path=path, rule="test support file", action="restored", phase="single")
        elif _matches(tdd.test_globs, path):
            if not existed or (path in own_tests and _appended(wb, base, path, target)):
                review.kept.append(path)
            else:
                _put_back(wb, base, path, existed)
                review.restored.append(path)
                why = _APPEND_RULE if path in own_tests else ""
                wb.emit("guard.test_tamper", path=path, phase="single", **({"reason": why} if why else {}))
        else:
            review.non_test.append(path)
    return review


def _put_back(wb: Workbench, base: str, path: str, existed: bool) -> None:
    restore_to_base(wb, base, path)  # a link at or above the path is removed, never followed


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


def _discriminating_tests(wb: Workbench, added: Sequence[str], task: Task) -> tuple[list[str], str, HeldCheck | None]:
    """(the added tests that look at the answer, the reason when none does, a hold when the runs could not decide).
    A tests chore that cites a criterion is checked as the verifier would a round later (`discriminate_extra`,
    L4-VER-009): a test counts when it fails by assertion when the project's functions answer their zero value, or on
    the unit base's code. With no unit base the chore is accepted: the verifier still decides at verification. When
    every added test is inconclusive (the runs could not decide, could not reach a test in another language, or could
    not be made: a project whose code is not Python, L4-VER-050) the chore is held with a harness question, like a red
    step (L4-IMP-063): accepting it would let an agent pass a chore with tests that were made unrunnable on purpose; its
    `Runs:` line names the runs that were made, none when none was. When some added tests are rejected and the others
    inconclusive the attempt fails, and the reason lists only the rejected ones as passing both runs, and each
    inconclusive one apart with its reason."""
    base_sha = unit_base(wb)
    if base_sha is None:
        return [], "", None
    outcome = discriminate_extra(wb, list(added), base_sha)
    if outcome.accepted:
        return sorted(outcome.accepted), "", None
    if added and all(t in outcome.inconclusive for t in added):  # the runs could not decide, or none could be made
        reason = outcome.inconclusive[sorted(added)[0]]
        held = HeldCheck(task.key, "green", "tests", (), tuple(sorted(added)), reason, outcome.made)
        return [], "", held
    shown = ", ".join([t for t in sorted(added) if t not in outcome.inconclusive][:MAX_LISTED])
    apart = "; ".join(
        f"{t}: inconclusive: {outcome.inconclusive[t]}" for t in sorted(outcome.inconclusive)[:MAX_LISTED]
    )
    inconclusive = f" Inconclusive, not counted as passing: {apart}." if apart else ""
    zero, base = ("test-extra-zero" in outcome.made), ("test-extra-base" in outcome.made)
    runs = (
        "when the project's functions answer their zero value and on the unit's base code"
        if zero == base
        else "when the project's functions answer their zero value"
        if zero
        else "on the unit's base code"
    )  # no run recorded: both
    why = (
        f"none of the tests you added looks at the answer: they pass {runs} ({shown}).{inconclusive} Assert the value "
        "the cited criterion's scenario names, through the interface the design names, so that a wrong implementation "
        "fails by assertion"
    )
    return [], why, None


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
    ci_job = chore_ci_job(_ledger_events(wb), findings)
    step = step_or_replay(wb, "single", task, attempt, previous_failure, adds_tests=adds_tests, ci_job=ci_job)
    if step.kind != "ok":
        wb.discard_changes()
        if step.kind == "held":
            assert step.held is not None
            return GreenOutcome("held", held=step.held)
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
        release_replay(wb, review.restored)
    elif kind == "refactor" and not _freeze_refactor(wb, task, base):
        wb.discard_changes()
        if retake:
            return _already_done(wb, task, findings, attempt)
        return GreenOutcome("failed", "nothing changed")
    else:  # a chore has no red phase: the tests that carry the family's proofs are put back, as green does for its own
        put_back = restore_frozen(wb.git, frozen, events=wb, excludes=wb.excludes, phase="single")
        put_back += freeze_test_paths(wb, task, base, phase="single")
        release_replay(wb, put_back)
    run_setup(wb)
    arm_replay_guard(wb)  # a replayed step commits exactly its saved patch
    gate = wb.run_gate("test", wb.cfg.gates.test.command, reports=wb.cfg.gates.test.reports, extra_env=fix_gate_env(wb))
    stuck = restore_replay(wb, "test run")
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
    if adds_tests and not reason and added and gate.report is not None:  # L4-VER-052: before the discrimination runs
        reason = over_cap_text(
            {i: gate.report.tests[i] for i in added},
            cap_universe(wb.provider, {c.id for c in wb.provider.criteria(wb.ref)}),
            wb.cfg.verifier.max_criteria_per_test,
        )
    reason = reason or worse_static_gates(wb, base, "green") or ci_steps_reason(wb, ci_steps)
    discriminating: list[str] | None = None
    if adds_tests and not reason and added and CRITERION_IN_TITLE.search(task.title):
        discriminating, reason, held = _discriminating_tests(wb, added, task)
        stuck = stuck or restore_replay(wb, "discrimination runs")
        if held is not None and (unsafe := stop_on_unsafe(wb)):  # a planted link or a failed restore wins over a hold
            held, reason = None, unsafe
        if held is not None:
            overrides = {t: o for t, o in accepted_overrides(wb, task.key, "tests").items() if t in held.tests}
            open_ = sorted(t for t in held.tests if t not in overrides)
            if open_:
                assert step.result is not None
                kept = capture(wb, held.only(open_), step.result)  # before the discard: an accept replays this step
                wb.discard_changes()
                return GreenOutcome("held", held=kept)
            _accept(wb, task, "tests", overrides, key="tests")
            discriminating = sorted(held.tests)
    reason = reason or stuck or restore_replay(wb, "before the commit")
    reason = stop_on_unsafe(wb) or reason or outside_links_reason(wb, base, "single")
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
