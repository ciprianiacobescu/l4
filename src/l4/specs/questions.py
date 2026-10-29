"""`questions.md` (SPEC 6): raising questions, reading answers and editing Status and suggestions without touching
a byte the harness does not own (L4-QMD-003).

The file is parsed into byte spans, not into a Markdown tree: every write is a splice of one or more spans, so the
bytes outside them (line endings, BOM, a human's notes, sections the harness does not know) are never rewritten.
Not built: re-rendering a mangled or deleted section from the ledger (`question.restored`, M1: spec-providers 1.31)
and verdict answers (L4-QMD-004).
"""

import hashlib
import re
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Literal

from l4.fsutil import UnsafeFile, atomic_write_bytes, read_regular_file
from l4.redact import Redactor
from l4.specs.base import SAFE_NAME, Criterion, SpecError

QUESTIONS_FILENAME = "questions.md"
INDEX_START = "<!-- l4:index:start -->"
INDEX_END = "<!-- l4:index:end -->"
MAX_QUESTIONS_BYTES = 2 * 1024 * 1024
MAX_TITLE_CHARS = 200
NO_TASKS = "none"  # the Blocking tasks line of a `verdict` question: it holds no task (the unit is already implemented)

_DASH = "\N{EM DASH}"
_HEADER_LINES = (
    "<!-- l4:questions v1",
    'How to answer: write under "### Answer" and set **Status** to `answered`.',
    "To accept the clarifier's suggestion as-is, set **Status** to `accepted`.",
    "Status values: open · answered · accepted · answered-by-clarifier · dismissed · superseded",
    "Kind values: technical · product · ambiguous · verdict · harness. For a `verdict` question, start the answer "
    "with `accept` or",
    "`reject`, then give your reason; for a `harness` question, with `accept` or `retry`.",
    "Do not change question IDs. Commit and push to the l4/… branch to resume the run. -->",
)
_INDEX_HEADER = ("| ID | Status | Blocking | Kind | Question |", "|----|--------|----------|------|----------|")
_HEADING_ID = re.compile(rb"^## Q-(\d+):", re.MULTILINE)
_ROW_ID = re.compile(rb"^\| Q-(\d+) \|", re.MULTILINE)
_START_LINE = re.compile(rb"^" + re.escape(INDEX_START.encode()) + rb"[ \t]*\r?$", re.MULTILINE)
_END_LINE = re.compile(rb"^" + re.escape(INDEX_END.encode()) + rb"[ \t]*\r?$", re.MULTILINE)
# a line that would be read as structure if an agent put it in a free-text field
# (a fence line too: one that never closes would hide every later question from the parser)
_STRUCTURAL = re.compile(r"^\s*(?:#{1,6}(?:\s|$)|-{3,}\s*$|\||[-*+]\s+\*\*|```|~~~)")


class QuestionKind(StrEnum):
    TECHNICAL = "technical"
    PRODUCT = "product"
    AMBIGUOUS = "ambiguous"
    VERDICT = "verdict"
    HARNESS = "harness"  # a check L4 could not decide holds its task (L4-IMP-063); answered `accept` or `retry`


@dataclass(frozen=True)
class NewQuestion:
    title: str
    kind: QuestionKind
    blocking_tasks: tuple[str, ...]
    context: str
    asked: str  # one line: when, by whom, run id, task
    options: tuple[str, ...] = ()
    criteria: tuple[Criterion, ...] = ()


_COMMENT_ENTITY = re.compile(r"&((?:amp;)*)lt;!--")


def _neutralise_comments(text: str) -> str:
    """ "<!--" would let an agent write the index markers, or hide text from the human reader. An entity that already
    looks like the replacement gains one `amp;`, so `_restore_comments` is an exact inverse."""
    return _COMMENT_ENTITY.sub(lambda m: f"&amp;{m.group(1)}lt;!--", text).replace("<!--", "&lt;!--")


def _restore_comments(text: str) -> str:
    return _COMMENT_ENTITY.sub(lambda m: f"&{m.group(1)[4:]}lt;!--" if m.group(1) else "<!--", text)


def _clean(text: str, redactor: Redactor) -> str:
    return _neutralise_comments(redactor.redact_text(text))


def _one_line(text: str, redactor: Redactor) -> str:
    return " ".join(_clean(text, redactor).split())


def _block(text: str, redactor: Redactor) -> list[str]:
    lines = _clean(text, redactor).replace("\r\n", "\n").replace("\r", "\n").strip("\n").split("\n")
    # a line that starts with a backslash is escaped too, so removing one is an exact inverse (`unescape_text`)
    return [f"\\{line}" if line.startswith("\\") or _STRUCTURAL.match(line) else line for line in lines]


def unescape_text(text: str) -> str:
    """What `_block` was given (after redaction): the text an agent or the clarifier wrote."""
    lines = (line[1:] if line.startswith("\\") else line for line in text.split("\n"))
    return _restore_comments("\n".join(lines))


def _index_region(data: bytes) -> tuple[int, int] | None:
    """(start, end) offsets of the lines between the markers, when the file has exactly one well-ordered region."""
    starts, ends = list(_START_LINE.finditer(data)), list(_END_LINE.finditer(data))
    if len(starts) == 1 and len(ends) == 1 and starts[0].start() < ends[0].start():
        return starts[0].end(), ends[0].start()
    return None


def _used_ids(data: bytes, region: tuple[int, int] | None) -> list[int]:
    """Ids from the harness-owned structure only: `## Q-NNN:` headings and rows inside the index region. A
    `Q-900` an agent typed into a Context block must not move the counter."""
    rows = _ROW_ID.findall(data[region[0] : region[1]]) if region else []
    return [int(n) for n in (*_HEADING_ID.findall(data), *rows)]


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def _render_section(qid: str, q: NewQuestion, redactor: Redactor) -> tuple[list[str], str]:
    title = _one_line(q.title, redactor)[:MAX_TITLE_CHARS] or "(untitled question)"
    tasks = ", ".join(q.blocking_tasks) or NO_TASKS
    lines = [
        "---",
        "",
        f"## {qid}: {title}",
        "",
        "- **Status:** open",
        f"- **Blocking tasks:** {tasks}",
        f"- **Kind:** {q.kind.value}",
        f"- **Asked:** {_one_line(q.asked, redactor)}",
    ]
    if q.criteria:
        lines.append("- **Criteria:** " + ", ".join(f"{c.id} ({_one_line(c.alias, redactor)})" for c in q.criteria))
    lines += ["", "### Context", *_block(q.context or "(no context given)", redactor), ""]
    if q.options:
        lines += ["### Options", *(f"{n}. {_one_line(o, redactor)}" for n, o in enumerate(q.options, 1)), ""]
    lines += ["### Answer", "<!-- write below this line -->"]
    return lines, f"| {qid} | open | {_cell(tasks)} | {q.kind.value} | {_cell(title)} |"


def raise_questions(unit_dir: Path, unit_name: str, batch: Sequence[NewQuestion], *, redactor: Redactor) -> list[str]:
    """Append one section per question and one index row each; returns the new ids (`Q-NNN`, never reused).

    Creates the file when it is missing. In an existing file the only changes are the rows inserted before the
    index end marker and the sections appended at the end; the file's line-ending style is kept.
    """
    for question in batch:
        for task in question.blocking_tasks:
            if not SAFE_NAME.match(task):
                raise ValueError(f"not a task id: {task!r}")
        if not question.blocking_tasks and question.kind is not QuestionKind.VERDICT:
            raise ValueError("a question must name at least one blocking task id")
    if not batch:
        return []
    path = unit_dir / QUESTIONS_FILENAME
    try:
        existing = read_regular_file(path, limit=MAX_QUESTIONS_BYTES)
    except FileNotFoundError:
        existing = None
    except UnsafeFile as exc:
        raise SpecError(str(exc)) from None
    if existing is None:
        eol = "\n"
        head = "\n".join(
            [f"# Questions {_DASH} {unit_name}", "", *_HEADER_LINES, "", INDEX_START, *_INDEX_HEADER, INDEX_END, ""]
        )
        data = head.encode()
    else:
        eol = "\r\n" if b"\r\n" in existing else "\n"
        data = existing
    region = _index_region(data)
    first = max(_used_ids(data, region), default=0) + 1
    ids = [f"Q-{n:03d}" for n in range(first, first + len(batch))]
    rendered = [_render_section(qid, q, redactor) for qid, q in zip(ids, batch, strict=True)]

    rows = "".join(f"{row}{eol}" for _, row in rendered).encode()
    if region is not None:
        data = data[: region[1]] + rows + data[region[1] :]
    if not data.endswith(b"\n"):
        data += eol.encode()
    data += eol.encode() + "".join(eol.join(lines) + eol for lines, _ in rendered).encode()
    atomic_write_bytes(path, data)
    if path.read_bytes() != data:
        raise SpecError(f"{path.name}: post-write verification failed")
    return ids


# --- reading: the tolerant parser (L4-QMD-002) -----------------------------------------------------------------


class QuestionStatus(StrEnum):
    OPEN = "open"
    ANSWERED = "answered"
    ACCEPTED = "accepted"
    ANSWERED_BY_CLARIFIER = "answered-by-clarifier"
    DISMISSED = "dismissed"
    SUPERSEDED = "superseded"


@dataclass(frozen=True)
class Span:
    """Byte offsets into `QuestionsFile.data`, `end` exclusive."""

    start: int
    end: int


@dataclass(frozen=True)
class Block:
    """A `### ` subsection: its heading line (with the line break) and the lines under it."""

    heading: Span
    body: Span


@dataclass(frozen=True)
class Question:
    id: str
    title: str
    status: QuestionStatus  # unknown values read as `open`
    blocking_tasks: tuple[str, ...]
    blocking_readable: bool  # False: the Blocking tasks line is empty or has a part that is not a task id
    superseded_by: str | None  # the `Q-NNN` named in a `superseded by Q-NNN` Status
    kind: QuestionKind | None
    kind_text: str
    asked: str
    section: Span  # the `## Q-NNN:` line to the last content line; the `---` separator after it is not included
    status_value: Span | None  # the text after `**Status:**`, without trailing blanks; None: no Status line
    suggestion: Block | None
    answer: Block | None
    suggestion_text: str  # comments removed, stripped
    answer_text: str  # comments removed, stripped
    context_text: str = ""  # the `### Context` and `### Options` bodies as written (neutralised, see `unescape_text`)
    options_text: str = ""
    restarted: bool = False  # the Status is `superseded by restart`: no successor, and nothing is held
    superseded_round: int | None = None  # the Status is `superseded by round <n>`: a later round replaced it
    answered_by: str = ""  # the text after `**Answered by:**` (the delegate's answer, L4-DLG-006)
    escalated_by: str = ""  # the text after `**Escalated by:**` (the delegate's escalation, L4-DLG-008)
    field_lines: tuple[tuple[str, Span], ...] = ()  # (lower-case field name, its whole line with the line break)


@dataclass(frozen=True)
class QuestionIssue:
    """Something a human should be told about (sticky note, SPEC 11): the parse itself never fails."""

    kind: Literal["unknown_status", "unsubmitted_answer", "empty_answer", "unreadable_blocking", "unreadable_section"]
    question_id: str
    detail: str = ""


_SUBSECTIONS = ("context", "options", "clarifier suggestion", "answer")
_HEADING = re.compile(rb"^## (?:Q-(\d+):[ \t]*(.*?)|.*?)[ \t]*\r?$")
_SUBHEADING = re.compile(rb"^###[ \t]+(Context|Options|Clarifier suggestion|Answer)[ \t]*\r?$", re.IGNORECASE)
_FIELD = re.compile(
    rb"^-[ \t]+\*\*(Status|Blocking tasks|Kind|Asked|Criteria|Answered by|Escalated by):\*\*[ \t]*(.*?)[ \t]*\r?$",
    re.IGNORECASE,
)
_DELEGATE_FIELDS = ("Answered by", "Escalated by")
_FENCE = re.compile(rb"^[ \t]{0,3}(```|~~~)")
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
_STATUS_WORD = re.compile(r"[A-Za-z][A-Za-z-]*")
_TASK_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
_SUCCESSOR = re.compile(r"\bsuperseded\s+by\s+`?(Q-\d+)", re.IGNORECASE)
_RESTART_SUPERSEDED = re.compile(r"\bsuperseded\s+by\s+restart\b", re.IGNORECASE)
SUPERSEDED_BY_RESTART = "superseded by restart"  # `l4 restart` (L4-OPS-004): the question belongs to the old attempt
_ROUND_SUPERSEDED = re.compile(r"\bsuperseded\s+by\s+round\s+(\d+)\b", re.IGNORECASE)
_QUESTION_HEADING = re.compile(rb"^## Q-(\d+):")
_ANSWER_MARK = b"<!-- write below this line -->"
_REPLACED_HEAD = "<!-- l4 questions --replace"
_REPLACED = re.compile(re.escape(_REPLACED_HEAD.encode()) + rb".*?-->", re.DOTALL)
_ANSWERED = frozenset({QuestionStatus.ANSWERED, QuestionStatus.ACCEPTED, QuestionStatus.ANSWERED_BY_CLARIFIER})


def _lines(data: bytes) -> list[tuple[int, int]]:
    """(start, end) of every line, `end` after the line break."""
    return [(m.start(), m.end()) for m in re.finditer(rb"[^\n]*\n|[^\n]+\Z", data)]


def _text(raw: bytes) -> str:
    return raw.decode("utf-8", errors="replace")


def _visible(raw: bytes) -> str:
    return _COMMENT.sub("", _text(raw)).strip()


def _status_of(text: str) -> QuestionStatus | None:
    word = _STATUS_WORD.search(text.strip().strip("`*_ "))
    try:
        return QuestionStatus(word.group(0).lower()) if word else None
    except ValueError:
        return None


def _tasks_of(text: str) -> tuple[tuple[str, ...], bool]:
    """(task ids, whether every part of the line was one). A line that is not fully readable holds every pending
    task (`blocked_tasks`): reading half of it would let the other half run unanswered."""
    parts = [part.strip().strip("`") for part in text.split(",")]
    tasks = tuple(t for t in parts if _TASK_KEY.fullmatch(t))
    return tasks, len(tasks) == len(parts)


def _after_separator(data: bytes, lines: list[tuple[int, int]], number: int) -> bool:
    """The nearest non-blank line above `lines[number]` is a `---`."""
    for start, stop in reversed(lines[:number]):
        text = data[start:stop].strip()
        if text:
            return text == b"---"
    return False


def _section_end(data: bytes, lines: list[tuple[int, int]], first: int, last: int) -> int:
    """End of the last content line of lines[first:last]: trailing blank lines and one `---` separator are left out."""
    end = last
    while end > first and not data[lines[end - 1][0] : lines[end - 1][1]].strip():
        end -= 1
    if end > first + 1 and data[lines[end - 1][0] : lines[end - 1][1]].strip() == b"---":
        end -= 1
        while end > first + 1 and not data[lines[end - 1][0] : lines[end - 1][1]].strip():
            end -= 1
    return lines[end - 1][1]


def _parse_section(
    data: bytes, lines: list[tuple[int, int]], first: int, last: int, number: str, title: bytes
) -> Question:
    end = _section_end(data, lines, first, last)
    status_value: Span | None = None
    fields: dict[str, str] = {}
    field_lines: dict[str, Span] = {}
    marks: list[tuple[str, int, int]] = []  # (subsection name, heading line index, line index after its heading)
    fenced = False
    fence_lines = [
        i for i in range(first + 1, last) if lines[i][0] < end and _FENCE.match(data[lines[i][0] : lines[i][1]])
    ]
    for index in range(first + 1, last):
        start, stop = lines[index]
        if start >= end:
            break
        line = data[start:stop].rstrip(b"\n")
        sub = _SUBHEADING.match(line)
        if sub and fenced and sum(i > index for i in fence_lines) % 2 == 0:
            fenced = False  # no fence line is left to close this one: it must not swallow the Answer block
        if sub and not fenced:
            marks.append((sub.group(1).decode().lower(), index, index + 1))
            continue
        if _FENCE.match(line):
            fenced = not fenced
        if fenced:
            continue
        if not marks and (field := _FIELD.match(line)):
            name = field.group(1).decode().lower()
            if name not in fields:
                fields[name] = _text(field.group(2))
                field_lines[name] = Span(start, stop)
                if name == "status":
                    status_value = Span(start + field.start(2), start + field.end(2))
    blocks: dict[str, Block] = {}
    for position, (name, heading, body_first) in enumerate(marks):
        body_end = lines[marks[position + 1][1]][0] if position + 1 < len(marks) else end
        body_start = min(lines[body_first][0] if body_first < len(lines) else end, body_end)
        blocks.setdefault(name, Block(Span(lines[heading][0], lines[heading][1]), Span(body_start, body_end)))
    kind_text = fields.get("kind", "").strip("`*_ ")
    try:
        kind: QuestionKind | None = QuestionKind(kind_text.lower())
    except ValueError:
        kind = None
    suggestion, answer = blocks.get("clarifier suggestion"), blocks.get("answer")
    context, options = blocks.get("context"), blocks.get("options")
    tasks, readable = _tasks_of(fields.get("blocking tasks", ""))
    if kind is QuestionKind.VERDICT and fields.get("blocking tasks", "").strip("`*_ ").lower() in ("", NO_TASKS):
        tasks, readable = (), True
    successor = _SUCCESSOR.search(fields.get("status", ""))
    return Question(
        id=f"Q-{number}", title=_text(title), status=_status_of(fields.get("status", "")) or QuestionStatus.OPEN,
        blocking_tasks=tasks, blocking_readable=readable, superseded_by=successor.group(1) if successor else None,
        kind=kind, kind_text=kind_text,
        asked=fields.get("asked", ""), section=Span(lines[first][0], end), status_value=status_value,
        suggestion=suggestion, answer=answer,
        suggestion_text=_visible(data[suggestion.body.start : suggestion.body.end]) if suggestion else "",
        answer_text=_visible(data[answer.body.start : answer.body.end]) if answer else "",
        context_text=_visible(data[context.body.start : context.body.end]) if context else "",
        options_text=_visible(data[options.body.start : options.body.end]) if options else "",
        restarted=bool(_RESTART_SUPERSEDED.search(fields.get("status", ""))) and not successor,
        superseded_round=int(later.group(1)) if (later := _ROUND_SUPERSEDED.search(fields.get("status", ""))) else None,
        answered_by=fields.get("answered by", ""), escalated_by=fields.get("escalated by", ""),
        field_lines=tuple(field_lines.items()),
    )  # fmt: skip


def _index_span(data: bytes) -> Span | None:
    region = _index_region(data)
    if region is None:
        return None
    start = region[0] + (
        2 if data[region[0] : region[0] + 2] == b"\r\n" else 1
    )  # the rows start after the marker's line break
    return Span(start, region[1])


@dataclass(frozen=True)
class QuestionsFile:
    data: bytes
    questions: tuple[Question, ...]
    index: Span | None  # the lines between the index markers; None: the file has no well-formed index
    issues: tuple[QuestionIssue, ...]

    @classmethod
    def parse(cls, source: bytes | str) -> "QuestionsFile":
        """Never raises on content: whatever a human did to the file, the rest of it is still read."""
        data = source.encode("utf-8") if isinstance(source, str) else source
        index = _index_span(data)
        lines = _lines(data)
        headings: list[tuple[int, re.Match[bytes]]] = []
        fenced = False
        hidden: list[str] = []  # question headings seen inside the open fence
        lost: list[str] = []  # question headings no section was read for
        for number, (start, stop) in enumerate(lines):
            line = data[start:stop].rstrip(b"\n")
            in_index = index is not None and index.start <= start < index.end
            heading_id = _QUESTION_HEADING.match(line)
            if fenced and heading_id and not in_index and _after_separator(data, lines, number):
                fenced, hidden = False, []  # the harness writes `---` before every section: the fence never closed
            if _FENCE.match(line):
                fenced, hidden = not fenced, []
            elif fenced and heading_id:
                hidden.append(f"Q-{heading_id.group(1).decode()}")
            if heading_id and in_index:
                lost.append(f"Q-{heading_id.group(1).decode()}")
            if not fenced and (match := _HEADING.match(line)) and not in_index:
                headings.append((number, match))
        questions = []
        for position, (first, match) in enumerate(headings):
            if match.group(1) is None:
                continue  # a section of someone else's: it ends the previous question and is never read
            last = headings[position + 1][0] if position + 1 < len(headings) else len(lines)
            questions.append(_parse_section(data, lines, first, last, match.group(1).decode(), match.group(2)))
        # a fence that never closes ends the read of the file: what it hid is unknown, so it holds every pending task
        lost += hidden if fenced else []
        unreadable = [QuestionIssue("unreadable_section", qid) for qid in dict.fromkeys(lost)]
        return cls(data, tuple(questions), index, (*_issues(questions, data), *unreadable))

    @classmethod
    def load(cls, path: Path) -> "QuestionsFile | None":
        """None when the unit has no questions file."""
        try:
            return cls.parse(read_regular_file(path, limit=MAX_QUESTIONS_BYTES))
        except FileNotFoundError:
            return None
        except UnsafeFile as exc:
            raise SpecError(str(exc)) from None

    def get(self, qid: str) -> Question | None:
        return next((q for q in self.questions if q.id == qid), None)

    @property
    def unreadable_ids(self) -> tuple[str, ...]:
        """Question ids the file has a heading for and the parse read no section of (`blocked_tasks(unreadable=)`)."""
        return tuple(i.question_id for i in self.issues if i.kind == "unreadable_section")

    def set_status(self, qid: str, status: QuestionStatus) -> "QuestionsFile":
        """Replace the text after `**Status:**` and update that question's index row; nothing else changes."""
        question = _require(self, qid)
        if question.status_value is None:
            raise SpecError(f"{qid} has no Status line")
        return _edited(self, [(question.status_value, status.value.encode())], row_of=qid)

    def set_field(self, qid: str, name: str, value: str) -> "QuestionsFile":
        """The harness-owned field line `- **<name>:** <value>` (`Answered by` or `Escalated by`, L4-QMD-003): an
        existing line of that name is replaced, else the line goes right after the Status line. The value is put on
        one line, with HTML comment markers neutralised; the caller redacts it. Every other byte, the line endings and a
        BOM stay."""
        if name not in _DELEGATE_FIELDS:
            raise SpecError(f"{name} is not a field the harness writes")
        question = _require(self, qid)
        eol = _eol(self.data)
        shown = _neutralise_comments(" ".join(value.split())).replace("-->", "--&gt;")  # a reply's words reach it
        line = f"- **{name}:** {shown}".encode()
        lines = dict(question.field_lines)
        if (old := lines.get(name.lower())) is not None:
            tail = self.data[old.start : old.end]
            kept = tail[len(tail.rstrip(b"\r\n")) :]
            return _edited(self, [(old, line + kept)])
        status = lines.get("status")
        if status is None:
            raise SpecError(f"{qid} has no Status line")
        if self.data[status.start : status.end].endswith(b"\n"):
            return _edited(self, [(Span(status.end, status.end), line + eol)])
        return _edited(self, [(Span(status.end, status.end), eol + line)])

    def supersede_by_restart(self, qid: str) -> "QuestionsFile":
        """Status `superseded by restart` (L4-OPS-004): the question was about the old attempt, and no question took
        over. Unlike a bare `superseded` it holds no task (see `holds`). The index row follows."""
        question = _require(self, qid)
        if question.status_value is None:
            raise SpecError(f"{qid} has no Status line")
        return _edited(self, [(question.status_value, SUPERSEDED_BY_RESTART.encode())], row_of=qid)

    def supersede_by_round(self, qid: str, round_no: int) -> "QuestionsFile":
        """Status `superseded by round <n>` (L4-OPS-014): a verdict question of an earlier verification round that a
        later round replaced (a person fixed the spec instead of answering). Like `superseded by restart` it holds no
        task (see `holds`). The index row follows."""
        question = _require(self, qid)
        if question.status_value is None:
            raise SpecError(f"{qid} has no Status line")
        return _edited(self, [(question.status_value, f"superseded by round {round_no}".encode())], row_of=qid)

    def set_suggestion(self, qid: str, text: str, *, redactor: Redactor) -> "QuestionsFile":
        """Replace the body of the *Clarifier suggestion* block, or add the block before `### Answer`. The text is
        redacted and neutralised like every other free text the harness writes."""
        question = _require(self, qid)
        eol = _eol(self.data)
        body = eol.join(line.encode() for line in _block(text or "(empty)", redactor)) + eol
        heading = b"### Clarifier suggestion" + eol
        if question.suggestion is not None:
            span = question.suggestion.body
            more = span.end != question.section.end  # another subsection follows: keep the blank line before it
            return _edited(self, [(span, body + (eol if more else b""))])
        if question.answer is not None:
            at = question.answer.heading.start
            return _edited(self, [(Span(at, at), heading + body + eol)])
        at = question.section.end
        lead = b"" if self.data[:at].endswith(b"\n") else eol
        return _edited(self, [(Span(at, at), lead + eol + heading + body)])

    def with_option_suggestion(self, qid: str, *, redactor: Redactor) -> "QuestionsFile":
        """The file with `qid`'s `### Clarifier suggestion` block added from option 1 (`option_suggestion`), as
        `set_suggestion` writes it: before `### Answer`, redacted and neutralised. The file itself when the question
        takes no option 1. Only the form `accept` of `l4 questions` writes the block (L4-QMD-008): `load` never adds
        one."""
        text = option_suggestion(_require(self, qid))
        return self if text is None else self.set_suggestion(qid, text, redactor=redactor)

    def set_answer(self, qid: str, text: str) -> "QuestionsFile":
        """Replace the body of the `### Answer` block with the comment line `<!-- write below this line -->` (kept when
        the block has it), the text and one line end, or add the block at the end of the section. Spans only: the
        text is the caller's (`questions_cli.check_text` has refused what the file would read as structure), and the
        file's line endings are kept. The Status is `set_status`'s."""
        question = _require(self, qid)
        eol = _eol(self.data)
        lines = re.split(r"\r\n|\r|\n", text.strip("\r\n"))
        body = eol.join(line.encode() for line in lines) + eol
        if question.answer is None:
            at = question.section.end
            lead = b"" if self.data[:at].endswith(b"\n") else eol
            return _edited(self, [(Span(at, at), lead + eol + b"### Answer" + eol + body)])
        span = question.answer.body
        old = self.data[span.start : span.end]
        marked = next((line.strip() for line in old.splitlines() if line.strip() == _ANSWER_MARK), None)
        more = span.end != question.section.end  # another subsection follows: keep the blank line before it
        head = marked + eol if marked is not None else b""
        return _edited(self, [(span, head + body + (eol if more else b""))])

    def replace_answer(self, qid: str, text: str, *, who: str, on: str) -> "QuestionsFile":
        """`answer --replace` (L4-QMD-010): the body of `### Answer` becomes `text` (as `set_answer` writes it), and the
        previous answer stays under it in an HTML comment, one for each replacement, oldest first. `_visible` removes
        comments, so the answer, its digest and the reason of the verdict hold the new text only. Each line of the
        old answer is quoted with `> ` (no line reads as structure) and `<!--` and `-->` in it are defused. The
        Status is `set_status`'s. The harness-owned `Answered by:` line goes: the delegate did not write these words."""
        question = _require(self, qid)
        if question.answer is None:
            raise SpecError(f"{qid} has no Answer block")
        eol = _eol(self.data)
        span = question.answer.body
        old = self.data[span.start : span.end]
        history = [m.group(0) for m in _REPLACED.finditer(old)]
        previous = question.answer_text.replace("-->", "--&gt;").replace("<!--", "&lt;!--")
        stamp = " ".join(f"{who} on {on}".replace("-->", "--&gt;").replace("<!--", "&lt;!--").split())
        lines = [
            f"{_REPLACED_HEAD} by {stamp}; previous answer:",
            *(f"> {line}" for line in previous.splitlines()),
            "-->",
        ]
        history.append(eol.join(line.encode() for line in lines))
        marked = next((line.strip() for line in old.splitlines() if line.strip() == _ANSWER_MARK), None)
        more = span.end != question.section.end
        body = eol.join(line.encode() for line in re.split(r"\r\n|\r|\n", text.strip("\r\n"))) + eol
        head = marked + eol if marked is not None else b""
        trail = b"".join(entry + eol for entry in history)
        edits = [(span, head + body + trail + (eol if more else b""))]
        if (field := dict(question.field_lines).get("answered by")) is not None:
            edits.append((field, b""))
        return _edited(self, edits)

    def refresh_index(self) -> "QuestionsFile":
        """Rewrite the index rows whose Status no longer matches their section: a human changes the Status in the
        section, which is the file's truth, and does not touch the table. A missing row stays missing (its id is
        reserved by the row of a deleted section, see `_with_row`); a file without an index is left as it is."""
        file = self
        for qid in [q.id for q in self.questions]:
            if file.index is None or (question := file.get(qid)) is None:
                break
            pattern = re.compile(rb"^\| " + re.escape(qid.encode()) + rb" \| ([^|\r\n]*?) \|[^\r\n]*", re.MULTILINE)
            row = pattern.search(file.data, file.index.start, file.index.end)
            if row is not None and row.group(1).decode() != question.status.value:
                file = QuestionsFile.parse(_with_row(file.data, file.index, question))
        return file

    def save(self, path: Path) -> None:
        atomic_write_bytes(path, self.data)
        if path.read_bytes() != self.data:
            raise SpecError(f"{path.name}: post-write verification failed")


def _issues(questions: Sequence[Question], data: bytes) -> Iterable[QuestionIssue]:
    for q in questions:
        if q.status_value is not None:
            written = _text(data[q.status_value.start : q.status_value.end])
            if _status_of(written) is None:
                yield QuestionIssue("unknown_status", q.id, written)
        if q.status is QuestionStatus.OPEN and q.answer_text:
            yield QuestionIssue("unsubmitted_answer", q.id)
        elif q.status in _ANSWERED and effective_answer(q) is None:
            yield QuestionIssue("empty_answer", q.id, q.status.value)
        if not q.blocking_readable and not is_answered(q):
            yield QuestionIssue("unreadable_blocking", q.id)


# --- answer semantics (L4-QMD-002, L4-QMD-005) -----------------------------------------------------------------


def question_titles(unit_dir: Path) -> dict[str, str]:
    """question id -> its title as the file holds it (redacted and on one line), for the events that announce it."""
    file = QuestionsFile.load(unit_dir / QUESTIONS_FILENAME)
    return {q.id: q.title for q in file.questions} if file is not None else {}


def effective_answer(question: Question) -> str | None:
    """What an implementer is given for a question: the human's text for `answered`, the *Clarifier suggestion* for
    `accepted` and `answered-by-clarifier` (as written, without the neutralising `set_suggestion` applies to a text
    that could read as structure). None for every other Status, and for an empty text."""
    if question.status is QuestionStatus.ANSWERED:
        return question.answer_text or None
    if question.status in (QuestionStatus.ACCEPTED, QuestionStatus.ANSWERED_BY_CLARIFIER):
        return unescape_text(question.suggestion_text) or None
    return None


_EDIT_TICKED = re.compile(r"Edit `(?P<path>[^`\s]+)`: (?P<rest>\S.*)", re.DOTALL)
_EDIT_BARE = re.compile(r"Edit (?P<path>[^`\s:]+): (?P<rest>\S.*)", re.DOTALL)
_OPTION_NUMBER = re.compile(r"^\s*\d+\.\s*")


def edit_option(text: str) -> str | None:
    """A technical question's option as a suggested edit (L4-IMP-004): "Edit `<path>`: <change>" or "Edit <path>:
    <change>". A bare path is one token with no whitespace, backtick or colon that holds a `/` or a `.`: "Edit the
    test: ..." names no file. Returns the backticked form, or None. The path is not checked against the work tree: a
    path that names no frozen file unfreezes nothing (`unfreeze.unfrozen`)."""
    text = text.strip()
    if (found := _EDIT_TICKED.fullmatch(text)) is None:
        found = _EDIT_BARE.fullmatch(text)
        if found is not None and not ("/" in found["path"] or "." in found["path"]):
            return None
    if found is None:
        return None
    return f"Edit `{found['path']}`: {found['rest']}"


def option_suggestion(question: Question) -> str | None:
    """What `accept` takes from option 1 when the question has no suggestion (L4-QMD-008): an open technical question
    with no `### Clarifier suggestion` block, whose option 1 is an edit (`edit_option`). A block that exists, an
    `(empty)` one included, is the clarifier's or the harness's decision and is never replaced."""
    if (
        question.status is not QuestionStatus.OPEN
        or question.kind is not QuestionKind.TECHNICAL
        or question.suggestion is not None
    ):
        return None
    options = [
        _OPTION_NUMBER.sub("", line) for line in unescape_text(question.options_text).splitlines() if line.strip()
    ]
    return edit_option(options[0]) if options else None


def accept_text(question: Question) -> str:
    """What `accept` takes (L4-QMD-008): the suggestion as written, else option 1 (`option_suggestion`), else ""."""
    return unescape_text(question.suggestion_text) or option_suggestion(question) or ""


_HARNESS_WORD = re.compile(r"(accept|retry)(?=[\s:,.;!]|$)", re.IGNORECASE)


def harness_decision(text: str) -> Literal["accept", "retry"] | None:
    """The first word of a harness answer: `accept` or `retry` (case-insensitive, then a space, `:`, `,` or the end)."""
    found = _HARNESS_WORD.match(text.strip())
    return found.group(1).lower() if found else None  # type: ignore[return-value]


def harness_answer(question: Question) -> Literal["accept", "retry"] | None:
    """What a harness question was answered (L4-IMP-063): Status `answered` with a text whose first word is `accept` or
    `retry`, or Status `dismissed`, which reads as `retry`. Any other answer is not one: None."""
    if question.status is QuestionStatus.DISMISSED:
        return "retry"
    if question.status is not QuestionStatus.ANSWERED:
        return None
    return harness_decision(question.answer_text)


def is_answered(question: Question) -> bool:
    """The Status is explicit and there is something to consume. A draft under `open` is not an answer. A status
    that needs a text (`answered`, `accepted`, `answered-by-clarifier`) but has none is not answered either: the
    implementer would be told nothing and would ask again. A harness question is answered only by `accept` or
    `retry`."""
    if question.kind is QuestionKind.HARNESS:
        return harness_answer(question) is not None
    return question.status is QuestionStatus.DISMISSED or effective_answer(question) is not None


def answered_by(question: Question) -> Literal["human", "clarifier"]:
    return "clarifier" if question.status is QuestionStatus.ANSWERED_BY_CLARIFIER else "human"


def answer_sha256(question: Question) -> str | None:
    """Hash of the effective answer (UTF-8, comments and surrounding whitespace removed, before redaction): what the
    implementer reads, so a later edit of exactly that text is what L4-QMD-006 calls an override."""
    answer = effective_answer(question)
    return hashlib.sha256(answer.encode("utf-8")).hexdigest() if answer is not None else None


def holds(
    questions: Iterable[Question], pending: Iterable[str], unreadable: Collection[str] = ()
) -> dict[str, frozenset[str]]:
    """Per question id, the pending task keys it still holds back (L4-QMD-005); empty sets are left out. Fail closed
    where the file cannot be read: a question whose Blocking tasks line is unreadable, and an id in `unreadable`
    (`QuestionsFile.unreadable_ids`), hold every pending task. A superseded question holds the tasks its named
    successor does not list: with no successor in the file nothing took over. The exceptions are `superseded by
    restart` (`l4 restart`) and `superseded by round <n>` (L4-OPS-014): the question of an old attempt or round,
    which holds nothing."""
    every, all_questions = frozenset(pending), list(questions)
    by_id = {q.id: q for q in all_questions}
    held = {qid: every for qid in unreadable}
    for q in all_questions:
        if is_answered(q) or (q.status is QuestionStatus.SUPERSEDED and (q.restarted or q.superseded_round)):
            continue  # a question that a restart or a later round superseded belongs to the old attempt
        if not q.blocking_readable:
            held[q.id] = every
            continue
        mine = every & set(q.blocking_tasks)
        if q.status is QuestionStatus.SUPERSEDED and (successor := by_id.get(q.superseded_by or "")) is not None:
            mine -= set(successor.blocking_tasks)
        held[q.id] = held.get(q.id, frozenset()) | mine
    return {qid: tasks for qid, tasks in held.items() if tasks}


def blocked_tasks(
    questions: Iterable[Question], pending: Iterable[str], unreadable: Collection[str] = ()
) -> frozenset[str]:
    """The pending task keys that some question still holds back (see `holds`)."""
    return frozenset().union(*holds(questions, pending, unreadable).values())


# --- writing: section-scoped edits (L4-QMD-003) ----------------------------------------------------------------


def _eol(data: bytes) -> bytes:
    return b"\r\n" if b"\r\n" in data else b"\n"


def _splice(data: bytes, edits: Sequence[tuple[Span, bytes]]) -> bytes:
    """Apply non-overlapping edits. Each caller derives its spans from the parse (a Status value, a block body, an
    insertion point), so the bytes outside them are not touched by construction."""
    out, pos = bytearray(), 0
    for span, new in sorted(edits, key=lambda e: e[0].start):
        if span.start < pos:
            raise ValueError("overlapping edits")
        out += data[pos : span.start] + new
        pos = span.end
    out += data[pos:]
    return bytes(out)


def _row(q: Question) -> str:
    def cell(text: str) -> str:
        return text.replace("|", "\\|")

    blocking = ", ".join(q.blocking_tasks) or (NO_TASKS if q.kind is QuestionKind.VERDICT else "")
    return f"| {q.id} | {q.status.value} | {cell(blocking)} | {cell(q.kind_text)} | {cell(q.title)} |"


def _with_index(data: bytes, parsed: "QuestionsFile") -> bytes:
    """A file that has no index gets one, built from its sections, after the instruction comment (else the title)."""
    eol = _eol(data)
    rows = b"".join(line.encode() + eol for line in (*_INDEX_HEADER, *(_row(q) for q in parsed.questions)))
    block = eol + INDEX_START.encode() + eol + rows + INDEX_END.encode() + eol
    comment = re.search(rb"<!-- l4:questions.*?-->[ \t]*\r?\n", data, re.DOTALL)
    title = re.search(rb"^(?:\xef\xbb\xbf)?# .*\n", data, re.MULTILINE)
    bom = 3 if data.startswith(b"\xef\xbb\xbf") else 0
    at = comment.end() if comment else title.end() if title else bom
    return _splice(data, [(Span(at, at), block)])


def _with_row(data: bytes, index: Span, question: Question) -> bytes:
    """Only the index row of `qid` changes. The rows of other ids stay as they are: a row whose section a human
    deleted is what keeps its id from being reused (L4-QMD-004)."""
    row = _row(question).encode()
    pattern = re.compile(rb"^\| " + re.escape(question.id.encode()) + rb" \|[^\r\n]*", re.MULTILINE)
    old = pattern.search(data, index.start, index.end)
    if old:
        return _splice(data, [(Span(old.start(), old.end()), row)])
    return _splice(data, [(Span(index.end, index.end), row + _eol(data))])


def _edited(file: QuestionsFile, edits: Sequence[tuple[Span, bytes]], *, row_of: str | None = None) -> QuestionsFile:
    data = _splice(file.data, edits)
    parsed = QuestionsFile.parse(data)
    if parsed.index is None:
        data = _with_index(data, parsed)
    elif row_of is not None and (question := parsed.get(row_of)) is not None:
        data = _with_row(data, parsed.index, question)
    return QuestionsFile.parse(data)


def _require(file: QuestionsFile, qid: str) -> Question:
    question = file.get(qid)
    if question is None:
        raise SpecError(f"{QUESTIONS_FILENAME} has no section for {qid}")
    return question
