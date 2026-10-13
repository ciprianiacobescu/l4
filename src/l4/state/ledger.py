"""The per-run ledger (SPEC 12.1, L4-STA-001): `<unit_dir>/.l4/ledger/<run-id>.jsonl`, one file per run.

M0 keeps the event-type set open (any `area.name`); string values are redacted at write time.
M1: state-vcs-locks 1.1 (OpenSpec tolerance contract test), 1.15 (EventType), 1.17 (check_run_file).
"""

import contextlib
import json
import logging
import os
import re
import shutil
import stat
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from l4 import __version__
from l4.buildinfo import harness_commit
from l4.exitcodes import ExitCode, L4Exit
from l4.fsutil import UnsafeFile, read_regular_file, reject_symlinks
from l4.redact import Redactor

MAX_LEDGER_FILE_BYTES = 16 * 1024 * 1024
RUN_ID = re.compile(r"^r-\d{8}T\d{4}Z-[0-9a-f]{4}$")
EVENT_TYPE = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")
RESERVED = frozenset({"ts", "run_id", "unit", "seq", "type"})
TS_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
_mirror = logging.getLogger("l4.ledger")  # `l4.log.JsonlHandler` copies each event into the run's JSONL log


class LedgerClosed(RuntimeError):
    pass


class LedgerCorrupt(L4Exit):
    def __init__(self, message: str) -> None:
        super().__init__(ExitCode.INTERNAL_ERROR, f"ledger corrupt: {message}")


@dataclass(frozen=True)
class LedgerEvent:
    ts: datetime
    run_id: str
    unit: str
    seq: int
    type: str
    data: Mapping[str, Any] = field(default_factory=dict)  # the payload keys, which sit at the top level of the line


def ledger_dir(unit_dir: Path) -> Path:
    return unit_dir / ".l4" / "ledger"


def ledger_path(unit_dir: Path, run_id: str) -> Path:
    if not RUN_ID.match(run_id):
        raise ValueError(f"not a run id: {run_id!r}")
    return ledger_dir(unit_dir) / f"{run_id}.jsonl"


def _now() -> datetime:
    return datetime.now(UTC)


MAX_REPORTED_SEQS = 100
MAX_TAMPER_READ = 4 * 1024 * 1024  # bytes past the writer's copy read to describe a tamper: an agent sets the size


def _read_start(path: Path, limit: int) -> bytes:
    """At most `limit` bytes from the start of `path` (never through a symlink)."""
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        chunks, left = [], limit
        while left > 0 and (chunk := os.read(fd, min(left, 1 << 20))):
            chunks.append(chunk)
            left -= len(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


@dataclass(frozen=True)
class Tamper:
    """What `restore_if_tampered` found: `kind` is truncated (lines of the writer's copy are gone and nothing was
    added: an agent resetting the file to HEAD), appended (only foreign lines added), edited (both), or replaced
    (not the writer's file any more: another inode, a symlink, a directory)."""

    kind: str
    removed_seqs: list[int]  # the first MAX_REPORTED_SEQS seqs of the writer's lines that are missing on disk
    removed_count: int
    foreign_lines: int  # lines on disk that the writer never wrote (in the first MAX_TAMPER_READ bytes past its size)

    def fields(self) -> dict[str, Any]:
        return {"kind": self.kind, "removed_seqs": self.removed_seqs, "removed_count": self.removed_count,
                "foreign_lines": self.foreign_lines}  # fmt: skip


def _line_seq(line: bytes) -> int | None:
    try:
        seq = json.loads(line).get("seq")
    except (ValueError, AttributeError):
        return None
    return seq if isinstance(seq, int) else None


def _describe_tamper(written: bytes, on_disk: bytes, same_file: bool) -> Tamper:
    mine, theirs = written.splitlines(), on_disk.splitlines()
    left: dict[bytes, int] = {}
    for line in theirs:
        left[line] = left.get(line, 0) + 1
    removed: list[bytes] = []
    for line in mine:
        if left.get(line, 0) > 0:
            left[line] -= 1
        else:
            removed.append(line)
    foreign = sum(left.values())
    seqs = [seq for seq in map(_line_seq, removed) if seq is not None]
    if not same_file:
        kind = "replaced"
    elif removed and foreign:
        kind = "edited"
    else:
        kind = "truncated" if removed else "appended"
    return Tamper(kind, seqs[:MAX_REPORTED_SEQS], len(removed), foreign)


class LedgerWriter:
    """Appends to one run's file: `run.started` first, strictly increasing `seq`, fsync per line, `finish()` last.
    `file_filter` is applied to each serialised line before it is written to the file (M1.9, P5)."""

    def __init__(
        self,
        fd: int,
        unit: str,
        run_id: str,
        redactor: Redactor,
        clock: Callable[[], datetime],
        file_filter: Callable[[str], str] | None = None,
    ) -> None:
        self._fd = fd
        self._file_filter = file_filter
        self._unit = unit
        self._run_id = run_id
        self._redactor = redactor
        self._clock = clock
        self._lock = threading.Lock()
        self._seq = 0
        self._last_ts: datetime | None = None
        self._closed = False
        self._path: Path | None = None
        self._observers: list[Callable[[LedgerEvent], None]] = []
        self._written = bytearray()  # a copy of every byte this writer put in the file: the worktree is agent-writable

    @classmethod
    def open(
        cls,
        unit_dir: Path,
        unit: str,
        run_id: str,
        *,
        redactor: Redactor,
        clock: Callable[[], datetime] = _now,
        observers: Sequence[Callable[[LedgerEvent], None]] = (),
        file_filter: Callable[[str], str] | None = None,
        **started: Any,
    ) -> "LedgerWriter":
        path = ledger_path(unit_dir, run_id)
        reject_symlinks(unit_dir, ".l4", "ledger")  # the ledger must land in the worktree, so it reaches the branch
        path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_APPEND | os.O_CLOEXEC | os.O_NOFOLLOW
        writer = cls(
            os.open(path, flags, 0o644), unit, run_id, redactor, clock, file_filter
        )  # FileExistsError: a run id is used once
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
        writer._path = path
        writer._observers.extend(observers)  # before `run.started`, so an observer sees the run from its first event
        writer.append("run.started", harness_version=__version__, harness_commit=harness_commit(), **started)
        return writer

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def path(self) -> Path | None:
        return self._path

    def append(self, event_type: str, /, **data: Any) -> LedgerEvent:
        if not EVENT_TYPE.match(event_type):
            raise ValueError(f"not an event type (expected area.name): {event_type!r}")
        clash = RESERVED & data.keys()
        if clash:
            raise ValueError(f"reserved event field(s): {sorted(clash)}")
        with self._lock:
            if self._closed:
                raise LedgerClosed(f"run {self._run_id} is finished; its ledger takes no more events")
            now = self._clock()
            ts = now if self._last_ts is None or now > self._last_ts else self._last_ts  # never backwards in a run
            seq = self._seq + 1  # stored only once the line is durable, so a failed serialise skips no number
            payload = self._redactor.redact_obj(data)
            envelope = {"ts": ts.strftime(TS_FORMAT), "run_id": self._run_id, "unit": self._unit, "seq": seq}
            text = json.dumps({**envelope, "type": event_type, **payload}, ensure_ascii=False) + "\n"
            # the file (and the copy the tamper check restores from) may hide what must not be committed, such as the
            # forge host (L4-OBS-002); the JSONL mirror and the observers below get the full event
            line = (self._file_filter(text) if self._file_filter is not None else text).encode("utf-8")
            view = memoryview(line)
            while view:
                view = view[os.write(self._fd, view) :]
            os.fsync(self._fd)
            self._written += line
            self._seq, self._last_ts = seq, ts
            event = LedgerEvent(ts, self._run_id, self._unit, seq, event_type, payload)
            _mirror.info(event_type, extra={"l4_event": {**envelope, "type": event_type, **payload}})
            if event_type == "run.finished":
                self._closed = True
                os.close(self._fd)
        for observe in self._observers:
            with contextlib.suppress(Exception):  # the event is durable and redacted: a console line never fails a run
                observe(event)
        return event

    def restore_if_tampered(self) -> "Tamper | None":
        """The run's file lies inside the worktree, where agent steps and agent-written tests run, and the fold
        trusts it. If it no longer holds exactly the bytes this writer wrote (appended or edited lines, a replaced
        inode), rewrite it from the writer's copy. Returns what it found (see `Tamper`) when it had to, else None."""
        with self._lock:
            if self._closed or self._path is None:
                return None
            path = self._path
            try:
                seen = os.stat(path, follow_symlinks=False)
                same = seen.st_ino == os.fstat(self._fd).st_ino and stat.S_ISREG(seen.st_mode)
                on_disk = _read_start(path, len(self._written) + MAX_TAMPER_READ) if same else b""
                intact = same and seen.st_size == len(self._written) and on_disk == self._written
            except OSError:
                same = intact = False
                on_disk = b""
            if intact:
                return None
            tamper = _describe_tamper(bytes(self._written), on_disk, same)
            if same:
                os.ftruncate(self._fd, 0)  # the O_APPEND descriptor then appends at the new end
            else:
                if path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path)
                else:
                    path.unlink(missing_ok=True)
                flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_APPEND | os.O_CLOEXEC | os.O_NOFOLLOW
                os.close(self._fd)
                self._fd = os.open(path, flags, 0o644)
            os.write(self._fd, bytes(self._written))
            os.fsync(self._fd)
            return tamper

    def finish(self, exit_code: int) -> None:
        self.append("run.finished", exit_code=exit_code)


@dataclass(frozen=True)
class LedgerRead:
    events: list[LedgerEvent]
    torn: list[str]  # files whose last line was cut off mid-write and skipped


def _parse_line(name: str, number: int, raw: bytes) -> LedgerEvent:
    where = f"{name}:{number}"
    try:
        body = json.loads(raw)
        ts = datetime.strptime(body.pop("ts"), TS_FORMAT).replace(tzinfo=UTC)
        run_id, unit, seq, type_ = body.pop("run_id"), body.pop("unit"), body.pop("seq"), body.pop("type")
    except (ValueError, KeyError, TypeError, AttributeError):
        raise LedgerCorrupt(f"{where} is not a ledger event") from None
    if not (isinstance(run_id, str) and isinstance(unit, str) and isinstance(type_, str)) or not isinstance(seq, int):
        raise LedgerCorrupt(f"{where} has a field of the wrong type")
    if run_id != name.removesuffix(".jsonl"):
        raise LedgerCorrupt(f"{where} has run_id {run_id!r}, which is not the file's run")
    return LedgerEvent(ts, run_id, unit, seq, type_, body)


def parse_ledger_files(files: Mapping[str, bytes]) -> LedgerRead:
    """Events of several run files, sorted by (ts, run_id, seq). A cut-off last line is skipped and reported; any
    other malformed line is `LedgerCorrupt`."""
    events: list[LedgerEvent] = []
    torn: list[str] = []
    for name in sorted(files):
        chunks = files[name].split(b"\n")
        previous = 0
        last = len(chunks) - 1
        for index, raw in enumerate(chunks):
            if index == last and raw == b"":
                continue  # the file ends with a newline
            try:
                event = _parse_line(name, index + 1, raw)
                if event.seq <= previous:  # a writer never repeats or reorders: someone edited the file
                    raise LedgerCorrupt(f"{name}:{index + 1} has seq {event.seq} after {previous}")
                previous = event.seq
                events.append(event)
            except LedgerCorrupt:
                if index != last:
                    raise
                torn.append(name)  # no newline after it and not parseable: the writer was killed mid-line
    events.sort(key=lambda e: (e.ts, e.run_id, e.seq))
    return LedgerRead(events, torn)


def read_ledger_files(unit_dir: Path) -> dict[str, bytes]:
    """`<run-id>.jsonl` -> bytes of the run files in the working tree; a symlink or oversized file is skipped."""
    directory = ledger_dir(unit_dir)
    files: dict[str, bytes] = {}
    try:
        reject_symlinks(unit_dir, ".l4", "ledger")
    except UnsafeFile:
        return files
    if directory.is_dir():
        for path in sorted(directory.glob("*.jsonl")):
            try:
                files[path.name] = read_regular_file(path, limit=MAX_LEDGER_FILE_BYTES)
            except UnsafeFile:
                continue  # a symlink or oversized file is not a ledger this harness wrote
    return files


def read_ledger(unit_dir: Path) -> LedgerRead:
    return parse_ledger_files(read_ledger_files(unit_dir))
