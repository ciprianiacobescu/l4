"""state-vcs-locks 1.29 end to end on a real bare remote: a run killed by SIGKILL twice, then a run that finishes."""

from pathlib import Path

from l4.agents.base import PermissionPolicy, RunRequest
from l4.config.schema import Profile
from l4.sim.builtin.manifest import scenario_text
from l4.sim.fakes import ScriptedAgent
from l4.sim.runner import run_scenario
from l4.sim.scenarios import Kill, Step, load_scenario
from l4.vcs.git import Git

UNIT_BRANCH = "l4/openspec/add-greeting"
TASKS = "openspec/changes/add-greeting/tasks.md"


def remote_git(root: Path) -> Git:
    return Git(root / "remote.git", environ={"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"})


def commits(remote: Git, *grep: str) -> list[str]:
    args = [f"--grep={g}" for g in grep]
    return remote.run("log", "--all-match", "--format=%H", *args, f"main..{UNIT_BRANCH}").stdout.split()


def test_crash_resume_flow(tmp_path):
    scenario = load_scenario(scenario_text("crash-mid-task-resume"))
    result = run_scenario(scenario, keep=True, root=tmp_path / "world")
    assert result.status == "pass", result.report
    remote = remote_git(tmp_path / "world")
    # one green commit per task, and one red: nothing lost or doubled by the two kills
    for task in ("1.1", "1.2"):
        for phase in ("red", "green"):
            assert len(commits(remote, f"L4-Step: {task}/{phase}/1")) == 1, (task, phase)
    assert len(commits(remote, "L4-TDD: green")) == 2
    types = [e["type"] for e in result.events]
    # run 2 restored the snapshot of the killed green 1.1; a step that finished normally leaves no stale snapshot to
    # reconcile, and the kill between red 1.2 and its first snapshot left nothing to find (the single-commit
    # assertions above are what show red 1.2 was not redone)
    reconciled = [e for e in result.events if e["type"] == "step.reconciled"]
    assert [(e["action"], e["step"]) for e in reconciled] == [("restore_wip", "1.1/green/1")]
    # the killed runs' uncommitted ledger tails are dropped, not read back as a planted ledger
    assert "guard.violation" not in types
    # `task.done` is inside the green commit, so no kill can lose it (the events are read from the pushed branch)
    assert sorted(e["task"] for e in result.events if e["type"] == "task.done") == ["1.1", "1.2"]
    # each marker is ticked once, and nothing else in tasks.md changed
    ticked = remote.run("show", f"{UNIT_BRANCH}:{TASKS}").stdout
    seed = remote.run("show", f"main:{TASKS}").stdout
    assert ticked.count("- [x] 1.1") == 1 and ticked.count("- [x] 1.2") == 1
    assert ticked.replace("[x]", "[ ]") == seed
    assert "[~]" not in ticked and "[-]" not in ticked


def test_kill_is_ignored_unless_the_agent_is_a_numbered_child_run(tmp_path):
    """An in-process run (no run number) must never be able to SIGKILL the test runner."""
    work = tmp_path / "work"
    work.mkdir()
    req = RunRequest(
        profile=Profile(adapter="fake"), role="implementer", cwd=work, prompt="# Task 1.1\n\n# Phase: RED (x)\n",
        result_path=tmp_path / "r.json", raw_events_path=tmp_path / "e.jsonl", env={},
        permission_policy=PermissionPolicy("implement"),
    )  # fmt: skip
    agent = ScriptedAgent([Step(kill=Kill(run=1, at="start"))])
    assert agent.run(req).status == "ok"


def test_kill_at_the_start_of_green_resumes_at_green_not_red(tmp_path):
    """SIGKILL between the red commit and the first WIP snapshot of green: the red commit alone must be enough to
    resume (SPEC L4-STA-003, 'else re-run the step'). Red must not run a second time."""
    text = scenario_text("crash-mid-task-resume")
    text = text.replace("kill: {run: 1, at: end, after_s: 3}", "kill: {run: 1, at: start}")
    text = text.replace("max_runs: 3", "max_runs: 4")
    line = "    - {type: step.reconciled, action: restore_wip}\n"
    assert line in text
    text = text.replace(line, "")  # run 1 died before any snapshot: there is nothing to restore
    scenario = load_scenario(text)
    result = run_scenario(scenario, keep=True, root=tmp_path / "world")
    assert result.status == "pass", result.report
    remote = remote_git(tmp_path / "world")
    for task in ("1.1", "1.2"):
        for phase in ("red", "green"):
            assert len(commits(remote, f"L4-Step: {task}/{phase}/1")) == 1, (task, phase)
    red_ok = [e for e in result.events if e["type"] == "task.red_ok" and e["task"] == "1.1"]
    assert len(red_ok) == 1  # a resumed run records `task.red_resumed`, it does not prove red again
    assert any(e["type"] == "task.red_resumed" and e["task"] == "1.1" for e in result.events)
