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


def test_a_wrong_major_is_an_error_and_not_an_unrecorded_version(make_ctx):  # SCN-OCG-05
    ctx, _ = make_ctx(tools={"opencode": "opencode v2.0.32"}, cfg=L4Config.model_validate(CFG))
    result, code = outcome(ctx)
    assert (result.status, result.severity) == ("fail", "error") and int(code) == 3  # the report is not ok
    assert "opencode 2.0.32 is OpenCode v2; this profile runs v1" in result.message
    assert "install opencode-ai@1.18.34" in result.message
    assert "unrecorded version" not in result.message


def test_a_v1_patch_drift_still_only_warns_and_the_report_is_ok(make_ctx):  # SCN-OCG-05
    ctx, _ = make_ctx(tools={"opencode": "1.18.35"}, cfg=L4Config.model_validate(CFG))
    result, code = outcome(ctx)
    assert (result.status, result.severity) == ("fail", "warn") and int(code) == 0
    assert "unrecorded version" in result.message


def test_a_v2_behind_a_word_character_is_an_error(make_ctx):
    ctx, _ = make_ctx(tools={"opencode": "opencode_2.0.32"}, cfg=L4Config.model_validate(CFG))
    result, code = outcome(ctx)
    assert (result.status, result.severity) == ("fail", "error") and int(code) == 3
    assert "is OpenCode v2; this profile runs v1" in result.message


def test_live_005_makes_a_kiro_cli_3_an_error(make_ctx):  # SCN-OCG-12
    cfg = L4Config.model_validate(
        {
            "profiles": {"kiro": {"adapter": "kiro-cli", "model": "auto"}},
            "roles": {"implementer": ["kiro"], "judges": ["kiro"]},
            "ci": {"cli_versions": {"kiro-cli": "2.28.0"}},
        }
    )
    ctx, _ = make_ctx(tools={"kiro-cli": "kiro-cli 3.0.0"}, cfg=cfg)
    result, code = outcome(ctx)
    assert (result.status, result.severity) == ("fail", "error") and int(code) == 3
    assert "kiro-cli 3.0.0 is Kiro CLI 3; L4 runs Kiro CLI 2: install kiro-cli 2.28.0" in result.message
    assert "unrecorded version" not in result.message
