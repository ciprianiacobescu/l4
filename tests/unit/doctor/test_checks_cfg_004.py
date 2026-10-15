"""CFG-004: an empty `gates.test.command` makes every unit `rejected` at run time (no test oracle); doctor says so."""

import pytest

from l4.config.schema import L4Config
from l4.doctor import checks_config as cc
from l4.doctor.registry import CONFIG_SCOPES, REGISTRY


def cfg(command: str | None) -> L4Config:
    return L4Config() if command is None else L4Config.model_validate({"gates": {"test": {"command": command}}})


@pytest.mark.parametrize("command", [None, "", "   "])
def test_an_empty_or_missing_test_command_fails_with_a_fix_hint(make_ctx, command):
    ctx, _ = make_ctx(cfg=cfg(command))
    result = cc._cfg_004(ctx)
    assert result.status == "fail"
    assert "gates.test.command" in result.message and "rejected" in result.message
    assert result.fix_hint is not None and "gates.test.command" in result.fix_hint and "\n" not in result.fix_hint


def test_a_test_command_passes(make_ctx):
    ctx, _ = make_ctx(cfg=cfg("pytest -q"))
    assert cc._cfg_004(ctx).status == "pass"


def test_it_is_an_error_that_runs_on_a_laptop_and_in_ci():
    check = {c.id: c for c in REGISTRY.checks()}["CFG-004"]
    assert check.severity == "error" and check.scopes >= CONFIG_SCOPES
