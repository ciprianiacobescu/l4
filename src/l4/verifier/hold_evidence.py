"""How the test step 5 wrote and why it failed at the head are shown (L4-VER-083): the numbered code and the outcomes
that have something to show. Pure; what the lines hold was redacted and bounded where the outcome was made
(`generate.generate_ui_test`)."""

from l4.verifier.types import GeneratedOutcome


def has_evidence(g: GeneratedOutcome) -> bool:
    """A test that was written and not accepted or waived, and that kept its failure or its code and path."""
    return g.status not in ("accepted", "waived") and bool(g.excerpt or (g.code and g.path))


def numbered_code(code: str) -> list[str]:
    """Each line of `code` as its number right-aligned in four columns, two spaces and the line (an empty line is its
    number alone): the numbers are those of pytest's locations in the excerpt."""
    lines = code.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return [f"{n:>4}  {line}" if line else f"{n:>4}" for n, line in enumerate(lines, 1)]
