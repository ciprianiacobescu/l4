"""Stage C exit, judges: the chain is walked with the independence rule, a limit or a mismatching served model moves
to the next independent judge in the same round, and `verification.md` says how the vendors are known."""

import json

import pytest

from l4.agents.base import LimitSignal
from l4.agents.factory import ADAPTERS
from l4.agents.fake import FakeAdapter, Step
from l4.cli import main
from l4.exitcodes import ExitCode
from l4.specs.criteria import openspec_criteria

from ..conftest import FIXTURE, UNIT
from ..implementer.conftest import green_step, red_step
from ..orchestrator.conftest import Run
from .conftest import judge_reply

CRITERIA = [c.id for c in openspec_criteria(FIXTURE / "openspec" / "changes" / "add-discount-codes")]
IMPLEMENT = [red_step(), green_step()]
VERIFICATION = "openspec/changes/add-discount-codes/verification.md"
EVIDENCE = "openspec/changes/add-discount-codes/.l4/evidence/round-1/verdict.json"
FULL = "claude-haiku-4-5-20251001"
PROFILES = {
    "same": {"adapter": "fake", "vendor": "fakeco"},  # the implementer's vendor
    "wrong-model": {"adapter": "fake", "vendor": "alpha", "model": "claude-haiku-4-5"},
    "free": {"adapter": "fake", "vendor": "beta"},
    "last": {"adapter": "fake", "vendor": "gamma"},
    "api": {"backend": "openai-chat", "model": "x"},  # no adapter: it cannot answer a tool-less call
}


def judge(**over) -> Step:
    return Step(structured=judge_reply(CRITERIA), **over)


def limited() -> Step:
    return Step(status="quota", limit=LimitSignal("fake", None, "usage_limit", None, "test", "limit reached"))


@pytest.fixture
def run_chain(tdd_repo, raw, monkeypatch, valid_spec, fake_clock):
    def run(script, judges, *, via: str = "run", served: bool = True, profiles=None, **config) -> Run:
        tdd_repo.write_config(profiles={**PROFILES, **(profiles or {})}, roles={"judges": judges}, **config)
        adapter = FakeAdapter(script, served_model=served)
        monkeypatch.setitem(ADAPTERS, "fake", lambda: adapter)
        argv = [via, "--unit", UNIT, "--repo", str(tdd_repo.repo)]
        return Run(main(argv, environ=tdd_repo.environ), adapter, tdd_repo, raw)

    return run


def test_the_first_independent_judge_is_skipped_to_and_the_report_names_the_independence(run_chain):
    run = run_chain([*IMPLEMENT, judge()], ["same", "free"], served=False)
    assert run.code == 0
    selected = [e for e in run.events("availability.selected") if e["role"] == "judges"]
    assert [(e["selected"], e["fallback_index"], e.get("fallback_from")) for e in selected] == [("free", 1, "same")]
    assert [s["profile"] for s in selected[0]["skipped"]] == ["same"]
    text = run.pushed(VERIFICATION)
    assert "- independence: declared (unverified): free beta (declared), impl fakeco (declared)" in text
    verdict = json.loads(run.pushed(EVIDENCE))
    assert verdict["independence"]["status"] == "declared (unverified)"
    assert verdict["profiles"]["judge"] == "free"


def test_a_mismatching_served_model_moves_to_the_next_independent_judge(run_chain):
    script = [*IMPLEMENT, judge(model="claude-sonnet-4-5-20250929"), judge(model=FULL)]
    run = run_chain(script, ["same", "wrong-model", "last"])
    assert run.code == 0
    (mismatch,) = run.events("availability.model_mismatch")
    assert (mismatch["profile"], mismatch["requested"], mismatch["served"]) == (
        "wrong-model", "claude-haiku-4-5", "claude-sonnet-4-5-20250929",
    )  # fmt: skip
    judged = [(e["profile"], e["status"]) for e in run.events("verify.judge")]
    assert judged == [("wrong-model", "model_mismatch"), ("last", "ok")]
    assert [e["selected"] for e in run.events("availability.selected") if e["role"] == "judges"] == [
        "wrong-model",
        "last",
    ]
    text = run.pushed(VERIFICATION)
    assert "- Judge: last" in text
    assert f"independence: declared (unverified): last anthropic (served {FULL}), impl fakeco (declared)" in text
    assert json.loads(run.pushed(EVIDENCE))["profiles"]["judge"] == "last"
    assert run.outcome["units"][0]["verdict"] == "PASS"


def test_a_served_model_that_matches_makes_the_judge_served(run_chain):
    run = run_chain([*IMPLEMENT, judge(model=FULL)], ["wrong-model"])
    assert run.code == 0
    judge_record = json.loads(run.pushed(EVIDENCE))["independence"]["judge"]
    assert (judge_record["provenance"], judge_record["served"]) == ("served", FULL)
    assert f"wrong-model anthropic (served {FULL})" in run.pushed(VERIFICATION)


def test_a_limit_cools_the_judge_and_the_next_one_answers_in_the_same_round(run_chain):
    run = run_chain([*IMPLEMENT, limited(), judge()], ["free", "last"])
    assert run.code == 0
    (cooldown,) = [e for e in run.events("availability.cooldown") if e["profile"] == "free"]
    assert cooldown["kind"] == "usage_limit"
    (fallback,) = [e for e in run.events("availability.fallback") if e["role"] == "judges"]
    assert (fallback["from"], fallback["to"]) == ("free", "last")
    assert [(e["verdict"], e["round"]) for e in run.events("verify.verdict")] == [("PASS", 1)]
    assert run.events("availability.limit")[0]["kind"] == "usage_limit"
    assert "- Judge: last" in run.pushed(VERIFICATION)


def test_every_judge_limited_parks_the_unit_with_the_earliest_reset(run_chain):
    run = run_chain([*IMPLEMENT, limited(), limited()], ["free", "last"])
    assert run.code == ExitCode.WAITING_CAPACITY
    (unit,) = run.outcome["units"]
    assert unit["phase_after"] == "waiting_capacity" and unit["retry_after"]
    parked = [e for e in run.events("phase.changed") if e["to"] == "waiting_capacity"]
    assert parked[0]["from"] == "verifying" and "no independent verifier" in parked[0]["reason"]
    assert not run.events("verify.verdict")


def test_every_judge_excluded_waits_with_a_retry_after_and_calls_no_judge(run_chain):
    run = run_chain(IMPLEMENT, ["same"])
    assert run.code == ExitCode.WAITING_CAPACITY
    assert len(run.adapter.requests) == 2  # red and green only
    parked = [e for e in run.events("phase.changed") if e["to"] == "waiting_capacity"]
    assert "no independent verifier" in parked[0]["reason"] and parked[0]["retry_after"]


def test_mismatches_until_nothing_is_left_wait_and_never_pass(run_chain):
    run = run_chain([*IMPLEMENT, judge(model="claude-opus-4-8")], ["wrong-model"])
    assert run.code == ExitCode.WAITING_CAPACITY
    assert len(run.events("availability.model_mismatch")) == 1 and not run.events("verify.verdict")


def test_a_chain_without_a_profile_that_can_judge_is_a_usage_error(run_chain):
    run = run_chain(IMPLEMENT, ["api"])
    assert run.code == ExitCode.USAGE_ERROR and len(run.adapter.requests) == 2


def blocked() -> Step:
    return Step(status="permission_blocked")


def test_a_judge_that_cannot_answer_moves_to_the_next_independent_judge(run_chain):
    run = run_chain([*IMPLEMENT, blocked(), judge()], ["free", "last"])
    assert run.code == 0
    assert [(e["profile"], e["status"]) for e in run.events("verify.judge")] == [("free", "error"), ("last", "ok")]
    assert run.events("availability.judge_error")[0]["profile"] == "free"
    assert "- Judge: last" in run.pushed(VERIFICATION)


def test_every_judge_failing_to_answer_parks_with_a_retry_after(run_chain):
    run = run_chain([*IMPLEMENT, blocked(), blocked()], ["free", "last"])
    assert run.code == ExitCode.WAITING_CAPACITY
    (unit,) = run.outcome["units"]
    assert unit["phase_after"] == "waiting_capacity" and unit["retry_after"]
    assert not run.events("verify.verdict")


def test_a_mismatching_judge_is_cooled_so_the_next_round_does_not_ask_it_again(run_chain):
    run = run_chain([*IMPLEMENT, judge(model="claude-opus-4-8")], ["wrong-model"])
    assert run.code == ExitCode.WAITING_CAPACITY
    (cooldown,) = [e for e in run.events("availability.cooldown") if e["profile"] == "wrong-model"]
    assert cooldown["kind"] == "model_mismatch"


OPENAI_IMPL = {"impl": {"adapter": "fake", "vendor": "openai"}}


def test_a_served_model_of_the_implementer_vendor_is_dropped_and_the_next_judge_answers(run_chain):
    # `free` names no full model id, so only the vendor of the served model can show that it is not independent
    script = [*IMPLEMENT, judge(model="gpt-5"), judge(model=FULL)]
    run = run_chain(script, ["free", "last"], profiles=OPENAI_IMPL)
    assert run.code == 0
    assert [(e["profile"], e["status"]) for e in run.events("verify.judge")] == [
        ("free", "model_mismatch"), ("last", "ok"),
    ]  # fmt: skip
    (mismatch,) = run.events("availability.model_mismatch")
    assert (mismatch["profile"], mismatch["served"]) == ("free", "gpt-5")
    assert [e["profile"] for e in run.events("availability.cooldown") if e["kind"] == "model_mismatch"] == ["free"]
    text = run.pushed(VERIFICATION)
    assert "- Judge: last" in text
    assert f"independence: declared (unverified): last anthropic (served {FULL}), impl openai (declared)" in text
    assert run.outcome["units"][0]["verdict"] == "PASS"


def test_a_served_model_of_no_known_vendor_is_never_counted(run_chain):
    run = run_chain([*IMPLEMENT, judge(model="mystery-1")], ["free"], profiles=OPENAI_IMPL)
    assert run.code == ExitCode.WAITING_CAPACITY
    assert [(e["profile"], e["status"]) for e in run.events("verify.judge")] == [("free", "model_mismatch")]
    assert not run.events("verify.verdict")


# --- a Kiro judge that reports its served model (kiro-judge 4.1, SCN-KJD-40 and SCN-KJD-41) ---

DEEPSEEK_IMPL = {"impl": {"adapter": "fake", "vendor": "deepseek"}}
KIRO_PROFILES = {
    "kiro-auto": {"adapter": "kiro-cli"},
    "kiro-sonnet": {"adapter": "kiro-cli", "model": "claude-sonnet-5.5"},
    "oc-judge": {"adapter": "fake", "vendor": "beta"},
    **DEEPSEEK_IMPL,
}


@pytest.fixture
def run_kiro(run_chain, monkeypatch):
    def run(kiro_script, script, judges):
        kiro = FakeAdapter(kiro_script, served_model=True)
        monkeypatch.setitem(ADAPTERS, "kiro-cli", lambda: kiro)
        return run_chain(script, judges, profiles=KIRO_PROFILES)

    return run


def test_scn_kjd_40_a_served_model_of_the_implementers_vendor_drops_an_auto_judges_verdict(run_kiro):
    run = run_kiro([judge(model="deepseek-3.2")], [*IMPLEMENT, judge()], ["kiro-auto", "oc-judge"])
    assert run.code == 0
    (mismatch,) = run.events("availability.model_mismatch")
    assert (mismatch["profile"], mismatch["served"]) == ("kiro-auto", "deepseek-3.2")
    assert [(e["profile"], e["status"]) for e in run.events("verify.judge")] == [
        ("kiro-auto", "model_mismatch"), ("oc-judge", "ok"),
    ]  # fmt: skip
    assert [e["profile"] for e in run.events("availability.cooldown") if e["kind"] == "model_mismatch"] == ["kiro-auto"]
    assert "- Judge: oc-judge" in run.pushed(VERIFICATION)
    assert run.outcome["units"][0]["verdict"] == "PASS"


def test_scn_kjd_40_a_claude_model_stands_and_no_model_leaves_the_judge_routed(run_kiro):
    served = run_kiro([judge(model="claude-sonnet-5.5")], [*IMPLEMENT], ["kiro-auto"])
    assert served.code == 0
    assert "kiro-auto anthropic (served claude-sonnet-5.5)" in served.pushed(VERIFICATION)


def test_scn_kjd_40_an_auto_judge_that_reports_no_model_stays_routed(run_kiro):
    routed = run_kiro([judge()], [*IMPLEMENT], ["kiro-auto"])
    assert routed.code == 0
    assert "kiro-auto routed: anthropic, minimax, zhipu (auto)" in routed.pushed(VERIFICATION)


def test_scn_kjd_41_a_pinned_model_that_kiro_could_not_set_is_a_model_mismatch(run_kiro):
    warned = Step(status="error", detail="model_mismatch: kiro-cli could not set claude-sonnet-5.5")
    run = run_kiro([warned], [*IMPLEMENT, judge()], ["kiro-sonnet", "oc-judge"])
    assert run.code == 0
    assert [(e["profile"], e["status"]) for e in run.events("verify.judge")] == [
        ("kiro-sonnet", "model_mismatch"), ("oc-judge", "ok"),
    ]  # fmt: skip
    (mismatch,) = run.events("availability.model_mismatch")
    assert mismatch["profile"] == "kiro-sonnet"
    assert [e["profile"] for e in run.events("availability.cooldown") if e["kind"] == "model_mismatch"] == [
        "kiro-sonnet"
    ]
    assert "- Judge: oc-judge" in run.pushed(VERIFICATION)


def test_scn_kjd_41_the_same_run_with_a_clean_stderr_gives_the_pinned_judges_verdict(run_kiro):
    run = run_kiro([judge(model="claude-sonnet-5.5")], [*IMPLEMENT], ["kiro-sonnet", "oc-judge"])
    assert run.code == 0 and "- Judge: kiro-sonnet" in run.pushed(VERIFICATION)


def test_finding_3_a_pinned_kiro_judge_whose_cli_names_the_pinned_model_stays_declared(run_kiro):
    """The owner's decision: the session file of a pinned run echoes the configuration; it is never a served report."""
    run = run_kiro([judge(model="claude-sonnet-5.5")], [*IMPLEMENT], ["kiro-sonnet"])
    assert run.code == 0
    text = run.pushed(VERIFICATION)
    assert "- independence: declared (unverified): kiro-sonnet anthropic (declared), impl deepseek (declared)" in text
    assert "(served" not in text
    assert json.loads(run.pushed(EVIDENCE))["independence"]["judge"]["provenance"] == "declared"


def test_scn_kjd_18_an_invalid_key_is_an_auth_failure_and_the_next_judge_answers(run_kiro):
    lost = Step(
        status="auth",
        detail="kiro-cli: the bearer token is invalid",
        limit=LimitSignal("kiro-cli", None, "auth", None, "kiro.run_error", "bearer token invalid"),
    )
    run = run_kiro([lost], [*IMPLEMENT, judge()], ["kiro-sonnet", "oc-judge"])
    assert run.code == 0
    (fallback,) = run.events("availability.fallback")
    assert fallback["role"] == "judges" and "oc-judge" in json.dumps(fallback)
    assert [(e["profile"], e["kind"]) for e in run.events("availability.cooldown")] == [("kiro-sonnet", "auth")]
    assert [(e["profile"], e["status"]) for e in run.events("verify.judge")] == [("oc-judge", "ok")]
    assert "- Judge: oc-judge" in run.pushed(VERIFICATION)


def test_scn_kjd_37_an_auth_fallback_does_not_call_an_auto_judge_its_own_probe_vetoes(run_chain, monkeypatch):
    """SCN-KJD-37 reached through a limit: the fallback walk re-checks the routed judge against its own probe."""
    from l4.agents.base import ProbeResult
    from l4.availability.vendor import routed_from_listing

    grown = routed_from_listing({"models": [{"model_id": "deepseek-3.2", "description": "DeepSeek V3.2"}]})
    assert grown is not None
    kiro = FakeAdapter([], served_model=True, probes={"auth": ProbeResult("auth", True, {"routed": grown.to_detail()})})
    monkeypatch.setitem(ADAPTERS, "kiro-cli", lambda: kiro)
    lost = Step(status="auth", limit=LimitSignal("fake", None, "auth", None, "test", "bearer token invalid"))
    profiles = {**KIRO_PROFILES, "oc-last": {"adapter": "fake", "vendor": "gamma"}}
    run = run_chain([*IMPLEMENT, lost, judge()], ["oc-judge", "kiro-auto", "oc-last"], profiles=profiles)
    assert run.code == 0
    assert kiro.requests == []
    assert [(e["profile"], e["status"]) for e in run.events("verify.judge")] == [("oc-last", "ok")]


# --- a Copilot judge that reports its served model (copilot-cli 4.3, SCN-FAC-44) ---

COPILOT_PROFILES = {
    "copilot-auto": {"adapter": "copilot-cli"},
    "copilot-sol": {"adapter": "copilot-cli", "model": "gpt-6.1-sol"},
    **DEEPSEEK_IMPL,
}


@pytest.fixture
def run_copilot(run_chain, monkeypatch):
    def run(copilot_script, script, judges):
        copilot = FakeAdapter(copilot_script, served_model=True)
        monkeypatch.setitem(ADAPTERS, "copilot-cli", lambda: copilot)
        return run_chain(script, judges, profiles=COPILOT_PROFILES)

    return run


@pytest.mark.parametrize(
    ("judge_name", "served"), [("copilot-auto", "mystery-model-1"), ("copilot-sol", "claude-sonnet-5.5")]
)
def test_scn_fac_44_a_served_id_of_no_family_or_another_than_the_pinned_one_is_a_model_mismatch(
    run_copilot, judge_name, served
):
    """Each judge in its own run: a cool-down of a profile with no model (`auto`) covers every model of the tool."""
    run = run_copilot([judge(model=served)], [*IMPLEMENT], [judge_name])
    assert run.code == ExitCode.WAITING_CAPACITY
    assert [(e["profile"], e["status"]) for e in run.events("verify.judge")] == [(judge_name, "model_mismatch")]
    assert not run.events("verify.verdict")
    (mismatch,) = run.events("availability.model_mismatch")
    assert (mismatch["profile"], mismatch["served"]) == (judge_name, served)
    assert [e["profile"] for e in run.events("availability.cooldown") if e["kind"] == "model_mismatch"] == [judge_name]


def test_scn_fac_44_an_auto_judge_that_names_gpt_6_1_sol_gives_a_served_verdict(run_copilot):
    run = run_copilot([judge(model="gpt-6.1-sol")], [*IMPLEMENT], ["copilot-auto"])
    assert run.code == 0
    text = run.pushed(VERIFICATION)
    assert "copilot-auto openai (served gpt-6.1-sol)" in text
    record = json.loads(run.pushed(EVIDENCE))["independence"]["judge"]
    assert (record["provenance"], record["served"]) == ("served", "gpt-6.1-sol")


def test_scn_fac_44_a_pinned_judge_that_names_its_own_model_stays_declared(run_copilot):
    run = run_copilot([judge(model="gpt-6.1-sol")], [*IMPLEMENT], ["copilot-sol"])
    assert run.code == 0
    text = run.pushed(VERIFICATION)
    assert "copilot-sol openai (declared)" in text and "(served" not in text
    assert json.loads(run.pushed(EVIDENCE))["independence"]["judge"]["provenance"] == "declared"
