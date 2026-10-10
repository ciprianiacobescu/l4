"""`l4 resume` for a halted unit (SCN-RES-01, state-vcs-locks 5.8 and 5.12, reduced)."""

import pytest
import yaml

from l4.cli import main
from l4.exitcodes import ExitCode, L4Exit
from l4.orchestrator import run_command
from l4.sim.builtin.manifest import scenario_text
from l4.sim.fakes import ProfileRouter, fake_openspec_cli
from l4.sim.remote import SimRepo
from l4.sim.runner import CONFIG_FILE, _events, scripted_agents, sim_app, sim_config, sim_environment
from l4.sim.scenarios import load_scenario
from l4.state.resume import run_resume
from l4.vcs.git import Git

UNIT = "openspec:add-greeting"
BRANCH = "l4/openspec/add-greeting"


def happy():
    return load_scenario(scenario_text("happy-openspec"), source="happy-openspec.yaml")


def failing_reds():
    """Three red steps that add no test: `max_task_attempts` is reached and the breaker halts the unit."""
    scenario = happy()
    steps = scenario.profiles["implementer"].steps
    dud = steps[0].model_copy(update={"write": {}})
    scenario.profiles["implementer"].steps = [dud, dud, dud]
    return scenario


@pytest.fixture
def world(tmp_path):
    sim = SimRepo.create("openspec-basic", root=tmp_path / "world")
    root = sim.root.resolve()
    (root / CONFIG_FILE).write_text(yaml.safe_dump(sim_config(happy())), encoding="utf-8")
    app = sim_app(root)
    remote = Git(sim.remote, environ=sim_environment(root))

    def run(scenario):
        with fake_openspec_cli():
            router = ProfileRouter(scripted_agents(scenario))
            return run_command(sim_app(root), adapters={"fake": router})

    return app, remote, run


def events(remote: Git) -> list[dict]:
    """The unit branch's ledger plus the pending ledger of its lock ref, as `l4 status` folds them."""
    return _events(remote, UNIT, "openspec/changes/add-greeting", "l4/")


def test_member_resumes_breaker_halt(world):
    app, remote, run = world
    assert run(failing_reds()).code == ExitCode.HALTED
    assert any(e["type"] == "phase.changed" and e["to"] == "halted" for e in events(remote))

    result = run_resume(app, unit=UNIT, reason="spec clarified")
    assert result.code == ExitCode.OK and result.units[0].phase_after == "implementing"
    log = events(remote)
    [resumed] = [e for e in log if e["type"] == "unit.resumed"]
    assert resumed["reason"] == "spec clarified"
    [back] = [e for e in log if e["type"] == "phase.changed" and e["trigger"] == "resumed"]
    assert (back["from"], back["to"], back["trigger"]) == ("halted", "implementing", "resumed")
    # pushed: a chore commit with the unit's trailers on the remote branch
    subject = remote.run("log", "-1", "--format=%s", BRANCH).stdout.strip()
    assert subject == "chore(add-greeting): resume [skip ci]"
    # and the next run carries on to review
    assert run(happy()).code == ExitCode.OK
    assert any(e["type"] == "phase.changed" and e["trigger"] == "hand_off_pushed" for e in events(remote))


def test_resume_refuses_a_unit_that_is_not_halted(world):
    app, _, run = world
    run(happy())
    with pytest.raises(L4Exit, match="in_review, not halted") as caught:
        run_resume(app, unit=UNIT, reason="again")
    assert caught.value.code == ExitCode.USAGE_ERROR


def test_resume_extensions_are_not_yet(world):
    app, _, _ = world
    with pytest.raises(L4Exit, match="--extend-iterations and --extend-cost not yet implemented"):
        run_resume(app, unit=UNIT, reason="more", extend_cost=20.0)
    with pytest.raises(L4Exit, match="--extend-iterations and --extend-cost not yet implemented"):
        run_resume(app, unit=UNIT, reason="more", extend_iterations=5)


def test_resume_refuses_a_fix_round_extension_for_a_halted_unit(world):
    """M1.13 line 17: a halted unit has no fix rounds to extend (a unit escalated after the fix rounds does)."""
    app, remote, run = world
    assert run(failing_reds()).code == ExitCode.HALTED
    with pytest.raises(L4Exit, match="halted, not escalated") as caught:
        run_resume(app, unit=UNIT, reason="more", extend_fix_rounds=1)
    assert caught.value.code == ExitCode.USAGE_ERROR
    assert not any(e["type"] in ("unit.resumed", "budget.extended") for e in events(remote))
    with pytest.raises(L4Exit, match="at least 1"):
        run_resume(app, unit=UNIT, reason="more", extend_fix_rounds=0)


def test_cli_resume_flags_delegate(world, capsys):
    app, remote, run = world
    run(failing_reds())
    argv = ["resume", "--unit", UNIT, "--reason", "why", "--repo", str(app.repo), "--config", str(app.config_path)]
    assert main(argv, environ=dict(app.environ)) == 0
    assert "unit.resumed" not in capsys.readouterr().err  # nothing alarming; the effect is in the ledger
    assert any(e["type"] == "unit.resumed" and e["reason"] == "why" for e in events(remote))


def test_resume_needs_no_sandbox(world, monkeypatch):
    """W2 (a): the config says `sandbox.mode: auto` and no bwrap exists, yet the resume (which runs no agent and no
    gate) takes the unit out of `halted` and pushes the resume commit."""
    app, remote, run = world
    assert run(failing_reds()).code == ExitCode.HALTED
    config = yaml.safe_load(app.config_path.read_text(encoding="utf-8"))
    config["sandbox"] = {"mode": "auto"}
    app.config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    monkeypatch.setattr("l4.sandbox.select.resolve_tool", lambda *a, **k: None)
    result = run_resume(app, unit=UNIT, reason="no sandbox here")
    assert result.code == ExitCode.OK and result.units[0].phase_after == "implementing"
    assert remote.run("log", "-1", "--format=%s", BRANCH).stdout.strip() == "chore(add-greeting): resume [skip ci]"
    with fake_openspec_cli():  # and `l4 run` of the same config still refuses without a sandbox
        again = sim_app(app.config_path.parent)
        refused = run_command(again, adapters={"fake": ProfileRouter(scripted_agents(happy()))})
    assert refused.code == ExitCode.DOCTOR_FAILED
