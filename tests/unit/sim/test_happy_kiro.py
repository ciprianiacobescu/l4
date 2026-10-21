import subprocess
from pathlib import Path

from l4.sim.builtin.manifest import scenario_text
from l4.sim.runner import run_scenario
from l4.sim.scenarios import fixture_root, load_scenario

SPEC = ".kiro/specs/user-greeting/tasks.md"
BRANCH = "l4/kiro/user-greeting"


def test_happy_kiro_passes_with_kiro_markers(tmp_path: Path):
    world = tmp_path / "world"
    result = run_scenario(load_scenario(scenario_text("happy-kiro")), root=world, keep=True)
    assert result.status == "pass", result.report
    assert (result.exit_code, result.final_phase) == (0, "in_review")

    started = [e["task"] for e in result.events if e["type"] == "task.started"]
    assert started == ["2.1", "1.1"]  # the wave-0 leaf first; the optional leaf 1.2 is never started
    assert [e["task"] for e in result.events if e["type"] == "task.done"] == ["2.1", "1.1"]

    show = subprocess.run(
        ["git", "-C", str(world / "remote.git"), "show", f"{BRANCH}:{SPEC}"], capture_output=True, check=True
    )
    seed = fixture_root("kiro-basic").joinpath("repo", SPEC).read_bytes()
    assert len(show.stdout) == len(seed)
    changed = [i for i, (a, b) in enumerate(zip(seed, show.stdout, strict=True)) if a != b]
    assert {show.stdout[i] for i in changed} == {ord("x")} and len(changed) == 4  # 2.1, 2, 1.1, 1: marker bytes only
    lines = show.stdout.decode().splitlines()
    boxes = [line.strip()[:5] for line in lines if line.strip().startswith("- [")]
    assert boxes == ["- [x]", "- [x]", "- [ ]", "- [x]", "- [x]"]  # both parents ticked, the optional leaf open
