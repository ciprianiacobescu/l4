import pytest

from l4.config.preflight import preflight_run_config
from l4.exitcodes import ExitCode, L4Exit

from .test_agent_judge_roles import app, cfg, roles


def test_preflight_refuses_a_verifier_agent_chain_that_names_an_undefined_profile(tmp_path):
    with pytest.raises(L4Exit) as err:
        preflight_run_config(app(tmp_path), cfg(**roles(verifier_agent=["nope"])))
    assert err.value.code == ExitCode.USAGE_ERROR and "roles.verifier_agent" in str(err.value)
    assert "nope" not in str(err.value)
    preflight_run_config(app(tmp_path), cfg(**roles(verifier_agent=["claude-s"])))
    preflight_run_config(app(tmp_path), cfg(**roles()))  # an empty chain turns step 4a off
