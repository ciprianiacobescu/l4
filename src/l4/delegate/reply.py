"""The checks of the delegate's reply (delegate-answers 6.2; L4-DLG-005, L4-DLG-014; design D7, D15).

`check_reply` keeps a reply only when every rule holds, and says which rule broke first otherwise: there is no repair
round, and a discarded reply is an escalation (the pass records `delegate.result{status: discarded}`). Pure: the unit
head is a `HeadTree` (the listing of regular files and a reader), the latest test report is a set of ids, and the
questions file is the one the answer would be written to, so that the composed answer is judged by the very checks of
`l4 questions` (`check_text`, `check_question`)."""

import re
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import PurePosixPath
from typing import Any, Literal

from l4.config import defaults as d
from l4.delegate.prompt import delegate_schema
from l4.implementer.guards import tracked_files
from l4.implementer.unfreeze import names_path
from l4.redact import Redactor
from l4.schemacheck import validate
from l4.security.protected import glob_match
from l4.specs.questions import Question, QuestionKind, QuestionsFile, unescape_text
from l4.specs.questions_cli import (
    PathEffect,
    check_question,
    check_text,
    cites_criterion,
    is_finding_question,
    suggestion_effects,
)
from l4.vcs.git import Git
from l4.verifier.verdicts import ends_with_scenario

MAX_REASON_CHARS = 1000
MAX_CHECKED = 20  # entries; the longest of each field is the next constant (review 3, minor 4)
MAX_CHECKED_CHARS = {"ref": 300, "quote": 600, "claim": 600}
LINE_WINDOW = 3  # a quote may be this many lines from the line a `path:line` reference names
MIN_QUOTE_CHARS = 12  # a shorter quote (after whitespace is folded) is in nearly any file: it shows nothing
HARNESS_WRITTEN = ("questions.md", "verification.md")  # the harness's own words, and the asker's: no evidence
HARNESS_ROOT_DIRS = (
    "vendor",
    "ci",
    "bin",
)  # what the harness writes in a root `.l4/`; the rest is the repository's
HARNESS_REASON = "cites a harness-written file (questions.md, verification.md, the harness's .l4/ files): not evidence"
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
    decision: str | None = None  # what the reply would have decided, when it was a well-formed result (never its text)
    # delegate-citations (L4-DLG-005): `retryable` is set only for a `checked` entry that does not resolve (the pass
    # asks the question once more); `checked` is the entries' `ref` and `quote`, redacted, of a reply that was a valid
    # document within the entry limits (never an entry's `claim`, never the answer's text)
    retryable: bool = False
    checked: tuple[dict[str, str], ...] = ()


def _flat(text: str) -> str:
    return " ".join(text.split())


def _safe_relative(ref: str) -> str | None:
    path = PurePosixPath(ref)
    if path.is_absolute() or not path.parts or ".." in path.parts or "" in ref.split("/"):
        return None
    return path.as_posix()


def _harness_written(path: str) -> bool:
    """What the harness or the asker wrote, so that citing it proves nothing about the repository (review F6): the
    questions file (the asker's own text), the harness's verification summary, a `.l4` folder below the root (a
    unit's ledger and evidence), the root `.l4/`'s `vendor/`, `ci/` and `bin/`, and `.l4-out/`. The rest of the root
    `.l4/` (`config.yaml`, `gates/`, `plans/`) is files a person wrote and committed: the repository's own."""
    parts = PurePosixPath(path).parts
    return (
        parts[-1] in HARNESS_WRITTEN
        or ".l4" in parts[1:]
        or (parts[0] == ".l4" and len(parts) > 1 and parts[1] in HARNESS_ROOT_DIRS)
        or parts[0] == ".l4-out"
    )


def _harness_ref(ref: str, unit_rel: str) -> bool:
    """A `checked` ref that names a file the harness or the asker wrote (`_harness_written`). A `spec:` name is
    relative to the unit's folder, so it is also read as the path it has there: `spec:.l4/ledger/r-1.jsonl` is the
    unit's ledger."""
    ref = ref.strip()
    if ref.startswith("test:"):
        return False
    if ref.startswith("spec:"):
        name = _safe_relative(ref.removeprefix("spec:").split("#", 1)[0])
        return name is not None and (_harness_written(name) or _harness_written(f"{unit_rel}/{name}"))
    found = _LINE_REF.fullmatch(ref)
    name = _safe_relative(found["path"]) if found else None
    return name is not None and _harness_written(name)


def _spec_file(name: str, head: HeadTree) -> str | None:
    """The repository path a `spec:<name>` entry names, each form only when it is a tracked regular file, in this
    order: `<unit folder>/<name>`; `<name>` itself when it starts with the unit folder's repository path (the path the
    prompt shows); for a `<name>` without `/`, the one file under the unit folder with that file name (two or more, or
    none, name no file)."""
    unit = f"{head.unit_rel}/"
    for path in (f"{unit}{name}", name if name.startswith(unit) else None):
        if path is not None and head.tracked.get(path):
            return path
    if "/" in name:
        return None
    named = [
        p for p, regular in head.tracked.items() if regular and p.startswith(unit) and p.rpartition("/")[2] == name
    ]
    return named[0] if len(named) == 1 else None


def _resolves(entry: Mapping[str, str], head: HeadTree, test_ids: Collection[str]) -> bool:
    """Whether a `checked` entry holds at the unit head: a `test:` id is in the report; a `spec:` quote is in the file
    `_spec_file` names; a `path:line` quote, whitespace folded, starts within `LINE_WINDOW` lines of the line (the
    first occurrence from `line - LINE_WINDOW` on starts in those lines), whatever line breaks the quote keeps."""
    ref, quote = entry["ref"].strip(), _flat(entry["quote"])
    if ref.startswith("test:"):
        return ref.removeprefix("test:").strip() in test_ids
    if ref.startswith("spec:"):
        name = _safe_relative(ref.removeprefix("spec:").split("#", 1)[0])
        if name is None or len(quote) < MIN_QUOTE_CHARS or _harness_written(name):
            return False
        chosen = _spec_file(name, head)
        text = head.read(chosen) if chosen is not None and not _harness_written(chosen) else None
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
    first = max(line - LINE_WINDOW, 1)
    window = _flat("\n".join(lines[first - 1 : line + LINE_WINDOW]))
    rest = _flat("\n".join(lines[first - 1 :]))
    return 0 <= rest.find(quote) < len(window)


def _frozen_hits(
    text: str, tasks: Sequence[str], frozen: Mapping[str, Sequence[str]], existing: Mapping[str, Sequence[str]]
) -> list[tuple[str, str]]:
    return [
        (path, task)
        for task in tasks
        for path in dict.fromkeys((*frozen.get(task, ()), *existing.get(task, ())))
        if names_path(text, path)
    ]


_PATH_TOKEN = re.compile(r"(?<![\w./-])[\w.][\w./-]*")


def named_paths(text: str, globs: Sequence[str]) -> list[str]:
    """The paths `text` names (a path as written, `names_path` of L4-IMP-015: "the conftest" alone names none) that one
    of `globs` matches, in the order they appear."""
    found: list[str] = []
    for token in _PATH_TOKEN.findall(text):
        path = token.rstrip(".,;:)").removeprefix("./")
        pathlike = "/" in path or "." in path.strip(".")
        hit = pathlike and any(glob_match(g, path) for g in globs) and names_path(text, path, dot_slash=True)
        if hit and path not in found:
            found.append(path)
    return found


def _cites_file(checked: Sequence[Mapping[str, str]], head: "HeadTree", files: Collection[str]) -> bool:
    """Whether a `checked` entry cites (as `path:line` or `spec:`) one of `files`."""
    for entry in checked:
        ref = entry["ref"].strip()
        if ref.startswith("spec:"):
            name = _safe_relative(ref.removeprefix("spec:").split("#", 1)[0])
            path = _spec_file(name, head) if name else None
        else:
            found = _LINE_REF.fullmatch(ref)
            path = _safe_relative(found["path"]) if found else None
        if path is not None and path in files:
            return True
    return False


def _recorded(checked: Sequence[Mapping[str, str]], redactor: Redactor) -> tuple[dict[str, str], ...]:
    """The `ref` and `quote` of each entry, redacted, for the record of a discarded reply; nothing when the entries
    break the limits (their length is then the reason, and they are not worth keeping)."""
    if len(checked) > MAX_CHECKED or any(len(e.get(k, "")) > n for e in checked for k, n in MAX_CHECKED_CHARS.items()):
        return ()
    return tuple({k: redactor.redact_text(e.get(k, "")) for k in ("ref", "quote")} for e in checked)


def check_reply(reply: Mapping[str, Any], *args: Any, **kwargs: Any) -> Kept | Discarded:
    """The reply as `_check_reply` judges it; a `Discarded` carries the decision a well-formed reply made."""
    got = _check_reply(reply, *args, **kwargs)
    decision = reply.get("decision") if isinstance(reply, Mapping) else None
    if isinstance(got, Discarded) and got.decision is None and isinstance(decision, str):
        valid = decision in {"answer", "accept", "reject", "retry", "escalate"}
        got = replace(got, decision=decision if valid else None)
    return got


def _check_reply(
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
    chore: bool = False,
    fix_task: bool = False,
    cap_only: bool = False,
    cap_only_file: str | None = None,
    judge_view_files: Collection[str] = (),
    test_globs: Sequence[str] = d.TEST_GLOBS,
    support_globs: Sequence[str] = d.TEST_SUPPORT_GLOBS,
) -> Kept | Discarded:
    """`question` is the question as `file` holds it (`file` is the questions file the answer would be written to).
    `frozen` is the frozen paths per held task (`frozen_paths`), `existing` the pre-existing tracked tests an answer
    that names them opens (`existing_tests`), `hold_kind` the kind of the hold a verdict question is about (None when
    the target is a criterion or a finding), `unfreeze` is `delegate.unfreeze`. 0.4.22 (L4-DLG-023 to L4-DLG-025):
    `chore` the question is a blocked fix chore's and `fix_task` it belongs to a fix task (nothing is unfrozen in
    one), `cap_only` the question is a cap-only criterion's and `cap_only_file` the file of its candidate test,
    `judge_view_files` the files a judge-view hold names, `test_globs` and `support_globs` `tdd.test_globs` and
    `tdd.test_support_globs`."""
    problems = validate(reply, delegate_schema()) if isinstance(reply, Mapping) else ["$: not an object"]
    if problems:
        return Discarded(f"not an l4/delegate-result@1 document: {problems[0]}")
    decision, reason, text = str(reply["decision"]), str(reply["reason"]), str(reply["text"])
    checked = tuple({k: str(v) for k, v in entry.items()} for entry in reply["checked"])
    recorded = _recorded(checked, redactor)

    def refuse(
        why: str, status: Literal["discarded", "escalated"] = "discarded", *, retryable: bool = False
    ) -> Discarded:
        return Discarded(why, status, checked=recorded, retryable=retryable)

    if reply["question"] != question.id:
        return refuse(f"the reply answers {reply['question']}, not {question.id}")
    if len(reason) > MAX_REASON_CHARS:
        return refuse(f"the reason has {len(reason)} characters: the limit is {MAX_REASON_CHARS}")
    kind = question.kind
    if kind is None or decision not in FIT[kind]:
        return refuse(f"the decision {decision} does not fit a {kind.value if kind else 'unknown'} question")
    if len(checked) > MAX_CHECKED:
        return refuse(f"the reply has {len(checked)} checked entries: the limit is {MAX_CHECKED}")
    for entry in checked:
        for key, limit in MAX_CHECKED_CHARS.items():
            if len(entry.get(key, "")) > limit:
                return refuse(f"a checked {key} has {len(entry[key])} characters: the limit is {limit}")
    if decision == "escalate":  # nothing was checked for it: only the refs are recorded, redacted
        return Kept(decision, reason, tuple({"ref": redactor.redact_text(e.get("ref", ""))} for e in checked))
    verdict, harness = kind is QuestionKind.VERDICT, kind is QuestionKind.HARNESS
    suggestion = unescape_text(question.suggestion_text)
    plain_accept = decision == "accept" and not (verdict or harness)
    if plain_accept and not suggestion:
        return refuse(f"accept needs a clarifier suggestion, and {question.id} has none")
    if not checked:
        return refuse(f"the decision {decision} has no checked entry")
    for entry in checked:
        if _harness_ref(entry["ref"], head.unit_rel):
            return refuse(f"checked {entry['ref']} {HARNESS_REASON}")
        if not _resolves(entry, head, test_ids):
            return refuse(f"checked {entry['ref']} does not resolve", retryable=True)
    if not plain_accept and (refusal := check_text(text, redactor)) is not None:
        return refuse(f"the text is refused: {refusal.message}")
    if verdict and hold_kind == "judge_view":  # L4-DLG-024: a reject escalates the unit, only a person decides it
        if decision == "reject":
            return refuse("a reject of the judge's view escalates the unit: only a person decides it")
        if decision == "accept" and not _cites_file(checked, head, judge_view_files):
            return refuse("an accept of a judge-view hold cites a file the hold names")
    if (
        verdict
        and decision == "reject"
        and hold_kind not in (None, "scope", "coverage", "judge_view")
        and not ends_with_scenario(text)
    ):
        return refuse("a reject of this hold needs a sentence WHEN ... THEN ... for a fix unit to pin")
    bare = verdict and decision == "reject" and is_finding_question(question) and not cites_criterion(question)
    if bare and not ends_with_scenario(text):  # L4-DLG-023: the fix unit's parser, its last WHEN ... THEN ...
        return refuse("a reject of this finding needs a sentence WHEN ... THEN ...: it cites no criterion")
    uncited = cap_only_file is None or not _cites_file(checked, head, (cap_only_file,))
    if verdict and decision == "accept" and cap_only and uncited:  # L4-DLG-024: the test's lines, not just its id
        return refuse(f"an accept of a cap-only criterion cites the lines of {cap_only_file or 'its test'}")
    composed = text if decision == "answer" else f"{decision} {text}" if verdict else f"{decision}: {text}"
    effective = suggestion if plain_accept else text
    if chore and not (verdict or harness):  # L4-DLG-025: the fix step would put such a file back
        hits = named_paths(effective, (*test_globs, *support_globs))
        if hits:
            return refuse(
                f"a fix task cannot change {hits[0]}: a person commits that change on the unit branch, then answers",
                "escalated",
            )
    tasks = [t for t in question.blocking_tasks if t in frozen]
    effects: tuple[PathEffect, ...] = ()
    # only a technical, product or ambiguous answer unfreezes anything (`unfreeze.unfrozen` skips the other kinds), so
    # a verdict or harness text that names a frozen test it reasons about is no unfreezing
    if not (verdict or harness) and (hits := _frozen_hits(effective, tasks, frozen, existing or {})):
        path, task = hits[0]
        would = f"the answer would unfreeze {path} of task {task} (delegate.unfreeze is false)"
        if not unfreeze:
            return (
                refuse(would, "escalated")
                if plain_accept
                else refuse(f"names the frozen path {path} of task {task}; {would}")
            )
        if not plain_accept:
            return refuse(f"names the frozen path {path} of task {task}; only the clarifier suggestion may unfreeze it")
        effects = tuple(e for e in suggestion_effects(question, frozen, existing) if e.unfreezes)
        for effect in effects:  # L4-DLG-014 (0.4.22): test files only, and nothing in a fix task
            if any(glob_match(g, effect.path) for g in support_globs):
                return refuse(
                    f"the answer would unfreeze {effect.path} of task {effect.task}, a test-support file: a "
                    "person's change (delegate.unfreeze opens test files only)",
                    "escalated",
                )
            if fix_task:
                return refuse(
                    f"the answer would unfreeze {effect.path} of task {effect.task}, a file of a fix task: a "
                    "person's change (delegate.unfreeze opens nothing in a fix task)",
                    "escalated",
                )
        stays = [e for e in suggestion_effects(question, frozen, existing) if not e.unfreezes]
        if stays:
            first = stays[0]
            return refuse(
                f"the answer would unfreeze {first.path} of task {first.task}, which stays frozen: {first.why}",
                "escalated",
            )
    form: Literal["accept", "answer"] = "accept" if plain_accept else "answer"
    if (
        refusal := check_question(
            file, question.id, form, None if plain_accept else composed, unit=unit, branch=branch, redactor=redactor
        )
    ) is not None:
        return refuse(refusal.message)
    return Kept(decision, reason, checked, form, None if plain_accept else composed, effective, effects)
