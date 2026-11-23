"""The failure excerpt a retry prompt carries (SPEC L4-IMP-008, L4-OBS-002): why a gate rejected an attempt, not only
which test it named (live wave A job 5699: the same mistake three times, because the retry prompt held an id and no
error). Pure: the report's own `<failure>`/`<error>` bodies, cut to what a person fixing the test would read.

Bounds: at most 8 lines per test, 40 lines and 3,000 characters in all. Paths are made relative to the worktree, the
gate's tmp root is `<tmp>`, and the redactor sees each test's whole body before a line is kept, then the result again.
The excerpt is agent-influenced output: the caller puts it in the prompt's data fence only. The committed ledger gets
only `ledger_excerpt` of it (L4-IMP-064: the `E` lines and one repository location, at most 600 characters, redacted),
which no prompt reads.
"""

import re
from collections.abc import Callable, Sequence
from pathlib import Path

from l4.gates.collection import LOCATION, error_lines, in_repository
from l4.gates.junit import TestCase, TestReport

MAX_E_LINES = 6
MAX_TEST_LINES = 8
MAX_LINES = 40
MAX_CHARS = 3000
MAX_TESTS = 8  # tests with a block of their own; the rest are counted
LINT_HEAD_LINES = 36
MAX_RECORD_EXCERPT_CHARS = 600  # a round's per-test excerpt (L4-VER-078): the bound of the ledger's `ledger_excerpt`
_E_LINE = re.compile(r"^E\s+\S")
_PYTEST_TMP = re.compile(r"/(?:private/)?(?:var/folders/[^\s'\"]+?/T|tmp)/pytest-of-[^/\s'\"]+/pytest-\d+")
_TRUNCATED = "... (truncated)"
# the shared redactor removes a whole private-key block (BEGIN to END). A report keeps only the last 4,000 characters of
# a body and the first 500 of a message, so a block can reach this module with one marker only; the markers are built
# from parts so that no source file holds a key marker as one string
_KEY_BEGIN = re.compile("-----BEGIN [A-Z ]*PRIVATE " + "KEY" + "-----")
_KEY_END = re.compile("-----END [A-Z ]*PRIVATE " + "KEY" + "-----")
_KEY_CUT = "[REDACTED:private-key]"


def _clean(text: str, worktree: Path, tmp_root: Path | None) -> str:
    """Relative paths and a masked tmp root, in this order: the tmp root may sit under the worktree."""
    if tmp_root is not None:
        for variant in {str(tmp_root), str(tmp_root.resolve())}:
            text = text.replace(variant, "<tmp>")
    text = _PYTEST_TMP.sub("<tmp>", text)
    for variant in sorted({str(worktree), str(worktree.resolve())}, key=len, reverse=True):
        text = text.replace(variant + "/", "").replace(variant, ".")
    return text


def _redact_keys(redact: Callable[[str], str], text: str) -> str:
    """`redact(text)`, and a private-key block that is only half there removed to the edge of the text: an END marker
    without its BEGIN (the text was cut from the front) takes everything before it, a BEGIN without its END (cut at
    the back) everything after it. Local to the excerpts: the shared redactor is unchanged."""
    text = redact(text)
    if ends := list(_KEY_END.finditer(text)):
        text = _KEY_CUT + text[ends[-1].end() :]
    if begin := _KEY_BEGIN.search(text):
        text = text[: begin.start()] + _KEY_CUT
    return text


def _cut_at_line(text: str, limit: int) -> str:
    """`text` cut at the last line end before `limit`; one line longer than `limit` is cut at `limit`."""
    if len(text) <= limit:
        return text
    kept = text[:limit]
    if text[limit] != "\n" and "\n" in kept:
        kept = kept.rsplit("\n", 1)[0]
    return kept


def redacted_cut(text: str, redact: Callable[[str], str], limit: int) -> str:
    """`text` redacted whole (a private-key block that is only half there removed to the edge), cut at the last line end
    before `limit` characters (one line longer than `limit` at `limit`), and redacted again: a cut made after the
    redaction can only drop text, never uncover a secret that the cut had split (L4-VER-083)."""
    return _redact_keys(redact, _cut_at_line(_redact_keys(redact, text), limit))


def _test_lines(body: str) -> list[str]:
    """The `E` lines (at most 6), the `>` line of the deepest frame in a repository file with its location, and the
    last `path:line: ErrorName` line, in the order pytest prints them."""
    lines = body.splitlines()
    e_lines = [line.rstrip() for line in lines if _E_LINE.match(line)][:MAX_E_LINES]
    last_arrow: str | None = None
    deepest: tuple[str, str] | None = None  # (the `>` line, the location line that follows it)
    last_location: str | None = None
    for line in lines:
        if line.startswith(">"):
            last_arrow = line.rstrip()
            continue
        found = LOCATION.match(line)
        if found is None:
            continue
        last_location = line.strip()
        if last_arrow is not None and in_repository(found.group("path")):
            deepest = (last_arrow, last_location)
        last_arrow = None
    out: list[str] = []
    if deepest is not None:
        out.append(deepest[0])
    out.extend(e_lines)
    if deepest is not None:
        out.append(deepest[1])
    if last_location is not None and (deepest is None or last_location != deepest[1]):
        out.append(last_location)
    return out[:MAX_TEST_LINES]


def _fit(lines: list[str]) -> str:
    """At most 40 lines and 3,000 characters, with a closing note when something was cut."""
    cut = False
    if len(lines) > MAX_LINES:
        lines, cut = lines[: MAX_LINES - 1], True
    while lines and len("\n".join([*lines, _TRUNCATED] if cut else lines)) > MAX_CHARS:
        lines, cut = lines[:-1], True
    if cut and len(lines) >= MAX_LINES:
        lines = lines[: MAX_LINES - 1]
    return "\n".join([*lines, _TRUNCATED] if cut else lines)


def failure_excerpt(
    report: TestReport,
    ids: Sequence[str],
    *,
    worktree: Path,
    tmp_root: Path | None,
    redact: Callable[[str], str],
) -> str:
    """The failure of each named test that the report has, bounded and redacted; empty when none has a body or a
    message. A test without a body gives its (500-character) message instead."""
    blocks: list[tuple[str, list[str]]] = []
    for test_id in sorted(set(ids)):
        case = report.tests.get(test_id)
        if case is None or case.status not in ("failed", "error"):
            continue
        # redacted whole before any line is dropped: a secret that spans lines (a private key) loses its end marker
        # to the 6-line bound, and the redactor would no longer see it
        body = _redact_keys(redact, case.detail or case.message)
        lines = _test_lines(body) if case.detail else body.splitlines()[:MAX_TEST_LINES]
        lines = [line for line in lines if line.strip()] or body.splitlines()[:2]
        if lines:
            blocks.append((test_id, lines))
    if not blocks:
        return ""
    counts: dict[str, int] = {}
    for _, lines in blocks:
        for line in set(lines):
            counts[line] = counts.get(line, 0) + 1
    shown_lines: set[str] = set()
    out: list[str] = []
    for test_id, lines in blocks[:MAX_TESTS]:
        out.append(f"{test_id}:")
        for line in lines:
            if line in shown_lines:
                continue
            shown_lines.add(line)
            out.append(f"  {line} (same for {counts[line]} tests)" if counts[line] > 1 else f"  {line}")
    if len(blocks) > MAX_TESTS:
        out.append(f"... and {len(blocks) - MAX_TESTS} more failing tests")
    text = _redact_keys(redact, _clean("\n".join(out), worktree, tmp_root))
    return _fit(text.splitlines())


def case_excerpt(
    case: TestCase,
    *,
    worktree: Path,
    tmp_root: Path | None,
    redact: Callable[[str], str],
    limit: int = MAX_RECORD_EXCERPT_CHARS,
) -> str:
    """The lines `failure_excerpt` keeps for one failed test, at most 8 lines and `limit` characters (L4-VER-078): its
    `E` lines and deepest repository frame, or the first lines of its message when the report holds no body. The body is
    redacted whole before any line is dropped, the result again after the paths are made relative, so a secret cut by
    the bound is never shown in part. Cut at the last line end before `limit` (one line longer than `limit` is cut at
    `limit`); empty when there is nothing to show. The name does not start with `test`: a test module that imports it
    would collect it."""
    body = _redact_keys(redact, case.detail or case.message)
    lines = _test_lines(body) if case.detail else body.splitlines()[:MAX_TEST_LINES]
    lines = [line for line in lines if line.strip()] or [line for line in body.splitlines() if line.strip()][:2]
    return _cut_at_line(_redact_keys(redact, _clean("\n".join(lines[:MAX_TEST_LINES]), worktree, tmp_root)), limit)


def collection_case_excerpt(
    detail: str,
    *,
    worktree: Path,
    tmp_root: Path | None,
    redact: Callable[[str], str],
    limit: int = MAX_RECORD_EXCERPT_CHARS,
) -> str:
    """The `E` lines of a collection error's traceback end (L4-VER-078), redacted before the cut and again after the
    paths are made relative, cut as a test's excerpt is: at most 8 lines and `limit` characters, at a line end."""
    found = error_lines(_redact_keys(redact, detail), 10 * MAX_CHARS).splitlines()[:MAX_TEST_LINES]
    return _cut_at_line(_redact_keys(redact, _clean("\n".join(found), worktree, tmp_root)), limit)


def lint_excerpt(text: str) -> str:
    """A static gate's log: its first 36 lines and its last line (the summary), repeated lines kept once, at most 40
    lines and 3,000 characters."""
    lines = [line.rstrip() for line in text.strip().splitlines()]
    seen: set[str] = set()
    kept: list[str] = []
    for line in lines:
        if len(line.strip()) >= 12:
            if line in seen:
                continue
            seen.add(line)
        kept.append(line)
    if len(kept) > LINT_HEAD_LINES + 1:
        summary = kept[-1]
        kept = [*kept[:LINT_HEAD_LINES], summary]
    return _fit(kept)
