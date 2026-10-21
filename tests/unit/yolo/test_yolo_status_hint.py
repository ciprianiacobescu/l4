"""`l4 yolo status` names the delegate while it is off (delegate-answers 26.1; L4-DLG-021; SCN-DLG-71/72/73)."""

import json

import yaml

import l4.yolo.commands as commands
from l4.delegate.hint import hint_text

from . import yolo_cmd_world
from .test_yolo_status_delegate import A, activate, ev

HINT = hint_text("main")
world, forge = yolo_cmd_world.world, yolo_cmd_world.forge  # the fixtures of the world


def waiting(monkeypatch, kinds=("technical",), phase="awaiting_human"):
    real = commands._read_units

    def fake(ctx, rev, wanted, *, intake):
        units = real(ctx, rev, wanted, intake=intake)
        units.phases[A] = phase
        units.open_kinds[A] = tuple(kinds)
        return units

    monkeypatch.setattr(commands, "_read_units", fake)


def base_delegate(world, **delegate) -> None:
    config = yaml.safe_load((world.root / "sim-config.yaml").read_text())
    config["delegate"] = delegate
    world.push({".l4/config.yaml": yaml.safe_dump(config)})
    world.clone.run("fetch", "--quiet", "origin")


def test_the_hint_follows_next(world, capsys, monkeypatch):  # SCN-DLG-71
    activate(world, ev("unit.dispatched", unit=A, run="r1"))
    waiting(monkeypatch)
    base_delegate(world, scope="yolo")
    assert world.l4("status", "p1") == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[-1] == HINT and lines[-2].startswith("Next:")
    assert world.l4("status", "p1", "--json") == 0
    assert json.loads(capsys.readouterr().out)["plans"][0]["delegate_hint"] == HINT


def test_no_hint_while_on_or_for_other_phases_and_kinds(world, capsys, monkeypatch):  # SCN-DLG-72
    activate(world, ev("unit.dispatched", unit=A, run="r1"))
    waiting(monkeypatch)
    base_delegate(world, enabled=True)
    assert world.l4("status", "p1", "--json") == 0
    assert json.loads(capsys.readouterr().out)["plans"][0]["delegate_hint"] is None
    base_delegate(world, scope="yolo", kinds=["verdict"])
    assert world.l4("status", "p1") == 0
    assert "Hint:" not in capsys.readouterr().out


def test_no_hint_for_a_unit_that_does_not_wait(world, capsys):
    activate(world, ev("unit.dispatched", unit=A, run="r1"))
    base_delegate(world, scope="yolo")
    assert world.l4("status", "p1") == 0
    assert "Hint:" not in capsys.readouterr().out
