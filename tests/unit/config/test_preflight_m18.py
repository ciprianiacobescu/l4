"""A7 (M1.8): the preflight text for `clarifier.s1_standin: llm_boolean` names the role and says what step 8 needs."""

import pytest

from l4.config.preflight import preflight_run_config
from l4.config.schema import L4Config
from l4.exitcodes import ExitCode, L4Exit

from ..llm.test_agent_judge_roles import app


def config(**roles) -> L4Config:
    return L4Config.model_validate(
        {
            "profiles": {"a": {"adapter": "fake", "vendor": "x"}, "b": {"adapter": "fake", "vendor": "y"}},
            "roles": {"implementer": ["a"], "judges": ["b"], **roles},
            "clarifier": {"s1_standin": "llm_boolean"},
        }
    )


def test_llm_boolean_message_names_the_role_and_step8(tmp_path):
    with pytest.raises(L4Exit) as err:
        preflight_run_config(app(tmp_path), config())
    assert err.value.code == ExitCode.USAGE_ERROR
    text = str(err.value)
    assert "clarifier.s1_standin is llm_boolean" in text and "roles.s1_judge is empty" in text
    assert "adapter profile" in text and "step 8" in text and "backend: system-one" in text


def test_llm_boolean_with_an_adapter_profile_passes(tmp_path):
    preflight_run_config(app(tmp_path), config(s1_judge=["a"]))
