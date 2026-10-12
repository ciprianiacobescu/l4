"""`feedback.md` (SPEC 6.3): a person's requests for changes to an open unit, read and edited without touching a byte
the harness does not own (L4-FBK-001, L4-FBK-002).

The file copies `questions.md` on purpose (`l4.specs.questions`): a header comment, an index between markers, one
`## FB-NNN: title` section per item, byte-span edits and ids that are never reused. The person owns the title, the
*Kind*, *Where*, *Env* and *Lesson* lines, the *Code*, *Feedback* and *When / Then* blocks and the Status values
`draft`, `submitted` and `withdrawn`. The harness owns the header, the index, the Status values `taken` and
`addressed` and each *Outcome* block.

A reader of the verifier's side uses `FeedbackFile.load(unit_dir)`, `.items`, `problems(item)` and
`content_sha256(item)`, then writes back with `.set_status(...)`, `.set_outcome(...)` and `.save()`. Every edit
returns a new `FeedbackFile`; the bytes outside the edited spans are the ones that were read.
"""

import hashlib
import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from l4.exitcodes import ExitCode
from l4.fsutil import UnsafeFile, atomic_write_bytes, read_regular_file
from l4.redact import Redactor
from l4.specs.base import SpecError
from l4.specs.questions import (
    MAX_TITLE_CHARS,
    Span,
    _block,
    _cell,
    _clean,
    _eol,
    _lines,
    _one_line,
    _section_end,
    _splice,
    _text,
    _visible,
)
from l4.state.ledger import read_ledger_files

FEEDBACK_FILENAME = "feedback.md"
INDEX_START = "<!-- l4:feedback-index:start -->"
INDEX_END = "<!-- l4:feedback-index:end -->"
MAX_FEEDBACK_BYTES = 2 * 1024 * 1024
MAX_PLACES = 5
OUTCOME_MARK = "<!-- written by the harness -->"
ENV_NAME = re.compile(r"^[A-Z_][A-Z0-9_]*$")

_DASH = "\N{EM DASH}"
_HEADER_LINES = (
    "<!-- l4:feedback v1",
    "Ask for changes here while the unit's branch is open. "
    "The easy way is `l4 feedback add` (see `l4 feedback --help`).",
    "An item is read only when its **Status** is `submitted`; `draft` items wait and `withdrawn` items are ignored.",
    "Kinds: refactor · duplication · tests · config · behaviour (see docs/feedback.md).",
    "Do not change item IDs. Commit and push to the l4/… branch: the harness takes submitted items at its next",
    "verification round, turns them into a fix unit and checks that each one was addressed. -->",
)
_INDEX_HEADER = ("| ID | Status | Kind | Where | Feedback |", "|----|--------|------|-------|----------|")
_START_LINE = re.compile(rb"^" + re.escape(INDEX_START.encode()) + rb"[ \t]*\r?$", re.MULTILINE)
_END_LINE = re.compile(rb"^" + re.escape(INDEX_END.encode()) + rb"[ \t]*\r?$", re.MULTILINE)
_ROW_ID = re.compile(rb"^\| FB-(\d+) \|", re.MULTILINE)
_LEDGER_ID = re.compile(rb"FB-(\d+)")


class FeedbackKind(StrEnum):
    REFACTOR = "refactor"
    DUPLICATION = "duplication"
    TESTS = "tests"
    CONFIG = "config"
    BEHAVIOUR = "behaviour"


class FeedbackStatus(StrEnum):
    DRAFT = "draft"  # the person's
    SUBMITTED = "submitted"
    WITHDRAWN = "withdrawn"
    TAKEN = "taken"  # the harness's
    ADDRESSED = "addressed"


HARNESS_STATUSES = frozenset({FeedbackStatus.TAKEN, FeedbackStatus.ADDRESSED})


class InvalidFeedback(SpecError):
    """An item that breaks the kind rules of L4-FBK-002, refused before anything is written."""

    default_code = ExitCode.USAGE_ERROR


@dataclass(frozen=True)
class Place:
    """A *Where* line: a repository-relative file and, when given, a line range (`end` is `start` for one line)."""

    path: str
    start: int | None = None
    end: int | None = None

    @property
    def label(self) -> str:
        if self.start is None:
            return self.path
        return f"{self.path}:{self.start}" + (f"-{self.end}" if self.end not in (None, self.start) else "")


@dataclass(frozen=True)
class Quote:
    """Lines of code quoted into the *Code* block; `label` (a place) is written above the fence when an item has
    more than one."""

    label: str
    language: str
    text: str


@dataclass(frozen=True)
class NewFeedback:
    kind: FeedbackKind
    title: str
    text: str
    by: str  # "<name>, <UTC time>"
    places: tuple[Place, ...] = ()
    code: tuple[Quote, ...] = ()
    env: str | None = None
    when: str | None = None
    then: str | None = None
    lesson: bool = False
    draft: bool = False


@dataclass(frozen=True)
class Block:
    """A `### ` subsection: its heading line (with the line break) and the lines under it."""

    heading: Span
    body: Span


@dataclass(frozen=True)
class FeedbackItem:
    id: str
    title: str
    status: FeedbackStatus  # an unknown value reads as `draft`
    status_text: str  # as written
    kind: FeedbackKind | None
    kind_text: str
    places: tuple[Place, ...]
    env: str | None
    when: str | None
    then: str | None
    lesson: bool
    by: str
    code: str  # the quoted lines, fences removed
    text: str  # the *Feedback* block, comments removed, stripped
    outcome: str  # the *Outcome* block without the harness's comment line
    section: Span  # the `## FB-NNN:` line to the last content line; the `---` after it is not included
    status_value: Span | None  # the text after `**Status:**`, without trailing blanks; None: no Status line
    outcome_block: Block | None


# --- the numbers: validity and the content hash ----------------------------------------------------------------


def _check(
    kind: FeedbackKind | None, kind_text: str, has_where: bool, env: str | None, when: str | None, then: str | None,
    text: str,
) -> tuple[str, ...]:  # fmt: skip
    if kind is None:
        return (f"unknown Kind `{kind_text}`",)
    found: list[str] = []
    if not text.strip():
        found.append("needs Feedback text")
    name = kind.value
    if kind in (FeedbackKind.REFACTOR, FeedbackKind.DUPLICATION, FeedbackKind.CONFIG) and not has_where:
        found.append(f"{name} needs Where")
    if kind is FeedbackKind.CONFIG:
        if not env:
            found.append("config needs Env")
        elif not ENV_NAME.match(env):
            found.append("Env must match ^[A-Z_][A-Z0-9_]*$")
        if bool(when) != bool(then):
            found.append("When and Then go together")
    elif kind is FeedbackKind.BEHAVIOUR:
        if not (when and then):
            found.append("behaviour needs When and Then")
        if env:
            found.append("behaviour refuses Env")
    else:
        for label, value in (("Env", env), ("When", when), ("Then", then)):
            if value:
                found.append(f"{name} refuses {label}")
    return tuple(found)


def problems(item: FeedbackItem) -> tuple[str, ...]:
    """Why the item is invalid (L4-FBK-002); empty when it is valid. An invalid item is never taken."""
    return _check(item.kind, item.kind_text, bool(item.places), item.env, item.when, item.then, item.text)


def new_problems(new: NewFeedback) -> tuple[str, ...]:
    """`problems` for an item that is not written yet."""
    return _check(new.kind, new.kind.value, bool(new.places), new.env, new.when, new.then, new.text)


def _normal(text: str | None) -> str:
    return " ".join((text or "").split())


def content_sha256(item: FeedbackItem) -> str:
    """Hash of what the person asked for: kind, places, env, when, then and text, whitespace normalised. The title,
    the lesson flag, the quoted code, the Status, the Outcome and the index are not in it, so a harness edit never
    changes it and an edit of the request does (L4-FBK-004: an edit re-opens a taken item)."""
    canonical = {
        "kind": (item.kind.value if item.kind else item.kind_text).lower(),
        "places": [[p.path, p.start, p.end] for p in item.places],
        "env": _normal(item.env), "when": _normal(item.when), "then": _normal(item.then), "text": _normal(item.text),
    }  # fmt: skip
    return hashlib.sha256(json.dumps(canonical, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


# --- reading: the tolerant parser ------------------------------------------------------------------------------

_HEADING = re.compile(rb"^## (?:FB-(\d+):[ \t]*(.*?)|.*?)[ \t]*\r?$")
_SUBHEADING = re.compile(rb"^###[ \t]+(Code|Feedback|When[ \t]*/[ \t]*Then|Outcome)[ \t]*\r?$", re.IGNORECASE)
_FIELD = re.compile(rb"^-[ \t]+\*\*(Status|Kind|Where|Env|Lesson|By):\*\*[ \t]*(.*?)[ \t]*\r?$", re.IGNORECASE)
_PAIR = re.compile(r"^-[ \t]+\*\*(When|Then):\*\*[ \t]*(.*?)[ \t]*$", re.IGNORECASE)
_OPENER = re.compile(rb"^[ \t]{0,3}(`{3,}|~{3,})(.*?)\r?$")
_CLOSER = re.compile(rb"^[ \t]{0,3}(`{3,}|~{3,})[ \t]*\r?$")
_STATUS_WORD = re.compile(r"[A-Za-z][A-Za-z-]*")
_PLACE = re.compile(r"^(?P<path>.+?)(?::(?P<start>\d+)(?:-(?P<end>\d+))?)?$")


def _fences(data: bytes, lines: list[tuple[int, int]]) -> tuple[list[bool], list[tuple[int, int]]]:
    """Per line, whether it is a fence line or inside a fence, and the (opening, closing) line pairs. A fence that
    never closes is plain text: it hides nothing after it."""
    fenced = [False] * len(lines)
    pairs: list[tuple[int, int]] = []
    unclosed: dict[bytes, int] = {}  # fence character -> the shortest length known to have no closer after it
    number = 0
    while number < len(lines):
        opener = _OPENER.match(data[lines[number][0] : lines[number][1]])
        if opener is None or (opener.group(1)[:1] == b"`" and b"`" in opener.group(2)):
            number += 1
            continue
        mark = opener.group(1)
        if mark[:1] in unclosed and len(mark) >= unclosed[mark[:1]]:
            number += 1
            continue
        for end in range(number + 1, len(lines)):
            closer = _CLOSER.match(data[lines[end][0] : lines[end][1]])
            if closer and closer.group(1)[:1] == mark[:1] and len(closer.group(1)) >= len(mark):
                pairs.append((number, end))
                fenced[number : end + 1] = [True] * (end + 1 - number)
                number = end + 1
                break
        else:
            unclosed[mark[:1]] = min(len(mark), unclosed.get(mark[:1], len(mark)))
            number += 1
    return fenced, pairs


def _index_region(data: bytes) -> tuple[int, int] | None:
    starts, ends = list(_START_LINE.finditer(data)), list(_END_LINE.finditer(data))
    if len(starts) == 1 and len(ends) == 1 and starts[0].start() < ends[0].start():
        return starts[0].end(), ends[0].start()
    return None


def _index_span(data: bytes) -> Span | None:
    region = _index_region(data)
    if region is None:
        return None
    return Span(region[0] + (2 if data[region[0] : region[0] + 2] == b"\r\n" else 1), region[1])


def _status_of(text: str) -> FeedbackStatus | None:
    word = _STATUS_WORD.search(text.strip().strip("`*_ "))
    try:
        return FeedbackStatus(word.group(0).lower()) if word else None
    except ValueError:
        return None


def _place_of(text: str) -> Place | None:
    value = text.strip().strip("`").strip()
    match = _PLACE.match(value) if value else None
    if match is None:
        return None
    start = int(match["start"]) if match["start"] else None
    end = int(match["end"]) if match["end"] else start
    return Place(match["path"].strip(), start, end)


def _parse_section(
    data: bytes, lines: list[tuple[int, int]], fenced: list[bool], pairs: list[tuple[int, int]], first: int, last: int,
    number: str, title: bytes,
) -> FeedbackItem:  # fmt: skip
    end = _section_end(data, lines, first, last)
    status_value: Span | None = None
    fields: dict[str, str] = {}
    wheres: list[str] = []
    marks: list[tuple[str, int]] = []  # (subsection name, heading line index)
    for index in range(first + 1, last):
        start, stop = lines[index]
        if start >= end:
            break
        if fenced[index]:
            continue
        line = data[start:stop].rstrip(b"\n")
        if sub := _SUBHEADING.match(line):
            marks.append((re.sub(r"\s+", "", sub.group(1).decode().lower()), index))
        elif not marks and (field := _FIELD.match(line)):
            name = field.group(1).decode().lower()
            if name == "where":
                wheres.append(_text(field.group(2)))
            elif name not in fields:
                fields[name] = _text(field.group(2))
                if name == "status":
                    status_value = Span(start + field.start(2), start + field.end(2))
    blocks: dict[str, Block] = {}
    for position, (name, heading) in enumerate(marks):
        body_end = lines[marks[position + 1][1]][0] if position + 1 < len(marks) else end
        body_start = min(lines[heading + 1][0] if heading + 1 < len(lines) else end, body_end)
        blocks.setdefault(name, Block(Span(lines[heading][0], lines[heading][1]), Span(body_start, body_end)))

    def visible(name: str) -> str:
        block = blocks.get(name)
        return _visible(data[block.body.start : block.body.end]) if block else ""

    code = ""
    if (block := blocks.get("code")) is not None:
        snippets = [
            b"".join(data[lines[i][0] : lines[i][1]] for i in range(opened + 1, closed)).decode(errors="replace")
            for opened, closed in pairs
            if block.body.start <= lines[opened][0] < block.body.end
        ]
        code = "\n".join(s.replace("\r\n", "\n").rstrip("\n") for s in snippets)
    pair_values: dict[str, str] = {}
    if (block := blocks.get("when/then")) is not None:
        for number_in_block, (start, stop) in enumerate(lines):
            if block.body.start <= start < block.body.end and not fenced[number_in_block]:
                pair = _PAIR.match(_text(data[start:stop]).rstrip("\r\n"))
                if pair:
                    pair_values.setdefault(pair.group(1).lower(), pair.group(2))
    outcome = "\n".join(line for line in visible("outcome").replace("\r\n", "\n").split("\n")).strip()
    kind_text = fields.get("kind", "").strip("`*_ ")
    try:
        kind: FeedbackKind | None = FeedbackKind(kind_text.lower())
    except ValueError:
        kind = None
    status_text = fields.get("status", "")
    return FeedbackItem(
        id=f"FB-{number}", title=_text(title), status=_status_of(status_text) or FeedbackStatus.DRAFT,
        status_text=status_text, kind=kind, kind_text=kind_text,
        places=tuple(p for p in map(_place_of, wheres) if p is not None),
        env=fields.get("env", "").strip("`*_ ") or None, when=pair_values.get("when") or None,
        then=pair_values.get("then") or None, lesson=fields.get("lesson", "").strip("`*_ ").lower() in ("yes", "true"),
        by=fields.get("by", ""), code=code, text=visible("feedback"), outcome=outcome,
        section=Span(lines[first][0], end), status_value=status_value, outcome_block=blocks.get("outcome"),
    )  # fmt: skip


@dataclass(frozen=True)
class FeedbackFile:
    data: bytes
    items: tuple[FeedbackItem, ...]
    index: Span | None  # the lines between the index markers; None: the file has no well-formed index
    path: Path | None = None

    @classmethod
    def parse(cls, source: bytes | str, path: Path | None = None) -> "FeedbackFile":
        """Never raises on content: whatever a person did to the file, the rest of it is still read."""
        data = source.encode("utf-8") if isinstance(source, str) else source
        index = _index_span(data)
        lines = _lines(data)
        fenced, pairs = _fences(data, lines)
        headings = []
        for number, (start, stop) in enumerate(lines):
            in_index = index is not None and index.start <= start < index.end
            if not fenced[number] and not in_index and (match := _HEADING.match(data[start:stop].rstrip(b"\n"))):
                headings.append((number, match))
        items = []
        for position, (first, match) in enumerate(headings):
            if match.group(1) is None:
                continue  # a section of someone else's: it ends the previous item and is never read
            last = headings[position + 1][0] if position + 1 < len(headings) else len(lines)
            items.append(
                _parse_section(data, lines, fenced, pairs, first, last, match.group(1).decode(), match.group(2))
            )
        return cls(data, tuple(items), index, path)

    @classmethod
    def load(cls, unit_dir: Path) -> "FeedbackFile | None":
        """None when the unit has no `feedback.md`."""
        path = unit_dir / FEEDBACK_FILENAME
        try:
            return cls.parse(read_regular_file(path, limit=MAX_FEEDBACK_BYTES), path)
        except FileNotFoundError:
            return None
        except UnsafeFile as exc:
            raise SpecError(str(exc)) from None

    def get(self, fid: str) -> FeedbackItem | None:
        """The item with that id; `FB-1` and `fb-001` name the same item."""
        wanted = _number(fid)
        return next((i for i in self.items if wanted is not None and _number(i.id) == wanted), None)

    def set_status(self, fid: str, status: FeedbackStatus | str) -> "FeedbackFile":
        """Replace the text after `**Status:**` and that item's index row; nothing else changes. The harness writes
        `taken` and `addressed`; the person's `submit` and `withdraw` write the others."""
        value = FeedbackStatus(status)
        item = _require(self, fid)
        if item.status_value is None:
            raise SpecError(f"{item.id} has no Status line")
        return _edited(self, [(item.status_value, value.value.encode())], row_of=item.id)

    def set_outcome(self, fid: str, text: str, *, redactor: Redactor) -> "FeedbackFile":
        """Replace the body of the item's *Outcome* block (or add the block at the end of the item) with the
        harness's comment line and the text, redacted and neutralised like every other free text it writes."""
        item = _require(self, fid)
        eol = _eol(self.data)
        body = eol.join(line.encode() for line in (OUTCOME_MARK, *_block(text or "(empty)", redactor)))
        block = item.outcome_block
        if block is None:
            at = item.section.end
            lead = b"" if self.data[:at].endswith(b"\n") else eol
            return _edited(self, [(Span(at, at), lead + eol + b"### Outcome" + eol + body + eol)])
        lead = b"" if self.data[: block.body.start].endswith(b"\n") else eol  # the heading was the last line
        ends = block.body.end > block.body.start and self.data[block.body.end - 1 : block.body.end] == b"\n"
        more = ends or block.body.end != item.section.end or block.body.end == block.body.start
        return _edited(self, [(block.body, lead + body + (eol if more else b""))])

    def refresh_index(self) -> "FeedbackFile":
        """Rewrite the index rows that no longer match their item, and add the rows that are missing. The row of a
        deleted section stays: it keeps the id from being reused. A file without an index gets one."""
        file = self
        if file.index is None:
            return FeedbackFile.parse(_with_index(file.data, file), file.path)
        for item in self.items:
            if file.index is None or (current := file.get(item.id)) is None:
                break
            data = _with_row(file.data, file.index, current)
            if data != file.data:
                file = FeedbackFile.parse(data, file.path)
        return file

    def save(self, path: Path | None = None) -> None:
        target = path or self.path
        if target is None:
            raise SpecError("feedback: no path to save to")
        atomic_write_bytes(target, self.data)
        if target.read_bytes() != self.data:
            raise SpecError(f"{target.name}: post-write verification failed")


def _number(fid: str) -> int | None:
    match = re.fullmatch(r"(?i)fb-(\d+)", fid.strip())
    return int(match.group(1)) if match else None


def _require(file: FeedbackFile, fid: str) -> FeedbackItem:
    item = file.get(fid)
    if item is None:
        raise SpecError(f"{FEEDBACK_FILENAME} has no section for {fid}")
    return item


# --- writing: span-scoped edits --------------------------------------------------------------------------------


def _row_text(fid: str, status: str, kind: str, where: Place | None, title: str) -> str:
    """The index shows the first place by its first line."""
    place = (f"{where.path}:{where.start}" if where.start is not None else where.path) if where else ""
    return f"| {fid} | {status} | {_cell(kind)} | {_cell(place)} | {_cell(title)} |"


def _row(item: FeedbackItem) -> str:
    kind = item.kind.value if item.kind else item.kind_text
    return _row_text(item.id, item.status.value, kind, item.places[0] if item.places else None, item.title)


def _with_index(data: bytes, parsed: FeedbackFile) -> bytes:
    """A file that has no index gets one, built from its items, after the instruction comment (else the title)."""
    eol = _eol(data)
    rows = b"".join(line.encode() + eol for line in (*_INDEX_HEADER, *(_row(i) for i in parsed.items)))
    block = eol + INDEX_START.encode() + eol + rows + INDEX_END.encode() + eol
    comment = re.search(rb"<!-- l4:feedback .*?-->[ \t]*\r?\n", data, re.DOTALL)
    title = re.search(rb"^(?:\xef\xbb\xbf)?# .*\n", data, re.MULTILINE)
    bom = 3 if data.startswith(b"\xef\xbb\xbf") else 0
    at = comment.end() if comment else title.end() if title else bom
    return _splice(data, [(Span(at, at), block)])


def _with_row(data: bytes, index: Span, item: FeedbackItem) -> bytes:
    """Only the index row of this item changes (or is added before the end marker)."""
    row = _row(item).encode()
    pattern = re.compile(rb"^\| " + re.escape(item.id.encode()) + rb" \|[^\r\n]*", re.MULTILINE)
    old = pattern.search(data, index.start, index.end)
    if old:
        return data if old.group(0) == row else _splice(data, [(Span(old.start(), old.end()), row)])
    return _splice(data, [(Span(index.end, index.end), row + _eol(data))])


def _edited(file: FeedbackFile, edits: Sequence[tuple[Span, bytes]], *, row_of: str | None = None) -> FeedbackFile:
    data = _splice(file.data, edits)
    parsed = FeedbackFile.parse(data, file.path)
    if parsed.index is None:
        data = _with_index(data, parsed)
    elif row_of is not None and (item := parsed.get(row_of)) is not None:
        data = _with_row(data, parsed.index, item)
    return FeedbackFile.parse(data, file.path)


# --- adding an item --------------------------------------------------------------------------------------------


def _ledger_ids(unit_dir: Path) -> Iterable[int]:
    """Ids named by any `feedback.*` event of any run of the unit: an item the person deleted is still taken."""
    for raw in read_ledger_files(unit_dir).values():
        for line in raw.split(b"\n"):
            if b'"type"' in line and b'"feedback.' in line:
                yield from (int(n) for n in _LEDGER_ID.findall(line))


def _used_ids(data: bytes | None) -> list[int]:
    """Ids from the harness-owned structure: the headings the parse reads (not one quoted inside a fence) and the
    rows inside the index region."""
    if data is None:
        return []
    region = _index_region(data)
    rows = _ROW_ID.findall(data[region[0] : region[1]]) if region else []
    return [*(n for i in FeedbackFile.parse(data).items if (n := _number(i.id)) is not None), *(int(n) for n in rows)]


def _read_existing(unit_dir: Path) -> bytes | None:
    try:
        return read_regular_file(unit_dir / FEEDBACK_FILENAME, limit=MAX_FEEDBACK_BYTES)
    except FileNotFoundError:
        return None
    except UnsafeFile as exc:
        raise SpecError(str(exc)) from None


def next_id(unit_dir: Path) -> str:
    """The next `FB-NNN`: one more than the largest id seen in a heading, in an index row, or in a `feedback.*`
    ledger event. Never an id that was used, even when the person deleted its section (SCN-FBK-02)."""
    return f"FB-{max([*_used_ids(_read_existing(unit_dir)), *_ledger_ids(unit_dir)], default=0) + 1:03d}"


def _fence_for(text: str) -> str:
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def _render_section(fid: str, new: NewFeedback, redactor: Redactor) -> tuple[list[str], str]:
    title = _one_line(new.title, redactor)[:MAX_TITLE_CHARS] or "(untitled feedback)"
    status = FeedbackStatus.DRAFT if new.draft else FeedbackStatus.SUBMITTED
    lines = ["---", "", f"## {fid}: {title}", "", f"- **Status:** {status.value}", f"- **Kind:** {new.kind.value}"]
    lines += [f"- **Where:** `{place.label}`" for place in new.places]
    if new.env:
        lines.append(f"- **Env:** `{new.env}`")
    lines += [f"- **Lesson:** {'yes' if new.lesson else 'no'}", f"- **By:** {_one_line(new.by, redactor)}", ""]
    if new.code:
        lines.append("### Code")
        for quote in new.code:
            code = _clean(quote.text, redactor).replace("\r\n", "\n").strip("\n")
            fence = _fence_for(code)
            if len(new.code) > 1:
                lines.append(f"`{quote.label}`")
            lines += [f"{fence}{quote.language}", *code.split("\n"), fence]
        lines.append("")
    lines += ["### Feedback", *_block(new.text, redactor), ""]
    if new.when or new.then:
        lines.append("### When / Then")
        lines += [
            f"- **{name}:** {_one_line(value, redactor)}"
            for name, value in (("When", new.when), ("Then", new.then))
            if value
        ]
        lines.append("")
    lines += ["### Outcome", OUTCOME_MARK]
    first = new.places[0] if new.places else None
    return lines, _row_text(fid, status.value, new.kind.value, first, title)


def append_item(
    unit_dir: Path, unit_name: str, new: NewFeedback, *, redactor: Redactor, validate: bool = True
) -> str:  # fmt: skip
    """Append one section and one index row; returns the new id. Creates the file (header and index) when it is
    missing; in an existing file the only changes are the row inserted before the index end marker and the section
    appended at the end, and the line-ending style is kept. An invalid item raises `InvalidFeedback` and writes
    nothing (`validate=False` is for tests that need an invalid file)."""
    if validate and (found := new_problems(new)):
        raise InvalidFeedback("; ".join(found))
    if len(new.places) > MAX_PLACES:
        raise InvalidFeedback(f"at most {MAX_PLACES} Where lines")
    existing = _read_existing(unit_dir)
    if existing is None:
        eol = "\n"
        head = "\n".join(
            [f"# Feedback {_DASH} {unit_name}", "", *_HEADER_LINES, "", INDEX_START, *_INDEX_HEADER, INDEX_END, ""]
        )
        data = head.encode()
    else:
        eol = "\r\n" if b"\r\n" in existing else "\n"
        data = existing
    fid = f"FB-{max([*_used_ids(data), *_ledger_ids(unit_dir)], default=0) + 1:03d}"
    lines, row = _render_section(fid, new, redactor)
    region = _index_region(data)
    if region is not None:
        data = data[: region[1]] + f"{row}{eol}".encode() + data[region[1] :]
    if not data.endswith(b"\n"):
        data += eol.encode()
    data += eol.encode() + (eol.join(lines) + eol).encode()
    path = unit_dir / FEEDBACK_FILENAME
    atomic_write_bytes(path, data)
    if path.read_bytes() != data:
        raise SpecError(f"{path.name}: post-write verification failed")
    return fid
