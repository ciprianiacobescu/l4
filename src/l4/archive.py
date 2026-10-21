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
import itertools
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import click

from l4.accepted import read_accepted
from l4.ci.sweeper import sweep
from l4.clarifier.notify import (
    DelegateAnswer,
    DelegateEscalation,
    answered_by_delegate_section,
    needs_person_section,
    sticky_line,
)
from l4.config.redaction import load_app_config
from l4.context import AppContext
from l4.delegate.due import delegate_answers, escalations
from l4.exitcodes import ExitCode, L4Exit
from l4.forge.base import (
    Forge,
    ForgeAuthError,
    ForgeError,
    ForgeUnavailable,
    Platform,
    PullRequest,
    forge_platform,
    make_forge,
)
from l4.forge.gitlab import push_auth_config, strip_remote_credentials
from l4.forge.urls import app_forge_urls, blob_url, origin_url
from l4.fsutil import read_regular_file
from l4.outcome import CommandResult
from l4.services import H_PUSHED, ForgeHook, HookContext, MirrorHook
from l4.specs.base import SpecError
from l4.specs.feedback import FeedbackFile
from l4.specs.fixmark import read_fix_marker
from l4.specs.followup import feedback_home, read_follow_up_marker
from l4.specs.questions import QUESTIONS_FILENAME, QuestionsFile
from l4.state.fold import fold
from l4.state.ledger import LedgerClosed, ledger_path, read_ledger
from l4.state.status import snapshots
from l4.vcs.authorship import HANDOFF_SUBJECT, handoff_commit
from l4.vcs.git import Git
from l4.vcs.trailers import CommitTrailers
from l4.verifier.notes import FEEDBACK_HINT, feedback_section

log = logging.getLogger("l4.archive")

_READY_PHASES = frozenset({"in_review", "archived", "merged"})  # the MR is (or stays) ready for a human
MAX_TITLE_CHARS = 200
MAX_PROPOSAL_BYTES = 64 * 1024
_PROPOSAL_PREFIX = re.compile(r"^proposal:\s*", re.IGNORECASE)
NOTHING_WAITING = "Nothing is waiting for a human answer."


# --- renderers (pure) ---------------------------------------------------------------------------------------------


def compose_sticky(notes: Sequence[str], phase: str, feedback: str | None, *, parent: str | None = None) -> str:
    """The body of the sticky note: the sections (or the sentence that nothing waits), then the *Your feedback*
    section, and for a unit in review the line that says how to ask for changes, always last (L4-FBK-011). A follow-up
    or a fix unit (`parent`: its parent's id) takes no feedback of its own: its last line sends the person to the
    parent (review #5)."""
    body = "\n\n".join(notes) if notes else NOTHING_WAITING
    if feedback:
        body += "\n\n" + feedback
    if phase == "in_review":
        body += "\n\n" + (_parent_line(parent) if parent else FEEDBACK_HINT)
    return body


def _parent_line(parent: str) -> str:
    return (
        f"Feedback goes to the parent unit {_one_line(parent)}, in its feedback.md (docs/feedback.md); "
        "this unit takes none of its own."
    )


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


def render_pr_body(
    unit_id: str,
    branch: str,
    evidence_path: str,
    project_url: str | None,
    platform: Platform = "gitlab",
    *,
    head: str | None = None,
    force: tuple[str, str] | None = None,
    delegate: Sequence[tuple[str, str, str]] = (),
) -> str:
    """Static: it names where the evidence will be, so it never needs rewriting when the phase changes. The link names
    the unit `head` commit when given, not the branch, so it still opens after the merged branch is deleted
    (squash-and-delete D9). `force` is `(by, reason)` of a person who accepted the unit's specification without a
    readiness review (L4-YOLO-062): one more line after the verification line. `delegate` is `(question, model, cli)` of
    each question the delegate answered: one line `Answered by the delegate:` naming them (L4-DLG-027, P2)."""
    evidence = f"`{evidence_path}`"
    if project_url:
        evidence = f"[{evidence_path}]({blob_url(project_url, head or branch, evidence_path, platform)})"
    forced = []
    if force is not None:
        by, reason = force[0], " ".join(force[1].split())
        forced = [
            f"- Force-accepted without review by {by} ({reason}): no model reviewed this unit's specification before "
            "it was built."
        ]
    delegated = []
    if delegate:
        named = ", ".join(
            f"{sticky_line(q)} ({sticky_line(model)} via {sticky_line(cli)})" for q, model, cli in delegate
        )
        delegated = [
            f"- Answered by the delegate: {named}; its verdict accepts are labelled delegate_override in "
            "verification.md."
        ]
    return "\n".join(
        [
            f"Implemented by the L4 harness from the spec unit `{unit_id}`.",
            "",
            f"- Branch: `{branch}`",
            f"- Verification: {evidence} (written when verification finishes)",
            *forced,
            *delegated,
            "- This merge request is a draft until verification passes; the harness then marks it ready.",
            "- Any merge method works: the harness detects the merge from the merge request and the tree. A merge "
            "commit keeps the commits' L4 trailers in the history; a squash drops them.",
            "- Who merges it: a person, unless the unit is in an active delivery plan with `merge: auto`; then the "
            "harness merges it after verification passes (see `l4 yolo status`).",
            "",
        ]
    )


def _str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def labels_for(prefix: str, phase: str, *, needs_answers: bool, needs_person: bool = False) -> list[str]:
    """The managed labels of a merge request: the phase, `needs-answers` while a question is open and `needs-person`
    while one of them is a question the delegate escalated (L4-CLR-004)."""
    return [
        f"{prefix}{phase}",
        *([f"{prefix}needs-answers"] if needs_answers else []),
        *([f"{prefix}needs-person"] if needs_person else []),
    ]


def operator_labels(prefix: str) -> list[str]:
    """The labels a member uses to command the harness (L4-OPS-008): `retry`, `restart` and `resume` (which means
    `retry`). A run creates them next to its phase labels so they can be found; it never puts them on a merge
    request."""
    return [f"{prefix}{name}" for name in ("retry", "restart", "resume")]


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
        found = ctx.shared["mr"] = _Mr(make_forge(ctx.cfg, s.app.environ, repo=s.app.repo))
        # a unit that went back to review already has its branch (and MR): the mirror may act before this run pushes
        found.pushed = s.git.rev_parse(f"refs/remotes/origin/{s.names.branch}") is not None
    return found


def _pr_body(
    ctx: HookContext, mr: _Mr, *, at_head: bool = True, with_force: bool = True, with_delegate: bool = True
) -> str:
    """The body of the unit's MR: the evidence linked at the unit's current head commit (squash-and-delete D9), or
    with `at_head` False at the branch, as the draft is opened before the evidence exists. The line of a force
    acceptance comes from the carrier file (`with_force` False leaves it out: the body of a PR opened before it); the
    line of the delegate's answers comes from the ledger (`with_delegate` False leaves it out, the same)."""
    s = ctx.services
    try:
        project_url: str | None = mr.forge.project_url()
    except ForgeAuthError:
        raise
    except ForgeError:
        project_url = None  # the body then names the file without a link
    evidence = (s.ref.path / "verification.md").resolve().relative_to(s.worktree.resolve()).as_posix()
    platform = forge_platform(ctx.cfg, s.app.environ, origin_url(s.app.repo, s.app.environ))
    head = s.git.rev_parse("HEAD") if at_head else None
    forced = next((i for i in read_accepted(s.ref.path) if i.get("force")), None) if with_force else None
    force = (forced["by"], forced["reason"]) if forced is not None else None
    answers = delegate_answers(read_ledger(s.ref.path).events) if with_delegate else ()
    delegated = tuple(
        dict.fromkeys(
            (str(e.data.get("question")), str(e.data.get("model") or "?"), str(e.data.get("cli") or "?"))
            for e in answers
        )
    )
    return render_pr_body(
        s.ref.id, s.names.branch, evidence, project_url, platform, head=head, force=force, delegate=delegated
    )


_SHA_LINK = re.compile(r"/blob/[0-9a-f]{40}/")


def harness_body(current: str | None, *bodies: str) -> bool:
    """Whether `current` is still the harness's own body (one of `bodies`, a link at any commit counting as the
    same), so that the hand-off may refresh it; a body a person edited, or one the forge does not report, stays
    (L4-ARC-003)."""
    if current is None:
        return False

    def norm(text: str) -> str:
        return _SHA_LINK.sub("/blob/<commit>/", text.replace("\r\n", "\n")).strip()

    return norm(current) in {norm(b) for b in bodies}


def _ensure_mr(ctx: HookContext, mr: _Mr) -> PullRequest:
    """The unit's open MR, opened as a draft when there is none yet."""
    s = ctx.services
    pr = mr.forge.find_pr(s.names.branch)
    if pr is None:
        title = render_pr_title(s.ref.name, proposal_title(s.ref.path, s.ref.name))
        pr = mr.forge.create_pr(s.names.branch, ctx.cfg.forge.base_branch, title, _pr_body(ctx, mr))
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
            sections = [*notes, *self._delegate_sections()]
            self._sticky(compose_sticky(sections, phase, self._feedback(), parent=self._parent()))

    def _delegate_sections(self) -> list[str]:
        """`Needs a person (the delegate escalated)` and `Answered by the delegate`, from the unit's ledger as it is
        now (L4-CLR-004): none for a unit the delegate never decided about."""
        s = self._ctx.services
        events = read_ledger(s.ref.path).events
        if not any(e.type == "delegate.result" for e in events):
            return []
        titles = {
            q.id: q for q in (QuestionsFile.load(s.ref.path / QUESTIONS_FILENAME) or QuestionsFile.parse(b"")).questions
        }
        redact = s.app.redactor.redact_text

        def title(key: str) -> str:
            found = titles.get(key)
            return found.title if found is not None else ""

        open_keys = fold(events, s.ref.id).questions.open
        escalated = [
            DelegateEscalation(key, kind, title(key), redact(reason))
            for key, reason, kind in escalations(events, open_keys)
        ]
        answered = [
            DelegateAnswer(
                str(e.data.get("question")), _str(e.data.get("kind")), title(str(e.data.get("question"))),
                str(e.data.get("model") or "?"), str(e.data.get("cli") or "?"),
            )
            for e in delegate_answers(events)
        ]  # fmt: skip
        return [sec for sec in (needs_person_section(escalated), answered_by_delegate_section(answered)) if sec]

    def _parent(self) -> str | None:
        """The parent's id for a follow-up or a fix unit (it takes no feedback of its own), else None."""
        marker = read_follow_up_marker(self._ctx.services.ref.path) or read_fix_marker(self._ctx.services.ref.path)
        return marker.parent if marker is not None else None

    def _feedback(self) -> str | None:
        """The *Your feedback* section from `feedback.md` and the ledger as they are now (None: no item, or the file
        cannot be read: the note is a courtesy)."""
        s = self._ctx.services
        try:
            file = FeedbackFile.load(feedback_home(s.ref.path))  # a follow-up shows its parent's items
        except (SpecError, OSError) as exc:
            log.warning("feedback.md is not readable, the sticky note leaves out the feedback section: %s", exc)
            return None
        if file is None:
            return None
        state = fold(read_ledger(s.ref.path).events, s.ref.id)
        return feedback_section(file, state, s.app.redactor.redact_text)

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
        events = read_ledger(s.ref.path).events
        open_keys = fold(events, s.ref.id).questions.open
        needs_person = bool(open_keys) and any(e.type == "delegate.result" for e in events) and bool(
            escalations(events, open_keys)
        )  # fmt: skip
        wanted = tuple(labels_for(prefix, phase, needs_answers=bool(open_keys), needs_person=needs_person))
        if wanted == mr.applied:
            return
        try:
            if mr.number is None:
                mr.number = _ensure_mr(ctx, mr).number
            missing = [name for name in (*wanted, *operator_labels(prefix)) if name not in mr.ensured]
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

    def _sticky(self, body: str) -> None:
        mr = self._mr
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
    fresh = _pr_body(ctx, mr)  # the evidence link names H, which holds it after the branch is deleted
    older = tuple(  # a PR opened before the force acceptance or the delegate's answers has the body without its line
        body
        for at_head, with_force, with_delegate in itertools.product((True, False), repeat=3)
        if (body := _pr_body(ctx, mr, at_head=at_head, with_force=with_force, with_delegate=with_delegate)) != fresh
    )
    if harness_body(pr.body, fresh, *older):
        mr.forge.update_pr(pr.number, body=fresh, draft=False)
    else:
        mr.forge.update_pr(pr.number, draft=False)  # a person's edit of the body stays
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
