"""The excerpt of a red CI job's log, pure (ci-evidence D1, D2, D4, D5; L4-VER-061 to L4-VER-063).

A GitHub job log ends with its post steps and the runner's warnings, so its last lines hold none of the failure. This
module finds the section of the failing step (`actions_excerpt`), keeps the lines that name what failed besides the
last lines of the section (`section_excerpt`, `summary_lines`) and ranks them for a blocker's detail
(`ranked_summary_lines`). It reads no network and no file and imports only `l4.forge.base`, so the forges and the
verifier can use it without a cycle. Redaction is not done here: the sweep does it (D6).
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from l4.forge.base import MAX_TAIL_CHARS, MAX_TAIL_LINES, clip_log, strip_ansi

MAX_LINE_CHARS = 500
MAX_SUMMARY_LINES = 12
MAX_SUMMARY_CHARS = 1200
MAX_ASSERTION_LINES = 6
MIN_TAIL_LINES = 5
GAP = "..."

# D4, in this order. Matched with `re.search` against the whole line, after the markers are converted.
SUMMARY_PATTERNS = (
    re.compile(r"^(?:FAILED|ERROR) \S"),  # 1: pytest's short test summary
    re.compile(r"^E\s{2,}\S"),  # 2: pytest's assertion lines (the first MAX_ASSERTION_LINES only)
    re.compile(r"^\s*FAIL\s+\S"),  # 3: jest, vitest
    re.compile(r"^\s*--- FAIL: "),  # 4: go test, also a subtest
    re.compile(r"\b[1-9]\d* (?:failed|errors?)\b"),  # 5: a count
    re.compile(r"^(?:##\[error\]|Error: )(?!Process completed with exit code)"),  # 6: a GitHub annotation
)
# D5: the class of each pattern when the lines are ranked: failing tests, counts, assertion lines, annotations.
_RANK = (0, 2, 0, 0, 1, 3)
_ASSERTION = 1  # index of the pattern of the `E` lines

_TIMESTAMP = re.compile(r"^(\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d)(?:\.\d+)?Z ")
_MARKERS = (("##[error]", "Error: "), ("##[warning]", "Warning: "), ("##[notice]", "Notice: "))
_RUN_GROUP = "##[group]Run "
_POST = "Post job cleanup."
_ORPHANS = "Cleaning up orphan processes"


@dataclass(frozen=True)
class ActionsStep:
    """One step of a GitHub job as the API reports it (`GET actions/jobs/:id`, `steps[]`)."""

    name: str
    conclusion: str | None
    started_at: datetime | None


@dataclass(frozen=True)
class Excerpt:
    text: str
    failed_step: str | None = None


def _rank(line: str) -> int | None:
    """The class of a summary line (lower is more important), or None when no pattern matches."""
    ranks = [_RANK[i] for i, pattern in enumerate(SUMMARY_PATTERNS) if pattern.search(line)]
    return min(ranks) if ranks else None


def line_rank(line: str) -> int | None:
    """The class of a summary line for a blocker's `Failed:` part: 0 failing test, 1 count, 2 `E` line, 3 annotation."""
    return _rank(line)


def summary_lines(lines: Sequence[str]) -> list[str]:
    """The lines that name what failed (D4), in log order, without repeats; at most `MAX_ASSERTION_LINES` `E` lines."""
    found: list[str] = []
    seen: set[str] = set()
    assertions = 0
    for line in lines:
        rank = _rank(line)
        if line in seen or rank is None:
            continue
        if rank == _RANK[_ASSERTION]:
            assertions += 1
            if assertions > MAX_ASSERTION_LINES:
                continue
        seen.add(line)
        found.append(line)
    return found


def ranked_summary_lines(lines: Sequence[str]) -> list[str]:
    """`summary_lines` in the order of a blocker's `Failed:` part (D5): the lines that name a failing test, then the
    counts, then the `E` lines, then the annotations; log order within a class."""
    found = summary_lines(lines)
    return sorted(found, key=lambda line: _rank(line) or 0)


def _cut(line: str) -> str:
    return line if len(line) <= MAX_LINE_CHARS else line[:MAX_LINE_CHARS] + GAP


def section_excerpt(
    header: str | None,
    body: Sequence[str],
    closing: Sequence[str] = (),
    *,
    max_lines: int,
    max_chars: int,
) -> str:
    """The header, the summary lines that come before the last `max_lines` lines, one `...` line when body lines were
    left out, those last lines, and the closing lines (D4). Over `max_chars` the tail's first lines go (down to
    `MIN_TAIL_LINES`), then the summary's last lines, then the start of the text."""
    cut = [_cut(line) for line in body]
    keep = max(max_lines, 1)
    tail = cut[-keep:]
    before = cut[: len(cut) - len(tail)]
    summary: list[str] = []
    size = 0
    for line in summary_lines(before):
        if len(summary) >= MAX_SUMMARY_LINES or size + len(line) + 1 > MAX_SUMMARY_CHARS:
            break
        summary.append(line)
        size += len(line) + 1
    head = [header] if header is not None else []

    def render() -> str:
        gap = [GAP] if len(summary) + len(tail) < len(cut) else []
        return "\n".join([*head, *summary, *gap, *tail, *closing])

    text = render()
    while len(text) > max_chars and len(tail) > MIN_TAIL_LINES:
        tail = tail[1:]
        text = render()
    while len(text) > max_chars and summary:
        summary = summary[:-1]
        text = render()
    return text[-max_chars:] if len(text) > max_chars else text


def actions_failed_step(steps: Sequence[ActionsStep]) -> ActionsStep | None:
    """The first step with the conclusion `failure`, else the first that is `timed_out` or `cancelled` (D2)."""
    for wanted in (("failure",), ("timed_out", "cancelled")):
        for step in steps:
            if step.conclusion in wanted:
                return step
    return None


def _convert(text: str) -> str | None:
    """A body line as GitHub's page shows it; None for a line that is only a marker (`##[endgroup]`)."""
    if text.startswith("##[endgroup]"):
        return None
    for marker, shown in _MARKERS:
        if text.startswith(marker):
            return shown + text[len(marker) :]
    if text.startswith("##[group]"):
        return text[len("##[group]") :]
    return text


def _lines(log: str) -> list[tuple[datetime | None, str]]:
    """(time to the second, text) per line: the byte-order mark, ANSI codes, carriage returns and the runner's
    timestamp prefix are gone."""
    plain = strip_ansi(log.removeprefix("\ufeff")).replace("\r\n", "\n").replace("\r", "\n")
    out: list[tuple[datetime | None, str]] = []
    for raw in plain.rstrip("\n").split("\n"):
        match = _TIMESTAMP.match(raw)
        if match is None:
            out.append((None, raw))
            continue
        out.append((datetime.fromisoformat(match.group(1)).replace(tzinfo=UTC), raw[match.end() :]))
    return out


def _second(moment: datetime) -> datetime:
    zoned = moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)
    return zoned.astimezone(UTC).replace(microsecond=0)


def _is_start(text: str) -> bool:
    return text.startswith(_RUN_GROUP) or text.startswith(_POST) or text.startswith(_ORPHANS)


def actions_excerpt(
    log: str,
    steps: Sequence[ActionsStep] | None,
    *,
    max_lines: int = MAX_TAIL_LINES,
    max_chars: int = MAX_TAIL_CHARS,
) -> Excerpt:
    """The failing step's section of a GitHub Actions log, and the step's name (D2)."""
    lines = _lines(log)
    failing = actions_failed_step(steps) if steps else None
    name = failing.name if failing is not None else None
    errors = [i for i, (_, text) in enumerate(lines) if text.startswith("##[error]")]
    if failing is not None and failing.started_at is not None:
        floor = _second(failing.started_at)
        later = [i for i in errors if (when := lines[i][0]) is None or when >= floor]
        errors = later or errors
    if not errors:
        converted = [c for _, text in lines if (c := _convert(text)) is not None]
        return Excerpt(clip_log("\n".join(converted), max_lines, max_chars), name)
    anchor = errors[0]
    starts = [i for i, (_, text) in enumerate(lines) if _is_start(text)]
    begin = max([0, *[i for i in starts if i <= anchor]])
    end = min([len(lines), *[i for i in starts if i > anchor]])
    section = [text for _, text in lines[begin:end]]
    header: str | None = None
    body = section
    if section and section[0].startswith(_RUN_GROUP):
        header = section[0][len("##[group]") :]
        rest = section[1:]
        close = next((i for i, text in enumerate(rest) if text.startswith("##[endgroup]")), None)
        body = rest[close + 1 :] if close is not None else rest
    elif section and (section[0].startswith(_POST) or section[0].startswith(_ORPHANS)):
        header, body = section[0], section[1:]
    converted = [c for text in body if (c := _convert(text)) is not None]
    return Excerpt(section_excerpt(header, converted, (), max_lines=max_lines, max_chars=max_chars), name or header)
