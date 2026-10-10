from pathlib import Path

import pytest

from l4.agents.base import ProbeCtx, RunRequest
from l4.agents.factory import Factory, RoleUnavailable
from l4.agents.fake import FakeAdapter
from l4.config.preflight import preflight_run_config
from l4.config.schema import L4Config
from l4.context import AppContext
from l4.exitcodes import ExitCode, L4Exit
from l4.llm.agent_judge import JUDGE_ADAPTERS, AgentJudge, open_role_judge

UNIT = "openspec:add-x"


def cfg(**over) -> L4Config:
    return L4Config.model_validate(
        {
            "profiles": {
                "claude-c": {"adapter": "claude-code", "model": "sonnet", "auth": "subscription"},
                "claude-s": {"adapter": "claude-code", "model": "haiku", "auth": "subscription"},
                "codex-a": {"adapter": "codex", "model": "m", "auth": "subscription", "vendor": "openai"},
                "api": {"backend": "openai-chat", "model": "x"},
                "kiro-x": {"adapter": "kiro-cli", "vendor": "aws"},
            },
            "roles": {"implementer": ["codex-a"], "judges": ["claude-c"]},
            **over,
        }
    )


@pytest.fixture
def probe_ctx(tmp_path: Path) -> ProbeCtx:
    return ProbeCtx(environ={"PATH": "/usr/bin"}, cwd=tmp_path, run=lambda *a: None)


def make_request(selected):
    def make(prompt: str, schema: dict, timeout_s: int) -> RunRequest:
        raise AssertionError("no call is made in this test")

    return make


def roles(**chains: list[str]) -> dict:
    return {"roles": {"implementer": ["codex-a"], "judges": ["claude-c"], **chains}}


def test_clarifier_and_s1_roles_resolve_adapter_profiles(probe_ctx):
    fake = FakeAdapter([])
    config = cfg(**roles(clarifier=["claude-c"], s1_judge=["claude-s"]), clarifier={"s1_standin": "llm_boolean"})
    factory = Factory(config, probe_ctx, adapters={"claude-code": fake})
    for role, name in (("clarifier", "claude-c"), ("s1_judge", "claude-s")):
        opened = open_role_judge(factory, role, UNIT, make_request)
        assert isinstance(opened.judge, AgentJudge) and opened.selected.profile_name == name
        assert opened.selected.impl._inner is fake  # a subscription login is gated (L4-FAC-008)
    assert "claude-code" in JUDGE_ADAPTERS


@pytest.mark.parametrize("name", ["kiro-x", "api"])
def test_a_profile_that_cannot_serve_a_toolless_call_is_unavailable_not_a_usage_error(probe_ctx, name):
    config = cfg(**roles(s1_judge=[name]))
    with pytest.raises(RoleUnavailable) as err:
        open_role_judge(Factory(config, probe_ctx), "s1_judge", UNIT, make_request)
    assert name in str(err.value) and "tool-less" in str(err.value)


def test_an_empty_chain_is_unavailable(probe_ctx):
    with pytest.raises(RoleUnavailable):
        open_role_judge(Factory(cfg(), probe_ctx), "clarifier", UNIT, make_request)


def test_a_failing_probe_is_unavailable(probe_ctx):
    from l4.agents.base import ProbeResult

    bad = FakeAdapter([], probes={"auth": ProbeResult("auth", False, reason="logged out")})
    factory = Factory(cfg(**roles(clarifier=["claude-c"])), probe_ctx, adapters={"claude-code": bad})
    with pytest.raises(RoleUnavailable, match="logged out"):
        open_role_judge(factory, "clarifier", UNIT, make_request)


def app(tmp_path: Path) -> AppContext:
    from l4.redact import Redactor

    return AppContext(
        repo=tmp_path, config_path=None, log_format="human", verbosity=0, run_id="r-20261004T1000Z-0001",
        environ={"PATH": "/usr/bin", "L4_CACHE": str(tmp_path.parent / "cache")}, redactor=Redactor({}),
    )  # fmt: skip


def test_preflight_refuses_the_boolean_standin_without_an_s1_judge_chain(tmp_path):
    bad = cfg(**roles(), clarifier={"s1_standin": "llm_boolean"})
    with pytest.raises(L4Exit) as err:
        preflight_run_config(app(tmp_path), bad)
    assert err.value.code == ExitCode.USAGE_ERROR and "roles.s1_judge" in str(err.value)
    ok = cfg(**roles(s1_judge=["claude-s"]), clarifier={"s1_standin": "llm_boolean"})
    preflight_run_config(app(tmp_path), ok)
    preflight_run_config(app(tmp_path), cfg(**roles()))  # `none` needs no chain


def test_preflight_refuses_an_optional_chain_that_names_an_undefined_profile(tmp_path):
    for role in ("clarifier", "s1_judge"):
        bad = cfg(**roles(**{role: ["nope"]}))
        with pytest.raises(L4Exit) as err:
            preflight_run_config(app(tmp_path), bad)  # not exit 2 half way through a run, after quota is spent
        assert err.value.code == ExitCode.USAGE_ERROR and f"roles.{role}" in str(err.value)
        assert "nope" not in str(err.value)
    preflight_run_config(app(tmp_path), cfg(**roles(clarifier=["claude-s"], s1_judge=["claude-s"])))
