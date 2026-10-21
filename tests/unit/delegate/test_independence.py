"""The delegate is never the mind that asked or judged the question (delegate-answers 3.2; L4-DLG-002, D3;
SCN-DLG-06, SCN-DLG-07, SCN-DLG-08, SCN-DLG-08a, SCN-DLG-08b)."""

from pathlib import Path

import pytest

from l4.agents.base import ProbeCtx
from l4.agents.factory import Factory
from l4.agents.fake import FakeAdapter
from l4.availability.errors import RoleUnavailable
from l4.config.schema import L4Config, Profile, RolesCfg
from l4.delegate.independence import (
    DELEGATE_SERVES,
    Asker,
    askers,
    delegate_constraint,
    independence_escalation,
    model_key,
    same_mind,
)
from l4.state.ledger import LedgerEvent

STAMP = "2026-10-18T10:00:00Z"
PROFILES = {
    "claude-opus": Profile(adapter="claude-code", model="claude-opus-5-5", vendor="anthropic"),
    "claude-sonnet": Profile(adapter="claude-code", model="claude-sonnet-5", vendor="anthropic"),
    "codex-sol": Profile(adapter="codex", model="gpt-6.1-sol", vendor="openai"),
    "judge-opus": Profile(adapter="claude-code", model="claude-opus-5-5", vendor="anthropic"),
    "delegate-opus": Profile(adapter="claude-code", model="claude-opus-5-5", vendor="anthropic"),
    "delegate-sol": Profile(adapter="codex", model="gpt-6.1-sol", vendor="openai"),
    "delegate-sonnet": Profile(adapter="claude-code", model="claude-sonnet-5", vendor="anthropic"),
    "zen": Profile(adapter="opencode", model="deepseek-v4.1-flash", vendor="deepseek"),
    "kiro": Profile(adapter="kiro-cli", model="claude-sonnet-4.5", vendor="anthropic"),
    "kiro-auto": Profile(adapter="kiro-cli", model="auto"),
    "kiro-bare": Profile(adapter="kiro-cli"),
    "or-auto": Profile(adapter="opencode", model="openrouter/auto", vendor="unknown"),
    "delegate-or": Profile(adapter="opencode", model="openrouter/anthropic/claude-opus-5-5", vendor="anthropic"),
    "delegate-a": Profile(
        adapter="opencode", model="openrouter/anthropic/claude-opus-5.5:thinking", vendor="anthropic"
    ),
    "delegate-b": Profile(
        adapter="opencode", model="google-vertex-anthropic/claude-opus-5-5@20261001", vendor="anthropic"
    ),
    "delegate-c": Profile(
        adapter="opencode", model="amazon-bedrock/us.anthropic.claude-opus-5-5-20261001-v1:0", vendor="anthropic"
    ),
    "delegate-gpt": Profile(adapter="opencode", model="openrouter/openai/gpt-6.1", vendor="openai"),
    "delegate-opus-free": Profile(adapter="opencode", model="openrouter/anthropic/claude-opus-5-5:free"),
    "delegate-free": Profile(adapter="opencode", model="openrouter/deepseek/deepseek-v4.1-flash:free"),
    "oc-impl": Profile(adapter="opencode", model="opencode-go/deepseek-v4.1-flash", vendor="deepseek"),
    "lint-cmd": Profile(adapter="command", model="lint", vendor="local", options={"argv": ["lint", "{prompt_file}"]}),
}


def event(seq: int, event_type: str, **data) -> LedgerEvent:
    return LedgerEvent(STAMP, "r-1", "u", seq, event_type, data)


def raised(seq: int = 1, qid: str = "Q-001", **data) -> LedgerEvent:
    return event(seq, "question.raised", id=qid, kind=data.pop("kind", "technical"), **data)


def selected(seq: int, role: str, profile: str) -> LedgerEvent:
    return event(seq, "availability.selected", role=role, selected=profile)


def judged(seq: int, round_no: int, profile: str, model: str | None) -> LedgerEvent:
    return event(seq, "verify.judge", round=round_no, profile=profile, model=model, status="ok")


def names(found: tuple[Asker, ...]) -> list[tuple[str | None, str | None]]:
    return [(a.profile, a.model) for a in found]


# -- who asked ---------------------------------------------------------------------------------------------------


def test_a_step_question_is_asked_by_the_profile_and_model_it_recorded():
    found = askers([raised(profile="claude-opus", model="claude-opus-5-5")], "Q-001")
    assert names(found) == [("claude-opus", "claude-opus-5-5")] and found[0].role == "asked"


def test_a_verdict_question_is_asked_by_the_judges_of_its_round():
    judges = [{"profile": "judge-opus", "model": "claude-opus-5-5"}, {"profile": "codex-sol", "model": None}]
    found = askers([raised(kind="verdict", judges=judges)], "Q-001")
    assert names(found) == [("judge-opus", "claude-opus-5-5"), ("codex-sol", None)]
    assert {a.role for a in found} == {"judged"}


def test_a_question_of_a_fix_unit_is_found_under_its_qualified_id():
    events = [
        raised(1, profile="claude-opus", model="m-parent"),
        raised(2, fix_unit="fix-1", profile="codex-sol", model="m-fix"),
    ]
    assert names(askers(events, "fix-1/Q-001")) == [("codex-sol", "m-fix")]
    assert names(askers(events, "Q-001")) == [("claude-opus", "m-parent")]


def test_an_old_raise_counts_every_implementer():
    """SCN-DLG-08: a `question.raised` written before this change names nobody: fail safe."""
    events = [
        selected(1, "implementer", "codex-sol"),
        selected(2, "implementer", "claude-sonnet"),
        selected(3, "judges", "judge-opus"),
        raised(4),
    ]
    assert names(askers(events, "Q-001")) == [("codex-sol", None), ("claude-sonnet", None)]


def test_an_old_verdict_raise_counts_every_judge_of_the_unit():
    events = [
        selected(1, "implementer", "codex-sol"),
        judged(2, 1, "judge-opus", "claude-opus-5-5"),
        judged(3, 2, "judge-opus", "claude-opus-5-5"),
        judged(4, 2, "claude-sonnet", None),
        raised(5, kind="verdict", source="verifier", round=2),
    ]
    # every judge of the unit's rounds, and (F9) the implementer profile that ran its steps
    assert names(askers(events, "Q-001")) == [
        ("judge-opus", "claude-opus-5-5"),
        ("claude-sonnet", None),
        ("codex-sol", None),
    ]


def test_a_question_with_no_raise_event_counts_everyone():
    events = [selected(1, "implementer", "codex-sol"), judged(2, 1, "judge-opus", None)]
    assert {a.profile for a in askers(events, "Q-009")} == {"codex-sol", "judge-opus"}


@pytest.mark.parametrize("source", ["intake_lint", "intake_open_questions"])
def test_an_intake_question_has_no_asker(source):
    """SCN-DLG-08b: no agent step is behind it, so it vetoes nothing."""
    events = [selected(1, "implementer", "codex-sol"), raised(2, kind="ambiguous", source=source)]
    assert askers(events, "Q-001") == ()


# -- the constraint ----------------------------------------------------------------------------------------------


def verdict_of(profile: str, model: str | None):
    return (Asker(profile, model, "judged"),)


def test_model_mode_vetoes_the_name_and_the_model():
    """SCN-DLG-06: `delegate-opus` runs the model that judged, under another name."""
    check = delegate_constraint(verdict_of("judge-opus", "claude-opus-5-5"), "model")
    assert (
        check("delegate-opus", PROFILES["delegate-opus"]) == "independence: model claude-opus-5-5 judged the question"
    )
    assert check("judge-opus", PROFILES["judge-opus"]) == "independence: model claude-opus-5-5 judged the question"
    assert check("delegate-sol", PROFILES["delegate-sol"]) is None


def test_model_mode_ignores_a_date_suffix_and_the_context_marker():
    check = delegate_constraint(verdict_of("judge-opus", "claude-opus-5-5-20261001[1m]"), "model")
    assert check("delegate-opus", PROFILES["delegate-opus"]) is not None


def test_model_mode_takes_the_configured_model_of_an_asker_that_recorded_none():
    asker = (Asker("claude-opus", None, "asked"),)
    # with no configuration to resolve it from, an unknown model vetoes (review F2: fail safe, D3)
    assert delegate_constraint(asker, "model")("delegate-opus", PROFILES["delegate-opus"]) is not None
    check = delegate_constraint(asker, "model", profiles=PROFILES)
    assert check("delegate-opus", PROFILES["delegate-opus"]) == "independence: model claude-opus-5-5 asked the question"


def test_profile_mode_vetoes_the_name_only():
    check = delegate_constraint(verdict_of("judge-opus", "claude-opus-5-5"), "profile")
    assert check("delegate-opus", PROFILES["delegate-opus"]) is None  # the same model under another name passes
    assert check("judge-opus", PROFILES["judge-opus"]) == "independence: profile judge-opus judged the question"


def test_no_asker_vetoes_nothing():
    for mode in ("model", "profile"):
        check = delegate_constraint((), mode)
        assert check("delegate-opus", PROFILES["delegate-opus"]) is None


# -- the factory -------------------------------------------------------------------------------------------------


def factory(tmp_path: Path, chain: list[str]) -> Factory:
    cfg = L4Config(profiles=PROFILES, roles=RolesCfg(delegate=chain))
    ctx = ProbeCtx(environ={"PATH": "/usr/bin"}, cwd=tmp_path, run=lambda *a: None)
    adapters = {name: FakeAdapter([]) for name in ("claude-code", "codex", "opencode", "kiro-cli", "command")}
    return Factory(cfg, ctx, adapters=adapters)


def test_the_verdict_a_claude_judge_raised_goes_to_codex(tmp_path):
    check = delegate_constraint(verdict_of("judge-opus", "claude-opus-5-5"), "model")
    picked = factory(tmp_path, ["delegate-opus", "delegate-sol"]).for_role(
        "delegate", "u", serves=DELEGATE_SERVES, constraints=[check]
    )
    assert picked.profile_name == "delegate-sol"
    assert [(s["profile"], s["step"], s["reason"]) for s in picked.skipped] == [
        ("delegate-opus", "constraint", "independence: model claude-opus-5-5 judged the question")
    ]


def test_another_adapter_does_not_serve_the_role(tmp_path):
    """SCN-DLG-08a (0.4.22, L4-DLG-015): a `command` profile has no read-only mode: skipped, the walk goes on; an
    `opencode` and a `kiro-cli` profile are selected."""
    picked = factory(tmp_path, ["lint-cmd", "delegate-sol"]).for_role("delegate", "u", serves=DELEGATE_SERVES)
    assert picked.profile_name == "delegate-sol"
    assert [(s["profile"], s["step"]) for s in picked.skipped] == [("lint-cmd", "serves")]
    assert set(DELEGATE_SERVES) == {"claude-code", "codex", "opencode", "kiro-cli", "fake"}
    for name in ("zen", "kiro"):
        assert factory(tmp_path, [name]).for_role("delegate", "u", serves=DELEGATE_SERVES).profile_name == name


def test_no_profile_left_is_an_escalation(tmp_path):
    """SCN-DLG-07: the only delegate is the model that asked."""
    check = delegate_constraint((Asker("claude-opus", "claude-opus-5-5", "asked"),), "model")
    with pytest.raises(RoleUnavailable) as err:
        factory(tmp_path, ["delegate-opus"]).for_role("delegate", "u", serves=DELEGATE_SERVES, constraints=[check])
    assert independence_escalation(err.value) == "no independent delegate"


def test_an_unusable_chain_is_not_an_independence_escalation(tmp_path):
    """A chain that is empty, or that is out only because an adapter cannot serve the role, is another cause."""
    with pytest.raises(RoleUnavailable) as err:
        factory(tmp_path, []).for_role("delegate", "u", serves=DELEGATE_SERVES)
    assert independence_escalation(err.value) is None
    with pytest.raises(RoleUnavailable) as only_serves:
        factory(tmp_path, ["lint-cmd"]).for_role("delegate", "u", serves=DELEGATE_SERVES)
    assert independence_escalation(only_serves.value) is None


def test_an_independence_veto_next_to_a_binary_failure_is_not_an_independence_escalation(tmp_path):
    from l4.agents.base import ProbeResult

    class NoBinary(FakeAdapter):
        def probe(self, profile, step, ctx):
            return ProbeResult(step, False, reason="not installed")

    check = delegate_constraint((Asker("claude-opus", "claude-opus-5-5", "asked"),), "model")
    cfg = L4Config(profiles=PROFILES, roles=RolesCfg(delegate=["delegate-opus", "delegate-sol"]))
    ctx = ProbeCtx(environ={"PATH": "/usr/bin"}, cwd=tmp_path, run=lambda *a: None)
    fac = Factory(cfg, ctx, adapters={"claude-code": FakeAdapter([]), "codex": NoBinary([])})
    with pytest.raises(RoleUnavailable) as err:
        fac.for_role("delegate", "u", serves=DELEGATE_SERVES, constraints=[check])
    assert independence_escalation(err.value) is None  # `delegate-sol` is out for a cause only a fix ends (L4-DLG-013)


# -- F9: a verdict is never answered by the model that wrote the code (owner decision, 2026-10-19) ----------------


def verdict_events(*extra: LedgerEvent) -> list[LedgerEvent]:
    judges = [{"profile": "judge-opus", "model": "claude-opus-5-5"}]
    return [selected(1, "implementer", "codex-sol"), raised(2, kind="verdict", judges=judges), *extra]


def test_a_verdict_question_is_asked_by_the_judges_and_the_implementer_profiles():
    found = askers(verdict_events(), "Q-001")
    assert names(found) == [("judge-opus", "claude-opus-5-5"), ("codex-sol", None)]
    assert [a.role for a in found] == ["judged", "asked"]


def test_a_verdict_question_falls_back_to_the_configured_implementer_chain():
    judges = [{"profile": "judge-opus", "model": "claude-opus-5-5"}]
    events = [raised(1, kind="verdict", judges=judges)]  # the ledger names no implementer step
    assert names(askers(events, "Q-001", configured=("codex-sol",))) == [
        ("judge-opus", "claude-opus-5-5"),
        ("codex-sol", None),
    ]
    assert names(askers(events, "Q-001")) == [("judge-opus", "claude-opus-5-5")]
    with_step = [selected(0, "implementer", "claude-sonnet"), *events]  # the ledger wins over the configuration
    assert [a.profile for a in askers(with_step, "Q-001", configured=("codex-sol",))] == ["judge-opus", "claude-sonnet"]


def test_a_technical_question_is_not_asked_by_the_judges_or_other_implementers():
    events = [selected(1, "implementer", "codex-sol"), raised(2, profile="claude-sonnet", model="claude-sonnet-5")]
    assert names(askers(events, "Q-001", configured=("codex-sol",))) == [("claude-sonnet", "claude-sonnet-5")]


def test_a_verdict_question_never_goes_to_the_implementers_model(tmp_path):
    """SCN-DLG-06a, the reference configuration: implementer codex-sol (gpt-6.1-sol), judge judge-opus, chain
    [delegate-opus, delegate-sol]: the judge's model and the implementer's model are both out."""
    check = delegate_constraint(askers(verdict_events(), "Q-001"), "model", profiles=PROFILES)
    with pytest.raises(RoleUnavailable) as err:
        factory(tmp_path, ["delegate-opus", "delegate-sol"]).for_role(
            "delegate", "u", serves=DELEGATE_SERVES, constraints=[check]
        )
    assert independence_escalation(err.value) == "no independent delegate"
    assert err.value.steps == ("constraint", "constraint")
    assert "independence: model claude-opus-5-5 judged the question" in str(err.value)
    assert "independence: model gpt-6.1-sol asked the question" in str(err.value)


def test_an_independent_third_model_answers_the_verdict(tmp_path):
    check = delegate_constraint(askers(verdict_events(), "Q-001"), "model", profiles=PROFILES)
    picked = factory(tmp_path, ["delegate-opus", "delegate-sol", "delegate-sonnet"]).for_role(
        "delegate", "u", serves=DELEGATE_SERVES, constraints=[check]
    )
    assert picked.profile_name == "delegate-sonnet"


def test_profile_mode_vetoes_the_implementers_name_for_a_verdict():
    check = delegate_constraint(askers(verdict_events(), "Q-001"), "profile", profiles=PROFILES)
    assert check("codex-sol", PROFILES["codex-sol"]) == "independence: profile codex-sol asked the question"
    assert check("delegate-sol", PROFILES["delegate-sol"]) is None


# -- M1: the model the implementer's steps reported is an asker's model too (D3) ---------------------------------

ALIAS_PROFILES = {
    "claude-impl": Profile(adapter="claude-code", model="opus", vendor="anthropic"),  # an alias the CLI accepts
    "judge-sol": Profile(adapter="codex", model="gpt-6.1-sol", vendor="openai"),
    "delegate-opus": Profile(adapter="claude-code", model="claude-opus-5-5", vendor="anthropic"),
}


def alias_events() -> list[LedgerEvent]:
    served = "claude-opus-5-5"
    return [
        selected(1, "implementer", "claude-impl"),
        event(2, "agent.finished", task="1.1", phase="red", status="ok", model=served),
        event(3, "agent.finished", task="1.1", phase="green", status="ok", model=served),
        event(4, "agent.finished", task="1.1", phase="green", status="ok", model=None),
        judged(5, 1, "judge-sol", "gpt-6.1-sol"),
        raised(6, kind="verdict", judges=[{"profile": "judge-sol", "model": "gpt-6.1-sol"}]),
    ]


def test_a_verdict_question_counts_the_models_the_implementer_steps_reported():
    found = askers(alias_events(), "Q-001", ("claude-impl",))
    assert (None, "claude-opus-5-5", "asked") in [(a.profile, a.model, a.role) for a in found]
    assert len([a for a in found if a.profile is None]) == 1  # once, whatever the step count; none for a null model
    check = delegate_constraint(found, "model", profiles=ALIAS_PROFILES)
    assert (
        check("delegate-opus", ALIAS_PROFILES["delegate-opus"])
        == "independence: model claude-opus-5-5 asked the question"
    )


def test_the_alias_implementer_leaves_a_verdict_with_no_independent_delegate(tmp_path):
    found = askers(alias_events(), "Q-001", ("claude-impl",))
    check = delegate_constraint(found, "model", profiles=ALIAS_PROFILES)
    with pytest.raises(RoleUnavailable) as err:
        factory(tmp_path, ["delegate-opus"]).for_role("delegate", "u", serves=DELEGATE_SERVES, constraints=[check])
    assert independence_escalation(err.value) == "no independent delegate"


def test_the_fail_safe_branches_count_the_reported_models_too():
    old = [e for e in alias_events() if e.type != "question.raised"] + [raised(7, kind="verdict", source="verifier")]
    for events in (old, [e for e in alias_events() if e.type != "question.raised"]):
        assert (None, "claude-opus-5-5") in [(a.profile, a.model) for a in askers(events, "Q-001", ("claude-impl",))]


def test_a_technical_question_stays_asked_by_the_step_that_raised_it():
    events = [*alias_events()[:4], raised(9, profile="claude-impl", model="claude-opus-5-5")]
    assert names(askers(events, "Q-001")) == [("claude-impl", "claude-opus-5-5")]


# -- one model identity for every adapter (L4-DLG-018, 0.4.22 A4) -----------------------------------------------------

OPUS_JUDGE = verdict_of("judge-opus", "claude-opus-5-5")


def test_a_provider_prefix_does_not_hide_the_model(tmp_path):  # SCN-DLG-64
    check = delegate_constraint(OPUS_JUDGE, "model")
    assert check("delegate-or", PROFILES["delegate-or"]) == "independence: model claude-opus-5-5 judged the question"
    picked = factory(tmp_path, ["delegate-or", "delegate-sonnet"]).for_role(
        "delegate", "u", serves=DELEGATE_SERVES, constraints=[check]
    )
    assert picked.profile_name == "delegate-sonnet"
    assert [(s["profile"], s["step"], s["reason"]) for s in picked.skipped] == [
        ("delegate-or", "constraint", "independence: model claude-opus-5-5 judged the question")
    ]


def test_a_slug_suffix_is_the_same_model(tmp_path):  # SCN-DLG-65
    asked = (Asker("codex-sol", "gpt-6.1-sol", "asked"),)
    check = delegate_constraint(asked, "model")
    assert check("delegate-gpt", PROFILES["delegate-gpt"]) == "independence: model gpt-6.1-sol asked the question"
    with pytest.raises(RoleUnavailable) as err:
        factory(tmp_path, ["delegate-gpt"]).for_role("delegate", "u", serves=DELEGATE_SERVES, constraints=[check])
    assert independence_escalation(err.value) == "no independent delegate"


def test_a_kiro_dotted_id_is_the_claude_id():
    check = delegate_constraint((Asker("claude-opus", "claude-opus-5.5", "asked"),), "model")
    assert check("delegate-opus", PROFILES["delegate-opus"]) == "independence: model claude-opus-5.5 asked the question"
    assert model_key("claude-opus-5.5") == model_key("claude-opus-5-5")


def test_auto_vetoes_under_model(tmp_path):  # SCN-DLG-62
    check = delegate_constraint((Asker("claude-opus", "claude-opus-5-5", "asked"),), "model")
    assert (
        check("kiro-auto", PROFILES["kiro-auto"]) == "independence: model: delegate profile kiro-auto is routed (auto)"
    )
    assert (
        check("kiro-bare", PROFILES["kiro-bare"]) == "independence: model: delegate profile kiro-bare is routed (auto)"
    )
    assert check("or-auto", PROFILES["or-auto"]) == "independence: model: delegate profile or-auto is routed (auto)"
    with pytest.raises(RoleUnavailable) as err:
        factory(tmp_path, ["kiro-auto"]).for_role("delegate", "u", serves=DELEGATE_SERVES, constraints=[check])
    assert independence_escalation(err.value) == "no independent delegate"
    assert model_key("auto") is None and model_key("openrouter/auto") is None and model_key(None) is None
    assert model_key("") is None


def test_a_tag_a_date_or_a_bedrock_shape_is_the_same_model(tmp_path):  # SCN-DLG-95
    check = delegate_constraint(OPUS_JUDGE, "model")
    picked = factory(tmp_path, ["delegate-a", "delegate-b", "delegate-c", "delegate-sonnet"]).for_role(
        "delegate", "u", serves=DELEGATE_SERVES, constraints=[check]
    )
    assert picked.profile_name == "delegate-sonnet"
    assert {s["profile"]: s["reason"] for s in picked.skipped} == dict.fromkeys(
        ("delegate-a", "delegate-b", "delegate-c"), "independence: model claude-opus-5-5 judged the question"
    )
    assert model_key("claude-opus-5-5[1m]") == model_key("claude-opus-5-5-20261001") == "claude-opus-5-5"
    assert model_key("opencode-go/deepseek-v4.1-flash") == model_key("openrouter/deepseek/deepseek-v4.1-flash:free")


def test_a_free_tag_does_not_hide_the_model():  # SCN-DLG-96
    implementer = (Asker("oc-impl", "opencode-go/deepseek-v4.1-flash", "asked"),)
    check = delegate_constraint(implementer, "model")
    assert check("delegate-free", PROFILES["delegate-free"]) == (
        "independence: model opencode-go/deepseek-v4.1-flash asked the question"
    )
    judged = delegate_constraint(OPUS_JUDGE, "model")  # the `:free` Opus delegate against an Opus judge
    assert judged("delegate-opus-free", PROFILES["delegate-opus-free"]) == (
        "independence: model claude-opus-5-5 judged the question"
    )


def test_a_kiro_implementer_on_auto_vetoes_every_delegate(tmp_path):  # SCN-DLG-112
    check = delegate_constraint((Asker("kiro-auto", "auto", "asked"),), "model", profiles=PROFILES)
    assert "has no known model" in (check("delegate-opus", PROFILES["delegate-opus"]) or "")
    with pytest.raises(RoleUnavailable) as err:
        factory(tmp_path, ["delegate-opus", "delegate-sol"]).for_role(
            "delegate", "u", serves=DELEGATE_SERVES, constraints=[check]
        )
    assert independence_escalation(err.value) == "no independent delegate"
    unresolved = delegate_constraint((Asker("kiro-bare", None, "asked"),), "model", profiles=PROFILES)
    assert unresolved("delegate-sol", PROFILES["delegate-sol"]) is not None  # no model recorded, none configured


def test_profile_mode_lets_auto_serve():
    check = delegate_constraint((Asker("claude-opus", "claude-opus-5-5", "asked"),), "profile")
    assert check("kiro-auto", PROFILES["kiro-auto"]) is None and check("or-auto", PROFILES["or-auto"]) is None
    assert check("claude-opus", PROFILES["claude-opus"]) == "independence: profile claude-opus asked the question"


def test_the_prefix_rule_vetoes_a_family_and_not_a_neighbour_that_only_shares_letters():
    assert same_mind("gpt-6-1", "gpt-6-1-sol") and same_mind("claude-opus-5", "claude-opus-5-5")
    assert not same_mind("gpt-6-1", "gpt-6-12") and not same_mind("claude-opus-5", "claude-sonnet-5")


def test_the_served_model_is_compared_the_same_way():
    from types import SimpleNamespace

    from l4.delegate.run import _Pass

    fake = SimpleNamespace(
        profiles=PROFILES,
        implementers=(),
        cfg=SimpleNamespace(independence="model"),
    )
    chosen = SimpleNamespace(profile=PROFILES["delegate-sol"], profile_name="delegate-sol")
    events = [raised(profile="claude-opus", model="claude-opus-5-5")]
    veto = _Pass._served_veto(fake, chosen, "openrouter/anthropic/claude-opus-5.5:thinking", events, "Q-001")
    assert veto == "independence: model claude-opus-5-5 asked the question (served by delegate-sol)"
    assert _Pass._served_veto(fake, chosen, "gpt-6.1-sol", events, "Q-001") is None


def test_a_hyphenated_bedrock_region_prefix_is_the_same_model():  # SCN-DLG-95
    from l4.availability.vendor import family_vendor
    from l4.delegate.independence import same_mind

    for prefix in ("us-gov.", "eu-central.", "us.", ""):
        name = f"amazon-bedrock/{prefix}anthropic.claude-opus-5-5-20261001-v1:0"
        assert model_key(name) == "claude-opus-5-5", name
        assert same_mind(model_key(name) or "", model_key("claude-opus-5-5") or "")
        assert family_vendor(name) == "anthropic", name
