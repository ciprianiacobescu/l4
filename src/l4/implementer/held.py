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
from typing import Any, Literal

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
MAX_SOURCE_LINES = 40  # lines of one test a question shows
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
    patch: bytes | None = None  # the step's changes (`git diff --binary`), saved before they were discarded
    result: str = ""  # the agent's result for that step, as JSON
    sources: tuple[tuple[str, str], ...] = ()  # (test id, its redacted, cut source) of the tests the question names
    digests: tuple[tuple[str, str], ...] = ()  # (test id, sha256 of its exact source): recorded for audit only
    patch_path: str = ""  # where the saved step is on the unit branch (repository path)
    carries: tuple[str, ...] = ()  # the question whose replay produced this step: its accept applies to the step again
    changes: tuple[str, ...] = ()  # every path the saved step changes, as `added path`, `modified path`, `deleted path`
    diffs: tuple[tuple[str, str], ...] = ()  # (path, its redacted, cut diff) of every changed path
    note: str = ""  # why the step could not be saved (too large to show in full)

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


def _source_lines(held: HeldCheck) -> list[str]:
    """What the person accepts: every path the replay applies, the tests as they are in the saved step, and the diff of
    every changed path (redacted before it was cut, when the hold was taken)."""
    lines: list[str] = []
    if held.changes:
        lines += ["", f"Changes the replay applies ({len(held.changes)} files):", *(f"    {c}" for c in held.changes)]
    if held.sources:
        lines += ["", f"Source of the tests (redacted; at most {MAX_SOURCE_LINES} lines each):"]
        for test, text in held.sources:
            lines += [f"{test}:", *(f"    {line}" for line in text.splitlines())]
    for path, text in held.diffs:
        lines += [
            "",
            f"Diff of {path} (redacted; at most {MAX_SOURCE_LINES} lines shown; a cut says so):",
            *(f"    {x}" for x in text.splitlines()),
        ]
    if held.carries:
        lines += [
            "",
            f"This step is the replay of the step you accepted with {', '.join(held.carries)}: that accept applies to "
            "it again when you accept this question.",
        ]
    if held.note:
        lines += ["", held.note]
    return lines


def _accept_lines(held: HeldCheck) -> list[str]:
    if held.patch is None:
        return [
            "`accept: <why>` counts these on the evidence of the real run: the next run does the step again, and "
            "when the check cannot decide again, the claim is taken (the verifier and the judge see that it was "
            "accepted). A criterion that the check shows not to discriminate still fails the attempt."
        ]
    return [
        f"`accept: <why>` replays exactly the saved change of {len(held.changes)} files (the whole patch is in "
        f"`{held.patch_path}` on the unit branch): the next run applies it, with every guard and gate an agent's "
        "changes get, instead of starting an agent. The accept takes effect only through that replay: if the replay "
        "fails a gate or the check refutes a criterion, the accept is used up, and a later step that meets the same "
        "inconclusive check is held again with a new question. When the check cannot decide again during the replay, "
        "the claim is taken (the verifier and the judge see that it was accepted). A criterion that the check shows "
        "not to discriminate still fails the attempt."
    ]


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
            *_source_lines(held),
            "",
            *_accept_lines(held),
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

    def covers(self, tests: Sequence[str]) -> bool:
        return set(tests) <= self.tests


def accepted_overrides(wb: Workbench, task_key: str, check: Check, *, for_replay: bool = False) -> dict[str, Override]:
    """subject (criterion id, or test id for `at_red`) -> the person's `accept` that covers it. A harness question
    counts when it blocks `task_key`, a human answered it `accept` with Status `answered`, the ledger recorded that
    answer's digest (`question.answered{by: human}`), and its own `question.raised` event (which the harness wrote:
    the file's text is never read for the subjects) has this task and this check. Two things end an accept
    (L4-IMP-065): a `tasks.reopened` of the task after the question was raised, and, for a question that saved its
    step (`patch_sha256`), the replay: it takes effect only while that step is replayed (`wb.replay_question`), so
    once the replay is used up it covers nothing, and a later step that meets the same inconclusive check is held
    again with a new question. A question of 0.4.16 (no `patch_sha256`) keeps the rule by test id. `for_replay`: the
    caller asks whether the question can be replayed at all."""
    file = QuestionsFile.load(wb.ref.path / QUESTIONS_FILENAME)
    if file is None:
        return {}
    events = read_ledger(wb.worktree / Path(wb.ledger_rel).parents[2]).events
    actors = {
        (str(e.data.get("id")), str(e.data.get("answer_sha256"))): str(e.data.get("by"))
        for e in events
        if e.type == "question.answered" and e.data.get("by") in ("human", "agent")
    }
    raised = {
        str(e.data.get("id")): (i, e)
        for i, e in enumerate(events)
        if e.type == "question.raised" and e.data.get("kind") == "harness"
    }
    allowed = _replay_chain(wb.replay_question, {qid: e for qid, (_, e) in raised.items()})
    found: dict[str, Override] = {}
    for question in file.questions:
        if question.kind is not QuestionKind.HARNESS or task_key not in question.blocking_tasks:
            continue
        if question.status is not QuestionStatus.ANSWERED or answered_by(question) != "human":
            continue
        digest = answer_sha256(question)
        by = actors.get((question.id, str(digest)))
        if harness_answer(question) != "accept" or digest is None or by is None:
            continue
        at, event = raised.get(question.id, (0, None))
        if event is None or event.data.get("task") != task_key or event.data.get("check") != check:
            continue
        if any(e.type == "tasks.reopened" and task_key in (e.data.get("tasks") or []) for e in events[at + 1 :]):
            continue  # the criteria may have changed since: an earlier accept never covers or replays
        if event.data.get("patch_sha256") and not for_replay and question.id not in allowed:
            continue  # a saved step is accepted for its replay only (and for the steps that replay produced)
        subjects = event.data.get("tests" if check in _TEST_SUBJECTS else "criteria") or []
        recorded = frozenset(str(t) for t in event.data.get("tests") or [])
        found.update({str(s): Override(question.id, digest, recorded, by) for s in subjects})
    return found


def _replay_chain(question: str | None, raised: Mapping[str, Any]) -> set[str]:
    """The question being replayed and those whose accept it carries (its step came from a replay that held again)."""
    chain: set[str] = set()
    todo = [question] if question else []
    while todo:
        qid = todo.pop()
        if qid in chain:
            continue
        chain.add(qid)
        event = raised.get(qid)
        todo += [str(c) for c in (event.data.get("carries") or [])] if event is not None else []
    return chain
