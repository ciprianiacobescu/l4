"""The minimal sweeper behind `l4 plan --sweep` and `l4 archive --unit` (forge-and-ci 1.36, M1.1 line 36).

One duty: a unit in `in_review` whose merge request a human merged becomes `merged` (an event in the pending ledger of
its lock ref, L4-STA-004) and gets its archive merge request (`l4.postmerge`), once. A unit already `merged` whose
folder is still under `openspec/changes/` gets the archive MR if it has none (a crash between the two steps, or an
archive MR that had to wait for another). Nothing is merged, closed or deleted here.

A definitive archive failure (`archive.failed`: the done-gate, strict validation, the CLI, a stray path, a ledger that
contradicts itself, a refusal of the archive push by the server's hooks, a 4xx of the forge) is written with the head of
the base branch and the tree of the unit's folder, and the unit is not tried again until one of the two changes or the
sweep runs with `retry` (`l4 archive --unit ID --retry`, for a cause outside the repository such as a push rule). The
lock ref is never deleted for this: it holds the pending ledger (L4-STA-004). A transient forge or git error is not a
failure: it is logged, the other units are still swept and the next pipeline tries again. Only an environment problem
(exit 3) or a bug is raised, after the last unit.

A Kiro unit has no change folder and no archive MR (`kiro.archive_dir` is not honoured): once its MR has merged the
sweep runs the done-gate on the base branch's head (`PostMergeArchiver.check_done`) and records `archive.done`
(`via: done_gate`), once. A refused gate is `archive.failed` like any archive failure, said once on the MR's note, and
tried again only when the unit's folder changes. Its lock ref is kept: the folder stays on the base, and the pending
ledger is the only record that the unit merged (retired, the folder's own ledger would read `in_review` again and the
next sweep would merge the unit a second time).

Once the archive MR has merged, the unit's folder is gone from the base and its lock ref is moved to
`refs/l4/archived/<fw>/<name>/<run-id>` (a reduced 2.51): the same commit, so the pending ledger is kept, and a later
change of the same name starts with no history of the old one.

The CI duty (M1.9, `l4 plan --sweep` only): an `in_review` unit with an open MR, whose branch head is its hand-off
commit H and whose H has no CI record yet, has the project's own pipeline for H read (`l4.ci.repo_ci`). A red job that
is not red on the base head either is recorded as `ci.failed` (with the end of its log, redacted), one that is red on
both as `ci.preexisting`, under the unit's lease and published to the lock ref; the next `l4 run` takes the edge. A
green or running pipeline writes nothing, and a branch past H is left to the run. Once per H.

The label duty (M1.11, L4-OPS-008, `l4 plan --sweep` only): a `halted`, `escalated` or `waiting_capacity` unit whose
open MR carries `<prefix>retry` or `<prefix>resume` is retried (`l4.state.retry.retry_unit`: the phase decides what a
retry does, a round added at a round limit included, L4-CI-004, L4-FBK-006), and a started unit whose open MR carries
`<prefix>restart` is started over (`l4.state.restart.restart_unit`); `restart` is also read on the closed MR of an
`abandoned` unit. A label counts when a member set it (`l4.ci.resume_label`: the forge's own record of who, Developer
access or more, not the harness's user), once per label event (`unit.retried{signal}`, `unit.restarted{signal}`). When
two operator labels are waiting, the newest event acts and the other is refused. A refusal (a non-member, the bot) is
said once per event: `resume.refused{signal, why}` in the pending ledger, the text naming the command that works, and
a section of the MR's sticky note.

The closed-MR duty (L4-OPS-009, `l4 plan --sweep` only): a started, non-terminal unit whose newest MR is closed without
a merge records `pr.closed{number}` and takes `pr_closed` (`abandoned`), with a note that names `l4 restart`; an
`abandoned` unit whose newest MR is open again takes `pr_reopened`. An MR that is not the unit's (the ledger names
another, or the unit was started over) is no evidence.

The follow-up duty (`l4 plan --sweep` only, L4-FBK-010): a `merged` unit whose `feedback.md` on the base branch has
takeable items and no open follow-up gets its follow-up unit `<name>-followup-<n>` (`l4.follow_up`: its own branch from
the base head, never pushed to the base). While one is open, newer items are recorded once as `feedback.waiting`
(`reason: follow_up_open`) in the pending ledger of the parent's lock ref; an archived change has no lock ref, and
nothing is written for it.

M1: forge-and-ci 2.51 (WIP-branch cleanup, deleting the archived refs), 2.53 (closed and reopened MRs), 2.54
(base-move refresh), state-vcs-locks 2.32 (capacity and lease resume), 2.35 (mirror repair).
"""

import logging
import shutil
from collections.abc import Collection, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from l4.ci.handoff_ci import NO_CHECK_RUN, read_handoff_ci  # noqa: F401  (NO_CHECK_RUN stays importable from here)
from l4.ci.resume_label import (
    Refusal,
    ResumeSignal,
    abandoned_section,
    halted_section,
    resume_refused_note,
    resume_signal,
    retry_label,
)
from l4.config.defaults import cache_root
from l4.config.schema import L4Config
from l4.context import AppContext
from l4.exitcodes import ExitCode, L4Exit
from l4.follow_up import perform_follow_ups
from l4.forge.base import (
    Forge,
    ForgeAuthError,
    ForgeError,
    ForgeRateLimited,
    ForgeUnavailable,
    JobLog,
    JobResult,
    PullRequest,
    fetch_auth_config,
    forge_platform,
    make_forge,
    require_token_in_ci,
)
from l4.forge.gitlab import push_auth_config, strip_remote_credentials
from l4.forge.pushfail import PushFailed
from l4.forge.urls import app_forge_urls, origin_url
from l4.postmerge import ArchiveResult, MergeDetector, MergeVerdict, PostMergeArchiver, merge_archive_guarded
from l4.progress import SWEEP_TRACE_TYPES, FilteredTrace, ProgressTrace
from l4.specs.base import Framework, UnitRef, parse_unit_id
from l4.specs.providers import provider_for_unit, providers_for
from l4.state.budget import feedback_rounds_exhausted
from l4.state.ledger import LedgerEvent, LedgerWriter, ledger_path
from l4.state.lifecycle import Phase, Trigger, transition
from l4.state.pending import PendingLedger, read_pending
from l4.state.review import foreign_tail
from l4.state.status import UnitSnapshot
from l4.vcs.errors import GitError
from l4.vcs.git import Git
from l4.vcs.locks import Busy, LocalFileLease
from l4.vcs.names import UnitNames, unit_branch
from l4.vcs.push import LOCK_REF_PREFIX, PushRejected
from l4.vcs.repokey import repository_key
from l4.yolo.tidy import tidy_archive_branch

if TYPE_CHECKING:
    from l4.orchestrator import UnitRunResult
    from l4.state.restart import RestartResult

log = logging.getLogger("l4.sweeper")

_SWEPT = {Phase.IN_REVIEW.value, Phase.MERGED.value}
_RETRIED = frozenset({Phase.HALTED.value, Phase.ESCALATED.value, Phase.WAITING_CAPACITY.value})  # where retry works
_ENDED = frozenset({Phase.MERGED.value, Phase.ARCHIVED.value})  # no operator label and no closed MR changes these
MAX_TAILS = 3  # failed jobs whose log tail goes into `ci.failed`; the others are listed by name
MAX_TAIL_LINES = 40
MAX_TAIL_CHARS = 3000
MAX_STEP_CHARS = 300


@dataclass(frozen=True)
class SweepAction:
    unit: str
    what: Literal[
        "merged", "archive_opened", "archive_existing", "archive_pending", "archive_failed", "skipped", "retired",
        "done", "ci_failed", "ci_preexisting", "ci_waiting", "ci_green", "ci_not_run", "resumed", "resume_refused",
        "resume_hint", "restarted", "abandoned", "reopened", "follow_up", "follow_up_waiting",
    ]  # fmt: skip
    detail: str = ""


def definitive_reason(exc: Exception) -> str | None:
    """Why a failure of the archive repeats until something changes: the server's hooks refused the push, or the forge
    answered 4xx (not a credential problem, a rate limit or a timeout). None: transient or the environment's."""
    if isinstance(exc, PushFailed):
        return str(exc) if exc.refused else None
    transient = isinstance(exc, ForgeAuthError | ForgeRateLimited)
    if isinstance(exc, ForgeError) and not transient and exc.status is not None and 400 <= exc.status < 500:
        return None if exc.status == 408 else str(exc)
    return None


def _repeats_until_fixed(exc: Exception) -> bool:
    """A failure the next pipeline can retry: an infrastructure error that is not the environment's (exit 3)."""
    return isinstance(exc, L4Exit | GitError | OSError) and getattr(exc, "code", None) is not ExitCode.DOCTOR_FAILED


def _unit_of_lock_ref(ref: str) -> str | None:
    """`openspec:add-x` for `refs/l4/locks/openspec/add-x`; None for anything else (a ref name is remote content)."""
    parts = ref.removeprefix(LOCK_REF_PREFIX).split("/")
    if not ref.startswith(LOCK_REF_PREFIX) or len(parts) != 2:
        return None
    try:
        parse_unit_id(f"{parts[0]}:{parts[1]}")
    except ValueError:
        return None
    return f"{parts[0]}:{parts[1]}"


class _UnitRun:
    """This sweep's ledger file for one unit: opened at the first event, published to the lock ref at the end (and
    before the archive build, which folds the pending files)."""

    def __init__(self, sweeper: "Sweeper", snapshot: UnitSnapshot, names: UnitNames) -> None:
        s = sweeper
        ref = snapshot.ref
        self._scratch = cache_root(s.app.environ, repo=s.app.repo) / "sweeps" / ref.framework.value / ref.name
        self._pending = PendingLedger(
            s.git, lock_ref=names.lock_ref, unit=snapshot.ref.id, run_id=s.app.run_id,
            fetch_config=fetch_auth_config(s.cfg, s.app.environ), push_config=push_auth_config(s.cfg, s.app.environ),
        )  # fmt: skip
        self._open = lambda: LedgerWriter.open(
            self._scratch, snapshot.ref.id, s.app.run_id, redactor=s.app.redactor, command="plan --sweep",
            branch=names.branch, file_filter=s.urls.scrub,
            observers=[FilteredTrace(ProgressTrace(), SWEEP_TRACE_TYPES)],
        )  # fmt: skip
        self._run_id = s.app.run_id
        self._writer: LedgerWriter | None = None
        self._published = 0
        self._written = 0

    @property
    def writer(self) -> LedgerWriter:
        if self._writer is None:
            self._writer = self._open()
        return self._writer

    def event(self, event_type: str, **data: object) -> None:
        self.writer.append(event_type, **data)
        self._written += 1

    def transition(self, snapshot: UnitSnapshot, trigger: Trigger, **context: object) -> None:
        transition(self.writer, snapshot.state, trigger, **context)
        self._written += 1

    def publish(self) -> None:
        if self._written > self._published:
            self._pending.publish(ledger_path(self._scratch, self._run_id))
            self._published = self._written

    def close(self, exit_code: int) -> None:
        if self._writer is not None:
            self.publish()
            self._writer.finish(exit_code)
            self._written += 1
            self.publish()
        shutil.rmtree(self._scratch, ignore_errors=True)


def merged_elsewhere(merged_into: str, base: str) -> str:
    """The cause of an `in_review` unit whose MR was merged into another branch (L4-YOLO-007, SCN-YOLO-13)."""
    return f"merged into {merged_into}, not the base {base}"


class Sweeper:
    def __init__(
        self,
        app: AppContext,
        cfg: L4Config,
        git: Git,
        forge: Forge,
        archiver: PostMergeArchiver,
        detector: MergeDetector,
        *,
        retry: bool = False,
        ci: bool = False,
        auto_units: Collection[str] = (),
    ) -> None:
        self.app, self.cfg, self.git, self.forge = app, cfg, git, forge
        self._auto_units = frozenset(auto_units)  # the units of an active `merge: auto` plan (L4-YOLO-009)
        self._archiver, self._detector, self._retry, self._ci = archiver, detector, retry, ci
        self.urls = app_forge_urls(app, cfg)  # what a ledger commits for the forge host, and how its URLs compare
        self._key: str | None = None
        self._merged: dict[str, list[PullRequest]] | None = None
        self._open: dict[str, PullRequest] | None = None
        self._newest: dict[str, PullRequest] | None = None
        self.misdirected: dict[str, str] = {}  # unit id -> `merged into <x>, not the base <base>` (L4-YOLO-007)
        self._misdirected_prs: dict[str, tuple[int, str]] = {}  # unit id -> (the merged MR's number, where it went)

    def run(self, snapshots: Sequence[UnitSnapshot]) -> list[SweepAction]:
        candidates = [s for s in snapshots if s.state.phase in _SWEPT]
        errors: list[Exception] = []
        actions: list[SweepAction] = []
        if candidates and self._merged_mrs() is None:
            return []  # the forge could not be asked: nothing is swept this time, and `l4 run` still goes on
        for snapshot in candidates:  # one unit's failure never stops the others
            try:
                action = self._sweep(snapshot, self._own_mr(snapshot, self._merged_mrs() or {}))
            except Exception as exc:  # noqa: BLE001 - re-raised below unless the next pipeline can retry it
                self._failed(snapshot.ref.id, exc, errors)
                continue
            if action is not None:
                actions.append(action)
        try:
            actions += self._retire(snapshots, errors)
        except Exception as exc:  # noqa: BLE001 - as above
            self._failed("lock refs", exc, errors)
        if self._ci:
            try:
                actions += self._closed_duty(snapshots, errors)
            except Exception as exc:  # noqa: BLE001 - as above
                self._failed("closed merge requests", exc, errors)
            try:
                actions += self._resume_duty(snapshots, errors)
            except Exception as exc:  # noqa: BLE001 - as above
                self._failed("operator labels", exc, errors)
            try:
                actions += self._follow_up_duty(snapshots, errors)
            except Exception as exc:  # noqa: BLE001 - as above
                self._failed("follow-ups", exc, errors)
        fatal = next((e for e in errors if not _repeats_until_fixed(e)), None)
        if fatal is not None:
            raise fatal
        return actions

    def _failed(self, what: str, exc: Exception, errors: list[Exception]) -> None:
        first = (str(exc).splitlines() or [type(exc).__name__])[0]
        log.error("%s: sweep failed, tried again next time: %s", what, self.app.redactor.redact_text(first))
        errors.append(exc)

    def _merged_mrs(self) -> dict[str, list[PullRequest]] | None:
        """The merged MRs of the harness' branches by source branch, newest first; None when the forge cannot be
        asked (only a credential problem is raised: the next pipeline asks again)."""
        if self._merged is None:
            try:
                found = self.forge.list_prs(self.cfg.forge.branch_prefix, "merged")
            except ForgeAuthError:
                raise
            except ForgeError as exc:
                first = (str(exc).splitlines() or [type(exc).__name__])[0]
                log.error("the merged MRs could not be listed: %s", self.app.redactor.redact_text(first))
                return None
            self._merged = {}
            for pr in found:
                self._merged.setdefault(pr.head_branch, []).append(pr)
        return self._merged

    def _own_mr(self, snapshot: UnitSnapshot, merged: dict[str, list[PullRequest]]) -> PullRequest | None:
        """The merged MR that is this unit's: the one its ledger names, else (no `pr.updated` was recorded) the latest
        of the branch. An older MR of a branch name that was used before is not. A merged MR counts only when it was
        merged into `forge.base_branch` (L4-YOLO-007): one retargeted and merged elsewhere is logged, remembered in
        `misdirected` for the unit's cause, and the unit stays as it is."""
        branch = unit_branch(snapshot.ref.id, self.cfg.forge.branch_prefix)
        prs = merged.get(branch, [])
        wanted = snapshot.state.pr
        if wanted is None:
            found = prs[0] if prs else None
        else:
            found = next((pr for pr in prs if self.urls.canonical(pr.url) == self.urls.canonical(wanted)), None)
            if prs and found is None:
                log.info("%s: the merged MR of %s is not the unit's MR %s", snapshot.ref.id, branch, wanted)
        base = self.cfg.forge.base_branch
        if found is not None and found.base_branch != base:
            log.warning(
                "%s: %s was merged into %s, not the base %s", snapshot.ref.id, found.url, found.base_branch, base
            )
            self.misdirected[snapshot.ref.id] = merged_elsewhere(found.base_branch, base)
            self._misdirected_prs[snapshot.ref.id] = (found.number, found.base_branch)
            return None
        self.misdirected.pop(snapshot.ref.id, None)
        self._misdirected_prs.pop(snapshot.ref.id, None)
        return found

    def _retire(self, snapshots: Sequence[UnitSnapshot], errors: list[Exception]) -> list[SweepAction]:
        """Lock refs of units that are gone from the base because their archive MR merged (the folder, not a message, is
        the evidence). A unit that is still listed, or whose folder is still on the base, is never touched."""
        base = f"refs/remotes/origin/{self.cfg.forge.base_branch}"
        if self.git.rev_parse(base) is None:
            return []
        live = {s.ref.id for s in snapshots}
        fetch = fetch_auth_config(self.cfg, self.app.environ)
        listing = self.git.run("ls-remote", "origin", f"{LOCK_REF_PREFIX}*", config=fetch).stdout
        actions = []
        for line in listing.splitlines():
            sha, _, lock = line.partition("\t")
            unit_id = _unit_of_lock_ref(lock)
            if unit_id is None or unit_id in live or self._folder_on_base(base, unit_id):
                continue
            try:
                action = self._retire_one(unit_id, lock, sha)
            except Exception as exc:  # noqa: BLE001 - one lock ref's failure never stops the others
                self._failed(unit_id, exc, errors)
                continue
            if action is not None:
                actions.append(action)
        return actions

    def _folder_on_base(self, base: str, unit_id: str) -> bool:
        framework, _, name = unit_id.partition(":")
        where = self.cfg.spec.kiro.root if framework == Framework.KIRO.value else self._changes_dir
        folder = f"{base}:{where}/{name}"
        return bool(self.git.run("rev-parse", "--verify", "--quiet", folder, check=False).stdout.strip())

    def _repo_key(self) -> str:
        """The repository key of this clone, read once per sweep (the paths of every unit carry it)."""
        if self._key is None:
            self._key = repository_key(self.app.repo, self.app.environ)
        return self._key

    def _retire_one(self, unit_id: str, lock: str, sha: str) -> SweepAction | None:
        names = UnitNames.for_unit(
            unit_id, branch_prefix=self.cfg.forge.branch_prefix, cache=cache_root(self.app.environ, repo=self.app.repo),
            repo_key=self._repo_key(),
        )  # fmt: skip
        merged = self._merged_mrs()
        if not merged or not merged.get(names.archive_branch):
            return None  # the archive MR is open, closed or never was: the lock ref is still the unit's
        self.git.fetch("origin", refspecs=(f"+{lock}:{lock}",), config=fetch_auth_config(self.cfg, self.app.environ))
        phases = [e for e in read_pending(self.git, lock).events if e.type == "phase.changed"]
        if not phases or phases[-1].data.get("to") != Phase.MERGED.value:
            return None
        lease = LocalFileLease(names.flock_path, unit=unit_id, run_id=self.app.run_id)
        try:
            lease.acquire()
        except Busy:
            return None
        try:
            archived = f"refs/l4/archived/{unit_id.replace(':', '/')}/{self.app.run_id}"
            try:
                self.git.retire_lock_ref(
                    "origin", sha, lock, archived, config=push_auth_config(self.cfg, self.app.environ)
                )
            except PushRejected:
                log.info("%s: the lock ref moved, not retired this time", unit_id)
                return None
            self.git.run("update-ref", archived, sha)
            self.git.run("update-ref", "-d", lock)
            log.info("%s: lock ref retired to %s", unit_id, archived)
            return SweepAction(unit_id, "retired", archived)
        finally:
            lease.release()

    def _inputs(self, ref: UnitRef) -> dict[str, str]:
        """What an archive of the unit is built from, as this clone sees it: the base head and the unit's folder. A Kiro
        unit's done-gate reads the folder alone, so unrelated work landing on the base does not repeat its verdict."""
        base = f"refs/remotes/origin/{self.cfg.forge.base_branch}"
        kiro = ref.framework is Framework.KIRO
        folder = f"{base}:{self.cfg.spec.kiro.root}/{ref.name}" if kiro else f"{base}:{self._changes_dir}/{ref.name}"
        found = {
            "base": None if kiro else self.git.rev_parse(base),
            "tree": self.git.run("rev-parse", "--verify", "--quiet", folder, check=False).stdout.strip() or None,
        }
        return {key: value for key, value in found.items() if value}

    @property
    def _changes_dir(self) -> str:
        return f"{self.cfg.spec.openspec.root}/changes"

    def _sweep(self, snapshot: UnitSnapshot, pr: PullRequest | None) -> SweepAction | None:
        ref = snapshot.ref
        if snapshot.state.phase == Phase.IN_REVIEW.value and pr is None:
            noted = self._note_misdirected(snapshot)
            ci = self._ci_duty(snapshot) if self._ci else None  # the MR is open (or closed): the merge duty is idle
            return noted or ci
        names = self._archiver.names(ref)
        failure = self._unresolved_failure(names)
        if (
            failure is not None
            and not self._retry
            and all(failure.data.get(k) == v for k, v in self._inputs(ref).items())
        ):
            log.info("%s: the archive failed earlier on these inputs (see its pending ledger); not tried again", ref.id)
            return SweepAction(ref.id, "skipped", "archive.failed is recorded")
        lease = LocalFileLease(names.flock_path, unit=ref.id, run_id=self.app.run_id)
        try:
            lease.acquire()
        except Busy as busy:
            log.info("%s: locked by another run, skipped: %s", ref.id, busy)
            return SweepAction(ref.id, "skipped", "locked")
        run = _UnitRun(self, snapshot, names)
        code = 1
        try:
            action = self._duty(snapshot, pr, run)
            code = 0
            return action
        finally:
            try:
                run.close(code)
            finally:
                lease.release()

    def _note_misdirected(self, snapshot: UnitSnapshot) -> SweepAction | None:
        """`pr.misdirected{pr, merged_into, base}` once per merged MR (L4-YOLO-007, SCN-YOLO-13): the pending ledger
        carries the cause that `l4 status --unit` shows; the unit's phase does not change."""
        found = self._misdirected_prs.get(snapshot.ref.id)
        if found is None:
            return None
        number, merged_into = found
        known = snapshot.state.misdirected
        if known is not None and str(known.pr) == str(number) and known.merged_into == merged_into:
            return None
        base = self.cfg.forge.base_branch
        fields: dict[str, object] = {"pr": number, "merged_into": merged_into, "base": base}
        action = SweepAction(snapshot.ref.id, "misdirected", merged_elsewhere(merged_into, base))
        return self._record_ci(snapshot, "pr.misdirected", fields, action)

    # --- feedback on a merged unit (L4-FBK-010) -------------------------------------------------------------------

    def _follow_up_duty(self, snapshots: Sequence[UnitSnapshot], errors: list[Exception]) -> list[SweepAction]:
        """A merged unit whose `feedback.md` on the base has takeable items gets its follow-up unit (a branch of its
        own; nothing is pushed to the base). While one is open, newer items are recorded as waiting, once each."""
        actions: list[SweepAction] = []
        merged = [s for s in snapshots if s.state.phase == Phase.MERGED.value and s.follow_up and s.follow_up.items]
        for made in perform_follow_ups(self.app, self.cfg, self.git, merged):
            actions.append(SweepAction(made.parent, "follow_up", f"{made.follow_up} for {', '.join(made.items)}"))
        for snapshot in merged:
            offer = snapshot.follow_up
            assert offer is not None
            if offer.open is None:
                continue
            ids = [
                i.id for i in offer.items
                if (known := snapshot.state.feedback.get(i.id)) is None
                or (known.status, known.reason) != ("waiting", "follow_up_open")
            ]  # fmt: skip
            if not ids:
                continue
            try:
                if (action := self._record_waiting(snapshot, ids, offer.open)) is not None:
                    actions.append(action)
            except Exception as exc:  # noqa: BLE001 - one unit's failure never stops the others
                self._failed(snapshot.ref.id, exc, errors)
        return actions

    def _record_waiting(self, snapshot: UnitSnapshot, ids: list[str], follow_up: str) -> SweepAction | None:
        """`feedback.waiting{ids, reason: "follow_up_open"}` in the pending ledger of the parent's lock ref. An
        archived change has no lock ref any more (it was retired): the planner still says it waits, and nothing is
        written."""
        names = self._archiver.names(snapshot.ref)
        if self.git.rev_parse(names.lock_ref) is None:
            return None
        lease = LocalFileLease(names.flock_path, unit=snapshot.ref.id, run_id=self.app.run_id)
        try:
            lease.acquire()
        except Busy:
            return None
        run = _UnitRun(self, snapshot, names)
        code = 1
        try:
            run.event("feedback.waiting", ids=ids, reason="follow_up_open", follow_up=follow_up)
            code = 0
            return SweepAction(snapshot.ref.id, "follow_up_waiting", f"{', '.join(ids)} wait for {follow_up}")
        finally:
            try:
                run.close(code)
            finally:
                lease.release()

    # --- a merge request closed without a merge (L4-OPS-009) -------------------------------------------------------

    def _newest_mrs(self) -> dict[str, PullRequest] | None:
        """The newest MR (any state) of each of the harness' branches by source branch: one listing per sweep. None when
        the forge cannot be asked (only a credential problem is raised)."""
        if self._newest is None:
            try:
                found = self.forge.list_prs(self.cfg.forge.branch_prefix, "all")
            except ForgeAuthError:
                raise
            except ForgeError as exc:
                first = (str(exc).splitlines() or [type(exc).__name__])[0]
                log.error("the MRs could not be listed: %s", self.app.redactor.redact_text(first))
                return None
            self._newest = {}
            for pr in sorted(found, key=lambda p: p.number):
                self._newest[pr.head_branch] = pr
        return self._newest

    def _units_mr(self, snapshot: UnitSnapshot, newest: dict[str, PullRequest]) -> PullRequest | None:
        """The newest MR of the unit's branch, when it is the unit's: the one its ledger names, else (none was
        recorded) the newest of a unit that was never started over. After a restart the old MR is closed and the unit
        has none yet: that MR says nothing about the new work."""
        pr = newest.get(unit_branch(snapshot.ref.id, self.cfg.forge.branch_prefix))
        if pr is None:
            return None
        wanted = snapshot.state.pr
        if wanted is None:
            return pr if snapshot.state.restarts == 0 else None
        return pr if self.urls.canonical(pr.url) == self.urls.canonical(wanted) else None

    def _closed_duty(self, snapshots: Sequence[UnitSnapshot], errors: list[Exception]) -> list[SweepAction]:
        live = [s for s in snapshots if s.state.phase is not None and s.state.phase not in _ENDED]
        newest = self._newest_mrs() if live else None
        if newest is None:
            return []
        actions = []
        for snapshot in live:
            pr = self._units_mr(snapshot, newest)
            abandoned = snapshot.state.phase == Phase.ABANDONED.value
            if pr is None or (pr.state, abandoned) not in (("closed", False), ("open", True)):
                continue
            try:
                action = self._close_or_reopen(snapshot, pr)
            except Exception as exc:  # noqa: BLE001 - one unit's failure never stops the others
                self._failed(snapshot.ref.id, exc, errors)
                continue
            if action is not None:
                actions.append(action)
        return actions

    def _close_or_reopen(self, snapshot: UnitSnapshot, pr: PullRequest) -> SweepAction | None:
        """`pr.closed{number}` and `pr_closed`, or `pr_reopened`, in the pending ledger under the unit's lease; the
        snapshot follows, so the label duty of the same sweep sees the new phase."""
        ref, state = snapshot.ref, snapshot.state
        closing = pr.state == "closed"
        names = self._archiver.names(ref)
        lease = LocalFileLease(names.flock_path, unit=ref.id, run_id=self.app.run_id)
        try:
            lease.acquire()
        except Busy as busy:
            log.info("%s: locked by another run, the MR state is recorded next time: %s", ref.id, busy)
            return None
        run = _UnitRun(self, snapshot, names)
        code = 1
        was = state.phase
        try:
            if closing:
                run.event("pr.closed", number=pr.number)
                run.transition(snapshot, Trigger.PR_CLOSED, pr=pr.number)
            else:
                run.transition(snapshot, Trigger.PR_REOPENED, pr=pr.number)
            run.publish()
            code = 0
        finally:
            try:
                run.close(code)
            finally:
                lease.release()
        if closing:
            state.previous_phase, state.phase = was, Phase.ABANDONED.value
            log.warning("%s: MR !%s was closed without a merge: abandoned; l4 restart starts the unit over", ref.id,
                        pr.number)  # fmt: skip
            self._note(snapshot, pr, abandoned_section(ref.id, f"{self.cfg.forge.labels_prefix}restart"))
            return SweepAction(ref.id, "abandoned", f"MR !{pr.number} was closed without a merge")
        state.phase, state.previous_phase = state.previous_phase, None
        log.info("%s: MR !%s is open again: back in %s", ref.id, pr.number, state.phase)
        return SweepAction(ref.id, "reopened", f"MR !{pr.number} is open again: back in {state.phase}")

    def _note(self, snapshot: UnitSnapshot, pr: PullRequest, body: str) -> None:
        try:
            self.forge.upsert_sticky_note(pr.number, body)
        except ForgeAuthError:
            raise
        except ForgeError as exc:  # the note is a courtesy: the ledger carries the phase
            log.warning("%s: the sticky note could not be written: %s", snapshot.ref.id,
                        self.app.redactor.redact_text(str(exc)))  # fmt: skip

    # --- the operator labels `retry`, `resume` and `restart` (M1.11, L4-CI-004, L4-SEC-004, L4-OPS-008) --------------

    def _resume_duty(self, snapshots: Sequence[UnitSnapshot], errors: list[Exception]) -> list[SweepAction]:
        held = [  # a merged unit too: a label on its MR is refused with the command that works (L4-OPS-008)
            s for s in snapshots
            if s.state.phase is not None and (s.state.phase not in _ENDED or s.state.phase == Phase.MERGED.value)
        ]  # fmt: skip
        if not held:
            return []
        newest = self._newest_mrs()
        if newest is None:
            return []
        actions = []
        for snapshot in held:
            try:
                action = self._resume_one(snapshot, newest)
            except Exception as exc:  # noqa: BLE001 - one unit's failure never stops the others
                self._failed(snapshot.ref.id, exc, errors)
                continue
            if action is not None:
                actions.append(action)
        return actions

    def _resume_one(self, snapshot: UnitSnapshot, newest: dict[str, PullRequest]) -> SweepAction | None:
        ref, state = snapshot.ref, snapshot.state
        prefix = self.cfg.forge.labels_prefix
        retry, resume, restart = f"{prefix}retry", f"{prefix}resume", f"{prefix}restart"
        pr = newest.get(unit_branch(ref.id, self.cfg.forge.branch_prefix))
        abandoned = state.phase == Phase.ABANDONED.value
        # retry: where a retry continues, on the open MR; restart: any started unit on its open MR, and an abandoned
        # unit on its closed one
        reads = {
            retry: pr is not None and pr.state == "open" and state.phase in _RETRIED,
            resume: pr is not None and pr.state == "open" and state.phase in _RETRIED,
            restart: pr is not None and (pr.state == "open" or (abandoned and pr.state == "closed")),
        }
        if pr is None or not any(label in pr.labels for label in (retry, resume, restart)):
            return self._push_hint(snapshot, retry) if state.phase == Phase.HALTED.value else None
        try:
            events = self.forge.label_events(pr.number)
            own_id = self.forge.own_user_id()
            decisions = {}
            for label, read in reads.items():
                why = self._cannot_act(ref.id, state.phase, label)
                if not read and why is None:
                    continue
                decision = resume_signal(
                    pr.labels, events, label=label, own_id=own_id, access=self.forge.member_access,
                    consumed={*state.resumed_signals, *state.refused_signals}, unit=ref.id,
                    command="l4 restart" if label == restart else "l4 retry",
                )  # fmt: skip
                if decision is not None and why is not None:  # whoever set it, it cannot act here
                    decision = Refusal(decision.event_id, decision.signal, why)
                if decision is not None:
                    decisions[label] = decision
        except ForgeAuthError:
            raise
        except ForgeError as exc:  # not a refusal: the forge could not say, and the next sweep asks again
            first = (str(exc).splitlines() or [type(exc).__name__])[0]
            log.error(
                "%s: who set the operator label could not be read: %s", ref.id, self.app.redactor.redact_text(first)
            )
            return None
        signals = {label: d for label, d in decisions.items() if isinstance(d, ResumeSignal)}
        winner = max(signals, key=lambda label: signals[label].event_id, default=None)
        acted: SweepAction | None = None
        for label, decision in sorted(decisions.items(), key=lambda item: item[1].event_id):
            if isinstance(decision, Refusal):
                self._refuse(snapshot, pr, decision, label)
                acted = SweepAction(ref.id, "resume_refused", f"{decision.signal}: {decision.why}")
            elif label != winner:
                superseded = Refusal(
                    decision.event_id, decision.signal, "a newer operator label on this merge request acts instead"
                )
                self._refuse(snapshot, pr, superseded, label)
        if winner is None:
            return acted
        signal = signals[winner]
        if winner == restart:
            restarted = self._restart_in_worktree(snapshot, signal, winner)
            log.info("%s: started over by a member's %s label (event %d): attempt %s", ref.id, winner, signal.event_id,
                     restarted.attempt)  # fmt: skip
            return SweepAction(ref.id, "restarted", f"{signal.signal}: started over, attempt {restarted.attempt}")
        result = self._retry_in_worktree(snapshot, signal, winner)
        log.info("%s: retried by a member's %s label (event %d)", ref.id, winner, signal.event_id)
        return SweepAction(ref.id, "resumed", f"{signal.signal}: back in {result.outcome.phase_after}")

    def _cannot_act(self, unit: str, phase: str | None, label: str) -> str | None:
        """Why an operator label cannot act on a unit in `phase`, naming what works (L4-OPS-008); None where it acts:
        `retry` and `resume` on `in_review`, `merged` and `abandoned`, and `restart` on `merged`."""
        prefix = self.cfg.forge.labels_prefix
        kind = label.removeprefix(prefix)
        run = f"l4 retry --unit {unit} --reason TEXT"
        if phase == Phase.MERGED.value:
            what = "a merged change gets a follow-up unit" if kind == "restart" else "the unit is merged"
            return f"the label {label} does nothing: {what}; use {run} to run the archive or the done-gate again"
        if kind in ("retry", "resume") and phase == Phase.IN_REVIEW.value:
            return f"the label {label} does nothing while the unit is in review; use {run}"
        if kind in ("retry", "resume") and phase == Phase.ABANDONED.value:
            return (
                f"the label {label} does nothing on an abandoned unit; add the label {prefix}restart, "
                f"or use l4 restart --unit {unit} --reason TEXT"
            )
        return None

    def _push_hint(self, snapshot: UnitSnapshot, label: str) -> SweepAction | None:
        """A person pushed to a halted branch (a task edit, say): nothing retries it but the label or `l4 retry`, so
        say so, once per branch head (`resume.hint{head}` in the pending ledger)."""
        if snapshot.spec_edit is not None:  # a spec edit re-enters the unit by itself at the next run (L4-OPS-014)
            return None
        ref = snapshot.ref
        head = self.git.rev_parse(f"refs/remotes/origin/{unit_branch(ref.id, self.cfg.forge.branch_prefix)}")
        if head is None or head in snapshot.state.hinted_heads or not foreign_tail(self.git, head, strict=False):
            return None
        names = self._archiver.names(ref)
        lease = LocalFileLease(names.flock_path, unit=ref.id, run_id=self.app.run_id)
        try:
            lease.acquire()
        except Busy as busy:
            log.info("%s: locked by another run, the hint is said next time: %s", ref.id, busy)
            return None
        run = _UnitRun(self, snapshot, names)
        code = 1
        try:
            run.event("resume.hint", head=head)
            run.publish()
            code = 0
        finally:
            try:
                run.close(code)
            finally:
                lease.release()
        log.warning("%s: halted; a person pushed after the halt: add the label %s or run l4 retry", ref.id, label)
        return SweepAction(ref.id, "resume_hint", f"head {head[:10]}")

    def _retry_in_worktree(self, snapshot: UnitSnapshot, signal: ResumeSignal, label: str) -> "UnitRunResult":
        from l4.state.retry import retry_unit  # the orchestrator imports the planner, which imports this module

        provider = provider_for_unit(providers_for(self.cfg, self.app.repo, self.app.environ), snapshot.ref.id)
        return retry_unit(
            self.app, self.cfg, self.git, provider, snapshot.ref, reason=f"label {label}", signal=signal.signal,
            by="member", rounds=None,
        )  # fmt: skip

    def _restart_in_worktree(self, snapshot: UnitSnapshot, signal: ResumeSignal, label: str) -> "RestartResult":
        from l4.state.restart import restart_unit

        provider = provider_for_unit(providers_for(self.cfg, self.app.repo, self.app.environ), snapshot.ref.id)
        return restart_unit(
            self.app, self.cfg, self.git, provider, snapshot.ref, reason=f"label {label}", signal=signal.signal,
            by="member",
        )  # fmt: skip

    def _refuse(self, snapshot: UnitSnapshot, pr: PullRequest, refusal: Refusal, label: str) -> None:
        """Said once per label event: a warning line, `resume.refused` in the pending ledger and a section of the MR's
        sticky note."""
        ref = snapshot.ref
        names = self._archiver.names(ref)
        lease = LocalFileLease(names.flock_path, unit=ref.id, run_id=self.app.run_id)
        try:
            lease.acquire()
        except Busy as busy:
            log.info("%s: locked by another run, the refusal is said next time: %s", ref.id, busy)
            return
        run = _UnitRun(self, snapshot, names)
        code = 1
        try:
            run.event("resume.refused", signal=refusal.signal, why=refusal.why)
            run.publish()
            code = 0
        finally:
            try:
                run.close(code)
            finally:
                lease.release()
        log.warning("%s: the %s label (event %d) was not honoured: %s", ref.id, label, refusal.event_id, refusal.why)
        snapshot.state.refused_signals[refusal.signal] = refusal.why  # a later label of the same sweep sees it
        state = snapshot.state
        if state.phase in (Phase.HALTED.value, Phase.ESCALATED.value):
            stopped = halted_section(
                state.phase,
                state.halt_detail or state.halt_reason or "see the ledger",
                ref.id,
                retry_label(f"{self.cfg.forge.labels_prefix}resume"),
                feedback=feedback_rounds_exhausted(state),
                reason_code=state.halt_reason,
            )  # the halting run's section stays: the note is rewritten whole
        elif state.phase == Phase.ABANDONED.value:
            stopped = abandoned_section(ref.id, f"{self.cfg.forge.labels_prefix}restart")
        else:
            stopped = None
        body = "\n\n".join(part for part in (stopped, resume_refused_note(state.refused_signals)) if part)
        self._note(snapshot, pr, body)

    # --- the project's own CI on H -------------------------------------------------------------------------------

    def _open_mrs(self) -> dict[str, PullRequest] | None:
        """The open MRs of the harness' branches by source branch: one listing per sweep. None when the forge cannot be
        asked (only a credential problem is raised)."""
        if self._open is None:
            try:
                found = self.forge.list_prs(self.cfg.forge.branch_prefix, "open")
            except ForgeAuthError:
                raise
            except ForgeError as exc:
                first = (str(exc).splitlines() or [type(exc).__name__])[0]
                log.error("the open MRs could not be listed: %s", self.app.redactor.redact_text(first))
                return None
            self._open = {pr.head_branch: pr for pr in found}
        return self._open

    def _ci_duty(self, snapshot: UnitSnapshot) -> SweepAction | None:
        review, state = snapshot.review, snapshot.state
        if review is None or review.handoff is None or not review.at_handoff:
            return None  # no H, or the branch is past it: a person's commit supersedes H's pipeline, `l4 run` takes it
        head, short = review.handoff, review.handoff[:10]
        if (known := state.ci_heads.get(head)) is not None:
            names = ", ".join(str(j.get("name")) for j in state.ci_failure.jobs) if state.ci_failure else ""
            if known == "failed" and state.ci_failure and state.ci_failure.head == head:
                return SweepAction(snapshot.ref.id, "ci_failed", f"H {short} red: {names} (already recorded)")
            return SweepAction(snapshot.ref.id, "ci_preexisting", f"H {short} red as on the base (already recorded)")
        branch = unit_branch(snapshot.ref.id, self.cfg.forge.branch_prefix)
        open_mrs = self._open_mrs()
        if open_mrs is None or branch not in open_mrs:
            return None
        try:
            platform = forge_platform(self.cfg, self.app.environ, origin_url(self.app.repo, self.app.environ))
            base = self.git.rev_parse(f"refs/remotes/origin/{self.cfg.forge.base_branch}")
            read = read_handoff_ci(self.forge, head, base, platform)  # the reader the guarded merge uses too
            if read.status == "running":
                return SweepAction(
                    snapshot.ref.id, "ci_waiting", f"H {short} running" + (f" ({read.reason})" if read.reason else "")
                )
            if read.status == "not_run":
                return SweepAction(snapshot.ref.id, "ci_not_run", f"H {short}: {read.reason}")
            if read.status == "green":
                return SweepAction(snapshot.ref.id, "ci_green", f"H {short} green")
            logs = {j.job_id: self._log(j) for j in read.failed[:MAX_TAILS]}
        except ForgeError as exc:  # a 401/403 too: the token may lack only this read (GitHub check runs), and the MR
            # listing above already raised if it is broken outright; a CI read never stops the sweep or `l4 run`
            first = (str(exc).splitlines() or [type(exc).__name__])[0]
            log.error("%s: CI of %s could not be read, tried again next time: %s", snapshot.ref.id, short,
                      self.app.redactor.redact_text(first))  # fmt: skip
            return None
        listed = []
        for j in read.failed:
            entry = {
                "name": j.key,
                "stage": j.stage,
                "url": j.web_url,
                "tail": logs.get(j.job_id, JobLog()).tail,
                "step": logs.get(j.job_id, JobLog()).step,
            }
            if j.workflow:
                entry |= {"workflow": j.workflow, "event": j.event}
            listed.append(entry)
        if read.status == "failed":
            fields = {"head": head, "pipeline": read.failed[0].pipeline_id, "jobs": listed,
                      "preexisting": [j.key for j in read.preexisting]}  # fmt: skip
            action = SweepAction(
                snapshot.ref.id, "ci_failed", f"H {short} red: {', '.join(j.key for j in read.failed)} (recorded)"
            )
            event = "ci.failed"
        else:
            names = [j.key for j in read.preexisting]
            fields = {"head": head, "pipeline": read.preexisting[0].pipeline_id, "jobs": names}
            action = SweepAction(snapshot.ref.id, "ci_preexisting", f"H {short} red as on the base: {', '.join(names)}")
            event = "ci.preexisting"
        return self._record_ci(snapshot, event, fields, action)

    def _log(self, job: JobResult) -> JobLog:
        """The end of a failed job's log and the command its step ran last, both redacted and clipped: a secret in a
        log never reaches the ledger. The step is cut after redaction, so a token is never split by the cut."""
        if job.job_id is None:
            return JobLog()
        try:
            log_ = self.forge.job_log(job.job_id, MAX_TAIL_LINES)
        except ForgeError:  # a forbidden log too: no evidence, but the finding still names the job and its URL
            return JobLog()
        step = self.app.redactor.redact_text(log_.step)[:MAX_STEP_CHARS] if log_.step else None
        return JobLog(self.app.redactor.redact_text(log_.tail)[-MAX_TAIL_CHARS:], step)

    def _record_ci(self, snapshot: UnitSnapshot, event: str, fields: dict[str, object], action: SweepAction):
        names = self._archiver.names(snapshot.ref)
        lease = LocalFileLease(names.flock_path, unit=snapshot.ref.id, run_id=self.app.run_id)
        try:
            lease.acquire()
        except Busy as busy:
            log.info("%s: locked by another run, CI not recorded: %s", snapshot.ref.id, busy)
            return SweepAction(snapshot.ref.id, "skipped", "locked")
        run = _UnitRun(self, snapshot, names)
        code = 1
        try:
            run.event(event, **fields)
            run.publish()
            code = 0
            return action
        finally:
            try:
                run.close(code)
            finally:
                lease.release()

    def _unresolved_failure(self, names: UnitNames) -> LedgerEvent | None:
        """The last `archive.failed` of the unit, unless an archive MR was opened (or the done-gate passed) after it."""
        last = None
        for event in read_pending(self.git, names.lock_ref).events:
            if event.type in ("archive.failed", "archive.opened", "archive.done"):
                last = event
        return last if last is not None and last.type == "archive.failed" else None

    def _done_recorded(self, names: UnitNames) -> bool:
        """The unit's done-gate passed on an earlier sweep (`archive.done` in its pending ledger)."""
        return any(e.type == "archive.done" for e in read_pending(self.git, names.lock_ref).events)

    def _duty(self, snapshot: UnitSnapshot, pr: PullRequest | None, run: _UnitRun) -> SweepAction:
        ref = snapshot.ref
        recorded = False
        if snapshot.state.phase == Phase.IN_REVIEW.value:
            assert pr is not None
            verdict = self._detector.classify(pr, ref.name, ref.framework.value)
            if verdict is MergeVerdict.UNKNOWN:
                return SweepAction(ref.id, "skipped", f"MR !{pr.number}: the merge commit is not in this clone")
            run.transition(snapshot, Trigger.PR_MERGED, pr=pr.number, merge_commit=pr.merge_commit_sha)
            run.publish()  # the archive build folds the pending files: they must hold this event
            recorded = True
            log.info("%s: MR !%s merged", ref.id, pr.number)
            if verdict is MergeVerdict.ARCHIVED:
                what = "spec folder" if ref.framework is Framework.KIRO else "change folder"
                return SweepAction(ref.id, "merged", f"MR !{pr.number}: the merged tree holds no {what}")
        kiro = ref.framework is Framework.KIRO
        if kiro and self._done_recorded(self._archiver.names(ref)):
            log.info("%s: the done-gate passed earlier (archive.done is recorded)", ref.id)
            return SweepAction(ref.id, "merged" if recorded else "skipped", "archive.done is recorded")
        try:
            result = (
                self._archiver.check_done(ref)
                if kiro
                else self._archiver.open_archive_pr(ref, iteration=snapshot.state.iteration)
            )
        except Exception as exc:  # noqa: BLE001 - only a definitive refusal is recorded, the rest is raised
            reason = definitive_reason(exc)
            if reason is None:
                raise
            result = ArchiveResult("failed", detail=reason)
        return self._record(ref, result, run, recorded, pr)

    def _done_gate_note(self, ref: UnitRef, pr: PullRequest, why: str) -> None:
        """A merged Kiro unit whose done-gate refused: said on the MR, once (the failure is recorded, so the sweep does
        not try again until the unit's folder changes)."""
        reason = self.app.redactor.redact_text(why)
        body = "\n".join(
            [
                "### The Kiro done-gate did not pass after the merge",
                "",
                reason,
                "",
                "Kiro has no archive step: the harness checks that every required task of the merged unit is `[x]`. "
                f"Finish the open task(s) in `{self.cfg.spec.kiro.root}/{ref.name}/tasks.md` on "
                f"`{self.cfg.forge.base_branch}`; the next sweep checks again when that folder changes.",
            ]
        )
        try:
            self.forge.upsert_sticky_note(pr.number, body)
        except ForgeAuthError:
            raise
        except ForgeError as exc:  # the note is a courtesy: `archive.failed` in the ledger carries the verdict
            log.warning("%s: the sticky note could not be written: %s", ref.id, self.app.redactor.redact_text(str(exc)))

    def _merge_archive(self, ref: UnitRef, pr: PullRequest, run: _UnitRun) -> SweepAction:
        """The archive MR of a unit of an active `merge: auto` plan is merged by the harness: its branch is pushed to
        the base as a fast-forward under the same guard as a unit merge (`merge_archive_guarded`, L4-YOLO-009,
        SCN-YOLO-19).
        `archive.merged{head}` on success, `archive.failed{reason}` on any refusal (the MR stays for a person); the
        plan does not wait for it."""
        unit, branch = ref.id, pr.head_branch
        fetch = fetch_auth_config(self.cfg, self.app.environ)
        self.git.fetch("origin", refspecs=(f"+refs/heads/{branch}:refs/remotes/origin/{branch}",), config=fetch)
        head = self.git.rev_parse(f"refs/remotes/origin/{branch}")
        if head is None:
            outcome_text = f"the archive branch {branch} is not on origin"
        else:
            outcome = merge_archive_guarded(self.app, self.cfg, self.git, head, self.cfg.forge.base_branch, pr=pr)
            outcome_text = "" if outcome.status == "merged" else f"{outcome.status}: {outcome.detail}"
        if not outcome_text:
            run.event("archive.merged", head=head, number=pr.number)
            log.info("%s: archive MR !%s merged by the harness (fast-forward to %s)", unit, pr.number, str(head)[:10])
            self._delete_archive_branch(unit, pr, branch, str(head))
            return SweepAction(unit, "archive_merged", pr.url)
        reason = self.app.redactor.redact_text(outcome_text)[:500]
        run.event("archive.failed", reason=reason, **self._inputs(ref))
        log.warning("%s: archive MR !%s was not merged by the harness: %s", unit, pr.number, reason)
        return SweepAction(unit, "archive_failed", reason)

    def _delete_archive_branch(self, unit: str, pr: PullRequest, branch: str, head: str) -> None:
        """After `archive.merged`, with `yolo.merge.delete_branches` on (squash-and-delete D8, L4-YOLO-033): the archive
        branch is deleted under a lease on the head that was merged, once the forge shows the MR merged (an open MR
        whose branch is deleted is closed on GitHub). A forge that has not caught up, or a lease that fails, leaves the
        branch; the plan step deletes it later (D7). Never an error: the archive is merged."""
        if not self.cfg.yolo.merge.delete_branches:
            return
        try:
            if self.forge.get_pr(pr.number).state != "merged":
                log.info("%s: archive MR !%s is not shown as merged yet: %s stays for now", unit, pr.number, branch)
                return
            done = tidy_archive_branch(self.app, self.cfg, self.git, unit, branch, head)
        except ForgeAuthError:
            raise
        except ForgeError as exc:
            log.info("%s: the archive branch is not deleted yet: %s", unit, self.app.redactor.redact_text(str(exc)))
            return
        if done is not None:
            kind, data = done
            what = "deleted" if kind == "unit.branch_deleted" else f"kept ({data.get('reason')})"
            log.info("%s: archive branch %s %s", unit, branch, what)

    def _record(
        self, ref: UnitRef, result: ArchiveResult, run: _UnitRun, recorded: bool, pr: PullRequest | None = None
    ) -> SweepAction:
        unit = ref.id
        if result.status == "done":
            run.event("archive.done", via="done_gate", base=result.base)
            log.info("%s: %s; no archive MR (Kiro has no archive folder)", unit, result.detail)
            return SweepAction(unit, "done", result.detail)
        if result.status == "opened" and result.pr is not None:
            run.event("archive.opened", number=result.pr.number, url=result.pr.url, branch=result.pr.head_branch)
            log.info("%s: archive MR !%s opened: %s", unit, result.pr.number, result.pr.url)
            if unit in self._auto_units:
                return self._merge_archive(ref, result.pr, run)
            return SweepAction(unit, "archive_opened", result.pr.url)
        if result.status == "failed":
            run.event("archive.failed", reason=self.app.redactor.redact_text(result.detail)[:500], **self._inputs(ref))
            if ref.framework is Framework.KIRO and pr is not None:
                self._done_gate_note(ref, pr, result.detail)
            return SweepAction(unit, "archive_failed", result.detail)
        if result.status == "existing" and result.pr is not None:
            log.info("%s: archive MR !%s is open", unit, result.pr.number)
            if unit in self._auto_units:
                return self._merge_archive(ref, result.pr, run)
            return SweepAction(unit, "archive_existing", result.pr.url)
        if result.status == "pending":
            log.info("%s: archive pending: %s", unit, result.detail)
            return SweepAction(unit, "archive_pending", result.detail)
        log.info("%s: %s", unit, result.detail or result.status)
        return SweepAction(unit, "merged" if recorded else "skipped", result.detail)


def sweep(
    app: AppContext, cfg: L4Config, git: Git, snapshots: Sequence[UnitSnapshot], *, retry: bool = False,
    ci: bool = False,
) -> list[SweepAction]:  # fmt: skip
    """The sweep of `l4 plan --sweep` (`ci`: with the CI duty on H, which `l4 archive` does not do). In CI a missing
    forge token is exit 3 (before anything is written); outside CI with no forge there is nothing to look at."""
    require_token_in_ci(cfg, app.environ)
    try:
        forge = make_forge(cfg, app.environ, repo=app.repo)  # outside CI the project comes from `origin` (L4-OPS-011)
    except ForgeUnavailable as exc:
        log.warning("sweep skipped: %s", exc)
        return []
    strip_remote_credentials(git)  # as `forge_hook` does: a git error below must not print the runner's job token
    fetch = fetch_auth_config(cfg, app.environ)
    archiver = PostMergeArchiver(cfg, app, git, forge, fetch_config=fetch)
    detector = MergeDetector(
        git,
        base_branch=cfg.forge.base_branch,
        changes_dir=f"{cfg.spec.openspec.root}/changes",
        kiro_root=cfg.spec.kiro.root,
        fetch_config=fetch,
    )
    from l4.yolo.cycle import auto_plan_units  # the plan step imports the sweeper's neighbours: read at call time

    auto = auto_plan_units(app, cfg, git)
    return Sweeper(app, cfg, git, forge, archiver, detector, retry=retry, ci=ci, auto_units=auto).run(snapshots)
