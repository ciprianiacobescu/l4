"""The tool-less Kiro judge (kiro-judge 3.1): harness agent, private KIRO_HOME, stdin transport, `--model auto`."""

import json
from pathlib import Path

import pytest

from l4.agents.base import AdapterError, PermissionPolicy, RunRequest
from l4.agents.kiro_cli import JUDGE_SETTINGS, TRUST_TOOLS, KiroCliAdapter
from l4.agents.proc import ProcOutcome
from l4.config.schema import Profile
from l4.llm.agent_judge import AgentJudge
from l4.verifier.judge import JUDGE_SCHEMA, run_judge

from ..verifier.test_judge_run import PROMPT

FIXTURE = Path(__file__).parents[2] / "fixtures" / "recorded" / "kiro-cli" / "2.32.0"
SONNET = Profile(adapter="kiro-cli", model="claude-sonnet-4.5", vendor="anthropic")
NO_MODEL = Profile(adapter="kiro-cli")


class RecordingProc:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def run(self, argv, env, cwd, *, stdout_path, timeout_s, stdin=None, stderr_path=None, **kw):
        home = env.get("KIRO_HOME")
        snapshot = None
        if home:
            snapshot = {
                str(p.relative_to(home)): (p.read_text(encoding="utf-8") if p.is_file() else None)
                for p in sorted(Path(home).rglob("*"))
            }
        self.calls.append(
            {"argv": list(argv), "env": dict(env), "stdin": stdin, "cwd": Path(cwd), "home_files": snapshot}
        )
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stdout_path.write_text("")
        return ProcOutcome(0)


def request(tmp_path: Path, profile: Profile, mode: str = "judge", prompt: str = "judge this", **kw) -> RunRequest:
    (tmp_path / "bin").mkdir(exist_ok=True)
    exe = tmp_path / "bin" / "kiro-cli"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    env = {"PATH": str(tmp_path / "bin"), **kw.pop("env", {})}
    return RunRequest(
        role="judge" if mode == "judge" else "implementer", cwd=tmp_path / "wt",
        result_path=tmp_path / "res" / "result.json", raw_events_path=tmp_path / "raw" / "events.jsonl", env=env,
        profile=profile, prompt=prompt, permission_policy=PermissionPolicy(mode), **kw,
    )  # fmt: skip


def run(tmp_path: Path, profile: Profile, mode: str = "judge", **kw) -> dict:
    proc = RecordingProc()
    KiroCliAdapter(proc).run(request(tmp_path, profile, mode, **kw))
    return proc.calls[0]


def agent_name(argv: list[str]) -> str:
    return argv[argv.index("--agent") + 1]


def test_scn_kjd_01_the_judge_argv_names_the_harness_agent_and_no_trust_flag(tmp_path):
    call = run(tmp_path, SONNET)
    argv = call["argv"]
    name = agent_name(argv)
    assert name.startswith("l4-judge-") and len(name) == len("l4-judge-") + 12
    assert argv[1:] == [
        "chat", "--no-interactive", "--v2", "--agent", name, "--model", "claude-sonnet-4.5",
        "--output-format", "stream-json",
    ]  # fmt: skip
    assert not any(a.startswith("--trust-tools") or a == "--trust-all-tools" for a in argv)
    assert "judge this" not in argv


def test_scn_kjd_02_the_private_kiro_home_holds_only_the_agent_and_the_settings(tmp_path):
    leftover = tmp_path / "res" / "kiro-home" / "agents" / "old.json"
    leftover.parent.mkdir(parents=True)
    leftover.write_text("{}")
    first = run(tmp_path, SONNET)
    second = run(tmp_path, SONNET)
    for call in (first, second):
        name = agent_name(call["argv"])
        assert call["env"]["KIRO_HOME"] == str(tmp_path / "res" / "kiro-home")
        assert sorted(call["home_files"]) == sorted(["agents", f"agents/{name}.json", "settings", "settings/cli.json"])
        expected = json.loads((FIXTURE / "judge-agent.json").read_text(encoding="utf-8"))
        expected["name"] = name
        assert json.loads(call["home_files"][f"agents/{name}.json"]) == expected
        assert json.loads(call["home_files"]["settings/cli.json"]) == {
            "chat.disableInheritingDefaultResources": True, "chat.agentEngine": "v2",
            "chat.enableAutoAgentUpgrade": False, "app.disableAutoupdates": True,
        }  # fmt: skip
    assert JUDGE_SETTINGS["chat.agentEngine"] == "v2"
    assert agent_name(first["argv"]) != agent_name(second["argv"])


def test_scn_kjd_03_a_configured_agent_is_ignored_and_a_model_less_judge_runs_auto(tmp_path):
    mine = SONNET.model_copy(update={"options": {"agent": "my-agent"}})
    call = run(tmp_path, mine)
    assert agent_name(call["argv"]).startswith("l4-judge-") and "my-agent" not in call["argv"]
    assert not any(a.startswith("--trust") for a in call["argv"]) and "--v2" in call["argv"]
    assert "judge this" not in call["argv"] and call["stdin"] == "judge this"
    auto = run(tmp_path, NO_MODEL)
    argv = auto["argv"]
    assert argv.count("--model") == 1 and argv[argv.index("--model") + 1] == "auto"
    config = json.loads(auto["home_files"][f"agents/{agent_name(argv)}.json"])
    assert config["model"] == "auto"


def test_scn_kjd_04_a_large_judge_prompt_goes_on_stdin(tmp_path):
    prompt = "x" * 150_000
    call = run(tmp_path, SONNET, prompt=prompt, env={"KIRO_LOG_LEVEL": "trace"})
    assert call["stdin"] == prompt and not any(prompt in a for a in call["argv"])
    assert call["cwd"] == tmp_path / "res" / "judge-cwd" and call["cwd"].is_dir()
    assert "KIRO_HOME" in call["env"] and "KIRO_LOG_LEVEL" not in call["env"]


def test_an_empty_judge_prompt_is_refused_before_the_spawn(tmp_path):
    proc = RecordingProc()
    with pytest.raises(AdapterError, match="empty"):
        KiroCliAdapter(proc).run(request(tmp_path, SONNET, prompt=" \n"))
    assert proc.calls == []


def test_scn_kjd_05_the_implementer_keeps_the_argv_transport(tmp_path):
    with pytest.raises(AdapterError, match="argument"):
        KiroCliAdapter(RecordingProc()).run(request(tmp_path, SONNET, "implement", prompt="x" * 200_000))
    call = run(tmp_path, SONNET, "implement", prompt="0123456789")
    assert call["argv"][-1] == "0123456789" and call["stdin"] is None


def test_scn_kjd_30_a_profile_with_no_model_runs_auto_in_every_mode(tmp_path):
    for mode in ("implement", "judge"):
        argv = run(tmp_path, NO_MODEL, mode)["argv"]
        assert argv.count("--model") == 1 and argv[argv.index("--model") + 1] == "auto"
    implement = run(tmp_path, NO_MODEL, "implement")["argv"]
    assert implement.index("--model") < implement.index("--output-format") and implement[-1] == "judge this"
    read_only = run(tmp_path, NO_MODEL, "read_only")["argv"]
    assert read_only[read_only.index("--model") + 1] == "auto"
    shouting = Profile(adapter="kiro-cli", model="AUTO", options={"agent": "mine"})
    argv = run(tmp_path, shouting, "implement")["argv"]
    assert argv.count("--model") == 1 and argv[argv.index("--model") + 1] == "auto"
    assert argv[argv.index("--agent") + 1] == "mine" and argv[-1] == "judge this"
    judged = run(tmp_path, shouting)
    config = json.loads(judged["home_files"][f"agents/{agent_name(judged['argv'])}.json"])
    assert config["model"] == "auto"


def test_no_trust_list_exists_for_the_judge():
    assert "judge" not in TRUST_TOOLS


# --- task 4.1: parse a judge run (L4-KJD-003, L4-KJD-015) ---

PASS_LINES = (FIXTURE / "judge-pass.stream.jsonl").read_text(encoding="utf-8").splitlines()
SESSION = "20373329-a874-487e-8a01-8ddee2cdc356"
RAW = Path("events.jsonl")


def judge_parse(lines, *, model=None, home=None, stderr=None, exit_code=0):
    return KiroCliAdapter(RecordingProc()).parse(
        lines, exit_code=exit_code, raw_events_path=RAW, judge=True, schema=JUDGE_SCHEMA, kiro_home=home,
        model=model, stderr_text=stderr,
    )  # fmt: skip


def stream(final_text, *, stop="end_turn", truncated=False, chunks=(), engine="v2", extra=()):
    def event(kind, data):
        return json.dumps({"type": kind, "data": data})

    def chunk(text):
        update = {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": text}}
        return event("sessionUpdate", {"sessionId": SESSION, "update": update})

    finished = {"sessionId": SESSION, "status": "success", "stopReason": stop, "finalText": final_text}
    if truncated:
        finished["finalTextTruncated"] = True
    return [
        event("runStarted", {"payloadSchema": "acp", "acpProtocolVersion": 1, "engine": engine}),
        *extra, *(chunk(c) for c in chunks), event("runFinished", finished),
    ]  # fmt: skip


def session_file(home: Path, model_id: str, session: str = SESSION) -> Path:
    path = home / "sessions" / "cli" / f"{session}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"session_state": {"rts_model_state": {"model_info": {"model_id": model_id}}}}), encoding="utf-8"
    )
    return path


def test_scn_kjd_06_a_sentence_before_the_json_is_the_verdict():
    result = judge_parse(PASS_LINES)
    assert result.status == "ok" and result.structured["criteria"][0]["verdict"] == "pass"
    assert result.model_resolved is None and result.usage.credits == pytest.approx(0.0512)


def valid_reply() -> str:
    final = json.loads(PASS_LINES[-1])["data"]["finalText"]
    return final


def test_scn_kjd_07_a_reply_with_no_object_gets_one_repair_call():
    first = stream("I think criterion 1 passes", stop="max_tokens")
    scripted = ScriptedKiro([first, PASS_LINES])
    judge = AgentJudge(scripted, lambda prompt, schema, timeout: None)  # type: ignore[arg-type,return-value]
    run = run_judge(judge, PROMPT, timeout_s=60, redact=str)
    assert run.status == "ok" and run.calls == 2 and run.reply == "retried"
    assert "max_tokens" in scripted.parsed[0].detail and scripted.parsed[0].structured is None


class ScriptedKiro(KiroCliAdapter):
    def __init__(self, streams):
        super().__init__(RecordingProc())
        self.streams, self.parsed = list(streams), []

    def run(self, req):
        result = self.parse(self.streams.pop(0), exit_code=0, raw_events_path=RAW, judge=True, schema=JUDGE_SCHEMA)
        self.parsed.append(result)
        return result


def test_scn_kjd_08_a_truncated_final_text_falls_back_to_the_message_chunks():
    text = valid_reply()
    lines = stream("cut", truncated=True, chunks=[text[: len(text) // 2], text[len(text) // 2 :]])
    result = judge_parse(lines)
    assert result.status == "ok" and result.structured["criteria"][0]["id"] == "C-00000001"


def tool_call(name=None, title=None, kind="tool_call"):
    update = {"sessionUpdate": kind, "toolCallId": "t1"}
    if name:
        update["_meta"] = {"kiro": {"toolName": name}}
    if title:
        update["title"] = title
    return json.dumps({"type": "sessionUpdate", "data": {"sessionId": SESSION, "update": update}})


def test_scn_kjd_09_a_tool_call_another_engine_or_another_model_is_never_a_verdict(tmp_path):
    reply = valid_reply()
    called = judge_parse(stream(reply, extra=[tool_call("read")]))
    assert (called.status, called.detail, called.structured) == ("error", "kiro-cli judge called a tool (read)", None)
    titled = judge_parse(stream(reply, extra=[tool_call(title="Reading file")]))
    assert titled.detail == "kiro-cli judge called a tool (Reading file)"
    update_only = judge_parse(stream(reply, extra=[tool_call("shell", kind="tool_call_update")]))
    assert (update_only.status, update_only.detail) == ("error", "kiro-cli judge called a tool (shell)")
    no_engine = judge_parse([line for line in stream(reply) if '"runStarted"' not in line])
    assert (no_engine.status, no_engine.structured) == ("error", None) and "engine" in no_engine.detail
    bare = judge_parse([line.replace(', "engine": "v2"', "") for line in stream(reply)])
    assert bare.status == "error" and "engine" in bare.detail
    engine = judge_parse(stream(reply, engine="v3"))
    assert (engine.status, engine.structured) == ("error", None)
    assert engine.detail == "kiro-cli ran engine v3; a judge runs v2"
    session_file(tmp_path, "claude-haiku-4.5")
    wrong = judge_parse(stream(reply), model="claude-sonnet-4.5", home=tmp_path)
    assert wrong.status == "error" and wrong.structured is None
    assert wrong.detail == "model_mismatch: kiro-cli selected claude-haiku-4.5, the profile names claude-sonnet-4.5"
    assert wrong.model_resolved == "claude-haiku-4.5"
    assert judge_parse(stream(reply), model="claude-sonnet-4.5", home=tmp_path / "none").status == "ok"


def test_a_pinned_run_whose_session_file_names_the_pinned_model_reports_no_served_model(tmp_path):
    """Finding 3, the owner's decision: a pinned run's session file is the CLI's own selection, an echo of the
    configuration, not a server report. It only detects a mismatch, so the judge keeps provenance `declared`."""
    for named in ("claude-sonnet-5.5", "claude-sonnet-5-5"):
        session_file(tmp_path / named, named)
        result = judge_parse(stream(valid_reply()), model="claude-sonnet-5.5", home=tmp_path / named)
        assert result.status == "ok" and result.model_resolved is None, named


def test_under_auto_the_session_file_gives_the_served_model(tmp_path):
    session_file(tmp_path, "claude-sonnet-5.5")
    for model in (None, "auto"):
        result = judge_parse(stream(valid_reply()), model=model, home=tmp_path)
        assert result.status == "ok" and result.model_resolved == "claude-sonnet-5.5"


def test_a_session_file_that_names_auto_or_is_missing_or_too_large_or_a_link_reports_nothing(tmp_path):
    reply = stream(valid_reply())
    session_file(tmp_path, "auto")
    assert judge_parse(reply, home=tmp_path).model_resolved is None
    assert judge_parse(reply, home=tmp_path / "missing").model_resolved is None
    big = session_file(tmp_path / "big", "claude-sonnet-5.5")
    big.write_text(big.read_text(encoding="utf-8") + " " * 1_100_000, encoding="utf-8")
    assert judge_parse(reply, home=tmp_path / "big").model_resolved is None
    target = session_file(tmp_path / "real", "claude-sonnet-5.5")
    link = tmp_path / "linked" / "sessions" / "cli" / f"{SESSION}.json"
    link.parent.mkdir(parents=True)
    link.symlink_to(target)
    result = judge_parse(reply, home=tmp_path / "linked")
    assert result.status == "ok" and result.model_resolved is None
    blank = session_file(tmp_path / "blank", "")
    assert blank.exists() and judge_parse(reply, home=tmp_path / "blank").model_resolved is None


def test_a_session_id_that_climbs_out_of_the_sessions_folder_reports_no_served_model(tmp_path):
    """Mutation M23: `../../x` would read `<KIRO_HOME>/x.json`; the id is refused before any path is built."""
    (tmp_path / "sessions" / "cli").mkdir(parents=True)
    planted = session_file(tmp_path / "planted", "claude-sonnet-5.5", session="x")
    (tmp_path / "x.json").write_text(planted.read_text(encoding="utf-8"), encoding="utf-8")
    assert (tmp_path / "sessions" / "cli" / "../../x.json").is_file()  # where the id would lead
    lines = [line.replace(SESSION, "../../x") for line in stream(valid_reply())]
    result = judge_parse(lines, home=tmp_path)
    assert result.session_id == "../../x"
    assert result.status == "ok" and result.model_resolved is None


def test_a_stderr_warning_about_the_pinned_model_is_a_model_mismatch_and_empty_stderr_is_fine():
    warning = "warning: could not set model claude-sonnet-5.5, continuing with the default model\n"
    result = judge_parse(stream(valid_reply()), model="claude-sonnet-5.5", stderr=warning)
    assert result.status == "error" and result.structured is None
    assert result.detail == "model_mismatch: kiro-cli could not set claude-sonnet-5.5"
    for line in (
        "Warning: claude-sonnet-5.5 is unavailable, continuing with auto\n",
        "error: failed to set claude-sonnet-5-5; using the default\n",
    ):
        named = judge_parse(stream(valid_reply()), model="claude-sonnet-5.5", stderr=line)
        assert named.status == "error" and named.detail == "model_mismatch: kiro-cli could not set claude-sonnet-5.5"
    assert (
        judge_parse(stream(valid_reply()), model="claude-sonnet-5.5", stderr="claude-sonnet-5.5 ready\n").status == "ok"
    )
    assert judge_parse(stream(valid_reply()), model="claude-sonnet-5.5", stderr="").status == "ok"
    unrelated = judge_parse(stream(valid_reply()), model="claude-sonnet-5.5", stderr="warning: update available\n")
    assert unrelated.status == "ok"
    assert judge_parse(stream(valid_reply()), stderr=warning).status == "ok"  # nothing is pinned under auto


def test_the_capabilities_say_the_adapter_may_report_the_served_model():
    assert KiroCliAdapter().capabilities().served_model is True


def test_run_passes_the_home_the_model_and_the_stderr_to_the_parse_and_reads_no_result_file(tmp_path):
    class Proc(RecordingProc):
        def run(self, argv, env, cwd, *, stdout_path, timeout_s, stdin=None, stderr_path=None, **kw):
            super().run(argv, env, cwd, stdout_path=stdout_path, timeout_s=timeout_s, stdin=stdin, **kw)
            stdout_path.write_text("\n".join(stream(valid_reply())) + "\n", encoding="utf-8")
            stderr_path.write_text("warning: could not set model claude-sonnet-4.5\n", encoding="utf-8")
            return ProcOutcome(0)

    req = request(tmp_path, SONNET)
    req.result_path.parent.mkdir(parents=True, exist_ok=True)
    req.result_path.write_text('{"criteria": "from a leftover file"}', encoding="utf-8")
    result = KiroCliAdapter(Proc()).run(req)
    assert result.detail == "model_mismatch: kiro-cli could not set claude-sonnet-4.5"


R28_FIXTURE = FIXTURE.parent / "2.28.0"


def fixture_lines(directory: Path, name: str) -> list[str]:
    return (directory / name).read_text(encoding="utf-8").splitlines()


def test_scn_kjd_18_an_invalid_key_is_an_auth_status_with_no_limit():
    lines = fixture_lines(FIXTURE, "auth-invalid-key.stream.jsonl")
    result = judge_parse(lines, exit_code=1)
    assert result.status == "auth" and result.limit is None and result.structured is None
    assert result.detail == (
        "kiro-cli could not authenticate (the login or KIRO_API_KEY is missing, expired or rejected)"
    )
    # the same rule in implement mode
    plain = KiroCliAdapter(RecordingProc()).parse(lines, exit_code=1, raw_events_path=RAW)
    assert plain.status == "auth"


def test_scn_kjd_19_no_login_is_an_auth_status_from_the_output_alone():
    stdout = fixture_lines(FIXTURE, "no-login.stdout.txt")
    stderr = (FIXTURE / "no-login.stderr.txt").read_text(encoding="utf-8")
    assert judge_parse(stdout, exit_code=1, stderr=stderr).status == "auth"
    assert judge_parse([], exit_code=1, stderr=stderr).status == "auth"
    plain = KiroCliAdapter(RecordingProc()).parse(stdout, exit_code=1, raw_events_path=RAW, stderr_text=stderr)
    assert plain.status == "auth"
    # an exit 1 with no stream and unrelated output is not an auth failure
    assert judge_parse([], exit_code=1, stderr="boom\n").status == "error"


def test_scn_kjd_20_a_missing_agent_or_missing_input_is_an_error_with_its_stage():
    agent = judge_parse(fixture_lines(R28_FIXTURE, "missing-agent.stream.jsonl"), exit_code=4)
    assert agent.status == "error" and "init" in agent.detail
    missing = judge_parse(fixture_lines(FIXTURE, "input-missing.stream.jsonl"), exit_code=1)
    assert missing.status == "error" and "input" in missing.detail


@pytest.mark.parametrize("stage", ["init", "input"])
@pytest.mark.parametrize("exit_code", [1, 4])
def test_a_run_error_at_init_or_input_that_says_not_logged_in_is_an_error_not_auth(stage, exit_code):
    """Mutation M20: the stage rule of L4-KJD-006 comes before the auth words."""
    line = json.dumps({"type": "runError", "data": {"sessionId": None, "stage": stage, "message": "not logged in"}})
    result = judge_parse([line], exit_code=exit_code)
    assert result.status == "error" and stage in result.detail and result.limit is None


def test_a_throttle_message_that_also_says_access_denied_stays_rate_limited():
    line = json.dumps(
        {"type": "runError", "data": {"stage": "prompt", "message": "AccessDenied: the request was throttled"}}
    )
    assert judge_parse([line], exit_code=1).status == "rate_limited"
    credits = json.dumps(
        {"type": "runError", "data": {"stage": "prompt", "message": "AccessDenied: you have used up your credits"}}
    )
    assert judge_parse([credits], exit_code=1).status == "quota"


def test_an_oversized_stderr_still_shows_its_model_warning(tmp_path):
    from l4.agents.kiro_cli import STDERR_LIMIT, _read_stderr

    path = tmp_path / "stderr.txt"
    noise = "x" * 100 + "\n"
    path.write_text(
        noise * (STDERR_LIMIT // len(noise) + 10) + "warning: could not set model claude-sonnet-5.5\n", encoding="utf-8"
    )
    assert path.stat().st_size > STDERR_LIMIT
    assert "could not set model claude-sonnet-5.5" in _read_stderr(path)
    early = tmp_path / "early.txt"
    early.write_text("warning: could not set model m\n" + noise * (STDERR_LIMIT // len(noise) + 10), encoding="utf-8")
    assert "could not set model m" in _read_stderr(early)
