"""`questions.md` merged per question id when a base merge conflicts in it (state-vcs-locks 4.6).

The base may be absent (the file is new on both sides). Per id, in order: byte-identical sections are kept; a section
that only one side changed against the base takes that side; if exactly one side carries a human answer that side
wins; otherwise the side whose last commit touching that question's section is newer wins (the file's last commit when
line times are unknown) (a tie goes to the unit branch, `ours`).
A question that exists on one side only is kept (a main-only question is appended with its index row). When ours wins
every question and theirs adds none, the result is ours byte for byte. The same id holding a different question (title
or asked line), or a file whose sections cannot be read, is `Escalate`: it stays a conflict.
"""

from collections.abc import Sequence

from l4.specs.questions import (
    Question,
    QuestionsFile,
    _eol,
    _splice,
    _with_index,
    _with_row,
    answered_by,
    is_answered,
)
from l4.vcs.merge import Escalate


def _section(file: QuestionsFile, question: Question) -> bytes:
    return file.data[question.section.start : question.section.end]


def _human(question: Question) -> bool:
    return is_answered(question) and answered_by(question) == "human"


def _readable(file: QuestionsFile, side: str) -> None:
    if file.unreadable_ids:
        raise Escalate(f"{side} questions.md has sections the harness cannot read ({', '.join(file.unreadable_ids)})")


def _section_time(data: bytes, question: Question, lines: Sequence[int]) -> int | None:
    """The newest commit time among the lines of the question's section, or None when `lines` does not fit `data`."""
    if len(lines) != data.count(b"\n") + (0 if data.endswith(b"\n") else 1):
        return None
    first = data.count(b"\n", 0, question.section.start)
    text = data[question.section.start : question.section.end].rstrip()
    if text.endswith(b"\n---"):  # the separator belongs to whoever appends the next question
        text = text[:-4].rstrip()
    span = lines[first : first + text.count(b"\n") + 1]
    return max(span) if span else None


def merge_questions(
    base: bytes | None,
    ours: bytes,
    theirs: bytes,
    ours_newer: bool,
    *,
    ours_lines: Sequence[int] = (),
    theirs_lines: Sequence[int] = (),
) -> bytes:
    mine, other = QuestionsFile.parse(ours), QuestionsFile.parse(theirs)
    _readable(mine, "the unit branch's")
    _readable(other, "the base's")
    ancestor = QuestionsFile.parse(base) if base is not None else None
    replace: list[tuple] = []
    appended: list[Question] = []
    touched: list[str] = []
    for theirs_q in other.questions:
        ours_q = mine.get(theirs_q.id)
        if ours_q is None:
            appended.append(theirs_q)
            continue
        ours_sec, theirs_sec = _section(mine, ours_q), _section(other, theirs_q)
        if ours_sec == theirs_sec:
            continue
        if ours_q.title != theirs_q.title or ours_q.asked != theirs_q.asked:
            raise Escalate(f"{theirs_q.id} is a different question on the two sides")
        base_q = ancestor.get(theirs_q.id) if ancestor is not None else None
        base_sec = _section(ancestor, base_q) if ancestor is not None and base_q is not None else None
        if base_sec is not None and ours_sec == base_sec:
            take_theirs = True
        elif base_sec is not None and theirs_sec == base_sec:
            take_theirs = False
        elif _human(ours_q) != _human(theirs_q):
            take_theirs = _human(theirs_q)
        else:
            ours_t, theirs_t = _section_time(ours, ours_q, ours_lines), _section_time(theirs, theirs_q, theirs_lines)
            newer = ours_t >= theirs_t if ours_t is not None and theirs_t is not None else ours_newer
            take_theirs = not newer
        if take_theirs:
            replace.append((ours_q.section, theirs_sec))
            touched.append(theirs_q.id)
    if not replace and not appended:
        return ours
    data = _splice(ours, replace)
    eol = _eol(ours)
    for question in appended:
        if not data.endswith(b"\n"):
            data += eol
        data += eol + b"---" + eol + eol + _section(other, question) + eol
        touched.append(question.id)
    parsed = QuestionsFile.parse(data)
    if parsed.index is None:
        return _with_index(data, parsed)
    for qid in touched:
        parsed = QuestionsFile.parse(data)
        if parsed.index is not None and (question := parsed.get(qid)) is not None:
            data = _with_row(data, parsed.index, question)
    return data
