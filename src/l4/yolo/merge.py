"""The guarded merge of a plan unit (design D8, L4-YOLO-008): the harness lands a verified unit on the target branch
with one fast-forward push of the unit head, never with a forge merge call and never forced.

`merge_guarded` checks the preconditions in order (the unit is `in_review` with a PASS, no question and no feedback
open; no person's commit after the hand-off; the PR exists, is open and is aimed at the target; the head equals the
`ls-remote` tip of the unit branch and, when the forge shows it, the PR head sha (R5); the target tip is an ancestor
of the head). Each failure is `not_ready` (or `stale` for the last) and pushes nothing. Then, when the caller gave a
`before_push` callback, it is called with the outcome-to-be and a False answer pushes nothing (`not_ready`, "the plan
no longer allows the merge": the plan step records `unit.merge_requested` there, under its lease, R5). Then it pushes
`<head>:refs/heads/<target>`. The freshness of head and base is enforced by the git server, not by the read before the
push: a target that moved in between is refused as a non-fast-forward and is `stale`; any other refusal (a protected
branch, a push rule, a permission) is `refused` and carries the forge's message, redacted.

The function writes no ledger: the caller records `unit.merge_requested` and `unit.merged`. `confirm_merged` asks
whether the target holds the head (it is the tip, or an ancestor of it when the target moved on after the push) and
waits, best effort, for the forge to mark the PR merged.
`guarded_push` is the push guard alone, shared with the archive branch (`postmerge.merge_archive_guarded`).
"""

import logging
import time
from collections.abc import Callable

from l4.config.schema import L4Config
from l4.context import AppContext
from l4.forge.base import Forge, ForgeError, ForgeUnavailable, PullRequest, fetch_auth_config
from l4.forge.gitlab import push_auth_config
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
    return MergeOutcome("merged", head, before, pr, f"{target} fast-forwarded to {head}")


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
) -> MergeOutcome:
    """The target tip must be an ancestor of `head` (`stale` if not, `not_ready` if the target is missing). Then
    `before_push`, when given, is called with the outcome-to-be (`merged`, with `target_before` known); False means do
    not push (`not_ready`, "the plan no longer allows the merge", R5). Then `push_fast_forward`."""
    tip = remote_tip(git, cfg, app.environ, target)
    if tip is None:
        return _not_ready(f"the target branch {target} does not exist on origin", head=head, pr=pr)
    if not _is_ancestor(git, cfg, app.environ, tip, head):
        return MergeOutcome("stale", head, tip, pr, f"the target {target} ({tip[:10]}) is not in the unit head")
    if before_push is not None:
        to_be = MergeOutcome("merged", head, tip, pr, f"{target} would be fast-forwarded to {head}")
        if not before_push(to_be):
            return _not_ready(NO_LONGER_ALLOWED, head=head, pr=pr)
    return push_fast_forward(app, cfg, git, head, target, before=tip, pr=pr)


def _unit_head(git: Git, snapshot: UnitSnapshot, cfg: L4Config) -> str | None:
    if snapshot.review is not None and snapshot.review.head:
        return snapshot.review.head
    branch = unit_branch(snapshot.ref.id, cfg.forge.branch_prefix)
    return git.rev_parse(f"refs/remotes/origin/{branch}")


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
    """The preconditions in order, then `guarded_push` (see the module docstring). `before_push` is called last, with
    the outcome-to-be, and False stops the merge without a push (R5). `sleep` waits between the reads of a PR whose
    head the forge shows late (tests pass a no-op). The plan step asks again for that head only when it would record
    the wait for the first time: `reread` False (a preview) or `waited_head`, the unit head a `merge_not_ready` wait
    is already recorded for, equal to the head to merge, reads the forge once."""
    target = cfg.forge.base_branch
    if (why := _readiness(snapshot)) is not None:
        return _not_ready(why)
    review = snapshot.review
    if review is not None and review.reentry:
        who = ", ".join(c.sha[:10] for c in review.foreign) or "history rewritten"
        return _not_ready(f"a person changed the branch after the hand-off ({who})")
    head = _unit_head(git, snapshot, cfg)
    if head is None:
        return _not_ready("the unit branch head is not known")
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
    return guarded_push(app, cfg, git, head, target, pr=pr.number, before_push=before_push)


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
    """True when origin's target holds `head`: it is the tip, or an ancestor of the tip when the target moved on after
    the push (review #18, R5). That is the proof. It then waits up to `wait_s` for the forge to show the PR as
    merged; a forge that has not caught up is logged, not an error."""
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
