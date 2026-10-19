"""What a human answer unfreezes for a task's green step, pure (M1.10 decision 6; L4-IMP-002, L4-QMD-005, L4-QMD-006).

Green may not edit a frozen test (the red commit's proof). When green finds the test itself wrong it asks, and a human
answers. An answer that *names* the test file lets exactly that file change in that task's next green, and only then.
Everything else stays frozen, and the verdict of the integrity check lists what was unfrozen and by which answer.
"""

import re
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

from l4.implementer.guards import IGNORE_FILE_GLOBS, FreezeManifest
from l4.security.protected import glob_match
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
    """`question` and `answer_sha256` are None for a grant by the task's own text (`reason == "named_by_task"`, then
    `source` says whose text); an old ledger event without a `reason` is a `human_answer`. A `delegate_answer` grant
    carries the delegate's `profile` and `model` from the `question.answered` that recorded it."""

    question: str | None
    answer_sha256: str | None
    paths: tuple[str, ...]
    reason: str = "human_answer"
    source: str | None = None
    by: str = "human"  # `delegate` for reason `delegate_answer` (L4-DLG-014)
    profile: str | None = None
    model: str | None = None


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
        return ", ".join(g.question for g in self.grants if g.question) or None

    @property
    def answer_sha256(self) -> str | None:
        return next((g.answer_sha256 for g in self.grants if g.answer_sha256), None)


def names_path(text: str, path: str, *, dot_slash: bool = False) -> bool:
    """`path` as a token of `text`: a repository-relative path, optionally followed by `:<line>` (or a line range) or
    by sentence punctuation. A longer path (`x.pyc`, `x.py.bak`, `dir/x.py`) is another token. `dot_slash`: one `./`
    that starts the token may come before the path (`./x.py`); the `./` of `../x.py` does not."""
    if path not in text:
        return False
    lead = r"(?:\./)?" if dot_slash else ""
    pattern = rf"(?<![\w./-]){lead}{re.escape(path)}(?::\d+(?:[-:]\d+)?)?(?![\w/-]|\.\w)"
    return re.search(pattern, text) is not None


def _is_ignore_file(path: str) -> bool:
    return any(glob_match(glob, path) for glob in IGNORE_FILE_GLOBS)


def named_by_task(text: str, manifest: FreezeManifest, *, source: str) -> Unfreeze:
    """The support files of `manifest` that the text block of a task names (D3 of unfreeze-and-answer): a Python file
    that is not an ignore file, was a regular file at the red commit and that red did not add or change. Paths come
    from the manifest, so a path outside it (another task's test file) is neither opened nor listed. At most
    `MAX_PATHS_PER_QUESTION` open, in sorted order; every other named manifest path is `kept` with its reason."""
    opened: list[str] = []
    kept: list[tuple[str, str]] = []
    for path in sorted(manifest.files):
        if not names_path(text, path, dot_slash=True):
            continue
        frozen = manifest.files[path]
        if frozen.kind == "test":
            kept.append((path, "a red test of this task"))
        elif _is_ignore_file(path):
            kept.append((path, "an ignore file"))
        elif frozen.in_red:
            kept.append((path, "the red step of this task changed it"))
        elif not path.endswith(".py"):
            kept.append((path, "not a Python file: a person decides"))
        elif frozen.sha256 is None:
            kept.append((path, "a symlink at the red commit"))
        elif len(opened) >= MAX_PATHS_PER_QUESTION:
            kept.append((path, f"more than {MAX_PATHS_PER_QUESTION} paths named"))
        else:
            opened.append(path)
    grants = (Grant(None, None, tuple(opened), reason="named_by_task", source=source),) if opened else ()
    return Unfreeze(grants, tuple(kept))


NOTE_PREFIX = "Harness note:"


def unfreeze_note(
    text: str,
    frozen: Sequence[str],
    *,
    suggested: bool,
    ignore: Sequence[str] = (),
    unit: str | None = None,
    qid_hint: bool = True,
) -> str:
    """What the harness adds to the question of a blocked green step so that a human knows how a frozen file is
    unfrozen (M1.13, W-C3; D7 of unfreeze-and-answer): the rule of `unfrozen`, in words. `frozen` are the frozen test
    and support files, `ignore` the ignore files of the manifest, which an answer never unfreezes. The note names only
    the files that `text` (the agent's own title, context and options) already names, at most
    `MAX_PATHS_PER_QUESTION`: the question text is what an `accepted` suggestion is held to (`names_path(asked,
    path)`), so a file the note named on its own would widen it. It never offers an edit that the harness refuses: an
    ignore file is never offered. `suggested`: the first option is an "Edit `<path>`: <change>" that is also the
    suggested answer, so `accepted` takes it. `unit` and `qid_hint` shape the `l4 questions accept` line."""
    named = [path for path in sorted(frozen) if names_path(text, path)][:MAX_PATHS_PER_QUESTION]
    ignored = [path for path in sorted(ignore) if names_path(text, path)][:MAX_PATHS_PER_QUESTION]
    ignore_rule = "An ignore file is never unfrozen by an answer, whatever it says."
    if ignored:
        listed = ", ".join(f"`{path}`" for path in ignored)
        ignore_rule = f"{listed} is an ignore file: it is never unfrozen by an answer, whatever it says."
    if not named:
        return (
            f"{NOTE_PREFIX} this task's red tests and test-support files are frozen, and green may change one only "
            "when the answer names its path. This question names no frozen test or support file, so an answer to it "
            f"cannot unfreeze anything. {ignore_rule}"
        )
    files = ", ".join(f"`{path}`" for path in named)
    accept = "`accepted` or `answered`"
    command = " or run `l4 questions accept Q-NNN --unit <unit>`" if qid_hint else ""
    if command and unit:
        command = command.replace("<unit>", unit)
    how = (
        f"set **Status** to {accept} to take option 1, which names the file, or write an answer that names its path"
        if suggested
        else "write an answer that names its path exactly as written here"
    )
    return (
        f"{NOTE_PREFIX} the red tests and test-support files of this task are frozen. To let the next green change "
        f"{files}, {how}{command}, then commit and push. {ignore_rule} An answer that does not name the file leaves "
        "it frozen, and an answer edited after a run has used it counts as an override and unfreezes nothing."
    )


# An agent that answers through `l4 questions` acts for the person who allowed it (`clarifier.answer_by_agents`), so its
# answer opens what a person's does (L4-QMD-009; as on 0.4.18, before the actor was recorded). The delegate's does not.
PERSON_OR_AGENT = ("human", "agent")


def recorded_digests(events: Sequence[LedgerEvent], actors: Collection[str] = ("human",)) -> dict[str, set[str]]:
    """Per question id, the `answer_sha256` of every `question.answered{by: <one of actors>}` the ledger holds."""
    found: dict[str, set[str]] = {}
    for event in events:
        if event.type == "question.answered" and event.data.get("by") in actors:
            found.setdefault(str(event.data.get("id")), set()).add(str(event.data.get("answer_sha256")))
    return found


def delegate_records(events: Sequence[LedgerEvent]) -> dict[tuple[str, str], tuple[str | None, str | None]]:
    """`(question id, answer_sha256)` -> `(profile, model)` of every `question.answered{by: delegate}`."""
    found: dict[tuple[str, str], tuple[str | None, str | None]] = {}
    for event in events:
        if event.type == "question.answered" and event.data.get("by") == "delegate":
            profile, model = event.data.get("profile"), event.data.get("model")
            found[(str(event.data.get("id")), str(event.data.get("answer_sha256")))] = (
                profile if isinstance(profile, str) else None,
                model if isinstance(model, str) else None,
            )
    return found


def unfrozen(
    questions: Sequence[Question],
    events: Sequence[LedgerEvent],
    scope: Collection[str],
    manifest: FreezeManifest,
    *,
    delegate_unfreeze: bool = False,
) -> Unfreeze:
    """The test files of `manifest` that the answers of `questions` unfreeze for a task whose own key and ancestors are
    `scope`. A question counts when its Status is `answered` or `accepted` by a human, the ledger recorded an answer
    with the digest of the text as it is now, its kind is not `verdict` and it blocks the task. The text must name the
    file; a test or a support file it names opens, so does a pre-existing tracked test file of the manifest (one red
    did not touch, which the task may have to change), an ignore file stays frozen (`kept`). An `accepted` answer is the
    clarifier's suggestion, so the question itself (title, Context, Options) must name the file too; a human's own
    answer may name any test or support file.

    `delegate_unfreeze` (`delegate.unfreeze` of the base branch, L4-DLG-014): an `accepted` suggestion that the ledger
    says the delegate accepted (`question.answered{by: delegate}` with the digest of the text as it is now) counts like
    a person's, with the rules of an accepted suggestion and the reason `delegate_answer`. A delegate's own text never
    unfreezes anything."""
    digests = recorded_digests(events, PERSON_OR_AGENT)
    by_delegate = delegate_records(events) if delegate_unfreeze else {}
    grants: list[Grant] = []
    kept: list[tuple[str, str]] = []
    for question in questions:
        if question.status not in _HUMAN_STATUSES or answered_by(question) != "human":
            continue
        if question.kind in (QuestionKind.VERDICT, QuestionKind.HARNESS) or not (
            set(question.blocking_tasks) & set(scope)
        ):
            continue
        digest = answer_sha256(question)
        answer = effective_answer(question)
        if digest is None or answer is None:
            continue
        who = by_delegate.get((question.id, digest)) if question.status is QuestionStatus.ACCEPTED else None
        if digest not in digests.get(question.id, set()) and who is None:
            continue
        named = [path for path in sorted(manifest.files) if names_path(answer, path)]
        tests = [p for p in named if not _is_ignore_file(p)]  # a test or a support file: the person decides
        # a tracked test file that red did not touch (never a red test: those are in `manifest.files`)
        tests += [p for p in manifest.preexisting if p not in manifest.files and names_path(answer, p)]
        kept.extend((p, "an ignore file") for p in named if _is_ignore_file(p))
        if question.status is QuestionStatus.ACCEPTED:  # the clarifier's text: it may not widen what was asked
            asked = "\n".join(
                (question.title, unescape_text(question.context_text), unescape_text(question.options_text))
            )
            for path in [p for p in tests if not names_path(asked, p)]:
                tests.remove(path)
                kept.append((path, f"an accepted suggestion names it, the question {question.id} does not"))
        for path in tests[MAX_PATHS_PER_QUESTION:]:
            kept.append((path, f"more than {MAX_PATHS_PER_QUESTION} paths named by {question.id}"))
        if tests and digest in digests.get(question.id, set()):
            grants.append(Grant(question.id, digest, tuple(tests[:MAX_PATHS_PER_QUESTION])))
        elif tests and who is not None:
            profile, model = who
            grants.append(
                Grant(
                    question.id,
                    digest,
                    tuple(tests[:MAX_PATHS_PER_QUESTION]),
                    reason="delegate_answer",
                    by="delegate",
                    profile=profile,
                    model=model,
                )  # fmt: skip
            )
    return Unfreeze(tuple(grants), tuple(kept))


RUNNER_FROZEN = "the runner sections are frozen from red to green (L4-IMP-002)"


def config_opened(
    questions: Sequence[Question],
    events: Sequence[LedgerEvent],
    scope: Collection[str],
    candidates: Mapping[str, Collection[str]],
    *,
    phase: str,
) -> Unfreeze:
    """The gate and runner configuration files that a person's answer opens for a task's step (L4-IMP-041), with the
    rules of `unfrozen` (L4-IMP-015): the Status is `answered` or `accepted` by a human, never
    `answered-by-clarifier`; the ledger recorded it with the digest of the text as it is now; the question is not a
    verdict question and blocks the task or an ancestor (`scope`); the answer names the path; an `accepted` suggestion
    only a path the question names too; at most `MAX_PATHS_PER_QUESTION` open per question.

    `candidates`: path -> the kinds (`gate`, `runner`) of every configuration file at the step base. In green a file
    that holds only runner configuration is `kept` with the reason (the red-to-green freeze is never lifted); a manifest
    opens for its gate sections only (the caller allows `gate` for an opened path in green)."""
    digests = recorded_digests(events, PERSON_OR_AGENT)
    grants: list[Grant] = []
    kept: list[tuple[str, str]] = []
    for question in questions:
        if question.status not in _HUMAN_STATUSES or answered_by(question) != "human":
            continue
        if question.kind in (QuestionKind.VERDICT, QuestionKind.HARNESS) or not (
            set(question.blocking_tasks) & set(scope)
        ):
            continue
        digest = answer_sha256(question)
        answer = effective_answer(question)
        if digest is None or answer is None or digest not in digests.get(question.id, set()):
            continue
        opened = [path for path in sorted(candidates) if names_path(answer, path, dot_slash=True)]
        if question.status is QuestionStatus.ACCEPTED:  # the clarifier's text: it may not widen what was asked
            asked = "\n".join(
                (question.title, unescape_text(question.context_text), unescape_text(question.options_text))
            )
            for path in [p for p in opened if not names_path(asked, p, dot_slash=True)]:
                opened.remove(path)
                kept.append((path, f"an accepted suggestion names it, the question {question.id} does not"))
        if phase == "green":
            for path in [p for p in opened if set(candidates[p]) == {"runner"}]:
                opened.remove(path)
                kept.append((path, RUNNER_FROZEN))
        for path in opened[MAX_PATHS_PER_QUESTION:]:
            kept.append((path, f"more than {MAX_PATHS_PER_QUESTION} paths named by {question.id}"))
        if opened:
            grants.append(Grant(question.id, digest, tuple(opened[:MAX_PATHS_PER_QUESTION])))
    return Unfreeze(tuple(grants), tuple(kept))
