"""A custom OpenAI-compatible provider for an opencode profile (magnitude, 2026-10-06 investigation): the generated
config carries a provider block whose key is a `{file:...}` reference, the key itself travels in a 0600 file in the
step's private directory, and nothing credential-like enters the sandbox environment or the config text."""

import json
import re
import stat
from pathlib import Path

import pytest

from l4.agents.base import AdapterError, PermissionPolicy, RunRequest
from l4.agents.opencode import OpenCodeAdapter
from l4.agents.proc import ProcOutcome
from l4.config.schema import Profile

RECORDED = Path(__file__).parents[2] / "fixtures" / "recorded" / "opencode" / "1.18.33"


def request(tmp_path: Path, **kw) -> RunRequest:
    kw.setdefault("role", "implementer")
    kw.setdefault("profile", Profile(adapter="opencode", model="opencode/big-pickle", vendor="unknown"))
    (tmp_path / "bin").mkdir(exist_ok=True)
    exe = tmp_path / "bin" / "opencode"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    return RunRequest(
        cwd=tmp_path / "wt", prompt="the prompt", result_path=tmp_path / "res" / "result.json",
        raw_events_path=tmp_path / "raw" / "events.jsonl", env={"PATH": str(tmp_path / "bin"), "HOME": "/h"}, **kw,
    )  # fmt: skip


class FakeProc:
    def __init__(self, stdout: str = "", outcome: ProcOutcome | None = None) -> None:
        self.stdout, self.outcome, self.calls = stdout, outcome or ProcOutcome(0), []

    def run(self, argv, env, cwd, *, stdout_path, timeout_s, stdin=None, stderr_path=None, interrupt=None,
            on_line=None, stall_timeout_s=None, watch=None, reader=None):  # fmt: skip
        self.calls.append({"argv": list(argv), "env": dict(env), "cwd": cwd, "stdin": stdin})
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stdout_path.write_text(self.stdout)
        return self.outcome


def config_of(env: dict[str, str]) -> dict:
    return json.loads(env["OPENCODE_CONFIG_CONTENT"])


MODEL = "qwen3.6-35b-a3b:gguf:q5"
KEY = "sk-magnitude-test-0123456789abcdef"
OPTIONS = {
    "provider": {
        "id": "magnitude", "base_url": "http://192.0.2.10:10100/inference/v1", "api_key_env": "MAGNITUDE_API_KEY",
        "models": {MODEL: {"context": 262144, "output": 16384}},
    },
    "tools": ["bash", "edit", "write", "read", "glob", "grep"],
    "reasoning": "none",
}  # fmt: skip
MAG = Profile(adapter="opencode", model=f"magnitude/{MODEL}", auth="api_key", vendor="alibaba", options=OPTIONS)
HOST_ENV = {"MAGNITUDE_API_KEY": KEY, "PATH": "/usr/bin"}


class SpyProc(FakeProc):
    """Reads the key file at the moment the agent would start, because the adapter removes it afterwards."""

    def run(self, argv, env, cwd, **kw):
        config = json.loads(env["OPENCODE_CONFIG_CONTENT"])
        ref = next(iter(config.get("provider", {}).values()), {}).get("options", {}).get("apiKey", "")
        match = re.fullmatch(r"\{file:(.+)\}", ref)
        self.key_file = Path(match.group(1)) if match else None
        self.key_text = self.key_file.read_text() if self.key_file else None
        self.key_mode = stat.S_IMODE(self.key_file.stat().st_mode) if self.key_file else None
        return super().run(argv, env, cwd, **kw)


def run_mag(tmp_path, policy=None, **kw):
    proc = SpyProc((RECORDED / "hello-ok-stdin-prompt.jsonl").read_text())
    req = request(
        tmp_path, profile=MAG, host_env=HOST_ENV, permission_policy=policy or PermissionPolicy("implement"), **kw
    )
    result = OpenCodeAdapter(proc).run(req)
    return proc, req, result


def test_the_provider_block_references_the_key_file_and_carries_the_model_entry(tmp_path):
    proc, req, _ = run_mag(tmp_path)
    config = config_of(proc.calls[0]["env"])
    block = config["provider"]["magnitude"]
    assert block["npm"] == "@ai-sdk/openai-compatible"
    assert block["options"]["baseURL"] == "http://192.0.2.10:10100/inference/v1"
    assert block["options"]["apiKey"] == f"{{file:{proc.key_file}}}"
    entry = block["models"][MODEL]
    assert entry["tool_call"] is True and entry["limit"] == {"context": 262144, "output": 16384}
    assert entry["options"] == {"reasoningEffort": "none"}
    assert proc.key_file.parent.is_relative_to(tmp_path / "res")  # inside the step's private, mounted directory


def test_the_key_is_in_a_0600_file_only_and_is_removed_after_the_run(tmp_path):
    proc, req, _ = run_mag(tmp_path)
    assert proc.key_text == KEY and proc.key_mode == 0o600
    assert not proc.key_file.exists()
    call = proc.calls[0]
    assert KEY not in json.dumps(call["env"]) and KEY not in " ".join(call["argv"])
    assert "MAGNITUDE_API_KEY" not in call["env"]  # the variable never enters the agent environment
    assert KEY not in json.dumps(req.env)


def test_the_key_file_is_removed_when_the_run_raises(tmp_path):
    class Boom(SpyProc):
        def run(self, *a, **kw):
            super().run(*a, **kw)
            raise RuntimeError("spawn failed")

    proc = Boom("")
    with pytest.raises(RuntimeError):
        OpenCodeAdapter(proc).run(request(tmp_path, profile=MAG, host_env=HOST_ENV))
    assert not proc.key_file.exists()


def test_implement_mode_is_restricted_to_the_declared_tools(tmp_path):
    proc, *_ = run_mag(tmp_path)
    config = config_of(proc.calls[0]["env"])
    assert config["tools"] == {"*": False, **{t: True for t in ("bash", "edit", "write", "read", "glob", "grep")}}
    assert config["permission"]["bash"]["git push*"] == "deny"  # the permission rules are unchanged


def test_judge_mode_has_no_tools_but_still_gets_the_provider(tmp_path):
    proc, *_ = run_mag(tmp_path, PermissionPolicy("judge"), role="judge")
    config = config_of(proc.calls[0]["env"])
    assert config["tools"] == {"*": False} and config["permission"] == {"*": "deny"}
    assert "magnitude" in config["provider"]


def test_a_missing_key_variable_is_a_named_adapter_error_not_a_leak(tmp_path):
    with pytest.raises(AdapterError, match="MAGNITUDE_API_KEY") as caught:
        OpenCodeAdapter(FakeProc("")).run(request(tmp_path, profile=MAG, host_env={"PATH": "/x"}))
    assert KEY not in str(caught.value)


def test_a_profile_without_a_provider_is_unchanged(tmp_path):
    proc = FakeProc((RECORDED / "hello-ok-stdin-prompt.jsonl").read_text())
    OpenCodeAdapter(proc).run(request(tmp_path))
    config = config_of(proc.calls[0]["env"])
    assert "provider" not in config and "tools" not in config
    assert list((tmp_path / "res" / "opencode-config").iterdir()) == []


def test_grammar_binding_failure_is_a_distinct_retryable_error():
    event = json.dumps({"type": "error", "error": {"name": "APIError", "data": {
        "message": "HTTP 400: invalid request: grammar binding failed: parser error: Too many items (limit 50000)",
        "statusCode": 400}}})  # fmt: skip
    result = OpenCodeAdapter().parse([event], exit_code=1, raw_events_path=Path("x"), model=f"magnitude/{MODEL}")
    assert result.status == "error"
    assert "provider_unavailable" in (result.detail or "") and "retryable" in (result.detail or "")
    assert "grammar" in (result.detail or "")


def test_a_plain_400_stays_a_generic_error():
    event = json.dumps({"type": "error", "error": {"name": "APIError", "data": {"message": "bad", "statusCode": 400}}})
    result = OpenCodeAdapter().parse([event], exit_code=1, raw_events_path=Path("x"))
    assert "provider_unavailable" not in (result.detail or "")


def test_dry_run_request_has_no_host_env_by_default(tmp_path):
    assert request(tmp_path).host_env == {}


def test_stall_outcome_still_removes_the_key(tmp_path):
    proc = SpyProc("", ProcOutcome(1, stalled=True))
    OpenCodeAdapter(proc).run(request(tmp_path, profile=MAG, host_env=HOST_ENV))
    assert not proc.key_file.exists()


class ModeSpy(FakeProc):
    """Records, while the agent would run, the modes of the step directory, `opencode-config`, the key file and the
    credential-loader file (all are gone afterwards)."""

    def __init__(self, req_dir: Path, *args, boom: bool = False, **kw):
        super().__init__(*args, **kw)
        self.req_dir, self.boom, self.modes = req_dir, boom, {}

    def run(self, argv, env, cwd, **kw):
        mode = lambda p: stat.S_IMODE(p.stat().st_mode) if p.exists() else None  # noqa: E731
        self.modes = {
            "step": mode(self.req_dir), "config": mode(self.req_dir / "opencode-config"),
            "key": mode(self.req_dir / "opencode-config" / "provider.key"),
            "credential": mode(self.req_dir / "credential"),
        }  # fmt: skip
        out = super().run(argv, env, cwd, **kw)
        if self.boom:
            raise RuntimeError("spawn failed")
        return out


GO = Profile(adapter="opencode", model="opencode-go/deepseek-v4.1-flash", auth="api_key", vendor="deepseek")


def test_private_dirs_are_0700_and_no_key_outlives_the_step(tmp_path):  # SCN-PRV-101
    for boom in (False, True):
        for profile, env in ((MAG, HOST_ENV), (GO, {"OPENCODE_API_KEY": "sk-go-loader-value", "PATH": "/usr/bin"})):
            work = tmp_path / f"{boom}-{profile.model.split('/')[0]}"
            work.mkdir()
            proc = ModeSpy(work / "res", (RECORDED / "hello-ok-stdin-prompt.jsonl").read_text(), boom=boom)
            req = request(work, profile=profile, host_env=env)
            if boom:
                with pytest.raises(RuntimeError):
                    OpenCodeAdapter(proc).run(req)
            else:
                OpenCodeAdapter(proc).run(req)
            assert proc.modes["step"] == 0o700 and proc.modes["config"] == 0o700
            assert proc.modes["key" if profile is MAG else "credential"] == 0o600
            assert not (work / "res" / "opencode-config" / "provider.key").exists()
            assert not (work / "res" / "credential").exists()
