"""One task from pending to done (SPEC L4-IMP-008): red, then green, with retries; blocked raises questions.

An attempt that fails a check counts against `implementer.max_task_attempts` of ITS phase (red, green and the
single phase each have their own budget: live M1.8 job 5561 left green one attempt after two failed reds). A red that
is committed does not need to be redone, so only green is retried after it. `partial` and `failed` results are
advisory (L4-IMP-005): the harness's own checks decide. A `blocked` result stops the task and becomes a question
in `questions.md`.
M1: implementer-tdd-loop 1.11 (skipping a blocked task for an independent one), 1.9 (repair prompt), identical-diff
and same-error detection, 1.24 (iteration cap), the "state your blocking questions" call for a stuck task.
"""

import logging
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from l4.gates.collection import ledger_excerpt
from l4.implementer.discrimination import _test_file
from l4.implementer.guardnotes import guard_note_text
from l4.implementer.guards import IGNORE_FILE_GLOBS
from l4.implementer.held import MAX_SUBJECTS, HeldCheck, held_question
from l4.implementer.result import ResultQuestion
from l4.implementer.tdd import (
    HANG_FRAME_CHARS,
    GreenOutcome,
    RedOutcome,
    resume_red,
    run_green,
    run_red,
    run_single,
)
from l4.implementer.unfreeze import unfreeze_note
from l4.implementer.workbench import Workbench
from l4.security.protected import glob_match
from l4.specs.base import Task
from l4.specs.fixmark import chore_findings, chore_kind, chore_retakes
from l4.specs.questions import QUESTIONS_FILENAME, NewQuestion, QuestionKind, QuestionsFile, raise_questions

log = logging.getLogger("l4.implementer")
MAX_HUNG_SHOWN = 3


@dataclass
class TaskOutcome:
    status: Literal["done", "blocked", "halt"]
    reason: str = ""
    question_ids: list[str] = field(default_factory=list)


def _questions(
    task: Task,
    questions: Sequence[ResultQuestion],
    summary: str,
    asked: str,
    red: RedOutcome | None = None,
    unit: str | None = None,
) -> list[NewQuestion]:
    """The agent's questions, bound to this task (its own `blocking_tasks` are repository-influenced text and are not
    trusted). A blocked step without any question still has to reach a human, so one is made from its summary.
    `red` is set for a green step: a technical question then ends with the harness's note on how a frozen test or
    support file is unfrozen (W-C3, D7)."""
    if not questions:
        return [
            NewQuestion(
                title=f"Task {task.key} is blocked",
                kind=QuestionKind.AMBIGUOUS,
                blocking_tasks=(task.key,),
                context=summary or "The implementer reported blocked without a question.",
                asked=asked,
            )  # fmt: skip
        ]
    return [
        NewQuestion(
            title=q.title,
            kind=QuestionKind(q.kind),
            blocking_tasks=(task.key,),
            context=_with_note(q, red, unit),
            asked=asked,
            options=tuple(q.options),
        )  # fmt: skip
        for q in questions
    ]


def _with_note(question: ResultQuestion, red: RedOutcome | None, unit: str | None) -> str:
    if red is None or question.kind != QuestionKind.TECHNICAL.value:
        return question.context
    suggested = bool(question.options) and _EDIT_OPTION.match(question.options[0]) is not None
    text = "\n".join((question.title, question.context, *question.options))
    note = unfreeze_note(text, _frozen_paths(red), ignore=_frozen_ignore(red), suggested=suggested, unit=unit)
    return f"{question.context}\n\n{note}" if question.context else note


_EDIT_OPTION = re.compile(r"^Edit `[^`\s]+`: \S")


def _suggest_edits(wb: Workbench, ids: Sequence[str], batch: Sequence[NewQuestion]) -> None:
    """A technical question whose first option is "Edit `<path>`: <change>" (`green.md`, M1.12 F2) carries it as its
    suggested answer, so that one `accepted` by the owner is the whole answer: the unfreeze of M1.10 C2 then reads the
    file from the suggestion and from the question, and no human has to write the edit."""
    path = wb.ref.path / QUESTIONS_FILENAME
    file = QuestionsFile.load(path)
    if file is None:
        return
    changed = False
    for qid, question in zip(ids, batch, strict=True):
        if question.kind is QuestionKind.TECHNICAL and question.options and _EDIT_OPTION.match(question.options[0]):
            file = file.set_suggestion(qid, question.options[0], redactor=wb.redactor)
            changed = True
    if changed:
        file.save(path)


def _raise_blocked(
    wb: Workbench, task: Task, questions: Sequence[ResultQuestion], summary: str, step: int,
    red: RedOutcome | None = None,
) -> list[str]:  # fmt: skip
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ")
    asked = f"{stamp} by {wb.selected.profile_name}, run {wb.run_id}, task {task.key}"
    batch = _questions(task, questions, summary, asked, red, wb.ref.name)
    ids = raise_questions(wb.ref.path, wb.ref.name, batch, redactor=wb.redactor)
    _suggest_edits(wb, ids, batch)
    for qid, question in zip(ids, batch, strict=True):
        wb.emit("question.raised", id=qid, task=task.key, kind=question.kind.value, title=question.title)
    wb.commit(
        f"docs({wb.ref.name}): questions [skip ci]", task=task.key, attempt=step, phase="blocked", tdd=None,
        paths=[f"{wb.unit_rel}/{QUESTIONS_FILENAME}"],
    )  # fmt: skip
    wb.push()
    return ids


def _raise_held(wb: Workbench, task: Task, held: HeldCheck, step: int) -> list[str]:
    """The question of a check L4 could not decide (L4-IMP-063): one `harness` question that blocks the task, the
    `question.raised` event that names the check and its subjects, and `check.inconclusive` with the evidence. Committed
    and pushed like a blocked task's questions; no attempt is counted."""
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ")
    asked = f"{stamp} by {wb.selected.profile_name}, run {wb.run_id}, task {task.key}"
    question = held_question(held, {c.id: c for c in wb.provider.criteria(wb.ref)}, asked)
    [qid] = raise_questions(wb.ref.path, wb.ref.name, [question], redactor=wb.redactor)
    redact = wb.redactor.redact_text
    tests = list(held.tests[:MAX_SUBJECTS])
    wb.emit(
        "question.raised", id=qid, task=task.key, kind=question.kind.value, title=question.title, check=held.check,
        criteria=list(held.criteria[:MAX_SUBJECTS]), tests=tests,
    )  # fmt: skip
    wb.emit(
        "check.inconclusive", task=task.key, phase=held.phase, check=held.check, criteria=list(held.criteria),
        tests=list(held.tests[:20]), reason=redact(held.reason), runs=list(held.runs), kept=list(held.kept[:50]),
        question=qid,
    )  # fmt: skip
    wb.commit(
        f"docs({wb.ref.name}): questions [skip ci]", task=task.key, attempt=step, phase="blocked", tdd=None,
        paths=[f"{wb.unit_rel}/{QUESTIONS_FILENAME}"],
    )  # fmt: skip
    wb.push()
    return [qid]


def _frozen_tests(red: RedOutcome) -> list[str]:
    return [p for p, f in red.manifest.files.items() if f.kind == "test"] if red.manifest else []


def _is_ignore(path: str) -> bool:
    return any(glob_match(glob, path) for glob in IGNORE_FILE_GLOBS)


def _frozen_paths(red: RedOutcome) -> list[str]:
    """The test and support files a person's answer can unfreeze: every manifest file but an ignore file, and the
    pre-existing tracked test files, which an answer that names one opens too."""
    if not red.manifest:
        return []
    return [*(p for p in red.manifest.files if not _is_ignore(p)), *red.manifest.preexisting]


def _frozen_ignore(red: RedOutcome) -> list[str]:
    return [p for p in red.manifest.files if _is_ignore(p)] if red.manifest else []


def _hung_frozen(wb: Workbench, red: RedOutcome, done: GreenOutcome) -> list[str]:
    """The tests of this green attempt that hit the per-test limit and are tests the red step froze (a test that is
    not frozen is the implementation's to fix, with the test named in the next prompt)."""
    return [h.id for h in done.hung if h.id in red.new_ids and _test_file(wb, h.id) in _frozen_tests(red)]


def _hang_question(wb: Workbench, tests: Sequence[str], done: GreenOutcome) -> ResultQuestion:
    """ONE technical question for the owner: which file, which test, which frame (W-D1). The first option is the
    suggested edit, so an `accepted` suggestion unfreezes the file (`_suggest_edits`, M1.12 F2)."""
    first = tests[0]
    path = _test_file(wb, first) or first.split("::", 1)[0]
    frame = next((h.frame for h in done.hung if h.id == first and h.frame), "")
    shown = ", ".join(tests[:MAX_HUNG_SHOWN])
    context = (
        f"The frozen test {shown} did not finish in {wb.cfg.gates.test_timeout_seconds()}s once the code works: it "
        "waits for something that the code under test does not provide (a peer that is never closed, a read with no "
        "data). It is frozen, so the implementer cannot change it. If the code is what keeps it waiting, say so in "
        "your answer."
    )
    if frame:
        context += f"\n\nIt was waiting here:\n```\n{frame[-HANG_FRAME_CHARS:]}\n```"
    return ResultQuestion(
        title=f"Frozen test {first} hangs once the code works",
        context=context,
        kind="technical",
        options=[
            f"Edit `{path}`: make the test finish (close the other end of what it waits on, or bound the read)",
            f"Keep `{path}` as it is and change the design so that the test can finish",
        ],
    )


def _ledger_text(wb: Workbench, excerpt: str) -> str:
    """The bounded form of a failure excerpt for the committed ledger: redacted whole, then cut (L4-IMP-064)."""
    redact = wb.redactor.redact_text
    return redact(ledger_excerpt(redact(excerpt)))


def _retry_reason(failure: str | None, wb: Workbench, excerpt: str = "") -> str | None:
    """What the next attempt's prompt says about this one: the headline, the failure excerpt of the named tests (live
    wave A job 5699: a retry that held only an id repeated the same mistake three times), and whatever the guards put
    back or did not apply in the step (handbook 10: errors are observations; live M1.6 job 5537, where the agent never
    learned that the guard had changed its file and sent the same one three times)."""
    if not failure:
        return failure
    note = guard_note_text(wb.guard_notes)
    return "\n\n".join(part for part in (failure, excerpt, note) if part)


@dataclass(frozen=True)
class EscalationRequest:
    """What `run_task` asks its hook when a profile has failed `implementer.escalate_after` attempts of a phase."""

    task: str
    phase: Literal["red", "green"]
    profile: str  # the profile that failed
    failures: tuple[tuple[str, str], ...]  # (profile, reason) of every failed attempt of this phase, oldest first
    attempt: int  # the attempt number of the next step


Escalate = Callable[[Workbench, EscalationRequest], Workbench | str]  # a new workbench, or why there is none


def _has_later(wb: Workbench, profile: str) -> bool:
    """Does `roles.implementer` list a profile after `profile`? (D1 condition 4)"""
    chain = wb.cfg.roles.implementer
    return profile in chain and chain.index(profile) + 1 < len(chain)


def run_task(wb: Workbench, task: Task, *, escalate: Escalate | None = None) -> TaskOutcome:
    wb.emit("task.started", task=task.key, title=task.title)
    limit = wb.cfg.implementer.max_task_attempts
    limit_after = wb.cfg.implementer.escalate_after
    # failed attempts per phase and profile, in the order the profiles ran the phase (D3): each profile is held to
    # `escalate_after` when a later profile can take over, and to `max_task_attempts` otherwise
    failures: dict[str, dict[str, int]] = {"red": {}, "green": {}, "single": {}}
    reasons: dict[str, list[tuple[str, str]]] = {
        "red": [],
        "green": [],
        "single": [],
    }  # (profile, reason), oldest first
    attempts = {"red": 0, "green": 0}  # the `<task>/<phase>/<attempt>` of the step key counts per phase
    failure: str | None = None
    excerpt = ""  # the failure text behind `failure`: in the next prompt, not in the ledger
    retry: str | None = (
        None  # `failure` and what the guards put back in that attempt: the next prompt's, not the ledger's
    )
    chore = chore_findings(wb.ref.path, task.title)  # a harness-tagged task of a fix unit: one phase, no test (D8)
    red: RedOutcome | None = None if chore else resume_red(wb, task)
    while True:
        current = "single" if chore else ("red" if red is None else "green")
        if failures[current].get(wb.selected.profile_name, 0) >= limit:
            break
        wb.unsafe.clear()  # a refused write belongs to the attempt that met it
        wb.guard_notes.clear()  # only what the guards did in this attempt is told to the next one
        if chore:
            attempts["green"] += 1
            done = run_single(
                wb, task, chore, attempt=attempts["green"], previous_failure=retry,
                kind=chore_kind(wb.ref.path, task.title) or "fix", retake=chore_retakes(wb.ref.path, task.title),
            )  # fmt: skip
            if done.status == "ok":
                return TaskOutcome("done")
            if done.status == "blocked":
                ids = _raise_blocked(wb, task, done.questions, done.summary, attempts["green"])
                return TaskOutcome("blocked", "single", ids)
            if done.status == "held":  # the discrimination check of a test chore could not decide (L4-IMP-063)
                assert done.held is not None
                return TaskOutcome("blocked", "single", _raise_held(wb, task, done.held, attempts["green"]))
            phase, failure, excerpt = "single", done.reason, done.excerpt
        elif red is None:
            attempts["red"] += 1
            outcome = run_red(wb, task, attempt=attempts["red"], previous_failure=retry)
            if outcome.status == "blocked":
                ids = _raise_blocked(wb, task, outcome.questions, outcome.summary, attempts["red"])
                return TaskOutcome("blocked", "red", ids)
            if outcome.status == "held":  # a check L4 could not decide: no attempt counted, no escalation (D7)
                assert outcome.held is not None
                return TaskOutcome("blocked", "red", _raise_held(wb, task, outcome.held, attempts["red"]))
            if outcome.status == "already_satisfied":
                return TaskOutcome("done")  # the tests exist and pass: there is nothing for green to do
            if outcome.status == "ok":
                red, failure, retry, excerpt = outcome, None, None, ""
                continue
            phase, failure, excerpt = "red", outcome.reason, outcome.excerpt
        else:
            attempts["green"] += 1
            done = run_green(wb, task, red, attempt=attempts["green"], previous_failure=retry)
            if done.status == "ok":
                return TaskOutcome("done")
            if done.status == "blocked":
                ids = _raise_blocked(wb, task, done.questions, done.summary, attempts["green"], red)
                return TaskOutcome("blocked", "green", ids)
            if done.status == "held":  # the test-at-red run could not decide: the red commit stays
                assert done.held is not None
                return TaskOutcome("blocked", "green", _raise_held(wb, task, done.held, attempts["green"]))
            phase, failure, excerpt = "green", done.reason, done.excerpt
            if hung_frozen := _hung_frozen(wb, red, done):
                # a frozen test that hangs once the code works is the owner's to edit: no attempt can change it, and
                # a halt would name nothing (W-D1). A test that is not frozen is retried with the frame in the prompt.
                question = _hang_question(wb, hung_frozen, done)
                ids = _raise_blocked(wb, task, [question], done.reason, attempts["green"], red)
                return TaskOutcome("blocked", "green", ids)
        retry = _retry_reason(failure, wb, excerpt)
        profile = wb.selected.profile_name
        failures[phase][profile] = failures[phase].get(profile, 0) + 1
        reasons[phase].append((profile, failure or ""))
        step = attempts["red" if phase == "red" else "green"]
        log.warning("%s: %s attempt %d failed on %s: %s", task.key, phase, step, profile, failure)
        wb.emit(
            "task.attempt_failed", task=task.key, phase=phase, attempt=step, profile=profile, reason=failure,
            excerpt_lines=len(excerpt.splitlines()),
            **({"excerpt": _ledger_text(wb, excerpt)} if excerpt else {}),
        )  # fmt: skip
        if escalate and phase != "single" and 1 <= limit_after < limit:
            count = failures[phase][profile]
            if limit_after <= count < limit and _has_later(wb, profile):
                request = EscalationRequest(
                    task.key, phase, profile, tuple(reasons[phase]), attempts[phase] + 1
                )  # fmt: skip
                answer = escalate(wb, request)
                if isinstance(answer, str):
                    wb.emit(
                        "implementer.escalation_skipped", task=task.key, phase=phase, **{"from": profile},
                        failures=count, reason=answer,
                    )  # fmt: skip
                else:
                    wb.emit(
                        "implementer.escalated", task=task.key, phase=phase, **{"from": profile},
                        to=answer.selected.profile_name, failures=count, attempt=request.attempt,
                    )  # fmt: skip
                    wb = answer
    ran = [{"profile": p, "failures": n} for p, n in failures[current].items()]
    where = current
    if len(ran) > 1:
        where += " on " + ", ".join(f"{p['profile']} ({p['failures']})" for p in ran)
    reason = f"task {task.key}: max_task_attempts ({limit}) reached in {where}; last failure: {failure}"
    wb.emit(
        "breaker.tripped", reason="max_task_attempts", task=task.key, phase=current,
        attempts=sum(failures[current].values()), profiles=ran, last_failure=failure,
    )  # fmt: skip
    return TaskOutcome("halt", reason)
