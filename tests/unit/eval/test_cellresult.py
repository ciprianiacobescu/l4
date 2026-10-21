"""A cell's raw run becomes one result: the status, the score, the errors and the invalid reason (plan D5)."""

from l4.eval.cellresult import finish_cell
from l4.eval.cellrun import Cell, CellRaw
from l4.redact import Redactor

from ._ledgers import ev, green_ledger

IMPL = Cell("implementer", "p1", "add-shelf-code", 0)
JUDGE = Cell("judge", "j1", "add-late-fee", 0)
EXPECT_IMPL = {"implementer": {"outcome": "pass"}, "judge": {"verdict": "PASS"}}
EXPECT_JUDGE = {"judge": {"verdict": "NEEDS_HUMAN", "min_findings": 1, "designed_defect": True}}


def raw(events, code=0, log="", invalid=None, report=None, tail="", wall=12.3456):
    return CellRaw(code, list(events), None, log, wall, invalid=invalid, report_text=report, setup_tail=tail)


def finish(cell, r, expected, free=False):
    return finish_cell(cell, r, expected, free=free, redactor=Redactor({}))


def test_a_clean_implementer_run_is_a_pass_with_its_score() -> None:
    result = finish(IMPL, raw(green_ledger()), EXPECT_IMPL)
    assert result["status"] == "pass" and result["invalid_reason"] is None
    assert result["attempts"] == {"red": 1, "green": 1} and result["wall_s"] == 12.346
    assert result["cell_key"] == "implementer|p1|add-shelf-code|0" and result["returncode"] == 0
    assert result["errors"] == [] and result["cost_usd"] is None


def test_a_judge_run_is_scored_against_the_expected_verdict() -> None:
    events = [
        ev("verify.judge", round=1, profile="j1", status="ok", calls=1, model=None),
        ev("verify.verdict", round=1, verdict="NEEDS_HUMAN", findings=2, criteria_passed=1, criteria_total=2),
    ]
    result = finish(JUDGE, raw(events, report="## Findings\n\n- [major, judge] x\n"), EXPECT_JUDGE)
    assert result["status"] == "pass" and result["agreement"] is True and result["worst_severity"] == "major"
    assert result["attempts"] is None


def test_a_rate_limited_cell_is_invalid_not_a_failure() -> None:
    events = [ev("availability.limit", tool="opencode", kind="rate_limit", source="s", excerpt="429")]
    result = finish(IMPL, raw(events, code=12), EXPECT_IMPL)
    assert result["status"] == "invalid" and result["invalid_reason"] == "rate_limited"
    assert [e["kind"] for e in result["errors"]] == ["rate_limit"]


def test_a_schema_error_that_halts_the_cell_is_a_failure() -> None:
    events = [
        ev("task.started", task="1.1", title="t"),
        ev("task.attempt_failed", task="1.1", phase="red", attempt=1, reason="the agent's result is invalid: x",
           excerpt_lines=0),
        ev("breaker.tripped", reason="max_task_attempts", task="1.1", phase="red", attempts=1, last_failure="x"),
    ]  # fmt: skip
    result = finish(IMPL, raw(events, code=13), EXPECT_IMPL)
    assert result["status"] == "fail" and result["halted_at"] == "red"
    assert [e["kind"] for e in result["errors"]] == ["schema"]


def test_exit_12_without_a_recognised_limit_is_unavailable() -> None:
    result = finish(IMPL, raw([], code=12, log="required role unavailable"), EXPECT_IMPL)
    assert result["status"] == "invalid" and result["invalid_reason"] == "endpoint_unavailable"


def test_an_l4_crash_is_invalid_with_the_last_log_line_not_a_failure_of_the_model() -> None:
    """Exit 1, 2 or 3 of the child `l4 run` is the harness or its environment failing (the review found every live
    cell exiting 2 at preflight): the model was not measured, so the cell is left out of the rate instead of reading
    as a 0% profile that a later fix would turn into a false `improved`, or a harness break into a false regression."""
    for code in (1, 2, 3):
        result = finish(IMPL, raw([], code=code, log="l4: config error\nroles.judges is empty"), EXPECT_IMPL)
        assert result["status"] == "invalid" and result["invalid_reason"] == "harness_error", code
        assert result["errors"][0]["kind"] == "other" and f"exit {code}" in result["errors"][0]["detail"]
        assert "roles.judges is empty" in result["errors"][0]["detail"]
    after_the_work = finish(IMPL, raw(green_ledger(), code=1, log="Traceback"), EXPECT_IMPL)
    assert after_the_work["status"] == "invalid" and after_the_work["invalid_reason"] == "harness_error"


def test_a_crash_with_a_known_cause_keeps_that_cause() -> None:
    events = [ev("gate.finished", name="setup", status="fail", exit_code=1, reason="x", log="l")]
    cold = finish(IMPL, raw(events, code=3, tail="Network connectivity is disabled, but"), EXPECT_IMPL)
    assert cold["invalid_reason"] == "setup_offline_cache_cold"
    after_red = [*green_ledger()[:6], ev("breaker.tripped", reason="baseline_failed", detail="at the red checkpoint")]
    halted = finish(IMPL, raw(after_red, code=13), EXPECT_IMPL)
    assert halted["status"] == "fail"  # the model ran: a designed stop of the run is still the cell's outcome


def test_the_cell_timeout_and_the_precheck_reasons_are_invalid() -> None:
    assert finish(IMPL, raw([], code=None, invalid="cell_timeout"), EXPECT_IMPL)["invalid_reason"] == "cell_timeout"
    veto = finish(IMPL, CellRaw(None, [], None, "", 0.0, invalid="vendor_veto"), EXPECT_IMPL)
    assert veto["status"] == "invalid" and veto["invalid_reason"] == "vendor_veto" and veto["errors"] == []


def test_a_cold_offline_cache_is_invalid_with_its_own_reason() -> None:
    events = [ev("gate.finished", name="setup", status="fail", exit_code=1, reason="x", log="l")]
    result = finish(IMPL, raw(events, code=13, tail="Network connectivity is disabled, but"), EXPECT_IMPL)
    assert result["invalid_reason"] == "setup_offline_cache_cold"


def test_cost_free_declaration_and_tokens() -> None:
    result = finish(IMPL, raw(green_ledger()), EXPECT_IMPL, free=True)
    assert result["cost_usd"] == 0.0 and result["input_tokens"] == 200 and result["output_tokens"] == 20


# --- a cell whose model under test never ran measured nothing about it
def test_a_baseline_that_fails_before_the_implementer_ran_is_invalid() -> None:
    """The base project's tests cannot run in the cell's environment (a sandbox, a seed, a uv fault): the breaker trips
    before any agent step, so the cell says nothing about the model and must not count against it (exit 13)."""
    events = [
        ev("run.started"), ev("task.started", task="1.1", title="t"),
        ev("breaker.tripped", reason="baseline_failed", detail="the test gate cannot run at the base: report missing"),
    ]  # fmt: skip
    result = finish(IMPL, raw(events, code=13), EXPECT_IMPL)
    assert result["status"] == "invalid" and result["invalid_reason"] == "baseline_failed"
    assert [e["kind"] for e in result["errors"]] == ["other"] and "baseline_failed" in result["errors"][0]["detail"]
    other = [ev("breaker.tripped", reason="unselectable_task", task="1.1")]
    assert finish(IMPL, raw(other, code=13), EXPECT_IMPL)["invalid_reason"] == "halted_before_agent"


def test_a_judge_cell_whose_judge_was_never_called_is_invalid() -> None:
    """The reference replay halted (or the run ended) before verification: the judge under test gave no reply, so the
    cell is not a disagreement of the judge."""
    replay_halted = [
        ev("run.started"), *green_ledger()[1:6],
        ev("breaker.tripped", reason="max_task_attempts", task="1.1", phase="red", attempts=3, last_failure="x"),
    ]  # fmt: skip
    result = finish(JUDGE, raw(replay_halted, code=13), EXPECT_JUDGE)
    assert result["status"] == "invalid" and result["invalid_reason"] == "judge_not_reached"
    judged = [ev("verify.judge", round=1, profile="j1", status="timeout", calls=1, model=None)]
    timed_out = finish(JUDGE, raw(judged, code=11), EXPECT_JUDGE)
    assert timed_out["status"] == "fail"  # called, and it timed out: a failure of the judge


def test_a_harness_error_in_the_setup_gate_names_the_setup_cause() -> None:
    """The cell's workspace is deleted after the cell, so the only trace of a failed setup gate is its excerpt: the
    detail carries the last line of the setup log (redacted), not the run's "see <path>" line."""
    events = [ev("gate.finished", name="setup", status="fail", exit_code=1, reason="exit code 1", log="l")]
    tail = "Resolved 5 packages\nerror: No interpreter found for Python >=3.12 in virtual environments\n"
    log = "[l4] run: openspec:x: gates.setup failed (exit code 1); see /home/u/out/cells/c/ws/repo/.l4-out/gates/1.log"
    result = finish(IMPL, raw(events, code=3, log=log, tail=tail), EXPECT_IMPL)
    assert result["invalid_reason"] == "harness_error"
    assert result["errors"][-1]["detail"] == (
        "l4 run exit 3: setup: error: No interpreter found for Python >=3.12 in virtual environments"
    )


# --- live run 2026-10-08: the reference judge was not logged in, and the cell blocked the implementer under test
def unavailable(role: str, profile: str, step: str, reason: str) -> dict:
    return ev("availability.unavailable", role=role, required=True, retry_after="2026-10-08T01:51:42Z",
              skipped=[{"profile": profile, "step": step, "reason": reason}])  # fmt: skip


def test_an_unavailable_reference_judge_is_not_the_implementers_fault() -> None:
    """f-muse wrote red and green, then the fixed judge (claude-code) failed its auth probe and the run waited for
    capacity (exit 12). The cell measured nothing about the judge's verdict on f-muse's work, and nothing about f-muse
    went wrong: it is `reference_unavailable`, never `endpoint_unavailable` (that reason stops the profile)."""
    events = [*green_ledger()[:-2], unavailable("judges", "claude-code", "auth", "claude is not logged in")]
    result = finish(IMPL, raw(events, code=12), EXPECT_IMPL)
    assert result["status"] == "invalid" and result["invalid_reason"] == "reference_unavailable"
    assert [e["kind"] for e in result["errors"]] == ["unavailable"]
    assert (
        result["errors"][0]["detail"]
        == "the reference judges profile is unavailable: claude-code auth: claude is not logged in"
    )


def test_the_replay_implementer_unavailable_is_the_reference_of_a_judge_cell() -> None:
    events = [unavailable("implementer", "eval-reference", "binary", "python not found")]
    assert finish(JUDGE, raw(events, code=12), EXPECT_JUDGE)["invalid_reason"] == "reference_unavailable"


def test_the_measured_profile_not_logged_in_is_a_login_reason() -> None:
    events = [unavailable("implementer", "p1", "auth", "codex is not logged in (ChatGPT login required)")]
    result = finish(IMPL, raw(events, code=12), EXPECT_IMPL)
    assert result["invalid_reason"] == "login" and [e["kind"] for e in result["errors"]] == ["login"]
    hello = [unavailable("implementer", "p1", "hello", "hello timed out")]
    assert finish(IMPL, raw(hello, code=12), EXPECT_IMPL)["invalid_reason"] == "endpoint_unavailable"
