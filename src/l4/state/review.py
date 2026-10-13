"""The unit branch after the hand-off (SPEC 12.0, forge-and-ci 2.41): what a human did to it while it was `in_review`.

`after_handoff` is pure over git. H is the unit's hand-off commit (`l4.vcs.authorship.handoff_commit`), a *foreign*
commit is any commit after H on the first-parent chain that is not the harness's (bot as author and committer, and an
`L4-Run` trailer), and a *spec edit* is a net change of the unit folder outside the files the harness owns
(`verification.md` and `.l4/`). `review_trigger` turns that, and the CI result the sweep recorded for H, into the
lifecycle edge `_drive` takes (M1 form: the source is `in_review` only; the approval half of SPEC 12.0 needs
`on_approval`, which is not built).
"""

from dataclasses import dataclass
from pathlib import PurePosixPath

from l4.state.fold import UnitState
from l4.state.lifecycle import Trigger
from l4.vcs.authorship import AUTHOR, SHA, SUBJECT, commit_records, handoff_commit, is_harness, is_harness_strict
from l4.vcs.git import Git

MAX_LISTED = 10  # commits named in an edge context, a plan row or a note
_HARNESS_OWNED = ("verification.md", ".l4")
_NOT_SPEC = (*_HARNESS_OWNED, "questions.md", "feedback.md")  # the files with a channel of their own (L4-OPS-014)


@dataclass(frozen=True)
class ForeignCommit:
    sha: str
    author: str
    subject: str


@dataclass(frozen=True)
class AfterHandoff:
    handoff: str | None  # H, None when the branch has none
    head: str | None  # the branch head the answer is for
    foreign: tuple[ForeignCommit, ...] = ()  # oldest first
    spec_edit: bool = False  # the net diff H..head changes the unit folder outside the harness's files
    lost: bool = False  # no H on the branch of an `in_review` unit (history rewritten)

    @property
    def reentry(self) -> bool:
        return bool(self.foreign) or self.lost

    @property
    def at_handoff(self) -> bool:
        """The branch head is H itself: nothing happened after it."""
        return self.handoff is not None and self.handoff == self.head


def _owned(rel_to_unit: str) -> bool:
    return PurePosixPath(rel_to_unit).parts[0] in _HARNESS_OWNED


def after_handoff(git: Git, head: str, name: str, unit_rel: str) -> AfterHandoff:
    head_sha = git.rev_parse(head)
    handoff = handoff_commit(git, head, name) if head_sha else None
    if head_sha is None or handoff is None:
        return AfterHandoff(handoff, head_sha, lost=True)
    records = commit_records(git, "--first-parent", "--reverse", f"{handoff}..{head_sha}")
    foreign = tuple(ForeignCommit(r[SHA], r[AUTHOR], r[SUBJECT]) for r in records if not is_harness_strict(r))
    spec_edit = False
    if foreign:
        changed = git.run("diff", "--name-only", "-z", handoff, head_sha, "--", f":(literal){unit_rel}").stdout
        prefix = unit_rel.rstrip("/") + "/"
        spec_edit = any(
            not _owned(path.removeprefix(prefix)) for path in changed.split("\0") if path.startswith(prefix)
        )
    return AfterHandoff(handoff, head_sha, foreign, spec_edit)


def foreign_tail(git: Git, head: str, scan: int = 50, *, strict: bool = True) -> tuple[ForeignCommit, ...]:
    """The commits at the end of the first-parent chain of `head` that the harness did not make, oldest first: what a
    person pushed after the harness's own last commit (the halt). `strict` (the default) is the rule of the review
    re-entry (author and committer); `strict=False` is the author rule, which a rebase keeps (review M2)."""
    found: list[ForeignCommit] = []
    harness = is_harness_strict if strict else is_harness
    for record in commit_records(git, "--first-parent", f"--max-count={scan}", head):
        if harness(record):
            break
        found.append(ForeignCommit(record[SHA], record[AUTHOR], record[SUBJECT]))
    return tuple(reversed(found))


@dataclass(frozen=True)
class SpecEdit:
    """A person's change to the unit folder since the harness's last commit (L4-OPS-014, L4-OPS-003)."""

    shas: tuple[str, ...]  # the person's commits after `base`, oldest first (the planner's fact `spec_edited`)
    base: str  # the harness's last commit: what the spec looked like when the harness left the unit
    head: str  # the branch head the answer is for

    @property
    def signal(self) -> str:
        """The consumed-signals key: a head grants its extra round once (`unit.retried{signal}`)."""
        return f"spec_edit:{self.head}"


def spec_edit_since_harness(git: Git, head: str, unit_rel: str) -> SpecEdit | None:
    """The `foreign_tail` of `head` when its net change since the harness's last commit touches a file of the unit
    folder that is not the harness's (`.l4/`, `verification.md`) and has no channel of its own (`questions.md`,
    `feedback.md`: answers, verdicts and feedback keep their paths). A change elsewhere (`src/`) and a fix-unit folder,
    which is a sibling of the unit folder, are not a change of the spec. One rule for the push (`spec_edited`) and the
    retry (`spec_edit_since_stop`). The tail is bounded by the author rule (`is_harness`, not the strict one): a
    person's rebase makes the person the committer of every harness commit and must not turn them into a spec edit
    (review M2). A file that is the same at the harness's last commit and at the head is no edit: the diff is the net
    change."""
    tail = foreign_tail(git, head, strict=False)
    base = git.rev_parse(f"{tail[0].sha}^") if tail else None
    if not tail or base is None:
        return None
    last = tail[-1].sha
    changed = git.run("diff", "--name-only", "-z", base, last, "--", f":(literal){unit_rel}").stdout
    prefix = unit_rel.rstrip("/") + "/"
    if not any(
        PurePosixPath(path.removeprefix(prefix)).parts[0] not in _NOT_SPEC for path in changed.split("\0")
        if path.startswith(prefix)
    ):  # fmt: skip
        return None
    return SpecEdit(tuple(c.sha for c in tail), base, last)


@dataclass(frozen=True)
class ReviewTrigger:
    trigger: Trigger
    context: dict[str, object]


def _commits(after: AfterHandoff) -> list[dict[str, str]]:
    return [{"sha": c.sha, "author": c.author, "subject": c.subject} for c in after.foreign[-MAX_LISTED:]]


def review_trigger(after: AfterHandoff, state: UnitState) -> ReviewTrigger | None:
    """The edge an `in_review` unit takes (SPEC 12.0), or None when it waits for the merge. A commit after H that the
    harness did not make comes first (G1): answers or spec edits go to `implementing`, anything else to `verifying`, and
    so does a branch that lost its H. Then the project's own CI recorded red on H (G2), which counts only while the
    branch head still is H: a later commit supersedes the old pipeline."""
    if after.reentry:
        context: dict[str, object] = {"handoff": after.handoff, "commits": _commits(after), "lost": after.lost}
        trigger = Trigger.SPEC_EDIT_AFTER_HANDOFF if after.spec_edit else Trigger.COMMIT_AFTER_HANDOFF
        return ReviewTrigger(trigger, context)
    failure = state.ci_failure
    if failure is not None and after.at_handoff and failure.head == after.handoff:
        context = {
            "head": failure.head, "pipeline": failure.pipeline, "jobs": failure.jobs,
            "preexisting": failure.preexisting,
        }  # fmt: skip
        return ReviewTrigger(Trigger.REPOSITORY_CI_FAILED, context)
    return None


def review_note(found: ReviewTrigger) -> str:
    """The sticky section of the merge request while the unit is back in `verifying` or `implementing` (decision 6)."""
    context, head = found.context, "### Re-verifying after the hand-off\n\n"
    if found.trigger is Trigger.REPOSITORY_CI_FAILED:
        jobs = ", ".join(f"`{j.get('name', '?')}`" for j in context.get("jobs", []))  # type: ignore[attr-defined]
        pipeline = f" (pipeline {context['pipeline']})" if context.get("pipeline") else ""
        return (
            f"{head}The project's own CI is red on the hand-off commit `{str(context['head'])[:10]}`{pipeline}: "
            f"{jobs} ({found.trigger.value}). The harness verifies the unit again and fixes what it can; "
            "it hands off again when the round passes."
        )
    commits = context.get("commits") or []
    if context.get("lost"):
        why = "The hand-off commit is no longer on the branch (history was rewritten)."
    else:
        listed = "\n".join(
            f"- `{c['sha'][:10]}` {c['subject']} ({c['author']})"  # type: ignore[index]
            for c in commits  # type: ignore[attr-defined]
        )
        why = f"Commits after the hand-off `{str(context['handoff'])[:10]}` were not made by the harness:\n\n{listed}"
    where = "implementing" if found.trigger is Trigger.SPEC_EDIT_AFTER_HANDOFF else "verifying"
    return (
        f"{head}{why}\n\nThe unit is back in `{where}` ({found.trigger.value}) and is handed off again when it passes."
    )
