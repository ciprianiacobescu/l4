"""Preflight, M1.6 (plan line 30): `verifier.s1.shadow` names profiles that exist and are System-One profiles."""

import pytest

from l4.config.preflight import preflight_run_config
from l4.exitcodes import ExitCode, L4Exit

from ..llm.test_agent_judge_roles import app, cfg
from ..llm.test_preflight_m15 import s1_profile

GOOD = {"engine": "remote", "base_url": "http://s1.test"}


def config(shadow):
    return cfg(**s1_profile(**GOOD), verifier={"s1": {"shadow": shadow}})


def refused(tmp_path, shadow, needle):
    with pytest.raises(L4Exit) as err:
        preflight_run_config(app(tmp_path), config(shadow))
    assert err.value.code == ExitCode.USAGE_ERROR and needle in str(err.value)


def test_a_shadow_name_that_is_not_defined_is_refused_with_the_name(tmp_path):
    needle = "verifier.s1.shadow names a profile that is not defined under profiles: laya-typo"
    refused(tmp_path, ["s1", "laya-typo"], needle)


def test_a_shadow_name_that_is_not_a_system_one_profile_is_refused(tmp_path):
    refused(tmp_path, ["claude-c"], "verifier.s1.shadow: claude-c is not a backend: system-one profile")


def test_system_one_profiles_and_an_empty_list_pass(tmp_path):
    preflight_run_config(app(tmp_path), config(["s1"]))
    preflight_run_config(app(tmp_path), config([]))
