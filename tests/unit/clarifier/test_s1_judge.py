from pathlib import Path

import pytest

from l4.agents.base import ProbeCtx, RunRequest
from l4.agents.factory import Factory
from l4.agents.fake import FakeAdapter
from l4.clarifier.router import S1_SCHEMA, LlmBooleanJudge, S1Query, S1Unavailable, build_s1_judge
from l4.config.schema import L4Config
from l4.llm.agent_judge import StructuredResult
from l4.redact import Redactor

from .conftest import ScriptedBackend, limit_run, ok

QUERY = S1Query(state="Question: Which rate?\n\nContext:\nNone.", instruction="Is this a product decision?")


def test_boolean_judge_maps_to_probabilities_and_reports_unavailable():
    backend = ScriptedBackend(ok({"answer": True}), ok({"answer": False}))
    judge = LlmBooleanJudge(backend, redact=lambda t: t.replace("SECRET", "[REDACTED]"))
    assert judge.source == "llm_boolean"
    assert judge.ask(S1Query("state SECRET", "Is it?")) == 1.0 and judge.ask(QUERY) == 0.0
    first = backend.calls[0]
    assert first["schema"] == S1_SCHEMA and first["max_tokens"] > 0
    prompt = first["system"] + "\n" + "\n".join(m.content for m in first["messages"])
    assert "Is it?" in prompt and "[REDACTED]" in prompt and "SECRET" not in prompt
    assert '<l4:data kind="s1-state">' in prompt  # the state is information, never an instruction

    for bad in (
        StructuredResult("limit", detail="usage limit", run=limit_run()),
        StructuredResult("error", detail="boom"),
    ):
        with pytest.raises(S1Unavailable, match="usage limit|boom"):
            LlmBooleanJudge(ScriptedBackend(bad)).ask(QUERY)


def test_a_broken_reply_or_a_timeout_gets_one_more_call_then_is_unavailable():
    backend = ScriptedBackend(StructuredResult("timeout", detail="late"), ok({"answer": True}))
    assert LlmBooleanJudge(backend).ask(QUERY) == 1.0 and len(backend.calls) == 2
    wrong = ScriptedBackend(ok({"answer": "yes"}), StructuredResult("schema_invalid", detail="answer: wrong type"))
    with pytest.raises(S1Unavailable, match="no valid answer"):
        LlmBooleanJudge(wrong).ask(QUERY)
    assert len(wrong.calls) == 2


def cfg(standin: str, s1_judge: list[str]) -> L4Config:
    return L4Config.model_validate(
        {
            "profiles": {"c": {"adapter": "claude-code", "model": "m", "auth": "subscription", "vendor": "anthropic"},
                         "api": {"backend": "openai-chat", "model": "x"}},
            "roles": {"implementer": ["c"], "judges": ["c"], "s1_judge": s1_judge},
            "clarifier": {"s1_standin": standin},
        }
    )  # fmt: skip


def make_request(profile):
    def make(prompt: str, schema: dict, timeout_s: int) -> RunRequest:
        raise AssertionError("not called")

    return make


@pytest.fixture
def probe_ctx(tmp_path: Path) -> ProbeCtx:
    return ProbeCtx(environ={"PATH": "/usr/bin"}, cwd=tmp_path, run=lambda *a: None)


@pytest.mark.parametrize(
    ("standin", "chain", "why"),
    [
        ("none", ["c"], "s1_standin is none"),
        ("llm_boolean", [], "no profile"),
        ("llm_boolean", ["api"], "backend profile"),
    ],
)
def test_standin_none_or_no_usable_profile_means_s1_is_unavailable(probe_ctx, standin, chain, why):
    judge = build_s1_judge(cfg(standin, chain), Factory(cfg(standin, chain), probe_ctx), "openspec:x", make_request)
    with pytest.raises(S1Unavailable, match=why):
        judge.ask(QUERY)


def test_the_role_is_opened_on_first_use_not_before(probe_ctx):
    probes: list[str] = []

    class Spy(FakeAdapter):
        def probe(self, profile, step, ctx):
            probes.append(step)
            return super().probe(profile, step, ctx)

    config = cfg("llm_boolean", ["c"])
    judge = build_s1_judge(
        config, Factory(config, probe_ctx, adapters={"claude-code": Spy([])}), "openspec:x", make_request
    )
    assert probes == [] and judge.source == "llm_boolean"  # a question that a cheaper rule blocks costs no probe call
    with pytest.raises(AssertionError):  # `make_request` is reached: the call itself is not the point here
        judge.ask(QUERY)
    assert probes == ["binary", "auth", "quota", "hello"]


def test_s1_disabled_means_unavailable_even_with_the_standin(probe_ctx):
    config = cfg("llm_boolean", ["c"])
    config.verifier.s1.enabled = False
    judge = build_s1_judge(config, Factory(config, probe_ctx), "openspec:x", make_request)
    with pytest.raises(S1Unavailable, match="verifier.s1.enabled is false"):
        judge.ask(QUERY)


def test_cost_is_reported_per_call():
    from l4.agents.base import Usage

    costs = []
    first = StructuredResult("schema_invalid", detail="x", usage=Usage(cost_usd=0.02))
    backend = ScriptedBackend(first, ok({"answer": True}, cost=0.03))
    judge = LlmBooleanJudge(backend, redact=lambda t: t, on_cost=costs.append)
    assert judge.ask(QUERY) == 1.0
    assert costs == [0.02, 0.03]


def test_a_limit_keeps_the_run_and_later_questions_do_not_call_s1_again(monkeypatch, probe_ctx):
    from types import SimpleNamespace

    from l4.clarifier import router

    run = limit_run()
    backend = ScriptedBackend(StructuredResult("limit", detail="usage limit", run=run))
    opened = SimpleNamespace(selected=SimpleNamespace(profile_name="judge"), judge=backend)
    monkeypatch.setattr(router, "open_role_judge", lambda *a: opened)
    config = cfg("llm_boolean", ["c"])
    judge = build_s1_judge(config, Factory(config, probe_ctx), "openspec:x", make_request)
    with pytest.raises(S1Unavailable) as first:
        judge.ask(QUERY)
    assert first.value.run is run
    with pytest.raises(S1Unavailable, match="usage limit") as second:
        judge.ask(QUERY)
    assert len(backend.calls) == 1 and second.value.run is None  # the limit is recorded once, by the first


# --- a usable System-One profile comes first --------------------------------------------------------------------


def s1_cfg(standin: str, chain: list[str], key_env: str = "TYPESAFE_API_KEY") -> L4Config:
    config = cfg(standin, chain)
    config.profiles["jev"] = config.profiles["api"].model_copy(
        update={"backend": "system-one", "engine": "jev", "model": "jev-1.13.0", "api_key_env": key_env}
    )
    return config


def build(config, probe_ctx, environ, tmp_path):
    from l4.redact import Redactor

    return build_s1_judge(
        config, Factory(config, probe_ctx), "openspec:x", make_request,
        redactor=Redactor({}), environ=environ, log_path=tmp_path / "s1.jsonl",
    )  # fmt: skip


def test_a_usable_system_one_profile_wins_over_the_chain_and_the_standin(probe_ctx, tmp_path):
    config = s1_cfg("llm_boolean", ["jev", "c"])
    judge = build(config, probe_ctx, {"TYPESAFE_API_KEY": "tsk_" + "k" * 24}, tmp_path)
    assert judge.source == "system_one" and judge.question_set == "clarifier-s1@2"
    judge.close()  # never started: a no-op


def test_an_unusable_system_one_profile_falls_back_to_the_standin_on_the_adapter_profile(probe_ctx, tmp_path):
    config = s1_cfg("llm_boolean", ["jev", "c"])
    chosen: list[str] = []

    def spy(selected):
        chosen.append(selected.profile_name)
        return make_request(selected)

    judge = build_s1_judge(
        config, Factory(config, probe_ctx, adapters={"claude-code": FakeAdapter([])}), "openspec:x", spy,
        redactor=Redactor({}), environ={}, log_path=tmp_path / "s1.jsonl",  # the key variable is not set
    )  # fmt: skip
    assert judge.source == "llm_boolean"
    with pytest.raises(AssertionError):  # `make_request` is reached: the call itself is not the point here
        judge.ask(QUERY)
    assert chosen == ["c"]  # the backend profile `jev` in front of it is skipped, not tried as an adapter


def test_an_unusable_system_one_profile_without_the_standin_says_why(probe_ctx, tmp_path):
    config = s1_cfg("none", ["jev", "c"])
    judge = build(config, probe_ctx, {}, tmp_path)
    with pytest.raises(S1Unavailable, match="s1_standin is none.*System One: .*TYPESAFE_API_KEY"):
        judge.ask(QUERY)


def test_no_redactor_means_no_system_one_path(probe_ctx):
    config = s1_cfg("none", ["jev"])
    judge = build_s1_judge(config, Factory(config, probe_ctx), "openspec:x", make_request)
    with pytest.raises(S1Unavailable, match="s1_standin is none"):
        judge.ask(QUERY)
