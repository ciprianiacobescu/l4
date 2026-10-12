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
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Literal

import click

from l4.config.redaction import load_app_config
from l4.config.schema import L4Config
from l4.context import AppContext
from l4.exitcodes import ExitCode, L4Exit
from l4.forge.base import fetch_auth_config
from l4.forge.urls import app_forge_urls
from l4.implementer.tasks import required
from l4.specs.base import Framework, SpecProvider, Task, UnitRef, UnknownUnit, parse_unit_id
from l4.specs.feedback import FEEDBACK_FILENAME, MAX_FEEDBACK_BYTES, FeedbackFile
from l4.specs.fixmark import read_fix_marker
from l4.specs.kiro import kiro_tasks
from l4.specs.markers import MAX_TASKS_BYTES
from l4.specs.openspec import parse_openspec_tasks
from l4.specs.providers import providers_for
from l4.specs.questions import MAX_QUESTIONS_BYTES, QUESTIONS_FILENAME, QuestionsFile
from l4.state.feedback_view import counts, item_views
from l4.state.fold import UnitState, fold
from l4.state.ledger import (
    MAX_LEDGER_FILE_BYTES,
    LedgerCorrupt,
    LedgerRead,
    parse_ledger_files,
    read_ledger_files,
)
from l4.state.lifecycle import Phase
from l4.state.pending import merge_ledgers, read_pending
from l4.state.review import AfterHandoff, after_handoff
from l4.vcs.errors import GitError
from l4.vcs.git import Git
from l4.vcs.names import lock_ref, unit_branch
from l4.vcs.refresh import refresh_in_ci
from l4.vcs.tree import regular_blobs

REMOTE = "origin"
TASK_PARSERS: dict[Framework, Callable[[bytes], list[Task]]] = {
    Framework.OPENSPEC: parse_openspec_tasks,
    Framework.KIRO: kiro_tasks,
}
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
class UnitSnapshot:
    ref: UnitRef
    state: UnitState
    tasks: list[Task]
    source: Literal["branch", "worktree"]
    corrupt: str | None = None  # "<file>:<line> ..." when the ledger could not be read; the phase is then "corrupt"
    questions: QuestionsFile | None = None  # `questions.md` from the same source as the tasks and the ledger
    children: tuple[ChildSnapshot, ...] = ()  # the fix units the ledger names, from the same source
    fix_of: str | None = None  # the parent's unit id when this unit is itself a fix unit (`.l4/fix.json`)
    review: AfterHandoff | None = None  # an `in_review` unit read from its branch: what happened after H (M1.9)
    feedback: FeedbackFile | None = None  # `feedback.md` from the same source as the tasks and the ledger

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
        read = merge_ledgers(parse_ledger_files(files), read_pending(git, lock_ref(ref.id)))  # the tail after H (5.5)
        _check_unit(read, ref.id)
    except LedgerCorrupt as exc:
        detail = str(exc).removeprefix("ledger corrupt: ")
        log.warning("%s: ledger corrupt: %s", ref.id, detail)
        return UnitSnapshot(ref, UnitState(unit=ref.id, phase=CORRUPT_PHASE), [], source, corrupt=detail)
    for name in read.torn:
        log.warning("%s: last line of %s was cut off mid-write and is ignored", ref.id, name)
    state = fold(read.events, ref.id)
    children = child_snapshots(provider, git, ref, state.children, tracking_ref if on_branch else None)
    marker = read_fix_marker(provider.unit_dir(ref))
    review = None
    if on_branch and state.phase == Phase.IN_REVIEW.value:
        review = after_handoff(git, tracking_ref, ref.name, _relative(provider, ref, git))
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
    )


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


def refresh_refs(app: AppContext, cfg: L4Config, git: Git, *, tolerate_denied: bool = False) -> None:
    """In CI, the unit branches and lock refs are fetched with `--prune` before anything is folded (G8). With
    `tolerate_denied` (`l4 status` only) a fetch the forge refuses falls back to the local refs and says so: the job
    token in the origin URL stops working once the job is cancelled. Any other git error still raises."""
    try:
        refresh_in_ci(
            git, environ=app.environ, branch_prefix=cfg.forge.branch_prefix, run_id=app.run_id,
            config=fetch_auth_config(cfg, app.environ),
        )  # fmt: skip
    except GitError as exc:
        if not (tolerate_denied and any(word in exc.stderr.lower() for word in _DENIED)):  # git's answer, not argv
            raise
        log.warning("could not refresh from the forge (access denied: the job may be cancelled); showing local refs")


def snapshots(
    app: AppContext, cfg: L4Config, wanted: tuple[str, ...], *, tolerate_denied: bool = False
) -> list[UnitSnapshot]:
    git = Git(app.repo, environ=app.environ)
    refresh_refs(app, cfg, git, tolerate_denied=tolerate_denied)
    pairs = select_units(providers_for(cfg, app.repo, app.environ), wanted)
    return [load_snapshot(p, git, ref, branch_prefix=cfg.forge.branch_prefix) for p, ref in pairs]


def _table(rows: list[UnitSnapshot]) -> str:
    header = ("UNIT", "PHASE", "ITER", "TASKS", "OPEN-Q", "VERDICT", "SOURCE")
    body = [
        (
            s.ref.id, s.state.phase or "-", str(s.state.iteration), f"{s.tasks_done}/{s.tasks_total}",
            ",".join(s.state.questions.open) or "-", s.state.last_verdict.verdict if s.state.last_verdict else "-",
            s.source,
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


def run_status(app: AppContext, *, unit: str | None, as_json: bool, rebuild: bool) -> ExitCode:
    if rebuild:
        raise L4Exit(ExitCode.USAGE_ERROR, "status: --rebuild not yet implemented (M1: state-vcs-locks 1.19)")
    app, cfg = load_app_config(app)  # schema errors: exit 2, nothing else runs
    rows = snapshots(app, cfg, (unit,) if unit else (), tolerate_denied=True)
    urls = app_forge_urls(app, cfg)
    if as_json:
        units = [
            {
                **s.state.model_dump(mode="json", by_alias=True),
                "pr": urls.expand(s.state.pr) if s.state.pr else None,  # the recorded `<forge>` back to a link
                "spec_tasks": {"done": s.tasks_done, "total": s.tasks_total},
                "source": s.source,
                **({"feedback_counts": s.feedback_counts} if s.feedback_counts else {}),
                **({"corrupt": s.corrupt} if s.corrupt else {}),
            }
            for s in rows
        ]
        text = json.dumps({"schema": "l4/status@1", "units": units}, indent=2, ensure_ascii=False)
    else:
        text = _table(rows) if rows else "no units"
    click.echo(app.redactor.redact_text(text))
    return ExitCode.OK
