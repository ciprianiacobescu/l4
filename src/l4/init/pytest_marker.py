"""Register the `l4` pytest marker in the adopting project (L4-INS-002, M1.9 P4).

The harness's tests carry `@pytest.mark.l4("C-xxxxxxxx")`. The harness's own pytest plugin registers the marker, but
the project's CI does not load it, so a project that runs `pytest --strict-markers` fails at collection. This module
plans the one edit that registers it where pytest reads its configuration, or refuses with the snippet to paste. It
only plans (bytes in, bytes out): `l4 init` and `l4 upgrade` write what it returns, and it never raises.

Where pytest looks first wins, so the order is that of pytest: a `pytest.ini`, `.pytest.ini`, `pytest.toml` or
`.pytest.toml` makes a conftest the only place (a marker added to the pyproject would never be seen); a pyproject with a
`[tool.pytest.ini_options]` table gets the entry appended to its `markers` (or a one-line `markers`); otherwise a
`pytest_configure` in the root `conftest.py` calls `addinivalue_line`. A project whose pytest configuration lives in
`tox.ini` or `setup.cfg` is not touched through the pyproject either: a new table there would shadow it.

The pyproject edit is textual and byte-minimal (the file's own indent, quotes and trailing comma), then verified: the
edited text is parsed again and must equal the original document plus that one entry, or the edit is refused.
"""

import ast
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MARKER = "l4(*ids): the acceptance criteria (C-xxxxxxxx) this test checks"  # the text of the harness plugin's marker
_INI_FILES = ("pytest.ini", ".pytest.ini", "pytest.toml", ".pytest.toml")
_HEADER = re.compile(r"^\s*\[tool\.pytest\.ini_options\]\s*(#.*)?$")
_ANY_HEADER = re.compile(r"^\s*\[")
_MARKERS_KEY = re.compile(r"^(?P<indent>\s*)markers\s*=\s*\[")
MAX_BYTES = 1024 * 1024
CONFTEST_FUNCTION = (
    "def pytest_configure(config):\n"
    f'    config.addinivalue_line("markers", "{MARKER}")\n'
)  # fmt: skip


@dataclass(frozen=True)
class MarkerEdit:
    """The one file to write. `data` is its new content; None means the marker is already registered there."""

    path: str  # relative to the repository, posix
    data: bytes | None
    created: bool = False  # the file does not exist yet


@dataclass(frozen=True)
class MarkerRefusal:
    reason: str
    snippet: str  # what to paste by hand


def _snippet(where: str) -> str:
    if where == "conftest":
        return f'def pytest_configure(config):\n    config.addinivalue_line("markers", "{MARKER}")\n'
    return f'markers = [\n    "{MARKER}",\n]  # under [tool.pytest.ini_options], or in your pytest configuration\n'


def _read(repo: Path, name: str) -> str | None:
    path = repo / name
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
            return None
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _registered(markers: Any) -> bool:
    entries = markers if isinstance(markers, list) else []
    return any(isinstance(m, str) and m.lstrip().startswith(("l4(", "l4:")) for m in entries)


def _ini_registered(text: str) -> bool:
    inside = False
    for line in text.splitlines():
        if re.match(r"^markers\s*[=:]", line):
            inside = True
            rest = line.split("=", 1)[-1].strip()
            if rest.startswith(("l4(", "l4:")):
                return True
        elif inside and line[:1].isspace() and line.strip():
            if line.strip().startswith(("l4(", "l4:")):
                return True
        elif inside:
            inside = False
    return False


def _conftest_registered(text: str) -> bool:
    return re.search(r"addinivalue_line\(\s*[\"']markers[\"']\s*,\s*[\"']l4[(:]", text) is not None


def _already(repo: Path, doc: dict[str, Any] | None) -> str | None:
    """Where the marker is registered already, as a path, or None."""
    if doc is not None:
        ini = doc.get("tool", {}).get("pytest", {}).get("ini_options", {})
        if isinstance(ini, dict) and _registered(ini.get("markers")):
            return "pyproject.toml"
    for name in (*_INI_FILES, "tox.ini", "setup.cfg"):
        if (text := _read(repo, name)) is not None and not name.endswith(".toml") and _ini_registered(text):
            return name
    for name in _INI_FILES:
        if name.endswith(".toml") and (text := _read(repo, name)) is not None:
            try:
                markers = tomllib.loads(text).get("pytest", {}).get("markers")
            except tomllib.TOMLDecodeError:
                markers = None
            if _registered(markers):
                return name
    if (text := _read(repo, "conftest.py")) is not None and _conftest_registered(text):
        return "conftest.py"
    return None


@dataclass(frozen=True)
class _Token:
    kind: str  # "string" | "comment" | "char"
    start: int
    end: int  # exclusive


def _tokens(text: str, start: int = 0, end: int | None = None):  # noqa: ANN202 - a generator of _Token
    """The one TOML scanner (M1.10 decision 12): `text[start:end]` as strings (basic and literal, one line or
    multi-line), comments and single characters. A quote inside the other kind of string, or a `#` or `]` inside any
    string, is part of that string. Raises ValueError for a string that is not closed."""
    stop = len(text) if end is None else end
    i = start
    while i < stop:
        ch = text[i]
        if ch == "#":
            j = text.find("\n", i, stop)
            j = stop if j < 0 else j
            yield _Token("comment", i, j)
            i = j
        elif ch in "\"'":
            multi = text.startswith(ch * 3, i)
            quote = ch * 3 if multi else ch
            j = i + len(quote)
            while True:
                if j >= stop or (not multi and text[j] == "\n"):
                    raise ValueError("unterminated string")
                if ch == '"' and text[j] == "\\":  # an escape in a basic string; a literal string has none
                    j += 2
                    continue
                if text.startswith(quote, j):
                    j += len(quote)
                    if multi:  # `""""x"""` ends with the last three of a run of quotes
                        while j < stop and text[j] == ch:
                            j += 1
                    break
                j += 1
            yield _Token("string", i, j)
            i = j
        else:
            yield _Token("char", i, i + 1)
            i += 1


def _close_of(text: str, start: int) -> int | None:
    """The index of the `]` that closes the array opened at `text[start]`; strings and comments are skipped."""
    depth = 0
    try:
        for token in _tokens(text, start):
            if token.kind != "char":
                continue
            if text[token.start] == "[":
                depth += 1
            elif text[token.start] == "]":
                depth -= 1
                if depth == 0:
                    return token.start
    except ValueError:
        return None
    return None


def _quote(array_body: str) -> str:
    """The quote character the array's own last string opens with, `"` for an empty array."""
    try:
        strings = [t for t in _tokens(array_body) if t.kind == "string"]
    except ValueError:
        return '"'
    return array_body[strings[-1].start] if strings else '"'


def _split_comment(text: str, scan_from: int, line_start: int, line_end: int) -> tuple[str, str]:
    """The line `text[line_start:line_end]` as code and trailing comment: the comment is the first `#` of that line
    outside every string. The scan starts at `scan_from` (the array's start), so a multi-line string that began on an
    earlier line is not mistaken for code."""
    try:
        comment = next(
            (t for t in _tokens(text, scan_from, line_end) if t.kind == "comment" and t.start >= line_start), None
        )
    except ValueError:
        return text[line_start:line_end], ""
    if comment is None:
        return text[line_start:line_end], ""
    code_end = comment.start
    while code_end > line_start and text[code_end - 1] in " \t":
        code_end -= 1
    return text[line_start:code_end], text[code_end:line_end]


def _edit_pyproject(text: str) -> str | None:
    """`text` with the marker added to `[tool.pytest.ini_options]`, or None when the layout is not one this edits."""
    lines = text.splitlines(keepends=True)
    header = next((n for n, line in enumerate(lines) if _HEADER.match(line.rstrip("\r\n"))), None)
    if header is None:
        return None
    end = next((n for n in range(header + 1, len(lines)) if _ANY_HEADER.match(lines[n])), len(lines))
    eol = "\r\n" if lines[header].endswith("\r\n") else "\n"
    for n in range(header + 1, end):
        match = _MARKERS_KEY.match(lines[n])
        if match is None:
            continue
        offset = sum(len(line) for line in lines[:n]) + match.end() - 1  # the `[`
        close = _close_of(text, offset)
        if close is None:
            return None
        body = text[offset + 1 : close]
        quote = _quote(body)
        entry = f"{quote}{MARKER}{quote}"
        if "\n" not in body:  # one line: `markers = ["a", "b"]`
            stripped = body.rstrip()
            if not stripped.strip():
                return text[: offset + 1] + entry + text[close:]
            comma = "" if stripped.endswith(",") else ","
            return text[: offset + 1] + stripped + f"{comma} {entry}" + body[len(stripped) :] + text[close:]
        # several lines: a new line after the last element, in the elements' own indent
        elements = [line for line in body.splitlines() if line.strip() and not line.strip().startswith("#")]
        if not elements:
            return None
        indent = re.match(r"\s*", elements[0]).group(0)  # type: ignore[union-attr]
        last = body.rstrip().rstrip("\r\n")
        last_line_start = last.rfind("\n") + 1
        abs_start = offset + 1 + last_line_start
        code, comment = _split_comment(text, offset + 1, abs_start, offset + 1 + len(last))
        trailing_comma = code.rstrip().endswith(",")
        fixed_last = last[last_line_start:] if trailing_comma else f"{code.rstrip()},{comment}"
        added = f"{indent}{entry}{',' if trailing_comma else ''}"
        rebuilt = last[:last_line_start] + fixed_last + eol + added + body[len(last) :]
        return text[: offset + 1] + rebuilt + text[close:]
    key = f'markers = ["{MARKER}"]{eol}'
    return "".join(lines[: header + 1]) + key + "".join(lines[header + 1 :])


def _verified(old: str, new: str) -> bool:
    """The new text parses and equals the old document with exactly the marker added."""
    try:
        before, after = tomllib.loads(old), tomllib.loads(new)
    except tomllib.TOMLDecodeError:
        return False
    options = before.get("tool", {}).get("pytest", {}).get("ini_options", {})
    wanted = {**options, "markers": [*options.get("markers", []), MARKER]}
    expected = {**before, "tool": {**before["tool"], "pytest": {**before["tool"]["pytest"], "ini_options": wanted}}}
    return after == expected


def _conftest_route(repo: Path) -> MarkerEdit | MarkerRefusal:
    text = _read(repo, "conftest.py")
    if text is None:
        if (repo / "conftest.py").exists() or (repo / "conftest.py").is_symlink():
            return MarkerRefusal("conftest.py cannot be read", _snippet("conftest"))
        header = "# Registered by `l4 init`: the harness's tests carry @pytest.mark.l4(...).\n\n\n"
        return MarkerEdit("conftest.py", (header + CONFTEST_FUNCTION).encode(), created=True)
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return MarkerRefusal("conftest.py does not parse", _snippet("conftest"))
    if any(isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) and n.name == "pytest_configure" for n in tree.body):
        return MarkerRefusal("conftest.py already defines pytest_configure: add the line to it", _snippet("conftest"))
    lead = "" if text.endswith("\n") or not text else "\n"
    return MarkerEdit("conftest.py", (text + lead + "\n\n" + CONFTEST_FUNCTION).encode())


def register_l4_marker(repo: Path) -> MarkerEdit | MarkerRefusal:
    """The edit that registers the `l4` marker in `repo`, `MarkerEdit(data=None)` when it already is, or a refusal."""
    pyproject = _read(repo, "pyproject.toml")
    doc: dict[str, Any] | None = None
    if pyproject is not None:
        try:
            doc = tomllib.loads(pyproject)
        except tomllib.TOMLDecodeError:
            return _conftest_route(repo)  # a pyproject that does not parse is not edited
    if (found := _already(repo, doc)) is not None:
        return MarkerEdit(found, None)
    if any((repo / name).exists() for name in _INI_FILES):
        return _conftest_route(repo)  # pytest reads these before the pyproject
    options = doc.get("tool", {}).get("pytest", {}).get("ini_options") if doc is not None else None
    if options is None:
        return _conftest_route(repo)  # no table to extend; a new one could shadow a tox.ini or setup.cfg configuration
    markers = options.get("markers") if isinstance(options, dict) else None
    if not isinstance(options, dict) or (markers is not None and not isinstance(markers, list)):
        reason = "pyproject.toml: [tool.pytest.ini_options] is not in a form this edits"
        return MarkerRefusal(reason, _snippet("pyproject"))
    edited = _edit_pyproject(pyproject)
    if edited is None:
        return MarkerRefusal(
            "pyproject.toml: pytest.ini_options is an inline or dotted table, which this does not edit",
            _snippet("pyproject"),
        )
    if not _verified(pyproject, edited):
        return MarkerRefusal(
            "pyproject.toml: the edited file did not re-parse to the original plus the marker", _snippet("pyproject")
        )
    return MarkerEdit("pyproject.toml", edited.encode())
