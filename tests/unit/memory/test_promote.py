from collections.abc import Callable
from pathlib import Path

import pytest

from l4.config.schema import L4Config
from l4.context import AppContext
from l4.exitcodes import ExitCode, L4Exit
from l4.memory import promote as promote_module
from l4.memory.cli import run_lessons
from l4.memory.inject import inject_for_task
from l4.memory.lessons import Lesson, LessonsFile, lesson_id, parse_lessons, render_lessons
from l4.memory.promote import check_checkout, promote
from l4.redact import Redactor
from l4.vcs.git import Git

LESSONS = ".serena/memories/harness/lessons.md"
KEY = "kg-a-no-new-test-traces"
LID = lesson_id(KEY)
INBOX = ".serena/memories/inbox/kg-2026-10-14"


def draft(*, body: str = "Name the criterion in the test name.", globs: tuple[str, ...] = ("src/web/**",)) -> str:
    return render_lessons(LessonsFile([Lesson(LID, "Recurring red failure", KEY, body, globs, source="l4 kg propose")]))


class Repo:
    def __init__(self, path: Path, environ: dict[str, str], raw: Callable[..., str]) -> None:
        self.path, self.environ, self.raw = path, environ, raw
        self.app = AppContext(
            repo=path, config_path=None, log_format="human", verbosity=0, run_id="r-20261014T1000Z-0001",
            environ=environ, redactor=Redactor({}),
        )  # fmt: skip
        self.cfg = L4Config()

    def put_draft(self, text: str | None = None, lid: str = LID) -> Path:
        path = self.path / INBOX / f"{lid}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(draft() if text is None else text, encoding="utf-8")
        return path

    def commit_lessons(self, *lessons: Lesson) -> None:
        path = self.path / LESSONS
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_lessons(LessonsFile(list(lessons))), encoding="utf-8")
        self.raw(self.path, "add", LESSONS)
        self.raw(self.path, "commit", "-q", "-m", "lessons")

    def head(self) -> str:
        return self.raw(self.path, "rev-parse", "HEAD").strip()

    def status(self) -> str:
        return self.raw(self.path, "status", "--porcelain", "--untracked-files=all")

    def lessons_text(self) -> str:
        path = self.path / LESSONS
        return path.read_text(encoding="utf-8") if path.exists() else ""


@pytest.fixture
def repo(make_repo, git_environ, raw) -> Repo:
    path = make_repo()
    return Repo(path, git_environ, raw)


def refused(call, *, containing: str) -> None:
    with pytest.raises(L4Exit) as caught:
        call()
    assert caught.value.code == ExitCode.USAGE_ERROR
    assert containing in str(caught.value)


def nothing_written(repo: Repo, before_head: str, proposal: Path) -> None:
    assert repo.head() == before_head
    assert not (repo.path / LESSONS).exists() or "## " + LID not in repo.lessons_text()
    assert proposal.exists()


# 3.2: one test per refusal


def test_memory_disabled_is_refused(repo: Repo):
    proposal = repo.put_draft()
    before = repo.head()
    repo.cfg = L4Config.model_validate({"memory": {"enabled": False}})
    refused(lambda: promote(repo.app, repo.cfg, LID, yes=True), containing="memory.enabled is false")
    nothing_written(repo, before, proposal)


def test_a_detached_head_is_refused(repo: Repo):
    proposal = repo.put_draft()
    repo.raw(repo.path, "checkout", "-q", "--detach")
    before = repo.head()
    refused(lambda: promote(repo.app, repo.cfg, LID, yes=True), containing="detached")
    nothing_written(repo, before, proposal)


def test_a_unit_branch_is_refused_scn_kg_29(repo: Repo):
    proposal = repo.put_draft()
    repo.raw(repo.path, "checkout", "-q", "-b", "l4/openspec/a")
    before = repo.head()
    refused(lambda: promote(repo.app, repo.cfg, LID, yes=True), containing="protected-path blocker")
    refused(lambda: promote(repo.app, repo.cfg, LID, yes=True), containing="Promote on the base branch")
    nothing_written(repo, before, proposal)


def test_anything_staged_is_refused(repo: Repo):
    proposal = repo.put_draft()
    (repo.path / "other.txt").write_text("x")
    repo.raw(repo.path, "add", "other.txt")
    before = repo.head()
    refused(lambda: promote(repo.app, repo.cfg, LID, yes=True), containing="staged")
    nothing_written(repo, before, proposal)


def test_a_lessons_file_that_differs_from_head_is_refused(repo: Repo):
    repo.commit_lessons(Lesson(lesson_id("a"), "a", "a", "body"))
    proposal = repo.put_draft()
    (repo.path / LESSONS).write_text(repo.lessons_text() + "\nmy own edit\n")
    before, text = repo.head(), repo.lessons_text()
    refused(lambda: promote(repo.app, repo.cfg, LID, yes=True), containing="not committed")
    assert repo.head() == before and repo.lessons_text() == text and proposal.exists()


def test_an_untracked_lessons_file_is_refused(repo: Repo):
    proposal = repo.put_draft()
    (repo.path / LESSONS).parent.mkdir(parents=True, exist_ok=True)
    (repo.path / LESSONS).write_text(render_lessons(LessonsFile([Lesson(lesson_id("a"), "a", "a", "b")])))
    before = repo.head()
    refused(lambda: promote(repo.app, repo.cfg, LID, yes=True), containing="not committed")
    assert repo.head() == before and proposal.exists()


def test_a_lessons_file_with_parse_problems_is_refused(repo: Repo):
    path = repo.path / LESSONS
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_lessons(LessonsFile()) + "\n## broken\n")
    repo.raw(repo.path, "add", LESSONS)
    repo.raw(repo.path, "commit", "-q", "-m", "bad lessons")
    proposal = repo.put_draft()
    before, text = repo.head(), repo.lessons_text()
    refused(lambda: promote(repo.app, repo.cfg, LID, yes=True), containing="lint")
    assert repo.head() == before and repo.lessons_text() == text and proposal.exists()


def test_a_missing_git_identity_is_refused(repo: Repo, tmp_path: Path):
    proposal = repo.put_draft()
    empty = tmp_path / "empty.gitconfig"
    empty.write_text("[user]\n\tuseConfigOnly = true\n")
    environ = {**repo.environ, "GIT_CONFIG_GLOBAL": str(empty)}
    app = AppContext(
        repo=repo.path, config_path=None, log_format="human", verbosity=0, run_id="r-20261014T1000Z-0001",
        environ=environ, redactor=Redactor({}),
    )  # fmt: skip
    before = repo.head()
    refused(lambda: promote(app, repo.cfg, LID, yes=True), containing="identity")
    nothing_written(repo, before, proposal)
    with pytest.raises(L4Exit):
        check_checkout(app, repo.cfg, Git(repo.path, environ=environ))
    check_checkout(app, repo.cfg, Git(repo.path, environ=environ), commit=False)  # no commit: no identity needed


# 3.1 through promote: the TODO line (SCN-KG-28)


def test_an_unfinished_draft_is_refused_scn_kg_28(repo: Repo):
    proposal = repo.put_draft(draft(body="Say it.\nTODO(person): write what the implementer should do"))
    before = repo.head()
    refused(
        lambda: promote(repo.app, repo.cfg, LID, yes=True), containing="the proposal still has its TODO(person) line"
    )
    nothing_written(repo, before, proposal)


# 3.3: confirmation


def test_no_terminal_and_no_yes_is_refused(repo: Repo, monkeypatch: pytest.MonkeyPatch):
    proposal = repo.put_draft()
    monkeypatch.setattr(promote_module, "_is_terminal", lambda: False)
    before = repo.head()
    refused(lambda: promote(repo.app, repo.cfg, LID), containing="--yes")
    nothing_written(repo, before, proposal)


def test_a_terminal_asks_and_a_no_writes_nothing(repo: Repo, monkeypatch: pytest.MonkeyPatch):
    proposal = repo.put_draft()
    monkeypatch.setattr(promote_module, "_is_terminal", lambda: True)
    monkeypatch.setattr(promote_module.click, "confirm", lambda *a, **k: False)
    before = repo.head()
    refused(lambda: promote(repo.app, repo.cfg, LID), containing="not promoted")
    nothing_written(repo, before, proposal)


def test_a_terminal_yes_promotes(repo: Repo, monkeypatch: pytest.MonkeyPatch):
    repo.put_draft()
    monkeypatch.setattr(promote_module, "_is_terminal", lambda: True)
    monkeypatch.setattr(promote_module.click, "confirm", lambda *a, **k: True)
    assert promote(repo.app, repo.cfg, LID).commit is not None


def test_the_lesson_and_its_scope_are_printed_before_the_write(repo: Repo, capsys: pytest.CaptureFixture[str]):
    repo.put_draft()
    promote(repo.app, repo.cfg, LID, yes=True)
    out = capsys.readouterr().out
    assert f"## {LID} · Recurring red failure" in out and "Name the criterion in the test name." in out
    assert "scope: src/web/**" in out and out.index("scope:") < out.index("committed")


def test_an_unscoped_lesson_says_every_task(repo: Repo, capsys: pytest.CaptureFixture[str]):
    repo.put_draft(draft(globs=()))
    promote(repo.app, repo.cfg, LID, yes=True, commit=False)
    assert "scope: every task" in capsys.readouterr().out


# 3.3 + 3.4: write and commit (SCN-KG-27)


def test_a_promoted_lesson_reaches_the_next_matching_task_scn_kg_27(repo: Repo):
    proposal = repo.put_draft()
    evidence = proposal.with_name(f"{LID}.evidence.md")
    evidence.write_text("units: a, b\n")
    other = repo.put_draft(draft(), lid=LID).parent / "unrelated.txt"
    other.write_text("keep me\n")
    before = repo.head()
    done = promote(repo.app, repo.cfg, LID, yes=True)
    assert done.action == "created" and done.commit == repo.head() != before
    assert LID in {x.id for x in parse_lessons(repo.lessons_text()).file.lessons}
    changed = repo.raw(repo.path, "show", "--name-only", "--format=", "HEAD").split()
    assert changed == [LESSONS]
    message = repo.raw(repo.path, "log", "-1", "--format=%B").rstrip("\n")
    assert message == f"chore(memory): lesson {LID} promoted [skip ci]\n\nPromoted-from: {INBOX}/{LID}.md"
    assert "L4-" not in message and "Co-Authored" not in message
    assert not proposal.exists() and not evidence.exists() and other.exists()
    assert inject_for_task(repo.path, repo.cfg.memory, ["src/web/page.py"]).ids == (LID,)
    assert inject_for_task(repo.path, repo.cfg.memory, ["docs/x.md"]).ids == ()


def test_the_commit_has_the_persons_identity_and_no_trailer(repo: Repo):
    repo.put_draft()
    promote(repo.app, repo.cfg, LID, yes=True)
    author = repo.raw(repo.path, "log", "-1", "--format=%an|%ae").strip()
    assert author == "L4 Test|l4-test@example.invalid"
    assert repo.raw(repo.path, "log", "-1", "--format=%(trailers:key=L4-Phase)").strip() == ""


def test_an_empty_inbox_folder_goes_with_its_files(repo: Repo):
    proposal = repo.put_draft()
    promote(repo.app, repo.cfg, LID, yes=True)
    assert not proposal.parent.exists()
    assert repo.status() == ""


def test_an_existing_dedupe_key_is_reinforced(repo: Repo):
    repo.commit_lessons(Lesson(LID, "Old title", KEY, "old body"))
    repo.put_draft()
    done = promote(repo.app, repo.cfg, LID, yes=True)
    (lesson,) = parse_lessons(repo.lessons_text()).file.lessons
    assert done.action == "reinforced" and lesson.reinforced_count == 2 and lesson.title == "Old title"


def test_the_caps_hold_and_the_archived_ids_are_printed(repo: Repo, capsys: pytest.CaptureFixture[str]):
    repo.commit_lessons(Lesson(lesson_id("old"), "Old", "old", "body"))
    repo.cfg = L4Config.model_validate({"memory": {"max_lessons": 1}})
    repo.put_draft()
    done = promote(repo.app, repo.cfg, LID, yes=True)
    assert done.archived == (lesson_id("old"),)
    assert f"archived {lesson_id('old')}" in capsys.readouterr().out
    changed = set(repo.raw(repo.path, "show", "--name-only", "--format=", "HEAD").split())
    assert changed == {LESSONS, f".serena/memories/harness/_archive/{lesson_id('old')}.md"}


def test_no_commit_writes_keeps_the_proposal_and_prints_the_git_lines(repo: Repo, capsys: pytest.CaptureFixture[str]):
    proposal = repo.put_draft()
    before = repo.head()
    done = promote(repo.app, repo.cfg, LID, yes=True, commit=False)
    out = capsys.readouterr().out
    assert done.commit is None and repo.head() == before and proposal.exists()
    assert LID in repo.lessons_text()
    assert f"git add -- {LESSONS}" in out
    assert f'git commit -m "chore(memory): lesson {LID} promoted [skip ci]" -m "Promoted-from: {INBOX}/{LID}.md"' in out
    assert repo.raw(repo.path, "diff", "--cached", "--name-only") == ""


def test_other_inbox_folders_need_from(repo: Repo):
    repo.put_draft()
    second = repo.path / ".serena/memories/inbox/kg-2026-10-15"
    second.mkdir()
    (second / f"{LID}.md").write_text(draft())
    before = repo.head()
    refused(lambda: promote(repo.app, repo.cfg, LID, yes=True), containing="--from")
    assert repo.head() == before
    promote(repo.app, repo.cfg, LID, yes=True, from_dir="kg-2026-10-15")
    assert (repo.path / INBOX / f"{LID}.md").exists() and not (second / f"{LID}.md").exists()


def test_a_failed_commit_keeps_the_files_and_the_proposal(repo: Repo, monkeypatch: pytest.MonkeyPatch):
    proposal = repo.put_draft()
    real = Git.run

    def failing(self, *args, **kwargs):
        if args and args[0] == "commit":
            raise promote_module.GitError(["git", "commit"], 1, "boom")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Git, "run", failing)
    with pytest.raises(L4Exit) as caught:
        promote(repo.app, repo.cfg, LID, yes=True)
    assert caught.value.code == ExitCode.INTERNAL_ERROR and "git commit" in str(caught.value)
    assert proposal.exists() and LID in repo.lessons_text()


# 3.5: run_lessons


def test_run_lessons_promote_with_options(repo: Repo):
    repo.put_draft()
    code = run_lessons(repo.app, words=("promote", LID), from_dir="kg-2026-10-14", yes=True, no_commit=True)
    assert code == ExitCode.OK and LID in repo.lessons_text()


def test_run_lessons_promote_needs_one_id(repo: Repo):
    for words in (("promote",), ("promote", LID, "x"), ("list", "x"), ("nope",)):
        with pytest.raises(L4Exit) as caught:
            run_lessons(repo.app, words=words)
        assert caught.value.code == ExitCode.USAGE_ERROR
        assert "usage: l4 lessons list | l4 lessons lint" in str(caught.value)


def test_the_git_calls_are_read_only_plus_add_and_commit(repo: Repo, monkeypatch: pytest.MonkeyPatch):
    repo.put_draft()
    seen: list[list[str]] = []
    real = Git._argv

    def spy(self, args, config):
        seen.append(list(args))
        return real(self, args, config)

    monkeypatch.setattr(Git, "_argv", spy)
    promote(repo.app, repo.cfg, LID, yes=True)
    allowed = {"rev-parse", "diff", "ls-files", "var", "add", "commit"}
    assert {call[0] for call in seen} <= allowed
    assert {"add", "commit"} <= {call[0] for call in seen}
