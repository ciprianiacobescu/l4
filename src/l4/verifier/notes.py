"""The sticky section for a unit that waits for verdicts (L4-VER-013, L4-QMD-004): the open verdict questions, and for
an answer that does not start with `accept` or `reject` the sentence that asks for a fix."""

from collections.abc import Callable, Collection

from l4.clarifier.clarifier import sticky_location
from l4.clarifier.notify import build_sticky_section
from l4.clarifier.ports import QuestionView
from l4.services import HookContext
from l4.specs.questions import QUESTIONS_FILENAME, QuestionsFile
from l4.verifier.types import VerifyResult
from l4.verifier.verdicts import verdict_status

VERDICT_HINT = "Start each answer with `accept` or `reject`, then give your reason."


def verdict_section(ctx: HookContext, consumed: Collection[str]) -> str | None:
    """None when no verdict question is waiting."""
    file = QuestionsFile.load(ctx.services.ref.path / QUESTIONS_FILENAME)
    status = verdict_status(file, consumed)
    waiting = {*status.open, *status.invalid}
    if file is None or not waiting:
        return None
    path, branch, link = sticky_location(ctx)
    views = [QuestionView.of(q) for q in file.questions if q.id in waiting]
    notes = [VERDICT_HINT] + [
        f"{qid} has an answer that does not start with `accept` or `reject`: it was not read. Please answer again."
        for qid in status.invalid
    ]
    return build_sticky_section(views, path=path, branch=branch, link=link) + "\n\n" + "\n".join(notes)


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
