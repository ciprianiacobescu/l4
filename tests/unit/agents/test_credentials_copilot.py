"""L4-PRV-049 (SCN-PRV-136): the Copilot token reaches a run through the credential loader only. Fake values only."""

import os
import stat
from pathlib import Path

import pytest

from l4.agents.base import RunRequest
from l4.agents.credentials import credential_loader, credential_variable, hosted_login_problem
from l4.agents.gate import OAUTH_ADAPTERS
from l4.config.schema import Profile

TOKEN = "github_pat_" + "x" * 40  # a placeholder built at run time, never a real token
PROFILE = Profile(adapter="copilot-cli", model="claude-sonnet-5.5", auth="api_key", vendor="anthropic")


@pytest.mark.parametrize("auth", [None, "subscription", "api_key"])
def test_the_credential_variable_is_the_same_under_every_auth(auth):
    assert credential_variable("copilot-cli", auth) == "COPILOT_GITHUB_TOKEN"
    assert hosted_login_problem("copilot-cli", auth) is None


def test_copilot_is_not_an_oauth_adapter():
    assert "copilot-cli" not in OAUTH_ADAPTERS


def _request(tmp_path: Path, host_env: dict[str, str]) -> RunRequest:
    step = tmp_path / "step"
    step.mkdir()
    return RunRequest(
        profile=PROFILE, role="implementer", cwd=tmp_path, prompt="p", result_path=step / "result.json",
        raw_events_path=step / "events.jsonl", env={"PATH": "/usr/bin"}, host_env=host_env,
    )  # fmt: skip


def test_the_loader_goes_in_front_of_the_argv_and_the_value_stays_in_a_file(tmp_path):  # SCN-PRV-136
    req = _request(tmp_path, {"COPILOT_GITHUB_TOKEN": TOKEN})
    with credential_loader(req) as load:
        argv = load(["copilot", "--version"])
        assert argv[:2] == ["/bin/sh", "-c"] and 'export COPILOT_GITHUB_TOKEN="$v"' in argv[2]
        assert argv[-2:] == ["copilot", "--version"]
        assert TOKEN not in " ".join(argv) and "COPILOT_GITHUB_TOKEN" not in req.env
        value_file = Path(argv[4])
        assert value_file.read_text() == TOKEN and stat.S_IMODE(os.stat(value_file).st_mode) == 0o600
    assert not value_file.exists()  # the credential does not outlive the step
    assert TOKEN not in repr(req)


def test_without_the_variable_the_argv_is_unchanged(tmp_path):
    req = _request(tmp_path, {"GH_TOKEN": TOKEN, "GITHUB_TOKEN": TOKEN})  # forge tokens are never the credential
    with credential_loader(req) as load:
        assert load(["copilot", "-p", "x"]) == ["copilot", "-p", "x"]
