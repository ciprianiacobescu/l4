"""The source encoding a Python file declares (SPEC L4-SEC-042).

Python honours a `# coding: <name>` cookie (PEP 263) on the first or second line, or a byte-order mark. The harness and
the judge read every file as UTF-8, so a file that names another encoding (`utf-7` turns `+AAo-` into a newline) shows
them a comment where Python runs code. Every Python file that a step or a unit adds or changes must therefore be UTF-8:
`non_utf8` names the encoding when it is not, with `tokenize.detect_encoding`, the function the interpreter's own
reading of the cookie is modelled on. The name returned is the one `tokenize` gives (`latin-1` is `iso-8859-1`); every
spelling of UTF-8 (`UTF8`, `utf_8`, `u8`) is returned as `utf-8`.
"""

import codecs
import io
import tokenize
from pathlib import PurePosixPath

PYTHON_SUFFIXES = (".py", ".pyi")
UTF8 = ("utf-8", "utf-8-sig")  # `utf-8-sig`: a file that starts with a byte-order mark
UNDECODABLE = "undecodable"  # an unknown codec, a BOM that contradicts the cookie, a first line that is not text


def is_python_file(path: str) -> bool:
    return PurePosixPath(path).suffix.lower() in PYTHON_SUFFIXES


def declared_encoding(data: bytes) -> str:
    """The encoding of a Python source: its cookie or byte-order mark, else `utf-8`. `UNDECODABLE` when the declaration
    is wrong (the interpreter would refuse the file, and no check can read it). The compiler turns every line ending
    (`\\r\\n`, a lone `\\r`) into `\\n` before it looks for the cookie, so the lines are counted the same way here."""
    lines = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    try:
        name = tokenize.detect_encoding(io.BytesIO(lines).readline)[0]  # it leaves a spelling like `UTF8` as written
        canonical = codecs.lookup(name).name
    except (SyntaxError, UnicodeError, LookupError, ValueError):
        return UNDECODABLE
    return canonical if canonical in UTF8 else name


def non_utf8(data: bytes) -> str | None:
    """The declared encoding when it is not UTF-8, else None."""
    encoding = declared_encoding(data)
    return None if encoding in UTF8 else encoding
