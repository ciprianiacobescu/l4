"""One task from pending to done (SPEC L4-IMP-008): red, then green, with retries; blocked raises questions.

An attempt that fails a check counts against `implementer.max_task_attempts` of ITS phase (red, green and the
single phase each have their own budget: live M1.8 job 5561 left green one attempt after two failed reds). A red that
is committed does not need to be redone, so only green is retried after it. `partial` and `failed` results are
advisory (L4-IMP-005): the harness's own checks decide. A `blocked` result stops the task and becomes a question
in `questions.md`.
M1: implementer-tdd-loop 1.11 (skipping a blocked task for an independent one), 1.9 (repair prompt), identical-diff
and same-error detection, 1.24 (iteration cap), the "state your blocking questions" call for a stuck task.
"""

import contextlib
import logging
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Literal

from l4 import deadline
from l4.config.schema import duration_seconds
from l4.gates.collection import ledger_excerpt
from l4.implementer.discrimination import _test_file
from l4.implementer.guardnotes import GuardNote, guard_note_text
from l4.implementer.guards import IGNORE_FILE_GLOBS
from l4.implementer.held import MAX_CONTEXT_BYTES, MAX_SUBJECTS, MIN_CONTEXT_BYTES, HeldCheck, held_question
from l4.implementer.held_patch import write_held
from l4.implementer.result import ResultQuestion
from l4.implementer.tdd import (
    HANG_FRAME_CHARS,
    GreenOutcome,
    RedOutcome,
    _last_checkpoint,
    _ledger_events,
    resume_red,
    run_green,
    run_red,
    run_single,
)
from l4.implementer.unfreeze import MAX_PATHS_PER_QUESTION, NOTE_PREFIX, forbidden_note, unfreeze_note
from l4.implementer.workbench import Workbench
from l4.security.protected import forbidden_rule, glob_match
from l4.specs.base import Task
from l4.specs.fixmark import chore_findings, chore_kind, chore_retakes
from l4.specs.paths import named_paths, names_path
from l4.specs.questions import (
    MAX_QUESTIONS_BYTES,
    QUESTIONS_FILENAME,
    NewQuestion,
    QuestionKind,
    QuestionsFile,
    edit_option,
    raise_questions,
)

log = logging.getLogger("l4.implementer")
MAX_HUNG_SHOWN = 3
REPAIR_EXHAUSTED_NOTE = (
    ". The repaired test may be right and the product code wrong: a person decides which of them is at fault"
)


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
    chore_unit: str | None = None,
    guard_notes: Sequence[GuardNote] = (),
    forbidden: Sequence[str] = (),
    exists: Callable[[str], bool] = lambda path: True,
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
            context=_with_note(q, red, unit, chore_unit, guard_notes, forbidden, exists),
            asked=asked,
            options=tuple(q.options),
        )  # fmt: skip
        for q in questions
    ]


def chore_question_note(unit: str | None) -> str:
    """What the harness adds to a technical question of a blocked fix chore (ci-evidence D11): an answer cannot free a
    test or support file in a fix task, so the question must not wait for one. `unit` is the unit that asked (a fix
    unit in a real run): `l4 retry` would be refused for it, so the way on is the answer, which D13 resolves to the
    parent's branch."""
    answer = (
        f'l4 questions answer Q-NNN --unit {unit} --text "..."'
        if unit
        else 'l4 questions answer Q-NNN --unit <fix unit> --text "..."'
    )
    return (
        f"{NOTE_PREFIX} this is a fix task. It cannot unfreeze a test or test-support file (a test, `conftest.py`, a "
        "fixture), whatever the answer says: a fix step's change to one is put back. A person must commit the change "
        f"on the unit branch themselves, then answer this question (`{answer}`)."
    )


def forbidden_found(
    question: ResultQuestion,
    guard_notes: Sequence[GuardNote],
    forbidden: Sequence[str],
    exists: Callable[[str], bool] = lambda path: True,
    frozen: Sequence[str] = (),
) -> list[tuple[str, str]]:
    """(path, glob) of the paths under `odd.forbidden_paths` that make the forbidden note replace the unfreeze note,
    each once, at most `MAX_PATHS_PER_QUESTION` (forbidden-path-intake D5).
    (a) This attempt's guards removed one: it, and the missing paths the question names.
    (b) No removal: the missing paths the question names, unless its first option names a frozen file (the question
    is then about that test; a mention of an existing forbidden file does not change what an answer can do).
    `exists`: whether the unit worktree has a path."""
    removed = [(note.path, note.rule) for note in guard_notes if note.forbidden]
    text = "\n".join((question.title, question.context, *question.options))
    missing = [
        (path, rule)
        for path in named_paths(text, ("**",))
        if (rule := forbidden_rule(path, forbidden)) is not None and not exists(path)
    ]
    if not removed and any(names_path(question.options[0], path) for path in frozen if question.options):
        return []
    return list(dict.fromkeys([*removed, *missing]))[:MAX_PATHS_PER_QUESTION]


def _with_note(
    question: ResultQuestion,
    red: RedOutcome | None,
    unit: str | None,
    chore_unit: str | None = None,
    guard_notes: Sequence[GuardNote] = (),
    forbidden: Sequence[str] = (),
    exists: Callable[[str], bool] = lambda path: True,
) -> str:
    frozen = [*_frozen_paths(red), *_frozen_ignore(red)] if red is not None else []
    if question.kind == QuestionKind.TECHNICAL.value and (
        found := forbidden_found(question, guard_notes, forbidden, exists, frozen)
    ):
        note = forbidden_note(found, unit=unit)  # no answer lifts the guard: not the unfreeze note, nor the fix chore's
        return f"{question.context}\n\n{note}" if question.context else note
    if chore_unit and question.kind == QuestionKind.TECHNICAL.value:
        note = chore_question_note(chore_unit)
        return f"{question.context}\n\n{note}" if question.context else note
    if red is None or question.kind != QuestionKind.TECHNICAL.value:
        return question.context
    suggested = bool(question.options) and _edit_of(question.options[0]) is not None
    text = "\n".join((question.title, question.context, *question.options))
    note = unfreeze_note(text, _frozen_paths(red), ignore=_frozen_ignore(red), suggested=suggested, unit=unit)
    return f"{question.context}\n\n{note}" if question.context else note


def _edit_of(option: str) -> str | None:
    """`edit_option` of an option as `questions.md` keeps it: on one line, every run of whitespace (a tab, a
    non-breaking space, a line break) one space (`_one_line`). The suggestion, the note and what `accept` takes then
    read the same text (L4-IMP-004, L4-QMD-008)."""
    return edit_option(" ".join(option.split()))


def _suggest_edits(wb: Workbench, ids: Sequence[str], batch: Sequence[NewQuestion]) -> None:
    """A technical question whose first option is "Edit `<path>`: <change>" (`green.md`, M1.12 F2), or the same with
    the path bare (`edit_option`, L4-IMP-004), carries it as its suggested answer in the backticked form, so that one
    `accepted` by the owner is the whole answer: the unfreeze of M1.10 C2 then reads the file from the suggestion and
    from the question, and no human has to write the edit."""
    path = wb.ref.path / QUESTIONS_FILENAME
    file = QuestionsFile.load(path)
    if file is None:
        return
    changed = False
    for qid, question in zip(ids, batch, strict=True):
        edit = _edit_of(question.options[0]) if question.options else None
        if question.kind is QuestionKind.TECHNICAL and edit is not None:
            file = file.set_suggestion(qid, edit, redactor=wb.redactor)
            changed = True
    if changed:
        file.save(path)


def _raise_blocked(
    wb: Workbench, task: Task, questions: Sequence[ResultQuestion], summary: str, step: int,
    red: RedOutcome | None = None, chore_unit: str | None = None,
) -> list[str]:  # fmt: skip
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ")
    asked = f"{stamp} by {wb.selected.profile_name}, run {wb.run_id}, task {task.key}"
    batch = _questions(
        task, questions, summary, asked, red, wb.ref.name, chore_unit, wb.guard_notes, wb.protected.odd_forbidden,
        lambda path: os.path.lexists(wb.worktree / path),
    )  # fmt: skip
    ids = raise_questions(wb.ref.path, wb.ref.name, batch, redactor=wb.redactor)
    _suggest_edits(wb, ids, batch)
    for qid, question in zip(ids, batch, strict=True):
        chore = {"chore": True} if chore_unit and question.kind is QuestionKind.TECHNICAL else {}
        # `chore`: a blocked fix chore's technical question, which carries the fix-task note (L4-DLG-025)
        wb.emit(
            "question.raised", id=qid, task=task.key, kind=question.kind.value, title=question.title, **chore,
            **wb.asker(),
        )  # fmt: skip
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
    saved, digests = write_held(wb, held)  # the step's changes, kept for an `accept` to replay (L4-IMP-065)
    if not saved:  # a refusal, or a step that could not be read back: only `retry` is offered
        held = replace(held, patch=None)
        digests = {"saved": False}
    elif held.check == "repair":  # what the verifier compares the accepted commit with (L4-VER-073)
        digests = {**digests, "repair_blobs": {path: [before, after] for path, before, after in held.blobs}}
    size = (wb.ref.path / QUESTIONS_FILENAME).stat().st_size if (wb.ref.path / QUESTIONS_FILENAME).is_file() else 0
    room = MAX_QUESTIONS_BYTES * 3 // 4 - size  # questions.md is read up to MAX_QUESTIONS_BYTES: never grow past it
    limit = max(MIN_CONTEXT_BYTES, min(MAX_CONTEXT_BYTES, room // 2))
    question = held_question(held, {c.id: c for c in wb.provider.criteria(wb.ref)}, asked, limit=limit)
    [qid] = raise_questions(wb.ref.path, wb.ref.name, [question], redactor=wb.redactor)
    redact = wb.redactor.redact_text
    tests = list(held.tests[:MAX_SUBJECTS])
    wb.emit(
        "question.raised", id=qid, task=task.key, kind=question.kind.value, title=question.title, check=held.check,
        criteria=list(held.criteria[:MAX_SUBJECTS]), tests=tests, **wb.asker(), **digests,
    )  # fmt: skip
    wb.emit(
        "check.inconclusive", task=task.key, phase=held.phase, check=held.check, criteria=list(held.criteria),
        tests=list(held.tests[:20]), reason=redact(held.reason), runs=list(held.runs), kept=list(held.kept[:50]),
        question=qid,
    )  # fmt: skip
    wb.commit(
        f"docs({wb.ref.name}): questions [skip ci]", task=task.key, attempt=step, phase="blocked", tdd=None,
        paths=[f"{wb.unit_rel}/{QUESTIONS_FILENAME}", *saved], exact_bytes=True,
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
    phase: Literal["red", "green", "single"]
    profile: str  # the profile that failed
    failures: tuple[tuple[str, str], ...]  # (profile, reason) of every failed attempt of this phase, oldest first
    attempt: int  # the attempt number of the next step


Escalate = Callable[[Workbench, EscalationRequest], Workbench | str]  # a new workbench, or why there is none


def _has_later(wb: Workbench, profile: str) -> bool:
    """Does `roles.implementer` list a profile after `profile`? (D1 condition 4)"""
    chain = wb.cfg.roles.implementer
    return profile in chain and chain.index(profile) + 1 < len(chain)


@dataclass(frozen=True)
class Seeded:
    """What the unit's ledger already says about a task's attempts since its window began (D7b)."""

    failures: dict[str, dict[str, int]]  # phase -> profile -> failed attempts
    reasons: dict[str, list[tuple[str, str]]]  # phase -> (profile, reason), oldest first
    attempts: dict[str, int]  # "red" | "green" (a single-phase chore's too) -> the highest attempt number used


def seed_attempts(wb: Workbench, task: Task) -> Seeded:
    """The failed attempts of `task` in its window (after its last commit, retry, resume or restart; of this workbench's
    fix unit, or of none), counted as if they had failed in this run, so `max_task_attempts` and `escalate_after` hold
    across runs (L4-IMP-075). The next attempt number continues after the highest attempt of the phase, a stop
    (`deadline.reached{when: during}`) included: a step key `<task>/<phase>/<attempt>` is used once."""
    fix_unit = wb.event_context.get("fix_unit")
    failures: dict[str, dict[str, int]] = {"red": {}, "green": {}, "single": {}}
    reasons: dict[str, list[tuple[str, str]]] = {"red": [], "green": [], "single": []}
    attempts = {"red": 0, "green": 0}
    for event in deadline.window(_ledger_events(wb), task.key, fix_unit=fix_unit):
        data = event.data
        if data.get("task") != task.key or data.get("fix_unit") != fix_unit:
            continue
        phase = data.get("phase")
        failed = event.type == "task.attempt_failed"
        stopped = event.type == "deadline.reached" and data.get("when") == "during"
        if phase not in failures or not (failed or stopped):
            continue
        if failed:
            profile = str(data.get("profile") or "")
            failures[phase][profile] = failures[phase].get(profile, 0) + 1
            reasons[phase].append((profile, str(data.get("reason") or "")))
        number = data.get("attempt")
        if isinstance(number, int) and not isinstance(number, bool):
            key = "red" if phase == "red" else "green"
            attempts[key] = max(attempts[key], number)
    return Seeded(failures, reasons, attempts)


def _escalate_if_due(
    wb: Workbench, task: Task, phase: str, failures: dict[str, dict[str, int]],
    reasons: dict[str, list[tuple[str, str]]], attempts: dict[str, int], escalate: Escalate | None, limit: int,
    limit_after: int,
) -> Workbench:  # fmt: skip
    """The escalation hook (D1 of escalate-and-note): when the selected profile has failed `escalate_after` attempts of
    `phase` and fewer than `max_task_attempts`, and a later profile exists, ask for the next profile's workbench. Run
    after a failed attempt, and before a task's first attempt when earlier runs' failures say so (L4-IMP-075)."""
    profile = wb.selected.profile_name
    if not escalate or not 1 <= limit_after < limit:
        return wb
    count = failures[phase].get(profile, 0)
    if not (limit_after <= count < limit and _has_later(wb, profile)):
        return wb
    number = attempts["red" if phase == "red" else "green"] + 1  # a single step counts with the green ones
    request = EscalationRequest(task.key, phase, profile, tuple(reasons[phase]), number)
    answer = escalate(wb, request)
    if isinstance(answer, str):
        wb.emit(
            "implementer.escalation_skipped", task=task.key, phase=phase, **{"from": profile},
            failures=count, reason=answer,
        )  # fmt: skip
        return wb
    wb.emit(
        "implementer.escalated", task=task.key, phase=phase, **{"from": profile},
        to=answer.selected.profile_name, failures=count, attempt=request.attempt,
    )  # fmt: skip
    return answer


def _check_step(wb: Workbench, phase: str, task: str, attempt: int) -> None:
    """The run deadline's check before a step (L4-IMP-067): a no-op without a deadline. Raises `DeadlineReached`. A
    step stopped at the last deadline starts only as the first step of a run (`stopped_last`, D7)."""
    deadline.check(
        phase, task, attempt, None, read_events=lambda: _ledger_events(wb),
        gates_timeout_s=duration_seconds(wb.cfg.gates.timeout), fix_unit=wb.event_context.get("fix_unit"),
    )  # fmt: skip


def _resumes_at_green(wb: Workbench, task: Task) -> bool:
    """The branch holds this task's red checkpoint: the task starts with its green step (its setup and baseline belong
    to that step)."""
    last = _last_checkpoint(wb)
    return last is not None and last[1:] == (task.key, "red")


def run_task(wb: Workbench, task: Task, *, escalate: Escalate | None = None) -> TaskOutcome:
    """One task. With a run deadline armed, a step that does not fit raises `DeadlineReached` before it starts, and a
    step that ran is timed (`step.timed`); the exception passes through, with the step's mark kept (L4-IMP-067)."""
    try:
        outcome = _run_task(wb, task, escalate=escalate)
    except deadline.DeadlineReached as exc:
        exc.fix_unit = exc.fix_unit or wb.event_context.get("fix_unit")  # a fix unit's stop is counted in its window
        raise
    except BaseException:
        with contextlib.suppress(Exception):
            deadline.release_task(wb.emit, task.key)
        raise
    deadline.release_task(wb.emit, task.key)
    return outcome


def _run_task(wb: Workbench, task: Task, *, escalate: Escalate | None = None) -> TaskOutcome:
    chore = chore_findings(wb.ref.path, task.title)  # a harness-tagged task of a fix unit: one phase, no test (D8)
    # failed attempts per phase and profile, in the order the profiles ran the phase (D3): each profile is held to
    # `escalate_after` when a later profile can take over, and to `max_task_attempts` otherwise. Those of earlier runs
    # count too (D7b); `attempts` is the `<task>/<phase>/<attempt>` of the step key, per phase
    failures, reasons, attempts = (seeded := seed_attempts(wb, task)).failures, seeded.reasons, seeded.attempts
    if deadline.current() is not None:  # the task's first step: before the red checkpoint is resumed (D3)
        first = "single" if chore else "green" if _resumes_at_green(wb, task) else "red"
        _check_step(wb, first, task.key, attempts["red" if first == "red" else "green"] + 1)
    wb.emit("task.started", task=task.key, title=task.title)
    wb.served_model = None  # a model that served an earlier task's step did not ask this task's question
    limit = wb.cfg.implementer.max_task_attempts
    limit_after = wb.cfg.implementer.escalate_after
    failure: str | None = None
    excerpt = ""  # the failure text behind `failure`: in the next prompt, not in the ledger
    retry: str | None = (
        None  # `failure` and what the guards put back in that attempt: the next prompt's, not the ledger's
    )
    red: RedOutcome | None = None if chore else resume_red(wb, task)
    start = "single" if chore else "red" if red is None else "green"
    for _ in wb.cfg.roles.implementer:  # D7b: earlier runs' failures can say to move through several profiles
        moved = _escalate_if_due(wb, task, start, failures, reasons, attempts, escalate, limit, limit_after)
        if moved.selected.profile_name == wb.selected.profile_name:
            break
        wb = moved
    while True:
        current = "single" if chore else ("red" if red is None else "green")
        if failures[current].get(wb.selected.profile_name, 0) >= limit:
            break
        wb.unsafe.clear()  # a refused write belongs to the attempt that met it
        wb.guard_notes.clear()  # only what the guards did in this attempt is told to the next one
        if chore:
            attempts["green"] += 1
            _check_step(wb, "single", task.key, attempts["green"])
            with deadline.timed(wb.emit):
                done = run_single(
                    wb, task, chore, attempt=attempts["green"], previous_failure=retry,
                    kind=chore_kind(wb.ref.path, task.title) or "fix", retake=chore_retakes(wb.ref.path, task.title),
                )  # fmt: skip
            if done.status == "ok":
                return TaskOutcome("done")
            if done.status == "blocked":
                ids = _raise_blocked(wb, task, done.questions, done.summary, attempts["green"], chore_unit=wb.ref.id)
                return TaskOutcome("blocked", "single", ids)
            if done.status == "held":  # the discrimination check of a test chore could not decide (L4-IMP-063)
                assert done.held is not None
                return TaskOutcome("blocked", "single", _raise_held(wb, task, done.held, attempts["green"]))
            phase, failure, excerpt = "single", done.reason, done.excerpt
        elif red is None:
            attempts["red"] += 1
            _check_step(wb, "red", task.key, attempts["red"])
            with deadline.timed(wb.emit):
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
            _check_step(wb, "green", task.key, attempts["green"])
            with deadline.timed(wb.emit):
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
        wb = _escalate_if_due(wb, task, phase, failures, reasons, attempts, escalate, limit, limit_after)
    if failure is None and reasons[current]:  # no attempt ran in this run: the newest failure of an earlier one
        failure = reasons[current][-1][1]
    ran = [{"profile": p, "failures": n} for p, n in failures[current].items()]
    where = current
    if len(ran) > 1:
        where += " on " + ", ".join(f"{p['profile']} ({p['failures']})" for p in ran)
    reason = f"task {task.key}: max_task_attempts ({limit}) reached in {where}; last failure: {failure}"
    if chore and chore_kind(wb.ref.path, task.title) == "repair":  # L4-IMP-091: the finding may be about the code
        reason += REPAIR_EXHAUSTED_NOTE
    wb.emit(
        "breaker.tripped", reason="max_task_attempts", task=task.key, phase=current,
        attempts=sum(failures[current].values()), profiles=ran, last_failure=failure,
    )  # fmt: skip
    return TaskOutcome("halt", reason)
