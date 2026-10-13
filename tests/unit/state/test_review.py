"""What happened on the unit branch after the hand-off commit H (SPEC 12.0, forge-and-ci 2.41)."""

from pathlib import Path

from l4.state.review import AfterHandoff, after_handoff
from l4.vcs.authorship import HANDOFF_SUBJECT
from l4.vcs.git import BOT_IDENTITY

NAME = "add-x"
UNIT_REL = "openspec/changes/add-x"
BOT = ("-c", f"user.name={BOT_IDENTITY.name}", "-c", f"user.email={BOT_IDENTITY.email}")


class Branch:
    def __init__(self, repo: Path, raw, git) -> None:
        self.repo, self.raw, self.git = repo, raw, git

    def commit(self, subject: str, files: dict[str, str], *, bot: bool, run: bool = True, phase="implementing") -> str:
        for rel, text in files.items():
            target = self.repo / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        self.raw(self.repo, "add", "-A")
        trailers = ["--trailer=L4-Run: r-1", f"--trailer=L4-Phase: {phase}"] if run else []
        self.raw(self.repo, *(BOT if bot else ()), "commit", "-q", "--allow-empty", "-m", subject, *trailers)
        return self.raw(self.repo, "rev-parse", "HEAD").strip()

    def handoff(self, files: dict[str, str] | None = None) -> str:
        return self.commit(
            HANDOFF_SUBJECT.format(name=NAME),
            files or {f"{UNIT_REL}/verification.md": "ok\n"}, bot=True, phase="verified",
        )  # fmt: skip

    def after(self) -> AfterHandoff:
        return after_handoff(self.git, "HEAD", NAME, UNIT_REL)


def _branch(make_repo, raw, git_for) -> Branch:
    repo = make_repo()
    raw(repo, "checkout", "-q", "-b", "l4/openspec/add-x")
    b = Branch(repo, raw, git_for(repo))
    b.commit("work", {f"{UNIT_REL}/tasks.md": "- [x] 1.1 a\n", "src/a.py": "a = 1\n"}, bot=True)
    return b


def test_foreign_commits_after_h_are_listed_harness_ones_are_not(make_repo, raw, git_for):
    b = _branch(make_repo, raw, git_for)
    h = b.handoff()
    assert b.after() == AfterHandoff(h, h, (), False, False)
    b.commit("bot again", {"src/b.py": "b\n"}, bot=True)
    assert b.after().foreign == () and b.after().handoff == h
    human = b.commit("fix the thing", {"src/a.py": "a = 2\n"}, bot=False, run=False)
    found = b.after()
    assert [c.sha for c in found.foreign] == [human]
    assert (found.foreign[0].subject, found.foreign[0].author) == ("fix the thing", "t")
    assert not found.spec_edit and not found.lost and found.head == human


def test_a_bot_named_commit_without_l4_run_is_foreign(make_repo, raw, git_for):
    b = _branch(make_repo, raw, git_for)
    b.handoff()
    sha = b.commit("sneaky", {"src/a.py": "a = 3\n"}, bot=True, run=False)
    assert [c.sha for c in b.after().foreign] == [sha]


def test_unit_folder_edit_is_a_spec_edit_but_verification_md_and_l4_are_not(make_repo, raw, git_for):
    b = _branch(make_repo, raw, git_for)
    b.handoff()
    b.commit("evidence", {f"{UNIT_REL}/verification.md": "changed\n", f"{UNIT_REL}/.l4/ledger/x.jsonl": "{}\n"},
             bot=False, run=False)  # fmt: skip
    assert b.after().foreign and not b.after().spec_edit
    b.commit("add a task", {f"{UNIT_REL}/tasks.md": "- [x] 1.1 a\n- [ ] 1.2 b\n"}, bot=False, run=False)
    assert b.after().spec_edit


def test_a_human_merge_of_the_base_after_h_is_foreign(make_repo, raw, git_for):
    b = _branch(make_repo, raw, git_for)
    h = b.handoff()
    raw(b.repo, "checkout", "-q", "main")
    (b.repo / "base.txt").write_text("new on main\n")
    raw(b.repo, "add", "-A")
    raw(b.repo, "commit", "-q", "-m", "main moves")
    raw(b.repo, "checkout", "-q", "l4/openspec/add-x")
    raw(b.repo, "merge", "-q", "--no-ff", "-m", "Merge main", "main")
    found = b.after()
    assert found.handoff == h and [c.subject for c in found.foreign] == ["Merge main"]
    assert not found.spec_edit


def test_h_missing_from_the_branch_is_lost(make_repo, raw, git_for):
    b = _branch(make_repo, raw, git_for)
    found = b.after()
    assert found.lost and found.handoff is None and found.foreign == ()


def test_an_answer_in_questions_md_alone_takes_the_answer_path(make_repo, raw, git_for):
    """`questions.md` is where a person answers (SPEC 6): a commit that only touches it is an answer, so the unit goes
    to `implementing` (SPEC 12.0 "answers or spec edits"), not straight into a new verification round."""
    from l4.state.fold import UnitState
    from l4.state.lifecycle import Trigger
    from l4.state.review import review_trigger

    b = _branch(make_repo, raw, git_for)
    b.commit("ask", {f"{UNIT_REL}/questions.md": "### Q-1\n**Status**: open\n"}, bot=True)
    h = b.handoff()
    answer = b.commit("answer Q-1", {f"{UNIT_REL}/questions.md": "### Q-1\n**Status**: answered\n"}, bot=False,
                      run=False)  # fmt: skip
    found = b.after()
    assert found.handoff == h and [c.sha for c in found.foreign] == [answer] and found.spec_edit
    edge = review_trigger(found, UnitState(unit="openspec:add-x", phase="in_review"))
    assert edge is not None and edge.trigger is Trigger.SPEC_EDIT_AFTER_HANDOFF


def test_an_amended_handoff_commit_is_seen_as_a_persons_change(make_repo, raw, git_for):
    b = _branch(make_repo, raw, git_for)
    b.handoff()
    (b.repo / "src" / "a.py").write_text("a = 99  # a person's change, amended into H\n")
    raw(b.repo, "add", "-A")
    raw(b.repo, "commit", "-q", "--amend", "--no-edit")  # the person is the committer; author and trailers stay
    found = b.after()
    assert found.reentry


def test_a_rebased_commit_after_h_is_a_persons_change(make_repo, raw, git_for):
    """A bot-authored, trailered commit whose committer is a person (cherry-pick, rebase) is foreign for G1."""
    b = _branch(make_repo, raw, git_for)
    b.handoff()
    bot_work = b.commit("bot work", {"src/b.py": "b\n"}, bot=True)
    raw(b.repo, "reset", "-q", "--hard", "HEAD~1")
    raw(b.repo, "cherry-pick", bot_work)  # author and trailers kept, committer = the configured person
    found = b.after()
    assert [c.subject for c in found.foreign] == ["bot work"] and found.reentry


def test_a_forge_squash_commit_by_a_project_bot_is_not_the_harnesss(make_repo, raw, git_for):
    """GitLab's squash commit on main: author a project bot account (not `l4-bot`), no L4 trailers."""
    from l4.vcs.authorship import commit_records, handoff_commit, is_harness, is_harness_strict

    b = _branch(make_repo, raw, git_for)
    h = b.handoff()
    raw(b.repo, "-c", "user.name=Project Bot", "-c", "user.email=project_7_bot_ab12@noreply.gitlab.example",
        "commit", "-q", "--allow-empty", "-m", "Squash of add-x")  # fmt: skip
    (squash,) = commit_records(b.git, "-1", "HEAD")
    assert not is_harness(squash) and not is_harness_strict(squash)
    assert handoff_commit(b.git, "HEAD", NAME) == h  # H is still found beneath the squash commit
    assert handoff_commit(b.git, "HEAD~1", NAME) == h


# --- L4-OPS-014: a person's spec edit since the harness's last commit ---------------------------------------------


def test_a_spec_edit_since_the_harness_names_the_commits_and_the_harness_commit_before_them(make_repo, raw, git_for):
    from l4.state.review import spec_edit_since_harness

    b = _branch(make_repo, raw, git_for)
    last = b.commit("stop", {f"{UNIT_REL}/.l4/ledger/a.jsonl": "{}\n"}, bot=True)
    assert spec_edit_since_harness(b.git, "HEAD", UNIT_REL) is None  # the head is the harness's own commit
    first = b.commit("reword", {f"{UNIT_REL}/proposal.md": "new\n"}, bot=False, run=False)
    second = b.commit("more", {"src/a.py": "a = 2\n"}, bot=False, run=False)
    found = spec_edit_since_harness(b.git, "HEAD", UNIT_REL)
    assert found is not None
    assert (found.shas, found.base, found.head) == ((first, second), last, second)


def test_only_files_the_harness_or_a_question_channel_owns_are_not_a_spec_edit(make_repo, raw, git_for):
    from l4.state.review import spec_edit_since_harness

    b = _branch(make_repo, raw, git_for)
    b.commit("stop", {f"{UNIT_REL}/.l4/ledger/a.jsonl": "{}\n"}, bot=True)
    owned = {f"{UNIT_REL}/{name}": "x\n" for name in ("verification.md", "questions.md", "feedback.md")}
    b.commit(
        "channels", {**owned, f"{UNIT_REL}/.l4/ledger/b.jsonl": "{}\n", "src/a.py": "a = 5\n"}, bot=False, run=False
    )
    assert spec_edit_since_harness(b.git, "HEAD", UNIT_REL) is None
    b.commit("spec", {f"{UNIT_REL}/specs/greeting/spec.md": "x\n"}, bot=False, run=False)
    assert spec_edit_since_harness(b.git, "HEAD", UNIT_REL) is not None


def test_a_sibling_fix_unit_folder_is_not_the_unit_folder(make_repo, raw, git_for):
    from l4.state.review import spec_edit_since_harness

    b = _branch(make_repo, raw, git_for)
    b.commit("stop", {f"{UNIT_REL}/.l4/ledger/a.jsonl": "{}\n"}, bot=True)
    b.commit("fix unit", {f"{UNIT_REL}-fix-1/tasks.md": "- [ ] 1.1 x\n"}, bot=False, run=False)
    assert spec_edit_since_harness(b.git, "HEAD", UNIT_REL) is None


def test_a_persons_rebase_with_no_unit_folder_change_is_no_spec_edit(make_repo, raw, git_for):
    """Review M2: a rebase makes the person the committer of every harness commit, so none is strict any more; the
    spec-edit scan is bounded by the author rule (bot author and `L4-Run`, kept by a rebase) and finds no edit."""
    from l4.state.review import foreign_tail, spec_edit_since_harness

    repo = make_repo()
    for j in range(60):  # more history than the scan reads: a strict scan would walk into it
        (repo / "hist.txt").write_text(str(j))
        raw(repo, "add", "-A")
        raw(repo, "commit", "-q", "-m", f"old history {j}")
    raw(repo, "checkout", "-q", "-b", "l4/openspec/add-x")
    b = Branch(repo, raw, git_for(repo))
    b.commit("task 1.1", {f"{UNIT_REL}/tasks.md": "- [x] 1.1 a\n", "src/a.py": "a = 1\n"}, bot=True)
    b.commit("ledger", {f"{UNIT_REL}/.l4/ledger/a.jsonl": "{}\n"}, bot=True)
    assert spec_edit_since_harness(b.git, "HEAD", UNIT_REL) is None
    raw(repo, "checkout", "-q", "main")
    (repo / "other.txt").write_text("x")
    raw(repo, "add", "-A")
    raw(repo, "commit", "-q", "-m", "unrelated change on main")
    raw(repo, "checkout", "-q", "l4/openspec/add-x")
    raw(repo, "rebase", "-q", "main")
    assert (
        foreign_tail(b.git, "HEAD") != ()
    )  # the strict rule sees the replayed commits as a person's (review re-entry)
    assert spec_edit_since_harness(b.git, "HEAD", UNIT_REL) is None


def test_a_persons_commit_after_a_rebase_is_still_a_spec_edit_from_the_replayed_harness_commit(make_repo, raw, git_for):
    from l4.state.review import spec_edit_since_harness

    b = _branch(make_repo, raw, git_for)
    last = b.commit("stop", {f"{UNIT_REL}/.l4/ledger/a.jsonl": "{}\n"}, bot=True)
    raw(b.repo, "checkout", "-q", "main")
    raw(b.repo, "commit", "-q", "--allow-empty", "-m", "main moves")
    raw(b.repo, "checkout", "-q", "l4/openspec/add-x")
    raw(b.repo, "rebase", "-q", "main")
    replayed = b.raw(b.repo, "rev-parse", "HEAD").strip()
    assert replayed != last
    person = b.commit("reword", {f"{UNIT_REL}/proposal.md": "new\n"}, bot=False, run=False)
    found = spec_edit_since_harness(b.git, "HEAD", UNIT_REL)
    assert found is not None and (found.shas, found.base) == ((person,), replayed)


def test_a_unit_folder_file_the_same_at_the_boundary_and_at_the_head_is_no_spec_edit(make_repo, raw, git_for):
    from l4.state.review import spec_edit_since_harness

    b = _branch(make_repo, raw, git_for)
    b.commit("stop", {f"{UNIT_REL}/.l4/ledger/a.jsonl": "{}\n"}, bot=True)
    before = (b.repo / UNIT_REL / "tasks.md").read_text()
    b.commit("edit", {f"{UNIT_REL}/tasks.md": "- [ ] 9.9 changed\n"}, bot=False, run=False)
    b.commit("undo", {f"{UNIT_REL}/tasks.md": before}, bot=False, run=False)
    assert spec_edit_since_harness(b.git, "HEAD", UNIT_REL) is None
