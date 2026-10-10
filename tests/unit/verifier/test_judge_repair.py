"""Weak judges (live wave D, W-D1): a reply that breaks the schema in a trivial way is repaired deterministically, a
reply that is still invalid gets one retry, and what happened is counted. Fixtures are the shape of the real failures
(an evidence quote over 300 characters, a `suggested_fix` that is a list), with synthetic content."""

import copy

import pytest

from l4.agents.base import Usage
from l4.llm.agent_judge import Msg, StructuredResult
from l4.schemacheck import validate
from l4.verifier.judge import JUDGE_SCHEMA, JudgePrompt, parse_judge_output, run_judge
from l4.verifier.judge_repair import repair_reply

from .conftest import judge_reply

ID = "C-0a1b2c3d"
PROMPT = JudgePrompt("SYSTEM", "USER", "0" * 64, "judge@1")


def long_quote_reply(verdict: str = "pass") -> dict:
    reply = judge_reply([ID], verdict)
    reply["criteria"][0]["evidence"][0]["quote"] = "assert widget.total() == 3  # " + "padding " * 60
    return reply


def list_fix_reply() -> dict:
    reply = judge_reply([ID])
    reply["findings"] = [
        {
            "severity": "minor", "title": "t", "detail": "d", "evidence": [], "spec_gap": True, "criterion": ID,
            "suggested_fix": ["WHEN the widget is empty", "THEN total returns 0"],
        }
    ]  # fmt: skip
    return reply


class Scripted:
    def __init__(self, *results: StructuredResult) -> None:
        self._results = list(results)
        self.calls: list[list[Msg]] = []

    def complete_structured(self, system, messages, json_schema, *, effort, max_tokens, timeout_s):
        self.calls.append(list(messages))
        return self._results.pop(0)


def invalid(raw: dict | None, detail: str = "$.criteria.0.evidence.0.quote: longer than 300") -> StructuredResult:
    return StructuredResult("schema_invalid", detail=detail, raw=raw, usage=Usage(cost_usd=0.01))


def ok(reply=None) -> StructuredResult:
    return StructuredResult("ok", parsed=reply or judge_reply([ID]), model_resolved="m", usage=Usage(cost_usd=0.01))


def test_an_over_long_quote_is_cut_with_an_ellipsis_and_the_verdict_is_untouched():
    bad = long_quote_reply()
    assert validate(bad, JUDGE_SCHEMA)
    fixed, fields = repair_reply(bad, JUDGE_SCHEMA)
    quote = fixed["criteria"][0]["evidence"][0]["quote"]
    assert len(quote) == 300 and quote.endswith("…") and quote.startswith("assert widget.total() == 3")
    assert not validate(fixed, JUDGE_SCHEMA) and fields == ("criteria[].evidence[].quote",)
    assert fixed["criteria"][0]["verdict"] == "pass" and bad["criteria"][0]["evidence"][0]["quote"].endswith("padding ")


def test_a_list_or_an_object_suggested_fix_becomes_a_string():
    fixed, fields = repair_reply(list_fix_reply(), JUDGE_SCHEMA)
    assert fixed["findings"][0]["suggested_fix"] == "WHEN the widget is empty\nTHEN total returns 0"
    assert fields == ("findings[].suggested_fix",)
    obj = list_fix_reply()
    obj["findings"][0]["suggested_fix"] = {"when": "empty", "then": 0}
    fixed, _ = repair_reply(obj, JUDGE_SCHEMA)
    assert fixed["findings"][0]["suggested_fix"] == '{"then": 0, "when": "empty"}'
    assert not validate(fixed, JUDGE_SCHEMA)


def test_unknown_keys_and_a_null_optional_are_dropped_and_named_without_their_values():
    bad = long_quote_reply()
    bad["stray"] = "sk-live-SECRET"
    bad["criteria"][0]["notes"] = "x"
    bad["criteria"][0]["counterexample"] = None
    fixed, fields = repair_reply(bad, JUDGE_SCHEMA)
    assert "stray" not in fixed and "notes" not in fixed["criteria"][0] and "counterexample" not in fixed["criteria"][0]
    assert not any("SECRET" in f for f in fields)
    assert set(fields) >= {"(top level).(unknown key)", "criteria[].(unknown key)", "criteria[].counterexample"}


def test_repair_never_changes_a_verdict_or_adds_a_pass():
    for verdict in ("fail", "insufficient_evidence", "not_verifiable"):
        fixed, _ = repair_reply(long_quote_reply(verdict), JUDGE_SCHEMA)
        assert fixed["criteria"][0]["verdict"] == verdict
    bad = judge_reply([ID], "fail")
    bad["criteria"][0]["verdict"] = "PASS"  # not repairable: the enum is not guessed
    fixed, fields = repair_reply(bad, JUDGE_SCHEMA)
    assert fixed == bad and fields == () and validate(fixed, JUDGE_SCHEMA)
    missing = judge_reply([ID])
    del missing["criteria"][0]["verdict"]
    assert repair_reply(missing, JUDGE_SCHEMA)[0] == missing  # a missing verdict is never invented


def test_a_valid_reply_and_the_input_are_left_alone():
    good = judge_reply([ID])
    before = copy.deepcopy(good)
    fixed, fields = repair_reply(good, JUDGE_SCHEMA)
    assert fixed == before and fields == () and good == before


def test_parse_judge_output_is_unchanged_it_does_not_repair():
    assert parse_judge_output(long_quote_reply()).__class__.__name__ == "SchemaInvalid"


def test_run_judge_repairs_a_rejected_reply_in_one_call_and_reports_the_fields():
    backend = Scripted(invalid(long_quote_reply()))
    run = run_judge(backend, PROMPT, timeout_s=60, redact=str)
    assert run.status == "ok" and run.calls == 1 and run.reply == "repaired"
    assert run.repaired == ("criteria[].evidence[].quote",) and run.verdict is not None
    assert run.verdict.criteria[0].verdict == "pass"


def test_a_backend_accepted_reply_the_model_rejects_is_not_repaired_it_is_retried():
    bad = judge_reply([ID])
    bad["findings"] = [{"severity": "major", "title": "t", "detail": "d", "evidence": [], "spec_gap": "yes"}]
    run = run_judge(Scripted(StructuredResult("ok", parsed=bad), ok()), PROMPT, timeout_s=60, redact=str)
    assert run.status == "ok" and run.calls == 2 and run.reply == "retried" and run.repaired == ()


def test_an_unrepairable_reply_gets_one_retry_with_a_bounded_error_and_is_counted_retried():
    no_verdict = judge_reply([ID])
    del no_verdict["criteria"][0]["verdict"]
    detail = "$.criteria.0.verdict: required " * 100
    backend = Scripted(invalid(no_verdict, detail), ok())
    run = run_judge(backend, PROMPT, timeout_s=60, redact=str)
    assert run.status == "ok" and run.calls == 2 and run.reply == "retried"
    assert len(backend.calls[1][-1].content) < 1_500 and "verdict" in backend.calls[1][-1].content


def test_two_unrepairable_replies_are_discarded_and_counted():
    no_verdict = judge_reply([ID])
    del no_verdict["criteria"][0]["verdict"]
    run = run_judge(Scripted(invalid(no_verdict), invalid(no_verdict)), PROMPT, timeout_s=60, redact=str)
    assert run.status == "schema_invalid" and run.verdict is None and run.reply == "discarded"


def test_the_retry_reply_may_be_repaired_too():
    no_verdict = judge_reply([ID])
    del no_verdict["criteria"][0]["verdict"]
    run = run_judge(Scripted(invalid(no_verdict), invalid(long_quote_reply())), PROMPT, timeout_s=60, redact=str)
    assert run.status == "ok" and run.calls == 2 and run.reply == "retried" and run.repaired


def test_a_clean_reply_is_valid_and_a_timeout_alone_counts_for_nothing():
    assert run_judge(Scripted(ok()), PROMPT, timeout_s=60, redact=str).reply == "valid"
    timed = run_judge(Scripted(StructuredResult("timeout"), ok()), PROMPT, timeout_s=60, redact=str)
    assert timed.status == "ok" and timed.reply == "valid"
    gone = run_judge(
        Scripted(StructuredResult("timeout"), StructuredResult("timeout")), PROMPT, timeout_s=5, redact=str
    )
    assert gone.reply == ""


@pytest.mark.parametrize("reply", [long_quote_reply(), list_fix_reply()])
def test_every_fixture_is_invalid_before_and_valid_after(reply):
    assert validate(reply, JUDGE_SCHEMA)
    assert not validate(repair_reply(reply, JUDGE_SCHEMA)[0], JUDGE_SCHEMA)


def test_reply_counts_tally_a_profile_from_the_ledger_events():
    from l4.verifier.judge import reply_counts

    events = [
        {"type": "verify.judge", "profile": "weak", "reply": "valid"},
        {"type": "verify.judge", "profile": "weak", "reply": "repaired"},
        {"type": "verify.judge", "profile": "weak", "reply": "discarded"},
        {"type": "verify.judge", "profile": "other", "reply": "valid"},
        {"type": "verify.judge", "profile": "weak"},  # an older harness: no reply recorded
        {"type": "verify.step", "profile": "weak", "reply": "valid"},
    ]
    assert reply_counts(events, "weak") == {"valid": 1, "repaired": 1, "retried": 0, "discarded": 1}
