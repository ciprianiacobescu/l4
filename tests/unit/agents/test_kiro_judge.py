"""The tool-less Kiro judge (kiro-judge 3.1): harness agent, private KIRO_HOME, stdin transport, `--model auto`."""

import json
from pathlib import Path

import pytest

from l4.agents.base import AdapterError, PermissionPolicy, RunRequest
from l4.agents.kiro_cli import JUDGE_SETTINGS, TRUST_TOOLS, KiroCliAdapter
from l4.agents.proc import ProcOutcome
from l4.config.schema import Profile

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
