"""`run_scenario` drives the real orchestrator (M14-G4)."""

import subprocess
import sys
from pathlib import Path

import pytest

from l4.sim.builtin.manifest import scenario_text
from l4.sim.runner import run_scenario
from l4.sim.scenarios import load_scenario

# what only the real orchestrator and verifier write: a skeleton driver would not
REAL_EVENTS = {"lock.acquired", "availability.selected", "verify.step", "verify.judge", "prompt.rendered"}


def builtin(name: str):
    return load_scenario(scenario_text(name), source=f"{name}.yaml")


def test_happy_openspec_reaches_in_review_with_the_real_orchestrator(tmp_path):
    result = run_scenario(builtin("happy-openspec"))
    assert result.status == "pass", result.report
    assert (result.exit_code, result.final_phase, result.driver) == (0, "in_review", "orchestrator")
    types = [e["type"] for e in result.events]
    assert set(types) >= REAL_EVENTS
    # red before green, per task, by event order
    order = [(e["task"], e["type"]) for e in result.events if e["type"] in ("task.red_ok", "task.done")]
    assert order == [("1.1", "task.red_ok"), ("1.1", "task.done"), ("1.2", "task.red_ok"), ("1.2", "task.done")]


def test_the_world_is_removed_unless_kept(tmp_path):
    world = tmp_path / "world"
    run_scenario(builtin("happy-openspec"), root=world)
    assert not world.exists()
    run_scenario(builtin("happy-openspec"), root=world, keep=True)
    assert (world / "remote.git").is_dir() and (world / "clone").is_dir()


def test_only_git_and_fixture_gates_are_spawned(monkeypatch):
    spawned: list[tuple[str, ...]] = []
    real = subprocess.Popen

    class Spy(real):  # type: ignore[valid-type, misc]
        def __init__(self, args, *a, **k):
            spawned.append(tuple(args) if not isinstance(args, str) else (args,))
            super().__init__(args, *a, **k)

    monkeypatch.setattr(subprocess, "Popen", Spy)
    assert run_scenario(builtin("happy-openspec")).status == "pass"
    programs = {Path(argv[0]).name for argv in spawned}
    assert programs == {"git", Path(sys.executable).name}, programs
    gates = [argv for argv in spawned if Path(argv[0]).name != "git"]
    assert gates and all(argv[1:] == ("tests/run_junit.py",) for argv in gates)


def test_a_step_the_script_does_not_have_fails_the_scenario_loudly():
    scenario = builtin("happy-openspec")
    scenario.profiles["implementer"].steps.pop(0)  # nothing for red 1.1
    result = run_scenario(scenario)
    assert result.status == "fail"
    assert "no scripted step matches phase='red' task='1.1'" in result.report


def test_an_expectation_mismatch_prints_the_diff_and_the_nearest_event():
    scenario = builtin("happy-openspec")
    scenario.expect.final_phase = "escalated"
    scenario.expect.events_include = [{"type": "task.done", "task": "9.9"}]
    result = run_scenario(scenario)
    assert result.status == "fail"
    assert "final_phase: expected 'escalated', actual 'in_review'" in result.report
    assert "events_include[0]" in result.report and "closest event of that type" in result.report


@pytest.mark.parametrize("name", ["happy-kiro", "stuck-human-answers", "stuck-clarifier-answers"])
def test_every_ready_builtin_passes(name):
    result = run_scenario(builtin(name))
    assert result.status == "pass", result.report


def test_an_s1_that_disagrees_sends_the_clarified_question_to_a_human():
    scenario = builtin("stuck-clarifier-answers")
    assert scenario.s1 is not None
    scenario.s1.default_p = 0.0  # S1 calls it a product decision and finds the citation unconvincing
    scenario.expect.exit_code, scenario.expect.final_phase = 11, "awaiting_human"
    scenario.expect.events_include = [{"type": "clarifier.result", "auto_accepted": False}]
    result = run_scenario(scenario)
    assert result.status == "pass", result.report
