import os
import stat
from pathlib import Path

import pytest

from l4.specs.base import MarkerWriteError
from l4.specs.markers import split_lines, write_marker

BOM = b"\xef\xbb\xbf"


def test_split_lines_keeps_offsets_with_bom_and_mixed_terminators():
    data = BOM + "- [ ] é one\r\n- [x] two\n- [ ] three\r- [ ] still three".encode()
    lines = split_lines(data)
    assert [line.number for line in lines] == [1, 2, 3]
    # offsets are bytes and include the BOM; the BOM stays in the text, as OpenSpec's \s matches it
    assert lines[0].start == 0 and lines[0].text.startswith("\ufeff- [ ]")
    assert lines[0].terminator == b"\r\n"
    assert lines[1].start == len(BOM) + len("- [ ] é one".encode()) + 2
    assert lines[1].terminator == b"\n"
    # OpenSpec splits on \n only: a lone \r is content, so line numbers cannot drift against the CLI
    assert lines[2].text == "- [ ] three\r- [ ] still three" and lines[2].terminator == b""
    assert b"".join(line.text.encode() + line.terminator for line in lines) == data
    # a multi-byte character before the bracket moves the byte offset, not the character index
    accented = split_lines("é- [ ] a".encode())[0]
    assert accented.offset_of(accented.text.index("[")) == len("é- ".encode())


def test_split_lines_has_no_phantom_line_after_the_last_terminator():
    assert [line.text for line in split_lines(b"a\nb\n")] == ["a", "b"]
    assert split_lines(b"") == []


def test_crlf_marker_flip_changes_exactly_one_byte(tmp_path: Path):
    path = tmp_path / "tasks.md"
    before = b"# Tasks\r\n\r\n- [ ]* 2.3 Add retry\r\n- [ ] 2.4 Next\r\n"
    path.write_bytes(before)
    path.chmod(0o640)
    offset = before.index(b"[ ]*") + 1
    result = write_marker(path, offset, b" ", b"x")
    after = path.read_bytes()
    assert len(after) == len(before)
    assert [i for i, (a, b) in enumerate(zip(before, after, strict=True)) if a != b] == [offset]
    assert after[offset : offset + 1] == b"x" and after.count(b"\r\n") == 4
    assert stat.S_IMODE(path.stat().st_mode) == 0o640
    assert result.offset == offset and result.size == len(before)
    assert [p.name for p in tmp_path.iterdir()] == ["tasks.md"]  # no temp file left behind


def test_write_marker_refuses_unsafe_requests_and_leaves_the_file_alone(tmp_path: Path):
    path = tmp_path / "tasks.md"
    path.write_bytes(b"- [ ] a\n")
    for offset, old, new in [(3, b"x", b"y"), (3, b" ", b"xx"), (3, b"  ", b"x"), (99, b" ", b"x"), (-1, b" ", b"x")]:
        with pytest.raises(MarkerWriteError):
            write_marker(path, offset, old, new)
    assert path.read_bytes() == b"- [ ] a\n"

    link = tmp_path / "link.md"
    link.symlink_to(path)
    with pytest.raises(MarkerWriteError, match="symlink"):
        write_marker(link, 3, b" ", b"x")
    assert path.read_bytes() == b"- [ ] a\n"
    with pytest.raises(MarkerWriteError):
        write_marker(tmp_path / "missing.md", 3, b" ", b"x")


def test_post_write_verification_detects_a_corrupted_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "tasks.md"
    path.write_bytes(b"- [ ] a\n")
    real_replace = os.replace

    def corrupting_replace(src, dst):
        real_replace(src, dst)
        Path(dst).write_bytes(b"- [x] a\nEXTRA\n")  # something else touched the file after the rename

    monkeypatch.setattr("l4.fsutil.os.replace", corrupting_replace)
    with pytest.raises(MarkerWriteError, match="verification"):
        write_marker(path, 3, b" ", b"x")


def test_write_marker_refuses_a_stale_offset_that_points_at_some_other_space(tmp_path: Path):
    path = tmp_path / "tasks.md"
    path.write_bytes(b"intro line\n- [ ] a\n")
    stale = b"intro line".index(b" ")  # a space, but not a checkbox interior
    with pytest.raises(MarkerWriteError, match="checkbox"):
        write_marker(path, stale, b" ", b"x")
    assert path.read_bytes() == b"intro line\n- [ ] a\n"
