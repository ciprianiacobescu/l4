"""L4-RACE-001: a refused lease of the unit branch is classified with `git ls-remote` (gone, moved forward, rewritten);
a branch that a person moved forward by answers only is merged and pushed again, up to three tries; anything else is
never merged (SCN-LCK-08, SCN-IMP-22, SCN-RACE-03..06). Real git: a bare remote, the run's clone and a person's."""

import logging
from collections.abc import Callable
from pathlib import Path

import pytest

from l4.redact import Redactor
from l4.specs.base import Framework
from l4.specs.harness_merge import harness_resolvers
from l4.specs.questions import NewQuestion, QuestionKind, QuestionsFile, QuestionStatus, raise_questions
from l4.vcs.git import BOT_IDENTITY, Git
from l4.vcs.push import BranchGone, BranchKeepsMoving, BranchMoved, BranchRewritten, PushRejected
from l4.vcs.race import AnswerMerge, is_answer_file
from l4.vcs.trailers import CommitTrailers

BRANCH = "l4/openspec/x"
REF = f"refs/heads/{BRANCH}"
UNIT = "openspec/changes/x"
FIX = "openspec/changes/x-fix-1"
QUESTIONS = f"{UNIT}/questions.md"
FIX_QUESTIONS = f"{FIX}/questions.md"
LEDGER = f"{UNIT}/.l4/ledger/r-1.jsonl"
ASKED = "2026-10-05T10:00:00Z by implementer `codex`, run r-1, task 1.1"


@pytest.fixture(autouse=True)
def _warnings_reach_caplog(monkeypatch):
    monkeypatch.setattr(logging.getLogger("l4"), "propagate", True)


def opened(folder: Path, *titles: str) -> bytes:
    folder.mkdir(parents=True, exist_ok=True)
    raise_questions(
        folder, "x", [NewQuestion(t, QuestionKind.PRODUCT, ("1.1",), "ctx", ASKED) for t in titles],
        redactor=Redactor({}),
    )  # fmt: skip
    return (folder / "questions.md").read_bytes()


def answered(data: bytes, qid: str, text: str) -> bytes:
    file = QuestionsFile.parse(data).set_status(qid, QuestionStatus.ANSWERED)
    body = file.get(qid).answer.body  # type: ignore[union-attr]
    return QuestionsFile.parse(file.data[: body.end] + text.encode() + b"\n" + file.data[body.end :]).data


class World:
    """The run's clone on the unit branch, pushed once (`A`), and a person's clone of it."""

    def __init__(self, repo: Path, human: Path, git: Git, sleeps: list[float], raw: Callable[..., str]) -> None:
        self.repo, self.human, self.git, self.sleeps, self.raw = repo, human, git, sleeps, raw
        self.merged: list[tuple[str, int, tuple[str, ...]]] = []
        self.rescans = 0
        self.on_rescan: Callable[[], None] | None = None

    def person(self, files: dict[str, bytes | str], message: str = "answers") -> str:
        """A commit of the person's clone, pushed to the unit branch."""
        for rel, data in files.items():
            target = self.human / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data if isinstance(data, bytes) else data.encode())
        self.raw(self.human, "add", "-A")
        self.raw(self.human, "-c", "user.name=h", "-c", "user.email=h@x", "commit", "-q", "-m", message)
        self.raw(self.human, "push", "-q", "origin", BRANCH)
        return self.raw(self.human, "rev-parse", "HEAD").strip()

    def run_commit(self, files: dict[str, bytes | str], trailers: CommitTrailers) -> str:
        for rel, data in files.items():
            target = self.repo / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data if isinstance(data, bytes) else data.encode())
        self.git.run("add", "-A")
        return self.git.commit("run work", trailers, BOT_IDENTITY)

    def remote(self) -> str:
        out = self.raw(self.repo, "ls-remote", "origin", REF).split()
        return out[0] if out else ""

    def head(self) -> str:
        return self.raw(self.repo, "rev-parse", "HEAD").strip()

    def answers(self, trailers: CommitTrailers, **extra) -> AnswerMerge:
        def rescan() -> None:
            self.rescans += 1
            if self.on_rescan is not None:
                self.on_rescan()

        return AnswerMerge(
            UNIT, trailers, harness_resolvers(UNIT, Framework.OPENSPEC), rescan,
            lambda sha, n, paths: self.merged.append((sha, n, paths)), **extra,
        )  # fmt: skip


@pytest.fixture
def world(make_repo, git_environ, raw, trailers, tmp_path) -> World:
    repo = make_repo(remote=True)
    sleeps: list[float] = []
    git = Git(repo, environ=git_environ, sleep=sleeps.append)
    git.run("checkout", "-q", "-b", BRANCH)
    first = opened(repo / UNIT, "Should clear() forget the code?", "Which file?")
    (repo / FIX).mkdir(parents=True)
    opened(repo / FIX, "Fix question?")
    (repo / "src").mkdir()
    (repo / "src" / "app.py").write_text("print('app')\n")
    git.run("add", "-A")
    git.commit("one", trailers, BOT_IDENTITY)
    git.push_branch("origin", BRANCH)
    human = tmp_path / "human"
    raw(tmp_path, "clone", "-q", "--branch", BRANCH, raw(repo, "remote", "get-url", "origin").strip(), str(human))
    w = World(repo, human, git, sleeps, raw)
    w.first = first  # type: ignore[attr-defined]
    return w


def test_a_branch_a_person_deleted_is_gone(world, raw):
    raw(world.repo, "push", "-q", "origin", "--delete", BRANCH)
    world.run_commit({"b.txt": "b"}, CommitTrailers("openspec:x", "r-1", 1, "implementing"))
    with pytest.raises(BranchGone) as caught:
        world.git.push_branch("origin", BRANCH)
    assert isinstance(caught.value, PushRejected) and "stale info" in caught.value.stderr
    assert world.remote() == ""  # never created again


def test_a_branch_that_moved_forward_is_told_with_its_new_head_files_and_commits(world, trailers):
    world.person({"src/app.py": "print('v2')\n"}, "one")
    human = world.person({"notes.md": "n\n", QUESTIONS: world.first}, "two")  # type: ignore[attr-defined]
    world.run_commit({"b.txt": "b"}, trailers)
    with pytest.raises(BranchMoved) as caught:
        world.git.push_branch("origin", BRANCH)
    moved = caught.value
    assert moved.remote_head == human and moved.commits == 2 and moved.paths == ("notes.md", "src/app.py")
    assert world.remote() == human
    assert world.raw(world.repo, "for-each-ref", "refs/l4/tmp").strip() == ""  # the private ref is removed again


def test_a_rewritten_branch_is_told_and_not_merged(world, raw, trailers):
    raw(world.human, "reset", "-q", "--hard", "origin/main")  # a history that lacks the run's push
    (world.human / "other.txt").write_text("o")
    raw(world.human, "add", "-A")
    raw(world.human, "-c", "user.name=h", "-c", "user.email=h@x", "commit", "-q", "-m", "rewritten")
    raw(world.human, "push", "-q", "--force", "origin", f"HEAD:{REF}")
    forced = raw(world.human, "rev-parse", "HEAD").strip()
    world.run_commit({"b.txt": "b"}, trailers)
    before = world.head()
    for answers in (None, world.answers(trailers)):  # SCN-RACE-04: also when the caller would merge answers
        with pytest.raises(BranchRewritten) as caught:
            world.git.push_branch("origin", BRANCH, answers=answers)
        assert caught.value.remote_head == forced and caught.value.expected
    assert world.remote() == forced and world.head() == before and world.sleeps == []


def test_a_new_branch_where_none_was_expected_is_a_rewritten_one(world, raw, trailers):
    fresh = Git(world.repo, environ=world.git.env, sleep=world.sleeps.append)  # has seen nothing of the branch
    raw(world.repo, "update-ref", "-d", f"refs/remotes/origin/{BRANCH}")
    world.run_commit({"b.txt": "b"}, trailers)
    with pytest.raises(BranchRewritten) as caught:
        fresh.push_branch("origin", BRANCH)
    assert caught.value.expected == "" and caught.value.remote_head == world.remote()


def test_a_lease_the_remote_still_holds_is_not_classified(world, monkeypatch, trailers):
    """The remote head is the lease value: the refusal was another one and stays what git said."""
    world.run_commit({"b.txt": "b"}, trailers)

    def refuse(args, config, moved):
        raise PushRejected(["git", "push"], 1, " ! [rejected] HEAD -> x (stale info)\n")

    monkeypatch.setattr(world.git, "_push", refuse)
    with pytest.raises(PushRejected) as caught:
        world.git.push_branch("origin", BRANCH)
    assert type(caught.value) is PushRejected


def test_answers_that_arrive_during_a_run_are_merged_and_pushed(world, raw, trailers):
    """SCN-IMP-22."""
    mine = world.run_commit({"b.txt": "b\n"}, trailers)
    theirs = world.person({QUESTIONS: answered(world.first, "Q-001", "yes: keep it")})  # type: ignore[attr-defined]
    merge_trailers = CommitTrailers("openspec:x", "r-1", 2, "implementing")
    done = world.git.push_branch("origin", BRANCH, answers=world.answers(merge_trailers))
    assert done.returncode == 0
    head = world.head()
    assert world.remote() == head
    parents = raw(world.repo, "rev-list", "--parents", "-n1", "HEAD").split()
    assert parents == [head, mine, theirs]  # a harness merge: the run's head first, the person's second
    assert raw(world.repo, "log", "-1", "--format=%an %s").strip() == (
        "l4-bot chore(x): merge 1 answer commit from the forge [skip ci]"
    )
    body = raw(world.repo, "log", "-1", "--format=%B")
    assert "L4-Unit: openspec:x" in body and "L4-Phase: implementing" in body and "L4-Task" not in body
    assert "yes: keep it" in (world.repo / QUESTIONS).read_text()  # the next step reads it from the worktree
    assert world.merged == [(theirs, 1, (QUESTIONS,))] and world.rescans == 1 and world.sleeps == [5.0]
    assert world.git.rev_parse(f"refs/remotes/origin/{BRANCH}") == head  # the next lease
    assert world.raw(world.repo, "for-each-ref", "refs/l4/tmp").strip() == ""
    pushes = [argv for argv in world.git.history if "push" in argv]
    flat = [part for argv in pushes for part in argv]
    assert "--force" not in flat and not any(part.startswith("+") for part in flat)
    assert pushes[-1][pushes[-1].index("--") - 1] == f"--force-with-lease={REF}:{theirs}"  # the lease: the merged head


def test_a_push_without_a_new_commit_of_the_person_makes_no_merge(world, trailers):
    world.run_commit({"b.txt": "b\n"}, trailers)
    world.git.push_branch("origin", BRANCH, answers=world.answers(trailers))
    assert world.merged == [] and world.rescans == 0 and world.sleeps == []


def test_a_persons_code_commit_is_not_merged(world, trailers):
    """SCN-RACE-03."""
    world.run_commit({"b.txt": "b\n"}, trailers)
    human = world.person({"src/app.py": "print('v2')\n", QUESTIONS: world.first})  # type: ignore[attr-defined]
    before = world.head()
    with pytest.raises(BranchMoved) as caught:
        world.git.push_branch("origin", BRANCH, answers=world.answers(trailers))
    assert not isinstance(caught.value, BranchKeepsMoving)
    assert caught.value.paths == ("src/app.py",) and caught.value.remote_head == human
    assert world.head() == before and world.remote() == human and world.merged == [] and world.sleeps == []


@pytest.mark.parametrize(
    "path",
    [f"{UNIT}/tasks.md", "openspec/changes/y/questions.md", f"{UNIT}/sub/questions.md", "questions.md",
     f"{UNIT}-fix-2/questions.md", f"{UNIT}-fix-x/questions.md", f"{UNIT}-fix-1/questions.md.bak"],
)  # fmt: skip
def test_only_the_questions_of_the_unit_and_its_fix_units_on_the_branch_are_answer_files(world, path):
    assert not is_answer_file(world.git, UNIT, path)


def test_the_questions_of_the_unit_and_of_a_fix_unit_on_the_branch_are_answer_files(world):
    assert is_answer_file(world.git, UNIT, QUESTIONS) and is_answer_file(world.git, UNIT, FIX_QUESTIONS)


def test_answers_to_a_fix_units_questions_are_merged_too(world, raw, trailers):
    """SCN-RACE-06."""
    fix = (world.repo / FIX_QUESTIONS).read_bytes()
    world.run_commit({"b.txt": "b\n"}, trailers)
    theirs = world.person({FIX_QUESTIONS: answered(fix, "Q-001", "yes: fix it")})
    world.git.push_branch("origin", BRANCH, answers=world.answers(trailers))
    assert world.remote() == world.head() and theirs in raw(world.repo, "rev-list", "--parents", "-n1", "HEAD").split()
    assert world.merged == [(theirs, 1, (FIX_QUESTIONS,))]


def test_answers_that_keep_arriving_stop_after_three_tries(world, trailers):
    """SCN-RACE-05: a new answer lands before each of the three pushes; 5 s and then 15 s apart, then an error."""
    world.run_commit({"b.txt": "b\n"}, trailers)
    text = iter(["one", "two", "three", "four"])
    current = [world.first]  # type: ignore[attr-defined]

    def arrive() -> None:
        data = answered(world.first, "Q-001", next(text))  # type: ignore[attr-defined]
        current[0] = data
        world.person({QUESTIONS: data})

    arrive()
    world.on_rescan = arrive  # after each merge, before the push
    with pytest.raises(BranchKeepsMoving) as caught:
        world.git.push_branch("origin", BRANCH, answers=world.answers(trailers))
    assert world.sleeps == [5.0, 15.0] and world.rescans == 2
    assert caught.value.tries == 3  # the pushes of `push_merging`, not the inner count of one push (review fix 7)
    from l4.forge.pushfail import explain_push_failure

    said = explain_push_failure(caught.value, branch=BRANCH, token_env="L4_FORGE_TOKEN", environ={}, redact=lambda s: s)
    assert "the harness tried 3 times" in str(said) and "keeps moving" in str(said)
    assert [m[1] for m in world.merged] == [1, 1]
    assert caught.value.remote_head == world.remote() and caught.value.paths == (QUESTIONS,)
    pushes = [argv for argv in world.git.history if "push" in argv]
    assert len(pushes) == 3 - 1 + 1 + 1  # the setup push, then the three tries of the run (one is the first push)


def test_a_conflict_in_the_questions_is_settled_per_question(world, raw, trailers):
    world.run_commit({QUESTIONS: answered(world.first, "Q-001", "yes: mine")}, trailers)  # type: ignore[attr-defined]
    world.person({QUESTIONS: answered(world.first, "Q-001", "yes: theirs")})  # type: ignore[attr-defined]
    world.git.push_branch("origin", BRANCH, answers=world.answers(trailers))
    text = (world.repo / QUESTIONS).read_text()
    assert "<<<<<<<" not in text and QuestionsFile.parse(text.encode()).get("Q-001") is not None
    assert world.remote() == world.head() and world.merged and raw(world.repo, "status", "--porcelain").strip() == ""


def test_a_conflict_nobody_can_settle_aborts_the_merge_and_pushes_nothing(world, raw, trailers, tmp_path):
    world.run_commit({"src/app.py": "print('mine')\n"}, trailers)
    other = opened(tmp_path / "other", "A different question?")  # the same id with another title
    world.person({QUESTIONS: other})
    world.run_commit({QUESTIONS: answered(world.first, "Q-001", "yes: mine")}, trailers)  # type: ignore[attr-defined]
    before = world.head()
    with pytest.raises(BranchMoved) as caught:
        world.git.push_branch("origin", BRANCH, answers=world.answers(trailers))
    assert caught.value.conflicts == (QUESTIONS,)
    assert world.head() == before and not (world.repo / ".git" / "MERGE_HEAD").exists()
    assert raw(world.repo, "status", "--porcelain").strip() == ""


def test_the_runs_open_ledger_may_be_dirty_during_the_merge(world, trailers):
    world.run_commit({"b.txt": "b\n"}, trailers)
    world.person({QUESTIONS: answered(world.first, "Q-001", "yes")})  # type: ignore[attr-defined]
    ledger = world.repo / LEDGER
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text('{"type":"run.started"}\n')
    world.git.push_branch("origin", BRANCH, answers=world.answers(trailers, keep_dirty=(LEDGER,)))
    assert world.remote() == world.head() and ledger.read_text() == '{"type":"run.started"}\n'


def test_a_refused_merge_is_a_classified_failed_push_and_leaves_the_worktree_as_it_was(world, raw, trailers):
    """Review fix 6: a dirty worktree is `MergeRefused` in the merge; for the push it is `BranchMoved` (a `GitError`,
    so the run knows its push failed), with the reason."""
    world.run_commit({"b.txt": "b\n"}, trailers)
    human = world.person({QUESTIONS: answered(world.first, "Q-001", "yes")})  # type: ignore[attr-defined]
    (world.repo / "stray.txt").write_text("x")
    before = world.head()
    with pytest.raises(BranchMoved) as caught:
        world.git.push_branch("origin", BRANCH, answers=world.answers(trailers))
    assert "stray.txt" in caught.value.refused and caught.value.remote_head == human
    assert world.head() == before and world.remote() == human and world.merged == []
    assert not (world.repo / ".git" / "MERGE_HEAD").exists()


def test_any_failure_after_the_merge_started_aborts_it(world, raw, trailers, monkeypatch):
    """Review fix 6: no MERGE_HEAD, no staged answer file is left behind, whatever goes wrong before the commit."""
    world.run_commit({"b.txt": "b\n"}, trailers)
    world.person({QUESTIONS: answered(world.first, "Q-001", "yes")})  # type: ignore[attr-defined]
    before = world.head()

    def boom(*args, **kwargs):
        raise RuntimeError("the commit failed")

    monkeypatch.setattr(Git, "commit", boom)
    with pytest.raises(RuntimeError):
        world.git.push_branch("origin", BRANCH, answers=world.answers(trailers))
    assert world.head() == before and not (world.repo / ".git" / "MERGE_HEAD").exists()
    assert raw(world.repo, "status", "--porcelain").strip() == ""


def test_a_scan_that_stops_the_push_after_the_merge_leaves_the_remote_alone(world, trailers):
    """The caller's rescan raises (a secret in the outgoing commits): no push follows the merge."""
    world.run_commit({"b.txt": "b\n"}, trailers)
    human = world.person({QUESTIONS: answered(world.first, "Q-001", "yes")})  # type: ignore[attr-defined]

    def stop() -> None:
        raise RuntimeError("secret")

    world.on_rescan = stop
    with pytest.raises(RuntimeError):
        world.git.push_branch("origin", BRANCH, answers=world.answers(trailers))
    assert world.remote() == human


def test_a_cancel_during_the_wait_stops_the_run(world, trailers):
    import signal

    from l4 import cancel
    from l4.cancel import RunCancelled

    world.run_commit({"b.txt": "b\n"}, trailers)
    world.person({QUESTIONS: answered(world.first, "Q-001", "yes")})  # type: ignore[attr-defined]
    world.git._sleep = lambda seconds: cancel.request(signal.SIGTERM)
    try:
        with pytest.raises(RunCancelled):
            world.git.push_branch("origin", BRANCH, answers=world.answers(trailers))
    finally:
        cancel.reset()


# --- answers only, commit by commit, and regular files only (review fix 4) ------------------------------------------


def test_a_code_commit_that_a_later_commit_reverts_is_still_not_an_answer(world, trailers):
    """The net diff of the two commits is the answer alone; the first one changed code, and is not merged."""
    world.run_commit({"b.txt": "b\n"}, trailers)
    world.person({"src/app.py": "print('v2')\n"}, "code")
    human = world.person({"src/app.py": "print('app')\n", QUESTIONS: world.first}, "revert + answer")  # type: ignore[attr-defined]
    before = world.head()
    with pytest.raises(BranchMoved) as caught:
        world.git.push_branch("origin", BRANCH, answers=world.answers(trailers))
    assert "src/app.py" in caught.value.paths and caught.value.commits == 2 and caught.value.remote_head == human
    assert world.head() == before and world.remote() == human and world.merged == []


def delete_questions(world: World) -> None:
    world.raw(world.human, "rm", "-q", QUESTIONS)
    world.raw(world.human, "-c", "user.name=h", "-c", "user.email=h@x", "commit", "-q", "-m", "delete")
    world.raw(world.human, "push", "-q", "origin", BRANCH)


def chmod_questions(world: World) -> None:
    (world.human / QUESTIONS).chmod(0o755)
    world.raw(world.human, "-c", "user.name=h", "-c", "user.email=h@x", "commit", "-q", "-a", "-m", "mode")
    world.raw(world.human, "push", "-q", "origin", BRANCH)


def link_questions(world: World) -> None:
    (world.human / QUESTIONS).unlink()
    (world.human / QUESTIONS).symlink_to("../../../README.md")
    world.raw(world.human, "add", "-A")
    world.raw(world.human, "-c", "user.name=h", "-c", "user.email=h@x", "commit", "-q", "-m", "link")
    world.raw(world.human, "push", "-q", "origin", BRANCH)


@pytest.mark.parametrize("change", [delete_questions, chmod_questions, link_questions])
def test_a_deleted_a_mode_changed_or_linked_questions_file_is_not_an_answer(world, trailers, change):
    world.run_commit({"b.txt": "b\n"}, trailers)
    change(world)
    human = world.raw(world.human, "rev-parse", "HEAD").strip()
    before = world.head()
    with pytest.raises(BranchMoved) as caught:
        world.git.push_branch("origin", BRANCH, answers=world.answers(trailers))
    assert caught.value.paths == (QUESTIONS,) and caught.value.remote_head == human
    assert world.head() == before and world.remote() == human and world.merged == []


def test_a_merge_commit_of_a_person_that_brings_an_answer_only_is_merged(world, raw, trailers):
    mine = world.run_commit({"b.txt": "b\n"}, trailers)
    raw(world.human, "checkout", "-q", "-b", "side")
    (world.human / QUESTIONS).write_bytes(answered(world.first, "Q-001", "yes: side"))  # type: ignore[attr-defined]
    raw(world.human, "-c", "user.name=h", "-c", "user.email=h@x", "commit", "-q", "-a", "-m", "side answer")
    raw(world.human, "checkout", "-q", BRANCH)
    raw(world.human, "-c", "user.name=h", "-c", "user.email=h@x", "merge", "-q", "--no-ff", "-m", "merge", "side")
    raw(world.human, "push", "-q", "origin", BRANCH)
    theirs = raw(world.human, "rev-parse", "HEAD").strip()
    world.git.push_branch("origin", BRANCH, answers=world.answers(trailers))
    assert world.merged and world.merged[0][0] == theirs and world.merged[0][2] == (QUESTIONS,)
    assert world.remote() == world.head() and raw(world.repo, "merge-base", "--is-ancestor", mine, "HEAD") == ""


def test_the_private_ref_is_one_per_process_and_branch(world, trailers):
    """Review fix 5: two worktrees of a clone (two units, or two runs) never share the ref the head is fetched to."""
    import os

    world.person({"notes.txt": "n"})
    world.run_commit({"b.txt": "b\n"}, trailers)
    with pytest.raises(BranchMoved):
        world.git.push_branch("origin", BRANCH)
    [fetch] = [argv for argv in world.git.history if "fetch" in argv and "--refmap=" in argv]
    assert fetch[-1] == f"+{REF}:refs/l4/tmp/{os.getpid()}/{BRANCH}"
