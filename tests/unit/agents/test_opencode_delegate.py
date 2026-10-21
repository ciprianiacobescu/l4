"""The opencode delegate reads the worktree and nothing else (L4-DLG-016; SCN-DLG-58, 59, 97, 99): a deny-by-default
permission map, the pinned major, the isolation of every opencode run."""

import fnmatch
import json
from pathlib import Path

import pytest

from l4.agents.base import PermissionPolicy, RunRequest
from l4.agents.opencode import (
    BASH_SENTINEL,
    INSTRUCTION_FILES,
    READ_TOOLS,
    OpenCodeAdapter,
    config_content,
)
from l4.agents.proc import ProcOutcome
from l4.config.schema import Profile

PRIVATE = Path("/p/res")
OC = Profile(adapter="opencode", model="opencode-go/deepseek-v4.1-flash", vendor="deepseek")
ZEN = Profile(adapter="opencode", model="opencode/free-model", vendor="unknown")
READ_ONLY = PermissionPolicy("read_only")

# The configurations of the implementer and the judge, as the code before the amendment wrote them.
IMPLEMENT = (
    '{"$schema":"https://opencode.ai/config.json","snapshot":false,"share":"disabled","autoupdate":false,'
    '"permission":{"edit":"allow","read":"allow","glob":"allow","grep":"allow","list":"allow","bash":{"*":"allow",'
    '"git commit*":"deny","git push*":"deny","git reset*":"deny","git checkout*":"deny"},"external_directory":'
    '{"*":"deny","/p/res/**":"allow","/p/res/*":"allow"},"webfetch":"deny","websearch":"deny","question":"deny",'
    '"doom_loop":"deny"}}'
)
JUDGE = (
    '{"$schema":"https://opencode.ai/config.json","snapshot":false,"share":"disabled","autoupdate":false,'
    '"tools":{"*":false},"permission":{"*":"deny"}}'
)
JUDGE_ZEN = (
    '{"$schema":"https://opencode.ai/config.json","snapshot":false,"share":"disabled","autoupdate":false,'
    '"permission":{"*":"deny","read":"ask","bash":"ask"}}'
)


def config(profile: Profile = OC, **kw) -> dict:
    options = profile.opencode_options()
    return json.loads(config_content(READ_ONLY, PRIVATE, str(profile.model), options, **kw))


def resolve(permission: dict, tool: str, arg: str = "*") -> str:
    """What opencode's permission map says about `tool` called on `arg`: the last matching rule wins, rules in key
    order, a tool's own entry a string (all arguments) or a map of argument patterns."""
    verdict = "ask"
    for key, rule in permission.items():
        if not fnmatch.fnmatchcase(tool, key):
            continue
        if isinstance(rule, str):
            verdict = rule
            continue
        for pattern, action in rule.items():
            if fnmatch.fnmatchcase(arg, pattern):
                verdict = action
    return verdict


def test_read_only_config_denies_by_default():  # SCN-DLG-58
    cfg = config()
    permission = cfg["permission"]
    assert list(permission)[0] == "*" and permission["*"] == "deny"  # key order is part of the contract
    assert cfg["tools"] == {"*": False, "read": True, "glob": True, "grep": True}
    for tool in READ_TOOLS:
        assert resolve(permission, tool, "src/app.py") == "allow"
    for tool in ("edit", "write", "patch", "bash", "webfetch", "websearch", "task", "question", "list", "skill"):
        assert resolve(permission, tool) == "deny", tool
    external = permission["external_directory"]
    assert list(external)[0] == "*" and external["*"] == "deny"
    assert resolve({"external_directory": external}, "external_directory", "/p/res/x/result.txt") == "allow"
    assert resolve({"external_directory": external}, "external_directory", "/etc/passwd") == "deny"
    assert cfg["snapshot"] is False and cfg["share"] == "disabled" and cfg["autoupdate"] is False
    assert cfg["lsp"] is False  # no language server is started in the checkout


def test_a_zen_model_keeps_bash_refused():  # SCN-DLG-59
    cfg = config(ZEN)
    assert cfg["tools"]["bash"] is True and cfg["tools"]["read"] is True  # Zen's free tier needs bash in the request
    assert cfg["permission"]["bash"] == {"*": "deny", BASH_SENTINEL: "ask"}
    assert resolve(cfg["permission"], "bash", "rm -rf /") == "deny"
    assert resolve(cfg["permission"], "bash", "git status") == "deny"
    assert "bash" not in config(OC)["tools"]  # any other model: bash is not even in the request


def test_the_zen_bash_permission_is_deny_with_a_sentinel_ask():  # SCN-DLG-59
    cfg = config(ZEN)
    assert cfg["permission"]["bash"] == {"*": "deny", BASH_SENTINEL: "ask"}
    assert "*" not in BASH_SENTINEL and BASH_SENTINEL.strip() == BASH_SENTINEL and " " not in BASH_SENTINEL


def test_the_implement_and_judge_configs_are_unchanged():
    assert config_content(PermissionPolicy("implement", gate_prefix="g"), PRIVATE, "opencode-go/x") == IMPLEMENT
    assert config_content(PermissionPolicy("implement"), PRIVATE, "opencode/free") == IMPLEMENT
    assert config_content(PermissionPolicy("judge"), PRIVATE, "opencode-go/x") == JUDGE
    assert config_content(PermissionPolicy("judge"), PRIVATE, "opencode/free") == JUDGE_ZEN


def test_options_tools_cannot_re_enable_a_tool():  # SCN-DLG-97
    narrowed = OC.model_copy(update={"options": {"tools": ["bash", "edit"]}})
    assert narrowed.opencode_options().tools  # the option is read, and ignored in this mode
    cfg = config(narrowed)
    assert cfg == config(OC)
    for tool in ("bash", "edit", "write"):
        assert resolve(cfg["permission"], tool) == "deny" and cfg["tools"].get(tool) is not True
    # while the implementer still honours it
    implementer = json.loads(
        config_content(PermissionPolicy("implement"), PRIVATE, "opencode-go/x", narrowed.opencode_options())
    )
    assert implementer["tools"] == {"*": False, "bash": True, "edit": True}


def test_no_list_tool_in_the_set():
    assert READ_TOOLS == ("read", "glob", "grep")
    cfg = config()
    assert "list" not in cfg["tools"] and resolve(cfg["permission"], "list") == "deny"


def test_env_files_stay_unreadable():  # SCN-DLG-99
    read = config()["permission"]["read"]
    assert list(read)[0] == "*" and read["*"] == "allow"  # the denials come after the allow
    assert list(read).index("*.env") > 0 and list(read).index("*.env.*") > 0
    permission = config()["permission"]
    assert resolve(permission, "read", ".env") == "deny"
    assert resolve(permission, "read", "config.env.local") == "deny"
    assert resolve(permission, "read", "src/app.py") == "allow"


# -- the run ----------------------------------------------------------------------------------------------------


class FakeProc:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def run(self, argv, env, cwd, *, stdout_path, timeout_s, stdin=None, stderr_path=None, **kw):
        self.calls.append({"argv": list(argv), "env": dict(env), "cwd": cwd, "stdin": stdin})
        stdout_path.parent.mkdir(parents=True, exist_ok=True)
        stdout_path.write_text("")
        if stderr_path is not None:
            stderr_path.write_text("")
        return ProcOutcome(0)


def request(tmp_path: Path, profile: Profile = OC, **kw) -> RunRequest:
    (tmp_path / "bin").mkdir(exist_ok=True)
    exe = tmp_path / "bin" / "opencode"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    return RunRequest(
        role="delegate", cwd=tmp_path / "wt", prompt="the prompt", result_path=tmp_path / "res" / "result.json",
        raw_events_path=tmp_path / "raw" / "events.jsonl", env={"PATH": str(tmp_path / "bin"), "HOME": "/h"},
        profile=profile, permission_policy=READ_ONLY, **kw,
    )  # fmt: skip


def test_the_argv_runs_in_the_worktree(tmp_path):
    proc = FakeProc()
    req = request(tmp_path)
    OpenCodeAdapter(proc).run(req)
    (call,) = proc.calls
    assert call["argv"][1:] == [
        "run", "--pure", "--format", "json", "-m", "opencode-go/deepseek-v4.1-flash", "--dir", str(req.cwd),
        "--title", "l4 delegate events",
    ]  # fmt: skip
    assert call["cwd"] == req.cwd and call["stdin"] == "the prompt"
    assert "judge-cwd" not in " ".join(call["argv"])
    env = call["env"]
    assert env["XDG_CONFIG_HOME"] == str(tmp_path / "res" / "opencode-config")
    assert {env[k] for k in env if k.startswith("OPENCODE_DISABLE_")} == {"1"}
    assert json.loads(env["OPENCODE_CONFIG_CONTENT"]) == config_for_run(tmp_path)


def config_for_run(tmp_path: Path) -> dict:
    return json.loads(config_content(READ_ONLY, tmp_path / "res", str(OC.model), OC.opencode_options()))


def test_no_result_file_is_left_to_read(tmp_path):
    (tmp_path / "res").mkdir()
    (tmp_path / "res" / "result.json").write_text("{}")
    proc = FakeProc()
    result = OpenCodeAdapter(proc).run(request(tmp_path))
    assert not (tmp_path / "res" / "result.json").exists() and result.structured is None


@pytest.mark.parametrize("name", INSTRUCTION_FILES)
def test_the_instruction_file_names_are_the_ones_opencode_loads(name):
    assert name in ("AGENTS.md", "CONTEXT.md", "CLAUDE.md")


def test_the_three_names_are_all_known():
    assert set(INSTRUCTION_FILES) == {"AGENTS.md", "CONTEXT.md", "CLAUDE.md"}
