# ruff: noqa: F811
"""`--record` reviews what origin holds, and the CI review warns about unpushed plan commits (yolo-guardrails D3, D4;
L4-YOLO-069, L4-YOLO-070; SCN-YOLO-185 to -191)."""

from l4.vcs.names import unit_branch
from l4.yolo.digest import unit_digest

from .test_yolo_commands_activate import fake_judge
from .test_yolo_review_worktree import (
    FOLDER_A,
    GAP,
    SPEC_FILE,
    answer,
    commit_edit,
    edit_spec,
    judge,
    push_edit,
    ready_world,
)
from .yolo_cmd_world import A, forge, plan_doc, world  # noqa: F401

RECORD = ("review", "p1", "--worktree", "--record")
HEADER = "review: --record records what CI and l4 yolo activate read, origin/main, and HEAD is not that commit:"


def head(world) -> str:
    return world.clone.run("rev-parse", "HEAD").stdout.strip()


def tip(world) -> str:
    return world.remote.rev_parse("main") or ""


def refused(world, capsys, *argv) -> str:
    capsys.readouterr()
    assert world.l4(*argv) == 2
    return capsys.readouterr().err


def test_a_record_with_head_ahead_is_refused_before_any_judge_call(world, monkeypatch, capsys):
    ready_world(world)
    commit_edit(world)
    fake = judge(monkeypatch)  # an empty script: a call fails the test
    err = refused(world, capsys, *RECORD)
    assert (
        f"{HEADER}\n  origin/main ({tip(world)[:7]}) is 1 commit behind HEAD ({head(world)[:7]}); they differ in "
        f"{FOLDER_A}: push, then review\n"
        "Fix: git push origin HEAD:main, then l4 yolo review p1 --worktree --record"
    ) in err
    assert fake.requests == [] and world.store().read().head is None


def test_a_record_with_head_behind_names_the_pull(world, monkeypatch, capsys):
    ready_world(world)
    world.push({"openspec/changes/add-b/proposal.md": "# B again\n"}, "b elsewhere")
    judge(monkeypatch)
    err = refused(world, capsys, *RECORD)
    assert "is 1 commit ahead of HEAD (" in err and "they differ in openspec/changes/add-b: pull, then review" in err
    assert err.rstrip().endswith("Fix: git pull --ff-only, then l4 yolo review p1 --worktree --record")
    assert world.store().read().head is None


def test_a_diverged_record_names_both(world, monkeypatch, capsys):
    ready_world(world)
    commit_edit(world)
    world.push({"openspec/changes/add-b/proposal.md": "# B again\n"}, "b elsewhere")
    judge(monkeypatch)
    err = refused(world, capsys, *RECORD)
    assert "have diverged: 1 commit only on HEAD, 1 only on origin/main" in err
    assert err.rstrip().endswith(
        "Fix: git pull --rebase, then git push origin HEAD:main, then l4 yolo review p1 --worktree --record"
    )


def test_a_record_refuses_when_the_divergence_cannot_be_counted(world, monkeypatch, capsys):
    """Review finding MINOR-8: two different shas and an unreadable `rev-list` count are not "HEAD is origin"."""
    from l4.vcs.git import Git, GitResult

    ready_world(world)
    commit_edit(world)
    real = Git.run

    def run(self, *args, **kwargs):
        if args[:1] == ("rev-list",):
            return GitResult(0, "junk\n", "")
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Git, "run", run)
    fake = judge(monkeypatch)
    err = refused(world, capsys, *RECORD)
    assert head(world)[:7] in err and tip(world)[:7] in err and "could not count" in err
    assert "Fix: git fetch origin main" in err and err.rstrip().endswith("l4 yolo review p1 --worktree --record")
    assert fake.requests == [] and world.store().read().head is None


def branch_with(world, files: dict[str, str]) -> str:
    """`origin/<A's unit branch>` holds HEAD plus `files`; the clone itself stays at `origin/main`."""
    branch = unit_branch(A, "l4/")
    for name, text in files.items():
        (world.app.repo / name).write_text(text, encoding="utf-8")
        world.clone.run("add", name)
    world.clone.run("commit", "-q", "-m", "on the branch")
    world.clone.run("push", "-q", "origin", f"HEAD:refs/heads/{branch}")
    world.clone.run("reset", "-q", "--hard", "origin/main")
    return branch


def test_a_record_refuses_a_unit_whose_branch_holds_another_spec(world, monkeypatch, capsys):
    ready_world(world)
    path = world.app.repo / SPEC_FILE
    branch = branch_with(world, {SPEC_FILE: path.read_text(encoding="utf-8") + "\nOn the branch.\n"})
    fake = judge(monkeypatch)
    err = refused(world, capsys, *RECORD)
    on_branch = world.remote.rev_parse(f"refs/heads/{branch}") or ""
    d_branch = unit_digest(world.remote, on_branch, FOLDER_A)
    d_head = unit_digest(world.clone, "HEAD", FOLDER_A)
    assert (
        f"review: --record: CI reads {A} on its branch {branch} ({on_branch[:7]}), where its spec digest is "
        f"{d_branch[:8]}; HEAD has {d_head[:8]}; changed: {SPEC_FILE}\n"
        f"Fix: change the spec on {branch} (runbook 7.14), or let CI review: l4 yolo review p1"
    ) in err
    assert fake.requests == [] and world.store().read().head is None


def test_a_branch_that_differs_only_in_check_marks_is_not_refused(world, monkeypatch, capsys):
    ready_world(world)
    tasks = f"{FOLDER_A}/tasks.md"
    text = (world.app.repo / tasks).read_text(encoding="utf-8")
    assert "[ ]" in text
    branch_with(world, {tasks: text.replace("[ ]", "[x]", 1)})
    judge(monkeypatch, answer(), answer(), answer())
    capsys.readouterr()
    assert world.l4(*RECORD) == 0
    assert "CI reads" not in capsys.readouterr().out


def test_a_record_at_origin_names_the_next_step(world, monkeypatch, capsys):
    ready_world(world)
    judge(monkeypatch, answer(), answer(), answer())
    capsys.readouterr()
    assert world.l4(*RECORD) == 0
    assert capsys.readouterr().out.splitlines()[-1] == "Next: a person runs l4 yolo activate p1 --reason TEXT"
    assert world.events()[1].data["target_rev"] == head(world) == tip(world)
    # a subject that is not READY and not accepted
    world.clone.run("config", "user.name", "alex")
    push_edit(world)
    judge(monkeypatch, answer("NEEDS_REVISION", [GAP]), answer(), answer())
    capsys.readouterr()
    assert world.l4(*RECORD) == 2
    assert capsys.readouterr().out.splitlines()[-1] == "Next: l4 yolo findings p1"


def test_the_dry_run_is_not_refused_before_the_push(world, monkeypatch, capsys):
    ready_world(world)
    commit_edit(world)
    edit_spec(world, "\nUncommitted.\n")
    judge(monkeypatch, answer(), answer(), answer())
    capsys.readouterr()
    assert world.l4("review", "p1", "--worktree") == 0
    assert capsys.readouterr().out.splitlines()[-1] == (
        "Next: commit and push the plan file and the unit folders, then l4 yolo review p1 --worktree --record "
        "(it records the review of origin/main; it judges again whatever the ledger does not hold)"
    )


# --- the CI review warns (D4; SCN-YOLO-190, -191) -----------------------------------------------------------------


def warning(world) -> str:
    return (
        f"warning: origin/main ({tip(world)[:7]}) is 1 commit behind HEAD ({head(world)[:7]}); they differ in "
        f"{FOLDER_A}: "
    )


def test_the_ci_review_warns_about_an_unpushed_plan_commit(world, capsys):
    ready_world(world)
    commit_edit(world)
    capsys.readouterr()
    assert world.l4("review", "p1", "--no-run") == 0
    out = capsys.readouterr().out
    assert out.splitlines()[0] == warning(world) + "CI reviews origin/main, not your commits: push, then review"
    assert "review requested" in out


def test_local_warns_too(world, monkeypatch, capsys):
    ready_world(world)
    commit_edit(world)
    fake_judge(monkeypatch, {})
    capsys.readouterr()
    assert world.l4("review", "p1", "--local") == 0
    first = capsys.readouterr().out.splitlines()[0]
    assert first == warning(world) + "--local reviews origin/main, not your commits: push, then review"


def test_an_unrelated_unpushed_commit_gives_no_warning(world, capsys):
    ready_world(world)
    world.app.repo.joinpath("README.md").write_text("changed\n", encoding="utf-8")
    world.clone.run("add", "README.md")
    world.clone.run("commit", "-q", "-m", "readme")
    capsys.readouterr()
    assert world.l4("review", "p1", "--no-run") == 0
    assert "warning:" not in capsys.readouterr().out


def test_head_behind_gives_no_warning(world, capsys):
    ready_world(world)
    world.push({"openspec/changes/add-b/proposal.md": "# B again\n"}, "b elsewhere")
    capsys.readouterr()
    assert world.l4("review", "p1", "--no-run") == 0
    assert "warning:" not in capsys.readouterr().out
