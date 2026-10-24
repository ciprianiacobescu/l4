"""The OpenCode v2 command layer (L4-OCV-003 to -006 configuration part, SCN-OCV-06 to -12, -27 adapter part): the one
argv builder, the isolation environment, the native configuration and the step bounds. Nothing here starts a process;
the parser and the run are later groups."""

import json
from pathlib import Path

import pytest

from l4.agents.base import AdapterError, PermissionPolicy, RunRequest
from l4.agents.opencode_v2 import (
    IMPLEMENT_STEPS,
    JUDGE_STEPS,
    OpenCodeV2Adapter,
    config_content_v2,
    isolation_env_v2,
    step_bound,
    v2_argv,
)
from l4.agents.proc import ProcOutcome
from l4.config.schema import OpencodeOptions, Profile

RECORDED = Path(__file__).parents[2] / "fixtures" / "recorded" / "opencode" / "2.0.32"
RESULT_DIR = Path("/tmp/l4-step/result")  # the directory the recorded normalisations were made for
EXE = "/opt/bin/opencode2"
PAID = "opencode-go/deepseek-v4.1-flash"
FREE = "opencode/big-pickle"
IMPLEMENT, JUDGE = PermissionPolicy("implement"), PermissionPolicy("judge")
SWITCHES = {
    "OPENCODE_DISABLE_PROJECT_CONFIG", "OPENCODE_DISABLE_CLAUDE_CODE", "OPENCODE_DISABLE_CLAUDE_CODE_SKILLS",
    "OPENCODE_DISABLE_EXTERNAL_SKILLS", "OPENCODE_DISABLE_AUTOUPDATE",
}  # fmt: skip


def v2_profile(model: str = PAID, **options) -> Profile:
    return Profile(adapter="opencode", model=model, vendor="unknown", options={"cli_major": 2, **options})


def request(tmp_path: Path, policy: PermissionPolicy = IMPLEMENT, role: str = "implementer", **kw) -> RunRequest:
    kw.setdefault("profile", v2_profile())
    return RunRequest(
        cwd=tmp_path / "wt", prompt="the prompt", role=role, result_path=tmp_path / "step" / "result" / "result.json",
        raw_events_path=tmp_path / "step" / "raw-001.jsonl", env={"PATH": "/usr/bin"}, permission_policy=policy, **kw,
    )  # fmt: skip


def recorded_permissions(name: str) -> list[dict]:
    document = json.loads((RECORDED / name).read_text())
    (info,) = [item["info"] for item in document if item["type"] == "document"]
    return info["permissions"]


def native(permissions: list[dict]) -> list[dict]:
    """The recorded normalisation as the native shape holds it: no `list` or `doom_loop` rule (not v2 actions), and
    a rule repeated identically once."""
    kept: list[dict] = []
    for rule in permissions:
        if rule["action"] in ("list", "doom_loop") or rule in kept:
            continue
        kept.append(rule)
    return kept


def rule(action: str, effect: str, resource: str = "*") -> dict[str, str]:
    return {"action": action, "resource": resource, "effect": effect}


def config_of(policy: PermissionPolicy, model: str = PAID, **options) -> dict:
    profile = v2_profile(model, **options)
    return json.loads(config_content_v2(policy, RESULT_DIR, model, profile.opencode_options()))


# -- SCN-OCV-06, SCN-OCV-07: the one argv builder --------------------------------------------------


def test_standalone_follows_the_subcommand_words_of_every_allowed_call():
    assert v2_argv(EXE, "run", "--format", "json", "-m", PAID) == [
        EXE,
        "run",
        "--standalone",
        "--format",
        "json",
        "-m",
        PAID,
    ]
    assert v2_argv(EXE, "auth list", "--format", "json") == [EXE, "auth", "list", "--standalone", "--format", "json"]
    assert v2_argv(EXE, "auth", "list", "--format", "json") == [EXE, "auth", "list", "--standalone", "--format", "json"]
    assert v2_argv(EXE, "session export", "ses_1") == [EXE, "session", "export", "--standalone", "ses_1"]


def test_each_call_gets_a_state_directory_of_its_own_and_no_data_directory(tmp_path):
    calls = {kind: tmp_path / kind for kind in ("run", "hello", "export", "auth")}
    envs = {kind: isolation_env_v2(base / "config", base / "opencode2-state", "{}") for kind, base in calls.items()}
    states = {env["XDG_STATE_HOME"] for env in envs.values()}
    assert len(states) == 4
    for kind, env in envs.items():
        assert Path(env["XDG_STATE_HOME"]).parent == calls[kind]  # under the call's private directory
        assert "XDG_DATA_HOME" not in env  # the credentials and opencode.db live there: never redirected


@pytest.mark.parametrize(
    "words",
    [("debug", "config"), ("models",), ("serve",), ("service",), ("api",), ("pair",), ("auth",), ("session",), ("",)],
)
def test_a_subcommand_outside_the_allowed_set_cannot_be_built(words):
    with pytest.raises(AdapterError):
        v2_argv(EXE, *words)


def test_a_subcommand_hidden_behind_an_option_is_not_accepted():
    with pytest.raises(AdapterError):
        v2_argv(EXE, "--format", "json", "debug", "config")


# -- SCN-OCV-08: argv and environment --------------------------------------------------------------


def test_the_implementer_argv_is_exactly_the_run_form(tmp_path):
    req = request(tmp_path)
    argv = OpenCodeV2Adapter().build_command(req, exe=EXE, workdir=req.cwd)
    assert argv == [EXE, "run", "--standalone", "--format", "json", "-m", PAID, "--title", "l4 implementer raw-001"]
    assert "--pure" not in argv and "--dir" not in argv


def test_a_judge_argv_names_its_role_in_the_title(tmp_path):
    req = request(tmp_path, JUDGE, role="judge")
    argv = OpenCodeV2Adapter().build_command(req, exe=EXE, workdir=req.cwd)
    assert argv[-2:] == ["--title", "l4 judge raw-001"] and "--pure" not in argv and "--dir" not in argv


def test_the_environment_holds_the_five_switches_and_the_config(tmp_path):
    content = config_content_v2(IMPLEMENT, RESULT_DIR, PAID, None)
    env = isolation_env_v2(tmp_path / "config", tmp_path / "state", content)
    assert {name for name in env if name.startswith("OPENCODE_DISABLE_")} == SWITCHES
    assert all(env[name] == "1" for name in SWITCHES)
    assert env["XDG_CONFIG_HOME"] == str(tmp_path / "config") and env["XDG_STATE_HOME"] == str(tmp_path / "state")
    assert env["OPENCODE_CONFIG_CONTENT"] == content
    assert set(env) == {*SWITCHES, "XDG_CONFIG_HOME", "XDG_STATE_HOME", "OPENCODE_CONFIG_CONTENT"}


def test_a_profile_without_a_model_cannot_build_a_command(tmp_path):
    req = request(tmp_path, profile=Profile(adapter="opencode", vendor="unknown", options={"cli_major": 2}))
    with pytest.raises(AdapterError):
        OpenCodeV2Adapter().build_command(req, exe=EXE, workdir=req.cwd)


def test_the_adapter_is_the_experimental_opencode():
    adapter = OpenCodeV2Adapter()
    assert adapter.name == "opencode" and adapter.experimental is True


# -- SCN-OCV-09: the native rules equal the recorded normalisation ---------------------------------


def test_implement_rules_equal_the_recorded_normalisation_followed_by_skill_and_subagent():
    expected = [*native(recorded_permissions("config-normalised-implement.json")), rule("skill", "deny"),
                rule("subagent", "deny")]  # fmt: skip
    assert config_of(IMPLEMENT)["permissions"] == expected


def test_judge_paid_rules_equal_the_recorded_normalisation_once_repeats_are_dropped():
    recorded = recorded_permissions("config-normalised-judge-paid.json")
    assert recorded == [rule("*", "deny")] * 2  # the recording repeats the rule: native says it once
    assert config_of(JUDGE)["permissions"] == native(recorded) == [rule("*", "deny")]


def test_judge_free_rules_equal_the_recorded_normalisation():
    assert config_of(JUDGE, FREE)["permissions"] == native(recorded_permissions("config-normalised-judge-free.json"))


def test_the_document_is_native_and_holds_no_v1_key():
    for policy, model in ((IMPLEMENT, PAID), (JUDGE, PAID), (JUDGE, FREE)):
        document = config_of(policy, model)
        assert document["$schema"] == "https://opencode.ai/config.json"
        assert document["snapshots"] is False and document["share"] == "disabled" and document["update"] == "disable"
        assert not {"permission", "tools", "snapshot", "autoupdate"} & set(document)
        assert set(document) == {"$schema", "snapshots", "share", "update", "permissions", "agents"}
        assert not {"list", "doom_loop"} & {r["action"] for r in document["permissions"]}


def test_the_document_is_one_compact_json_line():
    text = config_content_v2(IMPLEMENT, RESULT_DIR, PAID, None)
    assert text == json.dumps(json.loads(text), separators=(",", ":")) and "\n" not in text


def test_the_external_directory_deny_precedes_the_result_directory_allows():
    """OpenCode applies the last matching rule: the deny-all must come first."""
    rules = [r for r in config_of(IMPLEMENT)["permissions"] if r["action"] == "external_directory"]
    assert rules == [
        rule("external_directory", "deny"),
        rule("external_directory", "allow", f"{RESULT_DIR}/**"),
        rule("external_directory", "allow", f"{RESULT_DIR}/*"),
    ]


def test_deny_skill_and_mask_skill_and_subagent_take_the_refuse_value():
    """Fallback `deny_skill_and_mask` (U6): `skill` and `subagent` are refused like `bash` is, so a free model gets
    `ask` (a removed tool can trigger the free tier's 403), a paid one `deny`."""
    for model, effect in ((PAID, "deny"), (FREE, "ask")):
        rules = config_of(IMPLEMENT, model)["permissions"]
        assert rules[-2:] == [rule("skill", effect), rule("subagent", effect)]


# -- SCN-OCV-27, adapter part: no read-only shape (amendment E4) -----------------------------------


class Recorder:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def run(self, argv, env, cwd, **kw):
        self.calls.append({"argv": list(argv), "env": dict(env), "cwd": cwd})
        return ProcOutcome(0)


READ_ONLY = PermissionPolicy("read_only")


def test_a_read_only_request_is_refused_before_anything_starts(tmp_path):
    proc = Recorder()
    req = request(tmp_path, READ_ONLY, role="delegate")
    adapter = OpenCodeV2Adapter(proc)
    with pytest.raises(AdapterError, match="read.only"):
        adapter.run(req)
    with pytest.raises(AdapterError, match="read.only"):
        adapter.build_command(req, exe=EXE, workdir=req.cwd)
    assert proc.calls == []
    assert not (tmp_path / "step").exists()  # not even the step's private directory


def test_no_read_only_configuration_or_bound_exists():
    with pytest.raises(AdapterError, match="read.only"):
        config_content_v2(READ_ONLY, RESULT_DIR, PAID, None)
    with pytest.raises(AdapterError, match="read.only"):
        step_bound(READ_ONLY, None)


# -- SCN-OCV-10: a free judge is never deny-all only -----------------------------------------------


def test_a_free_judge_asks_for_read_and_shell_after_the_deny_all():
    assert config_of(JUDGE, FREE)["permissions"] == [
        rule("*", "deny"), rule("read", "ask"), rule("shell", "ask")
    ]  # fmt: skip


# -- SCN-OCV-11: options.tools keeps its meaning ---------------------------------------------------


def test_the_recorded_normalisation_of_options_tools_allows_shell_again():
    """The reason for the native array: in the recorded normalisation a `shell` allow follows the deny-all, although the
    profile listed only read and edit."""
    recorded = recorded_permissions("config-normalised-implement-tools.json")
    assert recorded[0] == rule("*", "deny") and rule("shell", "allow") in recorded[1:]


def test_tools_by_permission_only_the_listed_tools_are_allowed():
    """Fallback `tools_by_permission` (U2): `options.tools` is a deny-all and the listed tools' allows, because
    whether a v2 deny drops the tool's schema from the request is not recorded."""
    rules = config_of(IMPLEMENT, tools=["read", "edit"])["permissions"]
    assert rules[:3] == [rule("*", "deny"), rule("read", "allow"), rule("edit", "allow")]
    assert not [r for r in rules if r["action"] == "shell"]  # no shell rule at all: no allow, no git deny
    assert [r["action"] for r in rules if r["effect"] == "allow" and r["action"] != "external_directory"] == [
        "read",
        "edit",
    ]
    assert rules[-2:] == [rule("skill", "deny"), rule("subagent", "deny")]
    assert rule("external_directory", "allow", f"{RESULT_DIR}/**") in rules


def test_tools_map_to_their_v2_actions_in_listed_order_once_each():
    rules = config_of(IMPLEMENT, tools=["bash", "write", "edit", "patch", "grep", "glob"])["permissions"]
    allowed = [r["action"] for r in rules if r["effect"] == "allow" and r["action"] != "external_directory"]
    assert allowed == ["shell", "edit", "grep", "glob"]
    shell = [r for r in rules if r["action"] == "shell"]  # the git writes stay refused when shell is allowed
    assert shell[0] == rule("shell", "allow")
    assert [r["resource"] for r in shell[1:]] == ["git commit*", "git push*", "git reset*", "git checkout*"]
    assert all(r["effect"] == "deny" for r in shell[1:])


def test_list_has_no_v2_permission_action():
    """The load check refuses it already (L4-OCV-001): the adapter fails closed for a profile that skipped it."""
    options = OpencodeOptions.model_validate({"cli_major": 2, "tools": ["read", "list"]})
    with pytest.raises(AdapterError, match="list"):
        config_content_v2(IMPLEMENT, RESULT_DIR, PAID, options)


def test_options_tools_do_not_change_a_judge():
    assert config_of(JUDGE, tools=["read"])["permissions"] == [rule("*", "deny")]


# -- SCN-OCV-12: the step bound per role -----------------------------------------------------------


def test_the_bounds_per_role_and_a_profile_override():
    assert (JUDGE_STEPS, IMPLEMENT_STEPS) == (3, 200)
    for options in (None, v2_profile().opencode_options()):
        assert step_bound(JUDGE, options) == 3 and step_bound(IMPLEMENT, options) == 200
    bigger = v2_profile(steps={"implement": 400}).opencode_options()
    assert (step_bound(JUDGE, bigger), step_bound(IMPLEMENT, bigger)) == (3, 400)
    judge_only = v2_profile(steps={"judge": 5}).opencode_options()
    assert (step_bound(JUDGE, judge_only), step_bound(IMPLEMENT, judge_only)) == (5, 200)


def test_agents_build_steps_in_the_document():
    assert config_of(JUDGE)["agents"] == {"build": {"steps": 3}}  # the hello is judge mode too
    assert config_of(JUDGE, FREE)["agents"] == {"build": {"steps": 3}}
    assert config_of(IMPLEMENT)["agents"] == {"build": {"steps": 200}}
    assert config_of(IMPLEMENT, steps={"implement": 400})["agents"] == {"build": {"steps": 400}}
    assert config_of(JUDGE, steps={"implement": 400})["agents"] == {"build": {"steps": 3}}


def test_both_recorded_step_forms_resolve_to_the_same_bound():
    """D5's equivalence: the native `agents.build.steps` and the v1 form `maxSteps` resolve to the same value."""
    bounds = []
    for name in ("config-steps-native.json", "config-steps-v1-form.json"):
        document = json.loads((RECORDED / name).read_text())
        (info,) = [item["info"] for item in document if item["type"] == "document"]
        bounds.append(info["agents"]["build"]["steps"])
    assert bounds == [3, 3]
