"""L4-VER-091 (audit-writer-chain): a call of the `verifier_agent` role that one profile cannot answer is asked of the
next profile of the chain, in the same run, and the failed profile is skipped for the rest of the round."""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from l4.agents.base import LimitSignal, RunResult, Usage
from l4.agents.factory import WaitingCapacity
from l4.agents.fake import Step
from l4.llm.agent_judge import Msg, StructuredResult
from l4.verifier.writer_chain import WriterChain

from ..implementer.conftest import KNOWN, UNKNOWN, green_step, red_step
from .test_ladder_depth import AUDIT_KNOWN, JUDGE, audited_criterion, writer_step
from .test_ui_flow import JUDGE as UI_JUDGE
from .test_ui_flow import ui_test, web_green, web_repo  # noqa: F401  (the fixture)

RAW = Path("raw.jsonl")
ASK = ("system", [Msg("user", "write the test")], {"type": "object"})


def reply(status: str = "ok", detail: str = "", *, run_status: str | None = None, **kw) -> StructuredResult:
    run = (
        RunResult(run_status, RAW, usage=kw.get("usage") or Usage(), limit=kw.get("limit"))  # type: ignore[arg-type]
        if run_status
        else None
    )
    return StructuredResult(
        status, parsed={"code": "x"} if status == "ok" else None, detail=detail, run=run,  # type: ignore[arg-type]
        usage=kw.get("usage") or Usage(), length_stop=kw.get("length_stop", False),
    )  # fmt: skip


class FakeBackend:
    """FAKE: answers with the next scripted result and keeps how often it was asked."""

    def __init__(self, name: str, *results: StructuredResult) -> None:
        self.name, self.results, self.asked = name, list(results), 0

    def complete_structured(self, system, messages, json_schema, *, effort, max_tokens, timeout_s):
        self.asked += 1
        return self.results.pop(0)


class Rig:
    """FAKE: the selection of a chain of profiles, in order, skipping what the chain's `skip` set holds."""

    def __init__(self, *backends: FakeBackend) -> None:
        self.backends = {b.name: b for b in backends}
        self.skip: set[str] = set()
        self.failures: list[str] = []
        self.events: list[tuple[str, dict]] = []
        self.limited: list[str] = []

    def select(self) -> SimpleNamespace:
        for name in self.backends:
            if name not in self.skip:
                return SimpleNamespace(profile_name=name)
        raise WaitingCapacity("verifier_agent", "no independent verifier", datetime.now(UTC))

    def on_limit(self, selected, run) -> SimpleNamespace:
        self.limited.append(selected.profile_name)
        return self.select()

    def chain(self, step: str = "4a", role: str = "audit", redact=lambda text: text) -> WriterChain:
        return WriterChain(
            self.select, lambda s: self.backends[s.profile_name], self.on_limit, self.skip, self.failures,
            lambda event, /, **data: self.events.append((event, data)), step, role, redact,
        )  # fmt: skip

    def of(self, kind: str) -> list[dict]:
        return [d for k, d in self.events if k == kind]


def test_an_ok_reply_is_returned_at_once():
    rig = Rig(FakeBackend("first", reply()), FakeBackend("second"))
    assert rig.chain().complete_structured(*ASK).status == "ok"
    assert rig.events == [] and rig.skip == set() and rig.backends["second"].asked == 0


def test_a_length_stop_moves_to_the_next_profile_and_is_recorded():
    rig = Rig(
        FakeBackend("first", reply("error", "stopped at the output limit", run_status="error", length_stop=True)),
        FakeBackend("second", reply()),
    )
    assert rig.chain().complete_structured(*ASK).status == "ok"
    [event] = rig.of("availability.judge_error")
    assert event == {
        "role": "verifier_agent", "profile": "first", "kind": "length", "detail": "stopped at the output limit",
        "step": "4a",
    }  # fmt: skip
    assert rig.skip == {"first"} and rig.backends["second"].asked == 1


def test_a_refused_tool_call_is_kind_permission():
    rig = Rig(
        FakeBackend("first", reply("error", "permission denied for bash", run_status="permission_blocked")),
        FakeBackend("second", reply()),
    )
    assert rig.chain(step="5", role="ui_tests").complete_structured(*ASK).status == "ok"
    [event] = rig.of("availability.judge_error")
    assert (event["kind"], event["step"]) == ("permission", "5")


def test_any_other_error_is_kind_error_and_its_detail_is_one_line_cut_and_redacted():
    detail = "boom TOKEN-1234\nsecond line\n" + "x" * 400
    rig = Rig(FakeBackend("first", reply("error", detail, run_status="error")), FakeBackend("second", reply()))
    chain = rig.chain(redact=lambda text: text.replace("TOKEN-1234", "[x]"))
    chain.complete_structured(*ASK)
    [event] = rig.of("availability.judge_error")
    assert event["kind"] == "error" and event["detail"] == "boom [x]"


@pytest.mark.parametrize("status", ["timeout", "schema_invalid"])
def test_a_timeout_and_an_invalid_reply_are_returned_with_no_second_call(status):
    rig = Rig(FakeBackend("first", reply(status, "no answer", run_status="timeout")), FakeBackend("second"))
    assert rig.chain().complete_structured(*ASK).status == status
    assert rig.backends["second"].asked == 0 and rig.events == [] and rig.skip == set()


def test_a_limit_cools_the_profile_and_moves_on_through_the_factory():
    rig = Rig(
        FakeBackend("first", reply("limit", "rate limited", run_status="rate_limited")), FakeBackend("second", reply())
    )
    assert rig.chain().complete_structured(*ASK).status == "ok"
    assert rig.limited == ["first"] and rig.skip == {"first"}
    assert rig.of("availability.judge_error") == []  # a limit is `availability.limit` and `availability.fallback`


USAGE_LIMIT = LimitSignal("fake", None, "usage_limit", None, "test", "You have hit your usage limit")


def test_a_usage_limit_is_recorded_as_availability_limit_as_the_judges_record_it():
    rig = Rig(
        FakeBackend("first", reply("limit", "rate limited", run_status="rate_limited", limit=USAGE_LIMIT)),
        FakeBackend("second", reply()),
    )
    assert rig.chain().complete_structured(*ASK).status == "ok"
    assert rig.of("availability.limit") == [
        {"tool": "fake", "kind": "usage_limit", "source": "test", "excerpt": "You have hit your usage limit"}
    ]
    assert rig.limited == ["first"] and rig.of("availability.judge_error") == []


def test_a_limit_that_ends_the_chain_is_left_to_the_caller_and_keeps_its_run_for_it():
    rig = Rig(FakeBackend("first", reply("limit", "x", run_status="rate_limited", limit=USAGE_LIMIT)))
    result = rig.chain().complete_structured(*ASK)
    assert result.status == "limit" and result.run is not None and result.run.limit is USAGE_LIMIT  # RoleLimit's
    assert rig.of("availability.limit") == []  # the orchestrator records it once when it parks the unit


def test_a_limit_that_names_no_signal_records_no_availability_limit():
    rig = Rig(FakeBackend("first", reply("limit", "x", run_status="rate_limited")), FakeBackend("second", reply()))
    assert rig.chain().complete_structured(*ASK).status == "ok" and rig.of("availability.limit") == []


def test_a_limit_with_no_run_is_returned_for_the_caller():
    rig = Rig(FakeBackend("first", reply("limit", "no run")), FakeBackend("second"))
    assert rig.chain().complete_structured(*ASK).status == "limit" and rig.limited == []


def test_with_no_profile_left_the_last_result_carries_each_failure():
    rig = Rig(
        FakeBackend("first", reply("error", "stopped at the output limit", run_status="error", length_stop=True)),
        FakeBackend("second", reply("error", "tool refused", run_status="permission_blocked")),
    )
    last = rig.chain().complete_structured(*ASK)
    assert last.status == "error"
    assert last.detail == (
        "no profile of roles.verifier_agent could answer: first: length: stopped at the output limit; "
        "second: permission: tool refused"
    )
    assert rig.skip == {"first", "second"}


def test_the_chain_stays_on_the_profile_that_answered():
    rig = Rig(FakeBackend("first", reply("error", "x", run_status="error")), FakeBackend("second", reply(), reply()))
    chain = rig.chain()
    chain.complete_structured(*ASK)
    chain.complete_structured(*ASK)
    assert rig.backends["first"].asked == 1 and rig.backends["second"].asked == 2


def test_a_later_step_of_the_round_does_not_ask_a_failed_profile():
    rig = Rig(FakeBackend("first", reply("error", "x", run_status="error")), FakeBackend("second", reply(), reply()))
    rig.chain().complete_structured(*ASK)
    later = rig.chain(step="5", role="ui_tests")
    assert later.profile == "second"
    later.complete_structured(*ASK)
    assert rig.backends["first"].asked == 1


def test_a_step_that_finds_the_chain_used_up_returns_the_summary_without_a_call():
    rig = Rig(FakeBackend("only", reply("error", "stopped", run_status="error", length_stop=True)))
    rig.chain().complete_structured(*ASK)
    later = rig.chain(step="5", role="ui_tests")  # no profile is left: the round already failed them all
    result = later.complete_structured(*ASK)
    assert result.status == "error" and result.detail.startswith(
        "no profile of roles.verifier_agent could answer: only"
    )
    assert rig.backends["only"].asked == 1


def test_a_round_with_no_independent_verifier_still_raises_as_before():
    rig = Rig()
    with pytest.raises(WaitingCapacity):
        rig.chain()


def test_the_last_discarded_calls_cost_is_recorded_once_and_not_left_to_the_caller():
    usage = Usage(cost_usd=0.4)
    rig = Rig(FakeBackend("only", reply("error", "x", run_status="error", usage=usage)))
    last = rig.chain().complete_structured(*ASK)
    assert last.status == "error" and last.usage.cost_usd is None
    assert rig.of("budget.cost") == [{"usd": 0.4, "profile": "only", "role": "audit"}]


def test_the_detail_is_redacted_before_it_is_cut():
    detail = "x" * 296 + "TOKEN-1234"  # the secret straddles the cut
    rig = Rig(FakeBackend("first", reply("error", detail, run_status="error")), FakeBackend("second", reply()))
    chain = rig.chain(redact=lambda text: text.replace("TOKEN-1234", "[x]"))
    chain.complete_structured(*ASK)
    assert "TOKEN" not in rig.of("availability.judge_error")[0]["detail"]


def test_the_cost_of_a_discarded_call_is_recorded_with_its_profile():
    rig = Rig(
        FakeBackend("first", reply("error", "x", run_status="error", usage=Usage(cost_usd=0.4))),
        FakeBackend("second", reply(usage=Usage(cost_usd=0.1))),
    )
    result = rig.chain().complete_structured(*ASK)
    assert rig.of("budget.cost") == [{"usd": 0.4, "profile": "first", "role": "audit"}]
    assert result.usage.cost_usd == 0.1  # the caller sums the calls it used


# --- end to end: a round with two writer profiles (SCN-VER-362 .. 369) ---------------------------------------------


def two_writers(with_verifier, *, second_vendor: str = "fourthco", third: bool = False) -> dict:
    """The `with_verifier` config with a second (and a third) verifier-agent profile: all of other vendors than the
    implementer's, so each is independent of it."""
    config = with_verifier(audit_sample_ratio=0.5)
    config["profiles"] = {
        **config["profiles"],
        "second": {"adapter": "fake", "vendor": second_vendor},
        **({"third": {"adapter": "fake", "vendor": "fifthco"}} if third else {}),
    }
    config["roles"] = {"verifier_agent": ["auditor", "second", *(["third"] if third else [])]}
    return config


LENGTH = Step(status="error", length_stop=True, detail="the reply stopped at the output limit")
REFUSED = Step(status="permission_blocked", detail="permission denied: bash")


def errors(run) -> list[tuple[str, str, str]]:
    return [
        (e["profile"], e["kind"], e["step"])
        for e in run.events("availability.judge_error")
        if e["role"] == "verifier_agent"
    ]


def test_scn_ver_362_a_length_stop_moves_the_audit_call_to_the_next_profile(run_l4, valid_spec, with_verifier):
    cid = audited_criterion()
    config = two_writers(with_verifier)
    run = run_l4([red_step(), green_step(), LENGTH, writer_step(cid, AUDIT_KNOWN), JUDGE], **config)
    assert run.code == 0, run.outcome
    assert errors(run) == [("auditor", "length", "4a")]
    assert [e["status"] for e in run.events("verify.audit")] == ["accepted"]
    assert "waiting_capacity" not in {e["to"] for e in run.events("phase.changed")}


def test_scn_ver_364_the_next_profile_must_be_independent_of_the_implementers(run_l4, valid_spec, with_verifier):
    cid = audited_criterion()
    config = with_verifier(audit_sample_ratio=0.5)
    config["profiles"] = {
        **config["profiles"],
        "same": {"adapter": "fake", "vendor": "fakeco"},  # the implementer's vendor
        "third": {"adapter": "fake", "vendor": "fifthco"},
    }
    config["roles"] = {"verifier_agent": ["auditor", "same", "third"]}
    run = run_l4([red_step(), green_step(), LENGTH, writer_step(cid, AUDIT_KNOWN), JUDGE], **config)
    assert run.code == 0, run.outcome
    assert errors(run) == [("auditor", "length", "4a")]
    selected = [e for e in run.events("availability.selected") if e.get("role") == "verifier_agent"]
    assert "same" not in {e["selected"] for e in selected} and selected[-1]["selected"] == "third"


def test_scn_ver_365_a_usage_limit_cools_the_profile_and_moves_on(run_l4, valid_spec, with_verifier):
    cid = audited_criterion()
    config = two_writers(with_verifier)
    limit = LimitSignal("fake", None, "usage_limit", None, "test", "You have hit your usage limit")
    run = run_l4(
        [red_step(), green_step(), Step(status="quota", limit=limit), writer_step(cid, AUDIT_KNOWN), JUDGE], **config
    )
    assert run.code == 0, run.outcome
    [fallback] = [e for e in run.events("availability.fallback") if e["role"] == "verifier_agent"]
    assert (fallback["from"], fallback["to"]) == ("auditor", "second")
    [recorded] = run.events("availability.limit")  # the chain records the limit, as the step-9 judges do
    assert (recorded["tool"], recorded["kind"]) == ("fake", "usage_limit")
    assert [e["status"] for e in run.events("verify.audit")] == ["accepted"]


def test_scn_ver_366_with_no_profile_left_the_unit_waits_and_the_reason_names_each_failure(
    run_l4, valid_spec, with_verifier
):
    config = two_writers(with_verifier)
    run = run_l4([red_step(), green_step(), LENGTH, REFUSED], **config)
    assert run.code == 12, run.outcome
    assert run.outcome["units"][0]["phase_after"] == "waiting_capacity"
    reason = " ".join(str(e.get("reason", "")) for e in run.events("phase.changed"))
    assert (
        "no profile of roles.verifier_agent could answer: auditor: length:" in reason
        and "second: permission:" in reason
    )
    assert errors(run) == [("auditor", "length", "4a"), ("second", "permission", "4a")]


def test_scn_ver_366_a_chain_that_ends_on_a_usage_limit_waits_for_that_profiles_reset(
    run_l4, valid_spec, with_verifier
):
    config = two_writers(with_verifier)
    limit = LimitSignal("fake", None, "usage_limit", None, "test", "You have hit your usage limit")
    run = run_l4([red_step(), green_step(), LENGTH, Step(status="quota", limit=limit)], **config)
    assert run.code == 12, run.outcome
    assert run.outcome["units"][0]["phase_after"] == "waiting_capacity"
    reason = " ".join(str(e.get("reason", "")) for e in run.events("phase.changed"))
    assert "no profile of roles.verifier_agent could answer" not in reason  # RoleLimit, not the summary
    assert [e["tool"] for e in run.events("availability.limit")] == ["fake"]


def test_scn_ver_368_a_timeout_does_not_move_to_the_next_profile(run_l4, valid_spec, with_verifier):
    config = two_writers(with_verifier)
    run = run_l4([red_step(), green_step(), Step(status="timeout"), JUDGE], **config)
    assert run.code == 0, run.outcome
    [audit] = run.events("verify.audit")
    assert audit["status"] == "timeout"
    assert errors(run) == []  # the second profile was never asked: the script holds no step for it


def test_scn_ver_368_a_twice_invalid_reply_does_not_move_either(run_l4, valid_spec, with_verifier):
    cid = audited_criterion()
    config = two_writers(with_verifier)
    bad = Step(
        structured={
            "criterion": cid,
            "code": "import importlib\nimport pytdd.pricing as p\n\n\ndef test_x():\n    importlib.reload(p)\n",
        }
    )
    run = run_l4([red_step(), green_step(), bad, bad, JUDGE], **config)
    assert run.code == 0, run.outcome
    [audit] = run.events("verify.audit")
    assert audit["status"] == "invalid" and errors(run) == []


def test_scn_ver_369_a_discarded_calls_cost_is_recorded_with_its_profile(run_l4, valid_spec, with_verifier):
    cid = audited_criterion()
    config = two_writers(with_verifier)
    costly = Step(status="error", length_stop=True, detail="stopped", cost_usd=0.4)
    run = run_l4([red_step(), green_step(), costly, writer_step(cid, AUDIT_KNOWN), JUDGE], **config)
    assert run.code == 0, run.outcome
    discarded = [e for e in run.events("budget.cost") if e.get("profile") == "auditor"]
    assert [(e["usd"], e["role"]) for e in discarded] == [(0.4, "audit")]
    own = [e for e in run.events("budget.cost") if e.get("profile") == "verifier_agent" and e.get("role") == "audit"]
    assert all(e["usd"] != 0.4 for e in own)


def test_scn_ver_367_step_5s_writer_walks_the_chain_too(run_l4, valid_spec, web_repo):  # noqa: F811
    config = {**web_repo, "profiles": {**web_repo["profiles"], "second": {"adapter": "fake", "vendor": "fourthco"}}}
    config["roles"] = {"verifier_agent": ["writer", "second"]}
    script = [
        red_step(), web_green(), LENGTH, ui_test(KNOWN, 'data-testid="coupon"', "slot"),
        ui_test(UNKNOWN, "SAVE10", "code"), UI_JUDGE,
    ]  # fmt: skip
    run = run_l4(script, **config)
    assert run.code == 0, run.outcome
    assert errors(run) == [("writer", "length", "5")]
    assert [(e["criterion"], e["status"]) for e in run.events("verify.generated")] == [
        (KNOWN, "accepted"), (UNKNOWN, "accepted"),
    ]  # fmt: skip


def test_scn_ver_363_a_refused_tool_call_moves_the_call_and_the_profile_is_skipped_for_the_round(
    run_l4,
    valid_spec,
    web_repo,  # noqa: F811
    monkeypatch,
):
    import yaml

    from ..conftest import TddRepo

    patched = TddRepo.config

    def config(self, **kw):  # the audit sample is on as well: steps 4a and 5 both ask the role
        body = yaml.safe_load(patched(self, **kw))
        body["verifier"]["audit_sample_ratio"] = 0.5
        return yaml.safe_dump(body)

    monkeypatch.setattr(TddRepo, "config", config)
    cid = audited_criterion()
    options = {**web_repo, "profiles": {**web_repo["profiles"], "second": {"adapter": "fake", "vendor": "fourthco"}}}
    options["roles"] = {"verifier_agent": ["writer", "second"]}
    script = [
        red_step(), web_green(), REFUSED, writer_step(cid, AUDIT_KNOWN),
        ui_test(KNOWN, 'data-testid="coupon"', "slot"), ui_test(UNKNOWN, "SAVE10", "code"), UI_JUDGE,
    ]  # fmt: skip
    run = run_l4(script, **options)
    assert run.code == 0, run.outcome
    assert errors(run) == [("writer", "permission", "4a")]  # step 5 never asked the failed profile again
    assert [e["status"] for e in run.events("verify.audit")] == ["accepted"]
    assert len(run.events("verify.generated")) == 2
