"""Byte-safe task marker writes (SPEC 4.6, L4-TMW-001). Principle P4: tasks.md changes by one byte, atomically."""

from dataclasses import dataclass
from pathlib import Path

from l4.fsutil import UnsafeFile, atomic_write_bytes, read_regular_file
from l4.specs.base import MarkerWriteError

MAX_TASKS_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True)
class Line:
    number: int  # 1-based
    start: int  # byte offset of the first byte of the line (a BOM on line 1 counts)
    text: str  # without the terminator; a BOM stays in the text because OpenSpec's \s matches it
    terminator: bytes  # b"\r\n", b"\n" or b""

    def offset_of(self, char_index: int) -> int:
        """Byte offset in the file of the character at `char_index` of `text`."""
        return self.start + len(self.text[:char_index].encode("utf-8", "surrogateescape"))


def split_lines(data: bytes) -> list[Line]:
    """Split on b"\\n" only, never on a lone b"\\r": OpenSpec numbers lines over split('\\n'), so any other rule
    makes the harness and the CLI disagree about line numbers (spikes/04). b"\\r\\n" is kept as the terminator."""
    lines: list[Line] = []
    start = 0
    while start < len(data):
        end = data.find(b"\n", start)
        if end == -1:
            content, terminator, next_start = data[start:], b"", len(data)
        else:
            content, terminator, next_start = data[start:end], b"\n", end + 1
            if content.endswith(b"\r"):
                content, terminator = content[:-1], b"\r\n"
        lines.append(Line(len(lines) + 1, start, content.decode("utf-8", "surrogateescape"), terminator))
        start = next_start
    return lines


@dataclass(frozen=True)
class MarkerWrite:
    path: Path
    offset: int
    old: bytes
    new: bytes
    size: int


def write_marker(path: Path, offset: int, old: bytes, new: bytes) -> MarkerWrite:
    """Replace the one byte `old` at `offset` with `new`: temp file + rename, then re-read and compare.

    M1: spec-providers 1.9 (wide-bracket refusal), 1.10 (path_lock), 1.11 (foreign-edit abort). M0 has one writer
    per unit, under the unit lock, between agent steps.
    """
    if len(old) != 1 or len(new) != 1:
        raise MarkerWriteError("a marker is exactly one byte")
    try:
        before = read_regular_file(path, limit=MAX_TASKS_BYTES)
    except UnsafeFile as exc:
        raise MarkerWriteError(str(exc)) from None
    except OSError as exc:
        raise MarkerWriteError(f"cannot read {path.name}: {type(exc).__name__}") from None
    # the byte must still sit between "[" and "]": a stale offset (the file changed since it was parsed) is refused
    if not (0 < offset < len(before) - 1) or before[offset - 1 : offset + 2] != b"[" + old + b"]":
        raise MarkerWriteError(f"{path.name}: byte at offset {offset} is not a {old!r} checkbox marker")
    expected = before[:offset] + new + before[offset + 1 :]
    atomic_write_bytes(path, expected)
    if path.read_bytes() != expected:
        raise MarkerWriteError(f"{path.name}: post-write verification failed")
    return MarkerWrite(path, offset, old, new, len(expected))
