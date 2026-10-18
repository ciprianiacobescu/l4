# ruff: noqa: F811
"""Review fixes of plan-run-lessons: the key is read from the plan's own target branch (N1), a limit is finite (N2),
the extensions listed are the ones the fold applied (N7), the next line follows the answer step (N7)."""

import math
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import l4.yolo.commands as commands
from l4.cli import main
from l4.exitcodes import L4Exit
from l4.planner import UnitFacts
from l4.yolo.state import fold_plan

from .test_yolo_commands_manage import agent_env, resume, runs_world, tty  # noqa: F401
from .test_yolo_commands_waive import ID1, REASON, activated
from .yolo_cmd_world import ev, forge, world  # noqa: F401


def evil_config(world, key_yaml: str) -> Path:
    """An agent pushes its own branch `evil` whose `.l4/config.yaml` turns a key on (the base branch does not) and a
    CLI config that names `evil` as the base branch."""
    g = world.clone
    world.pull()
    g.run("checkout", "-q", "-b", "evil")
    cfg = Path(world.app.repo) / ".l4" / "config.yaml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(key_yaml, encoding="utf-8")
    g.run("add", "-f", ".l4/config.yaml")
    g.run("commit", "-q", "-m", "agents may (not on the base branch)")
    g.run("push", "-q", "origin", "evil")
    g.run("checkout", "-q", "main")
    doc = yaml.safe_load(Path(world.app.config_path).read_text(encoding="utf-8"))
    doc["forge"]["base_branch"] = "evil"
    out = Path(world.root) / "evil-config.yaml"
    out.write_text(yaml.safe_dump(doc), encoding="utf-8")
    return out


def test_n1_an_agent_cannot_point_the_base_branch_at_its_own_branch_to_extend(world, monkeypatch, capsys):
    tty(monkeypatch, False)
    agent_env(world)
    runs_world(world)
    assert "a person's decision" in resume(world, capsys, "--extend-runs", "50")  # control
    cfg = evil_config(world, "yolo:\n  extend_by_agents: true\n")
    before = world.kinds()
    args = ["yolo", "resume", "p1", "--reason", "more", "--extend-runs", "50", "--repo", str(world.app.repo),
            "--config", str(cfg)]  # fmt: skip
    code = main(args, environ=dict(world.app.environ))
    err = capsys.readouterr().err
    assert code == 2 and "a person's decision" in err and "differs from the plan's target" in err
    assert world.kinds() == before and fold_plan("p1", world.events()).extended.runs == 0


def test_n1_an_agent_cannot_point_the_base_branch_at_its_own_branch_to_waive(world, monkeypatch, capsys):
    from .test_yolo_commands_accept import agent

    activated(world)
    agent(world, monkeypatch)
    cfg = evil_config(world, "yolo:\n  review:\n    accept_by_agents: true\n")
    args = ["yolo", "waive", "p1", ID1, "--reason", REASON, "--yes", "--no-run", "--repo", str(world.app.repo),
            "--config", str(cfg)]  # fmt: skip
    assert main(args, environ=dict(world.app.environ)) == 2
    assert "differs from the plan's target" in capsys.readouterr().err
    assert "plan.finding_waived" not in world.kinds()


def test_n1_the_key_on_the_plans_own_target_still_lets_an_agent_extend(world, monkeypatch):
    tty(monkeypatch, False)
    agent_env(world)
    runs_world(world)
    world.push({".l4/config.yaml": "yolo:\n  extend_by_agents: true\n"}, "agents may extend")
    assert world.l4("resume", "p1", "--reason", "more", "--extend-runs", "20") == 0
    assert world.events()[-1].data["agent_key"] is True


@pytest.mark.parametrize("value", ["nan", "inf", "-inf"])
def test_n2_a_cost_that_is_not_finite_is_refused(world, monkeypatch, capsys, value):
    tty(monkeypatch)
    runs_world(world)
    before = world.kinds()
    assert world.l4("resume", "p1", "--reason", "x", "--extend-cost", value) == 2
    assert "finite" in capsys.readouterr().err and world.kinds() == before


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_n2_extend_itself_refuses_a_cost_that_is_not_finite(value):
    with pytest.raises(L4Exit) as caught:
        commands._extend(value, None, None, None)
    assert "finite" in str(caught.value)


def test_n7_the_extensions_listed_are_the_ones_the_fold_applied():
    def extended(n):
        return ev("plan.extended", by="a", actor="person", reason=str(n), extend={"runs": n},
                  limits_before={}, limits_after={})  # fmt: skip

    activated_ev = ev("plan.activated", plan_digest="x", digests={}, by="a", reason="go", limits={"max_runs": 9})
    events = [extended(100), activated_ev, extended(5), ev("plan.stopped", reason="limit_runs"), activated_ev,
              extended(3), ev("plan.cancelled", by="a"), extended(7)]  # fmt: skip
    listed = commands._extensions(events)
    assert [x["reason"] for x in listed] == ["5", "3"]  # a re-activation keeps them, a cancel ends them, none before
    assert sum(x["extend"]["runs"] for x in listed) == fold_plan("p1", events).extended.runs == 8


def test_n7_the_next_line_of_a_waiting_plan_follows_the_answer_step():
    state = fold_plan("p1", [ev("plan.activated", plan_digest="x", digests={}, limits={}, by="a")])
    state.status, state.current, state.wait_reason = "waiting", "openspec:add-b", "unit_awaiting_human"
    fix = "fix the answer of Q-004 in openspec/changes/add-b/questions.md on l4/openspec/add-b: start it with accept"
    line = commands._next_line("p1", state, None, None, unit_phase="awaiting_human", answer_fix=fix)
    assert fix in line and "--replace" in line and "continues by itself" in line
    plain = commands._next_line("p1", state, None, None, unit_phase="awaiting_human")
    assert "--replace" not in plain and "l4 questions answer Q-NNN" in plain


def _facts(**over) -> UnitFacts:
    base = {
        "unit": "openspec:add-b",
        "framework": "openspec",
        "phase": "awaiting_human",
        "tasks_done": 0,
        "tasks_total": 1,
    }
    return UnitFacts(**{**base, **over})


@pytest.mark.parametrize(
    "facts",
    [
        {"verdicts_invalid": ("Q-004",)},
        {"verdicts_dismissed": ("Q-004",)},
        {"drafts": ("Q-004",), "open_blocking_questions": ("Q-004",)},
    ],
)
def test_n7_the_answer_fix_of_a_unit_comes_from_the_answer_step(monkeypatch, facts):
    snap = SimpleNamespace(ref=SimpleNamespace(id="openspec:add-b", path=Path("/r/openspec/changes/add-b")))
    monkeypatch.setattr(commands, "facts_of", lambda s: _facts(**facts))
    fix = commands.answer_fix_of(snap, Path("/r"), "l4/")
    assert "Q-004" in fix and "--replace" in fix
    monkeypatch.setattr(commands, "facts_of", lambda s: _facts())
    assert commands.answer_fix_of(snap, Path("/r"), "l4/") == ""


# ---- round 2, R1: a plan file rewritten on the caller's own branch is never trusted ---------------------------------


def real_runs_world(world, used=82, limit=90):
    """An active plan whose activation records the real digest of the plan file on main, as `l4 yolo activate` does."""
    import json as _json  # noqa: F401

    from l4.yolo.digest import plan_digest

    from .yolo_cmd_world import A, B

    world.push_plan()
    digest = plan_digest(world.plan_text)
    activated = ev("plan.activated", plan_digest=digest, digests={}, by="alex@example.com", reason="go",
                   limits={"max_runs": limit, "max_unit_attempts": 2})  # fmt: skip
    charge = ev("plan.charged", unit=A, attempt=1, cost_usd=1.0, runs=used)
    admitted = ev("plan.admitted", plan_digest=digest, order=[A, B])
    world.seed("p1", admitted, world.reviewed(), activated, ev("unit.dispatched", unit=A), charge)


def evil_branch_with_plan(world, key_yaml: str) -> Path:
    """The agent's branch `evil`: the key on, and the plan file p1 rewritten to name `evil` as its target."""
    import json as _json

    g = world.clone
    world.pull()
    g.run("checkout", "-q", "-b", "evil")
    root = Path(world.app.repo)
    (root / ".l4").mkdir(exist_ok=True)
    (root / ".l4" / "config.yaml").write_text(key_yaml, encoding="utf-8")
    plan_file = root / ".l4" / "plans" / "p1.json"
    doc = _json.loads(plan_file.read_text(encoding="utf-8"))
    doc["target"] = "evil"
    plan_file.write_text(_json.dumps(doc, indent=2), encoding="utf-8")
    g.run("add", "-f", ".l4/config.yaml", ".l4/plans/p1.json")
    g.run("commit", "-q", "-m", "the plan targets my branch")
    g.run("push", "-q", "origin", "evil")
    g.run("checkout", "-q", "main")
    cfg = yaml.safe_load(Path(world.app.config_path).read_text(encoding="utf-8"))
    cfg["forge"]["base_branch"] = "evil"
    out = Path(world.root) / "evil-config.yaml"
    out.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return out


def test_r1_an_agent_cannot_rewrite_the_plan_target_on_its_own_branch(world, monkeypatch, capsys):
    tty(monkeypatch, False)
    agent_env(world)
    real_runs_world(world)
    assert "a person's decision" in resume(world, capsys, "--extend-runs", "50")  # control
    cfg = evil_branch_with_plan(world, "yolo:\n  extend_by_agents: true\n")
    before = world.kinds()
    args = ["yolo", "resume", "p1", "--reason", "more", "--extend-runs", "50", "--repo", str(world.app.repo),
            "--config", str(cfg)]  # fmt: skip
    code = main(args, environ=dict(world.app.environ))
    err = capsys.readouterr().err
    assert code == 2 and "a person's decision" in err and "differs from the digest" in err
    assert world.kinds() == before


def test_r1_the_recorded_plan_file_still_lets_an_agent_with_the_key_extend(world, monkeypatch):
    tty(monkeypatch, False)
    agent_env(world)
    real_runs_world(world)
    world.push({".l4/config.yaml": "yolo:\n  extend_by_agents: true\n"}, "agents may extend")
    assert world.l4("resume", "p1", "--reason", "more", "--extend-runs", "20") == 0
    assert world.events()[-1].data["agent_key"] is True
