from l4.verifier.judge import run_judge

from .test_judge_run import ID, PROMPT, Scripted, invalid, ok  # noqa: F401


def test_a_served_model_that_is_not_the_requested_one_discards_the_verdict():
    run = run_judge(
        Scripted(ok(model="claude-sonnet-4-5-20250929")), PROMPT, timeout_s=60, redact=str,
        expect_model="claude-haiku-4-5-20251001",
    )  # fmt: skip
    assert run.status == "model_mismatch" and run.verdict is None and run.calls == 1
    assert run.model_resolved == "claude-sonnet-4-5-20250929"
    assert "claude-haiku-4-5-20251001" in run.detail and "claude-sonnet-4-5-20250929" in run.detail
    assert run.cost_usd == 0.05  # the call was paid for


def test_the_same_model_after_normalisation_is_no_mismatch():
    for served in ("claude-haiku-4-5-20251001", "claude-haiku-4-5", "claude-haiku-4-5-20251001[1m]"):
        run = run_judge(Scripted(ok(model=served)), PROMPT, timeout_s=60, redact=str, expect_model="claude-haiku-4-5")
        assert run.status == "ok", served


def test_nothing_is_compared_without_an_expected_model_or_a_served_one():
    assert run_judge(Scripted(ok(model="anything")), PROMPT, timeout_s=60, redact=str).status == "ok"
    served_none = ok(model=None)  # type: ignore[arg-type]
    assert run_judge(Scripted(served_none), PROMPT, timeout_s=60, redact=str, expect_model="claude-x-1").status == "ok"


def test_the_repair_call_is_checked_too():
    run = run_judge(
        Scripted(invalid(), ok(model="claude-opus-4-8")), PROMPT, timeout_s=60, redact=str,
        expect_model="claude-haiku-4-5",
    )  # fmt: skip
    assert run.status == "model_mismatch" and run.calls == 2


def test_an_error_whose_detail_starts_with_model_mismatch_is_a_model_mismatch_with_no_verdict():
    from l4.llm.agent_judge import StructuredResult

    detail = "model_mismatch: kiro-cli could not set claude-sonnet-5.5"
    run = run_judge(Scripted(StructuredResult("error", detail=detail)), PROMPT, timeout_s=60, redact=str)
    assert run.status == "model_mismatch" and run.verdict is None and run.calls == 1
    assert run.detail == detail
