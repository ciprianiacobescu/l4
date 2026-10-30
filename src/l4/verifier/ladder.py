"""The verification ladder (SPEC 10.2) and its glue to the orchestrator: steps 0, 1, 2, 3 (with the end-to-end gate),
4, 4a, 5 (generated UI tests), 8 (S1, recorded only), 9 and 10, the `verify_hook` the orchestrator resolves lazily, and
the thin `l4 verify` handler.

Verdict to lifecycle (SPEC 12.0, verifier 1.20): PASS -> `verify_pass` (`verified`); FAIL -> `verify_fail_fix`
(`fixing`, exit 10, with a fix unit: `fixloop.after_verdict`) or `verify_fail_exhausted` (`escalated`, exit 13);
NEEDS_HUMAN -> `verify_needs_human` (`awaiting_human`, exit 11, with verdict questions).
A required role that cannot serve (independence, probes, a usage limit, a judge that cannot run)
raises `RoleUnavailable`/`RoleLimit`, which the orchestrator turns into `waiting_capacity` (exit 12); any other
exception leaves the phase at `verifying` with exit 1 and no verdict (L4-VER-010).

Independence is decided before anything runs, by `l4.verifier.selection`: the judge chain is walked with a veto on
every judge whose vendor (or model) equals that of an implementer profile of the unit, `unknown` is never independent
(L4-VER-001). A judge that hits a usage limit, or whose served model is not the one its profile names, gives way to the
next independent judge in the same round (nothing left: `waiting_capacity`, `no independent verifier`). The verdict
records how the vendors are known (`independence:` in verification.md and verdict.json).

Evidence is committed by the hook itself, on every verdict, as `docs(<unit>): verification round <n> [skip ci]` and
pushed: the worktree is deleted before the next run, and the orchestrator's last commit carries only the ledger.
On PASS the hand-off commit (forge-and-ci 1.39) still has the ledger to carry.
M1: verifier 1.19 (resume per step), steps 6 and 7.
"""

import dataclasses
import functools
import hashlib
import json
import logging
import os
import shutil
import time
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from l4.agents.base import RunResult
from l4.agents.factory import RoleUnavailable, Selected, WaitingCapacity
from l4.availability.vendor import RoutedLookup, built_in_routed, resolve_vendor
from l4.ci.detect import in_ci_job
from l4.ci.failing_step import active_ci_steps
from l4.clarifier.actor import answer_actor
from l4.config.defaults import cache_root
from l4.config.preflight import preflight_run_config
from l4.config.redaction import load_app_config
from l4.config.schema import L4Config
from l4.context import AppContext
from l4.evidence.collect import (
    Evidence,
    ScopeEvidence,
    changed_unit_files,
    collect_evidence,
    coverage_sources,
    human_only,
    scope_evidence,
)
from l4.evidence.report import evidence_json
from l4.evidence.scope import file_kind
from l4.exitcodes import ExitCode, L4Exit
from l4.fsutil import UnsafeFile, read_regular_file, reject_symlinks
from l4.gates.coverage import cov_env
from l4.gates.junit import TestReport, fold_subtest_id
from l4.implementer.discrimination import discriminate_extra, file_of_test, worktree_files
from l4.implementer.repaircheck import function_source
from l4.implementer.tdd import RoleLimit
from l4.implementer.test_locate import file_of_id, window
from l4.implementer.unit_context import (
    MAX_SOURCE_BYTES,
    NOT_READ,
    Cut,
    SourceFile,
    plan_context,
    read_sources,
    safe_label,
)
from l4.implementer.workbench import Workbench, clip_subject, make_workbench
from l4.llm.agent_judge import JUDGE_ADAPTERS, AgentJudge, LLMBackend, workbench_request_factory
from l4.llm.system_one import SystemOneBackend, open_s1_backend
from l4.memory.round import curate_round
from l4.orchestrator import run_unit_in_worktree
from l4.outcome import CommandResult
from l4.planner import facts_of, next_action
from l4.s1.items import item_keys_by_subject, items_from_evidence, project_key
from l4.s1.records import append_records
from l4.s1.shadow import run_shadow
from l4.sandbox.caches import verifier_caches
from l4.sandbox.select import sandbox_refusal
from l4.security.protected import glob_match
from l4.services import HookContext, Services, load_hooks
from l4.specs.base import Criterion, Framework, SpecError, Task
from l4.specs.criteria import base_criteria_at
from l4.specs.feedback import FeedbackFile
from l4.specs.followup import feedback_home
from l4.specs.markers import MAX_TASKS_BYTES
from l4.specs.providers import providers_for
from l4.specs.questions import QUESTIONS_FILENAME, QuestionsFile
from l4.specs.tasks_text import task_text
from l4.state.fold import fold
from l4.state.ledger import LedgerEvent, read_ledger
from l4.state.lifecycle import Trigger
from l4.state.status import load_snapshot, select_runnable
from l4.vcs.git import Git
from l4.vcs.trailers import CommitTrailers
from l4.verifier import base_tests, diffparts
from l4.verifier.aggregate import aggregate_criterion, aggregate_unit, judge_findings, pick_verdicts
from l4.verifier.audit import choose, run_audit
from l4.verifier.basemerge import bring_in_base
from l4.verifier.conventions import test_conventions
from l4.verifier.diffparts import (
    DiffPart,
    DiffParts,
    blob_ids,
    bookkeeping_pathspecs,
    file_rows,
    judge_parts,
    part_listing,
)
from l4.verifier.evidence import (
    commit_verifier_tests,
    read_verdict,
    restore_round,
    reusable,
    stored_finding,
    subject_sha,
)
from l4.verifier.feedback import (
    apply_addressed,
    contains_name,
    decide_feedback,
    feedback_ref,
    judged_outcomes,
    not_addressed_findings,
    pending_feedback,
    record_addressed,
    record_no_status,
    unjudged_outcomes,
)
from l4.verifier.fixloop import FamilyProvider, after_verdict, decide_fix, family_of, family_tasks, family_units
from l4.verifier.gates import (
    E2eGateOutcome,
    e2e_gate_configured,
    failure_records,
    run_build_gates,
    run_e2e_gate,
    run_test_gate,
)
from l4.verifier.generate import generate_ui_tests
from l4.verifier.integrity import IntegrityContext, record_outcome, run_integrity
from l4.verifier.judge import (
    AnswerRef,
    CriterionVerdict,
    FollowUpView,
    JudgePrompt,
    JudgeRun,
    JudgeVerdict,
    NamedChange,
    PartView,
    RoundOutput,
    SatisfiedRef,
    TaskRef,
    UnreadableAnswers,
    accepted_refs,
    answer_refs,
    build_judge_prompt,
    named_tests,
    render_answers,
    reply_counts,
    run_judge,
    satisfied_refs,
)
from l4.verifier.judge_followup import (
    apply_followups,
    criterion_files,
    find_splits,
    followup_rows,
    plan_followups,
    proof_tasks,
    split_note,
    task_files,
)
from l4.verifier.judge_parts import merge_part_verdicts
from l4.verifier.notes import verdict_section
from l4.verifier.playwright import playwright_enabled, ui_files, unit_changed_files
from l4.verifier.preconditions import check_preconditions, record_ci_steps, record_feedback
from l4.verifier.report import write_round_evidence
from l4.verifier.s1_labels import record_human_labels
from l4.verifier.s1_step import S1Step, S1Wiring, evidence_for, record_rows, run_step
from l4.verifier.selection import (
    Independence,
    JudgeSeat,
    assess_independence,
    independence_constraint,
    no_independent_verifier,
    probe_vetoes,
    seat_of,
    select_judge,
)
from l4.verifier.support_base import unit_test_plan
from l4.verifier.traceability import (
    OVER_CAP_LABEL,
    PROOF_HUMAN,
    apply_adequacy,
    count_named,
    extra_candidates,
    extra_proofs,
    ignored_findings,
    inadequate_findings,
    new_covered,
    rescue_ceiling,
    trace_criteria,
)
from l4.verifier.types import (
    AuditRecord,
    CounterexampleRun,
    CriterionEvidence,
    FeedbackRef,
    Finding,
    GeneratedOutcome,
    Severity,
    StepRecord,
    TracingTest,
    Verdict,
    VerifyResult,
)
from l4.verifier.ui_step import (
    edited_findings,
    gap_findings,
    plan_generation,
    previously_generated,
    ui_hold_views,
    ui_waivers,
    unclosed_holds,
    with_generated,
)
from l4.verifier.verdicts import (
    HoldView,
    apply_finding_verdicts,
    carry_rejects,
    consume_verdicts,
    effective_verdicts,
    finding_sha256,
    hold_covers,
    hold_id,
    hold_sha256,
    raise_verdict_questions,
    regressions,
    round_judges,
    settle_holds,
    supersede_stale_verdicts,
    text_sha256,
    unresolved_holds,
    verdict_targets,
)

log = logging.getLogger("l4.verify")

TRIGGERS = {Verdict.PASS: Trigger.VERIFY_PASS, Verdict.FAIL: Trigger.VERIFY_FAIL_FIX,
            Verdict.NEEDS_HUMAN: Trigger.VERIFY_NEEDS_HUMAN}  # fmt: skip
MAX_DIFF_CHARS = 120_000
MAX_NOTES_CHARS = 6_000
MAX_HOLD_PATHS = 5  # the unseen files a `judge view:` hold names
UNEXECUTED_NOTE = "not executed in M0: the verifier worktree is M1 (verifier 1.5)"
JUDGE_TIMEOUT_S = 600  # no config key in SPEC section 5; `claude -p` answers in 15-20 s [V]
VERIFY_PHASES = ("implemented", "verifying")
# (id, name, why it did not run when nothing earlier stopped the ladder), in ladder order
LADDER = (
    ("0", "preconditions", ""), ("1", "integrity", ""), ("2", "build", ""), ("3", "tests", ""),
    ("4", "traceability", ""), ("4a", "audit sampling", ""), ("5", "ui test generation", ""), ("6", "quality", ""),
    ("8", "s1 judge", ""), ("9", "judge", ""), ("10", "aggregation", ""),
)  # fmt: skip


def require_independent_judge(
    cfg: L4Config, implementer_profiles: Sequence[str], judge: str, *, role: str = "judges"
) -> None:
    """`RoleUnavailable` (exit 12) when the judge is not independent of every implementer profile of the unit. The
    ladder no longer calls it (`select_judge` walks the chain with `independence_constraint`, also for the audit
    writer); it stays until M1.5 is on `main` (parallel-ownership §4, item 6)."""
    judge_profile = cfg.profiles[judge]
    if reason := independence_constraint(cfg, implementer_profiles)(judge, judge_profile):
        raise RoleUnavailable(role, f"no independent verifier ({reason})")


@dataclass(frozen=True)
class ShadowWiring:
    cache_file: Path  # $L4_CACHE/s1-calibration.jsonl, next to the criterion rows
    log_path: Path
    environ: dict[str, str]


@dataclass
class VerifyContext:
    wb: Workbench
    judge: LLMBackend
    judge_profile: str
    implementer_profiles: list[str]
    round: int
    judge_timeout_s: int
    independence: Independence | None = None  # the record of the judge that gave the verdict (set by the judge step)
    seat: JudgeSeat = field(default_factory=JudgeSeat)
    # the next independent judge, after a usage limit (with its run) or a served-model mismatch (None):
    # `(reason, limited run) -> (backend, profile name)`; `WaitingCapacity` when none is left
    next_judge: Callable[[str, RunResult | None], tuple[LLMBackend, str]] | None = None
    audit_writer: Callable[[], LLMBackend] | None = None  # opens the `verifier_agent` role: only when a sample is drawn
    verifier_tests: list[Path] = field(default_factory=list)  # the tests the verifier wrote in this round (C9)
    ui_writer: Callable[[], LLMBackend] | None = None  # the same role for step 5, opened when a UI criterion is a gap
    s1: S1Wiring | None = None  # step 8: None when `verifier.s1.enabled` is off or `roles.s1_judge` is empty
    routed: RoutedLookup = built_in_routed  # the possible vendors of a judge or implementer on kiro-cli `auto`
    shadow: "ShadowWiring | None" = None  # step 8's record-only engines: set when `verifier.s1.shadow` names profiles
    base_note: str = ""  # step 0's note about the base: merged now, or already contained (`bring_in_base`)


def _git_diff(wb: Workbench, base_sha: str, head: str) -> tuple[str, bool]:
    """`git diff <base>...<head>` without the harness's bookkeeping (`bookkeeping_pathspecs`, L4-VER-040: the `.l4/`
    files, the harness's memories, and the `verification.md`, `questions.md` and `feedback.md` of each unit of the
    family: the harness's own files, not the unit's work), cut at MAX_DIFF_CHARS. A file of those names anywhere else
    is project content and stays."""
    raw = wb.git.run_bytes(
        "diff", "--no-color", "--no-ext-diff", "--no-textconv", f"{base_sha}...{head}", "--", ".",
        *bookkeeping_pathspecs(_unit_dirs(wb)),
    )  # fmt: skip
    text = raw.decode("utf-8", errors="replace")
    return text[:MAX_DIFF_CHARS], len(text) > MAX_DIFF_CHARS


def _events(wb: Workbench) -> list[LedgerEvent]:
    return read_ledger(wb.ref.path).events


def _red_green(events: Sequence[LedgerEvent]) -> dict[str, str]:
    """New test id -> task, from the `task.red_ok` events (proven red by the implementer loop). A test that a
    `tests.superseded` event lists (a stale test that a reopened task's red step replaced, L4-OPS-015) is not expected
    any more, unless a later `task.red_ok` names it again. Every other test a red step added stays expected, so one
    that vanishes without that record is still a blocker, also in a reopened task. A test a later task changed in
    place because its reviewed text named it (`reason: "named_by_task"`, L4-IMP-082) still exists: it stays expected."""
    found: dict[str, str] = {}
    for e in events:
        if e.type == "tests.superseded" and e.data.get("reason") != "named_by_task":
            for t in e.data.get("tests") or ():
                found.pop(fold_subtest_id(str(t)), None)
        elif e.type == "task.red_ok":
            found.update(
                dict.fromkeys((fold_subtest_id(str(t)) for t in e.data.get("tests", [])), str(e.data.get("task", "")))
            )
    return found


def _named_changes(wb: Workbench, base: str, head: str, events: Sequence[LedgerEvent]) -> list[NamedChange]:
    """The tests a `tests.superseded{reason: "named_by_task"}` event lists (L4-IMP-082, L4-IMP-089): the existing tests
    red changed in place, once per id, in ledger order, with the source of the reviewed text. A test of another
    language carries its own lines (`test_locate.window`) at the base and at head, found through its file."""
    found: dict[str, tuple[str, bool]] = {}
    for e in events:
        if e.type == "tests.superseded" and e.data.get("reason") == "named_by_task":
            other = e.data.get("language") not in (None, "python")
            for test in e.data.get("tests") or ():
                found.setdefault(str(test), (str(e.data.get("source") or "a reviewed text"), other))
    paths: list[str] | None = None
    changes = []
    for test, (source, other) in found.items():
        before = after = ""
        if other:
            if paths is None:
                paths = wb.git.run("ls-tree", "-r", "--name-only", head, check=False).stdout.splitlines()
            path = file_of_id(test, paths)
            name = test.partition("::")[2]
            if path is not None:
                shown = [wb.git.run("show", f"{rev}:{path}", check=False) for rev in (base, head)]
                before, after = (window(r.stdout, name) or "" if r.returncode == 0 else "" for r in shown)
        changes.append(NamedChange(test, source, before, after))
    return changes


def _repaired_changes(wb: Workbench, head: str, events: Sequence[LedgerEvent]) -> list[NamedChange]:
    """The tests a `task.repaired` event lists (L4-IMP-091, L4-VER-070), once per test, in ledger order: the test's own
    lines in its file at the step's base (the event's `base`) and at head, so that the judge sees what the repair
    changed and can tell a weakened check. A base that is not a commit, or a test that is not found, shows no lines."""
    found: dict[str, tuple[str, str]] = {}
    for e in events:
        if e.type == "task.repaired":
            for test in e.data.get("tests") or ():
                found.setdefault(str(test), (str(e.data.get("task") or "?"), str(e.data.get("base") or "")))
    changes = []
    for test, (task_key, base) in found.items():
        path, _, name = test.partition("::")
        before = after = ""
        if base and wb.git.run("cat-file", "-e", f"{base}^{{commit}}", check=False).returncode == 0:
            shown = [wb.git.run("show", f"{rev}:{path}", check=False) for rev in (base, head)]
            texts = [r.stdout if r.returncode == 0 else "" for r in shown]
            before, after = (function_source(t, name) or "" for t in texts)
        source = f"repaired by task {task_key} (a fix step for the unit's own failing test)"
        changes.append(NamedChange(test, source, before, after))
    return changes


def _notes(events: Sequence[LedgerEvent]) -> str:
    parts = [
        f"Task {e.data.get('task')} ({'red' if e.type == 'task.red_ok' else 'green'}): {e.data['notes']}"
        for e in events
        if e.type in ("task.red_ok", "task.done") and e.data.get("notes")
    ]
    return "\n\n".join(parts)[:MAX_NOTES_CHARS]


def _guards(events: Sequence[LedgerEvent]) -> list[str]:
    return [
        f"{e.type}: {e.data.get('path') or e.data.get('rule') or ''}".strip()
        for e in events
        if e.type.startswith("guard.")
    ]


MAX_CANDIDATES_LISTED = 5


def _candidates(e: CriterionEvidence, cap: int, unit_size: int) -> str:
    """L4-VER-054: the tests over the per-test cap that the judge may name for a criterion: at most five, the one with
    the fewest traced criteria first (then by id), and none above the ceiling, which no answer of the judge could
    count. `unit_size` 0 is a unit of unknown size: nothing is left out."""
    ceiling = rescue_ceiling(unit_size, cap) if unit_size else None
    usable = sorted((t for t in e.capped if ceiling is None or t.over_cap <= ceiling), key=lambda t: (t.over_cap, t.id))
    if not usable:
        return ""
    shown = "; ".join(f"{t.id} (traces {t.over_cap} criteria)" for t in usable[:MAX_CANDIDATES_LISTED])
    more = len(usable) - MAX_CANDIDATES_LISTED
    return f"; {OVER_CAP_LABEL}: {shown}" + (f" (+{more} more)" if more > 0 else "")


def _gate_summary(result: VerifyResult, *, cap: int = 3, unit_size: int = 0) -> str:
    lines = [f"- {g.name}: {g.status}" + (f" ({g.reason})" if g.reason else "") for g in result.gates]
    lines.append("")
    lines.append("Per-test outcome of the full test gate (test id, status):")
    lines += [f"  {test}  {status}" for test, status in sorted(result.tests.items())] or ["  (no tests)"]
    # an accepted audit test ran in the audit gate run, not in the full test gate: it is listed here from the audit
    # records, so that the matrix below never names a test this list lacks (M1.12, K2)
    lines += [
        f"  {test}  passed  (audit test of {a.criterion}, written and run by the verifier this round)"
        for a in result.audit
        if a.status == "accepted"
        for test in a.tests
    ]
    if result.trace:
        lines += ["", "Traceability (criterion, state, tracing tests with status and proof):"]
        lines += [
            f"  {e.criterion}  {e.state}  "
            + (
                "; ".join(f"{t.id} ({t.status}, {t.proof}{', ' + t.note if t.note else ''})" for t in e.tests)
                or "no discriminating test"
            )
            + _candidates(e, cap, unit_size)
            for e in result.trace
        ]
    if result.audit:
        lines += ["", "Audit tests written by the verifier agent (criterion, status):"]
        lines += [f"  {a.criterion}  {a.status}" + (f"  {a.reason}" if a.reason else "") for a in result.audit]
    if result.generated:
        lines += ["", "UI tests the verifier generated (criterion, status, outcome at the merge base and at head):"]
        lines += [
            f"  {g.criterion}  {g.status}  base {g.base or '-'}  head {g.head or '-'}  {g.path or ''}"
            for g in result.generated
        ]
    if result.integrity is not None and result.integrity.declared:
        lines += ["", "Suppression comments the implementer declared (review them):"]
        lines += [f"  {d}" for d in result.integrity.declared]
    return "\n".join(lines)


def _emit_step(vc: VerifyContext, record: StepRecord, subject: str) -> None:
    evidence = json.dumps(dataclasses.asdict(record), sort_keys=True)
    vc.wb.emit(
        "verify.step", round=vc.round, step=record.step, subject_sha=subject, status=record.status,
        evidence_hash=hashlib.sha256(evidence.encode()).hexdigest(),
    )  # fmt: skip


@dataclass
class _Run:
    """Mutable state of one `verify_unit` call."""

    result: VerifyResult
    records: dict[str, StepRecord] = field(default_factory=dict)
    judged: JudgeVerdict | None = None
    e2e: E2eGateOutcome | None = None  # step 3's end-to-end gate, when it ran: step 4 traces it, step 5 reads its page
    s1: S1Step | None = None  # step 8, until step 9 has spoken and the calibration rows can be written
    scope: ScopeEvidence | None = None  # step 1: what the unit changed and whether it stays in scope
    evidence: Evidence | None = None  # step 3: scope, tests ran and diff coverage (step 6 reports the coverage part)
    report: TestReport | None = None  # step 3's JUnit report


def _step(vc: VerifyContext, run: _Run, step: str, name: str, body: Callable[[], tuple[bool, str]]) -> bool:
    """Run one step, record it (`verify.step`) and report whether the ladder goes on."""
    start = time.monotonic()
    ok, note = body()
    _record_step(vc, run, StepRecord(step, name, "ok" if ok else "failed", round(time.monotonic() - start, 1), note))
    return ok


def _record_step(vc: VerifyContext, run: _Run, record: StepRecord) -> None:
    run.records[record.step] = record
    _emit_step(vc, record, run.result.subject_sha)


def _sha10(wb: Workbench, path: str) -> str | None:
    """The first 10 hex digits of the sha256 of a regular file of the worktree: what an extra proof is tied to."""
    target = wb.worktree / path
    if target.is_symlink() or not target.is_file():
        return None
    return hashlib.sha256(target.read_bytes()).hexdigest()[:10]


@dataclass
class _ExtraDecision:
    proofs: dict[str, dict[str, str]] = field(default_factory=dict)  # criterion -> test -> human | chore
    reasons: dict[str, str] = field(default_factory=dict)  # a rejected test -> why it stays ignored


def _extra_proof_step(
    vc: VerifyContext,
    run: _Run,
    trace: Sequence[CriterionEvidence],
    events: Sequence[LedgerEvent],
    base: str,
    head: str,
) -> _ExtraDecision | None:
    """Step 4's discrimination of tests that carry a criterion and have no proof, and that only people wrote or a test
    chore added (L4-VER-009, M1.11 decision 8): at most two gate runs, and only when there is such a test. An accepted
    one is recorded (`verify.extra_proof`, tied to its file's content) and counts as evidence with the proof `human` or
    `chore`; a rejected one stays a minor finding, with its reason."""
    wb = vc.wb
    chore_files = {str(f) for e in events if e.type == "task.tests_added" for f in e.data.get("files") or []}
    files = {t: f for item in trace for t, _ in item.ignored if (f := file_of_test(wb, t)) is not None}
    attribution = {f: PROOF_HUMAN for f in sorted(set(files.values())) if human_only(wb.git, base, head, f)}
    candidates = extra_candidates(trace, attribution, chore_files, file_of=files.get)
    if not candidates:
        return None
    outcome = discriminate_extra(
        wb, sorted({t for found in candidates.values() for t, _ in found}), base, real=run.report
    )
    decided = _ExtraDecision()
    groups: dict[tuple[str, str, str], list[str]] = {}
    for criterion, found in candidates.items():
        for test, source in found:
            if (via := outcome.accepted.get(test)) is None:
                decided.reasons[test] = (
                    f"inconclusive: {outcome.inconclusive[test]}"
                    if test in outcome.inconclusive
                    else outcome.reasons.get(test) or "passes against the zero values and on the base"
                )
                continue
            decided.proofs.setdefault(criterion, {})[test] = source
            groups.setdefault((criterion, source, via), []).append(test)
    for (criterion, source, via), tests in sorted(groups.items()):
        paths = sorted({files[t] for t in tests})
        wb.emit(
            "verify.extra_proof", round=vc.round, criterion=criterion, tests=sorted(tests), source=source, via=via,
            files={p: _sha10(wb, p) for p in paths},
        )  # fmt: skip
    return decided


def _unit_dirs(wb: Workbench) -> list[str]:
    """The unit directories of the family (the unit and its fix units), relative to the repository."""
    root = wb.worktree.resolve()
    return [u.path.resolve().relative_to(root).as_posix() for u in family_units(wb.provider, wb.ref)]


def _family_sources(wb: Workbench) -> tuple[SourceFile, ...]:
    """The unit's spec files, then each fix unit's under its own name: the judge reads the regression scenarios and the
    findings they answer. A file it cannot read whole (over the size limit, a link) comes back named (L4-KSP-014)."""
    found = list(read_sources(wb.ref.path, wb.worktree))
    for unit in family_units(wb.provider, wb.ref)[1:]:
        found += [replace(s, name=f"{unit.name}/{s.name}") for s in read_sources(unit.path, wb.worktree)]
    return tuple(found)


def _done_tasks(wb: Workbench, satisfied: Sequence[SatisfiedRef]) -> list[TaskRef]:
    """Every done task of the unit and of its fix units, with its whole text from its own `tasks.md` (owner decision 7):
    the judge checks that the diff does what each says. A task of the `satisfied` block is asked there already."""
    asked = {r.task for r in satisfied}
    found = []
    for unit in family_units(wb.provider, wb.ref):
        own = getattr(wb.provider, "own_tasks", wb.provider.tasks)
        text = _task_text_of(unit.path, wb.ref.framework)
        prefix = "" if unit == wb.ref else f"{unit.name}/"
        found += [TaskRef(f"{prefix}{t.key}", text(t)) for t in own(unit) if t.done and f"{prefix}{t.key}" not in asked]
    return found


def _family_answers(wb: Workbench, events: Sequence[LedgerEvent]) -> list[AnswerRef | UnreadableAnswers]:
    """The answered questions of the unit and then of each fix unit, in that order, the fix units' under their own
    names (`<fix unit>/Q-NNN`, as `_done_tasks` names their tasks), with the answer's actor computed as the
    implementer's `_answers` does (L4-VER-065). A `questions.md` that cannot be read is named and does not stop the
    round, as `_asked_feedback` does for `feedback.md`."""
    found: list[AnswerRef | UnreadableAnswers] = []
    for unit in family_units(wb.provider, wb.ref):
        fix = None if unit == wb.ref else unit.name
        path = unit.path / QUESTIONS_FILENAME
        try:
            file = QuestionsFile.load(path)
        except SpecError as exc:
            log.warning("%s: questions.md of %s is not read: %s", wb.ref.id, unit.name, exc)
            found.append(UnreadableAnswers(unit.name, str(exc).replace(str(path), QUESTIONS_FILENAME)))  # no local path
            continue
        if file is None:
            continue
        unit_git = wb.git.at(unit.path)
        found += answer_refs(
            file.questions, prefix=f"{fix}/" if fix else "",
            actor_of=lambda q, unit=unit, fix=fix, unit_git=unit_git: answer_actor(
                unit_git, unit.path, q, events, fix_unit=fix
            ),
        )  # fmt: skip
    return found


def _spec_hold_cuts(cuts: Sequence[Cut]) -> list[tuple[str, Cut]]:
    """What the judge did not see of its spec, as holds (L4-KSP-014), each with the cut that raised it: a file over the
    size limit or not readable, and a requirements, bugfix or spec-delta file cut by the budget (the criteria's
    source). A design or proposal cut by the budget is only named."""
    holds = []
    for cut in cuts:
        if cut.reason == "oversize":
            text = f"the spec file {cut.path} is larger than {MAX_SOURCE_BYTES} bytes: the judge saw only its start"
        elif cut.reason in NOT_READ:
            kind = {"symlink": "a symlink", "bad_name": "named unsafely"}.get(cut.reason, "not a regular file")
            text = f"the spec file {safe_label(cut.path)} is {kind}: the judge did not see it"
        elif cut.kind == "narrative":
            text = f"the spec file {cut.path} was cut to fit the judge's budget: the judge saw only part of it"
        else:
            continue
        holds.append((text, cut))
    return holds


def _spec_holds(cuts: Sequence[Cut]) -> list[str]:
    return [text for text, _ in _spec_hold_cuts(cuts)]


def _spec_hold_views(cuts: Sequence[Cut], sources: Sequence[SourceFile]) -> dict[str, HoldView]:
    """The content a person's accept of a spec-file hold is bound to: the hash of the spec file as read (and its size
    and why it was cut), so that an edit of the file voids the accept like a changed blob does for a diff hold."""
    by_path = {s.path: s for s in sources}
    views = {}
    for text, cut in _spec_hold_cuts(cuts):
        source = by_path.get(cut.path)
        body = (
            f"{cut.path}\t{hashlib.sha256(source.text.encode('utf-8')).hexdigest()}\t{source.total_bytes}\t{source.reason}"
            if source is not None
            else f"{cut.path}\tunread\t{cut.reason}"
        )
        views[text] = HoldView(hashlib.sha256(f"{text}\0{body}".encode()).hexdigest(), (cut.path,))
    return views


def verify_unit(vc: VerifyContext) -> VerifyResult:
    wb = vc.wb
    head = wb.head()
    events = _events(wb)
    criteria = wb.provider.criteria(wb.ref)
    subject = subject_sha(wb.git, head, _unit_dirs(wb))
    prev = read_verdict(wb.ref.path, vc.round - 1) if vc.round > 1 else None
    if reusable(prev, subject, [c.id for c in criteria]):
        assert prev is not None
        return _resume(vc, prev, criteria, events, subject)
    result = VerifyResult(
        wb.ref.id, vc.round, Verdict.NEEDS_HUMAN, "", head, judge_profile=vc.judge_profile,
        implementer_profiles=list(vc.implementer_profiles), red_green=_red_green(events), guards=_guards(events),
        subject_sha=subject,
    )  # fmt: skip
    run = _Run(result)
    findings = result.findings
    base_sha = ""
    report: TestReport | None = None

    def preconditions() -> tuple[bool, str]:
        nonlocal base_sha
        pre = check_preconditions(wb)
        record_ci_steps(wb, pre)
        record_feedback(wb, pre)
        base_sha = result.base_sha = pre.base_sha
        findings.extend(pre.findings)
        return not pre.findings, "; ".join(filter(None, [vc.base_note, *(f.title for f in pre.findings)]))

    def integrity() -> tuple[bool, str]:
        tasks = [(u.id, t) for u, t in family_tasks(wb.provider, wb.ref)]
        ctx = IntegrityContext(wb.git, wb.cfg, base_sha, head, events, tasks, _unit_dirs(wb), wb.ref.id)
        result.integrity = run_integrity(ctx)
        ran = base_tests.check_base_tests(wb, ctx, prior=result.integrity.checks, round_no=vc.round)
        record_outcome(result.integrity, base_tests.ROW, ran)
        findings.extend(result.integrity.findings)
        blocking = [f.title for f in result.integrity.findings if f.blocking]
        note = "; ".join(blocking) or f"{len(result.integrity.checks)} sub-checks"
        if result.integrity.unfrozen:
            note += f" (+{len(result.integrity.unfrozen)} unfrozen by human answers)"
        return not result.integrity.blocked, note + _scope_step(vc, run, base_sha)

    def build() -> tuple[bool, str]:
        out = run_build_gates(wb, active_ci_steps(events))
        result.gates.extend(out.gates)
        findings.extend(out.findings)
        return out.ok, "; ".join(f.detail for f in out.findings)

    def tests() -> tuple[bool, str]:
        nonlocal report
        extra, cov_dir = _coverage_env(vc, base_sha)
        out = run_test_gate(wb, set(result.red_green), extra_env=extra)
        result.gates.append(out.gate)
        findings.extend(out.findings)
        report = run.report = out.report
        if out.report is not None:
            result.tests = {i: c.status for i, c in out.report.tests.items()}
        notes = [f.detail for f in out.findings]
        gate_ok, seen, browser_report = out.ok, out.report, None
        if out.ok and e2e_gate_configured(wb.cfg):
            run.e2e = browser = run_e2e_gate(wb)
            result.gates.append(browser.gate)
            findings.extend(browser.findings)
            if browser.report is not None:
                result.tests |= {i: c.status for i, c in browser.report.tests.items()}
            notes += [f.detail for f in browser.findings]
            gate_ok, browser_report = browser.ok, browser.report
            result.e2e_tests = sorted(browser.report.tests) if browser.report is not None else []
            seen = _merged(out.report, browser.report)  # a new e2e test file ran in the e2e gate, not in this one
        result.failures, result.failures_dropped = failure_records(out.report, browser_report, wb.redactor.redact_text)
        blockers = _collect_step(vc, run, base_sha, seen, gate_ok, extra, cov_dir)
        return gate_ok and not blockers, "; ".join([*notes, *(f.detail for f in blockers)])

    def traceability() -> tuple[bool, str]:
        assert report is not None
        # pass-to-pass compares with the archived specs AT THE BASE COMMIT, read from git: the worktree is at the unit's
        # head, where the agent could have copied a delta into openspec/specs (HB-3, L4-VER-009)
        archived = base_criteria_at(wb.git, base_sha) if wb.ref.framework is Framework.OPENSPEC else []
        if wb.ref.framework is Framework.KIRO and isinstance(wb.provider, FamilyProvider):
            archived = wb.provider.merged_parent_criteria()  # a follow-up's merged parent: its folder is protected
        browser = run.e2e.report if run.e2e is not None else None
        # the e2e tests of earlier generations stand (ledger, unchanged file); any other e2e test needs a red proof
        generated, edited = previously_generated(events, wb.worktree, browser)
        trace = functools.partial(
            trace_criteria, criteria, report, events, wb.cfg, base=archived,
            extra_reports=[browser] if browser else [], generated=generated, file_sha=lambda path: _sha10(wb, path),
        )  # fmt: skip
        proved = extra_proofs(events, lambda path: _sha10(wb, path))  # people's and chores' tests seen to discriminate
        result.trace = trace(extra=proved)
        decided = _extra_proof_step(vc, run, result.trace, events, base_sha, head)
        if decided is not None:
            for criterion, tests_proved in decided.proofs.items():
                proved.setdefault(criterion, {}).update(tests_proved)
            result.trace = trace(extra=proved, reasons=decided.reasons)
        findings.extend(ignored_findings(result.trace))
        findings.extend(edited_findings(edited))
        covered = sum(e.state == "covered" for e in result.trace)
        return True, f"{covered}/{len(criteria)} criteria covered"

    reached = (
        _step(vc, run, "0", "preconditions", preconditions)
        and _step(vc, run, "1", "integrity", integrity)
        and _step(vc, run, "2", "build", build)
        and _step(vc, run, "3", "tests", tests)
    )
    if reached:
        _step(vc, run, "4", "traceability", traceability)
        _audit_step(vc, run, criteria, base_sha)
        _generate_step(vc, run, criteria, base_sha, events)
        _quality_step(vc, run)
        _s1_step(vc, run, criteria, base_sha)
        _shadow_step(vc, run, base_sha)
        try:
            _judge_step(vc, run, base_sha, events)
        finally:  # step 8's rows survive a judge that raises (their `judge` column stays empty)
            _calibrate(vc, run)
        findings.extend(_unsafe_findings(wb))
        _finalize(vc, run, criteria, events)
    else:  # a failed step 0-3 is a FAIL (a blocker came with it); no criterion was judged
        findings.extend(_unsafe_findings(wb))
        result.verdict = aggregate_unit(findings, result.criteria, result.holds)
    _publish_evidence(run)
    run.records["10"] = StepRecord("10", "aggregation", "ok", note=result.verdict.value)
    _emit_step(vc, run.records["10"], subject)
    result.steps = [
        run.records.get(step, StepRecord(step, name, "not_run", note=why or "an earlier step failed"))
        for step, name, why in LADDER
    ]
    return result


def _unsafe_findings(wb: Workbench) -> list[Finding]:
    """L4-SEC-021 part c: a gate run of the verifier planted a link on a path the harness restores, or the harness could
    not put a file back. The round ends FAIL; the verifier goes on (a planted link halts the implementer, not the
    verifier, which has no attempt to retry)."""
    planted = wb.planted_links()
    if planted:
        paths = ", ".join(dict.fromkeys(u.link for u in planted))
        return [Finding(Severity.BLOCKER, "a gate run planted a symbolic link in the worktree", paths, "deterministic")]
    if wb.unsafe:
        paths = ", ".join(dict.fromkeys(u.path for u in wb.unsafe))
        return [Finding(Severity.BLOCKER, "could not restore a file after a gate run", paths, "deterministic")]
    return []


def _scope_step(vc: VerifyContext, run: _Run, base_sha: str) -> str:
    """Step 1, second half (M1.6): what the unit changed and whether the spec names it. No test run is needed. The
    findings (`sdd.scope_check: fail`) and the holds (`warn`) join the round; a check that cannot run is a hold, never
    a silent pass. Returns the text appended to step 1's note."""
    wb, result = vc.wb, run.result
    try:
        run.scope = scope = scope_evidence(wb, base_sha, result.head_sha, wb.ref)
    except Exception as exc:  # noqa: BLE001 - the repository content is untrusted: nothing here may end the round
        log.warning("%s: scope check failed: %s", wb.ref.id, exc)
        result.holds.append(f"scope: could not be checked ({type(exc).__name__})")
        return "; scope check did not run"
    result.findings.extend(scope.outcome.findings)
    result.holds.extend(h.text for h in scope.holds)
    held = f", {len(scope.holds)} held" if scope.holds else ""
    return f"; scope: {len(scope.files)} changed file(s){held}"


def _coverage_env(vc: VerifyContext, base_sha: str) -> tuple[dict[str, str] | None, Path | None]:
    """The environment that loads `l4_cov` into step 3's test run, and the directory it writes (under the worktree, the
    one place the gate sandbox can write). None when diff coverage is off or no Python code file changed; the directory
    is None when `.l4-out` or `.l4-out/cov` is a symlink: the worktree is repository content, and clearing or writing
    through a planted link would delete or write outside the checkout (as `gates.e2e` refuses for `.l4-out/e2e`)."""
    wb = vc.wb
    try:
        reject_symlinks(wb.worktree, ".l4-out", "cov")
    except UnsafeFile as exc:
        log.warning("%s: coverage is not set up: %s", wb.ref.id, exc)
        return None, None
    cov_dir = wb.worktree / ".l4-out" / "cov"
    shutil.rmtree(cov_dir, ignore_errors=True)  # an earlier round's output must not stand in for this one's
    if wb.cfg.verifier.evidence.diff_coverage.mode == "off":
        return None, cov_dir
    try:
        unit_rel = wb.ref.path.resolve().relative_to(wb.worktree.resolve()).as_posix()
        packages = coverage_sources(wb.git, base_sha, wb.head(), wb.cfg, unit_rel)
        return (cov_env(cov_dir, packages) if packages else None), cov_dir
    except (ValueError, OSError) as exc:
        log.warning("%s: coverage is not set up: %s", wb.ref.id, exc)
        return None, cov_dir


def _merged(unit: TestReport | None, browser: TestReport | None) -> TestReport | None:
    """The tests of step 3's unit gate and of its end-to-end gate as one report (the tests-ran check reads both)."""
    if unit is None or browser is None:
        return unit
    return TestReport({**unit.tests, **browser.tests}, [*unit.collection_errors, *browser.collection_errors])


def _collect_step(
    vc: VerifyContext,
    run: _Run,
    base_sha: str,
    report: TestReport | None,
    gate_ok: bool,
    extra: dict[str, str] | None,
    cov_dir: Path | None,
) -> list[Finding]:
    """Step 3, second half: scope, tests ran and diff coverage from the gate's report and the plugin's output. The
    tests-ran findings join the round here (the blockers are returned: they stop the ladder like a failed gate);
    step 6 reports the coverage ones."""
    wb, result = vc.wb, run.result
    try:
        ev = collect_evidence(
            wb, base_sha, result.head_sha, report, cov_dir, wb.ref, new_tests=set(result.red_green),
            gate_passed=gate_ok, cov_nonce=(extra or {}).get("L4_COV_NONCE"), step1=run.scope,
        )  # fmt: skip
    except Exception as exc:  # noqa: BLE001
        log.warning("%s: evidence collection failed: %s", wb.ref.id, exc)
        result.holds.append(f"evidence: could not be collected ({type(exc).__name__})")
        return []
    run.evidence = ev
    ran = ev.ran.findings if ev.ran is not None else []
    result.findings.extend(ran)
    return [f for f in ran if f.severity is Severity.BLOCKER]


def _quality_step(vc: VerifyContext, run: _Run) -> None:
    """Step 6 (M1.6): the diff-coverage check. Under `warn` an unmeasured or low coverage is a hold, under `fail` a
    deterministic major finding (`check_diff_coverage`); the numbers are in the Evidence section."""
    ev, result = run.evidence, run.result
    mode = vc.wb.cfg.verifier.evidence.diff_coverage.mode
    why = (
        "verifier.evidence.diff_coverage.mode is off" if mode == "off"
        else "step 3 produced no evidence" if ev is None or ev.coverage is None
        else ""
    )  # fmt: skip
    if why:
        run.records["6"] = StepRecord("6", "quality", "not_run", note=why)
        return
    assert ev is not None and ev.coverage is not None
    result.findings.extend(ev.coverage_check.findings)
    result.holds.extend(h.text for h in ev.later_holds)
    dc = ev.coverage
    note = ev.coverage_check.note or f"{dc.percent}% of the changed executable lines ran"
    if dc.status == "ok" and dc.other_files:  # the Python was measured, the rest of the change was not
        note += f"; not measured: {dc.outside_note}"
    _record_step(vc, run, StepRecord("6", "quality", "ok", 0.0, note))


def _shadow_step(vc: VerifyContext, run: _Run, base_sha: str) -> None:
    """Step 8, shadow half (M1.6, D12): every item of the unit's evidence is asked of the engines in
    `verifier.s1.shadow`, and items and answers are recorded. Nothing here reads an answer to decide; whatever fails
    is logged and the round goes on."""
    wb, cfg, result = vc.wb, vc.wb.cfg, run.result
    if vc.shadow is None or run.evidence is None or run.report is None:
        return
    try:
        unit_rel = wb.ref.path.resolve().relative_to(wb.worktree.resolve()).as_posix()
        items = items_from_evidence(
            run.evidence, git=wb.git, cfg=cfg, redactor=wb.redactor, project=project_key(wb.git, wb.ref.id),
            unit_id=wb.ref.id, unit_name=wb.ref.name, spec_dir=unit_rel, base=base_sha, head=result.head_sha,
            report=run.report, new_tests=set(result.red_green), origin="live", run_id=wb.run_id, round=vc.round,
        )  # fmt: skip
        shadow = run_shadow(cfg, items, redactor=wb.redactor, environ=vc.shadow.environ, log_path=vc.shadow.log_path)
        run.evidence.item_keys = item_keys_by_subject(items)
        append_records([vc.shadow.cache_file, wb.out_dir / "s1" / f"{wb.run_id}.jsonl"], [*items, *shadow.answers])
        wb.emit(
            "verify.s1_shadow", round=vc.round, items=len(items), asked=len(shadow.asked),
            engines=[f"{e.profile}:{e.status}" for e in shadow.engines],
        )  # fmt: skip
    except Exception as exc:  # noqa: BLE001 - S1 decides nothing: its trouble stops nothing
        log.warning("%s: s1 shadow not recorded: %s", wb.ref.id, exc)


def _publish_evidence(run: _Run) -> None:
    """`VerifyResult.evidence`: the `l4/evidence@1` object of the round, taken last so that it carries the S1 item
    keys. A round that stopped before step 3 has the scope part only."""
    if run.evidence is not None:
        run.result.evidence = run.evidence.to_json()
    elif run.scope is not None:
        holds = [h.to_json() for h in run.scope.holds]
        run.result.evidence = evidence_json(run.scope.outcome, None, None, holds=holds)


def _resume(
    vc: VerifyContext, prev: dict[str, Any], criteria: Sequence[Criterion], events: Sequence[LedgerEvent], subject: str
) -> VerifyResult:
    """Resume at aggregation (D4): the previous round ended NEEDS_HUMAN on this subject with these criteria, so its
    steps 0-9 stand. Only step 10 runs again, with the human verdicts recorded since: no gate run, no judge call."""
    result = restore_round(prev, vc.wb.ref.id, vc.round)
    run = _Run(result, judged=JudgeVerdict.model_validate(prev["judge_verdict"]) if prev.get("judge_verdict") else None)
    for record in result.steps:
        if record.status == "reused":
            _emit_step(vc, record, subject)
    result.subject_sha = subject
    reused = int(prev.get("round") or 0)
    result.feedback_outcomes = judged_outcomes(events, reused)  # the judge check is not stored
    _carry_accepted(vc, events, reused)
    _finalize(vc, run, criteria, events)
    last = StepRecord("10", "aggregation", "ok", note=result.verdict.value)
    _emit_step(vc, last, subject)
    result.steps.append(last)
    return result


def _carry_accepted(vc: VerifyContext, events: Sequence[LedgerEvent], reused: int) -> None:
    """L4-VER-017: the judge's answers to the accepted findings in the round this one reuses, recorded again for this
    round (`reused_from`), since the merge guard reads the rows of the PASS round only (L4-YOLO-028). A reused round
    with no rows carries none."""
    for event in events:
        data = event.data
        if event.type != "review.accepted_judged" or data.get("round") != reused or not data.get("id"):
            continue
        vc.wb.emit(
            "review.accepted_judged", id=str(data["id"]), round=vc.round, addressed=data.get("addressed") is True,
            evidence=str(data.get("evidence") or ""), profile=str(data.get("profile") or ""), reused_from=reused,
        )  # fmt: skip


def _finalize(vc: VerifyContext, run: _Run, criteria: Sequence[Criterion], events: Sequence[LedgerEvent]) -> None:
    """Step 10 (SPEC 10.4), shared by a fresh round and a resumed one: the human verdicts that apply, every criterion
    aggregated from its evidence, the judge and the human, then the unit."""
    wb, result = vc.wb, run.result
    current = {c.id: text_sha256(c) for c in criteria}
    current |= {f.id: finding_sha256(f.id) for f in result.findings if f.source == "judge" and f.blocking}
    current |= {hold_id(h): hold_sha256(h, result.hold_views) for h in result.holds}
    effective = effective_verdicts(events, current)
    result.findings, effective = carry_rejects(
        result.findings, effective, events, lambda n, target: stored_finding(read_verdict(wb.ref.path, n), target)
    )
    result.findings = apply_finding_verdicts(result.findings, effective)
    result.findings = settle_holds(result.findings, result.holds, effective, hold_covers(events))  # a reject: a FAIL
    picked = pick_verdicts(run.judged) if run.judged is not None else {}
    evidence = {e.criterion: e for e in result.trace}
    required = wb.cfg.sdd.require_traceability
    result.criteria = [
        aggregate_criterion(
            c.id, c.alias, picked.get(c.id), result.cx_runs.get(c.id), trace=evidence.get(c.id),
            human=effective.get(c.id), require_traceability=required,
            cap=wb.cfg.verifier.max_criteria_per_test, unit_size=len(criteria),
            split=split_note(result.judge_split.get(c.id)),
        )
        for c in criteria
    ]  # fmt: skip
    s1_p = {r.criterion: r.p for r in result.s1 if r.p is not None}
    result.criteria = [  # what each criterion rests on, and S1's p beside it (recorded, never used)
        dataclasses.replace(c, tests=_evidence_tests(evidence.get(c.id)), s1_p=s1_p.get(c.id)) for c in result.criteria
    ]
    ids = [c.id for c in criteria] + [f.id for f in result.findings] + [hold_id(h) for h in result.holds]
    result.holds = unresolved_holds(result.holds, effective)  # an answered hold, either way, is not asked again
    result.human = [effective[t] for t in dict.fromkeys(ids) if t in effective]
    for void in regressions(effective, result.trace):  # a regression voids an accept for good (D3)
        wb.emit("human.void", question=void.question, target=void.target, reason="a tracing test fails at head")
    result.verdict = aggregate_unit(result.findings, result.criteria, result.holds)
    if result.verdict is Verdict.PASS:
        _hold_unjudged(vc, result)


def _hold_unjudged(vc: VerifyContext, result: VerifyResult) -> None:
    """L4-FBK-007, review #8: a round with pending items and no answer of this round's judge for one of them (the reply
    was discarded and a person accepted the hold, or the steps of an earlier round were reused) cannot PASS. Each such
    item becomes a not-addressed outcome (`not judged in this round`), so the round fails into the next feedback fix
    unit and the item is judged in a later round."""
    wb = vc.wb
    asked = _asked_feedback(wb)
    missing = unjudged_outcomes(asked, result.feedback_outcomes)
    if not missing:
        return
    result.feedback_outcomes = [*result.feedback_outcomes, *missing]
    result.findings.extend(not_addressed_findings(missing, asked))
    for outcome in missing:
        wb.emit("feedback.not_addressed", id=outcome.id, round=vc.round, evidence=outcome.evidence)
    result.verdict = aggregate_unit(result.findings, result.criteria, result.holds)


def _evidence_tests(e: CriterionEvidence | None) -> tuple[str, ...]:
    return tuple(t.id for t in e.tests if t.status == "passed" and t.adequate) if e is not None else ()


def _no_python(vc: VerifyContext, base_sha: str, head: str) -> bool:
    """The unit changed files outside the harness, spec and documentation paths and none of them is a `.py` file
    (tests included: a Python project's unit that only adds a test still audits). A unit that changed nothing there
    is not judged non-Python."""
    wb = vc.wb
    unit_rel = wb.ref.path.resolve().relative_to(wb.worktree.resolve()).as_posix()
    files = changed_unit_files(wb.git, base_sha, head, wb.cfg, unit_rel)
    return bool(files) and not any(p.endswith(".py") for p, _ in files)


def _audit_step(vc: VerifyContext, run: _Run, criteria: Sequence[Criterion], base_sha: str) -> None:
    """Step 4a (SPEC 10.2). Draws the sample, asks the verifier agent for the tests and judges them; an accepted one
    becomes evidence (`audit`), a failing one holds its criterion for a human."""
    wb, result = vc.wb, run.result
    ratio = wb.cfg.verifier.audit_sample_ratio
    why = (
        "roles.verifier_agent is empty" if vc.audit_writer is None
        else "verifier.audit_sample_ratio is 0" if ratio <= 0
        else ""
    )  # fmt: skip
    if not why and _no_python(vc, base_sha, result.head_sha):
        why = "audit sampling writes pytest tests only; changed code is not python"
    if why:
        run.records["4a"] = StepRecord("4a", "audit sampling", "not_run", note=why)
        return
    chosen, skipped = choose(new_covered(result.trace), ratio, wb.ref.id, vc.round)
    if not chosen:
        run.records["4a"] = StepRecord("4a", "audit sampling", "ok", note="no covered new criterion to audit")
        _emit_step(vc, run.records["4a"], result.subject_sha)
        return

    def body() -> tuple[bool, str]:
        assert vc.audit_writer is not None
        support = unit_test_plan(wb.git, wb.cfg, base_sha, result.head_sha, result.integrity)
        out = run_audit(
            wb, vc.audit_writer(), {c.id: c for c in criteria}, chosen, skipped, base_sha=base_sha,
            head=result.head_sha, round_no=vc.round, timeout_s=vc.judge_timeout_s, emit=wb.emit, support=support,
        )  # fmt: skip
        result.audit = out.records
        result.findings.extend(out.findings)
        vc.verifier_tests.extend(out.accepted)
        if out.cost_usd:
            result.cost_usd = (result.cost_usd or 0.0) + out.cost_usd
            wb.emit("budget.cost", usd=out.cost_usd, profile="verifier_agent", role="audit")
        result.trace = _with_audit(result.trace, out.records)
        counts = {s: sum(a.status == s for a in out.records) for s in {a.status for a in out.records}}
        note = ", ".join(f"{n} {s}" for s, n in sorted(counts.items()))
        if support.changes:
            note += f"; support files at the base: {len(support.changes)}"
        return True, note

    _step(vc, run, "4a", "audit sampling", body)


def _with_audit(trace: Sequence[CriterionEvidence], records: Sequence[AuditRecord]) -> list[CriterionEvidence]:
    by_id = {r.criterion: r for r in records}
    out = []
    for e in trace:
        r = by_id.get(e.criterion)
        if r is not None and r.status == "accepted":
            e = dataclasses.replace(e, tests=(*e.tests, *(TracingTest(t, "passed", "audit") for t in r.tests)))
        elif r is not None and r.status == "failed":
            e = dataclasses.replace(e, held=f"the audit test fails at head: {r.reason}")
        out.append(e)
    return out


def _ui_diff(wb: Workbench, base_sha: str, head: str, ui: Sequence[str]) -> str:
    """The unit's diff restricted to the UI files: what the test writer is shown (generate.py cuts it further)."""
    raw = wb.git.run_bytes(
        "diff", "--no-color", "--no-ext-diff", "--no-textconv", f"{base_sha}...{head}", "--", *ui,
    )  # fmt: skip
    return raw.decode("utf-8", errors="replace")[:MAX_DIFF_CHARS]


def _test_blobs(
    wb: Workbench, head: str, trace: Sequence[CriterionEvidence], changed: Collection[str] = ()
) -> Callable[[str], str]:
    """Test id -> the head blob of the file that holds it, for the tests step 4 traced to the criteria: what a UI
    hold's accept is bound to (`ui_step.ui_hold_binding`). A Python module is found in the work tree; any other id
    (`src/a.test.ts::name`, `src.a.test.ts::name`) by `test_locate.file_of_id` over the tree's files, the unit's
    changed files first when several match. A test whose file is not found keeps its id."""
    ids = {t.id for e in trace for t in e.tests} | {t for e in trace for t, _ in e.ignored}
    files = {i: file_of_test(wb, i) for i in ids}
    if any(f is None for f in files.values()):
        tree = worktree_files(wb)  # once
        files = {i: f or file_of_id(i, tree, changed) for i, f in files.items()}
    blobs = blob_ids(wb.git, head, sorted({f for f in files.values() if f}))
    return lambda test: (
        f"{files[test]}\t{blobs.get(files[test] or '', 'missing')}" if files.get(test) else f"{test}\tunmapped"
    )


def _generate_step(
    vc: VerifyContext, run: _Run, criteria: Sequence[Criterion], base_sha: str, events: Sequence[LedgerEvent]
) -> None:
    """Step 5 (SPEC 10.2, L4-VER-014). The targets are the UI-facing criteria that no test of the end-to-end report
    traces; each gets a Playwright test from the verifier agent, and the test counts only if it fails at the merge
    base and passes at head (generate.py). Accepted files stay in the worktree for the round's one test commit;
    a criterion that stays without one is `needs_human` through aggregation, with a finding that says why. A criterion
    whose accept is in force is *waived* first (L4-VER-067): no writer call, no hold, `verify.generated{waived}`."""
    wb, result, cfg = vc.wb, run.result, vc.wb.cfg
    browser = run.e2e
    changed: list[str] = []
    why = (
        "verifier.playwright.enabled is off" if not playwright_enabled(cfg)
        else "verifier.generate_missing_tests is off" if not cfg.verifier.generate_missing_tests
        else "gates.e2e has no command" if browser is None
        else ""
    )  # fmt: skip
    if not why:
        assert browser is not None
        changed = unit_changed_files(wb.git, base_sha, result.head_sha)
        proven = {e.criterion: {t.id for t in e.tests} for e in result.trace}  # step 4's evidence: the proved tests
        plan = plan_generation(criteria, browser.report, changed, cfg.verifier.playwright.ui_paths, proven=proven)
        why = plan.skipped
    if why:
        run.records["5"] = StepRecord("5", "ui test generation", "not_run", note=why)
        return
    if not plan.gaps:
        _record_step(vc, run, StepRecord("5", "ui test generation", "ok", note="every UI criterion has an e2e test"))
        return
    blob_of = _test_blobs(wb, result.head_sha, result.trace, changed)
    waived = ui_waivers(events, plan.gaps, result.trace, blob_of)
    result.findings.extend(gap_findings(plan.gaps, plan.unproved, waived))
    for criterion in plan.gaps:
        if criterion.id in waived:
            wb.emit("verify.generated", criterion=criterion.id, status="waived", by=waived[criterion.id], attempts=0)
            result.generated.append(
                GeneratedOutcome(
                    criterion.id, "waived", reason=f"waived by {waived[criterion.id]}", by=waived[criterion.id]
                )
            )
    gaps = [c for c in plan.gaps if c.id not in waived]
    if not gaps:
        note = f"{len(waived)} UI criteria waived by an accepted answer (L4-VER-067)"
        _record_step(vc, run, StepRecord("5", "ui test generation", "ok", note=note))
        return

    def hold_all(holds: list[str]) -> None:
        result.holds.extend(holds)
        result.hold_views |= ui_hold_views(holds, gaps, result.trace, blob_of)

    if vc.ui_writer is None:
        hold_all(unclosed_holds(gaps, []))
        run.records["5"] = StepRecord("5", "ui test generation", "not_run", note="roles.verifier_agent is empty")
        return

    def body() -> tuple[bool, str]:
        assert vc.ui_writer is not None and browser is not None
        ui = ui_files(changed, cfg.verifier.playwright.ui_paths)
        out = generate_ui_tests(
            wb, vc.ui_writer(), gaps, base_sha=base_sha, ui_diff=_ui_diff(wb, base_sha, result.head_sha, ui),
            snapshot=browser.snapshot or "",
            support=unit_test_plan(wb.git, wb.cfg, base_sha, result.head_sha, result.integrity),
        )  # fmt: skip
        result.generated = [*result.generated, *out.outcomes]
        vc.verifier_tests.extend(wb.worktree / path for path in out.paths)
        if out.cost_usd:
            result.cost_usd = (result.cost_usd or 0.0) + out.cost_usd
            wb.emit("budget.cost", usd=out.cost_usd, profile="verifier_agent", role="ui_tests")
        result.trace = with_generated(result.trace, out.outcomes)
        result.tests |= {i: "passed" for o in out.outcomes if o.accepted for i in o.tests}
        hold_all(unclosed_holds(gaps, out.outcomes))
        counts = {s: sum(o.status == s for o in out.outcomes) for s in {o.status for o in out.outcomes}}
        return True, ", ".join(f"{n} {s}" for s, n in sorted(counts.items()))

    _step(vc, run, "5", "ui test generation", body)


def has_system_one_profile(cfg: L4Config) -> bool:
    """Step 8 needs a `backend: system-one` profile on `roles.s1_judge`; an adapter profile there serves only the
    clarifier's `llm_boolean` stand-in (M1.8 A7: it made step 8 `unavailable` on every round)."""
    return any(getattr(cfg.profiles.get(name), "backend", None) == "system-one" for name in cfg.roles.s1_judge)


def _no_s1_reason(cfg: L4Config) -> str:
    if not cfg.roles.s1_judge:
        return "roles.s1_judge is empty"
    return (
        "no System One profile on roles.s1_judge (an adapter profile there serves only the clarifier's llm_boolean "
        "stand-in)"
    )


def _s1_step(vc: VerifyContext, run: _Run, criteria: Sequence[Criterion], base_sha: str) -> None:
    """Step 8 (SPEC 10.2, L4-VER-002 step 8): one S1 question per criterion over its evidence, recorded and never used
    to decide (D8). A server that is missing or down makes the step `unavailable` and the round goes on (SCN-VER-24)."""
    wb, result = vc.wb, run.result
    why = (
        "verifier.s1.enabled is off" if not wb.cfg.verifier.s1.enabled
        else _no_s1_reason(wb.cfg) if vc.s1 is None
        else "the unit has no criteria" if not criteria
        else ""
    )  # fmt: skip
    if why:
        run.records["8"] = StepRecord("8", "s1 judge", "not_run", note=why)
        return
    assert vc.s1 is not None
    start = time.monotonic()
    diff, _ = _git_diff(wb, base_sha, result.head_sha)
    run.s1 = step = run_step(vc.s1, wb.cfg, criteria, evidence_for(criteria, result.trace, diff))
    result.s1 = step.records
    for r in step.records:
        wb.emit(
            "verify.s1", round=vc.round, criterion=r.criterion, p=r.p, model=r.model, status=r.status,
            engine=r.engine, reason=r.reason, checkpoint=step.model, server_version=step.server_version,
        )  # fmt: skip
    _record_step(vc, run, StepRecord("8", "s1 judge", step.status, round(time.monotonic() - start, 1), step.note))


def _calibrate(vc: VerifyContext, run: _Run) -> None:
    """The calibration rows of step 8, written once the judge has answered: a row pairs S1's `p` with the
    deterministic state and the judge's word for the same criterion (L4-VER-008)."""
    wb, result = vc.wb, run.result
    if run.s1 is None or vc.s1 is None:
        return
    picked = pick_verdicts(run.judged) if run.judged is not None else {}
    try:
        record_rows(
            run.s1, vc.s1, run_file=wb.out_dir / "s1" / f"{wb.run_id}.jsonl", unit=wb.ref.id, run_id=wb.run_id,
            round_no=vc.round, deterministic={e.criterion: e.state for e in result.trace},
            judge={cid: v.verdict for cid, v in picked.items()},
        )  # fmt: skip
    except OSError as exc:  # S1 is corroborating only: a calibration file that cannot be written stops nothing
        log.warning("%s: s1 calibration rows not written: %s", wb.ref.id, exc)


def _asked_feedback(wb: Workbench) -> list[FeedbackRef]:
    """The items of the parent's `feedback.md` taken and not yet addressed: the judge is asked about them."""
    try:
        file = FeedbackFile.load(feedback_home(wb.ref.path))  # a follow-up judges its parent's items (L4-FBK-010)
    except SpecError as exc:  # an unreadable file is the person's to fix; it must not stop the round
        log.warning("%s: feedback.md is not read: %s", wb.ref.id, exc)
        return []
    return [feedback_ref(i) for i in pending_feedback(fold(_events(wb), wb.ref.id), file)]


MAX_NAME_FILE_BYTES = 1_000_000


def _changed_code(wb: Workbench, base_sha: str, head: str) -> list[str]:
    """The text, at `head`, of every non-test file the family changed since `base_sha`: the harness's own files, the
    spec and feedback files of the family's units, and the project's test files and test support files are left out."""
    raw = wb.git.run_bytes("diff", "--name-only", "-z", "--no-renames", "--diff-filter=d", f"{base_sha}...{head}")
    dirs = _unit_dirs(wb)
    found = []
    for path in filter(None, os.fsdecode(raw).split("\0")):
        if any(file_kind(path, unit, wb.cfg) in ("exempt", "test") for unit in dirs or [""]):
            continue
        if any(glob_match(g, path) for g in wb.cfg.tdd.test_support_globs):
            continue
        data = wb.git.run_bytes("show", f"{head}:{path}", check=False)[:MAX_NAME_FILE_BYTES]
        found.append(data.decode("utf-8", errors="replace"))
    return found


def _judge_step(vc: VerifyContext, run: _Run, base_sha: str, events: Sequence[LedgerEvent]) -> None:
    wb, result = vc.wb, run.result
    criteria = wb.provider.criteria(wb.ref)
    if not criteria:
        result.holds.append("the unit has no scenarios, so there is nothing for the judge to verify")
        run.records["9"] = StepRecord("9", "judge", "not_run", note="no criteria to judge")
        return
    ids = {c.id for c in criteria}
    asked = _asked_feedback(wb)
    accepted = accepted_refs(wb.ref.path)  # the findings a person accepted (L4-YOLO-028)
    satisfied = satisfied_refs(wb.provider.tasks(wb.ref), events, _task_text(wb))  # already satisfied (L4-VER-018)
    done = _done_tasks(wb, satisfied)
    answers = _family_answers(wb, events)  # L4-VER-065
    listing = "\n\n".join(f"{c.id}  {c.alias}\n{c.text}" for c in criteria)
    family = _family_sources(wb)
    plan = plan_context(  # the spec text has a budget of its own; the criteria, the done tasks and the answers first
        fixed_chars=len(listing) + sum(len(t.text) + len(t.task) for t in done)
        + len(render_answers(answers, wb.redactor.redact_text).text),
        budget_tokens=wb.cfg.verifier.judge_context_budget_tokens, conventions=(), source_files=family,
        keys=None,
    )  # fmt: skip

    def judge_body() -> tuple[bool, str]:
        parts = judge_parts(wb.git, base_sha, result.head_sha, _unit_dirs(wb))
        result.holds.extend(_judge_view_holds(parts))
        if plan.cuts:  # L4-KSP-014: a cut or unread spec file is named to the judge, held, and on the ledger
            result.holds.extend(_spec_holds(plan.cuts))
            wb.emit(
                "prompt.truncated", role="judge", round=vc.round,
                budget_tokens=wb.cfg.verifier.judge_context_budget_tokens, sources=[c.as_dict() for c in plan.cuts],
            )  # fmt: skip
        many = len(parts.parts) > 1
        listing, more = part_listing(parts)
        result.judge_files = [list(row) for row in file_rows(parts)]
        blobs = blob_ids(wb.git, result.head_sha, _covered(parts))
        views = _hold_views(parts, lambda path: blobs.get(path, "missing"))
        views |= _spec_hold_views(plan.cuts, family)
        result.hold_views |= {hold: {"sha": v.sha, "paths": list(v.paths)} for hold, v in views.items()}
        shown = parts.parts or (DiffPart(1, (), cut=False),)  # an empty diff is one prompt with no files

        def prompt_for(**over: Any) -> JudgePrompt:
            args: dict[str, Any] = {
                "unit_id": wb.ref.id, "sources": [(b.path, b.body()) for b in plan.sources], "criteria": criteria,
                "diff_truncated": False, "notes_for_verifier": _notes(events),
                "gate_report": _gate_summary(
                    result, cap=wb.cfg.verifier.max_criteria_per_test, unit_size=len(criteria)
                ),
                "redact": wb.redactor.redact_text, "conventions": test_conventions(wb.git, base_sha, wb.cfg),
                "owner_changes": [(f.path, f.human) for f in run.scope.files if f.human] if run.scope else [],
                "named_changes": _named_changes(wb, base_sha, result.head_sha, events),
                "repaired_changes": _repaired_changes(wb, result.head_sha, events),
                "round_outputs": _round_outputs(wb, result), "feedback": asked, "accepted": accepted,
                "satisfied": satisfied, "tasks": done, "unread": plan.cuts, "answers": answers,
            }  # fmt: skip
            return build_judge_prompt(**{**args, **over})

        prompts = [
            prompt_for(
                diff=part.text, diff_truncated=part.cut,
                part=PartView(part.index, len(shown), listing, more) if many else None,
            )
            for part in shown
        ]  # fmt: skip
        hashes = [p.sha256 for p in prompts]
        result.prompt_sha256 = hashes[0] if not many else hashlib.sha256("\n".join(hashes).encode()).hexdigest()
        result.prompt_template = prompts[0].version
        replies: list[JudgeVerdict] = []
        outcomes: list[str] = []
        for part, prompt in zip(shown, prompts, strict=True):
            at = (part.index, len(shown)) if many else None
            judged = _ask_judges(vc, prompt, result, part=at)
            if judged.status == "error":
                raise RoleUnavailable("judges", f"profile {vc.judge_profile} cannot answer: {judged.detail}")
            if judged.verdict is None:
                where = f"part {part.index} of {len(shown)}, " if many else ""
                result.holds.append(f"the judge's reply was discarded ({where}{judged.status}: {judged.detail})")
                return False, f"{judged.status}: {judged.detail}"
            replies.append(judged.verdict)
            outcomes.append(judged.reply)
            if many:
                result.judge_parts.append(
                    {"part": part.index, "files": len(part.entries), "chars": len(part.text), "reserve": parts.reserve,
                     "profile": vc.judge_profile, "calls": judged.calls, "reply": judged.reply,
                     "prompt_sha256": prompt.sha256}
                )  # fmt: skip
        verdict = merge_part_verdicts(replies)
        if many:  # L4-VER-057: a criterion the parts split is judged once more, on all of its files
            worst = next((w for w in ("discarded", "retried", "repaired", "valid") if w in outcomes), "")
            verdict = _follow_ups(
                vc, run, criteria=criteria, events=events, base_sha=base_sha, parts=parts, replies=replies,
                merged=verdict, prompt_for=prompt_for, hashes=hashes,
            )  # fmt: skip
            result.judge_reply = worst  # the worst reply of the parts is the round's
            result.prompt_sha256 = hashlib.sha256("\n".join(hashes).encode()).hexdigest()
        run.judged = verdict
        result.judge_verdict = verdict.model_dump(mode="json")
        verdicts = pick_verdicts(verdict)
        for c in criteria:
            _counterexample(wb, result, c.id, verdicts.get(c.id))
        unknown = sorted(set(verdicts) - ids)
        if unknown:
            title = "the judge cited criteria the unit does not have"
            result.findings.append(Finding(Severity.MINOR, title, ", ".join(unknown[:5]), "judge"))
        result.findings.extend(judge_findings(verdict, known=ids))
        reviewed = [(a.test, a.criterion, a.adequate) for a in verdict.test_adequacy]
        result.trace = apply_adequacy(result.trace, reviewed)
        result.trace = count_named(result.trace, *named_tests(verdict), cap=wb.cfg.verifier.max_criteria_per_test)
        result.findings.extend(inadequate_findings(result.trace))
        if asked:
            _judge_feedback(vc, result, asked, verdict, base_sha)
        for item in accepted:  # evidence only: the harness's merge guard reads these (L4-YOLO-028)
            answer = next((a for a in verdict.accepted or [] if a.id == item.id), None)
            wb.emit(
                "review.accepted_judged", id=item.id, round=vc.round, addressed=answer.addressed if answer else False,
                evidence=answer.evidence if answer else "not answered", profile=vc.judge_profile,
            )  # fmt: skip
        for ref in satisfied:  # L4-VER-018: a task ticked without a change of its own is checked against its text
            said = next((a for a in verdict.satisfied or [] if a.task == ref.task), None)
            holds, evidence = (said.holds, said.evidence) if said else (False, "not answered")
            wb.emit(
                "verify.satisfied_judged", task=ref.task, round=vc.round, holds=holds, evidence=evidence,
                profile=vc.judge_profile,
            )  # fmt: skip
            if said is None:
                title = f"the judge did not say whether task {ref.task} is done"
                result.findings.append(Finding(Severity.MINOR, title, "", "judge"))
            elif not said.holds:
                title = f"task {ref.task} is ticked as already satisfied, but its text is not done"
                result.findings.append(Finding(Severity.MAJOR, title, said.evidence, "judge"))
        return True, f"{result.judge_calls} call(s)"

    _step(vc, run, "9", "judge", judge_body)


def _follow_ups(
    vc: VerifyContext, run: _Run, *, criteria: Sequence[Criterion], events: Sequence[LedgerEvent], base_sha: str,
    parts: DiffParts, replies: Sequence[JudgeVerdict], merged: JudgeVerdict, prompt_for: Callable[..., JudgePrompt],
    hashes: list[str],
) -> JudgeVerdict:  # fmt: skip
    """L4-VER-056, L4-VER-057: after the parts' replies are merged, each criterion whose evidence the parts split is
    judged once more, in a follow-up call that shows its files together. The merged verdict with the follow-ups'
    answers applied; the records (`judge_followups`, `judge_split`) are set on the result. A follow-up that gives no
    usable answer keeps the parts' verdict: no hold, no discarded reply, no stop of the round."""
    wb, result = vc.wb, run.result
    reviewed = [(a.test, a.criterion, a.adequate) for a in merged.test_adequacy]
    trace = apply_adequacy(result.trace, reviewed)  # a copy: the round's own adequacy is applied after the follow-ups
    decided = set(effective_verdicts(events, {c.id: text_sha256(c) for c in criteria}))
    proofs = proof_tasks(events)
    evidence = {e.criterion: e for e in trace}
    dirs = _unit_dirs(wb)
    changed: dict[str, frozenset[str]] | None = None

    def files_of(cid: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
        nonlocal changed
        if changed is None:  # one `git log` for every task a candidate names
            units = {u.id for u in family_units(wb.provider, wb.ref)}
            changed = task_files(wb.git, base_sha, result.head_sha, units, {t for ts in proofs.values() for t in ts})
        return criterion_files(
            cid, replies=replies, evidence=evidence.get(cid), parts=parts, tasks=proofs.get(cid, ()),
            task_files=changed, unit_dirs=dirs, cfg=wb.cfg, unit_size=len(criteria),
        )  # fmt: skip

    def counts(path: str) -> bool:  # D2: a task's file counts toward the split only as code or a test (not a lock file)
        return all(file_kind(path, unit, wb.cfg) in ("code", "test") for unit in dirs or [""])

    splits = find_splits(
        [c for c in criteria if c.id not in decided], merged, trace, parts, files_of, counts,
        unit_size=len(criteria), cap=wb.cfg.verifier.max_criteria_per_test,
    )  # fmt: skip
    if not splits:
        return merged
    groups, records = plan_followups(splits, parts)
    own = (result.judge_profile, result.judge_model, result.independence, vc.independence)
    chain = (vc.judge, vc.judge_profile, vc.seat)  # a follow-up that falls back to the next judge changes these
    answered: list[tuple[tuple[str, ...], JudgeVerdict, frozenset[str]]] = []
    by_criterion = {s.criterion: s for s in splits}
    limited = False  # after a usage limit the other groups are not asked: their criteria keep the parts' verdict
    for group in groups:
        ids = group.criteria
        rows, more = followup_rows(parts, group)
        view = FollowUpView(group.index, len(groups), len(parts.parts), group.parts, rows, more)
        text = "".join(e.text for e in group.entries)
        judged: JudgeRun | None = None
        status = "limit"
        digest = ""  # a prompt that was not sent is not hashed
        if not limited:
            prompt = prompt_for(
                criteria=[c for c in criteria if c.id in ids], diff=text, followup=view, feedback=(), accepted=(),
                satisfied=(), tasks=(),
            )  # fmt: skip
            hashes.append(digest := prompt.sha256)
            try:
                judged = _ask_judges(vc, prompt, result, followup=(group.index, len(groups), ids))
                status = judged.status
            except (RoleLimit, RoleUnavailable) as exc:  # no next judge: the parts' verdict stands
                # a usage limit with no judge left is `limit` (it is a `WaitingCapacity` from the chain); any other
                # reason a judge is missing is `unavailable`
                limited = isinstance(exc, RoleLimit | WaitingCapacity)
                status = "limit" if limited else "unavailable"
        reply = judged.verdict if judged is not None else None
        shown_paths = {e.paths[-1] for e in group.entries}
        if reply is not None:
            answered.append((ids, reply, frozenset(shown_paths)))
        said = pick_verdicts(reply) if reply is not None else {}
        for cid in ids:
            split = by_criterion[cid]
            if reply is None:
                outcome, word = "no_answer", None
            else:
                outcome, word = ("answered", said[cid].verdict) if cid in said else ("not_answered", None)
            records[cid] = {
                "parts": list(split.parts), "outcome": outcome, "followup": group.index,
                "files": sum(1 for f in split.files if f in shown_paths),
                "not_shown": [list(x) for x in group.not_shown if x[0] in split.files], "answer": word,
                "status": status if outcome == "no_answer" else None,
            }  # fmt: skip
        result.judge_followups.append(
            {"followup": group.index, "criteria": list(ids), "parts": list(group.parts), "files": len(group.entries),
             "chars": len(text), "not_shown": [list(x) for x in group.not_shown], "profile": vc.judge_profile,
             "calls": judged.calls if judged is not None else 0, "reply": judged.reply if judged is not None else "",
             "status": status, "prompt_sha256": digest}
        )  # fmt: skip
    result.judge_split = {s.criterion: records[s.criterion] for s in splits}
    result.judge_profile, result.judge_model, result.independence, vc.independence = own  # the parts' judge stays
    vc.judge, vc.judge_profile, vc.seat = chain
    result.judge_replies = reply_counts(_events(wb), result.judge_profile)  # the parts' judge's, not a fallback's
    every = frozenset(e.paths[-1] for p in parts.parts for e in p.entries) | set(parts.unseen)
    return apply_followups(merged, [(ids, r) for ids, r, _ in answered], [paths for _, _, paths in answered], every)


def _view_holds(parts: DiffParts) -> list[tuple[str, tuple[str, ...]]]:
    """Each hold on the judge's view (L4-VER-043) with every file it covers: a file cut to one part, and the files in no
    part judged (all of them: the text names five). No character count of the diff is in a text, so a small change of
    size does not make a new hold."""
    holds = [
        (
            f"judge view: the diff of `{part.entries[0].paths[-1]}` is longer than one part "
            f"({diffparts.MAX_PART_CHARS} characters): the judge saw only its start",
            (part.entries[0].paths[-1],),
        )
        for part in parts.parts
        if part.cut
    ]
    if parts.unseen:
        named = ", ".join(f"`{path}`" for path in parts.unseen[:MAX_HOLD_PATHS])
        more = f" (+{len(parts.unseen) - MAX_HOLD_PATHS} more)" if len(parts.unseen) > MAX_HOLD_PATHS else ""
        holds.append(
            (
                f"judge view: the diff needs more than {diffparts.MAX_JUDGE_PARTS} parts of "
                f"{diffparts.MAX_PART_CHARS} characters: the judge did not see {named}{more}",
                tuple(parts.unseen),
            )
        )
    return holds


def _judge_view_holds(parts: DiffParts) -> list[str]:
    return [text for text, _ in _view_holds(parts)]


def _covered(parts: DiffParts) -> list[str]:
    return [path for _, paths in _view_holds(parts) for path in paths]


def _hold_views(parts: DiffParts, blob_of: Callable[[str], str]) -> dict[str, HoldView]:
    """The content a person's accept of each hold is bound to: the head blob of every file the hold covers and the full
    list of unseen files (review M1). The hold's id stays the hash of its text."""
    views = {}
    for text, paths in _view_holds(parts):
        covered = "\n".join(f"{path}\t{blob_of(path)}" for path in paths)
        views[text] = HoldView(hashlib.sha256(f"{text}\0{covered}".encode()).hexdigest(), paths)
    return views


def _task_text(wb: Workbench) -> Callable[[Task], str]:
    """A task's whole text as `tasks.md` at head holds it (its checkbox line and the lines under it, L4-VER-018): the
    title alone is the first line, and a task's instruction often goes on below it."""
    return _task_text_of(wb.ref.path, wb.ref.framework)


def _task_text_of(unit_dir: Path, framework: Framework) -> Callable[[Task], str]:
    try:
        data = read_regular_file(unit_dir / "tasks.md", limit=MAX_TASKS_BYTES)
    except (OSError, UnsafeFile):
        data = b""

    def text(task: Task) -> str:
        try:
            return task_text(data, task, framework) if data else task.title
        except ValueError:  # the line moved: the title is still the task's own words
            return task.title

    return text


def _judge_feedback(
    vc: VerifyContext, result: VerifyResult, asked: Sequence[FeedbackRef], verdict: JudgeVerdict, base_sha: str
) -> None:
    """L4-FBK-007: the judge's answers and the variable check decide each item. A not-addressed item is a blocking
    finding that carries it (the round fails into the next feedback fix unit); both outcomes are recorded with the
    round, and `apply_addressed` writes the Status and the Outcome once the round's evidence is committed. A yes is
    only evidence (`feedback.judged`) until a PASS round confirms it (`record_addressed`)."""
    wb = vc.wb
    texts: list[str] | None = None

    def has_name(name: str) -> bool:
        nonlocal texts
        if texts is None:
            texts = _changed_code(wb, base_sha, result.head_sha)
        return any(contains_name(name, text) for text in texts)

    outcomes = decide_feedback(asked, [verdict.feedback or []], has_name)
    result.feedback_outcomes = outcomes
    result.findings.extend(not_addressed_findings(outcomes, asked))
    for outcome in outcomes:
        if outcome.addressed:  # evidence for this round; `feedback.addressed` waits for a PASS round (review #14)
            wb.emit("feedback.judged", id=outcome.id, round=vc.round, evidence=outcome.evidence)
        else:
            wb.emit("feedback.not_addressed", id=outcome.id, round=vc.round, evidence=outcome.evidence)


def _round_outputs(wb: Workbench, result: VerifyResult) -> list[RoundOutput]:
    """The accepted audit tests of this round: in the worktree, committed after the judge has answered
    (`evidence.commit_verifier_tests`). They passed the audit gate run that accepted them."""
    found = []
    for record in result.audit:
        target = wb.worktree / record.test_path
        if record.status != "accepted" or not record.test_path or target.is_symlink() or not target.is_file():
            continue
        text = target.read_text(encoding="utf-8", errors="replace")
        found.append(RoundOutput(record.test_path, tuple((t, "passed") for t in record.tests), text))
    return found


def _ask_judges(
    vc: VerifyContext, prompt: JudgePrompt, result: VerifyResult, *, part: tuple[int, int] | None = None,
    followup: tuple[int, int, Sequence[str]] | None = None,
) -> JudgeRun:  # fmt: skip
    """One judge, then the next independent one for as long as the answer is a usage limit, comes from another
    model than the profile names (SCN-AVL-15) or from a served model whose vendor is not independent of the
    implementers (L4-VER-001; an unknown vendor never is): that verdict is dropped and never counted. The calls and
    the cost of every judge asked add up; the profile that gave the final answer is the one the report names."""
    wb = vc.wb
    while True:
        try:
            judged = run_judge(
                vc.judge, prompt, timeout_s=vc.judge_timeout_s, redact=wb.redactor.redact_text,
                expect_model=vc.seat.expect_model,
            )  # fmt: skip
        except RoleLimit as exc:
            limit = exc.result.limit
            if limit is not None:
                wb.emit("availability.limit", tool=limit.tool, kind=limit.kind, source=limit.source,
                        excerpt=limit.raw_excerpt)  # fmt: skip
            if vc.next_judge is None:
                raise
            vc.judge, vc.judge_profile = vc.next_judge("limit", exc.result)
            continue
        if judged.status == "ok" and vc.seat.reports_served and judged.model_resolved:
            served = assess_independence(
                wb.cfg, vc.implementer_profiles, vc.judge_profile, served_model=judged.model_resolved, routed=vc.routed
            )  # fmt: skip
            if not served.independent:  # L4-VER-001: the vendor of the model actually served is the one that counts
                judged.status, judged.verdict = "model_mismatch", None
                judged.detail = f"served {judged.model_resolved}: vendor {served.judge.vendor} is not independent"
        result.judge_model, result.judge_calls = judged.model_resolved, result.judge_calls + judged.calls
        if judged.cost_usd is not None:
            result.cost_usd = (result.cost_usd or 0.0) + judged.cost_usd
        wb.emit(
            "verify.judge", round=vc.round, profile=vc.judge_profile, status=judged.status, calls=judged.calls,
            model=judged.model_resolved, prompt_sha256=prompt.sha256, template=prompt.version, reply=judged.reply,
            answers=[list(a) for a in prompt.answers],
            **({"credits": round(judged.credits, 6)} if judged.credits is not None else {}),
            **({"part": part[0], "parts": part[1]} if part else {}),
            **({"followup": followup[0], "followups": followup[1], "criteria": list(followup[2])} if followup else {}),
        )  # fmt: skip
        if judged.repaired:  # a weak judge's trivial schema breaks, fixed by `judge_repair`; never a verdict
            wb.emit("judge.reply_repaired", round=vc.round, profile=vc.judge_profile, fields=list(judged.repaired))
        if judged.cost_usd:
            wb.emit("budget.cost", usd=judged.cost_usd, profile=vc.judge_profile, role="judge")
        if judged.credits:  # plan credits, never dollars (kiro-judge L4-KJD-004)
            wb.emit("budget.cost", credits=round(judged.credits, 6), credits_source=judged.credits_source,
                    profile=vc.judge_profile, role="judge")  # fmt: skip
        if judged.status not in ("model_mismatch", "error"):
            break
        if judged.status == "model_mismatch":
            wb.emit(
                "availability.model_mismatch", role="judges", profile=vc.judge_profile,
                requested=vc.seat.expect_model, served=judged.model_resolved,
            )  # fmt: skip
        else:  # a judge that cannot answer (a rejected tool call, an upstream 5xx) must not strand the unit
            wb.emit("availability.judge_error", role="judges", profile=vc.judge_profile, detail=judged.detail[:200])
        if vc.next_judge is None:
            break
        vc.judge, vc.judge_profile = vc.next_judge(judged.status, None)
    result.judge_profile = vc.judge_profile
    result.judge_reply = judged.reply
    result.judge_replies = reply_counts(_events(wb), vc.judge_profile)
    served = judged.model_resolved if vc.seat.reports_served and judged.status == "ok" else None
    vc.independence = result.independence = assess_independence(
        wb.cfg, vc.implementer_profiles, vc.judge_profile, served_model=served, routed=vc.routed
    )  # fmt: skip
    return judged


def _counterexample(wb: Workbench, result: VerifyResult, cid: str, verdict: CriterionVerdict | None) -> None:
    """A judge `fail` is never counted without evidence, and in M0 a counterexample is never executed: it is
    model-written code and SPEC 10.2 step 9 runs it on a scratch copy of head, not the unit worktree.
    # M1: verifier 1.5 (the verifier worktree), then run it there"""
    if verdict is None or verdict.verdict != "fail":
        return
    note = "the judge gave no counterexample" if verdict.counterexample is None else UNEXECUTED_NOTE
    run = CounterexampleRun("unexecuted", note)
    result.cx_runs[cid] = run
    wb.emit("verify.counterexample", criterion=cid, status=run.status, note=run.note)


def _commit_evidence(wb: Workbench, paths: Sequence[Path], round_no: int) -> None:
    root = wb.worktree.resolve()
    wb.git.run("add", "--", *(p.resolve().relative_to(root).as_posix() for p in paths))
    if wb.git.run("diff", "--cached", "--quiet", check=False).returncode == 0:
        return
    trailers = CommitTrailers(unit=wb.ref.id, run_id=wb.run_id, iteration=max(wb.iteration, 1), phase="verifying")
    wb.git.commit(clip_subject(f"docs({wb.ref.name}): verification round {round_no} [skip ci]"), trailers)


class _NoJudge:
    """The judge of a resumed round: step 9 is not run again, so a call is a bug."""

    def complete_structured(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("a resumed round makes no judge call")


def _resumable(services: Services, family: FamilyProvider, criteria: Sequence[Criterion], round_no: int) -> bool:
    """Whether `verify_unit` will resume at aggregation, decided before a judge is selected (and probed)."""
    if round_no <= 1 or (head := services.git.rev_parse("HEAD")) is None:
        return False
    root = services.worktree.resolve()
    subject = subject_sha(services.git, head, [u.path.resolve().relative_to(root).as_posix() for u in family.units()])
    return reusable(read_verdict(services.ref.path, round_no - 1), subject, [c.id for c in criteria])


def _ask_verdicts(
    ctx: HookContext, wb: Workbench, result: VerifyResult, criteria: Sequence[Criterion], round_no: int
) -> list[Path]:
    """NEEDS_HUMAN: one verdict question per criterion and judge-only finding that needs a human (L4-VER-013). The
    file joins the evidence commit, and the sticky section reaches the orchestrator through `ctx.shared["notes"]`."""
    services = ctx.services
    path = services.ref.path / QUESTIONS_FILENAME
    events = read_ledger(services.ref.path).events
    consumed = fold(events, services.ref.id).verdicts_consumed
    raise_verdict_questions(
        services.ref.path, services.ref.name, outcomes=result.criteria, criteria=criteria, trace=result.trace,
        findings=result.findings, existing=QuestionsFile.load(path), consumed=consumed, ledger=services.ledger,
        round_no=round_no, redactor=services.app.redactor, holds=result.holds, covers=hold_covers(events),
        hold_views=result.hold_views, judges=round_judges(events, round_no, wb.cfg),
        generated=result.generated,
    )  # fmt: skip
    if (section := verdict_section(ctx, consumed)) is not None:
        ctx.shared["notes"] = (section,)
    return [path] if path.exists() else []


def _supersede_verdicts(ctx: HookContext, result: VerifyResult, round_no: int) -> list[Path]:
    """The round ended with any verdict: the verdict questions of an earlier round that nobody answered are replaced
    by this round (L4-OPS-014). A NEEDS_HUMAN round keeps the ones it asks again. The file joins the evidence commit."""
    services = ctx.services
    path = services.ref.path / QUESTIONS_FILENAME
    events = read_ledger(services.ref.path).events
    ask = (
        verdict_targets(result.criteria, result.findings, result.holds) if result.verdict is Verdict.NEEDS_HUMAN else ()
    )
    ids = supersede_stale_verdicts(
        services.ref.path, existing=QuestionsFile.load(path), consumed=fold(events, services.ref.id).verdicts_consumed,
        events=events, ledger=services.ledger, round_no=round_no, current=ask,
    )  # fmt: skip
    return [path] if ids else []


def verify_hook(ctx: HookContext) -> Trigger:
    """The orchestrator's `verify` hook (resolved as `l4.verifier.ladder:verify_hook`): one round, evidence committed
    and pushed, then the trigger of the verdict."""
    cfg, services = ctx.cfg, ctx.services
    base = bring_in_base(ctx)  # first: the merge is a new subject, so it comes before verdicts and the reuse decision
    family = family_of(ctx)  # the unit and its fix units are verified as one
    criteria = family.criteria(services.ref)
    calibration = cache_root(services.app.environ, repo=services.app.repo) / "s1-calibration.jsonl"
    before = read_ledger(services.ref.path).events
    unit_git = Git(services.ref.path)
    recorded = consume_verdicts(
        QuestionsFile.load(services.ref.path / QUESTIONS_FILENAME), before, services.ledger, criteria,
        actor_of=lambda question: answer_actor(unit_git, services.ref.path, question, before),
    )  # fmt: skip
    # a human's verdict on a hold is ground truth: written at once, since the answer is consumed only once and the
    # round can still end before a judge is found (exit 12)
    record_human_labels(
        services.ref.path, recorded, [calibration, services.app.out_dir / "s1" / f"{services.app.run_id}.jsonl"]
    )
    state = fold(read_ledger(services.ref.path).events, services.ref.id)
    implementers = list(state.profiles_used.get("implementer") or cfg.roles.implementer)
    judges = [name for name in cfg.roles.judges if cfg.profiles[name].adapter in JUDGE_ADAPTERS]
    if not judges:  # preflight: a chain exists
        raise L4Exit(ExitCode.USAGE_ERROR, f"roles.judges: no profile of {', '.join(cfg.roles.judges)} can judge")
    round_no = (state.last_verdict.round if state.last_verdict else 0) + 1
    resume = _resumable(services, family, criteria, round_no)
    skip: set[str] = set()  # judges whose verdict was dropped in this round
    if resume:  # step 9 stands from the last round: no probe, no judge
        selected = Selected(judges[0], cfg.profiles[judges[0]], services.factory.build(cfg.profiles[judges[0]]))
    else:
        selected = select_judge(services.factory, cfg, services.ref.id, implementers, skip=skip)
    logs: list[tuple[Path, Path]] = []
    # L4-SEC-039: the round builds the project environment from caches of its own, emptied here, that no implementer
    # step or gate has touched; every workbench of the round (a judge that took over included) shares them
    round_caches = verifier_caches(
        cfg.sandbox.caches, cache_root(services.app.environ, repo=services.app.repo), services.ref.id,
        services.names.repo_key,
    )  # fmt: skip

    def bench(chosen: Selected) -> Workbench:
        return make_workbench(
            cfg=cfg, app=services.app, ref=services.ref, provider=family, worktree=services.worktree,
            git=services.git, ledger=services.ledger, sandbox=services.sandbox, selected=chosen,
            iteration=state.iteration, push=ctx.push, caches=round_caches,
        )  # fmt: skip

    def backend(chosen: Selected, judge_wb: Workbench) -> AgentJudge:
        stem = f"verify-judge-r{round_no}"
        return AgentJudge(
            chosen.impl,
            workbench_request_factory(judge_wb, chosen.profile, stem=stem, logs=logs, publish_prompts=True),
            events=services.ledger,
            role="judge",
            profile=chosen.profile_name,
        )

    wb = bench(selected)
    current = selected

    def next_judge(reason: str, limited: RunResult | None) -> tuple[LLMBackend, str]:
        """The next independent judge: after a limit the factory cools the profile and walks on, after a mismatch
        the profile is skipped. The new judge sees its own login only (a workbench built for it)."""
        nonlocal current
        try:
            if limited is not None:
                current = services.factory.on_limit(current, limited)
                if probe_vetoes(cfg, implementers, services.factory, current):  # D14: its own probe contradicts it
                    skip.add(current.profile_name)
                    current = select_judge(services.factory, cfg, services.ref.id, implementers, skip=skip)
                current.vendor, current.provenance = resolve_vendor(current.profile)
            else:
                skip.add(current.profile_name)
                if reason == "model_mismatch":  # also for the next round: it would pay for another discarded answer
                    services.factory.cool_down(current, "model_mismatch", "the served model is not the configured one")
                current = select_judge(services.factory, cfg, services.ref.id, implementers, skip=skip)
        except WaitingCapacity as exc:
            raise no_independent_verifier("judges", exc) from None
        log.warning("%s: judge %s: next independent judge is %s", services.ref.id, reason, current.profile_name)
        vc.seat = seat_of(current)
        return backend(current, bench(current)), current.profile_name

    def writer_for(stem: str) -> Callable[[], LLMBackend]:
        """The `verifier_agent` role, selected when it is needed (the audit sample is drawn, a UI criterion is a gap):
        the first usable profile of the chain that is independent of the implementers (C1); none is
        `WaitingCapacity` (`no independent verifier`)."""

        def open_writer() -> LLMBackend:
            writer = select_judge(services.factory, cfg, services.ref.id, implementers, role="verifier_agent")
            by_writer = dataclasses.replace(wb, selected=writer)
            return AgentJudge(
                writer.impl,
                workbench_request_factory(
                    by_writer, writer.profile, stem=f"{stem}-r{round_no}", logs=logs, publish_prompts=True
                ),
                events=services.ledger,
                role="verifier_agent",
                profile=writer.profile_name,
            )

        return open_writer

    def s1_backend() -> SystemOneBackend:
        return open_s1_backend(
            cfg, "s1_judge", services.ledger, environ=services.app.environ, redactor=services.app.redactor,
            log_path=services.app.repo / cfg.observability.log_dir / "system-one.jsonl",
        )  # fmt: skip

    s1 = S1Wiring(s1_backend, calibration)

    vc = VerifyContext(
        wb, _NoJudge() if resume else backend(selected, wb), selected.profile_name, implementers, round_no,
        JUDGE_TIMEOUT_S, seat=seat_of(selected), next_judge=None if resume else next_judge,
        audit_writer=writer_for("verify-audit") if cfg.roles.verifier_agent else None,
        ui_writer=writer_for("verify-ui") if cfg.roles.verifier_agent else None,
        s1=s1 if cfg.verifier.s1.enabled and has_system_one_profile(cfg) else None,
        shadow=ShadowWiring(s1.cache_file, services.app.repo / cfg.observability.log_dir / "system-one.jsonl",
                            dict(services.app.environ)) if cfg.verifier.s1.enabled and cfg.verifier.s1.shadow else None,
        base_note=base.note, routed=services.factory.routed,
    )  # fmt: skip
    try:
        result = verify_unit(vc)
    finally:
        for raw, published in logs:
            wb.publish_agent_logs(raw, published)
        wb.restore_ledger()
    decide_fix(ctx, wb, result)  # before the evidence is written, so that the report lists the fix unit
    record_addressed(services.ledger, result)  # a PASS round only, and before the report reads the round's events
    paths = write_round_evidence(services.ref.path, round_no, result, services.app.redactor)
    # Status and Outcome (L4-FBK-007), in the parent's file when the unit is a follow-up (L4-FBK-010)
    no_status: list[str] = []
    paths += apply_addressed(feedback_home(services.ref.path), result, services.app.redactor, skipped=no_status)
    if no_status:  # an item whose Status line is gone: recorded, never a crash (review #9)
        record_no_status(services.ledger, fold(_events(wb), wb.ref.id), no_status)
    if result.verdict is Verdict.NEEDS_HUMAN:
        paths += _ask_verdicts(ctx, wb, result, criteria, round_no)
    paths += [p for p in _supersede_verdicts(ctx, result, round_no) if p not in paths]
    commit_verifier_tests(wb, vc.verifier_tests, round_no)
    _commit_evidence(wb, paths, round_no)
    ctx.push()
    wb.emit(
        "verify.verdict", round=round_no, verdict=result.verdict.value, findings=len(result.findings),
        criteria_passed=sum(c.result == "pass" for c in result.criteria), criteria_total=len(result.criteria),
    )  # fmt: skip
    trigger = after_verdict(ctx, wb, result, TRIGGERS[result.verdict])
    curate_round(ctx, wb, result, trigger)  # the final PASS only; the `chore(memory)` commit comes before the hand-off
    return trigger


def run_verify(app: AppContext, *, unit: str, dry_run: bool = False) -> CommandResult:
    """`l4 verify --unit U`: the verifier alone, on a unit that is `implemented` or `verifying`. It is the normal run
    with the hand-off hook left out, so a PASS stops at `verified` (exit 0). It does not take a person's spec edit (that
    would run the implementer): the edit is recorded as `spec.edit_seen`, and the next `l4 run` takes it."""
    if dry_run:
        raise L4Exit(ExitCode.USAGE_ERROR, "verify: --dry-run not yet implemented (M1: verifier)")
    app, cfg = load_app_config(app)
    preflight_run_config(app, cfg)
    if not in_ci_job(app.environ) and (
        refusal := sandbox_refusal(cfg.sandbox, app.environ, app.repo, command="l4 verify")
    ):
        log.error("%s", app.redactor.redact_text(refusal))  # L4-SEC-041: exit 3 before the unit is read or leased
        return CommandResult(ExitCode.DOCTOR_FAILED)
    git = Git(app.repo, environ=app.environ)
    provider, ref = select_runnable(cfg, git, list(providers_for(cfg, app.repo, app.environ)), unit)
    snapshot = load_snapshot(provider, git, ref, branch_prefix=cfg.forge.branch_prefix)
    phase = snapshot.state.phase
    answered = phase == "awaiting_human" and next_action(facts_of(snapshot))[0] == "verify"  # verdicts are in
    if phase not in VERIFY_PHASES and not answered:
        raise L4Exit(
            ExitCode.USAGE_ERROR, f"verify: {unit} is {phase or 'new'}; only an implemented unit can be verified"
        )
    hooks = dataclasses.replace(load_hooks(), handoff=None, fix=None)
    result = run_unit_in_worktree(app, cfg, git, provider, ref, hooks=hooks, take_spec_edit=False)  # review L3
    return CommandResult(result.exit_code, [result.outcome])
