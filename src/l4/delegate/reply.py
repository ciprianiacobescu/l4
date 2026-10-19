"""The checks of the delegate's reply (delegate-answers 6.2; L4-DLG-005, L4-DLG-014; design D7, D15).

`check_reply` keeps a reply only when every rule holds, and says which rule broke first otherwise: there is no repair
round, and a discarded reply is an escalation (the pass records `delegate.result{status: discarded}`). Pure: the unit
head is a `HeadTree` (the listing of regular files and a reader), the latest test report is a set of ids, and the
questions file is the one the answer would be written to, so that the composed answer is judged by the very checks of
`l4 questions` (`check_text`, `check_question`)."""

import re
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Literal

from l4.delegate.prompt import delegate_schema
from l4.implementer.guards import tracked_files
from l4.implementer.unfreeze import names_path
from l4.redact import Redactor
from l4.schemacheck import validate
from l4.specs.questions import Question, QuestionKind, QuestionsFile, unescape_text
from l4.specs.questions_cli import PathEffect, check_question, check_text, suggestion_effects
from l4.vcs.git import Git
from l4.verifier.verdicts import ends_with_scenario

MAX_REASON_CHARS = 1000
MAX_CHECKED = 20  # entries; the longest of each field is the next constant (review 3, minor 4)
MAX_CHECKED_CHARS = {"ref": 300, "quote": 600, "claim": 600}
LINE_WINDOW = 3  # a quote may be this many lines from the line a `path:line` reference names
MIN_QUOTE_CHARS = 12  # a shorter quote (after whitespace is folded) is in nearly any file: it shows nothing
HARNESS_WRITTEN = ("questions.md", "verification.md")  # the harness's own words, and the asker's: no evidence
FIT: Mapping[QuestionKind, tuple[str, ...]] = {
    QuestionKind.TECHNICAL: ("answer", "accept", "escalate"),
    QuestionKind.PRODUCT: ("answer", "accept", "escalate"),
    QuestionKind.AMBIGUOUS: ("answer", "accept", "escalate"),
    QuestionKind.VERDICT: ("accept", "reject", "escalate"),
    QuestionKind.HARNESS: ("accept", "retry", "escalate"),
}
_LINE_REF = re.compile(r"(?P<path>[^\s:][^:]*):(?P<line>[0-9]+)(?:-[0-9]+)?")


@dataclass(frozen=True)
class HeadTree:
    """The unit head as the checks need it: `tracked` maps every path to whether it is a regular file (a symlink or a
    submodule is not), `read` gives a regular file's text, `unit_rel` is the unit's folder relative to the repository
    (what a `spec:` reference is relative to)."""

    tracked: Mapping[str, bool]
    read: Callable[[str], str | None]
    unit_rel: str

    @classmethod
    def at(cls, git: Git, rev: str, unit_rel: str) -> "HeadTree":
        listed = dict(tracked_files(git.run_bytes("ls-tree", "-r", "-z", rev)))

        def read(path: str) -> str | None:
            if not listed.get(path):
                return None
            done = git.run_bytes("show", f"{rev}:{path}", check=False)
            return done.decode("utf-8", errors="replace")

        return cls(listed, read, unit_rel)


@dataclass(frozen=True)
class Kept:
    """A reply the harness may act on. `decision` `escalate` writes nothing: the question goes to a person. Otherwise
    `form` and `text` are what `build_edit` takes (`accept`/None for the clarifier's suggestion, `answer`/the composed
    text for the rest), `effective` is the answer as the file will read it, and `unfreezes` the frozen paths an accepted
    suggestion opens (only with `delegate.unfreeze: true`)."""

    decision: str
    reason: str
    checked: tuple[Mapping[str, str], ...]
    form: Literal["accept", "answer"] | None = None
    text: str | None = None
    effective: str = ""
    unfreezes: tuple[PathEffect, ...] = ()

    @property
    def escalates(self) -> bool:
        return self.decision == "escalate"


@dataclass(frozen=True)
class Discarded:
    """`status` is what `delegate.result` records: `discarded` for a reply that breaks a rule, `escalated` for a
    well-formed `accept` that the unfreeze rule keeps from being written (L4-DLG-014). Either way the question goes to
    a person; `reason` names the first rule that broke."""

    reason: str
    status: Literal["discarded", "escalated"] = "discarded"


def _flat(text: str) -> str:
    return " ".join(text.split())


def _safe_relative(ref: str) -> str | None:
    path = PurePosixPath(ref)
    if path.is_absolute() or not path.parts or ".." in path.parts or "" in ref.split("/"):
        return None
    return path.as_posix()


def _harness_written(path: str) -> bool:
    """The questions file (the asker's own text), the harness's verification summary and anything under `.l4/` say what
    the harness or the asker wrote: citing them proves nothing about the repository (review F6)."""
    parts = PurePosixPath(path).parts
    return ".l4" in parts or parts[-1] in HARNESS_WRITTEN


def _resolves(entry: Mapping[str, str], head: HeadTree, test_ids: Collection[str]) -> bool:
    ref, quote = entry["ref"].strip(), _flat(entry["quote"])
    if ref.startswith("test:"):
        return ref.removeprefix("test:").strip() in test_ids
    if ref.startswith("spec:"):
        name = _safe_relative(ref.removeprefix("spec:").split("#", 1)[0])
        if name is None or len(quote) < MIN_QUOTE_CHARS or _harness_written(name):
            return False
        text = head.read(f"{head.unit_rel}/{name}") if head.tracked.get(f"{head.unit_rel}/{name}") else None
        return text is not None and quote in _flat(text)
    found = _LINE_REF.fullmatch(ref)
    if found is None or len(quote) < MIN_QUOTE_CHARS:
        return False
    path, line = _safe_relative(found["path"]), int(found["line"])
    if path is None or not head.tracked.get(path) or _harness_written(path):
        return False
    text = head.read(path)
    if text is None:
        return False
    lines = text.splitlines()
    span = max(len(entry["quote"].splitlines()), 1)
    for start in range(max(line - LINE_WINDOW, 1), line + LINE_WINDOW + 1):
        if quote in _flat("\n".join(lines[start - 1 : start - 1 + span])):
            return True
    return False


def _frozen_hits(
    text: str, tasks: Sequence[str], frozen: Mapping[str, Sequence[str]], existing: Mapping[str, Sequence[str]]
) -> list[tuple[str, str]]:
    return [
        (path, task)
        for task in tasks
        for path in dict.fromkeys((*frozen.get(task, ()), *existing.get(task, ())))
        if names_path(text, path)
    ]


def check_reply(
    reply: Mapping[str, Any],
    question: Question,
    file: QuestionsFile,
    *,
    head: HeadTree,
    test_ids: Collection[str],
    frozen: Mapping[str, Sequence[str]],
    unit: str,
    branch: str,
    redactor: Redactor,
    hold_kind: str | None = None,
    unfreeze: bool = False,
    existing: Mapping[str, Sequence[str]] | None = None,
) -> Kept | Discarded:
    """`question` is the question as `file` holds it (`file` is the questions file the answer would be written to).
    `frozen` is the frozen paths per held task (`frozen_paths`), `existing` the pre-existing tracked tests an answer
    that names them opens (`existing_tests`), `hold_kind` the kind of the hold a verdict question is about (None when
    the target is a criterion or a finding), `unfreeze` is `delegate.unfreeze`."""
    problems = validate(reply, delegate_schema()) if isinstance(reply, Mapping) else ["$: not an object"]
    if problems:
        return Discarded(f"not an l4/delegate-result@1 document: {problems[0]}")
    decision, reason, text = str(reply["decision"]), str(reply["reason"]), str(reply["text"])
    checked = tuple({k: str(v) for k, v in entry.items()} for entry in reply["checked"])
    if reply["question"] != question.id:
        return Discarded(f"the reply answers {reply['question']}, not {question.id}")
    if len(reason) > MAX_REASON_CHARS:
        return Discarded(f"the reason has {len(reason)} characters: the limit is {MAX_REASON_CHARS}")
    kind = question.kind
    if kind is None or decision not in FIT[kind]:
        return Discarded(f"the decision {decision} does not fit a {kind.value if kind else 'unknown'} question")
    if len(checked) > MAX_CHECKED:
        return Discarded(f"the reply has {len(checked)} checked entries: the limit is {MAX_CHECKED}")
    for entry in checked:
        for key, limit in MAX_CHECKED_CHARS.items():
            if len(entry.get(key, "")) > limit:
                return Discarded(f"a checked {key} has {len(entry[key])} characters: the limit is {limit}")
    if decision == "escalate":  # nothing was checked for it: only the refs are recorded, redacted
        return Kept(decision, reason, tuple({"ref": redactor.redact_text(e.get("ref", ""))} for e in checked))
    verdict, harness = kind is QuestionKind.VERDICT, kind is QuestionKind.HARNESS
    suggestion = unescape_text(question.suggestion_text)
    plain_accept = decision == "accept" and not (verdict or harness)
    if plain_accept and not suggestion:
        return Discarded(f"accept needs a clarifier suggestion, and {question.id} has none")
    if not checked:
        return Discarded(f"the decision {decision} has no checked entry")
    for entry in checked:
        if not _resolves(entry, head, test_ids):
            return Discarded(f"checked {entry['ref']} does not resolve")
    if not plain_accept and (refusal := check_text(text, redactor)) is not None:
        return Discarded(f"the text is refused: {refusal.message}")
    if (
        verdict
        and decision == "reject"
        and hold_kind not in (None, "scope", "coverage")
        and not ends_with_scenario(text)
    ):
        return Discarded("a reject of this hold needs a sentence WHEN ... THEN ... for a fix unit to pin")
    composed = text if decision == "answer" else f"{decision} {text}" if verdict else f"{decision}: {text}"
    effective = suggestion if plain_accept else text
    tasks = [t for t in question.blocking_tasks if t in frozen]
    effects: tuple[PathEffect, ...] = ()
    # only a technical, product or ambiguous answer unfreezes anything (`unfreeze.unfrozen` skips the other kinds), so
    # a verdict or harness text that names a frozen test it reasons about is no unfreezing
    if not (verdict or harness) and (hits := _frozen_hits(effective, tasks, frozen, existing or {})):
        path, task = hits[0]
        would = f"the answer would unfreeze {path} of task {task} (delegate.unfreeze is false)"
        if not unfreeze:
            return (
                Discarded(would, "escalated")
                if plain_accept
                else Discarded(f"names the frozen path {path} of task {task}; {would}")
            )
        if not plain_accept:
            return Discarded(
                f"names the frozen path {path} of task {task}; only the clarifier suggestion may unfreeze it"
            )
        effects = tuple(e for e in suggestion_effects(question, frozen, existing) if e.unfreezes)
        stays = [e for e in suggestion_effects(question, frozen, existing) if not e.unfreezes]
        if stays:
            first = stays[0]
            return Discarded(
                f"the answer would unfreeze {first.path} of task {first.task}, which stays frozen: {first.why}",
                "escalated",
            )
    form: Literal["accept", "answer"] = "accept" if plain_accept else "answer"
    if (
        refusal := check_question(
            file, question.id, form, None if plain_accept else composed, unit=unit, branch=branch, redactor=redactor
        )
    ) is not None:
        return Discarded(refusal.message)
    return Kept(decision, reason, checked, form, None if plain_accept else composed, effective, effects)
