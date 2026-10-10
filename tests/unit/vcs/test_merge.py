"""state-vcs-locks 1.27, 1.28, 4.6 and 4.4/4.5 at the git level: the base merged into a unit branch, history of the
branch never rewritten, harness-owned files resolved by the table, a source conflict aborted and named."""

import subprocess
from pathlib import Path

import pytest

from l4.exitcodes import ExitCode, L4Exit
from l4.redact import Redactor
from l4.specs.base import Framework
from l4.specs.harness_merge import harness_resolvers
from l4.specs.questions import NewQuestion, QuestionKind, QuestionsFile, QuestionStatus, raise_questions
from l4.specs.tasks_merge import merge_task_markers
from l4.vcs.merge import Escalate, MergeRefused, MergeResult, merge_base_into
from l4.vcs.trailers import CommitTrailers

BRANCH = "l4/x"
UNIT = "openspec/changes/x"
LEDGER = f"{UNIT}/.l4/ledger/r-1.jsonl"
EPOCH = 1_700_000_000
MSG = "chore(x): merge main@0123456789 into the unit branch [skip ci]"


@pytest.fixture
def merge_trailers() -> CommitTrailers:
    return CommitTrailers(unit="openspec:x", run_id="r-1", iteration=2, phase="verifying")


def commit_all(raw, repo: Path, message: str) -> str:
    raw(repo, "add", "-A")
    raw(repo, "commit", "-q", "-m", message)
    return raw(repo, "rev-parse", "HEAD").strip()


@pytest.fixture
def forked(make_repo, raw, git_for):
    """A unit branch `l4/x` with one commit of its own (pushed), and `main` one commit ahead of the fork (pushed).
    The checkout is on the unit branch."""
    repo = make_repo(remote=True)
    raw(repo, "checkout", "-q", "-b", BRANCH)
    (repo / "unit.txt").write_text("unit\n")
    commit_all(raw, repo, "unit work")
    raw(repo, "push", "-q", "origin", BRANCH)
    raw(repo, "checkout", "-q", "main")
    (repo / "main.txt").write_text("main\n")
    commit_all(raw, repo, "main moved")
    raw(repo, "push", "-q", "origin", "main")
    raw(repo, "checkout", "-q", BRANCH)
    base = raw(repo, "rev-parse", "main").strip()
    return repo, git_for(repo), base


def test_base_merged_pushed_history_untouched(forked, raw, merge_trailers):
    repo, git, base = forked
    old_head = git.rev_parse("HEAD")
    result = merge_base_into(git, base, message=MSG, trailers=merge_trailers, resolvers=())
    assert isinstance(result, MergeResult) and result.kind == "merged" and result.behind == 1
    assert result.sha == git.rev_parse("HEAD") and result.resolved == () and result.files == ()
    assert raw(repo, "rev-list", "--parents", "-n1", "HEAD").split() == [result.sha, old_head, base]
    assert raw(repo, "merge-base", "--is-ancestor", old_head, "HEAD") == ""  # every pushed commit is an ancestor
    assert (repo / "main.txt").exists() and (repo / "unit.txt").exists()
    assert raw(repo, "log", "-1", "--format=%s").strip() == MSG
    trailer_text = raw(repo, "log", "-1", "--format=%(trailers:key=L4-Phase,valueonly)").strip()
    assert trailer_text == "verifying"
    body = raw(repo, "log", "-1", "--format=%B")
    assert "L4-Unit: openspec:x" in body and "L4-Task" not in body and "L4-TDD" not in body and "L4-Step" not in body
    assert result.changed == ("main.txt",)
    assert raw(repo, "log", "-1", "--format=%an").strip() == "l4-bot"
    git.push("origin", [f"HEAD:refs/heads/{BRANCH}"])  # a fast-forward of the pushed branch
    assert raw(repo, "ls-remote", "origin", f"refs/heads/{BRANCH}").split()[0] == result.sha


def test_update_never_rewrites_pushed_history(forked, raw, merge_trailers):
    repo, git, base = forked
    merge_base_into(git, base, message=MSG, trailers=merge_trailers, resolvers=())
    git.push("origin", [f"HEAD:refs/heads/{BRANCH}"])
    flat = [part for argv in git.history for part in argv]
    assert "rebase" not in flat and "--amend" not in flat and "--force" not in flat and "-f" not in flat
    assert not any(part.startswith("+") for part in flat)
    assert not any("reset" in argv and "--hard" in argv for argv in git.history)
    assert raw(repo, "ls-remote", "origin", f"refs/heads/{BRANCH}").split()[0] == git.rev_parse("HEAD")


def test_branch_containing_base_is_a_noop(forked, raw, merge_trailers):
    repo, git, base = forked
    merge_base_into(git, base, message=MSG, trailers=merge_trailers, resolvers=())
    head = git.rev_parse("HEAD")
    git.history.clear()
    again = merge_base_into(git, base, message=MSG, trailers=merge_trailers, resolvers=())
    assert again.kind == "noop" and again.sha is None and again.behind == 0
    assert git.rev_parse("HEAD") == head
    assert not any("merge" in argv for argv in git.history)  # `merge-base` is a different word
    assert not any(argv[0:1] == ["commit"] or "commit" in argv for argv in git.history)


def test_dirty_worktree_refused_before_merge(forked, merge_trailers):
    repo, git, base = forked
    (repo / "stray.txt").write_text("x")
    git.history.clear()
    with pytest.raises(L4Exit) as exc:
        merge_base_into(git, base, message=MSG, trailers=merge_trailers, resolvers=())
    assert isinstance(exc.value, MergeRefused) and exc.value.code is ExitCode.INTERNAL_ERROR
    assert "uncommitted" in str(exc.value)
    assert not any("--no-commit" in argv for argv in git.history)


def test_conflict_abort_keeps_unstaged_ledger_lines(make_repo, raw, git_for, merge_trailers):
    repo = make_repo(remote=True)
    (repo / "cart.py").write_text("a\nb\nc\n")
    (repo / LEDGER).parent.mkdir(parents=True)
    (repo / LEDGER).write_text('{"seq":1}\n')
    commit_all(raw, repo, "base files")
    raw(repo, "push", "-q", "origin", "main")
    raw(repo, "checkout", "-q", "-b", BRANCH)
    (repo / "cart.py").write_text("a\nunit\nc\n")
    commit_all(raw, repo, "unit edit")
    raw(repo, "checkout", "-q", "main")
    (repo / "cart.py").write_text("a\nmain\nc\n")
    commit_all(raw, repo, "main edit")
    base = raw(repo, "rev-parse", "HEAD").strip()
    raw(repo, "checkout", "-q", BRANCH)
    head = raw(repo, "rev-parse", "HEAD").strip()
    with (repo / LEDGER).open("a") as handle:  # the run's open ledger: tracked, modified, unstaged
        handle.write('{"seq":2}\n')
    git = git_for(repo)
    result = merge_base_into(git, base, message=MSG, trailers=merge_trailers, resolvers=(), keep_dirty=(LEDGER,))
    assert result.kind == "conflict" and result.files == ("cart.py",) and result.sha is None
    assert (repo / LEDGER).read_text() == '{"seq":1}\n{"seq":2}\n'
    assert (repo / "cart.py").read_text() == "a\nunit\nc\n"
    assert git.rev_parse("HEAD") == head
    assert git.run("rev-parse", "-q", "--verify", "MERGE_HEAD", check=False).returncode != 0  # merge is aborted
    assert raw(repo, "status", "--porcelain").split() == ["M", LEDGER]


def test_source_conflict_aborts_and_names_files(make_repo, raw, git_for, merge_trailers):
    repo = make_repo(remote=True)
    (repo / "cart.py").write_text("a\nb\nc\n")
    (repo / "other.py").write_text("1\n2\n3\n")
    commit_all(raw, repo, "files")
    raw(repo, "checkout", "-q", "-b", BRANCH)
    (repo / "cart.py").write_text("a\nunit\nc\n")
    (repo / "other.py").write_text("1\nunit\n3\n")
    commit_all(raw, repo, "unit")
    raw(repo, "checkout", "-q", "main")
    (repo / "cart.py").write_text("a\nmain\nc\n")
    (repo / "other.py").write_text("1\nmain\n3\n")
    commit_all(raw, repo, "main")
    base = raw(repo, "rev-parse", "HEAD").strip()
    raw(repo, "checkout", "-q", BRANCH)
    git = git_for(repo)
    result = merge_base_into(git, base, message=MSG, trailers=merge_trailers, resolvers=())
    assert result.kind == "conflict" and result.files == ("cart.py", "other.py") and result.behind == 1
    assert git.run("status", "--porcelain").stdout == ""  # nothing half merged is left
    assert not any(argv[1] == "push" for argv in git.history)


def test_ledger_path_conflict_is_refused(make_repo, raw, git_for, merge_trailers):
    repo = make_repo(remote=True)
    (repo / LEDGER).parent.mkdir(parents=True)
    (repo / LEDGER).write_text("{}\n")
    commit_all(raw, repo, "ledger")
    raw(repo, "checkout", "-q", "-b", BRANCH)
    (repo / LEDGER).write_text("unit\n")
    commit_all(raw, repo, "unit")
    raw(repo, "checkout", "-q", "main")
    (repo / LEDGER).write_text("main\n")
    commit_all(raw, repo, "main")
    base = raw(repo, "rev-parse", "HEAD").strip()
    raw(repo, "checkout", "-q", BRANCH)
    git = git_for(repo)
    with pytest.raises(MergeRefused, match="ledger"):
        merge_base_into(git, base, message=MSG, trailers=merge_trailers, resolvers=())
    assert git.run("rev-parse", "-q", "--verify", "MERGE_HEAD", check=False).returncode != 0


def test_archived_commit_on_branch_refuses_merge(forked, raw, merge_trailers):
    repo, git, base = forked
    (repo / "archived.txt").write_text("a\n")
    raw(repo, "add", "-A")
    raw(repo, "commit", "-q", "-m", "archive\n\nL4-Phase: archived")
    git.history.clear()
    with pytest.raises(MergeRefused, match="archive"):
        merge_base_into(git, base, message=MSG, trailers=merge_trailers, resolvers=())
    assert not any("--no-commit" in argv for argv in git.history)


# --- harness-owned files: the resolver table of the base merge ------------------------------------------------------


def commit_at(repo: Path, git_environ, message: str, when: int) -> None:
    stamp = f"{EPOCH + when} +0000"  # git wants at least nine digits
    env = {**git_environ, "GIT_COMMITTER_DATE": stamp, "GIT_AUTHOR_DATE": stamp}
    base = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    subprocess.run([*base, "add", "-A"], cwd=repo, env=env, check=True, capture_output=True)
    subprocess.run([*base, "commit", "-q", "-m", message], cwd=repo, env=env, check=True, capture_output=True)


def fork_over(repo: Path, raw, git_environ, path: str, base: bytes | None, ours: bytes, theirs: bytes, times):
    """`path` as `base` on main, then `ours` on the unit branch (at times[0]) and `theirs` on main (at times[1])."""
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    if base is not None:
        target.write_bytes(base)
        commit_all(raw, repo, "base")
    raw(repo, "checkout", "-q", "-b", BRANCH)
    target.write_bytes(ours)
    commit_at(repo, git_environ, "unit side", times[0])
    raw(repo, "checkout", "-q", "main")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(theirs)
    commit_at(repo, git_environ, "main side", times[1])
    sha = raw(repo, "rev-parse", "HEAD").strip()
    raw(repo, "checkout", "-q", BRANCH)
    return sha


def questions_for(tmp: Path, *answers: str) -> list[bytes]:
    unit = tmp / "q"
    unit.mkdir(exist_ok=True)
    raise_questions(
        unit, "x", [NewQuestion("Should clear() forget the code?", QuestionKind.PRODUCT, ("1.1",), "ctx", "asked")],
        redactor=Redactor({}),
    )  # fmt: skip
    opened = (unit / "questions.md").read_bytes()
    out = [opened]
    for text in answers:
        file = QuestionsFile.parse(opened).set_status("Q-001", QuestionStatus.ANSWERED)
        body = file.get("Q-001").answer.body  # type: ignore[union-attr]
        out.append(file.data[: body.end] + text.encode() + b"\n" + file.data[body.end :])
    return out


@pytest.mark.parametrize(
    ("times", "winner"), [((2000, 1000), "branch"), ((1000, 2000), "main"), ((1500, 1500), "branch")]
)
def test_questions_merged_per_id_newer_human_answer(
    make_repo, raw, git_for, git_environ, merge_trailers, tmp_path, times, winner
):
    repo = make_repo(remote=True)
    opened, branch, main = questions_for(tmp_path, "yes: branch", "yes: main")
    path = f"{UNIT}/questions.md"
    base = fork_over(repo, raw, git_environ, path, opened, branch, main, times)
    git = git_for(repo)
    result = merge_base_into(
        git, base, message=MSG, trailers=merge_trailers, resolvers=harness_resolvers(UNIT, Framework.OPENSPEC)
    )
    assert result.kind == "merged" and result.resolved == (path,) and result.files == ()
    assert (repo / path).read_bytes() == (branch if winner == "branch" else main)
    assert raw(repo, "rev-list", "--parents", "-n1", "HEAD").split()[1:] == [
        raw(repo, "rev-parse", "HEAD^1").strip(),
        base,
    ]


def test_questions_time_is_per_answer_not_per_file(make_repo, raw, git_for, git_environ, merge_trailers, tmp_path):
    """SPEC L4-WTR-001 "keeping the newer human answer text": a later harness commit on the branch that raises Q-002
    must not make the branch's older Q-001 answer look newer than main's."""
    repo = make_repo(remote=True)
    opened, branch, main = questions_for(tmp_path, "yes: branch", "no: main")
    path = f"{UNIT}/questions.md"
    base = fork_over(repo, raw, git_environ, path, opened, branch, main, (1000, 2000))
    unit = tmp_path / "q"
    (unit / "questions.md").write_bytes(branch)
    raise_questions(
        unit, "x", [NewQuestion("Which rounding?", QuestionKind.PRODUCT, ("1.1",), "ctx", "asked")],
        redactor=Redactor({}),
    )  # fmt: skip
    (repo / path).write_bytes((unit / "questions.md").read_bytes())
    commit_at(repo, git_environ, "harness raises Q-002", 3000)
    result = merge_base_into(
        git_for(repo), base, message=MSG, trailers=merge_trailers, resolvers=harness_resolvers(UNIT, Framework.OPENSPEC)
    )
    merged = QuestionsFile.parse((repo / path).read_bytes())
    assert result.kind == "merged" and result.resolved == (path,)
    assert merged.get("Q-001").answer_text == "no: main"  # type: ignore[union-attr]
    assert merged.get("Q-002") is not None


def test_add_add_questions_file_is_resolved_without_a_base(
    make_repo, raw, git_for, git_environ, merge_trailers, tmp_path
):
    repo = make_repo(remote=True)
    _, branch, main = questions_for(tmp_path, "yes: branch", "yes: main")
    path = f"{UNIT}/questions.md"
    base = fork_over(repo, raw, git_environ, path, None, branch, main, (2000, 1000))
    result = merge_base_into(
        git_for(repo), base, message=MSG, trailers=merge_trailers, resolvers=harness_resolvers(UNIT, Framework.OPENSPEC)
    )
    assert result.kind == "merged" and result.resolved == (path,)
    assert (repo / path).read_bytes() == branch


def test_a_source_conflict_next_to_a_resolvable_one_aborts_everything(
    make_repo, raw, git_for, git_environ, merge_trailers, tmp_path
):
    repo = make_repo(remote=True)
    _, branch, main = questions_for(tmp_path, "yes: branch", "yes: main")
    (repo / "cart.py").write_text("a\nb\nc\n")
    base = fork_over(repo, raw, git_environ, f"{UNIT}/questions.md", None, branch, main, (2000, 1000))
    raw(repo, "checkout", "-q", "main")
    (repo / "cart.py").write_text("a\nmain\nc\n")
    commit_all(raw, repo, "main cart")
    raw(repo, "checkout", "-q", BRANCH)
    (repo / "cart.py").write_text("a\nunit\nc\n")
    commit_all(raw, repo, "unit cart")
    head = git_for(repo).rev_parse("HEAD")
    sha = raw(repo, "rev-parse", "main").strip()
    git = git_for(repo)
    result = merge_base_into(
        git, sha, message=MSG, trailers=merge_trailers, resolvers=harness_resolvers(UNIT, Framework.OPENSPEC)
    )
    assert result.kind == "conflict" and result.files == ("cart.py",) and result.resolved == (f"{UNIT}/questions.md",)
    assert git.rev_parse("HEAD") == head and git.run("status", "--porcelain").stdout == ""
    assert base != sha


TASKS_BASE = b"# Tasks\n\n- [ ] 1.1 Add item_count\n- [ ] 1.2 Document it\n"


def test_tasks_md_union_of_done_markers(make_repo, raw, git_for, git_environ, merge_trailers):
    repo = make_repo(remote=True)
    path = f"{UNIT}/tasks.md"
    ours = TASKS_BASE.replace(b"[ ] 1.1", b"[x] 1.1")
    theirs = TASKS_BASE.replace(b"[ ] 1.2", b"[x] 1.2")
    base = fork_over(repo, raw, git_environ, path, TASKS_BASE, ours, theirs, (2000, 1000))
    result = merge_base_into(
        git_for(repo), base, message=MSG, trailers=merge_trailers, resolvers=harness_resolvers(UNIT, Framework.OPENSPEC)
    )
    assert result.kind == "merged" and result.resolved == (path,)
    assert (repo / path).read_bytes() == TASKS_BASE.replace(b"[ ] 1.1", b"[x] 1.1").replace(b"[ ] 1.2", b"[x] 1.2")
    assert merge_task_markers(b"- [~] 1.1 a\r\n", b"- [x] 1.1 a\r\n", Framework.KIRO) == b"- [x] 1.1 a\r\n"
    assert merge_task_markers(b"- [-] 1.1 a\n", b"- [ ] 1.1 a\n", Framework.KIRO) == b"- [-] 1.1 a\n"


def test_differing_task_text_escalates(make_repo, raw, git_for, git_environ, merge_trailers):
    repo = make_repo(remote=True)
    path = f"{UNIT}/tasks.md"
    ours = TASKS_BASE.replace(b"[ ] 1.1", b"[x] 1.1")
    theirs = TASKS_BASE.replace(b"Document it", b"Document it well")
    base = fork_over(repo, raw, git_environ, path, TASKS_BASE, ours, theirs, (2000, 1000))
    git = git_for(repo)
    result = merge_base_into(
        git, base, message=MSG, trailers=merge_trailers, resolvers=harness_resolvers(UNIT, Framework.OPENSPEC)
    )
    assert result.kind == "conflict" and result.files == (path,) and result.resolved == ()
    with pytest.raises(Escalate):
        merge_task_markers(b"- [ ] 1.1 a\n", b"- [ ] 1.1 b\n", Framework.OPENSPEC)
    with pytest.raises(Escalate):
        merge_task_markers(b"- [ ] 1.1 a\n", b"- [ ] 1.1 a\n- [ ] 1.2 c\n", Framework.OPENSPEC)


def test_merge_runs_with_the_bot_identity_when_git_has_none(forked, raw, merge_trailers):
    """Live M1.7 step 3 (job 5504): on the runner `git merge --no-commit` stopped with "Committer identity unknown",
    since the runner user has no identity and git could not guess one. `user.useConfigOnly` stands for that here."""
    repo, git, base = forked
    raw(repo, "config", "user.useConfigOnly", "true")
    old_head = git.rev_parse("HEAD")
    result = merge_base_into(git, base, message=MSG, trailers=merge_trailers, resolvers=())
    assert result.kind == "merged"
    assert raw(repo, "rev-list", "--parents", "-n1", "HEAD").split() == [result.sha, old_head, base]
    assert raw(repo, "log", "-1", "--format=%an <%ae>|%cn <%ce>").strip() == (
        "l4-bot <l4-bot@users.noreply.invalid>|l4-bot <l4-bot@users.noreply.invalid>"
    )
