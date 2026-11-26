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


def test_names_of(path: str, ids: Iterable[str], paths: Collection[str]) -> list[str]:
    """The test names (after the first `::`) of the report `ids` that lie in the file `path`, `paths` being the files
    that `file_of_id` chooses among. The red step (L4-IMP-089) and the carry (L4-VER-097) read a report the one way."""
    heads: dict[str, str | None] = {}
    names: list[str] = []
    for test in ids:
        head = test.partition("::")[0]
        if head not in heads:
            heads[head] = file_of_id(test, paths)
        if heads[head] == path:
            names.append(test.partition("::")[2])
    return names


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


class CallIndex:
    """The test-call string of every line of a file, read once, and the lines that carry each string. `_start` run for
    many names of one file (the carry's, L4-VER-097) would otherwise read every line again for every name."""

    def __init__(self, lines: list[str]) -> None:
        self.literals = [_literal(lines, at) for at in range(len(lines))]
        self.by_literal: dict[str, list[int]] = {}
        for at, literal in enumerate(self.literals):
            if literal:
                self.by_literal.setdefault(literal, []).append(at)

    def found(self, name: str) -> list[tuple[int, int, str]]:
        """`(literal length, line, literal)` of every call whose string names `name`, in line order: the literal is the
        name or what follows one of its spaces (`_names`), so the candidates are the name's own suffixes."""
        suffixes = {name, *(name[at + 1 :] for at, char in enumerate(name) if char == " ")}
        return sorted(
            (len(literal), at, literal)
            for literal in suffixes
            if literal and _names(literal, name)
            for at in self.by_literal.get(literal, ())
        )  # fmt: skip


def _enclosing(lines: list[str], at: int, calls: CallIndex | None = None) -> list[str]:
    """The strings of the test calls that enclose line `at` (earlier lines indented less), outermost first."""
    names: list[str] = []
    level = _indent(lines[at])
    for before in range(at - 1, -1, -1):
        if level and lines[before].strip() and _indent(lines[before]) < level:
            level = _indent(lines[before])
            literal = calls.literals[before] if calls is not None else _literal(lines, before)
            if literal is not None:
                names.append(literal)
    return names[::-1]


def _start(lines: list[str], name: str, calls: CallIndex | None = None) -> int | None:
    """The line of the test call (or Go function) that names `name`: the longest literal wins; among equal literals the
    one whose enclosing calls' strings are the name's words before the literal (`AMBIGUOUS` when none or several is);
    with no call, the first line that holds the name. With `calls` (the file's `CallIndex`) only calls are looked at,
    through the index, and no call is None: `call_span` wants nothing else."""
    found: list[tuple[int, int, str]] = []  # (literal length, line, literal)
    if calls is not None:
        found = calls.found(name)
    else:
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
            context = " ".join(_enclosing(lines, at, calls))
            if context == prefix or (prefix and context.endswith(" " + prefix)):
                matching.append(at)
        return matching[0] if len(matching) == 1 else AMBIGUOUS
    if calls is not None:
        return None
    return next((at for at, line in enumerate(lines) if name in line), None)


def _backticks(line: str, inside: bool) -> bool:
    """Does the line end inside a template literal (or a Go raw string), given whether it began inside one? Outside a
    template, quoted strings and escapes are skipped first, so that a lone backtick in a string opens nothing."""
    text = re.sub(r"\\.", "", line)
    if not inside:
        text = re.sub(r"\"[^\"]*\"|'[^']*'", "", text)
    return inside != (text.count("`") % 2 == 1)


def _span(lines: list[str], name: str, calls: CallIndex | None = None) -> tuple[int, int] | None:
    """The first line and the line after the last of the test `name` in `lines` (see `window`), or None."""
    if not name:
        return None
    start = _start(lines, name, calls)
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
    return start, end


def call_span(lines: list[str], name: str, calls: CallIndex | None = None) -> tuple[int, int] | None:
    """The first line and the line after the last of the test `name`, as `window` gives them, but only when the block
    starts at a call line (`test`, `it`, `describe`, `suite` or `bench`, with its modifiers) whose string names the test
    (L4-VER-097): not `_start`'s last resort, the first line that holds the name, and not a Go function. None when the
    test is not found, or is found at several places that the enclosing strings do not tell apart. `calls` is the file's
    `CallIndex` when many names of one file are asked for."""
    span = _span(lines, name, calls)
    if span is None:
        return None
    literal = calls.literals[span[0]] if calls is not None else _literal(lines, span[0])
    return span if literal is not None and _names(literal, name) else None


def window(text: str, name: str) -> str | None:
    """A test's own lines in a file that is not Python: from the line of the test call that names it (`test`, `it`,
    `describe`, `suite` or `bench`, also `.only`, `.skip` or `.each`, or Go's `func <name>(`) to the line that closes it
    (the first later non-blank line indented no deeper than that line, included when it only closes; a line inside an
    unclosed template literal never ends it). Equal strings in two blocks are told apart by the enclosing `describe`
    strings in the name; if they cannot be, None. The block is given whole: the caller cuts it. None when no line names
    the test."""
    lines = text.splitlines()
    span = _span(lines, name)
    return None if span is None else "\n".join(lines[span[0] : span[1]])


def outside_tests(text: str, names: Iterable[str]) -> str:
    """The lines of `text` that lie in no `window` of `names` (a constant, a fixture or a helper that the tests of the
    file share, an import, a comment), whitespace-only lines dropped, joined with `\\n`. A test appended to a file
    brings the blank line before it, which lies outside every window: dropping blank lines keeps that out. A name that
    has no window (not found, ambiguous) removes nothing. Pure."""
    lines = text.splitlines()
    inside: set[int] = set()
    for name in names:
        if (span := _span(lines, name)) is not None:
            inside.update(range(*span))
    return "\n".join(line for at, line in enumerate(lines) if at not in inside and line.strip())
