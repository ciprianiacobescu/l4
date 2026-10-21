from l4.eval.errors import CellError, classify, invalidating
from l4.redact import Redactor

from ._ledgers import ev

SECRET = "sk-ant-abcdefghijklmnopqrstuvwx"
RED = Redactor({})


def kinds(errors: list[CellError]) -> list[str]:
    return [e.kind for e in errors]


def test_result_invalid_on_a_prompt_contract_adapter_is_schema() -> None:
    events = [ev("task.attempt_failed", task="1.1", phase="red", attempt=1,
                 reason="the agent step ended with status error: result invalid: $.status: not one of the allowed",
                 excerpt_lines=0)]  # fmt: skip
    assert kinds(classify(events, "", RED)) == ["schema"]


def test_result_invalid_on_a_native_adapter_is_schema() -> None:
    events = [ev("task.attempt_failed", task="1.1", phase="red", attempt=1,
                 reason="the agent's result is invalid: $.summary: required", excerpt_lines=0)]  # fmt: skip
    assert kinds(classify(events, "", RED)) == ["schema"]


def test_a_schema_invalid_judge_reply_is_schema() -> None:
    events = [ev("verify.judge", round=1, profile="j", status="schema_invalid", calls=2, model=None)]
    assert kinds(classify(events, "", RED)) == ["schema"]


def test_a_429_is_rate_limit() -> None:
    events = [ev("availability.limit", tool="opencode", kind="rate_limit", source="opencode.statusCode", excerpt="429")]
    assert kinds(classify(events, "", RED)) == ["rate_limit"]
    events = [ev("availability.limit", tool="claude-code", kind="usage_limit", source="x", excerpt="limit")]
    assert kinds(classify(events, "", RED)) == ["rate_limit"]


def test_an_agent_status_rate_limited_is_rate_limit() -> None:
    events = [ev("agent.finished", task="1.1", phase="red", status="rate_limited", exit_code=1, detail=None)]
    assert kinds(classify(events, "", RED)) == ["rate_limit"]


def test_endpoint_unavailable_and_geo_block_are_unavailable() -> None:
    log = "Error from provider (Console): Upstream request failed: Endpoint is unavailable."
    assert kinds(classify([], log, RED)) == ["unavailable"]
    assert kinds(classify([], "HTTP 403: not available in your region (geo)", RED)) == ["unavailable"]


def test_a_rate_limit_that_names_an_unavailable_endpoint_is_both_rate_limit_and_unavailable() -> None:
    events = [
        ev("availability.limit", tool="opencode", kind="rate_limit", source="s", excerpt="Endpoint is unavailable")
    ]
    assert set(kinds(classify(events, "Endpoint is unavailable", RED))) == {"rate_limit", "unavailable"}


def test_a_timeout_status_is_timeout() -> None:
    events = [ev("agent.finished", task="1.1", phase="red", status="timeout", exit_code=None, detail="stalled")]
    assert kinds(classify(events, "", RED)) == ["timeout"]
    events = [ev("task.attempt_failed", task="1.1", phase="green", attempt=1,
                 reason="the agent step ended with status timeout: no detail", excerpt_lines=0)]  # fmt: skip
    assert kinds(classify(events, "", RED)) == ["timeout"]


def test_the_cell_timeout_is_timeout() -> None:
    assert kinds(classify([], "", RED, cell_timeout=True)) == ["timeout"]


def test_an_auth_failure_is_login() -> None:
    events = [ev("agent.finished", task="1.1", phase="red", status="auth", exit_code=1, detail="401")]
    assert kinds(classify(events, "", RED)) == ["login"]


def test_a_cold_offline_cache_is_its_own_error() -> None:
    tail = "× Failed to download `pygments==2.21.0`\n╰─▶ Network connectivity is disabled, but the requested data"
    assert kinds(classify([], "", RED, setup_tail=tail)) == ["setup_cold"]


def test_nothing_recognisable_is_other_only_when_the_run_failed() -> None:
    assert classify([], "all fine", RED) == []
    assert kinds(classify([ev("breaker.tripped", reason="baseline_failed", detail="x")], "", RED)) == ["other"]


def test_the_detail_is_redacted_and_short() -> None:
    redactor = Redactor({"K": SECRET})
    events = [ev("task.attempt_failed", task="1.1", phase="red", attempt=1,
                 reason=f"the agent's result is invalid: {SECRET} " + "x" * 1000, excerpt_lines=0)]  # fmt: skip
    (error,) = classify(events, "", redactor)
    assert SECRET not in error.detail and len(error.detail) <= 200


def test_which_errors_make_a_cell_invalid() -> None:
    def cell(*k: str) -> list[CellError]:
        return [CellError(x, "d") for x in k]

    assert invalidating(cell("rate_limit")) == "rate_limited"
    assert invalidating(cell("unavailable")) == "endpoint_unavailable"
    assert invalidating(cell("login")) == "login"
    assert invalidating(cell("setup_cold")) == "setup_offline_cache_cold"
    assert invalidating(cell("schema")) is None  # counts as a failure
    assert invalidating(cell("timeout")) is None  # an agent timeout counts as a failure
    assert invalidating(cell("schema", "rate_limit")) == "rate_limited"
    assert invalidating([]) is None
