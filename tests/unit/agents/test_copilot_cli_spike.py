"""The SPIKE adapter prototype `l4.agents.copilot_cli` (not registered) against streams recorded on Copilot CLI 1.0.102
in BYOK mode (a local OpenAI-compatible model, no GitHub account): docs/plan/proposal-copilot-cli.md."""

import json
from pathlib import Path

from l4.agents import copilot_cli
from l4.agents.base import PermissionPolicy, RunRequest
from l4.agents.copilot_cli import CopilotCliAdapter, build_command, parse, stream_facts, usage_of
from l4.agents.proc import ProcOutcome
from l4.config.schema import Profile

RECORDED = Path(__file__).parents[2] / "fixtures" / "recorded" / "copilot" / "1.0.102-byok"
PROFILE = Profile(adapter="copilot", model="claude-sonnet-5")
SCHEMA = {"type": "object", "required": ["status"], "properties": {"status": {"type": "string"}}}


def recorded(name: str) -> str:
    return (RECORDED / name).read_text(encoding="utf-8")


def request(tmp_path: Path, **kw) -> RunRequest:
    kw.setdefault("profile", PROFILE)
    kw.setdefault("prompt", "do the task")
    kw.setdefault("env", {"PATH": str(tmp_path / "bin")})
    (tmp_path / "bin").mkdir(exist_ok=True)
    exe = tmp_path / "bin" / "copilot"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    (tmp_path / "wt").mkdir(exist_ok=True)
    return RunRequest(
        role="implementer", cwd=tmp_path / "wt", result_path=tmp_path / "step" / "result.json",
        raw_events_path=tmp_path / "raw" / "events.jsonl", **kw,
    )  # fmt: skip


class FakeProc:
    def __init__(self, stdout: str = "") -> None:
        self.calls: list[dict] = []
        self.stdout = stdout

    def run(self, argv, env, cwd, *, stdout_path, timeout_s, stdin=None, stderr_path=None, **kw):
        self.calls.append({"argv": list(argv), "env": dict(env), "stdin": stdin, "cwd": cwd})
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stdout_path.write_text(self.stdout)
        return ProcOutcome(0)


def test_a_judge_gets_an_unknown_tool_name_never_an_empty_allow_list(tmp_path):
    """An empty `--available-tools` leaves every tool on 1.0.102 [V]: the judge names a tool that does not exist."""
    req = request(tmp_path, permission_policy=PermissionPolicy("judge"))
    argv = build_command(req, exe="copilot", session_id="s", usage_path=Path("u"))
    assert "--available-tools=l4_no_tools" in argv
    assert not any(a in ("--available-tools", "--available-tools=") for a in argv)
    assert not any(a.startswith("--allow") for a in argv)


def test_the_delegate_reads_only_and_the_implementer_runs_only_the_gate_binary(tmp_path):
    reader = build_command(
        request(tmp_path, permission_policy=PermissionPolicy("read_only")), exe="copilot", session_id="s",
        usage_path=Path("u"),
    )  # fmt: skip
    assert "--available-tools=view,grep,glob" in reader and not any(a.startswith("--allow") for a in reader)
    req = request(tmp_path, permission_policy=PermissionPolicy("implement", gate_prefix=".venv/bin/python -m pytest"))
    implementer = build_command(req, exe="copilot", session_id="s", usage_path=Path("u"))
    assert "--allow-tool=write" in implementer and "--allow-tool=shell(.venv/bin/python:*)" in implementer
    assert "--allow-all-tools" not in implementer and "--yolo" not in implementer
    assert implementer[implementer.index("--add-dir") + 1] == str(req.result_path.parent)


def test_every_run_is_isolated_and_reads_its_prompt_from_stdin(tmp_path):
    proc = FakeProc(recorded("implement-bash.jsonl"))
    req = request(tmp_path, env={"PATH": str(tmp_path / "bin"), "COPILOT_ALLOW_ALL": "true"})
    CopilotCliAdapter(proc).run(req)
    call = proc.calls[0]
    assert call["stdin"] == "do the task" and "do the task" not in call["argv"] and "-p" not in call["argv"]
    for flag in (
        "--no-ask-user",
        "--no-auto-update",
        "--no-custom-instructions",
        "--disable-builtin-mcps",
        "--disallow-temp-dir",
    ):
        assert flag in call["argv"]
    assert "COPILOT_ALLOW_ALL" not in call["env"]
    home = Path(call["env"]["COPILOT_HOME"])
    assert home.parent == req.result_path.parent
    assert json.loads((home / "settings.json").read_text())["includeCoAuthoredBy"] is False


def test_a_tool_less_judge_reply_is_parsed_with_its_served_model_and_session(tmp_path):
    out = parse(recorded("judge-hello.jsonl"), exit_code=0, raw_events_path=tmp_path / "e", mode="judge", schema=None)
    assert out.final_text == "L4-OK" and out.model_resolved == "qwen3.5:2b"
    assert out.session_id and out.status == "error"  # no JSON object in "L4-OK": the judge's repair path
    assert (out.detail or "").startswith("structured output missing")


def test_the_delegate_reply_comes_after_its_last_read(tmp_path):
    facts = stream_facts(copilot_cli.events(recorded("delegate-view.jsonl")))
    assert facts["tools"] == ["view"] and "hello" in facts["last_message"]
    out = parse(recorded("delegate-view.jsonl"), exit_code=0, raw_events_path=tmp_path / "e", mode="read_only")
    assert out.detail.startswith("structured output missing")  # the recorded reply holds no JSON object


def test_a_delegate_that_ran_a_non_read_tool_gives_no_reply(tmp_path):
    out = parse(recorded("implement-bash.jsonl"), exit_code=0, raw_events_path=tmp_path / "e", mode="read_only")
    assert out.status == "error" and "outside the read set (bash)" in out.detail and out.structured is None


def test_a_denied_call_is_a_permission_denial_not_a_failed_run(tmp_path):
    out = parse(recorded("implement-denied.jsonl"), exit_code=0, raw_events_path=tmp_path / "e")
    assert out.permission_denials == [{"tool_name": "bash"}]
    assert out.result_problem == "missing" and out.status == "ok"  # no schema, no result file: the gates decide


def test_the_result_file_decides_an_implementer_run(tmp_path):
    out = parse(
        recorded("implement-bash.jsonl"), exit_code=0, raw_events_path=tmp_path / "e",
        result_text='{"status": "green"}', schema=SCHEMA,
        usage_document=json.loads(recorded("implement-bash.usage.json")),
    )  # fmt: skip
    assert out.status == "ok" and out.structured == {"status": "green"}
    assert out.usage.input_tokens > 0 and out.usage.credits is None  # BYOK meters no AI credits


def test_error_shapes_map_to_statuses(tmp_path):
    def run(name: str, **kw):
        return parse(recorded(name), exit_code=1, raw_events_path=tmp_path / "e", **kw)

    assert run("error-401.jsonl").status == "auth"
    quota = run("error-402.jsonl")
    assert quota.status == "quota" and quota.limit.kind == "credits"
    server = run("error-500.jsonl")
    assert server.status == "error" and server.transient and server.api_status == 500
    # a 429 is retried by the CLI itself (Retry-After honoured): the run is stopped from outside
    limited = parse(recorded("error-429-retrying.jsonl"), exit_code=142, raw_events_path=tmp_path / "e", timed_out=True)
    assert limited.status == "rate_limited" and limited.limit.kind == "rate_limit"


def test_no_credential_is_an_auth_failure_with_no_stream(tmp_path):
    stderr = "Error: No authentication information found.\n\nCopilot can be authenticated with GitHub ..."
    out = parse("", exit_code=1, raw_events_path=tmp_path / "e", stderr_text=stderr)
    assert out.status == "auth" and "COPILOT_GITHUB_TOKEN" in out.detail


def test_usage_counts_tokens_and_ai_credits_never_dollars():
    doc = {"totalNanoAiu": 2_500_000_000, "modelMetrics": {"m": {"usage": {"inputTokens": 10, "outputTokens": 2}}}}
    usage = usage_of(doc)
    assert (usage.input_tokens, usage.output_tokens, usage.credits, usage.cost_usd) == (10, 2, 2.5, None)
    assert usage_of(None).input_tokens == 0


def test_the_prototype_is_not_registered():
    from l4.agents.factory import ADAPTERS
    from l4.config.roles import HARNESS_ADAPTERS

    assert "copilot" not in ADAPTERS and "copilot" not in HARNESS_ADAPTERS
