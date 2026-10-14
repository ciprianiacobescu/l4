"""The text normaliser behind recurrence (L4-KG-006, design D5, SCN-KG-12, SCN-KG-13). Recurrence by finding id cannot
work, because a finding id hashes the title and the criterion id, and a criterion id includes the capability folder
(OpenSpec) or the unit folder (Kiro); the same mistake in two units has two ids. So two things are compared as text.

`norm` applies NFC, then replaces what differs from unit to unit with a placeholder, in this order: a backticked span
becomes `` `…` ``; `C-<8 hex>`, `F-<8 hex>`, `L-<8 hex>` and `Q-<n>` become `<criterion>`, `<finding>`, `<lesson>` and
`<question>`; a hex run of 7 or more becomes `<sha>`; a word with a `/` becomes `<path>`; a number becomes `#`. A list
of one placeholder (`<criterion>, <criterion>`) is one placeholder, because a reason that names three criteria is the
same mistake as one that names one. It then folds case and collapses whitespace. `norm` is idempotent.

`recurrence_key(title, alias, framework)` is `norm(title) + " | " + norm(requirement › scenario)`. The second part
is empty for a Kiro alias (`Req n.m`) and when there is no criterion. `failure_class(reason)` is the first line of an
attempt failure's reason, cut before the first `:` or ` (` that is outside a backticked span, normalised, and cut to
120 characters. Both are approximate: two different mistakes can share a key, and one reworded mistake can get two.
Every report line that uses a key says so.
"""

import re
import unicodedata

FAILURE_CLASS_MAX = 120
KEY_SEPARATOR = " | "
ALIAS_SEPARATOR = "›"

_BACKTICKED = re.compile(r"`[^`]*`")
_CRITERION = re.compile(r"\bC-[0-9a-f]{8}\b")
_FINDING = re.compile(r"\bF-[0-9a-f]{8}\b")
_LESSON = re.compile(r"\bL-[0-9a-f]{8}\b")
_QUESTION = re.compile(r"\bQ-\d+\b")
_SHA = re.compile(r"\b[0-9a-f]{7,}\b", re.IGNORECASE)
_PATH = re.compile(r"(?:[\w.\-~@+%]*/)+[\w.\-~@+%]*")
_NUMBER = re.compile(r"\d+")
_PLACEHOLDER_LIST = re.compile(r"(<[a-z]+>)(?:\s*,\s*\1)+")
_SPACE = re.compile(r"\s+")


def norm(text: str) -> str:
    out = unicodedata.normalize("NFC", text)
    out = _BACKTICKED.sub("`…`", out)
    for pattern, placeholder in (
        (_CRITERION, "<criterion>"), (_FINDING, "<finding>"), (_LESSON, "<lesson>"), (_QUESTION, "<question>"),
        (_SHA, "<sha>"), (_PATH, "<path>"), (_NUMBER, "#"),
    ):  # fmt: skip
        out = pattern.sub(placeholder, out)
    out = _PLACEHOLDER_LIST.sub(r"\1", out)
    return _SPACE.sub(" ", out.casefold()).strip()


def _requirement_scenario(alias: str | None, framework: str) -> str:
    """`Requirement › Scenario` of an OpenSpec alias `capability › Requirement › Scenario`; empty for anything else."""
    if framework != "openspec" or not alias:
        return ""
    parts = [part.strip() for part in alias.split(ALIAS_SEPARATOR)]
    return f" {ALIAS_SEPARATOR} ".join(norm(part) for part in parts[1:])


def recurrence_key(title: str, alias: str | None, framework: str) -> str:
    return f"{norm(title)}{KEY_SEPARATOR}{_requirement_scenario(alias, framework)}"


def _cut_point(line: str) -> int:
    """Index of the first `:` or ` (` that is not inside a backticked span, else the length of the line."""
    inside = False
    for index, char in enumerate(line):
        if char == "`":
            inside = not inside
        elif not inside and (char == ":" or (char == " " and line.startswith(" (", index))):
            return index
    return len(line)


def failure_class(reason: str) -> str:
    first = reason.split("\n", 1)[0]
    return norm(first[: _cut_point(first)])[:FAILURE_CLASS_MAX].rstrip()
