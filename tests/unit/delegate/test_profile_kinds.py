"""A weak model answers only what a later step checks (L4-DLG-019; SCN-DLG-66, 67): the kinds a delegate profile may
answer, the per-question veto, and the escalation text of a question no profile may answer."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from l4.agents.base import ProbeCtx
from l4.agents.factory import Factory
from l4.agents.fake import FakeAdapter
from l4.availability.cooldown import AvailabilityStore, cooldown_key
from l4.availability.errors import RoleUnavailable
from l4.config.schema import DelegateCfg, L4Config, Profile, RolesCfg
from l4.delegate.independence import DELEGATE_SERVES, Asker, delegate_constraint, independence_escalation
from l4.delegate.kinds import allowed_kinds, is_free_tier, join_kinds, kinds_constraint, unknown_kinds

from ..agents.cli_streams import oc_finish, oc_text, oc_tool
from .cli_adapters import ZEN_PROFILE, ScriptedOpenCode
from .conftest import blocked
from .test_pass import QUESTIONS, results, status_of
from .test_pass_adapters import text_of

CFG = DelegateCfg()
STRONG = Profile(adapter="claude-code", model="claude-opus-5-5", vendor="anthropic")
ZEN = Profile(adapter="opencode", model="opencode/free-model", vendor="unknown")
FREE_TAG = Profile(adapter="opencode", model="openrouter/deepseek/deepseek-v4.1-flash:free", vendor="deepseek")
PAID = Profile(adapter="opencode", model="opencode-go/deepseek-v4.1-flash", vendor="deepseek")
PROFILES = {"delegate-opus": STRONG, "delegate-free": ZEN, "delegate-tag": FREE_TAG, "delegate-go": PAID}


def with_kinds(profile: Profile, kinds) -> Profile:
    return profile.model_copy(update={"options": {**profile.options, "delegate_kinds": kinds}})


def test_a_free_tier_id_is_an_opencode_zen_id_or_a_free_tag():
    assert is_free_tier("opencode/free-model") and is_free_tier("openrouter/x/y:free")
    assert not is_free_tier("opencode-go/deepseek-v4.1-flash") and not is_free_tier("claude-opus-5-5")
    assert not is_free_tier(None) and not is_free_tier("")


def test_free_is_found_in_any_tag_segment():  # SCN-DLG-96
    assert is_free_tier("openrouter/x/y:free:thinking") and is_free_tier("openrouter/x/y:thinking:free")
    assert not is_free_tier("openrouter/x/y:thinking") and not is_free_tier("openrouter/x/y:freebie")
    assert not is_free_tier("openrouter/free/y:thinking")  # a path segment is not a tag


def test_a_profile_answers_every_kind_of_the_delegate_by_default():
    assert allowed_kinds(STRONG, CFG) == frozenset(CFG.kinds)
    assert allowed_kinds(PAID, CFG) == frozenset(CFG.kinds)  # not free by its id: nothing restricts it (DLG-002 warns)


def test_a_free_model_never_answers_a_verdict():  # SCN-DLG-66
    assert allowed_kinds(ZEN, CFG) == {"technical", "harness"}
    assert allowed_kinds(FREE_TAG, CFG) == {"technical", "harness"}
    assert kinds_constraint("verdict", CFG)("delegate-free", ZEN) == (
        "kinds: delegate-free answers technical and harness questions"
    )
    assert kinds_constraint("product", CFG)("delegate-tag", FREE_TAG) is not None
    assert kinds_constraint("ambiguous", CFG)("delegate-free", ZEN) is not None
    assert kinds_constraint("verdict", CFG)("delegate-opus", STRONG) is None


def test_a_free_model_answers_a_technical_question():  # SCN-DLG-67
    assert kinds_constraint("technical", CFG)("delegate-free", ZEN) is None
    assert kinds_constraint("harness", CFG)("delegate-free", ZEN) is None


def test_options_narrow_and_never_widen_a_free_model():
    assert allowed_kinds(with_kinds(ZEN, ["technical"]), CFG) == {"technical"}
    assert allowed_kinds(with_kinds(ZEN, ["verdict", "product", "technical"]), CFG) == {"technical"}  # never widened
    assert allowed_kinds(with_kinds(STRONG, ["technical", "verdict"]), CFG) == {"technical", "verdict"}
    assert allowed_kinds(with_kinds(STRONG, []), CFG) == frozenset()
    assert allowed_kinds(with_kinds(PAID, ["harness"]), CFG) == {"harness"}


def test_options_never_widen_the_kinds_of_the_delegate():
    narrow = DelegateCfg(kinds=["technical", "harness"])
    assert allowed_kinds(with_kinds(STRONG, ["technical", "verdict"]), narrow) == {"technical"}
    assert allowed_kinds(STRONG, narrow) == {"technical", "harness"}


def test_an_unknown_kind_in_options_is_ignored_and_reported():
    odd = with_kinds(STRONG, ["technical", "bogus", 3])
    assert allowed_kinds(odd, CFG) == {"technical"} and unknown_kinds(odd) == ["bogus", "3"]
    assert unknown_kinds(STRONG) == [] and unknown_kinds(with_kinds(STRONG, ["technical"])) == []
    not_a_list = with_kinds(STRONG, "technical")
    assert unknown_kinds(not_a_list) == ["technical"] and allowed_kinds(not_a_list, CFG) == frozenset()
    # the pass skips such a profile: its configuration is wrong
    why = kinds_constraint("technical", CFG)("delegate-opus", odd)
    assert why is not None and "bogus" in why and why.startswith("kinds: delegate-opus")


def test_kinds_are_listed_in_words():
    assert join_kinds(["technical"]) == "technical"
    assert join_kinds(["technical", "harness"]) == "technical and harness"
    assert join_kinds(["product", "ambiguous", "verdict"]) == "product, ambiguous and verdict"
    assert join_kinds([]) == "no"


def factory(tmp_path: Path, chain: list[str]) -> Factory:
    cfg = L4Config(profiles=PROFILES, roles=RolesCfg(delegate=chain))
    ctx = ProbeCtx(environ={"PATH": "/usr/bin"}, cwd=tmp_path, run=lambda *a: None)
    return Factory(cfg, ctx, adapters={name: FakeAdapter([]) for name in ("claude-code", "opencode")})


def pick(tmp_path, chain, kind, askers=()):
    return factory(tmp_path, chain).for_role(
        "delegate", "u", serves=DELEGATE_SERVES,
        constraints=[delegate_constraint(askers, "model"), kinds_constraint(kind, CFG)],
    )  # fmt: skip


def test_a_free_profile_is_skipped_for_a_verdict_and_selected_for_a_technical_question(tmp_path):
    chain = ["delegate-free", "delegate-opus"]
    verdict = pick(tmp_path, chain, "verdict")
    assert verdict.profile_name == "delegate-opus"
    assert [(s["profile"], s["step"], s["reason"]) for s in verdict.skipped] == [
        ("delegate-free", "constraint", "kinds: delegate-free answers technical and harness questions")
    ]
    assert pick(tmp_path, chain, "technical").profile_name == "delegate-free"


def test_no_profile_for_a_kind_escalates_with_its_reason(tmp_path):
    with pytest.raises(RoleUnavailable) as err:
        pick(tmp_path, ["delegate-free", "delegate-tag"], "verdict")
    assert independence_escalation(err.value, "verdict") == "no delegate profile answers verdict questions"


def test_a_chain_skipped_for_kinds_and_for_independence_together_says_no_independent_delegate(tmp_path):
    asked = (Asker("claude-opus", "claude-opus-5-5", "asked"),)
    with pytest.raises(RoleUnavailable) as err:
        pick(tmp_path, ["delegate-opus", "delegate-free"], "verdict", asked)
    assert independence_escalation(err.value, "verdict") == "no independent delegate"
    with pytest.raises(RoleUnavailable) as only_free:
        pick(tmp_path, ["delegate-free"], "verdict", asked)
    assert independence_escalation(only_free.value, "verdict") == "no delegate profile answers verdict questions"


# -- through the pass -------------------------------------------------------------------------------------------------


def cool_dlg(tdd_repo) -> None:
    until = datetime(2026, 1, 2, tzinfo=UTC)
    profile = Profile(adapter="fake", model="delegate-model-1")
    AvailabilityStore(tdd_repo.cache).cooldowns.record("dlg", cooldown_key("dlg", profile), until, "usage_limit", "t")


def free_adapter(install_cli, *, answers: bool) -> ScriptedOpenCode:
    lines = [oc_tool("read"), oc_finish("tool-calls"), oc_text(text_of()), oc_finish()]
    return install_cli("opencode", ScriptedOpenCode([lines] if answers else []))


def test_a_free_model_answers_a_technical_question_through_the_pass(
    delegate_run, install_cli, tdd_repo, fake_clock
):  # SCN-DLG-67: the strong profile cools, the free one answers
    cool_dlg(tdd_repo)
    adapter = free_adapter(install_cli, answers=True)
    run = delegate_run([blocked("technical")], roles={"delegate": ["dlg", "free"]}, profiles={"free": ZEN_PROFILE})
    assert status_of(run) == "answered" and len(adapter.requests) == 1
    assert "the delegate (opencode/free-model via opencode)" in run.pushed(QUESTIONS)
    assert results(run)[0]["profile"] == "free"


def test_a_free_model_never_answers_a_product_question_and_the_strong_one_defers(
    delegate_run, install_cli, tdd_repo, fake_clock
):  # SCN-DLG-66, with a product question (a verdict needs a judge round)
    cool_dlg(tdd_repo)
    adapter = free_adapter(install_cli, answers=False)
    run = delegate_run([blocked("product")], roles={"delegate": ["dlg", "free"]}, profiles={"free": ZEN_PROFILE})
    assert adapter.requests == []  # the free profile was not called
    (result,) = results(run)
    assert (result["status"], result["reason"], result["retry_after"]) == (
        "deferred", "cooling", "2026-01-02T00:00:00Z",
    )  # fmt: skip
    assert status_of(run) == "open"


def test_no_profile_for_a_kind_escalates_in_the_pass(delegate_run, install_cli):
    adapter = free_adapter(install_cli, answers=False)
    run = delegate_run([blocked("product")], roles={"delegate": ["free"]}, profiles={"free": ZEN_PROFILE})
    assert adapter.requests == []
    (result,) = results(run)
    assert (result["status"], result["reason"]) == ("escalated", "no delegate profile answers product questions")
    assert status_of(run) == "open" and run.code == 11
