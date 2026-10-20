# ruff: noqa: F811
"""`l4 yolo go` push (L4-YOLO-082; SCN-YOLO-205 to -212): a fast-forward push of the base branch, never forced, after
the working-tree admission, and never one that would stop the active plan."""

import stat

from l4.yolo.digest import plan_digest

from .yolo_actor import agent, person  # noqa: F401
from .yolo_cmd_world import PURPOSE_B, A, B, ev, forge, plan_doc, world  # noqa: F401


class Boom:
    def __init__(self, *args, **kwargs):
        raise AssertionError("no model")


def no_model(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("no model")

    monkeypatch.setattr("l4.yolo.readiness.Factory", Boom)
    monkeypatch.setattr("l4.yolo.commands.review_plan_costed", boom)


def commit(world, files: dict[str, str], message: str = "local") -> str:
    """A local commit in the checkout under test (not pushed)."""
    for path, text in files.items():
        target = world.app.repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    world.clone.run("add", *files)
    world.clone.run("commit", "--quiet", "-m", message)
    return world.clone.rev_parse("HEAD") or ""


def origin_main(world) -> str:
    return world.remote.rev_parse("refs/heads/main") or ""


def local_plan(world, *extra: dict[str, str]) -> str:
    """Plan `p1` committed on the local base branch and NOT pushed, with a review at the digests of its files seeded on
    the origin: the starting point of a run that reaches the end once it has pushed. Returns the origin's head."""
    before = origin_main(world)
    world.push_plan()
    world.pull()
    world.seed("p1", ev("plan.admitted", plan_digest=plan_digest(world.plan_text), order=[A, B]), world.reviewed())
    world.remote.run("update-ref", "refs/heads/main", before)
    world.clone.run("fetch", "--quiet", "origin")
    for files in extra:
        commit(world, files)
    return before


def pushed(world, monkeypatch):
    """Spy on the git push `go` makes: the list of its argv."""
    from l4.yolo import go

    calls: list[tuple[str, ...]] = []
    real = go._push

    def spy(git, args, config=()):
        calls.append(tuple(args))
        return real(git, args, config)

    monkeypatch.setattr(go, "_push", spy)
    return calls


def test_nothing_ahead_pushes_nothing(world, forge, person, monkeypatch, capsys):
    no_model(monkeypatch)
    world.push_plan()
    world.pull()
    world.seed("p1", ev("plan.admitted", plan_digest=plan_digest(world.plan_text), order=[A, B]), world.reviewed())
    calls = pushed(world, monkeypatch)
    assert world.l4("go", "p1", "--reason", "R") == 0
    assert "push: ok: origin/main has HEAD" in capsys.readouterr().out
    assert calls == []


def test_commits_ahead_are_pushed_as_a_fast_forward(world, forge, person, monkeypatch, capsys):
    """SCN-YOLO-205."""
    no_model(monkeypatch)
    local_plan(world, {"docs/note.md": "a note\n"})
    assert origin_main(world) != world.clone.rev_parse("HEAD")
    calls = pushed(world, monkeypatch)
    assert world.l4("go", "p1", "--reason", "R") == 0
    out = capsys.readouterr().out
    assert origin_main(world) == world.clone.rev_parse("HEAD")
    assert len(calls) == 1 and calls[0][:2] == ("push", "origin")
    assert not [a for a in calls[0] if a.startswith("--force")] and "refs/heads/main:refs/heads/main" in calls[0]
    assert "push: done: pushed 2 commit(s) to origin/main (" in out
    assert [c.args for c in forge.called("start_run")] == [("main",)]  # the activation's run, not a review's


def test_no_push_stops_with_the_push_command(world, forge, person, monkeypatch, capsys):
    """SCN-YOLO-206, both halves."""
    no_model(monkeypatch)
    before = local_plan(world)
    calls = pushed(world, monkeypatch)
    assert world.l4("go", "p1", "--reason", "R", "--no-push") == 21
    out = capsys.readouterr().out
    assert out.splitlines()[-1] == "Next: git push origin main" and "push: stopped" in out
    assert origin_main(world) == before and calls == []
    assert world.l4("go", "p1", "--reason", "R") == 0  # pushed by hand or by go, then nothing is ahead
    capsys.readouterr()
    assert world.l4("go", "p1", "--reason", "R", "--no-push") == 0
    assert "push: ok" in capsys.readouterr().out


def test_a_diverged_base_is_never_forced(world, forge, person, monkeypatch, capsys):
    """SCN-YOLO-207."""
    no_model(monkeypatch)
    local_plan(world)
    other = world.push({"other.md": "someone else\n"}, "someone else")
    calls = pushed(world, monkeypatch)
    assert world.l4("go", "p1", "--reason", "R") == 21
    out = capsys.readouterr().out
    assert "HEAD and origin/main have diverged" in out
    assert out.splitlines()[-1] == "Next: git pull --rebase origin main"
    assert origin_main(world) == other and calls == []


def test_only_the_base_branch_is_pushed(world, forge, person, monkeypatch, capsys):
    """SCN-YOLO-208."""
    no_model(monkeypatch)
    before = local_plan(world)
    world.clone.run("switch", "--quiet", "-c", "feature")
    calls = pushed(world, monkeypatch)
    assert world.l4("go", "p1", "--reason", "R") == 21
    out = capsys.readouterr().out
    assert "go pushes only the branch main; HEAD is feature with 1 commit(s) not on origin/main" in out
    assert out.splitlines()[-1] == "Next: git switch main"
    assert origin_main(world) == before and calls == []
    world.clone.run("checkout", "--quiet", "--detach")
    assert world.l4("go", "p1", "--reason", "R") == 21
    assert "HEAD is detached" in capsys.readouterr().out


def test_the_worktree_admission_runs_before_the_push(world, forge, person, monkeypatch, capsys):
    """SCN-YOLO-209: a spec folder that no plan lists would run at once."""
    no_model(monkeypatch)
    spec = PURPOSE_B.replace("counter", "other") + (
        "## ADDED Requirements\n\n### Requirement: C counts\nThe `c()` function SHALL return 1.\n\n"
        "#### Scenario: Counting\n- **WHEN** `c()` is called\n- **THEN** it returns 1\n"
    )
    before = local_plan(
        world,
        {
            "openspec/changes/add-c/tasks.md": "## 1. C\n\n- [ ] 1.1 Add `c()`\n",
            "openspec/changes/add-c/proposal.md": "# C\n",
            "openspec/changes/add-c/specs/c/spec.md": spec,
        },
    )
    calls = pushed(world, monkeypatch)
    assert world.l4("go", "p1", "--reason", "R") == 22
    out = capsys.readouterr().out
    assert "uncovered: openspec:add-c" in out
    assert out.splitlines()[-1] == "Next: l4 yolo check p1 --worktree"
    assert origin_main(world) == before and calls == []
    assert "push: stopped" in out and "check:" not in out


def test_a_push_that_would_stop_the_active_plan_is_not_made(world, forge, person, monkeypatch, capsys):
    """SCN-YOLO-212."""
    no_model(monkeypatch)
    world.push_plan()
    world.pull()
    world.seed(
        "p1", ev("plan.activated", plan_digest=plan_digest(world.plan_text), digests={}, limits={}, by="a", reason="r")
    )
    before = origin_main(world)
    commit(world, {"openspec/changes/add-b/specs/b/spec.md": PURPOSE_B + "## ADDED Requirements\n\nchanged\n"})
    calls = pushed(world, monkeypatch)
    assert world.l4("go", "p1", "--reason", "R") == 21
    out = capsys.readouterr().out
    assert "pushing this stops the active plan p1 with inputs_changed" in out
    assert out.splitlines()[-1] == "Next: l4 yolo status p1"
    assert origin_main(world) == before and calls == []
    # a commit that touches neither the plan file nor a unit folder is pushed
    world.clone.run("reset", "--quiet", "--hard", "origin/main")
    commit(world, {"docs/note.md": "unrelated\n"})
    assert world.l4("go", "p1", "--reason", "R") == 0
    assert origin_main(world) == world.clone.rev_parse("HEAD")


def test_a_stopped_inputs_changed_plan_is_pushed(world, forge, person, monkeypatch, capsys):
    """The guard does not apply: pushing the fixed spec is the way on."""
    no_model(monkeypatch)
    world.push_plan()
    world.pull()
    world.seed(
        "p1",
        ev("plan.activated", plan_digest=plan_digest(world.plan_text), digests={}, limits={}, by="a", reason="r"),
        ev("plan.stopped", reason="inputs_changed", detail="x"),
    )
    commit(world, {"openspec/changes/add-b/proposal.md": "# B fixed\n"})
    assert world.l4("go", "p1", "--reason", "R", "--wait", "0") in (0, 24, 26)
    assert "push: done: pushed 1 commit(s) to origin/main" in capsys.readouterr().out
    assert origin_main(world) == world.clone.rev_parse("HEAD")


def test_a_refused_push_names_gits_reason(world, forge, person, monkeypatch, capsys):
    no_model(monkeypatch)
    before = local_plan(world)
    hook = world.sim.remote / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\necho 'no pushes today' >&2\nexit 1\n", encoding="utf-8")
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR)
    assert world.l4("go", "p1", "--reason", "R") == 21
    out = capsys.readouterr().out
    assert "push: stopped" in out and "no pushes today" in out
    assert out.splitlines()[-1] == "Next: git push origin main"
    assert origin_main(world) == before


# --- the agent's hand-off scope (D12) ---------------------------------------------------------------------------------


def test_an_agents_push_outside_the_hand_off_is_a_persons(world, forge, monkeypatch, capsys):
    """SCN-YOLO-210."""
    no_model(monkeypatch)
    before = local_plan(world, {".l4/config.yaml": "yolo:\n  review:\n    accept_by_agents: true\n"})
    agent(world, monkeypatch)
    calls = pushed(world, monkeypatch)
    assert world.l4("go", "p1", "--reason", "R") == 27
    out = capsys.readouterr().out
    assert "push: person" in out and ".l4/config.yaml" in out
    assert out.splitlines()[-1] == "Next: a person runs: git push origin main"
    assert origin_main(world) == before and calls == []


def test_an_agent_pushes_the_plan_file_and_its_unit_folders(world, forge, monkeypatch, capsys):
    """SCN-YOLO-211."""
    no_model(monkeypatch)
    local_plan(world, {"openspec/changes/add-b/proposal.md": "# B, reworded\n"})
    agent(world, monkeypatch)
    calls = pushed(world, monkeypatch)
    world.l4("go", "p1", "--reason", "R", "--wait", "0")
    out = capsys.readouterr().out
    assert "push: done: pushed 2 commit(s) to origin/main" in out
    assert len(calls) == 1 and origin_main(world) == world.clone.rev_parse("HEAD")


def test_an_agents_push_of_another_plans_file_is_a_persons(world, forge, monkeypatch, capsys):
    no_model(monkeypatch)
    other = '{"schema": "l4/delivery-plan@1", "plan_id": "p2", "batches": []}\n'
    before = local_plan(world, {".l4/plans/p2.json": other})
    agent(world, monkeypatch)
    assert world.l4("go", "p1", "--reason", "R") == 27
    out = capsys.readouterr().out
    assert ".l4/plans/p2.json" in out and out.splitlines()[-1] == "Next: a person runs: git push origin main"
    assert origin_main(world) == before


def test_a_person_pushes_what_an_agent_may_not(world, forge, person, monkeypatch, capsys):
    no_model(monkeypatch)
    local_plan(world, {".l4/config.yaml": "yolo:\n  review:\n    accept_by_agents: true\n"})
    world.l4("go", "p1", "--reason", "R", "--wait", "0")
    assert "push: done" in capsys.readouterr().out
    assert origin_main(world) == world.clone.rev_parse("HEAD")


# --- renames (D4.3, D12): every path a commit touches counts, the old path of a rename too --------------------


def rename(world, source: str, target: str, message: str = "move") -> None:
    (world.app.repo / target).parent.mkdir(parents=True, exist_ok=True)
    world.clone.run("mv", source, target)
    world.clone.run("commit", "--quiet", "-m", message)


def test_an_agents_rename_out_of_scope_is_a_persons_push(world, forge, monkeypatch, capsys):
    """A file moved into a unit folder deletes its old path on origin: that path is outside the hand-off."""
    no_model(monkeypatch)
    world.push({"tests/run_junit.py": "print('junit')\n"}, "a tool")
    world.pull()
    before = local_plan(world)
    rename(world, "tests/run_junit.py", "openspec/changes/add-b/run_junit.py")
    agent(world, monkeypatch)
    calls = pushed(world, monkeypatch)
    assert world.l4("go", "p1", "--reason", "R", "--wait", "0") == 27
    out = capsys.readouterr().out
    assert "tests/run_junit.py" in out and out.splitlines()[-1] == "Next: a person runs: git push origin main"
    assert origin_main(world) == before and calls == []


def test_a_rename_out_of_the_active_plans_unit_folder_is_guarded(world, forge, person, monkeypatch, capsys):
    """Moving a spec file out of a unit folder stops the active plan as surely as editing it."""
    no_model(monkeypatch)
    world.push_plan()
    world.pull()
    world.seed(
        "p1", ev("plan.activated", plan_digest=plan_digest(world.plan_text), digests={}, limits={}, by="a", reason="r")
    )
    before = origin_main(world)
    rename(world, "openspec/changes/add-b/proposal.md", "docs/proposal-b.md")
    calls = pushed(world, monkeypatch)
    assert world.l4("go", "p1", "--reason", "R", "--wait", "0") == 21
    out = capsys.readouterr().out
    assert "stops the active plan p1 with inputs_changed: openspec/changes/add-b/proposal.md" in out
    assert out.splitlines()[-1] == "Next: l4 yolo status p1"
    assert origin_main(world) == before and calls == []


def test_a_push_that_would_stop_another_active_plan_is_not_made(world, forge, person, monkeypatch, capsys):
    """Only one plan is active on a target: its inputs are guarded for every caller, not only its own run's."""
    import json

    no_model(monkeypatch)
    world.push_plan()
    other = plan_doc({"openspec:elsewhere": []}, plan_id="p2")
    world.push({".l4/plans/p2.json": json.dumps(other)}, "a second plan")
    world.pull()
    world.seed("p1", ev("plan.admitted", plan_digest=plan_digest(world.plan_text), order=[A, B]), world.reviewed())
    world.seed("p2", ev("plan.activated", plan_digest="x", digests={}, limits={}, by="a", reason="r"))
    before = origin_main(world)
    commit(world, {"openspec/changes/elsewhere/proposal.md": "# changed\n"})
    calls = pushed(world, monkeypatch)
    assert world.l4("go", "p1", "--reason", "R") == 21
    out = capsys.readouterr().out
    assert "pushing this stops the active plan p2 with inputs_changed: openspec/changes/elsewhere/proposal.md" in out
    assert out.splitlines()[-1] == "Next: l4 yolo status p2"
    assert origin_main(world) == before and calls == []


def test_a_sync_refusal_after_the_push_is_a_stop_with_the_document(world, forge, person, monkeypatch, capsys):
    import json

    from l4.exitcodes import ExitCode, L4Exit
    from l4.yolo import commands

    no_model(monkeypatch)
    local_plan(world)
    real = commands._sync
    calls: list[int] = []

    def sync(ctx, who):
        calls.append(1)
        if len(calls) >= 2:
            raise L4Exit(ExitCode.USAGE_ERROR, "go: origin/main is not on origin")
        return real(ctx, who=who)

    monkeypatch.setattr("l4.yolo.commands._sync", sync)
    assert world.l4("go", "p1", "--reason", "R", "--json") == 21
    doc = json.loads(capsys.readouterr().out)
    assert doc["exit"] == 21 and doc["steps"][1]["status"] == "stopped" and doc["next_command"]


def test_a_fault_listing_the_other_plans_is_exit_1_with_the_document(world, forge, person, monkeypatch, capsys):
    import json

    from l4.vcs.errors import GitError
    from l4.yolo import go

    no_model(monkeypatch)
    before = local_plan(world, {"docs/note.md": "a note\n"})

    def down(git, config=()):
        raise GitError(["git", "ls-remote"], 128, "fatal: unable to access origin\n")

    monkeypatch.setattr(go, "list_plans", down)
    calls = pushed(world, monkeypatch)
    assert world.l4("go", "p1", "--reason", "R", "--json") == 1
    doc = json.loads(capsys.readouterr().out)
    assert (
        doc["exit"] == 1
        and doc["steps"][1]["status"] == "stopped"
        and "cannot list the plans" in doc["steps"][1]["detail"]
    )
    assert doc["next_command"] == "l4 yolo go p1 --reason R --json"
    assert origin_main(world) == before and calls == []
