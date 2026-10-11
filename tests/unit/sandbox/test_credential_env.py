"""L4-PRV-024 (SCN-PRV-69): only the step profile's credential variable reaches its agent, and never through argv.

A value given to bwrap with `--setenv` lands in bwrap's argv. The adapter writes it to a 0600 file in the step's private
directory and prefixes the agent argv with a `/bin/sh` loader that reads and deletes the file inside the sandbox."""

import stat
import subprocess
from pathlib import Path

import pytest

from l4.agents.base import AdapterError, RunRequest
from l4.agents.claude_code import ClaudeCodeAdapter
from l4.agents.codex import CodexAdapter
from l4.agents.credentials import credential_variable, loader_argv
from l4.agents.kiro_cli import KiroCliAdapter
from l4.agents.proc import ProcOutcome
from l4.config.schema import Profile
from l4.sandbox.bwrap import BwrapSandbox

KIRO_VALUE = "kiro-VALUE-0123456789"
CODEX_VALUE = "codex-VALUE-9876543210"
HOST = {"KIRO_API_KEY": KIRO_VALUE, "CODEX_API_KEY": CODEX_VALUE, "PATH": "/usr/bin"}
KIRO = Profile(adapter="kiro-cli", model="claude-sonnet-4", vendor="anthropic", options={"agent": "l4"})


class SpyProc:
    """Reads the credential file when the agent would start (the adapter removes it afterwards)."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    def run(self, argv, env, cwd, *, stdout_path, timeout_s, stdin=None, stderr_path=None, **kw):
        loader = argv.index("l4-credential") if "l4-credential" in argv else None
        file = Path(argv[loader + 1]) if loader is not None else None
        # the file path is the argument after the loader's `$0` (behind bwrap's own flags)
        self.calls.append(
            {
                "argv": list(argv), "env": dict(env), "file": file,
                "text": file.read_text() if file and file.exists() else None,
                "mode": stat.S_IMODE(file.stat().st_mode) if file and file.exists() else None,
            }
        )  # fmt: skip
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stdout_path.write_text("")
        return ProcOutcome(0)


def request(tmp_path: Path, make_spec, tool: str, profile: Profile, host_env=HOST, wrapped=True) -> RunRequest:
    (tmp_path / "bin").mkdir(exist_ok=True)
    exe = tmp_path / "bin" / tool
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    spec = make_spec("agent", adapter=profile.adapter, tmp_dir=tmp_path / "res")
    (tmp_path / "res").mkdir(exist_ok=True)
    sandbox = BwrapSandbox("/usr/bin/bwrap", host_root=Path("/nonexistent-l4-host-root"))
    return RunRequest(
        role="implementer", profile=profile, cwd=spec.worktree, prompt="do the task",
        result_path=tmp_path / "res" / "result.json", raw_events_path=tmp_path / "raw" / "events.jsonl",
        env={"PATH": str(tmp_path / "bin"), "HOME": str(spec.home)}, host_env=host_env,
        wrap=(lambda argv, env, cwd=None: sandbox.wrap(argv, spec, env, cwd)) if wrapped else None,
    )  # fmt: skip


def test_only_the_profiles_variable_enters_its_sandbox(tmp_path, make_spec):
    req = request(tmp_path, make_spec, "kiro-cli", KIRO)
    proc = SpyProc()
    KiroCliAdapter(proc).run(req)
    [call] = proc.calls
    everything = " ".join(call["argv"]) + " ".join(call["env"].values())
    assert KIRO_VALUE not in everything and CODEX_VALUE not in everything  # no value in bwrap's argv or env
    assert "CODEX_API_KEY" not in everything and "KIRO_API_KEY" in everything  # the loader names one variable
    assert any('export KIRO_API_KEY="$v"' in part for part in call["argv"])
    assert "--setenv" not in call["argv"] or "KIRO_API_KEY" not in call["argv"]  # never `--setenv KIRO_API_KEY <v>`
    assert call["text"] == KIRO_VALUE and call["mode"] == 0o600  # it existed, private, during the run
    assert call["file"].parent == tmp_path / "res"  # in the step's private (bound) directory
    assert not call["file"].exists()  # and is gone after
    assert KIRO_VALUE not in repr(req) and "KIRO_API_KEY" not in req.env


def test_the_credential_file_is_removed_when_the_run_raises(tmp_path, make_spec):
    class Boom(SpyProc):
        def run(self, *a, **kw):
            super().run(*a, **kw)
            raise RuntimeError("spawn failed")

    proc = Boom()
    with pytest.raises(RuntimeError):
        KiroCliAdapter(proc).run(request(tmp_path, make_spec, "kiro-cli", KIRO))
    assert not proc.calls[0]["file"].exists()


def _profile(adapter: str, auth: str, vendor: str) -> Profile:
    return Profile(adapter=adapter, model="m", auth=auth, vendor=vendor)


@pytest.mark.parametrize(
    ("adapter", "tool", "profile", "variable"),
    [
        (ClaudeCodeAdapter, "claude", _profile("claude-code", "subscription", "anthropic"), "CLAUDE_CODE_OAUTH_TOKEN"),
        (ClaudeCodeAdapter, "claude", _profile("claude-code", "api_key", "anthropic"), "ANTHROPIC_API_KEY"),
        (CodexAdapter, "codex", _profile("codex", "api_key", "openai"), "CODEX_API_KEY"),
        (KiroCliAdapter, "kiro-cli", _profile("kiro-cli", "api_key", "anthropic"), "KIRO_API_KEY"),
    ],
)
def test_each_adapter_loads_its_own_variable(tmp_path, make_spec, adapter, tool, profile, variable):
    value = "v-" + variable
    proc = SpyProc()
    adapter(proc).run(request(tmp_path, make_spec, tool, profile, host_env={**HOST, variable: value}))
    [call] = proc.calls
    assert call["text"] == value and f'export {variable}="$v"' in " ".join(call["argv"])
    assert value not in " ".join(call["argv"])


def test_codex_on_a_subscription_never_gets_an_api_key(tmp_path, make_spec):
    profile = Profile(adapter="codex", model="m", auth="subscription", vendor="openai")
    proc = SpyProc()
    CodexAdapter(proc).run(request(tmp_path, make_spec, "codex", profile))
    [call] = proc.calls
    assert call["file"] is None and CODEX_VALUE not in " ".join(call["argv"])


def test_without_the_variable_the_argv_is_unchanged(tmp_path, make_spec):
    proc = SpyProc()
    req = request(
        tmp_path, make_spec, "kiro-cli", KIRO, host_env={"PATH": "/usr/bin", "KIRO_API_KEY": "  "}, wrapped=False
    )
    KiroCliAdapter(proc).run(req)
    [call] = proc.calls
    assert call["argv"][0] == str(tmp_path / "bin" / "kiro-cli") and call["file"] is None
    assert not list((tmp_path / "res").glob("credential*"))


def test_the_variables_per_profile():
    assert credential_variable("claude-code", None) == "CLAUDE_CODE_OAUTH_TOKEN"
    assert credential_variable("claude-code", "subscription") == "CLAUDE_CODE_OAUTH_TOKEN"
    assert credential_variable("claude-code", "api_key") == "ANTHROPIC_API_KEY"
    assert credential_variable("codex", "api_key") == "CODEX_API_KEY"
    assert credential_variable("codex", "subscription") is None and credential_variable("codex", None) is None
    assert credential_variable("kiro-cli", "subscription") == "KIRO_API_KEY"
    assert credential_variable("kiro-cli", "api_key") == "KIRO_API_KEY"
    assert credential_variable("opencode", "api_key") is None and credential_variable("command", None) is None


def test_the_loader_name_is_checked_before_it_is_put_in_shell_text(tmp_path):
    with pytest.raises(AdapterError) as err:
        loader_argv('X"; rm -rf ~; "', tmp_path / "c", ["true"])
    assert "rm" not in str(err.value)


def test_the_loader_delivers_the_variable_and_removes_the_file(tmp_path):
    """The loader text runs for real under /bin/sh (no bwrap): the child sees the variable, argv and the file do not."""
    value_file = tmp_path / "credential"
    value_file.write_text(KIRO_VALUE)
    argv = loader_argv(
        "KIRO_API_KEY", value_file, ["/bin/sh", "-c", 'printf "%s %s" "${#KIRO_API_KEY}" "$#"', "x", "y"]
    )
    assert KIRO_VALUE not in " ".join(argv)
    done = subprocess.run(argv, env={"PATH": "/usr/bin:/bin"}, capture_output=True, text=True, timeout=20, check=False)
    assert done.returncode == 0 and done.stdout == f"{len(KIRO_VALUE)} 1"
    assert not value_file.exists()


def test_the_loader_fails_closed_when_the_file_is_missing(tmp_path):
    argv = loader_argv("KIRO_API_KEY", tmp_path / "missing", ["/bin/sh", "-c", "echo ran"])
    done = subprocess.run(argv, env={"PATH": "/usr/bin:/bin"}, capture_output=True, text=True, timeout=20, check=False)
    assert done.returncode == 97 and "ran" not in done.stdout
