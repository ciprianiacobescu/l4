"""The guarded merge of a plan unit (design D8, L4-YOLO-008): the harness lands a verified unit on the target branch
with one fast-forward push of the unit head, never with a forge merge call and never forced.

`merge_guarded` checks the preconditions in order (the unit is `in_review` with a PASS, no question and no feedback
open; no person's commit after the hand-off; the PR exists, is open and is aimed at the target; the target tip is an
ancestor of the head). Each failure is `not_ready` (or `stale` for the last) and pushes nothing. Then it pushes
`<head>:refs/heads/<target>`. The freshness of head and base is enforced by the git server, not by the read before the
push: a target that moved in between is refused as a non-fast-forward and is `stale`; any other refusal (a protected
branch, a push rule, a permission) is `refused` and carries the forge's message, redacted.

The function writes no ledger: the caller records `unit.merge_requested` and `unit.merged`. `confirm_merged` asks
whether the target holds the head and waits, best effort, for the forge to mark the PR merged.
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
from l4.vcs.errors import GitError
from l4.vcs.git import Git
from l4.vcs.names import unit_branch
from l4.vcs.push import PushRejected
from l4.yolo.model import MergeOutcome

log = logging.getLogger("l4.yolo.merge")

_UNRESOLVED_FEEDBACK = ("submitted", "taken", "waiting", "not_addressed")
_REFUSAL_LINES = 3


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


def _is_ancestor(git: Git, cfg: L4Config, environ: object, tip: str, head: str) -> bool:
    """Whether `tip` is an ancestor of `head`, fetching `tip` first when this clone has not got it."""
    if git.run("cat-file", "-e", f"{tip}^{{commit}}", check=False).returncode != 0:
        git.run("fetch", "--no-tags", "origin", tip, config=fetch_auth_config(cfg, environ), check=False)  # type: ignore[arg-type]
    return git.run("merge-base", "--is-ancestor", tip, head, check=False).returncode == 0


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
    app: AppContext, cfg: L4Config, git: Git, head: str, target: str, *, pr: int | None = None
) -> MergeOutcome:
    """The target tip must be an ancestor of `head` (`stale` if not, `not_ready` if the target is missing), then
    `push_fast_forward`."""
    tip = remote_tip(git, cfg, app.environ, target)
    if tip is None:
        return _not_ready(f"the target branch {target} does not exist on origin", head=head, pr=pr)
    if not _is_ancestor(git, cfg, app.environ, tip, head):
        return MergeOutcome("stale", head, tip, pr, f"the target {target} ({tip[:10]}) is not in the unit head")
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


def merge_guarded(app: AppContext, cfg: L4Config, git: Git, forge: Forge, snapshot: UnitSnapshot) -> MergeOutcome:
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
    return guarded_push(app, cfg, git, head, target, pr=pr.number)


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
    """True when origin's target holds `head` (the proof). It then waits up to `wait_s` for the forge to show the PR as
    merged; a forge that has not caught up is logged, not an error."""
    target = cfg.forge.base_branch
    if remote_tip(git, cfg, git.env, target) != head:
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
