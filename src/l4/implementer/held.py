"""A check L4 could not decide holds the task (SPEC L4-IMP-063, design D7, D8).

When every unconfirmed criterion of a red step (or every corrected test of `test-at-red`) is inconclusive, the
implementer has done nothing wrong and nothing the agent can change would help: the step's changes are discarded, one
question of the kind `harness` is raised, and the task ends `blocked` without a counted attempt. A person (or an agent
where the project allows it) answers `accept` (the next attempt counts those criteria on the evidence of the real run
when the check is inconclusive again) or `retry` (the check runs again, for example after an L4 upgrade).
"""

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

from l4.gates.junit import fold_subtest_id
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

Check = Literal["pre_satisfied", "vacuity", "at_red", "tests", "repair"]
MAX_SHOWN_TESTS = 10
MAX_SHOWN_SUPPRESSIONS = 20  # suppression comments a repair question lists
MAX_SOURCE_LINES = 40  # lines of one test a question shows
MAX_LINE_CHARS = 400  # characters of one shown line; a longer one is cut and says so
MAX_CONTEXT_BYTES = 48_000  # a harness question's Context (questions.md is read up to 2 MB)
MIN_CONTEXT_BYTES = 4_000  # what a question keeps when questions.md is nearly full: the listing and the patch path
MAX_SUBJECTS = 50  # criteria or tests a `question.raised` event names
_LABEL = {
    "pre_satisfied": "pre-satisfied",
    "vacuity": "run (b) zero-value",
    "at_red": "test-at-red",
    "tests": "test chore discrimination",
    "repair": "repair proposal",
}
_TEST_SUBJECTS = ("at_red", "tests", "repair")  # the checks whose subjects are test ids, not criteria
ACCEPT_OPTION = "accept: count these on the evidence of the real run"
RETRY_OPTION = "retry: run the check again (after an L4 upgrade or a fix)"
REPAIR_ACCEPT_OPTION = "accept: apply this edit"
REPAIR_RETRY_OPTION = "retry: <note>"
PERSON_ONLY = "Only a person can accept a repair of a test; no agent or delegate answer applies it."
_PROOF = {
    "zero_value": "it fails by an assertion when the product answers its zero values",
    "base": "it fails by an assertion against the unit base's production code",
}


@dataclass(frozen=True)
class RepairedTest:
    """One test of a repair proposal (L4-IMP-091): what the question shows of it. `kind` and `message` are those of the
    failure that made it a candidate (the round's `failures`), `gate` the gate it failed in, `proof` how the repaired
    test was proved again (`zero_value`, `base`)."""

    id: str
    name: str  # `path::name`
    kind: str
    gate: str
    message: str
    proof: str = ""


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
    repaired: tuple[RepairedTest, ...] = ()  # check `repair`: the tests the proposal changes and what shows them
    blobs: tuple[tuple[str, str, str], ...] = ()  # check `repair`: (path, blob before, blob after) of the saved patch

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


_CUT_NOTE = re.compile(r"\[line cut: \d+ more characters\]\Z")


def cap_line(line: str) -> str:
    """One shown line, at most `MAX_LINE_CHARS` characters; a cut says how many were dropped. A line is cut once: one
    that already ends in its own cut note (and is no longer than a cut line is) is returned as it is, so the count
    stays that of the line as it was, not of the cut line."""
    if len(line) <= MAX_LINE_CHARS:
        return line
    note = _CUT_NOTE.search(line)
    if note is not None and len(line) <= MAX_LINE_CHARS + len(note.group()):
        return line
    return f"{line[:MAX_LINE_CHARS]}[line cut: {len(line) - MAX_LINE_CHARS} more characters]"


def text_lines(text: str) -> list[str]:
    """The lines of `text` as git counts them: broken at a newline only (a final newline ends the last line, a carriage
    return before a newline is not part of the line). `str.splitlines` also breaks at a form feed, U+000B, U+001C..001E,
    U+0085, U+2028 and U+2029, which git, Python and a diff do not: a view built from it shows a line that is not there
    and shifts every line after it (L4-IMP-091, design D3)."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return [line[:-1] if line.endswith("\r") else line for line in lines]


# The default-ignorable characters that `str.isprintable()` accepts (it rejects the other format characters): the
# combining grapheme joiner, the Hangul and Khmer fillers, the Mongolian free variation selectors, U+3164 and U+FFA0,
# the variation selectors and their supplement, the blank braille pattern, the Khitan small script filler (U+16FE4)
# and the musical null notehead (U+1D159), which render blank.
_INVISIBLE_RANGES = (
    (0x034F, 0x034F), (0x115F, 0x1160), (0x17B4, 0x17B5), (0x180B, 0x180F), (0x3164, 0x3164),
    (0xFE00, 0xFE0F), (0xFFA0, 0xFFA0), (0xE0100, 0xE01EF), (0x2800, 0x2800), (0x16FE4, 0x16FE4),
    (0x1D159, 0x1D159),
)  # fmt: skip
_INVISIBLE = re.compile(
    "[" + "".join(f"{re.escape(chr(lo))}-{re.escape(chr(hi))}" for lo, hi in _INVISIBLE_RANGES) + "]"
)
_BOM = chr(0xFEFF)


def _hidden(char: str) -> bool:
    """A character a reader's view does not show as it is (design D3): what `str.isprintable()` rejects (the controls,
    the format characters such as U+00AD and the bidirectional and zero-width ones, the line and paragraph separators,
    private-use and unassigned code points, and every space but U+0020), and the default-ignorable ones it accepts.
    Tab and newline are the caller's to allow."""
    return not char.isprintable() or _INVISIBLE.match(char) is not None


def unshown_in(text: str) -> str | None:
    """`U+XXXX` of the first character of `text` that a view does not show as it is, or None. Allowed: tab, newline, a
    carriage return directly before a newline (a CRLF line end) and one U+FEFF at the very start of the text (a byte
    order mark). A line is checked as one string first (`str.isprintable`, a regular expression), so a whole file costs
    one pass in C unless it holds such a character."""
    lines = text.split("\n")
    for number, line in enumerate(lines):
        if number == 0 and line.startswith(_BOM):
            line = line[1:]
        if number < len(lines) - 1 and line.endswith("\r"):
            line = line[:-1]
        if line.replace("\t", "").isprintable() and _INVISIBLE.search(line) is None:
            continue
        for char in line:
            if char != "\t" and _hidden(char):
                return f"U+{ord(char):04X}"
    return None


def _spell(char: str) -> str:
    code = ord(char)
    if code <= 0xFF:
        return f"\\x{code:02x}"
    return f"\\u{code:04x}" if code <= 0xFFFF else f"\\U{code:08x}"


def escape_unshown(text: str) -> str:
    """`text` with each such character written as an escape (`\\x0c`, `\\u202e`, `\\U000e0041`: two, four or eight
    hex digits), a carriage return and a byte order mark wherever they stand too: a line shown to a person never carries
    a character that acts on the view. Tab and newline stay. In a text where anything is escaped every backslash is
    doubled first, so a real form feed (`\\x0c`) and the four characters `\\x0c` (`\\\\x0c`) never look the same; a text
    with nothing to escape is returned as it is, backslashes single."""
    if text.replace("\t", "").replace("\n", "").isprintable() and _INVISIBLE.search(text) is None:
        return text
    return "".join(
        _spell(char) if char not in "\t\n" and _hidden(char) else char for char in text.replace("\\", "\\\\")
    )


def _shown(text: str) -> str:
    """A string a question shows on one line: its characters spelled, and cut at `MAX_LINE_CHARS`."""
    return cap_line(escape_unshown(text))


def _one_line(text: str) -> str:
    """... and with a newline spelled too, for a field that must not start a line of its own."""
    return cap_line(escape_unshown(text).replace("\n", "\\n"))  # spelled after the escapes, which double a backslash


def _indented(text: str) -> list[str]:
    return [f"    {_shown(line)}" for line in text_lines(text)]


def _source_lines(held: HeldCheck) -> list[str]:
    """What the person accepts: every path the replay applies, the tests as they are in the saved step, and the diff of
    every changed path (redacted before it was cut, when the hold was taken)."""
    lines: list[str] = []
    if held.changes:
        lines += ["", f"Changes the replay applies ({len(held.changes)} files):", *_indented("\n".join(held.changes))]
    if held.sources:
        lines += ["", f"Source of the tests (redacted; at most {MAX_SOURCE_LINES} lines each):"]
        for test, text in held.sources:
            lines += [f"{_shown(test)}:", *_indented(text)]
    for path, text in held.diffs:
        lines += [
            "",
            f"Diff of {_shown(path)} (redacted; at most {MAX_SOURCE_LINES} lines of at most {MAX_LINE_CHARS} "
            "characters shown; a cut says so):",
            *_indented(text),
        ]
    if held.carries:
        lines += [
            "",
            f"This step is the replay of the step you accepted with {', '.join(held.carries)}: the same paths, with "
            "the content its own gates rewrote (the diff above is what will be replayed). That accept applies to it "
            "again when you accept this question.",
        ]
    return lines


def _accept_lines(held: HeldCheck) -> list[str]:
    if held.patch is None:
        return [
            "The step saved with an earlier question cannot be replayed, so `accept` is not offered: an accept "
            "without a saved step would cover nothing, and an `accept` answer to this question gives no override."
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


def _bounded(context: str, held: HeldCheck, head: list[str], tail: list[str], limit: int) -> str:
    """The Context, or, over `MAX_CONTEXT_BYTES`, the same question with the path listing and the patch path in place of
    the diffs and sources (a harness question must stay readable whatever the step changed)."""
    if len(context.encode()) <= limit:
        return context
    where = f"`{held.patch_path}` on the unit branch" if held.patch_path else "the saved patch"
    paths: list[str] = []
    used = 0
    for change in held.changes:
        line = f"    {cap_line(change)}"
        used += len(line.encode()) + 1
        if used > limit // 3:
            paths.append(f"    ... {len(held.changes) - len(paths)} more paths; the whole list is in the patch")
            break
        paths.append(line)
    return "\n".join(
        [
            *head,
            "",
            f"The diffs and sources are too large to show here. The step changed {len(held.changes)} files:",
            *paths,
            f"The whole change is in {where}; read it there before you answer.",
            "",
            *tail,
        ]
    )


def _suppression_lines(held: HeldCheck) -> list[str]:
    """The suppression comments the saved result declares for the edit, one line each (file, line, rule, reason; the
    characters spelled, a long line cut, at most `MAX_SHOWN_SUPPRESSIONS`), or nothing. The replay keeps them (design
    D5): the verifier reports a suppression comment that no result declared, so what a person accepts must show them."""
    try:
        data = json.loads(held.result) if held.result else {}
    except ValueError:
        return []
    declared = data.get("suppressions") if isinstance(data, dict) else None
    items = [d for d in declared if isinstance(d, dict)] if isinstance(declared, list) else []
    if not items:
        return []
    lines = [
        "Suppressions the agent declared for this edit (file:line rule: reason); an accept keeps them as declared, "
        "and the verifier accepts a suppression comment only if one of them covers it:"
    ]
    for item in items[:MAX_SHOWN_SUPPRESSIONS]:
        file, line, rule, reason = (item.get(key, "") for key in ("file", "line", "rule", "reason"))
        lines.append(f"    {_one_line(f'{file}:{line} {rule}: {reason}')}")
    if len(items) > MAX_SHOWN_SUPPRESSIONS:
        lines.append(f"    ... {len(items) - MAX_SHOWN_SUPPRESSIONS} more suppressions")
    return lines


def _repair_question(held: HeldCheck, asked: str, limit: int) -> NewQuestion:
    """The question of a repair proposal (L4-IMP-091, design D3): each repaired test with the failure that made it a
    candidate, the evidence of the runs that passed it, the edit and its diff, and the two options. Only a person's
    `accept` applies the edit."""
    tests = held.repaired or tuple(RepairedTest(t, t, "", "", "") for t in held.tests)
    lines = []
    for test in tests[:MAX_SHOWN_TESTS]:
        failure = f"{test.kind} in the {test.gate} gate: {_shown(test.message)}" if test.kind else "(not recorded)"
        lines.append(f"    {_shown(test.id)} ({_shown(test.name)}) failed with {failure}")
    if len(tests) > MAX_SHOWN_TESTS:
        lines.append(f"    ... {len(tests) - MAX_SHOWN_TESTS} more tests")
    proofs = [f"    {_shown(t.id)}: {_PROOF.get(t.proof, t.proof or 'not recorded')}" for t in tests[:MAX_SHOWN_TESTS]]
    head = [
        f"A repair of the unit's own failing tests of task {held.task} passed its checks and waits for a person: "
        "nothing is committed, no attempt was used and no profile was escalated.",
        f"Why: {_shown(held.reason)}",
        "The tests it repairs:",
        *lines,
        "Evidence: the repaired tests passed in the gate they failed in. Runs: " + (", ".join(held.runs) or "none"),
        "How each repaired test was proved again:",
        *proofs,
        "The structural rules of a repair held: only these tests' definitions changed and imports may have been added, "
        "no check was removed, no skip was added, no product code changed.",
        *_suppression_lines(held),
    ]
    if held.patch is None:
        accept = [_accept_lines(held)[0]]
    else:
        accept = [
            f"`accept: <why>` applies exactly this edit (the whole patch is in `{held.patch_path}` on the unit "
            "branch): the next run applies the saved patch with no agent, runs the gate and the proofs again, commits "
            "it as this unit's repair, and the next round's judge sees each test before and after. If the replay "
            "fails a check, the accept is used up and the next attempt is an agent's."
        ]
    tail = [
        *accept,
        "`retry: <note>` drops the edit and asks the agent again; the note reaches it.",
        PERSON_ONLY,
    ]
    context = _bounded("\n".join([*head, *_source_lines(held), "", *tail]), held, head, tail, limit)
    return NewQuestion(
        title=f"Task {held.task}: a repair of the unit's own failing tests waits for a person",
        kind=QuestionKind.HARNESS,
        blocking_tasks=(held.task,),
        context=context,
        asked=asked,
        options=(REPAIR_ACCEPT_OPTION, REPAIR_RETRY_OPTION) if held.patch is not None else (REPAIR_RETRY_OPTION,),
    )


def held_question(
    held: HeldCheck, criteria: Mapping[str, Criterion], asked: str, *, limit: int = MAX_CONTEXT_BYTES
) -> NewQuestion:
    if held.check == "repair":
        return _repair_question(held, asked, limit)
    label = _LABEL[held.check]
    shown = ", ".join(held.tests[:MAX_SHOWN_TESTS]) + (
        f" (+{len(held.tests) - MAX_SHOWN_TESTS} more)" if len(held.tests) > MAX_SHOWN_TESTS else ""
    )
    head = [
        f"L4 could not run the {label} check of task {held.task}, so it does not count the failure against the "
        "agent: no attempt was used and no profile was escalated.",
        f"Why: {cap_line(held.reason)}",
        "Runs: " + (", ".join(held.runs) or "none"),
        "Kept real: " + (", ".join(held.kept) or "nothing"),
        f"Tests: {shown or 'none'}",
    ]
    tail = [
        *_accept_lines(held),
        "`retry: <note>` runs the check again, for example after an L4 upgrade; the note reaches the agent.",
        "A person answers; an agent only where `clarifier.answer_by_agents` is true on the base branch.",
    ]
    context = _bounded("\n".join([*head, *_source_lines(held), "", *tail]), held, head, tail, limit)
    return NewQuestion(
        title=f"Task {held.task}: the {label} check could not decide",
        kind=QuestionKind.HARNESS,
        blocking_tasks=(held.task,),
        context=context,
        asked=asked,
        options=(ACCEPT_OPTION, RETRY_OPTION) if held.patch is not None else (RETRY_OPTION,),
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


def accepted_overrides(wb: Workbench, task_key: str, check: Check, *, for_replay: bool = False) -> dict[str, Override]:
    """subject (criterion id, or test id for `at_red`) -> the person's `accept` that covers it. A harness question
    counts when it blocks `task_key`, a human answered it `accept` with Status `answered`, the ledger recorded that
    answer's digest (`question.answered{by: human}`), and its own `question.raised` event (which the harness wrote:
    the file's text is never read for the subjects) has this task and this check. Two things end an accept
    (L4-IMP-065): a `tasks.reopened` of the task after the question was raised, and, for a question that saved its
    step (`saved: true`), the replay: it takes effect only while that step is replayed (`wb.replay_question`), so
    once the replay is used up it covers nothing, and a later step that meets the same inconclusive check is held
    again with a new question. A question of 0.4.16 (no `saved` field) keeps the rule by test id. `for_replay`: the
    caller asks whether the question can be replayed at all. A `repair` question (L4-IMP-091) counts an `accept` only
    when a person gave it (`by: human`): an agent's (`clarifier.answer_by_agents`) or the delegate's never applies a
    repair, whatever the configuration says; its events are those of this workbench's fix unit (a fix unit numbers its
    questions from Q-001 in its own file)."""
    file = QuestionsFile.load(wb.ref.path / QUESTIONS_FILENAME)
    if file is None:
        return {}
    events = _ledger_events(wb, check)
    actors = {
        (str(e.data.get("id")), str(e.data.get("answer_sha256"))): e.data
        for e in events
        if e.type == "question.answered" and e.data.get("by") in ("human", "agent", "delegate")
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
        recorded_by = actors.get((question.id, str(digest)))
        if harness_answer(question) != "accept" or digest is None or recorded_by is None:
            continue
        by = str(recorded_by.get("by"))
        if check == "repair" and by != "human":
            continue  # only a person applies a repair of a test (D4)
        model, cli = (
            (str(recorded_by.get("model") or ""), str(recorded_by.get("cli") or "")) if by == "delegate" else ("", "")
        )
        at, event = raised.get(question.id, (0, None))
        if event is None or event.data.get("task") != task_key or event.data.get("check") != check:
            continue
        if any(e.type == "tasks.reopened" and task_key in (e.data.get("tasks") or []) for e in events[at + 1 :]):
            continue  # the criteria may have changed since: an earlier accept never covers or replays
        saved = event.data.get("saved")  # absent: a question of 0.4.16, which keeps the rule by test id
        if saved is False:
            continue  # the step could not be replayed: only `retry` is offered, an accept covers nothing
        if saved is True and not for_replay and question.id not in allowed:
            continue  # a saved step is accepted for its replay only (and for the steps that replay produced)
        subjects = event.data.get("tests" if check in _TEST_SUBJECTS else "criteria") or []
        if check in _TEST_SUBJECTS:  # a question raised before L4-GAT-006 names a subtest's id
            subjects = [fold_subtest_id(str(t)) for t in subjects]
        recorded = frozenset(fold_subtest_id(str(t)) for t in event.data.get("tests") or [])
        found.update({str(s): Override(question.id, digest, recorded, by, model, cli) for s in subjects})
    return found


def _ledger_events(wb: Workbench, check: Check) -> list[Any]:
    """The unit's ledger; for a `repair` question only the events of this workbench's fix unit."""
    events = read_ledger(wb.worktree / Path(wb.ledger_rel).parents[2]).events
    if check != "repair":
        return events
    fix_unit = wb.event_context.get("fix_unit")
    return [e for e in events if e.data.get("fix_unit") == fix_unit]


def recorded_repair_blobs(wb: Workbench, task_key: str, qid: str) -> dict[str, tuple[str, str]] | None:
    """path -> (blob before, blob after) that the raise of the `repair` question `qid` of this task recorded
    (`repair_blobs`, L4-IMP-091), from the events of this workbench's fix unit; the newest raise of that question.
    None when there is no such raise or it records no usable blobs: the caller cannot compare then."""
    found: Any = None
    for event in _ledger_events(wb, "repair"):
        data = event.data
        if (
            event.type == "question.raised"
            and data.get("kind") == "harness"
            and data.get("id") == qid
            and data.get("task") == task_key
            and data.get("check") == "repair"
        ):
            found = data.get("repair_blobs")
    if not isinstance(found, dict) or not found:
        return None
    pairs: dict[str, tuple[str, str]] = {}
    for path, pair in found.items():
        if not isinstance(pair, (list, tuple)) or len(pair) != 2 or not all(isinstance(b, str) and b for b in pair):
            return None
        pairs[str(path)] = (pair[0], pair[1])
    return pairs


def ignored_accept(wb: Workbench, task_key: str, qid: str) -> str | None:
    """`by` of the recorded answer of a `repair` question when it is an `accept` that does not count: given by an agent
    or the delegate (L4-IMP-091, SCN-IMP-473). None when the question is not answered `accept`, the ledger records no
    such actor, or a person gave it."""
    file = QuestionsFile.load(wb.ref.path / QUESTIONS_FILENAME)
    question = file.get(qid) if file is not None else None
    if question is None or question.status is not QuestionStatus.ANSWERED or harness_answer(question) != "accept":
        return None
    digest = answer_sha256(question)
    for event in reversed(_ledger_events(wb, "repair")):
        if (
            event.type == "question.answered"
            and event.data.get("id") == qid
            and event.data.get("answer_sha256") == digest
        ):
            by = event.data.get("by")
            return str(by) if by in ("agent", "delegate") else None
    return None


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
