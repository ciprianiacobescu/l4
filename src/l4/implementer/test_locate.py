"""Where a test is, in any language (SPEC L4-IMP-065, design test-file-reach D1 and D2). Pure: no work tree, no git.

A test id of a report is its file's path or dotted module, `::`, and the test's name. pytest writes the file as a dotted
module (`tests.test_x.TestY::test_z`), a JavaScript or TypeScript reporter as the path with dots for slashes
(`src.pricing.total.test.ts::total of two prices`), and some write the path itself. `file_of_id` maps all of them to one
of the repository's files, and `window` gives a test's own lines in a file that is not Python.
"""

import re
from collections.abc import Callable, Collection, Iterable

_CALLS = r"(?:test|it|describe|suite|bench)"
_MODIFIERS = r"(?:\.(?:only|skip|todo|concurrent|fails|failing|each(?:\((?:[^()]|\([^()]*\))*\))?))*"
_CALL = re.compile(rf"""^\s*{_CALLS}{_MODIFIERS}\s*\(\s*(?P<quote>["'`])(?P<literal>.*?)(?P=quote)""")
_OPENED = re.compile(rf"^\s*{_CALLS}{_MODIFIERS}\s*\(\s*$")  # prettier puts a long name on the next line
_LITERAL = re.compile(r"""^\s*(?P<quote>["'`])(?P<literal>.*?)(?P=quote)""")
_CLOSING = re.compile(r"^[\s\]\)\}\;,]*$")  # a line that only closes: `}`, `});`, `})`


def _pick(found: list[str], preferred: Collection[str]) -> str | None:
    """The only one of `found` that is `preferred`, or None."""
    chosen = [path for path in found if path in preferred]
    return chosen[0] if len(chosen) == 1 else None


def file_of_id(
    test_id: str, paths: Iterable[str], preferred: Collection[str] | Callable[[], Collection[str]] = ()
) -> str | None:
    """The one of `paths` that holds the test of `test_id`, or None. The id's head (before its first `::`) is, in
    order: (1) one of the paths; (2) a path with dots for slashes (`src.pricing.total.test.ts`); (3) a dotted Python
    module (the longest dotted prefix whose `/`-joined form plus `.py` is a path); (4) the end of such a path (a
    reporter whose class names start below the repository root). Several paths at step 2 or 4 give None, unless exactly
    one of them is in `preferred` (a collection, or a function that gives it, called only when several match). A file
    name may hold dots (`total.v2.test.ts`), so the head is never split to guess a path: only whole paths are compared,
    and the exact match comes before the module walk, which would read `src.pricing.total.test.ts` as the module
    `src/pricing/total.py` that lies beside the test."""
    head = test_id.split("::", 1)[0]
    if not head:
        return None
    known = set(paths)
    if head in known:
        return head
    last = head.rsplit(".", 1)[-1]
    dotted = {path: path.replace("/", ".") for path in known if path.endswith(last)}

    def choose(found: list[str]) -> str | None:
        if len(found) <= 1:
            return found[0] if found else None
        return _pick(sorted(found), preferred() if callable(preferred) else preferred)

    if exact := [path for path, name in dotted.items() if name == head]:
        return choose(exact)
    parts = head.split(".")
    while parts:
        module = "/".join(parts) + ".py"
        if module in known:
            return module
        parts.pop()
    return choose([path for path, name in dotted.items() if name.endswith("." + head)])


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def _names(literal: str, name: str) -> bool:
    """Does the test call's string name the reported test? Reporters join the describe names and the test's with a
    space or ` > `, so the literal is the whole name or its last words."""
    return bool(literal) and (name == literal or name.endswith((" " + literal, "> " + literal)))


AMBIGUOUS = -1  # `_start`: several blocks carry the name and the reported name does not tell them apart


def _literal(lines: list[str], at: int) -> str | None:
    """The string a test call on line `at` opens with (on the line, or on the next when the call ends its line)."""
    if (call := _CALL.match(lines[at])) is not None:
        return call.group("literal")
    if _OPENED.match(lines[at]) and at + 1 < len(lines) and (nxt := _LITERAL.match(lines[at + 1])) is not None:
        return nxt.group("literal")
    return None


def _enclosing(lines: list[str], at: int) -> list[str]:
    """The strings of the test calls that enclose line `at` (earlier lines indented less), outermost first."""
    names: list[str] = []
    level = _indent(lines[at])
    for before in range(at - 1, -1, -1):
        if level and lines[before].strip() and _indent(lines[before]) < level:
            level = _indent(lines[before])
            if (literal := _literal(lines, before)) is not None:
                names.append(literal)
    return names[::-1]


def _start(lines: list[str], name: str) -> int | None:
    """The line of the test call (or Go function) that names `name`: the longest literal wins; among equal literals the
    one whose enclosing calls' strings are the name's words before the literal (`AMBIGUOUS` when none or several is);
    with no call, the first line that holds the name."""
    found: list[tuple[int, int, str]] = []  # (literal length, line, literal)
    go = re.compile(rf"^\s*func\s+(?:\([^)]*\)\s*)?{re.escape(name.split('/', 1)[0])}\s*\(") if name else None
    for at, line in enumerate(lines):
        literal = _literal(lines, at)
        if literal is not None and _names(literal, name):
            found.append((len(literal), at, literal))
        elif go is not None and go.match(line) and not found:
            found.append((len(name), at, name))
    if found:
        top = max(length for length, _, _ in found)
        tied = [(at, literal) for length, at, literal in found if length == top]
        if len(tied) == 1:
            return tied[0][0]
        matching = []
        for at, literal in tied:
            prefix = name[: len(name) - len(literal)].rstrip(" >").replace(" > ", " ")
            context = " ".join(_enclosing(lines, at))
            if context == prefix or (prefix and context.endswith(" " + prefix)):
                matching.append(at)
        return matching[0] if len(matching) == 1 else AMBIGUOUS
    return next((at for at, line in enumerate(lines) if name in line), None)


def _backticks(line: str, inside: bool) -> bool:
    """Does the line end inside a template literal (or a Go raw string), given whether it began inside one? Outside a
    template, quoted strings and escapes are skipped first, so that a lone backtick in a string opens nothing."""
    text = re.sub(r"\\.", "", line)
    if not inside:
        text = re.sub(r"\"[^\"]*\"|'[^']*'", "", text)
    return inside != (text.count("`") % 2 == 1)


def window(text: str, name: str) -> str | None:
    """A test's own lines in a file that is not Python: from the line of the test call that names it (`test`, `it`,
    `describe`, `suite` or `bench`, also `.only`, `.skip` or `.each`, or Go's `func <name>(`) to the line that closes it
    (the first later non-blank line indented no deeper than that line, included when it only closes; a line inside an
    unclosed template literal never ends it). Equal strings in two blocks are told apart by the enclosing `describe`
    strings in the name; if they cannot be, None. The block is given whole: the caller cuts it. None when no line names
    the test."""
    if not name:
        return None
    lines = text.splitlines()
    start = _start(lines, name)
    if start is None or start == AMBIGUOUS:
        return None
    base = _indent(lines[start])
    end = len(lines)
    inside = _backticks(lines[start], False)
    for at in range(start + 1, len(lines)):
        line = lines[at]
        if not inside and line.strip() and _indent(line) <= base:
            end = at + 1 if _CLOSING.match(line) else at
            break
        inside = _backticks(line, inside)
    return "\n".join(lines[start:end])
