"""SCN-FAC-52, SCN-FAC-53, SCN-FAC-56, SCN-FAC-57 (L4-FAC-023): OpenCode 1's output limit is the variable
`OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX`, set by the profile alone; the hints that name the key are added by `run()`,
never by `parse()`."""

import hashlib
import json
from pathlib import Path

import pytest

from l4.agents.base import PermissionPolicy, RunRequest, RunResult
from l4.agents.opencode import (
    OUTPUT_TOKEN_ENV,
    OpenCodeAdapter,
    config_content,
    output_limit_env,
    output_limit_hint,
)
from l4.agents.opencode_v2 import OpenCodeV2Adapter
from l4.agents.proc import ProcOutcome
from l4.config.schema import OpencodeOptions, Profile

from .test_opencode import FakeProc, request
from .test_opencode_provider import HOST_ENV
from .test_opencode_provider import MODEL as CUSTOM_MODEL
from .test_opencode_provider import OPTIONS as CUSTOM_OPTIONS
from .test_opencode_v2_run import V2Proc
from .test_opencode_v2_run import request as v2_request

RECORDED = Path(__file__).parents[2] / "fixtures" / "recorded" / "opencode" / "1.18.33"
MODEL = "opencode-go/deepseek-v4.1-flash"
OK_STREAM = (RECORDED / "hello-ok-stdin-prompt.jsonl").read_text()
V1_NO_KEY = (
    "the reply stopped at its output limit: OpenCode 1 asks for at most 32000 output tokens unless "
    "options.max_output_tokens is set (up to the model's own maximum)"
)
V2_NO_KEY = (
    "the reply stopped at its output limit: OpenCode 2 asks for the model's known output limit, else 32000 tokens, "
    "unless options.max_output_tokens is set (up to the model's own maximum)"
)
WITH_KEY = (
    "the reply stopped at its output limit (options.max_output_tokens 65536, or less when the model or the context "
    "allows less)"
)
CLAUSE_400 = "options.max_output_tokens is set: a provider refuses a maximum output above the model's own (HTTP 400)"
LENGTH_DETAIL = "the stream ended without a final stop (last reason: length)"
POLICIES = {
    "implement": PermissionPolicy("implement"),
    "judge": PermissionPolicy("judge"),
    "read_only": PermissionPolicy("read_only"),
}


def keyed(model: str = MODEL, **options) -> Profile:
    return Profile(adapter="opencode", model=model, vendor="deepseek", options={"max_output_tokens": 65536, **options})


PLAIN = Profile(adapter="opencode", model=MODEL, vendor="deepseek")


HOST_VALUE = "99999"  # the host's own value of the variable: it must never reach a CLI


def run_env(tmp_path: Path, profile: Profile, mode: str, host_env: dict[str, str] | None = None) -> dict[str, str]:
    proc = FakeProc(OK_STREAM)
    tmp_path.mkdir(parents=True, exist_ok=True)
    req = request(tmp_path, profile=profile, permission_policy=POLICIES[mode], role=mode, host_env=host_env or {})
    OpenCodeAdapter(proc).run(req)
    (call,) = proc.calls
    return call["env"]


# --- SCN-FAC-52, SCN-FAC-53: the variable in every mode, and only with the key ---


@pytest.mark.parametrize("mode", ["implement", "judge", "read_only"])
def test_the_key_is_exported_to_every_mode_and_the_configuration_is_unchanged(tmp_path, mode):
    with_key = run_env(tmp_path / "a", keyed(), mode)
    without = run_env(tmp_path / "b", PLAIN, mode)
    assert with_key[OUTPUT_TOKEN_ENV] == "65536" and OUTPUT_TOKEN_ENV not in without
    assert OUTPUT_TOKEN_ENV == "OPENCODE_EXPERIMENTAL_OUTPUT_TOKEN_MAX"
    expected = json.loads(without["OPENCODE_CONFIG_CONTENT"])
    assert json.loads(with_key["OPENCODE_CONFIG_CONTENT"]).keys() == expected.keys()
    assert with_key["OPENCODE_CONFIG_CONTENT"].replace(str(tmp_path / "a"), "") == without[
        "OPENCODE_CONFIG_CONTENT"
    ].replace(str(tmp_path / "b"), "")


@pytest.mark.parametrize("mode", ["implement", "judge", "read_only"])
def test_the_hosts_own_value_never_reaches_a_v1_run(tmp_path, mode):
    host = {OUTPUT_TOKEN_ENV: HOST_VALUE}
    assert OUTPUT_TOKEN_ENV not in run_env(tmp_path / "a", PLAIN, mode, host)
    assert run_env(tmp_path / "b", keyed(), mode, host)[OUTPUT_TOKEN_ENV] == "65536"


RESULT_DIR = Path("/tmp/l4-step/result")
# sha256 of `config_content(policy, RESULT_DIR, model, None, None)` as rendered by 0.4.58 (f0bc8a3c, the commit before
# this change): the same render code, run from a worktree of that commit. A model of the free tier differs in judge and
# read-only mode only.
RENDERED_0458 = {
    ("opencode-go/deepseek-v4.1-flash", "implement"): "0f446bd97cf3882281f86ed59ed97e8504f3406cc964ffdcab8278c682f13ff5",  # noqa: E501
    ("opencode-go/deepseek-v4.1-flash", "judge"): "05a67845b1f061e5ec1186c86d59b8ab3a8857ef3827eb26d4d6b13e29dcad7d",
    ("opencode-go/deepseek-v4.1-flash", "read_only"): "d55c29175f5e4e4a2ff81fd539c9ac562197e6345c24ce001ca1e98c41940a5a",  # noqa: E501
    ("opencode/big-pickle", "implement"): "0f446bd97cf3882281f86ed59ed97e8504f3406cc964ffdcab8278c682f13ff5",
    ("opencode/big-pickle", "judge"): "bac274efe82d69b39a7dddc6d4a489efdf0b063498338ef5790d7d385428706a",
    ("opencode/big-pickle", "read_only"): "30cb7a6d38b4270595ab6bfea6576ad402a1f99115113e761db014df0071775a",
}  # fmt: skip


@pytest.mark.parametrize("mode", ["implement", "judge", "read_only"])
@pytest.mark.parametrize("model", [MODEL, "opencode/big-pickle"])
def test_without_the_key_the_v1_configuration_is_the_one_of_0458_byte_for_byte(model, mode):
    """SCN-FAC-53: head's text without the key equals 0.4.58's, pinned by hash, not only by a comparison inside head."""
    text = config_content(POLICIES[mode], RESULT_DIR, model, None, None)
    assert hashlib.sha256(text.encode()).hexdigest() == RENDERED_0458[(model, mode)]
    keyed_options = keyed(model).opencode_options()
    assert config_content(POLICIES[mode], RESULT_DIR, model, keyed_options, None) == text  # the key is not in it


def test_the_other_options_of_a_profile_do_not_export_it(tmp_path):
    profile = Profile(adapter="opencode", model=MODEL, vendor="deepseek", options={"tools": ["read", "bash"]})
    assert OUTPUT_TOKEN_ENV not in run_env(tmp_path, profile, "implement")


def test_a_custom_provider_keeps_its_model_entry_and_gets_the_variable(tmp_path):
    options = {**CUSTOM_OPTIONS, "provider": {
        **CUSTOM_OPTIONS["provider"], "models": {CUSTOM_MODEL: {"context": 262144, "output": 65536}},
    }, "max_output_tokens": 65536}  # fmt: skip
    profile = Profile(
        adapter="opencode", model=f"magnitude/{CUSTOM_MODEL}", auth="api_key", vendor="alibaba", options=options
    )
    proc = FakeProc(OK_STREAM)
    OpenCodeAdapter(proc).run(request(tmp_path, profile=profile, host_env=HOST_ENV))
    env = proc.calls[0]["env"]
    config = json.loads(env["OPENCODE_CONFIG_CONTENT"])
    assert config["provider"]["magnitude"]["models"][CUSTOM_MODEL]["limit"] == {"context": 262144, "output": 65536}
    assert env[OUTPUT_TOKEN_ENV] == "65536"


def test_output_limit_env_is_the_profile_alone():
    assert output_limit_env(None) == {} and output_limit_env(OpencodeOptions()) == {}
    assert output_limit_env(OpencodeOptions(max_output_tokens=1024)) == {OUTPUT_TOKEN_ENV: "1024"}


# --- SCN-FAC-56: the hint of a length stop ---


def length_result(detail: str | None = LENGTH_DETAIL, stop: bool = True) -> RunResult:
    return RunResult(status="error", raw_events_path=Path("x"), detail=detail, length_stop=stop)


@pytest.mark.parametrize(
    ("major", "options", "hint"),
    [
        (1, None, V1_NO_KEY),
        (1, OpencodeOptions(), V1_NO_KEY),
        (2, None, V2_NO_KEY),
        (1, OpencodeOptions(max_output_tokens=65536), WITH_KEY),
        (2, OpencodeOptions(max_output_tokens=65536), WITH_KEY),
    ],
)
def test_the_hint_is_joined_to_the_detail_by_a_semicolon(major, options, hint):
    out = output_limit_hint(length_result(), options, major)
    assert out.detail == f"{LENGTH_DETAIL}; {hint}"


@pytest.mark.parametrize("detail", [None, ""])
def test_an_empty_detail_becomes_the_hint_alone(detail):
    assert output_limit_hint(length_result(detail), None, 1).detail == V1_NO_KEY


def test_a_run_that_did_not_stop_at_its_limit_is_unchanged():
    out = output_limit_hint(length_result(stop=False), OpencodeOptions(max_output_tokens=65536), 1)
    assert out.detail == LENGTH_DETAIL


def length_stream() -> str:
    lines = [
        {"type": "step_start", "sessionID": "ses_x", "part": {}},
        {"type": "text", "sessionID": "ses_x", "part": {"type": "text", "text": '{"criteria": ['}},
        {"type": "step_finish", "sessionID": "ses_x",
         "part": {"reason": "length", "tokens": {"input": 10, "output": 32000}}},
    ]  # fmt: skip
    return "\n".join(json.dumps(line) for line in lines) + "\n"


@pytest.mark.parametrize(("profile", "hint"), [(PLAIN, V1_NO_KEY), (keyed(), WITH_KEY)])
def test_a_v1_length_stop_names_the_key_in_the_run(tmp_path, profile, hint):
    req = request(tmp_path, profile=profile, role="judge", permission_policy=PermissionPolicy("judge"))
    out = OpenCodeAdapter(FakeProc(length_stream())).run(req)
    assert out.length_stop is True and out.status == "error"
    assert out.detail == f"{LENGTH_DETAIL}; {hint}"


def test_parse_alone_keeps_todays_detail(tmp_path):
    out = OpenCodeAdapter().parse(
        length_stream().splitlines(), exit_code=0, raw_events_path=tmp_path / "raw.jsonl", judge=True
    )
    assert out.length_stop is True and out.detail == LENGTH_DETAIL


@pytest.mark.parametrize(
    ("profile", "hint"),
    [
        (Profile(adapter="opencode", model=MODEL, vendor="deepseek", options={"cli_major": 2}), V2_NO_KEY),
        (keyed(cli_major=2), WITH_KEY),
    ],
)
def test_a_v2_length_stop_names_the_key_in_the_run(tmp_path, profile, hint):
    proc = V2Proc(length_stream(), "", export_outcome=ProcOutcome(1))
    req = v2_request(tmp_path, profile=profile, role="judge", permission_policy=PermissionPolicy("judge"))
    out = OpenCodeV2Adapter(proc).run(req)
    assert out.length_stop is True and out.status == "error"
    assert out.detail == f"opencode2 session export failed (exit 1) and the stream has no final stop; {hint}"


def test_a_run_that_stopped_for_another_reason_gets_no_hint(tmp_path):
    lines = length_stream().replace('"length"', '"tool-calls"')
    req = request(tmp_path, profile=keyed(), role="judge", permission_policy=PermissionPolicy("judge"))
    out = OpenCodeAdapter(FakeProc(lines)).run(req)
    assert out.length_stop is False and out.detail == "the stream ended without a final stop (last reason: tool-calls)"


# --- SCN-FAC-57: the 400 clause ---


def error_stream(status: int, message: str = "bad request") -> str:
    data = {"message": message, "statusCode": status}
    return json.dumps({"type": "error", "sessionID": "ses_x", "error": {"name": "APIError", "data": data}}) + "\n"


def v2_error_stream(status: int) -> str:
    return json.dumps({"type": "error", "sessionID": "ses_x", "error": {"type": "x", "status": status}}) + "\n"


def judge(tmp_path: Path, profile: Profile, stream: str) -> RunResult:
    req = request(tmp_path, profile=profile, role="judge", permission_policy=PermissionPolicy("judge"))
    return OpenCodeAdapter(FakeProc(stream, ProcOutcome(1))).run(req)


def judge_v2(tmp_path: Path, profile: Profile, stream: str) -> RunResult:
    req = v2_request(tmp_path, profile=profile, role="judge", permission_policy=PermissionPolicy("judge"))
    return OpenCodeV2Adapter(V2Proc(stream, "", export_outcome=ProcOutcome(1))).run(req)


def test_a_v1_400_with_the_key_names_the_key(tmp_path):
    out = judge(tmp_path, keyed(), error_stream(400))
    assert out.api_status == 400
    assert out.detail == f"opencode reported an error (status 400); {CLAUSE_400}"


@pytest.mark.parametrize("status", [500, 402, 404])
def test_a_v1_status_other_than_400_gets_no_clause(tmp_path, status):
    out = judge(tmp_path, keyed(), error_stream(status))
    assert CLAUSE_400 not in (out.detail or "")


def test_a_v1_400_without_the_key_is_todays_text(tmp_path):
    out = judge(tmp_path, PLAIN, error_stream(400))
    assert out.detail == "opencode reported an error (status 400)"


def test_a_v2_400_with_the_key_names_the_key(tmp_path):
    out = judge_v2(tmp_path, keyed(cli_major=2), v2_error_stream(400))
    assert out.api_status == 400
    assert out.detail == f"opencode2 reported an error (x, status 400); {CLAUSE_400}"


def test_a_v2_400_without_the_key_or_with_another_status_gets_no_clause(tmp_path):
    plain = Profile(adapter="opencode", model=MODEL, vendor="deepseek", options={"cli_major": 2})
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    assert judge_v2(tmp_path / "a", plain, v2_error_stream(400)).detail == "opencode2 reported an error (x, status 400)"
    assert CLAUSE_400 not in (judge_v2(tmp_path / "b", keyed(cli_major=2), v2_error_stream(500)).detail or "")


def test_a_custom_providers_grammar_failure_is_not_a_400_of_the_key(tmp_path):
    options = {**CUSTOM_OPTIONS, "max_output_tokens": 16384}
    profile = Profile(
        adapter="opencode", model=f"magnitude/{CUSTOM_MODEL}", auth="api_key", vendor="alibaba", options=options
    )
    req = request(
        tmp_path, profile=profile, role="judge", permission_policy=PermissionPolicy("judge"), host_env=HOST_ENV
    )
    out = OpenCodeAdapter(FakeProc(error_stream(400, "grammar binding failed"), ProcOutcome(1))).run(req)
    assert "provider_unavailable" in (out.detail or "") and CLAUSE_400 not in out.detail


def test_the_request_helper_is_shared():
    assert RunRequest  # the imports above are the fixtures of test_opencode.py and test_opencode_v2_run.py
