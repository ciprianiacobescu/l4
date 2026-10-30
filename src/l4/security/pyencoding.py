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
import re
import tokenize
from pathlib import PurePosixPath

PYTHON_SUFFIXES = (".py", ".pyi")
COOKIE_PREFIX_BYTES = 64 * 1024  # a reader needs this many bytes + 1 to know whether the file goes on
UTF8 = ("utf-8", "utf-8-sig")  # `utf-8-sig`: a file that starts with a byte-order mark
SAFE = (*UTF8, "ascii")  # ASCII is a subset of UTF-8: the same bytes read the same, so nothing hides behind it
UNDECODABLE = "undecodable"  # an unknown codec, a BOM that contradicts the cookie, a first line that is not text
UNREADABLE = "unreadable"  # line 1 or 2 is a comment or blank line longer than the prefix: a cookie may follow
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
