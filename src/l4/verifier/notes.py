"""The sticky section for a unit that waits for verdicts (L4-VER-013, L4-QMD-004): the open verdict questions, and for
an answer that does not start with `accept` or `reject` the sentence that asks for a fix."""

from collections.abc import Callable, Collection

from l4.clarifier.clarifier import sticky_location
from l4.clarifier.notify import build_sticky_section, sticky_line
from l4.clarifier.ports import QuestionView
from l4.services import HookContext
from l4.specs.feedback import FeedbackFile
from l4.specs.questions import QUESTIONS_FILENAME, QuestionsFile
from l4.state.feedback_view import item_views
from l4.state.fold import UnitState
from l4.verifier.types import VerifyResult
from l4.verifier.verdicts import VerdictQuestions, verdict_status

FEEDBACK_HINT = (
    "To ask for changes: l4 feedback add --kind refactor|duplication|tests|config|behaviour --at FILE:LINE "
    '--text "…", then commit and push (docs/feedback.md).'
)  # L4-FBK-011: the last line of every note of a unit in review
MAX_FEEDBACK_LINES = 30
MAX_FEEDBACK_LINE_CHARS = 300
VERDICT_HINT = "Start each answer with `accept` or `reject`, then give your reason."


def verdict_hints(status: VerdictQuestions) -> list[str]:
    """The lines under the open verdict questions: the hint, a line for an answer that was not read, and for a question
    that was dismissed (L4-OPS-009) the line that says a verdict question cannot be dismissed."""
    return [
        VERDICT_HINT,
        *(
            f"{qid} has an answer that does not start with `accept` or `reject`: it was not read. Please answer again."
            for qid in status.invalid
        ),
        *(
            f"{qid}: a verdict question cannot be dismissed: start the answer with accept or reject"
            for qid in status.dismissed
        ),
    ]


def verdict_section(ctx: HookContext, consumed: Collection[str]) -> str | None:
    """None when no verdict question is waiting."""
    file = QuestionsFile.load(ctx.services.ref.path / QUESTIONS_FILENAME)
    status = verdict_status(file, consumed)
    waiting = {*status.open, *status.invalid}
    if file is None or not waiting:
        return None
    path, branch, link = sticky_location(ctx)
    views = [QuestionView.of(q) for q in file.questions if q.id in waiting]
    return build_sticky_section(views, path=path, branch=branch, link=link) + "\n\n" + "\n".join(verdict_hints(status))


def escalation_section(result: VerifyResult, reason: str, redact: Callable[[str], str] = lambda text: text) -> str:
    """The sticky section of a unit that ran out of fix rounds (L4-VER-007): the verdict summary, so the merge request
    labelled `l4:escalated` says why. Titles and details come from judges and gates (and the reason from an OpenSpec
    error): redacted whole, then flattened and cut."""

    def clean(text: str, limit: int) -> str:
        return " ".join(redact(text).split())[:limit]

    lines = [
        "### Escalated: the verifier failed this unit and it cannot be fixed automatically",
        "",
        f"Round {result.round} ended {result.verdict.value}: {clean(reason, 300)}.",
        "",
    ]
    blocking = [f for f in result.findings if f.blocking]
    lines += [f"- [{f.severity.value}] {clean(f.title, 160)} ({f.id})" for f in blocking[:10]]
    failed = [c for c in result.criteria if c.result == "fail"]
    lines += [f"- criterion {c.id} fails: {clean(c.reason, 160)}" for c in failed[:10]]
    lines += ["", "See `verification.md` on the unit branch for the evidence."]
    return "\n".join(lines)


def feedback_section(
    file: FeedbackFile | None, state: UnitState, redact: Callable[[str], str] = lambda text: text
) -> str | None:
    """The *Your feedback* section (L4-FBK-011, D12): one line per item of `feedback.md`, None when it has none.
    Places, evidence and problems come from the repository and from judges: redacted, then one line, without markup
    that could ping people or hide text, and cut."""
    views = item_views(file, state)
    if not views:
        return None
    lines = ["### Your feedback", ""]
    for view in views[:MAX_FEEDBACK_LINES]:
        head = " ".join(part for part in (view.id, view.kind, view.place) if part)
        line = f"{head} \N{EM DASH} {view.text}"
        lines.append("- " + sticky_line(redact(line), MAX_FEEDBACK_LINE_CHARS))
    if len(views) > MAX_FEEDBACK_LINES:
        lines.append(f"- and {len(views) - MAX_FEEDBACK_LINES} more in `feedback.md`")
    return "\n".join(lines)
