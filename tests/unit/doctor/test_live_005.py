"""HB-17: LIVE-005 warns when a head profile's CLI version has no recorded fixtures (SCN-FAC-14)."""

import pytest

from l4 import recordedversions
from l4.config.schema import L4Config
from l4.doctor import checks_agents as agents
from l4.doctor.registry import Check, Registry, exit_code, run_checks

CFG = {
    "profiles": {"oc": {"adapter": "opencode", "model": "m", "vendor": "unknown"}, "fake": {"adapter": "fake"}},
    "roles": {"implementer": ["oc"], "judges": ["oc"], "clarifier": ["fake"]},
}


@pytest.fixture(autouse=True)
def recorded(monkeypatch):
    monkeypatch.setattr(recordedversions, "load", lambda: {"opencode": ["1.18.33"]})


def outcome(ctx):
    registry = Registry()
    registry.register(Check("LIVE-005", "recorded versions", "warn", agents._live_005, frozenset({"live"})))
    (result,) = run_checks(ctx, registry=registry, live=True)
    return result, exit_code([result])


def test_a_newer_patch_version_warns_and_names_both_versions(make_ctx):
    ctx, _ = make_ctx(tools={"opencode": "1.18.34"}, cfg=L4Config.model_validate(CFG))
    result, code = outcome(ctx)
    assert (result.status, result.severity) == ("fail", "warn") and int(code) == 0
    assert "unrecorded version" in result.message and "oc" in result.message
    assert "1.18.34" in result.message and "1.18.33" in result.message


def test_a_recorded_version_passes(make_ctx):
    ctx, _ = make_ctx(tools={"opencode": "1.18.33"}, cfg=L4Config.model_validate(CFG))
    result, _ = outcome(ctx)
    assert result.status == "pass"


def test_a_missing_binary_is_not_this_checks_business(make_ctx):
    ctx, _ = make_ctx(tools={}, cfg=L4Config.model_validate(CFG))
    result, _ = outcome(ctx)
    assert result.status == "pass"
