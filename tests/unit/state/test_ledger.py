import json
import os
import signal
import subprocess
import sys
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from l4.redact import Redactor
from l4.state.ledger import (
    LedgerClosed,
    LedgerCorrupt,
    LedgerWriter,
    ledger_dir,
    ledger_path,
    parse_ledger_files,
    read_ledger,
)

RUN = "r-20261003T1312Z-7f3a"
T0 = datetime(2026, 10, 3, 13, 12, 0, 123456, tzinfo=UTC)


class Clock:
    def __init__(self, start: datetime = T0) -> None:
        self.now = start

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now


def open_writer(unit_dir: Path, run_id: str = RUN, clock=None, **started) -> LedgerWriter:
    return LedgerWriter.open(
        unit_dir, "openspec:add-login", run_id, redactor=Redactor({}), clock=clock or Clock(), **started
    )


def lines(unit_dir: Path, run_id: str = RUN) -> list[dict]:
    return [json.loads(line) for line in ledger_path(unit_dir, run_id).read_text(encoding="utf-8").splitlines()]


def test_paths_are_next_to_the_unit(tmp_path: Path):
    assert ledger_dir(tmp_path) == tmp_path / ".l4" / "ledger"
    assert ledger_path(tmp_path, RUN) == tmp_path / ".l4" / "ledger" / f"{RUN}.jsonl"
    with pytest.raises(ValueError):
        ledger_path(tmp_path, "../../etc/passwd")


def test_run_started_first_strict_seq_and_finish(tmp_path: Path):
    writer = open_writer(tmp_path, base_sha="a" * 40, iteration=1)
    first = writer.append("task.started", task="1.1")
    writer.append("task.done", task="1.1")
    writer.finish(0)
    events = lines(tmp_path)
    assert [e["type"] for e in events] == ["run.started", "task.started", "task.done", "run.finished"]
    assert [e["seq"] for e in events] == [1, 2, 3, 4]
    assert events[0]["base_sha"] == "a" * 40 and events[0]["harness_version"] and events[3]["exit_code"] == 0
    assert all(e["run_id"] == RUN and e["unit"] == "openspec:add-login" for e in events)
    assert events[0]["ts"] == "2026-10-03T13:12:01.123456Z"
    assert first.seq == 2 and first.data == {"task": "1.1"}
    with pytest.raises(LedgerClosed):
        writer.append("task.started", task="1.2")
    assert len(lines(tmp_path)) == 4  # nothing was appended


def test_append_after_finish_is_refused(tmp_path: Path):
    writer = open_writer(tmp_path)
    writer.finish(13)
    with pytest.raises(LedgerClosed):
        writer.finish(0)
    with pytest.raises(LedgerClosed):
        writer.append("x.y")


def test_timestamps_never_go_backwards_within_a_run(tmp_path: Path):
    times = iter([T0, T0 - timedelta(hours=1), T0 - timedelta(hours=2), T0 + timedelta(seconds=5)])
    writer = open_writer(tmp_path, clock=lambda: next(times))
    writer.append("a.b")
    writer.append("a.c")
    stamps = [e["ts"] for e in lines(tmp_path)]
    assert stamps == sorted(stamps)


def test_every_line_is_fsynced_and_strings_are_redacted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    synced = []
    real = os.fsync
    monkeypatch.setattr("l4.state.ledger.os.fsync", lambda fd: (synced.append(fd), real(fd))[1])
    secret = "glpat-" + "a1b2c3d4e5f6a7b8c9d0"
    writer = LedgerWriter.open(
        tmp_path, "openspec:x", RUN, redactor=Redactor({"T": "supersecretvalue1"}), clock=Clock()
    )
    base = len(synced)
    writer.append("agent.session", note=f"token {secret} and supersecretvalue1", nested={"k": [secret]})
    assert len(synced) == base + 1
    text = ledger_path(tmp_path, RUN).read_text(encoding="utf-8")
    assert secret not in text and "supersecretvalue1" not in text and "[REDACTED:" in text


def test_reserved_keys_bad_types_and_duplicate_runs_are_refused(tmp_path: Path):
    writer = open_writer(tmp_path)
    for bad in ("seq", "ts", "run_id", "unit", "type"):
        with pytest.raises(ValueError, match="reserved"):
            writer.append("task.done", **{bad: 1})
    for bad_type in ("", "Task Done", "../x", "a\nb"):
        with pytest.raises(ValueError, match="event type"):
            writer.append(bad_type)
    assert len(lines(tmp_path)) == 1
    with pytest.raises(FileExistsError):  # a run id is used once
        open_writer(tmp_path)


def test_concurrent_appends_keep_seq_strict(tmp_path: Path):
    writer = open_writer(tmp_path)

    def work() -> None:
        for _ in range(40):
            writer.append("step.finished", n=1)

    threads = [threading.Thread(target=work) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert [e["seq"] for e in lines(tmp_path)] == list(range(1, 162))


def test_killed_run_leaves_readable_ledger(tmp_path: Path):
    code = (
        "import sys, os, signal\n"
        "from pathlib import Path\n"
        "from l4.redact import Redactor\n"
        "from l4.state.ledger import LedgerWriter\n"
        f"w = LedgerWriter.open(Path({str(tmp_path)!r}), 'openspec:x', {RUN!r}, redactor=Redactor({{}}))\n"
        "w.append('task.started', task='1.1')\n"
        "os.kill(os.getpid(), signal.SIGKILL)\n"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert done.returncode == -signal.SIGKILL
    read = read_ledger(tmp_path)
    assert [e.type for e in read.events] == ["run.started", "task.started"] and read.torn == []


def test_reading_sorts_by_ts_run_seq_skips_a_torn_last_line_and_rejects_other_damage(tmp_path: Path):
    def event(run: str, seq: int, ts: str, type_: str = "task.done", **data) -> bytes:
        body = {"ts": ts, "run_id": run, "unit": "openspec:x", "seq": seq, "type": type_, **data}
        return (json.dumps(body) + "\n").encode()

    run_a, run_b = "r-20261003T1000Z-aaaa", "r-20261003T1100Z-bbbb"
    files = {
        f"{run_b}.jsonl": event(run_b, 1, "2026-10-03T11:00:00.000000Z", "run.started")
        + event(run_b, 2, "2026-10-03T11:00:01.000000Z")
        + b'{"ts": "2026-10-03T11:00:02.000000Z", "run_i',  # killed mid-write
        f"{run_a}.jsonl": event(run_a, 1, "2026-10-03T10:00:00.000000Z", "run.started")
        + event(run_a, 2, "2026-10-03T11:00:01.000000Z"),  # same instant as run b's seq 2: run_id breaks the tie
    }
    read = parse_ledger_files(files)
    assert [(e.run_id[-4:], e.seq) for e in read.events] == [("aaaa", 1), ("bbbb", 1), ("aaaa", 2), ("bbbb", 2)]
    assert read.torn == [f"{run_b}.jsonl"]

    complete_but_unterminated = {f"{run_a}.jsonl": event(run_a, 1, "2026-10-03T10:00:00.000000Z").rstrip(b"\n")}
    assert len(parse_ledger_files(complete_but_unterminated).events) == 1

    damaged = {f"{run_a}.jsonl": b"not json\n" + event(run_a, 2, "2026-10-03T10:00:00.000000Z")}
    with pytest.raises(LedgerCorrupt, match=r"\.jsonl:1"):
        parse_ledger_files(damaged)
    wrong_run = {f"{run_a}.jsonl": event(run_b, 1, "2026-10-03T10:00:00.000000Z")}
    with pytest.raises(LedgerCorrupt, match="run_id"):
        parse_ledger_files(wrong_run)
    missing = {f"{run_a}.jsonl": b'{"ts": "2026-10-03T10:00:00.000000Z", "run_id": "' + run_a.encode() + b'"}\n'}
    with pytest.raises(LedgerCorrupt):
        parse_ledger_files(missing)


def test_read_ledger_on_disk_ignores_symlinks_and_other_files(tmp_path: Path):
    assert read_ledger(tmp_path).events == []
    open_writer(tmp_path).finish(0)
    (ledger_dir(tmp_path) / "notes.txt").write_text("x")
    outside = tmp_path / "outside.jsonl"
    outside.write_text("garbage")
    (ledger_dir(tmp_path) / "r-20261003T1400Z-cccc.jsonl").symlink_to(outside)
    read = read_ledger(tmp_path)
    assert [e.type for e in read.events] == ["run.started", "run.finished"]


def test_a_payload_that_cannot_be_serialised_does_not_consume_a_seq(tmp_path: Path):
    writer = open_writer(tmp_path)
    with pytest.raises(TypeError):
        writer.append("task.started", task=Path("x"))
    writer.append("task.done", task="1.1")
    writer.finish(0)
    assert [e["seq"] for e in lines(tmp_path)] == [1, 2, 3]


def test_a_symlinked_dot_l4_is_refused_for_writing_and_reading(tmp_path: Path):
    unit_dir, outside = tmp_path / "unit", tmp_path / "outside"
    unit_dir.mkdir()
    outside.mkdir()
    (unit_dir / ".l4").symlink_to(outside)
    with pytest.raises(OSError, match="symlink"):
        LedgerWriter.open(unit_dir, "openspec:x", RUN, redactor=Redactor({}))
    assert list(outside.rglob("*")) == []
    (outside / "ledger").mkdir()
    (outside / "ledger" / f"{RUN}.jsonl").write_text("garbage\n")
    assert read_ledger(unit_dir).events == []  # not followed, so the garbage is not even looked at


def forged_line(seq: int) -> bytes:
    return json.dumps(
        {"ts": "2026-10-03T13:13:00.000000Z", "run_id": RUN, "unit": "openspec:add-login", "seq": seq,
         "type": "phase.changed", "to": "verified"}  # fmt: skip
    ).encode() + b"\n"


def test_a_repeated_or_decreasing_seq_in_a_run_file_is_corrupt(tmp_path: Path):
    writer = open_writer(tmp_path)
    writer.append("step.started")
    path = ledger_path(tmp_path, RUN)
    with path.open("ab") as handle:
        handle.write(forged_line(2))
    with pytest.raises(LedgerCorrupt, match="seq 2 after 2"):
        read_ledger(tmp_path)


def test_a_ledger_with_appended_lines_is_rewritten_from_the_writers_copy(tmp_path: Path):
    writer = open_writer(tmp_path)
    writer.append("step.started")
    path = ledger_path(tmp_path, RUN)
    good = path.read_bytes()
    assert writer.restore_if_tampered() is None
    with path.open("ab") as handle:
        handle.write(forged_line(3))
    assert writer.restore_if_tampered() is not None
    assert path.read_bytes() == good
    writer.append("step.finished")
    assert [e.seq for e in read_ledger(tmp_path).events] == [1, 2, 3]
    assert b"verified" not in path.read_bytes()


def test_a_ledger_replaced_by_a_new_inode_or_a_symlink_is_restored_and_still_appendable(tmp_path: Path):
    writer = open_writer(tmp_path)
    path = ledger_path(tmp_path, RUN)
    good = path.read_bytes()
    path.rename(tmp_path / "moved")
    path.write_bytes(forged_line(2))
    assert writer.restore_if_tampered() is not None and path.read_bytes() == good
    path.unlink()
    path.symlink_to(tmp_path / "elsewhere")
    assert writer.restore_if_tampered() is not None and not path.is_symlink() and path.read_bytes() == good
    writer.append("step.started")  # the new descriptor is the one in use
    assert [e.seq for e in read_ledger(tmp_path).events] == [1, 2]
    path.write_bytes(b"")  # truncated in place
    assert writer.restore_if_tampered() is not None
    writer.append("step.finished")
    assert [e.seq for e in read_ledger(tmp_path).events] == [1, 2, 3]


def test_run_started_names_the_harness_commit_that_ran(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import sys
    import types

    monkeypatch.setitem(sys.modules, "l4._commit", types.SimpleNamespace(COMMIT="c" * 40))
    open_writer(tmp_path, base_sha="a" * 40, iteration=1)
    assert lines(tmp_path)[0]["harness_commit"] == "c" * 40


def test_file_filter_applies_to_the_file_only(tmp_path):
    """P5: what is committed (the file, and the copy the tamper check restores from) goes through the filter; the JSONL
    mirror in `.l4-out/logs` and the observers keep the full text."""
    import json
    import logging

    from l4.redact import Redactor
    from l4.state.ledger import LedgerWriter, read_ledger

    seen: list[object] = []
    mirrored: list[dict] = []

    class Capture(logging.Handler):
        def emit(self, record):
            mirrored.append(getattr(record, "l4_event", {}))

    handler = Capture()
    logging.getLogger("l4.ledger").addHandler(handler)
    logging.getLogger("l4.ledger").setLevel(logging.INFO)
    try:
        writer = LedgerWriter.open(
            tmp_path, "openspec:x", "r-20261004T1200Z-abcd", redactor=Redactor({}), observers=[seen.append],
            file_filter=lambda text: text.replace("https://forge.corp.example", "<forge>"),
        )  # fmt: skip
        event = writer.append("pr.updated", url="https://forge.corp.example/g/p/-/merge_requests/7", number=7)
        writer.finish(0)
    finally:
        logging.getLogger("l4.ledger").removeHandler(handler)
    on_disk = (tmp_path / ".l4" / "ledger" / "r-20261004T1200Z-abcd.jsonl").read_text()
    assert "<forge>/g/p/-/merge_requests/7" in on_disk and "forge.corp.example" not in on_disk
    assert read_ledger(tmp_path).events[1].data["url"] == "<forge>/g/p/-/merge_requests/7"  # what a later fold sees
    assert event.data["url"] == "https://forge.corp.example/g/p/-/merge_requests/7"
    assert any(getattr(e, "data", {}).get("url", "").startswith("https://forge.corp.example") for e in seen)
    assert any(m.get("url") == "https://forge.corp.example/g/p/-/merge_requests/7" for m in mirrored)
    # the tamper check compares with what was written: a filtered file is intact, an edited one is restored
    writer2 = LedgerWriter.open(
        tmp_path, "openspec:x", "r-20261004T1300Z-abcd", redactor=Redactor({}),
        file_filter=lambda text: text.replace("secret-host", "<forge>"),
    )  # fmt: skip
    writer2.append("pr.updated", url="https://secret-host/a")
    assert writer2.restore_if_tampered() is None
    path = tmp_path / ".l4" / "ledger" / "r-20261004T1300Z-abcd.jsonl"
    path.write_text(path.read_text() + json.dumps({"seq": 99}) + "\n")
    assert writer2.restore_if_tampered() is not None and "secret-host" not in path.read_text()
