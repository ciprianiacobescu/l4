"""What a human answer unfreezes for a task's green step, pure (M1.10 decision 6; L4-IMP-002, L4-QMD-005, L4-QMD-006).

Green may not edit a frozen test (the red commit's proof). When green finds the test itself wrong it asks, and a human
answers. An answer that *names* the test file lets exactly that file change in that task's next green, and only then.
Everything else stays frozen, and the verdict of the integrity check lists what was unfrozen and by which answer.
"""

import re
from collections.abc import Collection, Sequence
from dataclasses import dataclass

from l4.implementer.guards import FreezeManifest
from l4.specs.questions import (
    Question,
    QuestionKind,
    QuestionStatus,
    answer_sha256,
    answered_by,
    effective_answer,
    unescape_text,
)
from l4.state.ledger import LedgerEvent

MAX_PATHS_PER_QUESTION = 3
_HUMAN_STATUSES = (QuestionStatus.ANSWERED, QuestionStatus.ACCEPTED)


@dataclass(frozen=True)
class Grant:
    question: str
    answer_sha256: str
    paths: tuple[str, ...]


@dataclass(frozen=True)
class Unfreeze:
    """`grants`: one per question that unfreezes something; `kept`: `(path, why)` for a named file that stays frozen."""

    grants: tuple[Grant, ...] = ()
    kept: tuple[tuple[str, str], ...] = ()

    @property
    def paths(self) -> tuple[str, ...]:
        return tuple(sorted({p for g in self.grants for p in g.paths}))

    @property
    def question(self) -> str | None:
        return ", ".join(g.question for g in self.grants) or None

    @property
    def answer_sha256(self) -> str | None:
        return self.grants[0].answer_sha256 if self.grants else None


def names_path(text: str, path: str) -> bool:
    """`path` as a token of `text`: a repository-relative path, optionally followed by `:<line>` (or a line range) or
    by sentence punctuation. A longer path (`x.pyc`, `x.py.bak`, `dir/x.py`) is another token."""
    pattern = rf"(?<![\w./-]){re.escape(path)}(?::\d+(?:[-:]\d+)?)?(?![\w/-]|\.\w)"
    return re.search(pattern, text) is not None


NOTE_PREFIX = "Harness note:"


def unfreeze_note(text: str, frozen_tests: Sequence[str], *, suggested: bool) -> str:
    """What the harness adds to the question of a blocked green step so that a human knows how a frozen test is
    unfrozen (M1.13, W-C3): the rule of `unfrozen`, in words. It names only the frozen test files that `text` (the
    agent's own title, context and options) already names, at most `MAX_PATHS_PER_QUESTION`: the question text is what
    an `accepted` suggestion is held to (`names_path(asked, path)`), so a file the note named on its own would widen
    it. `suggested`: the first option is an "Edit `<path>`: <change>" that is also the suggested answer, so `accepted`
    takes it."""
    named = [path for path in sorted(frozen_tests) if names_path(text, path)][:MAX_PATHS_PER_QUESTION]
    if not named:
        return (
            f"{NOTE_PREFIX} this task's red tests are frozen, and green may change one only when the answer names its "
            "path. This question names no frozen test file, so an answer to it cannot unfreeze anything."
        )
    files = ", ".join(f"`{path}`" for path in named)
    how = (
        "set **Status** to `accepted` to take option 1, which names the file, or write an answer that names its path"
        if suggested
        else "write an answer that names its path exactly as written here"
    )
    return (
        f"{NOTE_PREFIX} the red tests of this task are frozen. To let the next green change {files}, {how}, then "
        "commit and push. An answer that does not name the file leaves it frozen, and an answer edited after a run has "
        "used it counts as an override and unfreezes nothing."
    )


def _recorded_digests(events: Sequence[LedgerEvent]) -> dict[str, set[str]]:
    """Per question id, the `answer_sha256` of every `question.answered{by: human}` the ledger holds."""
    found: dict[str, set[str]] = {}
    for event in events:
        if event.type == "question.answered" and event.data.get("by") == "human":
            found.setdefault(str(event.data.get("id")), set()).add(str(event.data.get("answer_sha256")))
    return found


def unfrozen(
    questions: Sequence[Question], events: Sequence[LedgerEvent], scope: Collection[str], manifest: FreezeManifest
) -> Unfreeze:
    """The test files of `manifest` that the answers of `questions` unfreeze for a task whose own key and ancestors are
    `scope`. A question counts when its Status is `answered` or `accepted` by a human, the ledger recorded an answer
    with the digest of the text as it is now, its kind is not `verdict` and it blocks the task. The text must name the
    file; a support or ignore file it names stays frozen (`kept`). An `accepted` answer is the clarifier's suggestion,
    so the question itself (title, Context, Options) must name the file too; a human's own answer may name any test."""
    digests = _recorded_digests(events)
    grants: list[Grant] = []
    kept: list[tuple[str, str]] = []
    for question in questions:
        if question.status not in _HUMAN_STATUSES or answered_by(question) != "human":
            continue
        if question.kind is QuestionKind.VERDICT or not (set(question.blocking_tasks) & set(scope)):
            continue
        digest = answer_sha256(question)
        answer = effective_answer(question)
        if digest is None or answer is None or digest not in digests.get(question.id, set()):
            continue
        named = [path for path in sorted(manifest.files) if names_path(answer, path)]
        tests = [p for p in named if manifest.files[p].kind == "test"]
        for path in named:
            if manifest.files[path].kind != "test":
                kept.append((path, "a support or ignore file stays frozen"))
        if question.status is QuestionStatus.ACCEPTED:  # the clarifier's text: it may not widen what was asked
            asked = "\n".join(
                (question.title, unescape_text(question.context_text), unescape_text(question.options_text))
            )
            for path in [p for p in tests if not names_path(asked, p)]:
                tests.remove(path)
                kept.append((path, f"an accepted suggestion names it, the question {question.id} does not"))
        for path in tests[MAX_PATHS_PER_QUESTION:]:
            kept.append((path, f"more than {MAX_PATHS_PER_QUESTION} paths named by {question.id}"))
        if tests:
            grants.append(Grant(question.id, digest, tuple(tests[:MAX_PATHS_PER_QUESTION])))
    return Unfreeze(tuple(grants), tuple(kept))
