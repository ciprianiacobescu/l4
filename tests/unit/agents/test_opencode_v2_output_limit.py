"""SCN-OCV-49, SCN-OCV-50, SCN-OCV-51, SCN-OCV-52 (L4-OCV-020): a `cli_major: 2` profile's `options.max_output_tokens`
is its model's `limit.output` in the native configuration, after `agents`, for the run, its export and the hello and
never for `auth list`; without the key the configuration is the one of 0.4.58, byte for byte."""

import hashlib
import json
from pathlib import Path

import pytest

from l4.agents.base import PermissionPolicy
from l4.agents.opencode import OUTPUT_TOKEN_ENV
from l4.agents.opencode_v2 import OpenCodeV2Adapter, config_content_v2
from l4.config.schema import Profile

from .test_opencode_v2_run import V2Proc, request, text_run

RESULT_DIR = Path("/tmp/l4-step/result")
PAID, FREE = "opencode-go/deepseek-v4.1-flash", "opencode/big-pickle"
POLICIES = {"implement": PermissionPolicy("implement"), "judge": PermissionPolicy("judge")}
# sha256 of `config_content_v2(policy, RESULT_DIR, model, None)` as rendered by 0.4.58 (the commit before this change)
RENDERED_0458 = {
    ("opencode-go/deepseek-v4.1-flash", "implement"): "469aa122c375c6dec03aada3d76af07297fe84c4a833853c5bf3a8f664e438d8",  # noqa: E501
    ("opencode-go/deepseek-v4.1-flash", "judge"): "d23fc9a2e3589795922bfc5033e3e25256cfa3b4e859bacf36c5e9bc1367c512",
    ("opencode/big-pickle", "implement"): "8f6a0ce1db0812d40ba16c745cc0a2eabc8b58ee3fd1be235a1263bcde130567",
    ("opencode/big-pickle", "judge"): "f39c0c2d7a457118e6ad0cafdc6a4c76bde21c2013396abfe23c07d9fb74b52f",
}  # fmt: skip


def profile(model: str = PAID, **options) -> Profile:
    return Profile(adapter="opencode", model=model, vendor="unknown", options={"cli_major": 2, **options})


def render(model: str, mode: str, **options) -> str:
    return config_content_v2(POLICIES[mode], RESULT_DIR, model, profile(model, **options).opencode_options())


@pytest.mark.parametrize("mode", ["implement", "judge"])
def test_the_limit_is_the_last_key_after_agents_and_nothing_else_moves(mode):
    without = json.loads(render(PAID, mode))
    text = render(PAID, mode, max_output_tokens=65536)
    parsed = json.loads(text)
    expected = {
        **without,
        "providers": {"opencode-go": {"models": {"deepseek-v4.1-flash": {"limit": {"output": 65536}}}}},
    }
    assert parsed == expected
    assert list(parsed)[-1] == "providers" and list(parsed)[:-1] == list(without)
    assert text == json.dumps(expected, separators=(",", ":"))


def test_the_model_id_keeps_everything_after_the_first_slash():
    parsed = json.loads(render("openrouter/anthropic/claude-sonnet-5.5", "judge", max_output_tokens=64000))
    assert parsed["providers"] == {
        "openrouter": {"models": {"anthropic/claude-sonnet-5.5": {"limit": {"output": 64000}}}}
    }


@pytest.mark.parametrize("mode", ["implement", "judge"])
@pytest.mark.parametrize("model", [PAID, FREE])
def test_without_the_key_the_text_is_the_one_of_0458(model, mode):
    text = render(model, mode)
    assert "providers" not in text
    assert hashlib.sha256(text.encode()).hexdigest() == RENDERED_0458[(model, mode)]
    assert text == config_content_v2(POLICIES[mode], RESULT_DIR, model, None)
    with_steps = profile(model, steps={"judge": 3, "implement": 200}).opencode_options()
    assert config_content_v2(POLICIES[mode], RESULT_DIR, model, with_steps) == text


def configs(proc: V2Proc) -> list[dict]:
    return [json.loads(call["env"]["OPENCODE_CONFIG_CONTENT"]) for call in proc.calls]


def test_the_run_and_its_export_carry_the_block_and_no_environment_holds_the_variable(tmp_path):
    proc = text_run()
    OpenCodeV2Adapter(proc).run(request(tmp_path, profile=profile(max_output_tokens=65536)))
    assert [c["kind"] for c in proc.calls] == ["run", "export"]
    block = {"opencode-go": {"models": {"deepseek-v4.1-flash": {"limit": {"output": 65536}}}}}
    assert [c.get("providers") for c in configs(proc)] == [block, block]
    assert all(OUTPUT_TOKEN_ENV not in call["env"] for call in proc.calls)


def test_a_run_without_the_key_has_no_block_and_no_variable(tmp_path):
    proc = text_run()
    OpenCodeV2Adapter(proc).run(request(tmp_path, profile=profile()))
    assert all("providers" not in c for c in configs(proc))
    assert all(OUTPUT_TOKEN_ENV not in call["env"] for call in proc.calls)
