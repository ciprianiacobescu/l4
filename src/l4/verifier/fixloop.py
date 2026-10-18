"""Fix units inside their parent's run (M1.3 decision D1, lines 35 and 36).

A fix unit `<parent>-fix-<n>` is a change on the parent's branch, in the parent's worktree and ledger. It has no phase
of its own: the parent stays `fixing` while `fix_hook` runs the fix unit's tasks with `run_task` on a child workbench,
then goes back to `verifying`, and the verifier judges the parent and its fix units as one family (`FamilyProvider`).

The child workbench is the parent's with these differences: the reference is the fix unit, every event carries
`fix_unit`, the parent's directory is protected, the parent's run ledger is the one file of the run that steps leave
alone, and the cache mounts are the parent's (a cold uv cache per fix unit would cost minutes). The fix unit has its
own `questions.md`, and no clarifier: a human answers. A fix unit is an OpenSpec change or a Kiro bugfix spec.
"""

import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

from l4.clarifier.clarifier import sticky_location
from l4.clarifier.notify import build_sticky_section
from l4.clarifier.ports import QuestionView
from l4.config.defaults import cache_root
from l4.exitcodes import ExitCode, L4Exit
from l4.implementer.loop import run_task
from l4.implementer.tasks import open_blocking_questions, questions_hold, select_next_step, unselectable
from l4.implementer.tdd import BaselineFailed, PlantedLink, RoleLimit
from l4.implementer.workbench import PreviousAttempt, Workbench, clip_subject, make_workbench
from l4.sandbox.caches import mount_caches
from l4.services import HookContext
from l4.specs.base import (
    Criterion,
    FixUnitCapable,
    Framework,
    GateReport,
    Marker,
    OpenSpecCommandError,
    OpenSpecUnavailable,
    SpecDelta,
    SpecError,
    SpecProvider,
    Task,
    Unit,
    UnitRef,
    ValidationReport,
)
from l4.specs.base import (
    Finding as SpecFinding,
)
from l4.specs.criteria import kiro_criteria, openspec_criteria
from l4.specs.feedback import FeedbackFile, FeedbackStatus
from l4.specs.fixmark import read_fix_marker, split_fix_name
from l4.specs.followup import feedback_home, parent_folder, read_follow_up_marker
from l4.specs.questions import QUESTIONS_FILENAME, QuestionsFile, answer_sha256, answered_by, blocked_tasks, is_answered
from l4.state.budget import FEEDBACK_ROUNDS_EXHAUSTED, feedback_round_limit, feedback_rounds_left
from l4.state.fold import UnitState, fold
from l4.state.ledger import LedgerEvent, ledger_path, read_ledger
from l4.state.lifecycle import Trigger
from l4.state.next_step import JUDGE_VIEW_REJECTED, NO_CONVERTIBLE_FINDING, UNCONVERTED_AND_JUDGE_VIEW
from l4.vcs.authorship import commit_records, is_harness_strict
from l4.vcs.git import Git
from l4.vcs.trailers import CommitTrailers
from l4.verifier.feedback import record_no_status
from l4.verifier.fixunit import FixPlan, plan_fix_unit, redact_plan
from l4.verifier.notes import escalation_section
from l4.verifier.provenance import introduction_problem
from l4.verifier.report import write_round_evidence
from l4.verifier.types import Finding, FixDecision, Severity, Verdict, VerifyResult
from l4.verifier.verdicts import JUDGE_VIEW_REJECTED_TITLE


def is_fix_unit(ref: UnitRef) -> bool:
    """Whether the unit's folder carries the marker `create_fix_unit` writes (`.l4/fix.json`)."""
    return read_fix_marker(ref.path) is not None


Reject = Callable[[UnitRef, str], None]


def fix_units_of(
    provider: SpecProvider, parent: UnitRef, *, git: Git | None = None, on_reject: Reject | None = None
) -> list[UnitRef]:
    """The parent's fix units in the order they were spawned: `<parent>-fix-<n>` folders whose marker names it.
    With `git` (inside a run) the marker is also required to come from the harness: the commit that introduced it is
    the harness's `docs(<parent>): fix unit <n>` commit and it has not changed since. Anything else is left out and
    reported to `on_reject(unit, why)`. Without `git` (after a merge, where history is rewritten) the marker is all."""
    found = []
    for ref in provider.list_units():
        split = split_fix_name(ref.name)
        marker = read_fix_marker(ref.path) if split is not None and split[0] == parent.name else None
        if marker is None or marker.parent != parent.id:
            continue
        if git is not None:
            rel = ref.path.resolve().relative_to(git.repo.resolve()).as_posix()
            if (why := introduction_problem(git, rel, parent.name, marker.round)) is not None:
                if on_reject is not None:
                    on_reject(ref, why)
                continue
        found.append((marker.round, ref))
    return [ref for _, ref in sorted(found, key=lambda pair: (pair[0], pair[1].name))]


def without_fix_units(
    chosen: Sequence[tuple[SpecProvider, UnitRef]], *, named: Sequence[str]
) -> list[tuple[SpecProvider, UnitRef]]:
    """`l4 run` never selects a fix unit: it is the parent's to run (exit 2 when `--unit` names one). Left in the list
    they would be planned and verified as units of their own once they are on `main`."""
    fixes = [(p, r) for p, r in chosen if is_fix_unit(r)]
    for _, ref in fixes:
        if ref.id in named:
            marker = read_fix_marker(ref.path)
            parent = marker.parent if marker else "its parent"
            raise L4Exit(ExitCode.USAGE_ERROR, f"{ref.id} is a fix unit of {parent}: run the parent")
    return [pair for pair in chosen if pair not in fixes]


class FamilyProvider:
    """A parent and its fix units as one unit for the parts of the harness that read the whole: the criteria (a red
    test of a fix task may cite a criterion of the parent, and the verifier judges all of them), the tasks of the
    parent (every task of the family, for step 0) and the done-gate. Markers, validation and sources stay per unit:
    `tasks(<fix unit>)` is that unit's own list, so that `run_task` ticks the right box."""

    def __init__(
        self, inner: SpecProvider, parent: UnitRef, *, git: Git | None = None, on_reject: Reject | None = None
    ) -> None:
        """`git` makes the family trust only fix units that the harness committed (see `fix_units_of`); `on_reject`
        hears about each rejected folder once."""
        self.inner, self.parent = inner, parent
        self.framework: Framework = inner.framework
        self.git, self._on_reject = git, on_reject
        self._rejected: set[tuple[str, str]] = set()

    def _reject(self, unit: UnitRef, why: str) -> None:
        if self._on_reject is not None and (unit.name, why) not in self._rejected:
            self._rejected.add((unit.name, why))
            self._on_reject(unit, why)

    def units(self) -> list[UnitRef]:
        return [self.parent, *fix_units_of(self.inner, self.parent, git=self.git, on_reject=self._reject)]

    def list_units(self) -> list[UnitRef]:
        return self.inner.list_units()

    def unit_dir(self, unit: UnitRef) -> Path:
        return self.inner.unit_dir(unit)

    def tasks(self, unit: UnitRef) -> list[Task]:
        if unit != self.parent:
            return self.inner.tasks(unit)
        return [t for member in self.units() for t in self.inner.tasks(member)]

    def criteria(self, unit: UnitRef) -> list[Criterion]:
        """The family's criteria, each id once and in the order first met. A Kiro fix unit restates a criterion of its
        parent under its own number (`2.1` for `Req 1.2`, same id): the criterion keeps the reading of the unit asked
        for, so the parent's own reading for the parent, and for the fix unit the `Req 2.1` its tasks cite."""
        seen: dict[str, Criterion] = {}
        for member in self.units():
            for criterion in self.inner.criteria(member):
                if criterion.id not in seen or member == unit:
                    seen[criterion.id] = criterion
        if unit == self.parent:  # a follow-up keeps what its merged parent promised (L4-FBK-010)
            for criterion in self.merged_parent_criteria():
                seen.setdefault(criterion.id, criterion)
        return list(seen.values())

    def merged_parent_criteria(self) -> list[Criterion]:
        """The criteria of the merged unit this one follows, as they are in the follow-up's tree: a refactor must leave
        them true, and a follow-up of one refactor has no scenarios of its own. Empty for any other unit. The folder is
        the parent's own, which the follow-up may not edit (the protected-path check), so it stands for the base's."""
        marker = read_follow_up_marker(self.parent.path)
        folder = parent_folder(self.parent.path, marker) if marker is not None else None
        if folder is None:
            return []
        try:
            return kiro_criteria(folder) if self.framework is Framework.KIRO else openspec_criteria(folder)
        except SpecError:
            return []

    def load(self, unit: UnitRef) -> Unit:
        return Unit(unit, tuple(self.tasks(unit)), tuple(self.criteria(unit)))

    def set_marker(self, unit: UnitRef, task_key: str, marker: Marker) -> None:
        self.inner.set_marker(unit, task_key, marker)

    def validate(self, unit: UnitRef, strict: bool = True) -> ValidationReport:
        return self.inner.validate(unit, strict)

    def done_gate(self, unit: UnitRef) -> GateReport:
        """The provider's own gate per member (M1.4 changes what counts as done), and together for the family."""
        members = self.units() if unit == self.parent else [unit]
        reports = [(m, self.inner.done_gate(m)) for m in members]
        reasons = tuple(f"{m.name}: {r}" for m, report in reports for r in report.reasons)
        return GateReport(all(report.passed for _, report in reports), reasons)

    def own_tasks(self, unit: UnitRef) -> list[Task]:
        return self.inner.tasks(unit)

    @property
    def can_fix(self) -> bool:
        """The wrapper has `create_fix_unit` whatever `inner` is, so `isinstance(wrapper, FixUnitCapable)` is always
        true: consumers ask this, not `isinstance`."""
        return isinstance(self.inner, FixUnitCapable)

    def create_fix_unit(
        self, parent: UnitRef, round: int, findings: Sequence[SpecFinding], spec_delta: SpecDelta | None
    ) -> UnitRef:
        if not isinstance(self.inner, FixUnitCapable):
            raise SpecError(f"{type(self.inner).__name__} has no fix units")
        return self.inner.create_fix_unit(parent, round, findings, spec_delta)


def family_of(ctx: HookContext) -> FamilyProvider:
    """The run's family of the unit: fix units count only when the harness committed them; a folder that looks like
    one but is not is recorded (`guard.violation`, rule `foreign-fix-unit`) and ignored."""
    s = ctx.services
    root = s.worktree.resolve()

    def reject(unit: UnitRef, why: str) -> None:
        path = unit.path.resolve().relative_to(root).as_posix()
        s.ledger.append(
            "guard.violation", phase="verify", path=path, rule="foreign-fix-unit", action="ignored", reason=why
        )

    return FamilyProvider(s.provider, s.ref, git=s.git, on_reject=reject)


def family_units(provider: SpecProvider, ref: UnitRef) -> list[UnitRef]:
    """The unit and, for a `FamilyProvider`, its fix units; any other provider has just the unit."""
    return provider.units() if isinstance(provider, FamilyProvider) and ref == provider.parent else [ref]


def family_tasks(provider: SpecProvider, ref: UnitRef) -> list[tuple[UnitRef, Task]]:
    """(unit, task) over the family. Task keys repeat across units, so the pair is the identity of a task."""
    units = family_units(provider, ref)
    own = provider.own_tasks if isinstance(provider, FamilyProvider) else provider.tasks
    return [(u, t) for u in units for t in own(u)]


@dataclass(frozen=True)
class FixOutcome:
    """`done`: every task of the fix unit is ticked (`fix.done` is in the ledger). `blocked`: a task waits for a human
    answer in the fix unit's `questions.md` (exit 11, the parent stays `fixing`). `halt`: the loop cannot go on."""

    status: Literal["done", "blocked", "halt"]
    question_ids: tuple[str, ...] = ()
    reason: str = ""
    section: str | None = None  # the sticky-note section for the questions of a blocked fix unit
    code: str = ""  # a halt that names its own code (`planted_link`); else the orchestrator derives it from `reason`


def _halt(ctx: HookContext, reason: str, **event: object) -> FixOutcome:
    ctx.services.ledger.append("breaker.tripped", reason=reason[:200], **event)
    return FixOutcome("halt", reason=reason)


def _reenter(ctx: HookContext, fix: UnitRef) -> bool:
    """The human's answers in the fix unit's `questions.md` become `question.answered{by, fix_unit}` events, once per
    answer text. The parent's `Clarifier.reenter` reads the ledger of the directory it is given, and a fix unit has
    none, so the record is looked up in the parent's ledger by `fix_unit`."""
    s = ctx.services
    file = QuestionsFile.load(fix.path / QUESTIONS_FILENAME)
    if file is None:
        return False
    new = False
    recorded = {
        str(e.data["id"]): e.data.get("answer_sha256")
        for e in read_ledger(s.ref.path).events
        if e.type == "question.answered" and e.data.get("fix_unit") == fix.name and "id" in e.data
    }
    for question in file.questions:
        if not is_answered(question):
            continue
        digest = answer_sha256(question)
        if recorded.get(question.id) != digest:
            s.ledger.append(
                "question.answered", id=question.id, by=answered_by(question), answer_sha256=digest, fix_unit=fix.name
            )
            new = True
    return new


def _section(ctx: HookContext, fix: UnitRef, ids: Sequence[str]) -> str | None:
    file = QuestionsFile.load(fix.path / QUESTIONS_FILENAME)
    if file is None:
        return None
    s = ctx.services
    views = [QuestionView.of(q) for q in file.questions if q.id in ids]
    parent_path, branch, link = sticky_location(ctx)
    path = (fix.path.resolve().relative_to(s.worktree.resolve()) / QUESTIONS_FILENAME).as_posix()
    link = link.replace(parent_path, path) if link else None
    return build_sticky_section(views, path=path, branch=branch, link=link).replace(
        "### Waiting for you: a human answer", f"### Waiting for you: a human answer (fix unit `{fix.name}`)", 1
    )


def _child_workbench(ctx: HookContext, fix: UnitRef, iteration: int) -> Workbench:
    s = ctx.services
    current = ctx.shared.get("implementer")  # the orchestrator's `_select`: the profile in use after any fallback
    selected = current() if current is not None else s.factory.for_role("implementer", s.ref.id)
    root = s.worktree.resolve()
    parent_rel = s.ref.path.resolve().relative_to(root).as_posix()
    family = family_of(ctx)
    # the parent and every sibling fix unit are the harness's while this one runs; the running one is `unit_dir`
    others = tuple(u.path.resolve().relative_to(root).as_posix() for u in family.units() if u.name != fix.name)
    return make_workbench(
        cfg=ctx.cfg, app=s.app, ref=fix, provider=family, worktree=s.worktree, git=s.git,
        ledger=s.ledger, sandbox=s.sandbox, selected=selected, iteration=iteration, push=ctx.push,
        event_context={"fix_unit": fix.name}, extra_unit_dirs=others, family_glob=f"{parent_rel}-fix-*",
        caches=mount_caches(
            ctx.cfg.sandbox.caches, cache_root(s.app.environ, repo=s.app.repo), s.ref.id, s.names.repo_key
        ),
        ledger_rel=ledger_path(s.ref.path, s.app.run_id).resolve().relative_to(root).as_posix(),
    )  # fmt: skip


def _fall_back(ctx: HookContext, wb: Workbench, fix: UnitRef, exc: RoleLimit, task: str, iteration: int) -> Workbench:
    """Contract C21: a limit in a fix task goes through the orchestrator (`ctx.shared["fall_back"]`, its
    `switch_profile`), which cools the profile down and selects the next one of the chain, so the run's profiles,
    `L4-Fallback-From` and every later `ctx.shared["implementer"]()` follow it; nothing left raises `WaitingCapacity`
    (the unit parks, exit 12). What the limited step left is discarded; the rebuilt workbench keeps the baselines and
    tells the next profile what happened, as the orchestrator's own fallback does."""
    if (limit := exc.result.limit) is not None:
        wb.emit("availability.limit", tool=limit.tool, kind=limit.kind, source=limit.source, excerpt=limit.raw_excerpt)
    wb.discard_changes()
    previous = wb.selected.profile_name
    ctx.shared["fall_back"](exc.result, task)
    fresh = _child_workbench(ctx, fix, iteration)
    fresh.baselines, fresh.static_baselines = wb.baselines, wb.static_baselines
    fresh.previous_attempt = PreviousAttempt(previous, limit.kind if limit is not None else exc.result.status, task)
    return fresh


def fix_hook(ctx: HookContext) -> FixOutcome:
    """Run the tasks of the open fix unit (the last `fix.spawned` without a `fix.done`) until every one is ticked, one
    is blocked on a question, or one halts. A `RoleLimit` from a task moves it to the next implementer profile once
    (contract C21, `_fall_back`); a second limit on the same task, or an empty chain, parks the unit (exit 12)."""
    s = ctx.services
    state = fold(read_ledger(s.ref.path).events, s.ref.id)
    name = state.open_fix_unit
    if name is None:
        return _halt(ctx, f"{s.ref.id} is fixing but no fix unit is open")
    fix = next((r for r in family_of(ctx).units()[1:] if r.name == name), None)  # harness-committed ones only
    marker = read_fix_marker(fix.path) if fix is not None else None
    if fix is None or marker is None or marker.parent != s.ref.id:
        return _halt(ctx, f"the fix unit {name} is not a fix unit of {s.ref.id}", fix_unit=name)
    wb = _child_workbench(ctx, fix, state.iteration)
    retried: set[str] = set()  # tasks already moved to another profile after a limit
    while True:
        if _reenter(ctx, fix) and "answers_recorded" in ctx.shared:
            ctx.shared["answers_recorded"]()  # the mirror drops `l4:needs-answers` before the chore's agent runs
        tasks = wb.provider.tasks(fix)
        file = QuestionsFile.load(fix.path / QUESTIONS_FILENAME)
        pending = [t.key for t in tasks if not t.done]
        blocked = blocked_tasks(file.questions, pending, file.unreadable_ids) if file else frozenset()
        task = select_next_step(tasks, blocked)
        if task is None:
            if stuck := unselectable(tasks):
                why = f"task {stuck[0].key} of {name} cannot be selected: its checkbox is not an empty `[ ]`"
                return _halt(ctx, why, fix_unit=name, task=stuck[0].key)
            if questions_hold(tasks, blocked):
                ids = tuple(open_blocking_questions(file, tasks))
                return FixOutcome("blocked", ids, section=_section(ctx, fix, ids))
            s.ledger.append("fix.done", fix_unit=name, round=marker.round, findings=list(marker.findings))
            return FixOutcome("done")
        try:
            outcome = run_task(wb, task)
        except BaselineFailed as exc:
            return _halt(ctx, str(exc), fix_unit=name)
        except PlantedLink as exc:
            links = [{"path": u.link, "points_to": u.target, "where": u.where} for u in exc.links][:20]
            ctx.services.ledger.append(
                "breaker.tripped", reason="planted_link", fix_unit=name, task=task.key, links=links
            )  # fmt: skip
            return FixOutcome("halt", reason=f"task {task.key} of {name}: {exc}", code="planted_link")
        except RoleLimit as exc:
            if task.key in retried or "fall_back" not in ctx.shared:
                raise
            retried.add(task.key)
            wb = _fall_back(ctx, wb, fix, exc, task.key, state.iteration)
            continue
        if outcome.status == "blocked":
            ids = tuple(outcome.question_ids)
            return FixOutcome("blocked", ids, section=_section(ctx, fix, ids))
        if outcome.status == "halt":
            return FixOutcome("halt", reason=outcome.reason)


# --- after the verdict (line 37) --------------------------------------------------------------------------------------


def _used_rounds(provider: FamilyProvider, state: UnitState) -> int:
    """The fix units that count against `verifier.max_fix_rounds`: feedback fix units do not (L4-FBK-006). A fix unit
    on disk that the ledger does not know is counted as a fix round."""
    return max(state.fix_rounds_counted, len(provider.units()) - 1 - state.feedback_rounds_used)


def _next_ordinal(provider: FamilyProvider, state: UnitState) -> int:
    """`<parent>-fix-<n>`: n runs over fix units of every kind."""
    return max(state.fix_round, len(provider.units()) - 1) + 1


def adopt_orphans(ctx: HookContext, provider: FamilyProvider) -> None:
    """A fix unit that is committed on the branch but has no `fix.spawned` (the run died between the commit and the
    event) is recorded now, so that the fold knows its round and that it is open. Its marker is all that is left of the
    plan: the verdict questions it consumed are not recorded (`consumed` stays empty)."""
    s = ctx.services
    spawned = {e.data.get("fix_unit") for e in read_ledger(s.ref.path).events if e.type == "fix.spawned"}
    root = s.worktree.resolve()
    for fix in fix_units_of(provider.inner, provider.parent, git=s.git, on_reject=provider._reject):
        marker = read_fix_marker(fix.path)
        tracked = s.git.run("ls-files", "--error-unmatch", "--", (fix.path.resolve() / ".l4" / "fix.json")
                            .relative_to(root).as_posix(), check=False).returncode == 0  # fmt: skip
        if fix.name not in spawned and marker is not None and tracked:
            s.ledger.append(
                "fix.spawned", parent=s.ref.id, fix_unit=fix.name, round=marker.round, verify_round=None,
                findings=list(marker.findings), consumed=[], adopted=True,
            )  # fmt: skip


def _unfinished_fix(ctx: HookContext, provider: FamilyProvider) -> UnitRef | None:
    """The open fix unit when a task of it is not ticked: a FAIL has to run it, not plan another one beside it."""
    s = ctx.services
    name = fold(read_ledger(s.ref.path).events, s.ref.id).open_fix_unit
    fix = next((u for u in provider.units()[1:] if u.name == name), None)
    return fix if fix is not None and any(not t.done for t in provider.own_tasks(fix)) else None


# --- a failure that repeats (L4-OPS-007) --------------------------------------------------------------------------

FIX_ROUNDS_EXHAUSTED, NO_FIX_UNITS = "fix_rounds_exhausted", "no_fix_units"
FIX_UNIT_NOT_CREATED, SAME_FAILURE = "fix_unit_not_created", "same_failure"  # `ctx.shared["escalation"]` codes (D5)
# a feedback-only spawn: `consumed` names the human rejects its round could not convert (L4-VER-016)
_FEEDBACK_ONLY = {"feedback_only": True, "lists_unconverted": True}
MAX_SAME_DETAIL = 200  # characters of the failure set in the `same_failure` detail
TEST_GATES = ("test", "e2e")
_BLOCKING = (Severity.BLOCKER.value, Severity.MAJOR.value)
_EXIT = re.compile(r"exit code (-?\d+)")
_RETRY_EVENTS = ("unit.retried", "unit.resumed")  # a person's decision to try again: the next round is judged anew


def failure_set(
    gates: Iterable[Mapping[str, object]], tests: Mapping[str, str], findings: Iterable[Mapping[str, object]] = ()
) -> frozenset[str]:
    """What a FAIL round failed on (D7): the name of each failed gate, the failing test ids of a failed test gate, and
    for a failed gate with no failing test the exit code (`<gate>:exit <code>`, else the head of its reason) and the
    digest of its last error lines (`<gate>:log <digest>`, review M5: two lint errors are two failures, the same crash
    twice is one). The id of each blocking finding of source `deterministic` (an integrity or ladder blocker: its id
    comes from its title and criterion, so it is the same in every round) is in it as `finding <id>`: a round that
    fails on such a finding alone, every gate passing, still has a set. Judge, human and feedback findings are not
    part of it: their wording changes between rounds. `gates` and `findings` are the `verdict.json` rows."""
    failing = sorted(i for i, status in tests.items() if status in ("failed", "error"))
    found: set[str] = set()
    for row in gates:
        if row.get("status") != "fail":
            continue
        name = str(row.get("name") or "")
        found.add(name)
        if name in TEST_GATES and failing:
            found.update(failing)
            continue
        reason = str(row.get("reason") or "")
        code = _EXIT.search(reason)
        found.add(f"{name}:exit {code.group(1)}" if code else f"{name}:{reason.split(';', 1)[0].strip()[:80]}")
        if digest := row.get("digest"):
            found.add(f"{name}:log {digest}")
    for row in findings:
        if row.get("source") == "deterministic" and row.get("severity") in _BLOCKING and row.get("id"):
            found.add(f"finding {row['id']}")
    return frozenset(found)


def _previous_round(unit_dir: Path, round_no: int) -> tuple[int, dict[str, object]] | None:
    """The newest stored round before `round_no` and its `verdict.json`; None when there is none or it is unreadable."""
    evidence = unit_dir / ".l4" / "evidence"
    rounds = sorted(
        (
            int(p.name.removeprefix("round-"))
            for p in evidence.glob("round-*")
            if p.name.removeprefix("round-").isdigit()
        ),
        reverse=True,
    )
    for n in rounds:
        if n < round_no:
            try:
                data = json.loads((evidence / f"round-{n}" / "verdict.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return None
            return (n, data) if isinstance(data, dict) else None
    return None


def repeated_failure(unit_dir: Path, git: Git, events: Sequence[LedgerEvent], result: VerifyResult) -> str | None:
    """The `same_failure` detail when `result` (a FAIL round) failed the way the round before it did, else None. The
    set must not be empty. Not a repeat when the previous round did not FAIL, when its head is unknown, when a commit
    of a person lies between that head and now (the person changed something), or when a retry was recorded after the
    previous round's verdict (the person chose to try once more)."""
    found = _previous_round(unit_dir, result.round)
    if found is None:
        return None
    before, data = found
    gates, tests, earlier = data.get("gates"), data.get("tests"), data.get("findings") or []
    if data.get("verdict") != Verdict.FAIL.value or not isinstance(gates, list) or not isinstance(tests, dict):
        return None
    now_findings = ({**asdict(f), "severity": f.severity.value} for f in result.findings)
    now = failure_set((asdict(g) for g in result.gates), result.tests, now_findings)
    before_set = failure_set(
        (g for g in gates if isinstance(g, dict)), tests, (f for f in earlier if isinstance(f, dict))
    )
    if not now or now != before_set:
        return None
    head = str(data.get("head_sha") or "")
    if not head or git.run("cat-file", "-e", f"{head}^{{commit}}", check=False).returncode != 0:
        return None
    if any(not is_harness_strict(r) for r in commit_records(git, "--first-parent", f"{head}..HEAD")):
        return None
    last = max(
        (i for i, e in enumerate(events) if e.type == "verify.verdict" and e.data.get("round") == before), default=-1
    )
    if any(e.type in _RETRY_EVENTS for e in events[last + 1 :]):
        return None
    listed = ", ".join(sorted(now))[:MAX_SAME_DETAIL]
    return f"round {result.round} failed the same way as round {before}: {listed}"


def _no_task_cause(findings: Sequence[Finding]) -> tuple[str, str]:
    """Why a failed round with no fix group escalates: a person rejected a hold on the judge's view of the diff (a fix
    unit cannot shrink it, L4-VER-044), or no finding can be converted (L4-OPS-022), or both: each way out is named."""
    view = any(f.title == JUDGE_VIEW_REJECTED_TITLE for f in findings)
    others = any(f.source == "human" and f.blocking and f.title != JUDGE_VIEW_REJECTED_TITLE for f in findings)
    if view and others:
        return (
            "a person rejected a hold on the judge's view of the diff (a fix unit cannot shrink the diff), and "
            "another finding of a person cannot be converted into a fix task",
            UNCONVERTED_AND_JUDGE_VIEW,
        )
    if view:
        return (
            "a person rejected a hold on the judge's view of the diff: a fix unit cannot shrink the diff",
            JUDGE_VIEW_REJECTED,
        )
    return "no finding of this round can be converted into a fix task", NO_CONVERTIBLE_FINDING


def decide_fix(ctx: HookContext, wb: Workbench, result: VerifyResult) -> None:
    """Sets `result.fix` (L4-VER-006, L4-VER-007), before the evidence is written. FAIL with rounds left: a fix unit.
    FAIL without: `escalated`. PASS with `verifier.fix_minor_findings`: a fix unit for the convertible minors while
    rounds are left, else they are listed as not converted. A NEEDS_HUMAN verdict has no fix decision."""
    provider = wb.provider
    if result.verdict is Verdict.NEEDS_HUMAN or not isinstance(provider, FamilyProvider):
        return
    s, cfg = ctx.services, ctx.cfg.verifier
    adopt_orphans(ctx, provider)
    if result.verdict is Verdict.FAIL and (open_fix := _unfinished_fix(ctx, provider)) is not None:
        marker = read_fix_marker(open_fix.path)
        titles = [t.title for t in provider.own_tasks(open_fix) if not t.done]
        result.fix = FixDecision("spawn", marker.round if marker else 0, titles, [])  # no plan: it exists already
        return
    events = read_ledger(s.ref.path).events
    state = fold(events, s.ref.id)
    used = _used_rounds(provider, state)
    ordinal = _next_ordinal(provider, state)
    limit = cfg.max_fix_rounds + state.fix_rounds_extra  # a member's extension (`l4 resume`, the label), L4-IMP-013
    plan = plan_fix_unit(
        provider.criteria(wb.ref), result, result.human, ordinal=ordinal, fix_minor=cfg.fix_minor_findings
    )
    tasks = [f"{', '.join(g.ids)} {g.title}" for g in plan.groups]
    listed = list(plan.not_converted)
    if result.verdict is Verdict.FAIL:
        if not provider.can_fix:
            why, code = f"{wb.ref.framework.value} has no fix units", NO_FIX_UNITS
        elif plan.feedback_only:  # its own limit, not `max_fix_rounds` (L4-FBK-006)
            if feedback_rounds_left(ctx.cfg, state) > 0:
                result.fix = FixDecision("spawn", ordinal, tasks, listed, plan=plan)
            else:
                note = f"feedback round limit reached ({feedback_round_limit(ctx.cfg, state)})"
                result.fix = FixDecision("escalate", ordinal - 1, [], listed, note, code=FEEDBACK_ROUNDS_EXHAUSTED)
            return
        elif (same := repeated_failure(wb.ref.path, wb.git, events, result)) is not None:  # L4-OPS-007
            why, code = same, SAME_FAILURE
        elif used >= limit:
            why, code = f"fix rounds used {used}/{limit}", FIX_ROUNDS_EXHAUSTED
        elif not plan.groups:
            why, code = _no_task_cause(result.findings)
        else:
            result.fix = FixDecision("spawn", ordinal, tasks, listed, plan=plan)
            return
        result.fix = FixDecision("escalate", used, [], listed, why, code=code)
        return
    if not plan.groups:
        result.fix = FixDecision("none", used, [], listed) if listed else None
    elif not provider.can_fix or used >= limit:
        why = f"fix rounds used {used}/{limit}"
        if not provider.can_fix:
            why = f"{wb.ref.framework.value} has no fix units"
        result.fix = FixDecision("none", used, [], [*listed, *(f"{', '.join(g.ids)}: {why}" for g in plan.groups)])
    else:
        result.fix = FixDecision("spawn", ordinal, tasks, listed, plan=plan)


def _mark_taken(
    wb: Workbench, plan: FixPlan, fix_unit: str, round_: int, *, skipped: list[str] | None = None
) -> list[str]:
    """Status `taken` and the Outcome line `Taken in round N into <fix unit>` in the parent's `feedback.md`, so that
    the one fix-unit commit carries them (L4-FBK-004). Returns the repository-relative paths written. An item with no
    Status line is skipped (its id goes to `skipped`): this write never raises."""
    file = FeedbackFile.load(feedback_home(wb.ref.path))  # a follow-up's items are its parent's (L4-FBK-010)
    if file is None or not plan.taken:
        return []
    for ref in plan.taken:
        if (item := file.get(ref.id)) is not None and item.status_value is None:
            if skipped is not None:
                skipped.append(ref.id)
        elif item is not None:
            file = file.set_status(ref.id, FeedbackStatus.TAKEN).set_outcome(
                ref.id, f"Taken in round {round_} into {fix_unit}", redactor=wb.redactor
            )
    file.save()
    assert file.path is not None
    return [file.path.resolve().relative_to(wb.worktree.resolve()).as_posix()]


def _drop_fix_unit(ctx: HookContext, wb: Workbench, result: VerifyResult, fix: FixDecision, reason: str) -> None:
    """The optional fix unit of a PASS could not be created: the minors are listed as not converted, and the evidence
    that already said "Fix unit n is created" is written again and committed."""
    result.fix = FixDecision("none", fix.ordinal - 1, [], [*fix.not_converted, reason])
    paths = write_round_evidence(wb.ref.path, result.round, result, wb.redactor)
    root = wb.worktree.resolve()
    wb.git.run("add", "--", *(p.resolve().relative_to(root).as_posix() for p in paths))
    trailers = CommitTrailers(unit=wb.ref.id, run_id=wb.run_id, iteration=max(wb.iteration, 1), phase="verifying")
    wb.git.commit(clip_subject(f"docs({wb.ref.name}): verification round {result.round} amended [skip ci]"), trailers)
    ctx.push()


def after_verdict(ctx: HookContext, wb: Workbench, result: VerifyResult, trigger: Trigger) -> Trigger:
    """Called once at the end of `verify_hook`, after the evidence commit: executes `result.fix`. A fix unit is written
    (and validated: an invalid one is removed and raises), committed as `docs(<unit>): fix unit <n> [skip ci]` with
    `L4-Phase: verifying`, pushed, and only then recorded as `fix.spawned`. Returns the trigger of the verdict, or
    `VERIFY_FAIL_EXHAUSTED` when the rounds are used up (the sticky note carries the verdict summary)."""
    fix = result.fix
    if fix is None or fix.action == "none":
        return trigger
    if fix.action == "escalate":
        ctx.shared["notes"] = (escalation_section(result, fix.reason, wb.redactor.redact_text),)
        if fix.code:  # the edge's reason, which resume and the label read (`halt_reason`)
            ctx.shared["escalation"] = (fix.code, fix.reason)
        return Trigger.VERIFY_FAIL_EXHAUSTED
    if fix.plan is None:  # the fix unit already exists: `fix_hook` runs it
        return trigger
    plan: FixPlan = redact_plan(fix.plan, wb.redactor.redact_text)
    provider = wb.provider
    assert isinstance(provider, FamilyProvider)
    try:
        ref = provider.create_fix_unit(wb.ref, fix.ordinal, plan.groups, plan.delta)
    except SpecError as e:
        reason = f"the fix unit could not be created: {e}"
        if result.verdict is Verdict.PASS:  # the minor-finding fix unit is optional: a verified unit stays verified
            _drop_fix_unit(ctx, wb, result, fix, reason)
            return trigger
        if isinstance(e, OpenSpecUnavailable | OpenSpecCommandError):
            raise  # transient (exit 1 / 3): the unit stays `verifying` and the run can be repeated
        # a deterministic failure: the same plan fails the same way next round, and each round costs a judge call
        result.fix = FixDecision(
            "escalate", fix.ordinal - 1, [], list(fix.not_converted), reason, code=FIX_UNIT_NOT_CREATED
        )
        ctx.shared["notes"] = (escalation_section(result, reason, wb.redactor.redact_text),)
        ctx.shared["escalation"] = (FIX_UNIT_NOT_CREATED, reason)
        return Trigger.VERIFY_FAIL_EXHAUSTED
    rel = ref.path.resolve().relative_to(wb.worktree.resolve()).as_posix()
    no_status: list[str] = []
    written = _mark_taken(wb, plan, ref.name, result.round, skipped=no_status)
    wb.git.run("add", "--", rel, *written)
    trailers = CommitTrailers(unit=wb.ref.id, run_id=wb.run_id, iteration=max(wb.iteration, 1), phase="verifying")
    wb.git.commit(clip_subject(f"docs({wb.ref.name}): fix unit {fix.ordinal} [skip ci]"), trailers)
    ctx.push()
    ledger = ctx.services.ledger
    ledger.append(
        "fix.spawned", parent=wb.ref.id, fix_unit=ref.name, round=fix.ordinal, verify_round=result.round,
        findings=plan.finding_ids, consumed=plan.consumed, **(_FEEDBACK_ONLY if plan.feedback_only else {}),
    )  # fmt: skip
    for item in plan.taken:
        ledger.append(
            "feedback.taken", id=item.id, kind=item.kind, sha256=item.sha256, round=result.round, fix_unit=ref.name
        )
    if plan.waiting:  # still takeable: the next round takes them
        ledger.append("feedback.waiting", ids=plan.waiting, reason="fix_unit_full")
    if no_status:  # after the takes, so that the problem is the item's last word (review #9)
        record_no_status(ledger, fold(read_ledger(wb.ref.path).events, wb.ref.id), no_status)
    return trigger
