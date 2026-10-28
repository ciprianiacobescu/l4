"""Where a test is, in any language (SPEC L4-IMP-065, design test-file-reach D1 and D2). Pure: no work tree, no git.

A test id of a report is its file's path or dotted module, `::`, and the test's name. pytest writes the file as a dotted
module (`tests.test_x.TestY::test_z`), a JavaScript or TypeScript reporter as the path with dots for slashes
(`src.pricing.total.test.ts::total of two prices`), and some write the path itself. `file_of_id` maps all of them to one
of the repository's files, and `window` gives a test's own lines in a file that is not Python.
"""

import re
from collections.abc import Collection, Iterable

_CALLS = r"(?:test|it|describe|suite|bench)"
_MODIFIERS = r"(?:\.(?:only|skip|todo|concurrent|fails|failing|each(?:\((?:[^()]|\([^()]*\))*\))?))*"
_CALL = re.compile(rf"""^\s*{_CALLS}{_MODIFIERS}\s*\(\s*(?P<quote>["'`])(?P<literal>.*?)(?P=quote)""")
_OPENED = re.compile(rf"^\s*{_CALLS}{_MODIFIERS}\s*\(\s*$")  # prettier puts a long name on the next line
_LITERAL = re.compile(r"""^\s*(?P<quote>["'`])(?P<literal>.*?)(?P=quote)""")
_CLOSING = re.compile(r"^[\s\]\)\}\;,]*$")  # a line that only closes: `}`, `});`, `})`


def file_of_id(test_id: str, paths: Iterable[str], preferred: Collection[str] = ()) -> str | None:
    """The one of `paths` that holds the test of `test_id`, or None. The id's head (before its first `::`) is, in
    order: one of the paths; a dotted Python module (the longest dotted prefix whose `/`-joined form plus `.py` is a
    path); or a path with dots for slashes, whole or from a dot on (a reporter whose class names start below the
    repository root). Several such paths give None, unless exactly one of them is in `preferred`. A file name may hold
    dots (`total.v2.test.ts`), so the head is never split to guess a path: only whole paths are compared."""
    head = test_id.split("::", 1)[0]
    if not head:
        return None
    known = set(paths)
    if head in known:
        return head
    parts = head.split(".")
    while parts:
        module = "/".join(parts) + ".py"
        if module in known:
            return module
        parts.pop()
    last = head.rsplit(".", 1)[-1]
    found = sorted(
        path
        for path in known
        if path.endswith(last) and ((dotted := path.replace("/", ".")) == head or dotted.endswith("." + head))
    )
    if len(found) <= 1:
        return found[0] if found else None
    chosen = [path for path in found if path in preferred]
    return chosen[0] if len(chosen) == 1 else None


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _names(literal: str, name: str) -> bool:
    """Does the test call's string name the reported test? Reporters join the describe names and the test's with a
    space or ` > `, so the literal is the whole name or its last words."""
    return bool(literal) and (name == literal or name.endswith((" " + literal, "> " + literal)))


def _start(lines: list[str], name: str) -> int | None:
    """The line of the test call (or Go function) that names `name`: the longest literal wins; with no call, the first
    line that holds the name."""
    best: tuple[int, int] | None = None  # (literal length, line)
    go = re.compile(rf"^\s*func\s+(?:\([^)]*\)\s*)?{re.escape(name.split('/', 1)[0])}\s*\(") if name else None
    for at, line in enumerate(lines):
        literal = None
        if (call := _CALL.match(line)) is not None:
            literal = call.group("literal")
        elif _OPENED.match(line) and at + 1 < len(lines) and (nxt := _LITERAL.match(lines[at + 1])) is not None:
            literal = nxt.group("literal")
        if literal is not None and _names(literal, name) and (best is None or len(literal) > best[0]):
            best = (len(literal), at)
        elif go is not None and go.match(line) and best is None:
            best = (len(name), at)
    if best is not None:
        return best[1]
    return next((at for at, line in enumerate(lines) if name in line), None)


def window(text: str, name: str) -> str | None:
    """A test's own lines in a file that is not Python: from the line of the test call that names it (`test`, `it`,
    `describe`, `suite` or `bench`, also `.only`, `.skip` or `.each`, or Go's `func <name>(`) to the line that closes it
    (the first later non-blank line indented no deeper than that line, included when it only closes). The block is
    given whole: the caller cuts it. None when no line names the test."""
    if not name:
        return None
    lines = text.splitlines()
    start = _start(lines, name)
    if start is None:
        return None
    base = _indent(lines[start])
    end = len(lines)
    for at in range(start + 1, len(lines)):
        line = lines[at]
        if line.strip() and _indent(line) <= base:
            end = at + 1 if _CLOSING.match(line) else at
            break
    return "\n".join(lines[start:end])
