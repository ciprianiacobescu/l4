"""The source encoding a Python file declares (SPEC L4-SEC-042).

Python honours a `# coding: <name>` cookie (PEP 263) on the first or second line, or a byte-order mark. The harness and
the judge read every file as UTF-8, so a file that names another encoding (`utf-7` turns `+AAo-` into a newline) shows
them a comment where Python runs code. Every Python file that a step or a unit adds or changes must therefore be UTF-8:
`non_utf8` names the encoding when it is not, with `tokenize.detect_encoding`, the function the interpreter's own
reading of the cookie is modelled on. The name returned is the one `tokenize` gives (`latin-1` is `iso-8859-1`); every
spelling of UTF-8 (`UTF8`, `utf_8`, `u8`) is returned as `utf-8` and every spelling of ASCII as `ascii`, the two
encodings that `non_utf8` accepts besides the byte-order-mark form `utf-8-sig`.

Only the first two lines can hold a cookie, so no file is ever read whole: a reader hands over at most
`COOKIE_PREFIX_BYTES + 1` bytes (`read_inside_prefix`, `Git.blob_prefix`) and `non_utf8` decides from them. A prefix
that ends inside line 1 or line 2 cannot be decided when that line is a comment or blank (the cookie may follow):
that is `UNREADABLE`, a violation like any other encoding. A cut line that starts with code cannot hold a cookie,
and neither can line 2 after a line 1 of code, so a long line of code is fine. The cut bytes are never decoded.
"""

import codecs
import io
import os
import re
import tokenize
from collections.abc import Callable
from pathlib import PurePosixPath
from typing import Any

PYTHON_SUFFIXES = (".py", ".pyi")
COOKIE_PREFIX_BYTES = 64 * 1024  # a reader needs this many bytes + 1 to know whether the file goes on
UTF8 = ("utf-8", "utf-8-sig")  # `utf-8-sig`: a file that starts with a byte-order mark
SAFE = (*UTF8, "ascii")  # ASCII is a subset of UTF-8: the same bytes read the same, so nothing hides behind it
UNDECODABLE = "undecodable"  # an unknown codec, a BOM that contradicts the cookie, a first line that is not text
UNREADABLE = "unreadable"  # line 1 or 2 is a comment or blank line longer than the prefix: a cookie may follow
MAX_LINK_HOPS = 40  # links followed on the way to a file (the kernel allows 40 as well)
_BOM = b"\xef\xbb\xbf"
_COMMENT_OR_BLANK = re.compile(rb"[ \t\f]*(?:#|$)")  # a line a cookie may sit on (PEP 263), cut or not


def is_python_file(path: str) -> bool:
    return PurePosixPath(path).suffix.lower() in PYTHON_SUFFIXES


def _lines(data: bytes) -> bytes:
    """The compiler turns every line ending (`\\r\\n`, a lone `\\r`) into `\\n` before it looks for the cookie, so the
    lines are counted the same way here."""
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def declared_encoding(data: bytes) -> str:
    """The encoding of a Python source that is read whole: its cookie or byte-order mark, else `utf-8`. `UNDECODABLE`
    when the declaration is wrong (the interpreter would refuse the file, and no check can read it)."""
    try:
        name = tokenize.detect_encoding(io.BytesIO(_lines(data)).readline)[0]  # it leaves a spelling like `UTF8` as is
        canonical = codecs.lookup(name).name
    except (SyntaxError, UnicodeError, LookupError, ValueError):
        return UNDECODABLE
    return canonical if canonical in SAFE else name


def non_utf8(data: bytes) -> str | None:
    """The declared encoding when it is not UTF-8 (or ASCII), else None. `data` is the start of a file, as many bytes as
    a reader took (at most `COOKIE_PREFIX_BYTES + 1`; more is cut): a file of `COOKIE_PREFIX_BYTES` bytes or fewer is
    read whole; a longer one is judged by its first two lines (see the module text), `UNREADABLE` if they cannot be."""
    if len(data) <= COOKIE_PREFIX_BYTES:
        encoding = declared_encoding(data)
        return None if encoding in SAFE else encoding
    cut = data[:COOKIE_PREFIX_BYTES].removesuffix(b"\r")  # a \r\n may be cut between its two bytes: the line goes on
    *done, partial = _lines(cut).split(b"\n")  # complete lines, then the line the cut ends in
    if len(done) >= 2:
        encoding = declared_encoding(done[0] + b"\n" + done[1] + b"\n")
        return None if encoding in SAFE else encoding
    if done:  # line 1 is complete: its cookie or its code settles line 1 and, if it is code, line 2 too
        encoding = declared_encoding(done[0] + b"\n")
        if encoding not in SAFE:
            return encoding
        if not _COMMENT_OR_BLANK.match(done[0].removeprefix(_BOM)):
            return None  # line 1 is code: no cookie is looked for on line 2
    elif not _COMMENT_OR_BLANK.match(partial.removeprefix(_BOM)):
        return None  # line 1 is code and is cut: no cookie on it or on line 2
    cut_line = partial if done else partial.removeprefix(_BOM)
    return UNREADABLE if _COMMENT_OR_BLANK.match(cut_line) else None  # line 1 or 2 is cut where a cookie may sit


def shown(path: str) -> str:
    """A name for a message or an event: bytes that are not UTF-8 appear as `\\xff`, never as the lone surrogate that
    `os.fsdecode` gives them, which no UTF-8 writer (the run ledger included) can write."""
    return os.fsencode(path).decode("utf-8", "backslashreplace")


_LONE_SURROGATE = re.compile("[\\ud800-\\udfff]")  # a str holds no valid pair: every one of these is lone


def has_surrogate(text: str) -> bool:
    """Whether `text` holds a lone surrogate, which no UTF-8 writer can write. One scan; the common answer is no."""
    return _LONE_SURROGATE.search(text) is not None


def _display(match: re.Match[str]) -> str:
    char = match.group()
    return shown(char) if "\udc80" <= char <= "\udcff" else f"\\u{ord(char):04x}"


def surrogate_free(value: Any) -> Any:
    """`value` with every lone surrogate of its text (str keys and values, nested in dicts, lists and tuples; a tuple
    becomes a list) written as text a UTF-8 writer can write: a byte 0x80..0xFF that `os.fsdecode` escaped as `\\xff`
    (the form of `shown`), any other lone surrogate as `\\ud800`. Each character is converted alone, so escaped bytes
    that would form a UTF-8 character together stay text. A str without a surrogate comes back as the same object."""
    if isinstance(value, str):
        return _LONE_SURROGATE.sub(_display, value) if has_surrogate(value) else value
    if isinstance(value, dict):
        return {surrogate_free(k) if isinstance(k, str) else k: surrogate_free(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [surrogate_free(v) for v in value]
    return value


def describe(encoding: str) -> str:
    """What is wrong with a file that `non_utf8` named `encoding`, for a guard event and a finding."""
    if encoding == UNREADABLE:
        return (
            f"line 1 or 2 is unreadable: a comment or blank line longer than {COOKIE_PREFIX_BYTES} bytes, "
            "so a coding cookie may follow"
        )
    if encoding == UNDECODABLE:
        return "its encoding declaration is wrong or its first line is not text"
    return f"it declares the encoding {encoding}"


def resolve_links(path: str, read_link: Callable[[str], str | None]) -> tuple[str | None, list[str]]:
    """Follow `path` (relative to a root, `/`-separated) through the links of a tree, the way the kernel does:
    `read_link(p)` returns the target text when `p` is a link and None when it is not (or is absent). A link in the
    middle of the path (a linked directory) is followed too, a target is read relative to the directory of its link,
    and the walk never leaves the root. Returns (the path of what it ends at, the links followed in order); the first
    is None for an absolute target, a target above the root, an empty target or more than `MAX_LINK_HOPS` links (a
    loop). What the path ends at may be a directory, a missing path or a file: the caller looks."""
    followed: list[str] = []
    done: list[str] = []
    todo = path.split("/")
    while todo:
        name = todo.pop(0)
        if name in ("", "."):
            continue
        if name == "..":
            if not done:
                return None, followed
            done.pop()
            continue
        here = "/".join([*done, name])
        target = read_link(here)
        if target is None:
            done.append(name)
            continue
        followed.append(here)
        if len(followed) > MAX_LINK_HOPS or not target or target.startswith("/"):
            return None, followed
        todo = [*target.split("/"), *todo]
    return "/".join(done) or None, followed
