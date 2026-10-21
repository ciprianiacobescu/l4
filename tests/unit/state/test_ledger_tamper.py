"""`restore_if_tampered` says what it found, so a reviewer can tell an agent's harmless reset to HEAD from forged
lines (live job 5482 seq 66)."""

import os
from pathlib import Path

import pytest

from l4.state.ledger import ledger_path, read_ledger

from .test_ledger import RUN, forged_line, open_writer


def test_a_ledger_cut_back_to_its_committed_prefix_is_a_truncation_naming_the_lost_seqs(tmp_path: Path):
    writer = open_writer(tmp_path)
    for _ in range(57):
        writer.append("step.started")  # up to seq 58
    path = ledger_path(tmp_path, RUN)
    head_blob, inode = path.read_bytes(), os.stat(path).st_ino
    for _ in range(5):
        writer.append("gate.finished")  # seq 59-63
    path.write_bytes(head_blob)  # `git show HEAD:<ledger> > <ledger>`
    writer.append("wip.snapshot")  # 64
    writer.append("step.finished")  # 65
    tamper = writer.restore_if_tampered()
    assert tamper is not None
    assert (tamper.kind, tamper.removed_seqs, tamper.foreign_lines) == ("truncated", [59, 60, 61, 62, 63], 0)
    assert tamper.removed_count == 5
    assert [e.seq for e in read_ledger(tmp_path).events] == list(range(1, 66))
    assert os.stat(path).st_ino == inode
    assert writer.restore_if_tampered() is None


def test_appended_edited_and_replaced_ledgers_are_told_apart(tmp_path: Path):
    writer = open_writer(tmp_path)
    writer.append("step.started")
    path = ledger_path(tmp_path, RUN)
    good = path.read_bytes()
    with path.open("ab") as handle:
        handle.write(forged_line(3))
    appended = writer.restore_if_tampered()
    assert appended is not None
    assert (appended.kind, appended.removed_seqs, appended.foreign_lines) == ("appended", [], 1)
    path.write_bytes(good.replace(b"step.started", b"step.finished"))
    edited = writer.restore_if_tampered()
    assert edited is not None and edited.kind == "edited" and edited.removed_seqs == [2] and edited.foreign_lines == 1
    path.rename(tmp_path / "moved")
    path.write_bytes(forged_line(2))
    replaced = writer.restore_if_tampered()
    assert replaced is not None and replaced.kind == "replaced"
    assert path.read_bytes() == good


def test_a_ledger_grown_huge_is_described_from_its_start_and_never_read_whole(tmp_path: Path, monkeypatch):
    """The old check compared sizes before reading; describing the tamper must not read whatever an agent appended (a
    sparse 16 GiB file costs the agent nothing and would cost the harness the memory)."""
    from l4.state import ledger as ledger_module

    writer = open_writer(tmp_path)
    writer.append("step.started")
    path = ledger_path(tmp_path, RUN)
    good = path.read_bytes()
    with path.open("ab") as handle:
        handle.write(forged_line(3))
    os.truncate(path, 16 << 30)  # sparse
    largest: list[int] = []
    real_read = os.read

    def bounded(fd: int, n: int) -> bytes:
        largest.append(n)
        return real_read(fd, n)

    monkeypatch.setattr(Path, "read_bytes", lambda self: pytest.fail(f"read whole: {self}"))
    monkeypatch.setattr(ledger_module.os, "read", bounded)
    tamper = writer.restore_if_tampered()
    monkeypatch.undo()
    assert tamper is not None and tamper.kind == "appended" and tamper.removed_seqs == [] and tamper.foreign_lines >= 1
    assert max(largest) <= len(good) + ledger_module.MAX_TAMPER_READ
    assert path.read_bytes() == good and os.stat(path).st_size == len(good)
