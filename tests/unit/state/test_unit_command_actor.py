# ruff: noqa: F811
"""L4-OPS-025: `l4 retry`, `l4 resume` and `l4 restart` record who ran them (`actor`, `marker`) in `unit.retried`,
`unit.resumed` and `unit.restarted`; the sweep's label (`by: member`) and a spec-edit push (`by: push`) record none.
SCN-OPS-54 and -55."""

import l4
from l4.cli import main
from l4.config.redaction import load_app_config
from l4.exitcodes import ExitCode
from l4.specs.providers import providers_for
from l4.state.retry import retry_unit
from l4.state.status import refresh_refs, select_runnable
from l4.vcs.git import Git

from .ops_world import UNIT, escalate, events, failing_reds, happy, world  # noqa: F401
from .test_restart import forge, poisoned  # noqa: F401


def run_command(world, name, *extra):
    argv = [name, "--unit", UNIT, "--reason", "why", "--no-run" if name != "resume" else "--no-fetch"]
    if name == "resume":
        argv.pop()
    argv += ["--repo", str(world.app.repo), "--config", str(world.app.config_path), *extra]
    return main(argv, environ=dict(world.app.environ))


def person_at_a_terminal(monkeypatch):
    monkeypatch.setattr("l4.actor._stdin_tty", lambda: True)


def of(world, kind):
    return [e for e in events(world.remote) if e["type"] == kind][-1]


def test_scn_ops_54_a_persons_and_an_agents_retry_record_their_kind(world, monkeypatch):
    person_at_a_terminal(monkeypatch)
    assert world.run(failing_reds()).code == ExitCode.HALTED
    assert run_command(world, "retry") == 0
    retried = of(world, "unit.retried")
    assert (retried["actor"], retried["marker"]) == ("person", None) and retried["reason"] == "why"
    started = [e for e in events(world.remote) if e["type"] == "run.started"][-1]
    assert started["harness_version"] == l4.__version__  # SCN-OPS-57: the run records the harness that ran it
    assert world.run(failing_reds()).code == ExitCode.HALTED  # halted again
    world.app.environ["CLAUDECODE"] = "1"
    assert run_command(world, "retry") == 0
    retried = of(world, "unit.retried")
    assert (retried["actor"], retried["marker"]) == ("agent", "CLAUDECODE")


def test_scn_ops_54_a_resume_records_its_kind(world, monkeypatch):
    person_at_a_terminal(monkeypatch)
    assert world.run(failing_reds()).code == ExitCode.HALTED
    assert run_command(world, "resume") == 0
    resumed = of(world, "unit.resumed")
    assert (resumed["actor"], resumed["marker"]) == ("person", None)
    assert "unit.retried" not in [e["type"] for e in events(world.remote)]


def test_scn_ops_54_a_restart_records_its_kind_and_an_agent_without_a_terminal(world, forge, monkeypatch):
    monkeypatch.setattr("l4.actor._stdin_tty", lambda: False)
    poisoned(world, forge)
    assert run_command(world, "restart") == 0
    restarted = of(world, "unit.restarted")
    assert (restarted["actor"], restarted["marker"]) == ("agent", None) and restarted["reason"] == "why"


def test_scn_ops_54_the_phase_after_a_retry_is_the_one_of_0459(world, monkeypatch):
    person_at_a_terminal(monkeypatch)
    assert world.run(failing_reds()).code == ExitCode.HALTED
    assert run_command(world, "retry") == 0
    changes = [(e["from"], e["to"]) for e in events(world.remote) if e["type"] == "phase.changed"]
    assert changes[-1] == ("halted", "implementing")


def test_scn_ops_55_a_label_and_a_spec_edit_record_no_actor(world):
    assert world.run(failing_reds()).code == ExitCode.HALTED
    app, cfg = load_app_config(world.app)
    git = Git(app.repo, environ=app.environ)
    refresh_refs(app, cfg, git)
    provider, ref = select_runnable(cfg, git, list(providers_for(cfg, app.repo, app.environ)), UNIT)
    retry_unit(app, cfg, git, provider, ref, reason="label l4:retry", by="member", signal="label:7")
    retried = of(world, "unit.retried")
    assert retried["by"] == "member" and "actor" not in retried and "marker" not in retried
