from pathlib import Path

import pytest

from l4.cli import main
from l4.memory.lessons import Lesson, LessonsFile, lesson_id, render_lessons

LESSONS = ".serena/memories/harness/lessons.md"


def lesson(key: str, **kw) -> Lesson:
    return Lesson(id=lesson_id(key), title=kw.pop("title", key), dedupe_key=key, **kw)


def write(repo: Path, text: str) -> None:
    path = repo / LESSONS
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def run(repo: Path, *words: str) -> int:
    return main(["lessons", *words, "--repo", str(repo)], environ={})


def test_lessons_list_and_lint(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    good = lesson("ui-criterion-without-e2e-test", title="UI criteria need an end-to-end test", scope_globs=("web/**",))
    write(tmp_path, render_lessons(LessonsFile([good, lesson("other")])))
    assert run(tmp_path, "list") == 0
    out = capsys.readouterr().out
    assert "L-09421538  UI criteria need an end-to-end test  [web/**]  x1" in out
    assert run(tmp_path, "lint") == 0
    assert capsys.readouterr().out == ""

    write(tmp_path, render_lessons(LessonsFile([Lesson("L-deadbeef", "t", "some-key")])) + "\n## broken\n")
    assert run(tmp_path, "lint") == 3
    out = capsys.readouterr().out
    assert "heading is not" in out and "L-deadbeef: id does not match the dedupe key" in out
    assert run(tmp_path, "list") == 0  # list still works, and warns on stderr
    assert "warning: line" in capsys.readouterr().err


def test_missing_file_is_zero_lessons(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    assert run(tmp_path, "list") == 0 and run(tmp_path, "lint") == 0
    assert capsys.readouterr().out == ""


def test_unknown_subcommand_is_a_usage_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    assert run(tmp_path) == 2
    assert run(tmp_path, "promote") == 2
    assert "usage: l4 lessons list | l4 lessons lint" in capsys.readouterr().err
