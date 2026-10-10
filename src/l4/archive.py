"""The merge request side of a run: the orchestrator hooks `forge`, `mirror` and `handoff` (forge-and-ci 1.39) and the
pure renderers they use (1.10 reduced).

`forge_hook` says how pushes authenticate and opens the draft MR after the first push, `mirror_hook` keeps one
`l4:<phase>` label (plus `l4:needs-answers`) on it, `handoff_hook` makes the one hand-off commit on a verified unit,
pushes it and marks the MR ready. The MR is a mirror of the unit branch and its ledger, so a forge error while mirroring
is a warning; only the hand-off itself fails the run. With no forge credential outside CI the hooks do nothing and
the unit stays `verified` (inside CI a missing token is exit 3 earlier, `l4.forge.base.require_token_in_ci`).

M1: forge-and-ci 1.8 commit status, 1.9 and 1.37 token scopes and FORGE-001, 1.30 `-o ci.skip`
(checkpoint messages carry `[skip ci]`, which suffices), 1.38 the done-gate and the commit status of the hand-off.
"""

import contextlib
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

import click

from l4.ci.sweeper import sweep
from l4.config.redaction import load_app_config
from l4.context import AppContext
from l4.exitcodes import ExitCode, L4Exit
from l4.forge.base import Forge, ForgeAuthError, ForgeError, ForgeUnavailable, PullRequest, make_forge
from l4.forge.gitlab import push_auth_config, strip_remote_credentials
from l4.forge.urls import app_forge_urls
from l4.fsutil import read_regular_file
from l4.outcome import CommandResult
from l4.services import H_PUSHED, ForgeHook, HookContext, MirrorHook
from l4.state.fold import fold
from l4.state.ledger import LedgerClosed, ledger_path, read_ledger
from l4.state.status import snapshots
from l4.vcs.authorship import HANDOFF_SUBJECT, handoff_commit
from l4.vcs.git import Git
from l4.vcs.trailers import CommitTrailers

log = logging.getLogger("l4.archive")

_READY_PHASES = frozenset({"in_review", "archived", "merged"})  # the MR is (or stays) ready for a human
MAX_TITLE_CHARS = 200
MAX_PROPOSAL_BYTES = 64 * 1024
_PROPOSAL_PREFIX = re.compile(r"^proposal:\s*", re.IGNORECASE)
NOTHING_WAITING = "Nothing is waiting for a human answer."


# --- renderers (pure) ---------------------------------------------------------------------------------------------


def _one_line(text: str) -> str:
    """Repo content in a one-line field: every kind of line break and control character is gone."""
    return "".join(ch for ch in " ".join(text.split()) if ch.isprintable())


def _same_name(text: str, name: str) -> bool:
    """Case, spaces, `-` and `_` do not make a heading another name than the unit's."""
    strip = str.maketrans("", "", " -_")
    return bool(name) and text.lower().translate(strip) == name.lower().translate(strip)


def proposal_title(unit_dir: Path, name: str = "") -> str:
    """The first `# ` heading of `proposal.md` without a leading `Proposal:` (M1.1 line 40), else the first line under
    `## Why`, else ''. The heading is the proposal's own name for itself; the Why line was SPEC L4-ARC-002's first
    choice and is now the fallback. A heading that only repeats the unit `name` (the title already starts with it)
    is not a title either (M1.8 R6)."""
    try:
        lines = read_regular_file(unit_dir / "proposal.md", limit=MAX_PROPOSAL_BYTES).decode("utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return ""
    heading = next((line[2:] for line in lines if line.startswith("# ")), "")
    heading = _one_line(_PROPOSAL_PREFIX.sub("", heading.strip(), count=1))
    if heading and not _same_name(heading, name):
        return heading
    for index, line in enumerate(lines):
        if line.startswith("#") and line.lstrip("# ").strip().lower() == "why":
            for text in lines[index + 1 :]:
                if text.strip() and not text.startswith("#"):
                    return _one_line(text.lstrip("-*> ").strip())
            break
    return ""


def render_pr_title(name: str, proposal: str) -> str:
    title = f"[l4] {name}: {proposal}" if proposal else f"[l4] {name}"
    return title if len(title) <= MAX_TITLE_CHARS else title[: MAX_TITLE_CHARS - 3].rstrip() + "..."


def render_pr_body(unit_id: str, branch: str, evidence_path: str, project_url: str | None) -> str:
    """Static: it names where the evidence will be, so it never needs rewriting when the phase changes."""
    evidence = f"`{evidence_path}`"
    if project_url:
        evidence = f"[{evidence_path}]({project_url}/-/blob/{quote(branch, safe='/')}/{quote(evidence_path, safe='/')})"
    return "\n".join(
        [
            f"Implemented by the L4 harness from the spec unit `{unit_id}`.",
            "",
            f"- Branch: `{branch}`",
            f"- Verification: {evidence} (written when verification finishes)",
            "- This merge request is a draft until verification passes; the harness then marks it ready.",
            "- Any merge method works: the harness detects the merge from the merge request and the tree. A merge "
            "commit keeps the commits' L4 trailers in the history; a squash drops them.",
            "- The harness never merges it.",
            "",
        ]
    )


def labels_for(prefix: str, phase: str, *, needs_answers: bool) -> list[str]:
    return [f"{prefix}{phase}", *([f"{prefix}needs-answers"] if needs_answers else [])]


# --- what the hooks of one run share ------------------------------------------------------------------------------


@dataclass
class _Mr:
    forge: Forge
    number: int | None = None
    pushed: bool = False  # the unit branch exists on the remote, so an MR can
    draft: bool | None = None  # the MR's draft flag as this run last saw or wrote it; None: not read yet
    applied: tuple[str, ...] | None = None  # the label set last written
    sticky: str | None = None  # the sticky note body last written
    ensured: set[str] = field(default_factory=set)


def _mr(ctx: HookContext) -> _Mr:
    """Raises `ForgeUnavailable` when this run has no forge."""
    found = ctx.shared.get("mr")
    if found is None:
        s = ctx.services
        found = ctx.shared["mr"] = _Mr(make_forge(ctx.cfg, s.app.environ))
        # a unit that went back to review already has its branch (and MR): the mirror may act before this run pushes
        found.pushed = s.git.rev_parse(f"refs/remotes/origin/{s.names.branch}") is not None
    return found


def _ensure_mr(ctx: HookContext, mr: _Mr) -> PullRequest:
    """The unit's open MR, opened as a draft when there is none yet."""
    s = ctx.services
    pr = mr.forge.find_pr(s.names.branch)
    if pr is None:
        try:
            project_url: str | None = mr.forge.project_url()
        except ForgeAuthError:
            raise
        except ForgeError:
            project_url = None  # the body then names the file without a link
        evidence = (s.ref.path / "verification.md").resolve().relative_to(s.worktree.resolve()).as_posix()
        body = render_pr_body(s.ref.id, s.names.branch, evidence, project_url)
        title = render_pr_title(s.ref.name, proposal_title(s.ref.path, s.ref.name))
        pr = mr.forge.create_pr(s.names.branch, ctx.cfg.forge.base_branch, title, body)
    mr.number, mr.draft = pr.number, pr.draft
    urls = app_forge_urls(s.app, ctx.cfg)  # the recorded URL may hold `<forge>` or, from an older harness, the host
    recorded = fold(read_ledger(s.ref.path).events, s.ref.id).pr
    if recorded is None or urls.canonical(recorded) != urls.canonical(pr.url):
        s.ledger.append("pr.updated", url=pr.url, number=pr.number, draft=pr.draft)
    return pr


def _warn(what: str, exc: ForgeError) -> None:
    if isinstance(exc, ForgeAuthError):
        raise exc  # a wrong or under-scoped token is exit 3 now, not a stale merge request
    log.warning("%s failed, the merge request may be stale until the next push: %s", what, exc)


# --- hooks --------------------------------------------------------------------------------------------------------


class _Forge:
    def __init__(self, ctx: HookContext, mr: _Mr) -> None:
        self._ctx, self._mr = ctx, mr
        self.push_config: Sequence[tuple[str, str]] = push_auth_config(ctx.cfg, ctx.services.app.environ)

    def after_push(self, phase: str | None) -> None:
        self._mr.pushed = True
        if self._mr.number is not None:
            return
        try:
            _ensure_mr(self._ctx, self._mr)
        except ForgeError as exc:
            _warn("opening the merge request", exc)


class _Mirror:
    def __init__(self, ctx: HookContext, mr: _Mr) -> None:
        self._ctx, self._mr = ctx, mr

    def sync(self, phase: str | None, notes: Sequence[str] | None = None) -> None:
        """Labels, then the sticky note. `notes` are the sections of the note (the clarifier's needs-answers list);
        None leaves the note alone, an empty sequence says nothing is waiting any more."""
        if phase is None or not self._mr.pushed:
            return
        self._draft(phase)
        self._labels(phase)
        if notes is not None:
            self._sticky(notes)

    def _draft(self, phase: str) -> None:
        """A unit that is neither in review nor merged is not ready: its MR goes back to draft, before the labels and
        before the run's first push (L4-ARC-008 (c)). It only flips toward draft: marking ready is the hand-off's."""
        mr = self._mr
        if phase in _READY_PHASES or mr.draft is True:
            return
        try:
            if mr.number is None or mr.draft is None:
                _ensure_mr(self._ctx, mr)
            if mr.draft is False and mr.number is not None:
                mr.draft = mr.forge.update_pr(mr.number, draft=True).draft
        except ForgeError as exc:
            _warn("setting the merge request back to draft", exc)

    def _labels(self, phase: str) -> None:
        mr, ctx = self._mr, self._ctx
        s = ctx.services
        prefix = ctx.cfg.forge.labels_prefix
        needs_answers = bool(fold(read_ledger(s.ref.path).events, s.ref.id).questions.open)
        wanted = tuple(labels_for(prefix, phase, needs_answers=needs_answers))
        if wanted == mr.applied:
            return
        try:
            if mr.number is None:
                mr.number = _ensure_mr(ctx, mr).number
            missing = [name for name in wanted if name not in mr.ensured]
            if missing:
                mr.forge.ensure_labels(missing)
                mr.ensured.update(missing)
            mr.forge.set_managed_labels(mr.number, list(wanted), prefix)
            mr.applied = wanted
            # a halting run pushes first in `close()`, after `ledger.finish`: the labels are set, the record is lost
            with contextlib.suppress(LedgerClosed):
                s.ledger.append("pr.labels", number=mr.number, labels=list(wanted))
        except ForgeError as exc:
            _warn("labelling the merge request", exc)

    def _sticky(self, notes: Sequence[str]) -> None:
        mr = self._mr
        body = "\n\n".join(notes) if notes else NOTHING_WAITING
        if body == mr.sticky:
            return
        try:
            if mr.number is None:
                mr.number = _ensure_mr(self._ctx, mr).number
        except ForgeError as exc:
            return _warn("writing the sticky note of the merge request", exc)
        try:
            mr.forge.upsert_sticky_note(mr.number, body)
            mr.sticky = body
        except Exception as exc:  # noqa: BLE001 - the note is a courtesy: whatever fails, the unit's exit code stays
            log.warning("writing the sticky note of the merge request failed, it may be stale: %s", exc)


def forge_hook(ctx: HookContext) -> ForgeHook | None:
    try:
        mr = _mr(ctx)
    except ForgeUnavailable as exc:
        log.warning(
            "forge hooks skipped: %s. No merge request will be opened, labelled or marked ready, and the unit "
            "stops at `verified` (pushes still use the origin remote).",
            exc,
        )
        return None
    try:
        ctx.shared["project_url"] = mr.forge.project_url()  # a rejected token stops the run before any agent runs
    except ForgeError as exc:
        _warn("checking the forge token", exc)
    strip_remote_credentials(ctx.services.git)
    return _Forge(ctx, mr)


def mirror_hook(ctx: HookContext) -> MirrorHook | None:
    try:
        return _Mirror(ctx, _mr(ctx))
    except ForgeUnavailable:
        return None  # `forge_hook` already said so


def handoff_hook(ctx: HookContext) -> bool:
    """One hand-off commit with the ledger (and `verification.md`, already committed by the verifier), pushed, then
    the MR marked ready. H is made unless HEAD already is this unit's H, so a retry after a failed MR update makes no
    second hand-off commit, while a unit that re-entered review gets a new one (L4-ARC-008 (a)); `pr.ready` records
    its sha. False: no forge, nothing was handed off."""
    try:
        mr = _mr(ctx)
    except ForgeUnavailable:
        return False
    s = ctx.services
    subject = HANDOFF_SUBJECT.format(name=s.ref.name)
    if handoff_commit(s.git, "HEAD", s.ref.name) != s.git.rev_parse("HEAD"):  # HEAD is not this unit's H: make one
        root = s.worktree.resolve()
        paths = [ledger_path(s.ref.path, s.app.run_id), s.ref.path / "verification.md"]
        s.git.run("add", "--", *(p.resolve().relative_to(root).as_posix() for p in paths if p.exists()))
        state = fold(read_ledger(s.ref.path).events, s.ref.id)
        trailers = CommitTrailers(
            unit=s.ref.id, run_id=s.app.run_id, iteration=max(state.iteration, 1), phase="verified"
        )
        s.git.commit(subject, trailers, allow_empty=True)
    ctx.push()
    ctx.shared[H_PUSHED] = True  # from here the unit branch stays at H, whatever the rest of the run does
    pr = _ensure_mr(ctx, mr)
    mr.forge.update_pr(pr.number, draft=False)
    mr.draft = False
    s.ledger.append("pr.ready", url=pr.url, number=pr.number, head=s.git.rev_parse("HEAD"))
    return True


def run_archive(app: AppContext, *, unit: str, retry: bool = False) -> CommandResult:
    """`l4 archive --unit ID`: the post-merge duty of the sweeper for one unit, on demand. The unit must be `in_review`
    with a merged MR, or already `merged` (L4-ARC-007: the archive is a merge request, never a push to the base)."""
    app, cfg = load_app_config(app)
    git = Git(app.repo, environ=app.environ)
    rows = snapshots(app, cfg, (unit,))
    actions = sweep(app, cfg, git, rows, retry=retry)
    for action in actions:
        click.echo(app.redactor.redact_text(f"{action.unit}: {action.what} {action.detail}".rstrip()))
    if not actions:
        phase = rows[0].state.phase or "none"
        raise L4Exit(ExitCode.USAGE_ERROR, f"{unit} is {phase}: only a merged unit can be archived")
    stuck = any(a.what == "archive_failed" or (a.what == "skipped" and "archive.failed" in a.detail) for a in actions)
    code = ExitCode.HALTED if stuck else ExitCode.OK  # a recorded failure is not "nothing to do": say so, `--retry`
    return CommandResult(code, [])
