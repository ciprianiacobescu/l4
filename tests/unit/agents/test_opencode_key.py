"""L4-PRV-028 (SCN-PRV-77): OpenCode's own key reaches the run through the credential loader only."""

import os
import stat
from pathlib import Path

import pytest

from l4.agents.credentials import credential_variable, hosted_login_problem, profile_credential_variable
from l4.agents.gate import refreshable_login
from l4.agents.opencode import OpenCodeAdapter
from l4.config.defaults import DEFAULT_REDACT_ENV
from l4.config.schema import Profile
from l4.provision.readiness import provider_steps

from .test_opencode import FakeProc, request

SECRET = "oc-test-VALUE-123"
GO = Profile(adapter="opencode", model="opencode-go/deepseek-v4.1-flash", auth="api_key", vendor="deepseek")
CUSTOM = Profile(
    adapter="opencode", model="opencode-go/qwen", auth="api_key", vendor="alibaba",
    options={"provider": {
        "id": "opencode-go", "base_url": "http://10.0.0.5:10100/v1", "api_key_env": "MAGNITUDE_API_KEY",
        "models": {"qwen": {"context": 32768, "output": 4096}},
    }},
)  # fmt: skip


class SpyProc(FakeProc):
    """Reads the credential file while the (fake) process runs: that is when the loader would."""

    def run(self, argv, env, cwd, **kw):
        self.seen = {}
        if argv[:2] == ["/bin/sh", "-c"]:
            path = argv[4]
            self.seen = {"mode": stat.S_IMODE(os.stat(path).st_mode), "value": Path(path).read_text(), "path": path}
        return super().run(argv, env, cwd, **kw)


def test_the_run_argv_is_the_loader_with_the_name_only(tmp_path):
    proc = SpyProc()
    req = request(tmp_path, profile=GO)
    object.__setattr__(req, "host_env", {"OPENCODE_API_KEY": SECRET})
    OpenCodeAdapter(proc).run(req)
    (call,) = proc.calls
    argv = call["argv"]
    assert argv[:2] == ["/bin/sh", "-c"] and "export OPENCODE_API_KEY=" in argv[2]
    assert argv[5].endswith("opencode") and "run" in argv
    assert SECRET not in " ".join(argv) and all(SECRET not in v for v in call["env"].values())
    assert "OPENCODE_API_KEY" not in call["env"]
    assert proc.seen["value"] == SECRET and proc.seen["mode"] == 0o600
    assert not os.path.exists(proc.seen["path"])  # removed after the run


def test_without_the_key_the_argv_is_the_plain_command(tmp_path):
    proc = SpyProc()
    OpenCodeAdapter(proc).run(request(tmp_path, profile=GO))
    assert proc.calls[0]["argv"][1] == "run"


def test_a_free_model_and_a_custom_provider_run_without_the_loader(tmp_path):
    free = Profile(adapter="opencode", model="opencode/big-pickle", vendor="unknown")
    proc = SpyProc()
    req = request(tmp_path, profile=free)
    object.__setattr__(req, "host_env", {"OPENCODE_API_KEY": SECRET})
    OpenCodeAdapter(proc).run(req)
    assert proc.calls[0]["argv"][1] == "run"


@pytest.mark.parametrize(
    ("profile", "variable"),
    [
        (GO, "OPENCODE_API_KEY"),
        (GO.model_copy(update={"model": "opencode/big-pickle"}), "OPENCODE_API_KEY"),
        (GO.model_copy(update={"auth": "subscription"}), None),
        (GO.model_copy(update={"auth": None}), None),
        (GO.model_copy(update={"model": "google/gemini-3.5-flash"}), None),
        (GO.model_copy(update={"model": "opencode-gold/x"}), None),
        (CUSTOM, None),
        (Profile(adapter="codex", auth="api_key"), "CODEX_API_KEY"),
        (Profile(adapter="claude-code", auth="subscription"), "CLAUDE_CODE_OAUTH_TOKEN"),
    ],
)
def test_profile_credential_variable(profile, variable):
    assert profile_credential_variable(profile) == variable
    assert credential_variable("opencode", "api_key") is None  # the profile-less form is unchanged


def test_no_login_lock_hosted_problem_redaction_and_steps():
    assert refreshable_login(GO) is False
    assert hosted_login_problem("opencode", "api_key") is None
    assert "OPENCODE_API_KEY" in DEFAULT_REDACT_ENV
    github = provider_steps(GO, platform="github", environment="l4")
    assert github == ("run `l4 setup github --secret OPENCODE_API_KEY=<ENV>` (the value comes from your environment)",)
    assert "masked CI variable OPENCODE_API_KEY" in provider_steps(GO)[0]
    free = Profile(adapter="opencode", model="opencode/big-pickle", vendor="unknown")
    assert provider_steps(free) == ()
