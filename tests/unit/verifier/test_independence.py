import pytest
from pydantic import ValidationError

from l4.agents.factory import RoleUnavailable
from l4.config.schema import L4Config
from l4.exitcodes import ExitCode
from l4.verifier.ladder import require_independent_judge
from l4.verifier.selection import assess_independence


def config(independence: str = "different_vendor", **profiles: dict) -> L4Config:
    return L4Config.model_validate(
        {
            "verifier": {"independence": independence},
            "profiles": {
                "impl": {"adapter": "codex", "vendor": "openai", "model": "gpt-x"},
                "judge": {"adapter": "claude-code", "vendor": "anthropic", "model": "claude-y"},
                **profiles,
            },
        }
    )


def test_a_judge_of_another_vendor_is_independent():
    require_independent_judge(config(), ["impl"], "judge")


@pytest.mark.parametrize(
    ("override", "why"),
    [
        ({"judge": {"adapter": "opencode", "vendor": "openai"}}, "share the vendor"),
        ({"judge": {"adapter": "opencode"}}, "no known vendor"),  # vendor not declared: never independent
        ({"judge": {"adapter": "opencode", "vendor": "unknown"}}, "no known vendor"),
        ({"impl": {"adapter": "opencode"}}, "implementer profile impl has no known vendor"),
        ({"judge": {"adapter": "codex"}}, "share the vendor"),  # the vendor is the tool's: no declaration needed
    ],
)
def test_otherwise_the_role_is_unavailable_with_exit_12(override, why):
    with pytest.raises(RoleUnavailable, match="no independent verifier") as exc:
        require_independent_judge(config(**override), ["impl"], "judge")
    assert exc.value.code is ExitCode.WAITING_CAPACITY and why in str(exc.value)


def test_every_implementer_profile_of_the_unit_counts_not_just_the_first():
    cfg = config(fallback={"adapter": "opencode", "vendor": "anthropic"})
    with pytest.raises(RoleUnavailable, match="fallback"):
        require_independent_judge(cfg, ["impl", "fallback"], "judge")


def test_different_model_compares_model_ids_and_none_checks_nothing():
    same = config("different_model", judge={"adapter": "claude-code", "vendor": "anthropic", "model": "gpt-x"})
    with pytest.raises(RoleUnavailable, match="share the model"):
        require_independent_judge(same, ["impl"], "judge")
    require_independent_judge(config("different_model"), ["impl"], "judge")
    require_independent_judge(config("none", judge={"adapter": "opencode", "vendor": "openai"}), ["impl"], "judge")


def profiles(**kw: dict) -> L4Config:
    return L4Config.model_validate({"profiles": kw})


@pytest.mark.parametrize(
    ("adapter", "vendor"), [("claude-code", "openai"), ("codex", "anthropic"), ("claude-code", "unknown")]
)
def test_a_profile_whose_declared_vendor_contradicts_its_tool_is_rejected_at_load(adapter, vendor):
    with pytest.raises(ValidationError) as exc:
        profiles(p={"adapter": adapter, "vendor": vendor})
    message = str(exc.value).split("Value error,", 1)[1].split("[type=")[0]
    assert "contradicts" in message and vendor not in message.replace(adapter, "").replace("anthropic", "").replace(
        "openai", ""
    )  # names the tool's vendor, never the configured value


def test_a_tool_vendor_may_be_declared_when_it_agrees():
    cfg = profiles(a={"adapter": "claude-code", "vendor": "Anthropic"}, b={"adapter": "codex", "vendor": "openai"})
    assert cfg.profiles["a"].adapter == "claude-code"


def test_codex_implementer_and_claude_code_judge_are_verified_from_the_tool_vendors():
    cfg = profiles(impl={"adapter": "codex"}, judge={"adapter": "claude-code"})
    inde = assess_independence(cfg, ["impl"], "judge")
    assert inde.status == "verified (different_vendor)"
    assert (inde.judge.vendor, inde.judge.provenance) == ("anthropic", "tool")
    assert (inde.implementers[0].vendor, inde.implementers[0].provenance) == ("openai", "tool")
    require_independent_judge(cfg, ["impl"], "judge")


def test_opencode_judge_with_a_declared_vendor_is_declared_unverified():
    cfg = profiles(
        impl={"adapter": "codex"}, judge={"adapter": "opencode", "model": "opencode/big-pickle", "vendor": "zhipu"}
    )
    inde = assess_independence(cfg, ["impl"], "judge")
    assert inde.status == "declared (unverified)"
    assert inde.line().startswith("independence: declared (unverified): judge zhipu (declared)")


@pytest.mark.parametrize(
    ("served", "vendor", "provenance"),
    [
        ("claude-haiku-4-5-20251001", "anthropic", "served"),
        ("gpt-5.2-codex", "openai", "served"),
        ("o3-mini", "openai", "served"),
        ("gemini-3-pro", "google", "served"),
        ("mystery-1", "unknown", "unknown"),
    ],
)
def test_a_served_model_gives_the_vendor_not_the_declaration(served, vendor, provenance):
    cfg = profiles(impl={"adapter": "codex"}, judge={"adapter": "opencode", "vendor": "zhipu"})
    judge = assess_independence(cfg, ["impl"], "judge", served_model=served).judge
    assert (judge.vendor, judge.provenance) == (vendor, provenance)


def test_a_served_model_of_the_implementer_vendor_is_not_independent_and_unknown_never_is():
    cfg = profiles(impl={"adapter": "codex"}, judge={"adapter": "opencode", "vendor": "zhipu"})
    assert not assess_independence(cfg, ["impl"], "judge", served_model="gpt-5").independent
    assert not assess_independence(cfg, ["impl"], "judge", served_model="mystery-1").independent
    assert assess_independence(cfg, ["impl"], "judge", served_model="claude-opus-4-1").independent


@pytest.mark.parametrize("declared", ["OpenAI", " openai ", "OPENAI"])
def test_a_declared_vendor_is_compared_without_case_or_spaces(declared):
    cfg = profiles(impl={"adapter": "codex"}, judge={"adapter": "opencode", "vendor": declared})
    with pytest.raises(RoleUnavailable, match="share the vendor"):
        require_independent_judge(cfg, ["impl"], "judge")
    assert assess_independence(cfg, ["impl"], "judge").judge.vendor == "openai"


def test_two_declared_vendors_differing_only_in_case_are_one_vendor():
    cfg = profiles(impl={"adapter": "opencode", "vendor": "Zhipu"}, judge={"adapter": "kiro-cli", "vendor": "zhipu"})
    with pytest.raises(RoleUnavailable, match="share the vendor"):
        require_independent_judge(cfg, ["impl"], "judge")


@pytest.mark.parametrize("served", ["gpt-5", "mystery-1"])
def test_a_judge_that_is_not_independent_is_never_reported_verified(served):
    cfg = profiles(impl={"adapter": "codex"}, judge={"adapter": "claude-code"})
    record = assess_independence(cfg, ["impl"], "judge", served_model=served)
    assert record.status == "not independent (different_vendor)"
    assert record.line().startswith("independence: not independent (different_vendor): ")
    assert record.to_json()["status"] == "not independent (different_vendor)"


@pytest.mark.parametrize(
    "served", ["us.anthropic.claude-sonnet-4-5-20250929-v1:0", "anthropic.claude-3-7-sonnet", "claude-opus-4-1@2025"]
)
def test_a_bedrock_or_vertex_claude_id_is_anthropic(served):
    cfg = profiles(impl={"adapter": "codex"}, judge={"adapter": "claude-code"})
    record = assess_independence(cfg, ["impl"], "judge", served_model=served)
    assert (record.judge.vendor, record.judge.provenance, record.status) == (
        "anthropic", "served", "verified (different_vendor)",
    )  # fmt: skip
