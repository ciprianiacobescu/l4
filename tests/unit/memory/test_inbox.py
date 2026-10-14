from pathlib import Path

import pytest

from l4.exitcodes import ExitCode, L4Exit
from l4.memory import inbox
from l4.memory.lessons import Lesson, LessonsFile, lesson_id, render_lessons

KEY = "kg-a-no-new-test-traces"
LID = lesson_id(KEY)


def draft(
    *, key: str = KEY, lid: str | None = None, body: str = "Name the criterion in the test.", scope="`src/web/**`"
):
    lesson = Lesson(lid or lesson_id(key), "Recurring red failure", key, body, (scope.strip("`"),) if scope else ())
    return render_lessons(LessonsFile([lesson]))


def put(repo: Path, folder: str, lid: str, text: str) -> Path:
    path = repo / ".serena" / "memories" / "inbox" / folder / f"{lid}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def refused(call, *, containing: str) -> None:
    with pytest.raises(L4Exit) as caught:
        call()
    assert caught.value.code == ExitCode.USAGE_ERROR
    assert containing in str(caught.value)


def test_find_proposal_returns_the_one_file(tmp_path: Path):
    path = put(tmp_path, "kg-2026-10-14", LID, draft())
    assert inbox.find_proposal(tmp_path, LID, None) == path


def test_no_proposal_is_exit_2(tmp_path: Path):
    refused(lambda: inbox.find_proposal(tmp_path, LID, None), containing=LID)


def test_bad_lesson_id_is_exit_2(tmp_path: Path):
    refused(lambda: inbox.find_proposal(tmp_path, "../x", None), containing="L-<8 hex>")


def test_two_folders_are_listed_unless_from_names_one(tmp_path: Path):
    first = put(tmp_path, "kg-2026-10-14", LID, draft())
    second = put(tmp_path, "kg-2026-10-15", LID, draft())
    with pytest.raises(L4Exit) as caught:
        inbox.find_proposal(tmp_path, LID, None)
    assert caught.value.code == ExitCode.USAGE_ERROR
    assert "kg-2026-10-14" in str(caught.value) and "kg-2026-10-15" in str(caught.value)
    assert inbox.find_proposal(tmp_path, LID, "kg-2026-10-15") == second
    assert inbox.find_proposal(tmp_path, LID, ".serena/memories/inbox/kg-2026-10-14") == first


def test_from_must_be_an_inbox_folder(tmp_path: Path):
    put(tmp_path, "kg-a", LID, draft())
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "elsewhere" / f"{LID}.md").write_text(draft())
    refused(lambda: inbox.find_proposal(tmp_path, LID, "elsewhere"), containing="inbox")
    refused(lambda: inbox.find_proposal(tmp_path, LID, "../inbox"), containing="inbox")


def test_a_symlinked_proposal_is_refused(tmp_path: Path):
    real = tmp_path / "real.md"
    real.write_text(draft())
    folder = tmp_path / ".serena" / "memories" / "inbox" / "kg-a"
    folder.mkdir(parents=True)
    (folder / f"{LID}.md").symlink_to(real)
    refused(lambda: inbox.find_proposal(tmp_path, LID, None), containing="symlink")


def test_parse_proposal_accepts_a_good_draft(tmp_path: Path):
    path = put(tmp_path, "kg-a", LID, draft())
    lesson = inbox.parse_proposal(path, LID)
    assert (
        lesson.id == LID and lesson.scope_globs == ("src/web/**",) and lesson.body == "Name the criterion in the test."
    )


def test_a_proposal_over_256_kib_is_refused(tmp_path: Path):
    path = put(tmp_path, "kg-a", LID, draft(body="x" * (256 * 1024)))
    refused(lambda: inbox.parse_proposal(path, LID), containing="larger")


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("no header\n", "no lessons header"),
        (draft().replace("v1", "v2"), "unsupported"),
        (draft() + "\n## L-00000000 · second\n- **Dedupe key:** other\n\nbody\n", "exactly one"),
        (draft().replace("## " + LID, "## nonsense"), "problem"),
    ],
)
def test_parse_proposal_refuses_what_is_not_one_v1_section(tmp_path: Path, text: str, message: str):
    path = put(tmp_path, "kg-a", LID, text)
    refused(lambda: inbox.parse_proposal(path, LID), containing=message)


def test_the_id_must_equal_lesson_id_of_the_dedupe_key(tmp_path: Path):
    wrong = "L-deadbeef"
    path = put(tmp_path, "kg-a", wrong, draft(lid=wrong))
    refused(lambda: inbox.parse_proposal(path, wrong), containing=f"expected {LID}")


def test_the_asked_id_must_be_the_one_in_the_file(tmp_path: Path):
    other = lesson_id("other-key")
    path = put(tmp_path, "kg-a", other, draft())
    refused(lambda: inbox.parse_proposal(path, other), containing=LID)


def test_an_invalid_glob_is_refused(tmp_path: Path):
    path = put(tmp_path, "kg-a", LID, draft(scope="../outside/**"))
    refused(lambda: inbox.parse_proposal(path, LID), containing="glob")


def test_the_todo_line_is_refused(tmp_path: Path):
    body = "Say it.\nTODO(person): write what the implementer should do instead, then run l4 lessons promote"
    path = put(tmp_path, "kg-a", LID, draft(body=body))
    refused(lambda: inbox.parse_proposal(path, LID), containing="the proposal still has its TODO(person) line")


def test_an_empty_body_is_refused(tmp_path: Path):
    path = put(tmp_path, "kg-a", LID, draft(body=""))
    refused(lambda: inbox.parse_proposal(path, LID), containing="body is empty")
