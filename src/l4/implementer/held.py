"""A check L4 could not decide holds the task (SPEC L4-IMP-063, design D7, D8).

When every unconfirmed criterion of a red step (or every corrected test of `test-at-red`) is inconclusive, the
implementer has done nothing wrong and nothing the agent can change would help: the step's changes are discarded, one
question of the kind `harness` is raised, and the task ends `blocked` without a counted attempt. A person (or an agent
where the project allows it) answers `accept` (the next attempt counts those criteria on the evidence of the real run
when the check is inconclusive again) or `retry` (the check runs again, for example after an L4 upgrade).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from l4.implementer.workbench import Workbench
from l4.specs.base import Criterion
from l4.specs.questions import (
    QUESTIONS_FILENAME,
    NewQuestion,
    QuestionKind,
    QuestionsFile,
    QuestionStatus,
    answer_sha256,
    answered_by,
    harness_answer,
)
from l4.state.ledger import read_ledger

Check = Literal["pre_satisfied", "vacuity", "at_red", "tests"]
MAX_SHOWN_TESTS = 10
MAX_SUBJECTS = 50  # criteria or tests a `question.raised` event names
_LABEL = {
    "pre_satisfied": "pre-satisfied",
    "vacuity": "run (b) zero-value",
    "at_red": "test-at-red",
    "tests": "test chore discrimination",
}
_TEST_SUBJECTS = ("at_red", "tests")  # the checks whose subjects are test ids, not criteria
ACCEPT_OPTION = "accept: count these on the evidence of the real run"
RETRY_OPTION = "retry: run the check again (after an L4 upgrade or a fix)"


@dataclass(frozen=True)
class HeldCheck:
    """What a check could not decide: the task and phase, which check, the criteria (or, for `at_red`, only the tests)
    it left open, why, which gate runs it made and which functions it kept real."""

    task: str
    phase: Literal["red", "green"]
    check: Check
    criteria: tuple[str, ...]
    tests: tuple[str, ...]
    reason: str
    runs: tuple[str, ...] = ()
    kept: tuple[str, ...] = ()

    @property
    def subjects(self) -> tuple[str, ...]:
        """What an `accept` answer counts: the criteria, or the corrected tests of `at_red`."""
        return self.tests if self.check in _TEST_SUBJECTS else self.criteria

    def only(self, subjects: Sequence[str]) -> "HeldCheck":
        """The same hold for the given subjects only (those no override covers)."""
        keep = set(subjects)
        criteria = self.criteria if self.check in _TEST_SUBJECTS else tuple(c for c in self.criteria if c in keep)
        tests = tuple(t for t in self.tests if t in keep) if self.check in _TEST_SUBJECTS else self.tests
        return replace(self, criteria=criteria, tests=tests)


def held_question(held: HeldCheck, criteria: Mapping[str, Criterion], asked: str) -> NewQuestion:
    label = _LABEL[held.check]
    shown = ", ".join(held.tests[:MAX_SHOWN_TESTS]) + (
        f" (+{len(held.tests) - MAX_SHOWN_TESTS} more)" if len(held.tests) > MAX_SHOWN_TESTS else ""
    )
    context = "\n".join(
        [
            f"L4 could not run the {label} check of task {held.task}, so it does not count the failure against the "
            "agent: no attempt was used and no profile was escalated.",
            f"Why: {held.reason}",
            "Runs: " + (", ".join(held.runs) or "none"),
            "Kept real: " + (", ".join(held.kept) or "nothing"),
            f"Tests: {shown or 'none'}",
            "",
            "`accept: <why>` counts these on the evidence of the real run: the next run does the red step again, and "
            "when the check cannot decide again, the claim is taken (the verifier and the judge see that it was "
            "accepted). A criterion that the check shows not to discriminate still fails the attempt.",
            "`retry: <note>` runs the check again, for example after an L4 upgrade; the note reaches the agent.",
            "A person answers; an agent only where `clarifier.answer_by_agents` is true on the base branch.",
        ]
    )
    return NewQuestion(
        title=f"Task {held.task}: the {label} check could not decide",
        kind=QuestionKind.HARNESS,
        blocking_tasks=(held.task,),
        context=context,
        asked=asked,
        options=(ACCEPT_OPTION, RETRY_OPTION),
        criteria=tuple(criteria[c] for c in held.criteria if c in criteria),
    )


@dataclass(frozen=True)
class Override:
    """A person's (or, where the project allows it, an agent's) `accept`. `tests` are the tests the held check named:
    the override covers a criterion only while its candidate tests are among them, so a later different test of the
    criterion is not carried by an answer given about another."""

    question: str
    answer_sha256: str
    tests: frozenset[str] = frozenset()
    by: str = "human"
    model: str = ""  # the delegate: the model and the CLI that answered (L4-DLG-010)
    cli: str = ""

    def covers(self, tests: Sequence[str]) -> bool:
        return set(tests) <= self.tests


def accepted_overrides(wb: Workbench, task_key: str, check: Check) -> dict[str, Override]:
    """subject (criterion id, or test id for `at_red`) -> the person's `accept` that covers it. A harness question
    counts when it blocks `task_key`, a human answered it `accept` with Status `answered`, the ledger recorded that
    answer's digest (`question.answered{by: human}`), and its own `question.raised` event (which the harness wrote:
    the file's text is never read for the subjects) has this task and this check."""
    file = QuestionsFile.load(wb.ref.path / QUESTIONS_FILENAME)
    if file is None:
        return {}
    events = read_ledger(wb.worktree / Path(wb.ledger_rel).parents[2]).events
    actors = {
        (str(e.data.get("id")), str(e.data.get("answer_sha256"))): e.data
        for e in events
        if e.type == "question.answered" and e.data.get("by") in ("human", "agent", "delegate")
    }
    raised = {
        str(e.data.get("id")): e for e in events if e.type == "question.raised" and e.data.get("kind") == "harness"
    }
    found: dict[str, Override] = {}
    for question in file.questions:
        if question.kind is not QuestionKind.HARNESS or task_key not in question.blocking_tasks:
            continue
        if question.status is not QuestionStatus.ANSWERED or answered_by(question) != "human":
            continue
        digest = answer_sha256(question)
        recorded_by = actors.get((question.id, str(digest)))
        if harness_answer(question) != "accept" or digest is None or recorded_by is None:
            continue
        by = str(recorded_by.get("by"))
        model, cli = (
            (str(recorded_by.get("model") or ""), str(recorded_by.get("cli") or "")) if by == "delegate" else ("", "")
        )
        event = raised.get(question.id)
        if event is None or event.data.get("task") != task_key or event.data.get("check") != check:
            continue
        subjects = event.data.get("tests" if check in _TEST_SUBJECTS else "criteria") or []
        recorded = frozenset(str(t) for t in event.data.get("tests") or [])
        found.update({str(s): Override(question.id, digest, recorded, by, model, cli) for s in subjects})
    return found
