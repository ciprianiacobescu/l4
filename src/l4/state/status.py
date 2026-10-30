"""`l4 status` and the unit snapshot `l4 plan` shares (SPEC 2.1, L4-STA-004).

The unit's ledger, tasks and questions are read from `origin/<branch_prefix><fw>/<name>` when that remote-tracking
ref exists (M0 gap G4: a default-branch checkout has no ledger, the unit branch has it), else from the working tree.
Only the local ref is read. Inside GitLab CI the refs are refreshed first (`l4.vcs.refresh`, G8); a local run has no
side effects and a stale ref gives a stale answer.
The pending ledger of the unit's lock ref (L4-STA-004) is folded over either source: it holds what the run wrote
after the hand-off commit. M1: state-vcs-locks 1.19 `--rebuild`, state.json, `state_drift`.
"""

import json
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, Literal

import click

from l4.agents.activity import ago
from l4.ci.detect import in_ci_job
from l4.ci.relay import early_pin_stop
from l4.config.redaction import load_app_config
from l4.config.schema import L4Config
from l4.context import AppContext
from l4.exitcodes import ExitCode, L4Exit
from l4.forge.base import STATUS_FETCH_TIMEOUT_S, fetch_auth_config
from l4.forge.urls import ForgeUrls, app_forge_urls, origin_url
from l4.fsutil import UnsafeFile, read_regular_file
from l4.implementer.tasks import required
from l4.implementer.unit_context import NOT_READ, budget_advice, safe_label
from l4.specs.base import Framework, SpecProvider, Task, UnitRef, UnknownUnit, parse_unit_id
from l4.specs.feedback import FEEDBACK_FILENAME, MAX_FEEDBACK_BYTES, FeedbackFile
from l4.specs.fixmark import read_fix_marker
from l4.specs.followup import MARKER_PATH, MAX_MARKER_BYTES, parse_follow_up_marker, read_follow_up_marker
from l4.specs.kiro import kiro_tasks
from l4.specs.markers import MAX_TASKS_BYTES
from l4.specs.openspec import parse_openspec_tasks
from l4.specs.providers import providers_for
from l4.specs.questions import MAX_QUESTIONS_BYTES, QUESTIONS_FILENAME, QuestionsFile, QuestionStatus
from l4.state.feedback_view import counts, item_views
from l4.state.fold import UnitState, fold, recorded_ready
from l4.state.followups import (
    FollowUpOffer,
    archive_folders,
    base_ref,
    follow_ups_of,
    known_follow_ups,
    offer_for,
    read_feedback_at,
    taken_by_follow_ups,
)
from l4.state.ledger import (
    MAX_LEDGER_FILE_BYTES,
    TS_FORMAT,
    LedgerCorrupt,
    LedgerEvent,
    LedgerRead,
    parse_ledger_files,
    read_ledger_files,
)
from l4.state.lifecycle import SPEC_EDIT_PHASES, Phase
from l4.state.next_step import label_for, next_step, reason
from l4.state.parks import FixPark, fix_parks
from l4.state.pending import merge_ledgers, read_pending
from l4.state.review import AfterHandoff, SpecEdit, after_handoff, spec_edit_since_harness
from l4.vcs.errors import GitError
from l4.vcs.git import Git
from l4.vcs.names import lock_ref, unit_branch
from l4.vcs.push import is_permission_failure
from l4.vcs.refresh import refresh_remote_refs
from l4.vcs.tree import regular_blobs

if TYPE_CHECKING:
    from l4.delegate.hint import HintReader
    from l4.planner import UnitFacts

REMOTE = "origin"
TASK_PARSERS: dict[Framework, Callable[[bytes], list[Task]]] = {
    Framework.OPENSPEC: parse_openspec_tasks,
    Framework.KIRO: kiro_tasks,
}
STOPPED = (Phase.HALTED.value, Phase.ESCALATED.value)
CORRUPT_PHASE = "corrupt"  # a status value, not a lifecycle phase: the unit's ledger could not be read
log = logging.getLogger("l4.status")


@dataclass(frozen=True)
class ChildSnapshot:
    """A fix unit of the unit, as its tasks and questions are on the unit branch (fix units have no branch of their
    own)."""

    name: str
    tasks: list[Task]
    questions: QuestionsFile | None = None

    @property
    def tasks_done(self) -> int:
        return sum(t.done for t in self.tasks)


@dataclass(frozen=True)
class Activity:
    """The newest ledger event of a unit (L4-OPS-020)."""

    ts: str
    type: str
    task: str | None
    run_id: str | None


@dataclass(frozen=True)
class OpenRun:
    """A `run.started` of `l4 run` with no `run.finished` for the same run."""

    run_id: str
    started: str
    ci_url: str | None
    job_timeout_s: int | None = None  # `run.started{job_timeout_s}`: the job's timeout in seconds (L4-IMP-073)


@dataclass(frozen=True)
class UnitSnapshot:
    ref: UnitRef
    state: UnitState
    tasks: list[Task]
    source: Literal["branch", "worktree", "archive"]
    corrupt: str | None = None  # "<file>:<line> ..." when the ledger could not be read; the phase is then "corrupt"
    questions: QuestionsFile | None = None  # `questions.md` from the same source as the tasks and the ledger
    children: tuple[ChildSnapshot, ...] = ()  # the fix units the ledger names, from the same source
    fix_of: str | None = None  # the parent's unit id when this unit is itself a fix unit (`.l4/fix.json`)
    review: AfterHandoff | None = None  # an `in_review` unit read from its branch: what happened after H (M1.9)
    feedback: FeedbackFile | None = None  # `feedback.md` from the same source as the tasks and the ledger
    follow_up_of: str | None = None  # the parent's unit id when this unit is a follow-up (`.l4/followup.json`)
    follow_up: FollowUpOffer | None = None  # a `merged` unit: the items a follow-up should take (L4-FBK-010)
    stopped_in: str | None = None  # a halted or escalated unit: the run whose edge stopped it (L4-OPS-006)
    spec_edit: SpecEdit | None = None  # a person's spec push after the harness's last commit (L4-OPS-014)
    last_activity: Activity | None = None  # the newest ledger event (L4-OPS-020)
    open_run: OpenRun | None = None  # a run that started and has no end recorded (L4-OPS-020)
    events: tuple[LedgerEvent, ...] = ()  # the ledger events read (for `status --events`)
    fix_parks: tuple[FixPark, ...] = ()  # the trailing parks only a fix ends, no work between them (L4-YOLO-035)
    prompt_cut: dict[str, Any] | None = None  # the data of the last implementer `prompt.truncated` (L4-IMP-054)
    # the questions the delegate has still to decide, (key, time it may be asked again), set only for a unit in its
    # scope while the base branch enables it (`l4.delegate.due.stamp_due`); empty otherwise
    delegate_due: tuple[tuple[str, str | None], ...] = ()

    @property
    def feedback_counts(self) -> dict[str, int]:
        """Items per state (D12), from the file and the fold; empty when the unit has no item."""
        return counts(item_views(self.feedback, self.state))

    @property
    def tasks_done(self) -> int:
        return sum(t.done for t in required(self.tasks))

    @property
    def tasks_total(self) -> int:
        return len(required(self.tasks))


def _relative(provider: SpecProvider, ref: UnitRef, git: Git) -> str:
    return provider.unit_dir(ref).resolve().relative_to(git.repo.resolve()).as_posix()


def _read_branch(
    git: Git, tracking_ref: str, unit_rel: str, *, parse_tasks: Callable[[bytes], list[Task]] = parse_openspec_tasks
) -> tuple[dict[str, bytes], list[Task], QuestionsFile | None]:
    """Raw blob bytes only: text-mode git would turn CRLF into LF and invalid UTF-8 into U+FFFD, so the parse
    would no longer be OpenSpec's (L4-OSP-004). Sizes are capped like the working-tree reads."""
    ledger = regular_blobs(git, tracking_ref, f"{unit_rel}/.l4/ledger/", MAX_LEDGER_FILE_BYTES)
    files = {
        blob.path.rsplit("/", 1)[-1]: git.run_bytes("cat-file", "blob", blob.oid)
        for blob in ledger
        if blob.path.endswith(".jsonl")
    }
    tasks_blob = regular_blobs(git, tracking_ref, f"{unit_rel}/tasks.md", MAX_TASKS_BYTES)
    tasks = parse_tasks(git.run_bytes("cat-file", "blob", tasks_blob[0].oid)) if tasks_blob else []
    questions_blob = regular_blobs(git, tracking_ref, f"{unit_rel}/{QUESTIONS_FILENAME}", MAX_QUESTIONS_BYTES)
    questions = None
    if questions_blob:
        questions = QuestionsFile.parse(git.run_bytes("cat-file", "blob", questions_blob[0].oid))
    return files, tasks, questions


def _read_feedback(git: Git, tracking_ref: str, unit_rel: str) -> FeedbackFile | None:
    blob = regular_blobs(git, tracking_ref, f"{unit_rel}/{FEEDBACK_FILENAME}", MAX_FEEDBACK_BYTES)
    return FeedbackFile.parse(git.run_bytes("cat-file", "blob", blob[0].oid)) if blob else None


def _check_unit(read: LedgerRead, unit_id: str) -> None:
    for event in read.events:
        if event.unit != unit_id:
            raise LedgerCorrupt(f"{event.run_id}.jsonl:{event.seq} is an event of {event.unit}, not of {unit_id}")


def load_snapshot(provider: SpecProvider, git: Git, ref: UnitRef, *, branch_prefix: str) -> UnitSnapshot:
    """One unit's snapshot. A corrupt ledger makes only this unit `corrupt`: a single bad branch must not take
    the router down for every other unit."""
    tracking_ref = f"refs/remotes/{REMOTE}/{unit_branch(ref.id, branch_prefix)}"
    on_branch = git.rev_parse(tracking_ref) is not None
    source: Literal["branch", "worktree"] = "branch" if on_branch else "worktree"
    try:
        if on_branch:
            files, tasks, questions = _read_branch(
                git, tracking_ref, _relative(provider, ref, git), parse_tasks=TASK_PARSERS[ref.framework]
            )
            feedback = _read_feedback(git, tracking_ref, _relative(provider, ref, git))
        else:
            files, tasks = read_ledger_files(provider.unit_dir(ref)), provider.tasks(ref)
            questions = QuestionsFile.load(provider.unit_dir(ref) / QUESTIONS_FILENAME)
            feedback = FeedbackFile.load(provider.unit_dir(ref))
        pending = read_pending(git, lock_ref(ref.id))
        read = merge_ledgers(parse_ledger_files(files), pending)  # the tail after H (5.5)
        _check_unit(read, ref.id)
    except LedgerCorrupt as exc:
        detail = str(exc).removeprefix("ledger corrupt: ")
        log.warning("%s: ledger corrupt: %s", ref.id, detail)
        return UnitSnapshot(ref, UnitState(unit=ref.id, phase=CORRUPT_PHASE), [], source, corrupt=detail)
    for name in read.torn:
        log.warning("%s: last line of %s was cut off mid-write and is ignored", ref.id, name)
    state = fold(read.events, ref.id)
    state.ready_head, state.ready_at = recorded_ready(pending.events)  # H comes from the lock ref only (L4-ARC-008)
    last, open_run = _activity(read.events)
    children = child_snapshots(provider, git, ref, state.children, tracking_ref if on_branch else None)
    marker = read_fix_marker(provider.unit_dir(ref))
    follow = _read_follow_up_marker(git, tracking_ref, _relative(provider, ref, git)) if on_branch else None
    if not on_branch and (found := read_follow_up_marker(provider.unit_dir(ref))) is not None:
        follow = found.parent
    review = None
    if on_branch and state.phase == Phase.IN_REVIEW.value:
        review = after_handoff(git, tracking_ref, ref.name, _relative(provider, ref, git), recorded=state.ready_head)
    edit = None
    if on_branch and state.phase in {p.value for p in SPEC_EDIT_PHASES}:
        edit = spec_edit_since_harness(git, tracking_ref, _relative(provider, ref, git))
    return UnitSnapshot(
        ref,
        state,
        tasks,
        source,
        questions=questions,
        children=children,
        fix_of=marker.parent if marker else None,
        review=review,
        feedback=feedback,
        follow_up_of=follow,
        stopped_in=_stopped_in(read.events, state),
        spec_edit=edit,
        last_activity=last,
        open_run=open_run,
        events=tuple(read.events),
        fix_parks=fix_parks(read.events),
        prompt_cut=_prompt_cut(read.events),
    )


def _prompt_cut(events: Sequence[LedgerEvent]) -> dict[str, Any] | None:
    """The cut of the LATEST implementer prompt (L4-IMP-054): a later `prompt.rendered` that has no `prompt.truncated`
    after it cut nothing and clears it. The judge's `prompt.truncated` is not an implementer prompt. The cut carries the
    `budget_source` of its prompt, so that the advice names the key that really set the budget."""
    cut: dict[str, Any] | None = None
    source = "implementer"
    for e in events:
        if e.type == "prompt.rendered":
            cut, source = None, str(e.data.get("budget_source") or "implementer")
        elif e.type == "prompt.truncated" and e.data.get("role") != "judge":
            cut = {"budget_source": source, **e.data}
    return cut


MAX_CUT_FILES = 3


def _cut_text(cut: dict[str, Any]) -> str:
    """`path shown of total characters` for a budget cut, `path not read (symlink)` and the like for the others."""
    path, reason = safe_label(str(cut.get("path", "?"))), cut.get("reason", "budget")
    if reason in NOT_READ:
        return f"{path} not read ({reason})"
    if reason == "oversize":
        return f"{path} {cut.get('total_bytes', '?')} bytes, the first part read"
    return f"{path} {cut.get('shown_chars', 0)} of {cut.get('total_chars', 0)} characters"


def _prompt_cut_line(cut: dict[str, Any]) -> str:
    sources = [s for s in cut.get("sources", []) if isinstance(s, dict)]
    shown = [_cut_text(s) for s in sources[:MAX_CUT_FILES]]
    more = [f"and {len(sources) - MAX_CUT_FILES} more"] if len(sources) > MAX_CUT_FILES else []
    what = ", ".join([*shown, *more])
    task = f"task {safe_label(str(cut['task']))} " if cut.get("task") else ""
    return (
        f"Prompt cut: {task}{cut.get('role', '?')} attempt {cut.get('attempt', '?')}: {what} "
        f"({budget_advice(str(cut.get('budget_source', 'implementer')))})"
    )


def _activity(events: Sequence[LedgerEvent]) -> tuple[Activity | None, OpenRun | None]:
    """The newest event (the last read on a tie) and the newest `run.started` of `l4 run` with no `run.finished` of
    the same run (L4-OPS-020, D7)."""
    newest: LedgerEvent | None = None
    started: LedgerEvent | None = None
    finished = {e.run_id for e in events if e.type == "run.finished"}
    for e in events:
        if newest is None or e.ts >= newest.ts:
            newest = e
        if e.type == "run.started" and e.data.get("command") == "run" and (started is None or e.ts >= started.ts):
            started = e
    task = newest.data.get("task") if newest else None
    last = Activity(newest.ts.strftime(TS_FORMAT), newest.type, task or None, newest.run_id) if newest else None
    url = started.data.get("ci_url") if started else None
    timeout = started.data.get("job_timeout_s") if started else None
    open_run = (
        OpenRun(
            started.run_id, started.ts.strftime(TS_FORMAT), url if isinstance(url, str) and url else None,
            timeout if isinstance(timeout, int) and not isinstance(timeout, bool) and timeout > 0 else None,
        )
        if started and started.run_id not in finished
        else None
    )  # fmt: skip
    return last, open_run


def _stopped_in(events: Sequence[LedgerEvent], state: UnitState) -> str | None:
    """The run id of the last edge into `halted` or `escalated`, while the unit is still stopped."""
    if state.phase not in STOPPED:
        return None
    edges = [e for e in events if e.type == "phase.changed" and e.data.get("to") in STOPPED]
    return edges[-1].run_id if edges else None


def _read_follow_up_marker(git: Git, tracking_ref: str, unit_rel: str) -> str | None:
    blob = regular_blobs(git, tracking_ref, "/".join((unit_rel, *MARKER_PATH)), MAX_MARKER_BYTES)
    marker = parse_follow_up_marker(git.run_bytes("cat-file", "blob", blob[0].oid)) if blob else None
    return marker.parent if marker else None


def child_snapshots(
    provider: SpecProvider, git: Git, ref: UnitRef, names: list[str], tracking_ref: str | None
) -> tuple[ChildSnapshot, ...]:
    """The tasks and questions of each fix unit the ledger names: from `tracking_ref` when the unit has a branch, else
    from the working tree. A fix unit that is not there (a branch not yet pushed, a bad ledger) is left out."""
    found = []
    for name in names:
        try:
            child = UnitRef(ref.framework, name, ref.path.parent / name)
        except ValueError:
            continue
        if tracking_ref is not None:
            rel = (PurePosixPath(_relative(provider, ref, git)).parent / name).as_posix()
            _, tasks, questions = _read_branch(git, tracking_ref, rel)
        else:
            tasks = provider.tasks(child)
            questions = QuestionsFile.load(provider.unit_dir(child) / QUESTIONS_FILENAME)
        if tasks:
            found.append(ChildSnapshot(name, tasks, questions))
    return tuple(found)


def select_units(providers: list[SpecProvider], wanted: tuple[str, ...]) -> list[tuple[SpecProvider, UnitRef]]:
    """Every unit of every provider, or only the `--unit` ids (an unknown one is a usage error)."""
    found = [(p, ref) for p in providers for ref in p.list_units()]
    if not wanted:
        return sorted(found, key=lambda pair: pair[1].id)
    ids = {ref.id for _, ref in found}
    for unit_id in wanted:
        try:
            parse_unit_id(unit_id)
        except ValueError as exc:
            raise L4Exit(ExitCode.USAGE_ERROR, str(exc)) from None
        if unit_id not in ids:
            raise UnknownUnit(f"no such unit: {unit_id}")
    return sorted((pair for pair in found if pair[1].id in set(wanted)), key=lambda pair: pair[1].id)


_DENIED = ("access denied", "authentication failed", "http basic", "returned error: 401", "returned error: 403")


def _fetch_reason(app: AppContext, exc: GitError) -> str:
    """What git said, in one redacted line: the first line of its stderr without the `fatal: ` prefix."""
    lines = [line.strip() for line in exc.stderr.splitlines() if line.strip()]
    first = lines[0].removeprefix("fatal: ") if lines else f"git exited with {exc.returncode}"
    return app.redactor.redact_text(first)[:200]


# what a failed local fetch tells the command that stops on it, besides the reason: how to go on without the forge
READ_LOCAL_HINT = "pass --no-fetch to read the local refs"
RUN_NEEDS_FORGE_HINT = (
    "a run needs the forge (its worktree fetches the unit); fix the connection, "
    "or read the local state with `l4 status --no-fetch`"
)  # `l4 run` and `l4 resume`: `--no-fetch` skips the read of the state, not the fetch of the worktree
ARCHIVE_NEEDS_FORGE_HINT = (
    "an archive needs the forge (its worktree fetches the base branch); fix the connection, "
    "or read the local state with `l4 status --no-fetch`"
)


def refresh_refs(
    app: AppContext,
    cfg: L4Config,
    git: Git,
    *,
    tolerate_denied: bool = False,
    fetch: bool = True,
    stop_hint: str = READ_LOCAL_HINT,
) -> None:
    """The unit branches, lock refs and plan refs are fetched with `--prune` before anything is folded (G8, L4-CLI-005),
    in a CI job or not; `fetch=False` (`--no-fetch`) reads the local refs, and a CI job must not (usage error,
    L4-CLI-003). In a CI job, with `tolerate_denied` (`l4 status` only) a fetch the forge refuses falls back to the
    local refs and says so: the job token in the origin URL stops working once the job is cancelled. Any other git
    error still raises. On a person's computer a failed fetch (a laptop may be offline) makes `l4 status`
    (`tolerate_denied`) say so and show the local refs, whatever git said, after `STATUS_FETCH_TIMEOUT_S` at the
    latest; any other command stops with the reason and `stop_hint` (exit 3 when the forge refused the credential,
    and then the token variable is named when it is set)."""
    job = in_ci_job(app.environ)
    if job and not fetch:
        raise L4Exit(
            ExitCode.USAGE_ERROR,
            "--no-fetch is for a person's computer: a CI job must not read stale refs (L4-CLI-003)",
        )
    try:
        refresh_remote_refs(
            git, branch_prefix=cfg.forge.branch_prefix, run_id=app.run_id, fetch=fetch,
            config=fetch_auth_config(cfg, app.environ) if job
            else fetch_auth_config(cfg, app.environ, origin_url(app.repo, app.environ)),
            timeout=STATUS_FETCH_TIMEOUT_S if tolerate_denied and not job else None,
        )  # fmt: skip
    except GitError as exc:
        if job:
            if not (tolerate_denied and any(word in exc.stderr.lower() for word in _DENIED)):  # git's answer, not argv
                raise
            log.warning(
                "could not refresh from the forge (access denied: the job may be cancelled); showing local refs"
            )
            return
        reason = _fetch_reason(app, exc)
        if tolerate_denied:
            log.warning("could not refresh from the forge (%s); showing local refs", reason)
            return
        refused = is_permission_failure(exc.stderr)
        message = f"could not refresh from the forge ({reason})"
        if refused and app.environ.get(cfg.forge.token_env):  # git uses it instead of the person's own credentials
            message += (
                f"; {cfg.forge.token_env} is set, so git uses it instead of your credential helper: check or unset it"
            )
        raise L4Exit(
            ExitCode.DOCTOR_FAILED if refused else ExitCode.INTERNAL_ERROR, f"{message}; {stop_hint}"
        ) from None


def _archive_snapshot(git: Git, cfg: L4Config, name: str, folder: str, ref: str) -> UnitSnapshot | None:
    """An archived OpenSpec change that holds a `feedback.md`, as the base branch has it: the archive folded the pending
    ledger into the folder's own, so the fold reads `merged` there. None for anything that is not a merged unit."""
    unit = UnitRef(Framework.OPENSPEC, name, git.repo / folder)
    try:
        blobs = regular_blobs(git, ref, f"{folder}/.l4/ledger/", MAX_LEDGER_FILE_BYTES)
        files = {
            blob.path.rsplit("/", 1)[-1]: git.run_bytes("cat-file", "blob", blob.oid)
            for blob in blobs
            if blob.path.endswith(".jsonl")
        }
        state = fold(parse_ledger_files(files).events, unit.id)
    except LedgerCorrupt:
        return None
    if state.phase != Phase.MERGED.value:
        return None
    return UnitSnapshot(unit, state, [], "archive", feedback=read_feedback_at(git, ref, folder))


def discover(
    cfg: L4Config, git: Git, providers: list[SpecProvider], wanted: tuple[str, ...] = ()
) -> list[tuple[SpecProvider, UnitSnapshot]]:
    """Every unit with its snapshot: the units of the working tree, plus what only git holds (L4-FBK-010): the open
    follow-ups, which live on their own branch and are never on the base until they merge, and the archived OpenSpec
    changes that carry a `feedback.md`. A `merged` unit gets its `feedback.md` from the base branch (the person's
    items are committed there) and the offer a follow-up should take."""
    prefix = cfg.forge.branch_prefix
    known = known_follow_ups(git, cfg)
    by_framework = {p.framework: p for p in providers}
    branch_only = [k for k in known if k.branch and not k.on_base and k.framework in by_framework]
    base = base_ref(cfg)
    has_base = git.rev_parse(base) is not None
    archived = archive_folders(git, cfg) if has_base and Framework.OPENSPEC in by_framework else {}
    extra_ids = {k.id for k in branch_only} | {f"openspec:{n}" for n in archived}
    base_wanted = tuple(w for w in wanted if w not in extra_ids)
    pairs = [] if wanted and not base_wanted else select_units(providers, base_wanted)
    rows = [(p, load_snapshot(p, git, ref, branch_prefix=prefix)) for p, ref in pairs]
    listed = {s.ref.id for _, s in rows}
    for k in branch_only:
        if k.id in listed or (wanted and k.id not in wanted):
            continue
        provider = by_framework[k.framework]
        ref = UnitRef(k.framework, k.name, provider.unit_dir(UnitRef(k.framework, k.name, git.repo)))
        rows.append((provider, load_snapshot(provider, git, ref, branch_prefix=prefix)))
        listed.add(k.id)
    for name, folder in archived.items():
        unit_id = f"openspec:{name}"
        if unit_id in listed or (wanted and unit_id not in wanted):
            continue
        if read_feedback_at(git, base, folder) is None:
            continue  # an archived change with no feedback is not a unit any more
        if (snapshot := _archive_snapshot(git, cfg, name, folder, base)) is not None:
            rows.append((by_framework[Framework.OPENSPEC], snapshot))
    phases = {s.ref.id: s.state.phase for _, s in rows}
    done = {Phase.MERGED.value, Phase.ABANDONED.value}
    out = []
    for provider, snapshot in rows:
        if snapshot.state.phase == Phase.MERGED.value:
            follows = follow_ups_of(known, snapshot.ref.id)
            opened = {k.name for k in follows if phases.get(k.id) not in done}
            released = {k.name for k in follows if phases.get(k.id) == Phase.ABANDONED.value}
            file = snapshot.feedback
            if has_base and snapshot.source != "archive":
                rel = _relative(provider, snapshot.ref, git)
                file = read_feedback_at(git, base, rel) or file  # the base branch holds what the person committed
            # the follow-ups' takes are on their own ledgers, not the parent's: the parent reads them from the markers
            state = taken_by_follow_ups(snapshot.state, file, [k for k in follows if k.name not in released])
            snapshot = replace(
                snapshot, state=state, feedback=file, follow_up=offer_for(file, state, follows, opened, released)
            )
        out.append((provider, snapshot))
    return _with_delegate(cfg, git, sorted(out, key=lambda pair: pair[1].ref.id))


def _with_delegate(
    cfg: L4Config, git: Git, rows: list[tuple[SpecProvider, UnitSnapshot]]
) -> list[tuple[SpecProvider, UnitSnapshot]]:
    """The questions the delegate has still to decide (`UnitSnapshot.delegate_due`, L4-DLG-003), for the units in its
    scope. This run's config is the cheap first look (the delegate off costs nothing); the settings and the scope come
    from the base branch and the plan files, read once and only when a unit waits."""
    if not cfg.delegate.enabled:
        return rows
    from l4.delegate.due import stamp_due  # the delegate imports the planner and the plan state, which import this
    from l4.delegate.scope import plans_view
    from l4.delegate.settings import delegate_settings

    settings = delegate_settings(git, cfg.forge.base_branch)
    stamped = stamp_due([s for _, s in rows], settings.delegate, lambda: plans_view(git.repo, cfg, git))
    return [(provider, snap) for (provider, _), snap in zip(rows, stamped, strict=True)]


def select_runnable(cfg: L4Config, git: Git, providers: list[SpecProvider], unit: str) -> tuple[SpecProvider, UnitRef]:
    """The one unit a command with `--unit` acts on, open follow-ups included. An archived change is only ever the
    parent of a follow-up: it is no unit to run, resume or verify."""
    for provider, snapshot in discover(cfg, git, providers, (unit,)):
        if snapshot.source != "archive":
            return provider, snapshot.ref
    raise UnknownUnit(f"no such unit: {unit}")


def snapshots(
    app: AppContext,
    cfg: L4Config,
    wanted: tuple[str, ...],
    *,
    tolerate_denied: bool = False,
    fetch: bool = True,
    stop_hint: str = READ_LOCAL_HINT,
) -> list[UnitSnapshot]:
    git = Git(app.repo, environ=app.environ)
    refresh_refs(app, cfg, git, tolerate_denied=tolerate_denied, fetch=fetch, stop_hint=stop_hint)
    return [s for _, s in discover(cfg, git, providers_for(cfg, app.repo, app.environ), wanted)]


REASON_WIDTH = 60  # the REASON cell of the table (L4-OPS-006)


def _cut(text: str | None) -> str:
    """One line, at most `REASON_WIDTH` characters, an ellipsis where it was cut; `-` for no reason."""
    line = " ".join((text or "").split())
    if not line:
        return "-"
    return line if len(line) <= REASON_WIDTH else line[: REASON_WIDTH - 1] + "…"


def _facts(snapshot: UnitSnapshot) -> "UnitFacts":
    from l4.planner import facts_of  # the planner imports this module: the facts are read at call time

    return facts_of(snapshot)


def _where(snapshot: UnitSnapshot, repo: Path, branch_prefix: str) -> tuple[str, str]:
    """(branch, questions path in the repository) of the unit, for the step that names where an answer goes."""
    try:
        folder = snapshot.ref.path.resolve().relative_to(repo.resolve()).as_posix()
    except ValueError:
        folder = snapshot.ref.path.as_posix()
    return unit_branch(snapshot.ref.id, branch_prefix), f"{folder}/{QUESTIONS_FILENAME}"


def _next(snapshot: UnitSnapshot, repo: Path, branch_prefix: str) -> str:
    branch, questions_path = _where(snapshot, repo, branch_prefix)
    return next_step(_facts(snapshot), branch=branch, questions_path=questions_path)


def _since(ts: str, now: datetime) -> str:
    return ago((now - datetime.strptime(ts, TS_FORMAT).replace(tzinfo=UTC)).total_seconds())


def _table(rows: list[UnitSnapshot], now: datetime) -> str:
    header = ("UNIT", "PHASE", "REASON", "ITER", "TASKS", "OPEN-Q", "VERDICT", "LAST", "SOURCE")
    body = [
        (
            s.ref.id, s.state.phase or "-", _cut(reason(_facts(s))), str(s.state.iteration),
            f"{s.tasks_done}/{s.tasks_total}",
            ",".join(s.state.questions.open) or "-", s.state.last_verdict.verdict if s.state.last_verdict else "-",
            f"{_since(s.last_activity.ts, now)} ago" if s.last_activity else "-", s.source,
        )
        for s in rows
    ]  # fmt: skip
    if any(s.feedback_counts for s in rows):  # a column only when some unit has items (D12)
        header = (*header, "FEEDBACK")
        body = [
            (*line, ", ".join(f"{name.replace('_', ' ')} {n}" for name, n in s.feedback_counts.items()) or "-")
            for line, s in zip(body, rows, strict=True)
        ]
    widths = [max(len(r[i]) for r in [header, *body]) for i in range(len(header))]
    return "\n".join(
        "  ".join(cell.ljust(w) for cell, w in zip(r, widths, strict=True)).rstrip() for r in [header, *body]
    )


NOTE_LIMIT = 300  # the reason that `Orchestrator.resume` records and the prompt block reads (L4-OPS-018)


def note_binding(state: UnitState) -> tuple[str | None, str | None]:
    """The task (and fix unit) that a person's note binds to: the one that tripped `max_task_attempts` on a `halted`
    unit; `(None, None)` for every other stop, which names no task (L4-OPS-018, D11)."""
    if state.phase == Phase.HALTED.value and state.halt_reason == "max_task_attempts" and state.halt_task:
        return state.halt_task, state.halt_fix_unit
    return None, None


def note_lines(command: str, state: UnitState, reason: str) -> list[str]:
    """The lines that `l4 retry` and `l4 resume` print about the note, from the state before they recorded: the cut
    of a long reason, then where the reason goes (L4-OPS-018, D13)."""
    lines = []
    if len(reason) > NOTE_LIMIT:
        cut = f"{command}: the reason is longer than {NOTE_LIMIT} characters"
        lines.append(f"{cut}; the implementer reads the first {NOTE_LIMIT}")
    task, _ = note_binding(state)
    lines.append(
        f"note: the reason goes to the next steps of task {task}"
        if task
        else "note: the stop names no task, so no implementer step reads the reason"
    )
    return lines


def _block(
    snapshot: UnitSnapshot, repo: Path, cfg: L4Config, now: datetime, urls: ForgeUrls, hint: str | None = None
) -> str:
    """The `--unit` detail (L4-OPS-006): the phase, the whole cause of a stop, the run that stopped it, the label that
    does what the step does, and the step last."""
    facts = _facts(snapshot)
    held = snapshot.state.phase == Phase.AWAITING_HUMAN.value and bool(facts.harness_open)  # L4-OPS-006
    cause = reason(facts) if snapshot.state.phase in (*STOPPED, CORRUPT_PHASE) or held else None
    label = label_for(facts, cfg.forge.labels_prefix)
    lines = [f"Phase: {snapshot.state.phase or '-'}"]
    lines += [f"Cause: {cause}"] if cause else []
    lines += [f"Stopped in run: {snapshot.stopped_in}"] if snapshot.stopped_in else []
    if (last := snapshot.last_activity) is not None:
        what = ", ".join(
            [last.type, *([f"task {last.task}"] if last.task else []), *([f"run {last.run_id}"] if last.run_id else [])]
        )
        lines.append(f"Last activity: {_since(last.ts, now)} ago ({what})")
    if snapshot.prompt_cut is not None:
        lines.append(_prompt_cut_line(snapshot.prompt_cut))
    if (run := snapshot.open_run) is not None:
        link = f": {urls.expand(run.ci_url)}" if run.ci_url else ""
        lines.append(f"Open run: {run.run_id} started {_since(run.started, now)} ago, no end recorded{link}")
    lines += [f"Or: add the label {label}"] if label else []
    state = snapshot.state
    if state.phase == Phase.HALTED.value and state.halt_reason == "max_task_attempts" and state.halt_task:
        of = f" of {state.halt_fix_unit}" if state.halt_fix_unit else ""
        lines.append(f"Retry note: the --reason of l4 retry goes to the implementer of task {state.halt_task}{of}")
    lines += _delegate_lines(snapshot)
    return "\n".join([*lines, f"Next: {_next(snapshot, repo, cfg.forge.branch_prefix)}", *([hint] if hint else [])])


def open_question_kinds(snapshot: UnitSnapshot) -> tuple[str, ...]:
    """The kinds of the open questions of the unit and of its fix units that the delegate could still take (the
    delegate's hint, L4-DLG-021): one it escalated for its current raise is final, and it would never ask again."""
    escalated: set[str] = set()
    if any(e.type == "delegate.result" for e in snapshot.events):
        from l4.delegate.due import escalations  # the delegate imports this module

        keys = [q.id for q in snapshot.questions.questions] if snapshot.questions else []
        keys += [f"{c.name}/{q.id}" for c in snapshot.children if c.questions for q in c.questions.questions]
        escalated = {key for key, _, _ in escalations(snapshot.events, keys)}
    owners = [("", snapshot.questions), *((f"{child.name}/", child.questions) for child in snapshot.children)]
    return tuple(
        q.kind.value if q.kind is not None else "unknown"
        for prefix, file in owners
        if file is not None
        for q in file.questions
        if q.status is QuestionStatus.OPEN and f"{prefix}{q.id}" not in escalated
    )


def _delegate_hint(reader: "HintReader", snapshot: UnitSnapshot) -> str | None:
    return reader.hint(snapshot.ref.id, snapshot.state.phase, open_question_kinds(snapshot), fix_of=snapshot.fix_of)


def _has_delegate(snapshot: UnitSnapshot) -> bool:
    return any(e.type == "delegate.result" for e in snapshot.events)  # the delegate off: nothing is read or shown


def _delegate_lines(snapshot: UnitSnapshot) -> list[str]:
    """`Delegate:` lines, one per question the delegate answered, escalated or defers (L4-DLG-011)."""
    if not _has_delegate(snapshot):
        return []
    from l4.delegate.lines import status_lines  # the delegate imports this module

    return status_lines(snapshot.events)


def _delegate_json(snapshot: UnitSnapshot) -> list[dict[str, Any]]:
    if not _has_delegate(snapshot):
        return []
    from l4.delegate.lines import status_json

    return status_json(snapshot.events)


def _activity_json(last: Activity | None) -> dict[str, str] | None:
    if last is None:
        return None
    return {"ts": last.ts, "type": last.type, **({"task": last.task} if last.task else {}), "run_id": last.run_id or ""}


def _open_run_json(run: OpenRun | None, urls: ForgeUrls) -> dict[str, str] | None:
    if run is None:
        return None
    return {"run_id": run.run_id, "started": run.started, **({"ci_url": urls.expand(run.ci_url)} if run.ci_url else {})}


def _utcnow() -> datetime:
    return datetime.now(UTC)


MAX_VERIFICATION_BYTES = 1024 * 1024


def _check_read_flags(
    unit: str | None, events: bool, event_type: str | None, last: int | None, verification: bool
) -> None:
    """`--events` and `--verification` read one unit; `--type` and `--last` filter events (exit 2 otherwise)."""
    if events and verification:
        raise L4Exit(ExitCode.USAGE_ERROR, "status: --events and --verification are one of two readings; use one")
    if (events or verification) and not unit:
        raise L4Exit(ExitCode.USAGE_ERROR, "status: --events and --verification need --unit")
    if (event_type is not None or last is not None) and not events:
        raise L4Exit(ExitCode.USAGE_ERROR, "status: --type and --last need --events")
    if last is not None and last < 1:
        raise L4Exit(ExitCode.USAGE_ERROR, "status: --last must be 1 or more")


def _events_text(unit: str, row: UnitSnapshot, event_type: str | None, last: int | None, as_json: bool) -> str:
    if row.corrupt:
        raise L4Exit(ExitCode.INTERNAL_ERROR, f"{unit}: ledger corrupt: {row.corrupt}")
    chosen = [e for e in row.events if event_type is None or e.type == event_type]
    shown = chosen[-last:] if last else chosen
    if as_json:
        rows = [
            {"ts": e.ts.strftime(TS_FORMAT), "run_id": e.run_id, "seq": e.seq, "type": e.type, **e.data} for e in shown
        ]
        document = {"schema": "l4/events@1", "unit": unit, "total": len(chosen), "shown": len(shown), "events": rows}
        return json.dumps(document, indent=2, ensure_ascii=False)
    lines = [
        " ".join(
            [
                e.ts.strftime(TS_FORMAT),
                e.run_id,
                f"#{e.seq}",
                e.type,
                *(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in e.data.items()),
            ]
        )
        for e in shown
    ]
    return "\n".join(lines) if lines else f"{unit}: no such events"


def _verification_text(app: AppContext, cfg: L4Config, row: UnitSnapshot) -> str:
    """The unit's `verification.md` from the same source as its ledger: the branch on origin, else the working tree."""
    name = "verification.md"
    missing = f"{row.ref.id}: no verification.md ({row.source})"
    try:
        folder = row.ref.path.resolve().relative_to(app.repo.resolve()).as_posix()
    except ValueError:
        return missing
    if row.source == "branch":
        git = Git(app.repo, environ=app.environ)
        tracking = f"refs/remotes/{REMOTE}/{unit_branch(row.ref.id, cfg.forge.branch_prefix)}"
        blobs = regular_blobs(git, tracking, f"{folder}/{name}", MAX_VERIFICATION_BYTES)
        return git.run_bytes("cat-file", "blob", blobs[0].oid).decode("utf-8", "replace") if blobs else missing
    try:
        return read_regular_file(row.ref.path / name, limit=MAX_VERIFICATION_BYTES).decode("utf-8", "replace")
    except (UnsafeFile, OSError):
        return missing


def run_status(
    app: AppContext,
    *,
    unit: str | None,
    as_json: bool,
    rebuild: bool,
    events: bool = False,
    event_type: str | None = None,
    last: int | None = None,
    verification: bool = False,
    no_fetch: bool = False,
    clock: Callable[[], datetime] = _utcnow,
) -> ExitCode:
    if rebuild:
        raise L4Exit(ExitCode.USAGE_ERROR, "status: --rebuild not yet implemented (M1: state-vcs-locks 1.19)")
    _check_read_flags(unit, events, event_type, last, verification)
    if early_pin_stop(
        app.repo, app.environ, command="status", config_path=app.config_path
    ):  # L4-IMP-072: a stopped job's status step is not red
        return ExitCode.OK
    app, cfg = load_app_config(app)  # schema errors: exit 2, nothing else runs
    rows = snapshots(app, cfg, (unit,) if unit else (), tolerate_denied=True, fetch=not no_fetch)
    if events or verification:
        row = rows[0]
        text = _events_text(row.ref.id, row, event_type, last, as_json) if events else _verification_text(app, cfg, row)
        click.echo(app.redactor.redact_text(text), nl=not text.endswith("\n"))
        return ExitCode.OK
    urls = app_forge_urls(app, cfg)
    now = clock()
    from l4.delegate.hint import HintReader  # the delegate imports this module

    reader = HintReader(Git(app.repo, environ=app.environ), cfg)
    hints = {s.ref.id: _delegate_hint(reader, s) for s in rows} if unit else {}  # one unit: no read for a listing
    from l4.yolo.commands import plan_lines  # here: the plan commands import this module

    plans = plan_lines(app.repo, Git(app.repo, environ=app.environ), {s.ref.id: s.state.phase for s in rows}, cfg)
    if as_json:
        units = [
            {
                **s.state.model_dump(mode="json", by_alias=True),
                "pr": urls.expand(s.state.pr) if s.state.pr else None,  # the recorded `<forge>` back to a link
                "spec_tasks": {"done": s.tasks_done, "total": s.tasks_total},
                "source": s.source,
                "reason": reason(_facts(s)),
                "next": _next(s, app.repo, cfg.forge.branch_prefix),
                **({"feedback_counts": s.feedback_counts} if s.feedback_counts else {}),
                **({"corrupt": s.corrupt} if s.corrupt else {}),
                **({"delegate": d} if (d := _delegate_json(s)) else {}),
                **({"delegate_hint": hints[s.ref.id]} if unit else {}),
                "last_activity": _activity_json(s.last_activity),
                "prompt_cut": s.prompt_cut,
                "open_run": _open_run_json(s.open_run, urls),
            }
            for s in rows
        ]
        payload: dict[str, object] = {"schema": "l4/status@1", "units": units}
        if plans:
            payload["plans"] = plans  # only with a plan: the shape of a repository without one is unchanged
        text = json.dumps(payload, indent=2, ensure_ascii=False)
    else:
        text = _table(rows, now) if rows else "no units"
        text = "\n".join([*plans, text])  # one line per plan above the table (L4-YOLO-015)
        if unit and rows:
            text = "\n\n".join([text, *(_block(s, app.repo, cfg, now, urls, hints.get(s.ref.id)) for s in rows)])
    click.echo(app.redactor.redact_text(text))
    return ExitCode.OK
