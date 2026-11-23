"""How the test step 5 wrote and why it failed at the head are shown (L4-VER-083): the numbered code and the outcomes
that have something to show. Pure; what the lines hold was redacted and bounded where the outcome was made
(`generate.generate_ui_test`)."""

from l4.verifier.types import GeneratedOutcome

MAX_CODE_LINES = 200  # the lines of a test that a question or a report shows
MAX_NUMBERED_CHARS = 6000  # the numbered lines and the cut line, each with its line end, before an indent is added


def has_evidence(g: GeneratedOutcome) -> bool:
    """A test that was written and not accepted, and that kept its failure or its code and path."""
    return g.status not in ("accepted", "waived") and bool(g.excerpt or (g.code and g.path))


def _cut_line(count: int) -> str:
    return f"… (cut: {count} more line{'' if count == 1 else 's'})"


def numbered_code(code: str) -> list[str]:
    """Each line of `code` as its number right-aligned in four columns, two spaces and the line (an empty line is its
    number alone): the numbers are those of pytest's locations in the excerpt. At most `MAX_CODE_LINES` lines and
    `MAX_NUMBERED_CHARS` characters, the numbers included: a longer copy keeps its first lines and ends with one line
    that says how many were cut (`… (cut: N more lines)`), which the bound counts."""
    lines = code.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    numbered = [f"{n:>4}  {line}" if line else f"{n:>4}" for n, line in enumerate(lines, 1)]
    if len(numbered) <= MAX_CODE_LINES and sum(len(line) + 1 for line in numbered) <= MAX_NUMBERED_CHARS:
        return numbered
    room = MAX_NUMBERED_CHARS - len(_cut_line(len(numbered))) - 1  # the cut line is the longest it can be
    kept: list[str] = []
    for line in numbered[:MAX_CODE_LINES]:
        if len(line) + 1 > room:
            break
        kept.append(line)
        room -= len(line) + 1
    return [*kept, _cut_line(len(numbered) - len(kept))]
