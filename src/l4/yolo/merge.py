"""The guarded merge of a plan unit (design D8, L4-YOLO-008; squash-and-delete D3, L4-YOLO-032): the harness lands a
verified unit on the target branch, by default as one squash commit made by the forge's own merge call pinned to the
recorded hand-off commit H (`yolo.merge.method: squash`), or with one fast-forward push of H (`fast-forward`), never
forced. H is the sha that `pr.ready{head}` recorded (L4-YOLO-040), never a branch tip the merge read.

`merge_guarded` checks the preconditions in order (the unit is `in_review` with a PASS, no question and no feedback
open; no commit after H; H is recorded and is the branch head; no red CI recorded on H; the PR exists, is open and is
aimed at the target; H equals the `ls-remote` tip of the unit branch and, when the forge shows it, the PR head sha
(R5); the repository's CI on H allows the merge (L4-YOLO-042); the target tip is an ancestor of H). Each failure is
`not_ready` (or `stale` for the last) and pushes nothing. Then, when the caller gave a `before_push` callback, it is
called with the outcome-to-be and a False answer pushes nothing (`not_ready`, "the plan no longer allows the merge":
the plan step records `unit.merge_requested` there, under its lease, R5). Then, with `fast-forward`, it pushes
`<head>:refs/heads/<target>`. The freshness of head and base is enforced by the git server, not by the read before the
push: a target that moved in between is refused as a non-fast-forward and is `stale`; any other refusal (a protected
branch, a push rule, a permission) is `refused` and carries the forge's message, redacted. With `squash` it calls
`Forge.merge_pr(pr, sha=head, ...)`: the forge answers `head_moved` (`not_ready`, the next run reads again) or
`refused`, or merges. That call has no guard on the target, so the landed commit is compared with what was read: its
parent is the tip read and its tree is the head's tree, else `MergeOutcome.raced` is set and the post-merge check
(L4-YOLO-009) of the landed commit decides.

The function writes no ledger: the caller records `unit.merge_requested` and `unit.merged`. `confirm_merged` asks
whether the target holds the landed commit (it is the tip, or an ancestor of it when the target moved on after the
merge) and waits, best effort, for the forge to mark the PR merged.
`guarded_push` is the push guard alone, shared with the archive branch (`postmerge.merge_archive_guarded`).
"""

import logging
import re
import time
from collections.abc import Callable
from dataclasses import replace

from l4.ci.handoff_ci import read_handoff_ci
from l4.config.schema import L4Config
from l4.context import AppContext
from l4.forge.base import (
    Forge,
    ForgeAuthError,
    ForgeError,
    ForgeUnavailable,
    PullRequest,
    fetch_auth_config,
    forge_platform,
)
from l4.forge.gitlab import push_auth_config
from l4.forge.urls import origin_url
from l4.state.feedback_view import item_views
from l4.state.status import UnitSnapshot
from l4.vcs.authorship import SHA, commit_records, is_harness_strict
from l4.vcs.errors import GitError
from l4.vcs.git import Git
from l4.vcs.names import unit_branch
from l4.vcs.push import PushRejected
from l4.yolo.model import MergeOutcome

log = logging.getLogger("l4.yolo.merge")

_UNRESOLVED_FEEDBACK = ("submitted", "taken", "waiting", "not_addressed")
_REFUSAL_LINES = 3
NO_LONGER_ALLOWED = "the plan no longer allows the merge"
HEAD_LAG_READS = 3  # a PR head that differs from the branch tip is read again this many times ...
HEAD_LAG_WAIT_S = 5.0  # ... this many seconds apart: the forge may lag a push by a few seconds (L4-YOLO-008)


def _not_ready(detail: str, **known: object) -> MergeOutcome:
    return MergeOutcome("not_ready", detail=detail, **known)  # type: ignore[arg-type]


def remote_tip(git: Git, cfg: L4Config, environ: dict[str, str] | object, branch: str) -> str | None:
    """The sha of `refs/heads/<branch>` on origin, None when the branch is not there."""
    config = fetch_auth_config(cfg, environ)  # type: ignore[arg-type]
    listing = git.run("ls-remote", "origin", f"refs/heads/{branch}", config=config).stdout
    for line in listing.splitlines():
        sha, _, ref = line.partition("\t")
        if ref.strip() == f"refs/heads/{branch}" and sha:
            return sha
    return None


def _have(git: Git, cfg: L4Config, environ: object, sha: str) -> None:
    """Fetch `sha` when this clone has not got it (a tip another clone pushed)."""
    if git.run("cat-file", "-e", f"{sha}^{{commit}}", check=False).returncode != 0:
        git.run("fetch", "--no-tags", "origin", sha, config=fetch_auth_config(cfg, environ), check=False)  # type: ignore[arg-type]


def _is_ancestor(git: Git, cfg: L4Config, environ: object, tip: str, head: str) -> bool:
    """Whether `tip` is an ancestor of `head`, fetching `tip` first when this clone has not got it."""
    _have(git, cfg, environ, tip)
    return git.run("merge-base", "--is-ancestor", tip, head, check=False).returncode == 0


def foreign_commits(git: Git, cfg: L4Config, environ: object, tip: str, head: str) -> list[str]:
    """The short shas of the commits after `tip` up to `head` (merges included) that are not strict harness commits
    (author and committer the bot, an `L4-Run` trailer: `is_harness_strict`, the rule of the review re-entry), newest
    first. A tip that is not an ancestor of `head` gives every commit of `head` not in `tip`, which is what the ancestor
    check then refuses as `stale`."""
    _have(git, cfg, environ, tip)
    records = commit_records(git, f"{tip}..{head}")
    return [r[SHA][:10] for r in records if not is_harness_strict(r)]


def push_fast_forward(
    app: AppContext, cfg: L4Config, git: Git, head: str, target: str, *, before: str | None, pr: int | None = None
) -> MergeOutcome:
    """The push alone: `<head>:refs/heads/<target>`, no force. The server refuses unless the target tip is still an
    ancestor of `head`: `stale` for that, `refused` (with the redacted message) for every other refusal."""
    try:
        git.push("origin", [f"{head}:refs/heads/{target}"], config=push_auth_config(cfg, app.environ))
    except PushRejected as exc:
        return MergeOutcome("stale", head, before, pr, f"the target {target} moved before the push: {_first(app, exc)}")
    except GitError as exc:
        return MergeOutcome("refused", head, before, pr, f"the push to {target} was refused: {_first(app, exc)}")
    return MergeOutcome("merged", head, before, pr, f"{target} fast-forwarded to {head}", landed=head)


def _first(app: AppContext, exc: GitError) -> str:
    lines = [line.strip() for line in exc.stderr.strip().splitlines() if line.strip()][:_REFUSAL_LINES]
    return app.redactor.redact_text(" | ".join(lines) or f"git exit {exc.returncode}")


def guarded_push(
    app: AppContext,
    cfg: L4Config,
    git: Git,
    head: str,
    target: str,
    *,
    pr: int | None = None,
    before_push: Callable[[MergeOutcome], bool] | None = None,
    land: Callable[[str], MergeOutcome] | None = None,
) -> MergeOutcome:
    """The target tip must be an ancestor of `head` (`stale` if not, `not_ready` if the target is missing). Then
    `before_push`, when given, is called with the outcome-to-be (`merged`, with `target_before` known); False means do
    not push (`not_ready`, "the plan no longer allows the merge", R5). Then `land(tip)` (the squash merge), or
    `push_fast_forward` when none is given."""
    tip = remote_tip(git, cfg, app.environ, target)
    if tip is None:
        return _not_ready(f"the target branch {target} does not exist on origin", head=head, pr=pr)
    if not _is_ancestor(git, cfg, app.environ, tip, head):
        return MergeOutcome("stale", head, tip, pr, f"the target {target} ({tip[:10]}) is not in the unit head")
    if before_push is not None:
        how = "fast-forwarded" if land is None else "squash-merged"
        to_be = MergeOutcome("merged", head, tip, pr, f"{target} would be {how} to {head}")
        if not before_push(to_be):
            return _not_ready(NO_LONGER_ALLOWED, head=head, pr=pr)
    if land is not None:
        return land(tip)
    return push_fast_forward(app, cfg, git, head, target, before=tip, pr=pr)


_SKIP_CI = re.compile(r"\s*\[(?:skip ci|ci skip)\]\s*", re.IGNORECASE)


def squash_message(title: str, pr: int, unit: str, commits: int, head: str, run_id: str) -> tuple[str, str]:
    """The squash commit's title and body (squash-and-delete D5): the PR title without `[skip ci]` / `[ci skip]` and
    with ` (#<pr>)`; the body says what was squashed and carries the trailers a person can search for. No `[skip ci]`:
    the target's own CI should see the change."""
    cleaned = _SKIP_CI.sub(" ", title).strip() or unit
    body = (
        f"Squash of {unit}: {commits} commit{'' if commits == 1 else 's'}, verified head {head}.\n\n"
        f"L4-Unit: {unit}\nL4-Verified-Head: {head}\nL4-Run: {run_id}"
    )
    return f"{cleaned} (#{pr})", body


def squash_merge(
    app: AppContext, cfg: L4Config, git: Git, forge: Forge, pr: PullRequest, unit: str, head: str, tip: str
) -> MergeOutcome:
    """The forge's squash merge pinned to `head`, with the message of `squash_message`. `head_moved` is `not_ready`;
    a refusal (or a token the forge turns down) is `refused` with the forge's message. After `merged` the landed commit
    is read: a parent other than `tip`, or a tree other than the head's, means a person's push landed between the read
    and the merge (`raced`)."""
    target = cfg.forge.base_branch
    _have(git, cfg, app.environ, head)
    counted = git.run("rev-list", "--count", f"{tip}..{head}", check=False).stdout.strip()
    title, body = squash_message(pr.title, pr.number, unit, int(counted) if counted.isdigit() else 0, head, app.run_id)
    try:
        call = forge.merge_pr(pr.number, sha=head, title=title, message=body)
    except ForgeAuthError as exc:
        return MergeOutcome(
            "refused", head, tip, pr.number, f"the forge refused the merge: {app.redactor.redact_text(str(exc))}"
        )
    if call.status == "head_moved":
        return _not_ready(
            f"the pull request head moved before the merge ({app.redactor.redact_text(call.detail)}): "
            "the next run reads it again",
            head=head, pr=pr.number,
        )  # fmt: skip
    if call.status == "refused" or not call.sha:
        detail = app.redactor.redact_text(call.detail) or "no reason given"
        return MergeOutcome("refused", head, tip, pr.number, f"the squash merge into {target} was refused: {detail}")
    landed = call.sha
    _have(git, cfg, app.environ, landed)
    parent = git.run("rev-parse", "--verify", "-q", f"{landed}^", check=False).stdout.strip()
    tree = git.run("rev-parse", "--verify", "-q", f"{landed}^{{tree}}", check=False).stdout.strip()
    expected = git.run("rev-parse", "--verify", "-q", f"{head}^{{tree}}", check=False).stdout.strip()
    raced = not parent or parent != tip or not tree or tree != expected
    if raced:
        log.warning(
            "!%s: the squash commit %s has parent %s and tree %s; the tip read was %s and the head's tree is %s: "
            "the target moved while the forge merged",
            pr.number, landed[:10], parent[:10] or "?", tree[:10] or "?", tip[:10], expected[:10] or "?",
        )  # fmt: skip
    merged_head = head
    if raced:  # a person may have merged the pull request at another head: that head is what landed
        try:
            shown = forge.get_pr(pr.number).head_sha
        except (ForgeError, ForgeUnavailable) as exc:
            log.info("!%s: the merged head could not be read: %s", pr.number, exc)
            shown = None
        if shown and shown != head:
            log.warning(
                "!%s: the pull request was merged at %s, not at the verified %s", pr.number, shown[:10], head[:10]
            )
            merged_head = shown
    return MergeOutcome(
        "merged", merged_head, tip, pr.number, f"{target} squash-merged as {landed}", landed=landed, raced=raced
    )


def _recorded_head(snapshot: UnitSnapshot) -> tuple[str | None, str | None]:
    """The recorded hand-off commit H to merge, or the `not_ready` detail (L4-YOLO-040): no H is recorded, or the
    snapshot's hand-off commit or branch head is not H."""
    state, unit = snapshot.state, snapshot.ref.id
    h = state.ready_head
    if h is None:
        return (
            None,
            f"no hand-off commit H is recorded for {unit} (no pr.ready): l4 retry --unit {unit} hands it off again",
        )
    review = snapshot.review
    if review is None or not review.head:
        return None, "the unit branch head is not known"
    if review.handoff != h or review.head != h:
        return None, (
            f"the unit branch head {review.head[:10]} is not its recorded hand-off commit H {h[:10]}: "
            "the next run verifies the new head"
        )
    return h, None


def _ci_gate(
    app: AppContext, cfg: L4Config, git: Git, forge: Forge, snapshot: UnitSnapshot, head: str, pr: PullRequest
) -> tuple[MergeOutcome | None, str, tuple[str, ...], str]:
    """The repository's CI on H (L4-YOLO-042, L4-YOLO-043), read as the sweep reads it. A `not_ready` outcome, or
    `(None, ci, ci_jobs, warning)` when the merge may go on: `green`, `preexisting` (with the keys of the jobs red on
    the base too) or `not_run` (only when `yolo.merge.require_ci` is false). Running, red (new on H), cancelled or held,
    a required check that H has not reported, and unreadable CI always block. Every detail is fixed text with shas and
    job names, so it holds while nothing changes."""
    h10, unit, known = head[:10], snapshot.ref.id, {"head": head, "pr": pr.number}
    try:
        base = git.rev_parse(f"refs/remotes/origin/{cfg.forge.base_branch}")
        platform = forge_platform(cfg, app.environ, origin_url(app.repo, app.environ))
        read = read_handoff_ci(
            forge, head, base, platform, base_branch=cfg.forge.base_branch, ready_at=snapshot.state.ready_at
        )
    except (ForgeError, ForgeUnavailable) as exc:
        first = app.redactor.redact_text((str(exc).splitlines() or [type(exc).__name__])[0])
        text = f"the repository CI of the hand-off commit {h10} could not be read: {first}"
        return _not_ready(text, **known), "", (), ""
    said = f"; {read.warning}" if read.warning else ""

    def stop(text: str) -> tuple[MergeOutcome, str, tuple[str, ...], str]:
        return _not_ready(text + said, **known), "", (), ""

    if read.status == "running":
        base_note = f" ({read.reason})" if read.reason else ""
        return stop(
            f"the repository CI is still running on the hand-off commit {h10}{base_note}: "
            "the plan merges when it is green"
        )
    if read.status == "unreported":
        return stop(
            f"the required check {read.reason} has not reported on the hand-off commit {h10}; "
            "GitHub will refuse the merge until it does"
        )
    if read.status == "blocked":
        keys = ", ".join(sorted(j.key for j in read.blocked))
        return stop(f"the repository CI has a cancelled or held job on the hand-off commit {h10}: {keys}: re-run it")
    if read.status == "failed":
        keys = ", ".join(sorted(j.key for j in read.failed))
        if snapshot.state.ci_heads.get(head) == "preexisting":
            how = (
                "; the sweep recorded red jobs on the base too and these are not red there now: "
                f"l4 retry --unit {unit} verifies the unit again"
            )
        else:
            how = ": the next sweep records it and the unit is verified again"
        return stop(f"the repository CI failed on the hand-off commit {h10}: {keys}{how}")
    if read.status == "not_run":
        if cfg.yolo.merge.require_ci:
            return stop(
                f"no CI of the repository ran on the hand-off commit {h10} ({read.reason}): run the "
                "repository's CI on the unit branch or its pull request, or set yolo.merge.require_ci: false"
            )
        return None, "not_run", (), read.warning
    if read.status == "preexisting":
        return None, "preexisting", tuple(sorted(j.key for j in read.preexisting)), read.warning
    return None, "green", (), read.warning


def _readiness(snapshot: UnitSnapshot) -> str | None:
    """Precondition 1: why the unit is not ready to merge, None when it is."""
    state = snapshot.state
    if state.phase != "in_review":
        return f"the unit is {state.phase or 'unknown'}, not in_review"
    verdict = state.last_verdict
    if verdict is None or verdict.verdict != "PASS":
        return f"the last verdict is {verdict.verdict if verdict else 'missing'}, not PASS"
    if state.questions.open:
        return f"questions are open: {', '.join(state.questions.open)}"
    open_items = [v.id for v in item_views(snapshot.feedback, state) if v.state in _UNRESOLVED_FEEDBACK]
    if open_items:
        return f"feedback is unresolved: {', '.join(open_items)}"
    return None


def merge_guarded(
    app: AppContext,
    cfg: L4Config,
    git: Git,
    forge: Forge,
    snapshot: UnitSnapshot,
    *,
    before_push: Callable[[MergeOutcome], bool] | None = None,
    sleep: Callable[[float], None] = time.sleep,
    reread: bool = True,
    waited_head: str | None = None,
) -> MergeOutcome:
    """The preconditions in order, then `guarded_push` with the squash merge or the push (see the module docstring).
    `before_push` is called last, with the outcome-to-be, and False stops the merge without a push (R5). `sleep`
    waits between the reads of a PR whose head the forge shows late (tests pass a no-op). The plan step asks again for
    that head only when it would record the wait for the first time: `reread` False (a preview) or `waited_head`, the
    unit head a `merge_not_ready` wait is already recorded for, equal to the head to merge, reads the forge once."""
    target = cfg.forge.base_branch
    if (why := _readiness(snapshot)) is not None:
        return _not_ready(why)
    review = snapshot.review
    if review is not None and review.reentry:
        who = ", ".join(c.sha[:10] for c in review.foreign) or "history rewritten"
        h = (snapshot.state.ready_head or review.handoff or "?")[:10]
        return _not_ready(f"the branch changed after the hand-off commit H {h} ({who}): the unit is verified again")
    head, why = _recorded_head(snapshot)
    if head is None:
        return _not_ready(why or "the unit branch head is not known")
    failure = snapshot.state.ci_failure
    if failure is not None and failure.head == head:
        names = ", ".join(sorted(str(j.get("name")) for j in failure.jobs))
        return _not_ready(
            f"the repository CI failed on the hand-off commit {head[:10]}: {names} (recorded): "
            "the unit is verified again",
            head=head,
        )
    pr = _find_pr(forge, snapshot, cfg)
    if pr is None:
        return _not_ready("the unit has no pull request", head=head)
    if pr.state != "open":
        return _not_ready(f"the pull request !{pr.number} is {pr.state}, not open", head=head, pr=pr.number)
    if pr.base_branch != target:
        return _not_ready(
            f"the pull request !{pr.number} is aimed at {pr.base_branch}, not the target {target}",
            head=head, pr=pr.number,
        )  # fmt: skip
    on_origin = remote_tip(git, cfg, app.environ, unit_branch(snapshot.ref.id, cfg.forge.branch_prefix))
    if on_origin is None:
        return _not_ready("the unit branch is not on origin any more", head=head, pr=pr.number)
    if on_origin != head:
        return _not_ready(
            f"the unit branch moved since the run read it (origin {on_origin[:10]}, head {head[:10]}): "
            "the next run verifies the new head",
            head=head, pr=pr.number,
        )  # fmt: skip
    forge_head = pr.head_sha  # None when the forge does not report it (the local forge): the ls-remote check stands
    lagging = bool(forge_head) and forge_head != head and reread and waited_head != head
    for _ in range(HEAD_LAG_READS if lagging else 0):  # the forge may lag a push
        sleep(HEAD_LAG_WAIT_S)
        try:
            forge_head = forge.get_pr(pr.number).head_sha
        except (ForgeError, ForgeUnavailable) as exc:
            log.info("!%s: the forge could not be asked again: %s", pr.number, exc)
            break
        if not forge_head or forge_head == head:
            break
    if forge_head and forge_head != head:
        return _not_ready(
            f"the pull request head {forge_head[:10]} is not the head to merge {head[:10]}", head=head, pr=pr.number
        )
    blocked, ci, ci_jobs, warning = _ci_gate(app, cfg, git, forge, snapshot, head, pr)
    if blocked is not None:
        return blocked
    if cfg.yolo.merge.method == "fast-forward":
        out = guarded_push(app, cfg, git, head, target, pr=pr.number, before_push=before_push)
    else:
        unit = snapshot.ref.id
        out = guarded_push(
            app, cfg, git, head, target, pr=pr.number, before_push=before_push,
            land=lambda tip: squash_merge(app, cfg, git, forge, pr, unit, head, tip),
        )  # fmt: skip
    if out.status != "merged":
        return out
    if out.head != head:  # a person merged the PR at another head: the verdict on H says nothing about it
        return replace(out, ci="unknown", ci_jobs=(), warning=warning)
    return replace(out, ci=ci, ci_jobs=ci_jobs, warning=warning)


def _find_pr(forge: Forge, snapshot: UnitSnapshot, cfg: L4Config) -> PullRequest | None:
    found = forge.find_pr(unit_branch(snapshot.ref.id, cfg.forge.branch_prefix))
    wanted = snapshot.state.pr
    if found is not None and wanted and found.url.rstrip("/") != wanted.rstrip("/"):
        log.info("%s: the open pull request %s is not the unit's %s", snapshot.ref.id, found.url, wanted)
    return found


def confirm_merged(
    forge: Forge,
    git: Git,
    cfg: L4Config,
    pr: int,
    head: str,
    *,
    wait_s: float = 30,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> bool:
    """True when origin's target holds `head` (the landed commit: the unit head of a fast-forward, the squash commit of
    a squash): it is the tip, or an ancestor of the tip when the target moved on after the merge (review #18, R5).
    That is the proof. It then waits up to `wait_s` for the forge to show the PR as merged; a forge that has not
    caught up is logged, not an error."""
    target = cfg.forge.base_branch
    tip = remote_tip(git, cfg, git.env, target)
    if tip is None:
        return False
    if tip != head:
        _have(git, cfg, git.env, tip)
        if not _is_ancestor(git, cfg, git.env, head, tip):
            return False
    deadline = clock() + wait_s
    while True:
        try:
            if forge.get_pr(pr).state == "merged":
                return True
        except (ForgeError, ForgeUnavailable) as exc:
            log.info("!%s: the forge could not be asked yet: %s", pr, exc)
        if clock() >= deadline:
            log.warning(
                "!%s: %s holds %s, but the forge has not marked the PR merged after %ss", pr, target, head, wait_s
            )
            return True
        sleep(min(1.0, max(0.0, deadline - clock())))
