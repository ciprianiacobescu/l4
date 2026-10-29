"""The progress trace: ledger events become `[l4] <unit> <message>` lines, and a secret never reaches the console."""

import io
import logging
from datetime import UTC, datetime
from pathlib import Path

import pytest

from l4.log import RedactingFormatter
from l4.progress import ProgressTrace
from l4.redact import Redactor
from l4.state.ledger import LedgerEvent, LedgerWriter

RUN = "r-20261004T1200Z-abcd"
GITLAB_TOKEN = "glpat-" + "k9L8m7N6" * 3
CONFIGURED = "hunter2-hunter2-hunter2"


@pytest.fixture
def console():
    """The `l4` logger writing into a buffer through the real formatter, as `configure_logging` wires it."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(RedactingFormatter(Redactor({"L4_FORGE_TOKEN": CONFIGURED}), as_json=False))
    logger = logging.getLogger("l4")
    saved = (list(logger.handlers), logger.level, logger.propagate)
    logger.handlers, logger.propagate = [handler], False
    logger.setLevel(logging.INFO)
    yield stream
    logger.handlers, logger.level, logger.propagate = saved[0], saved[1], saved[2]


def event(type_: str, **data: object) -> LedgerEvent:
    return LedgerEvent(datetime(2026, 10, 4, 12, 0, tzinfo=UTC), RUN, "openspec:demo", 1, type_, data)


def test_a_token_in_an_event_never_reaches_the_console_through_the_ledger(console, tmp_path: Path):
    redactor = Redactor({"L4_FORGE_TOKEN": CONFIGURED})
    writer = LedgerWriter.open(tmp_path, "openspec:demo", RUN, redactor=redactor, observers=[ProgressTrace()])
    writer.append("task.started", task="1.1", title=f"use {GITLAB_TOKEN} and {CONFIGURED}")
    writer.append("question.raised", id="Q-001", kind="ambiguous", title=f"is {GITLAB_TOKEN} ok?")
    writer.append("run.finished", exit_code=0)
    out = console.getvalue()
    assert "task 1.1 started" in out and "question Q-001 raised" in out and "run finished: exit 0" in out
    assert GITLAB_TOKEN not in out and CONFIGURED not in out
    assert GITLAB_TOKEN not in (tmp_path / ".l4" / "ledger" / f"{RUN}.jsonl").read_text()


def test_a_token_handed_straight_to_the_trace_is_still_redacted_by_the_log_formatter(console):
    trace = ProgressTrace()
    trace(event("task.started", task="1.1", title=f"x {GITLAB_TOKEN} {CONFIGURED}"))
    trace(event("gate.finished", name="test", status="fail", exit_code=1, reason=f"boom {GITLAB_TOKEN}", tests=1,
                passed=0, failed=1))  # fmt: skip
    out = console.getvalue()
    assert out.count("[l4] openspec:demo ") == 2
    assert GITLAB_TOKEN not in out and CONFIGURED not in out and "[REDACTED:" in out


def test_selection_line_follows_the_spec_format(console):
    probes = {"binary": {"version": "0.160.0"}, "auth": {"auth_method": "chatgpt"}, "hello": {"ms": 4200}}
    ProgressTrace()(event("availability.selected", role="implementer", selected="codex", fallback_index=0,
                          skipped=[], probes=probes))  # fmt: skip
    assert console.getvalue() == (
        "[l4] openspec:demo implementer: codex ok (binary 0.160.0 · auth chatgpt · hello 4.2s) → selected\n"
    )


def test_an_unknown_event_prints_nothing_and_a_broken_one_does_not_raise(console):
    trace = ProgressTrace()
    trace(event("something.new", x=1))
    trace(event("gate.finished"))  # no fields at all
    assert "something" not in console.getvalue()


def test_a_fix_units_task_with_the_parents_task_key_is_told_apart_and_nothing_crashes(console):
    trace = ProgressTrace()
    trace(event("task.started", task="1.1", title="parent task"))
    trace(event("step.started", task="1.1", phase="red", attempt=1, agent="impl"))
    trace(event("agent.finished", task="1.1", phase="red", status="ok"))
    trace(event("task.started", task="1.1", title="fix task", fix_unit="demo-fix-1"))
    trace(event("step.started", task="1.1", phase="single", attempt=1, agent="impl", fix_unit="demo-fix-1"))
    trace(event("agent.finished", task="1.1", phase="single", status="ok", fix_unit="demo-fix-1"))
    trace(event("agent.finished", task="1.1", phase="single", status="ok", fix_unit="demo-fix-1"))  # no start: no crash
    lines = console.getvalue().splitlines()
    assert "[l4] openspec:demo task 1.1 started: parent task" in lines
    assert "[l4] openspec:demo [demo-fix-1] task 1.1 started: fix task" in lines
    assert all("agent single task 1.1 ok" in line for line in lines if "agent single task" in line)


def test_base_merge_lines(console):
    logging.getLogger("l4").setLevel(logging.INFO)
    trace = ProgressTrace()
    trace(event("run.started", branch="l4/openspec/demo", base="a" * 40, iteration=1, harness_commit="b" * 40))
    trace(event("base.merged", base="main", base_sha="c" * 40, merge_sha="d" * 40, behind=1, resolved=[],
                frozen_touched=[]))  # fmt: skip
    trace(event("base.merged", base="main", base_sha="e" * 40, merge_sha="f" * 40, behind=4,
                resolved=["openspec/changes/demo/questions.md"], frozen_touched=[]))  # fmt: skip
    trace(event("base.conflict", base="main", base_sha="1" * 40, files=["src/a.py", "src/b.py"], resolved=[]))
    lines = [line for line in console.getvalue().splitlines() if "base" in line and "run " not in line]
    assert lines == [
        "[l4] openspec:demo base merged: main@cccccccccc into l4/openspec/demo as dddddddddd (1 commit)",
        "[l4] openspec:demo base merged: main@eeeeeeeeee into l4/openspec/demo as ffffffffff "
        "(4 commits; resolved openspec/changes/demo/questions.md)",
        "[l4] openspec:demo base merge conflict with main@1111111111: src/a.py, src/b.py; "
        "merge it by hand and push (exit 1)",
    ]


def test_a_check_the_run_makes_after_setup_is_on_the_console(console):
    trace = ProgressTrace()
    message = "coverage.py is not importable by .venv/bin/python"
    trace(event("doctor.check", id="COV-001", status="fail", message=message))
    trace(event("doctor.check", id="COV-001", status="pass", message="coverage.py imports in .venv/bin/python"))
    out = console.getvalue()
    assert "doctor COV-001 fail: coverage.py is not importable" in out and "doctor COV-001 pass:" in out


def test_review_reentry_and_ci_lines(console):
    trace = ProgressTrace()
    trace(event("run.started", branch="l4/openspec/demo", base="a" * 40, iteration=2))
    trace(event("phase.changed", **{"from": "in_review", "to": "verifying"}, trigger="commit_after_handoff",
                handoff="h" * 40, lost=False,
                commits=[{"sha": "1" * 40, "author": "ann", "subject": "fix the CI job"}]))  # fmt: skip
    trace(event("phase.changed", **{"from": "in_review", "to": "implementing"}, trigger="spec_edit_after_handoff",
                handoff="h" * 40, lost=False,
                commits=[{"sha": "2" * 40, "author": "bob", "subject": "add a task"},
                         {"sha": "3" * 40, "author": "ann", "subject": "answer Q-001"}]))  # fmt: skip
    trace(event("phase.changed", **{"from": "in_review", "to": "verifying"}, trigger="repository_ci_failed",
                head="h" * 40, pipeline=7, jobs=[{"name": "test"}, {"name": "lint"}], preexisting=[]))  # fmt: skip
    trace(event("ci.failed", head="h" * 40, pipeline=7, jobs=[{"name": "test"}, {"name": "lint"}], preexisting=[]))
    trace(event("ci.preexisting", head="h" * 40, pipeline=7, jobs=["always-red"]))
    lines = [line for line in console.getvalue().splitlines() if "started (iteration" not in line]
    assert lines == [
        "[l4] openspec:demo phase in_review → verifying (commit_after_handoff: 1 commit, 1111111111 fix the CI job "
        "by ann)",
        "[l4] openspec:demo phase in_review → implementing (spec_edit_after_handoff: 2 commits, 3333333333 answer "
        "Q-001 by ann)",
        "[l4] openspec:demo phase in_review → verifying (repository_ci_failed: test, lint on hhhhhhhhhh)",
        "[l4] openspec:demo repository CI failed on hhhhhhhhhh: test, lint (pipeline 7); l4 run re-verifies",
        "[l4] openspec:demo CI jobs red on H and on the base: always-red (pre-existing, no fix round)",
    ]


def test_zeroed_runs_say_they_are_expected_to_fail(console):
    trace = ProgressTrace()
    trace(event("gate.finished", name="test-presatisfied", status="fail", exit_code=1))
    trace(event("gate.finished", name="test-zero", status="fail", exit_code=1))
    trace(event("gate.finished", name="test-zero", status="pass", exit_code=0))  # a zeroed run that passes: notable
    trace(event("gate.finished", name="test", status="fail", exit_code=1))
    assert console.getvalue().splitlines() == [
        "[l4] openspec:demo gate test-presatisfied fail (expected: zero values must fail) (exit 1)",
        "[l4] openspec:demo gate test-zero fail (expected: zero values must fail) (exit 1)",
        "[l4] openspec:demo gate test-zero pass (exit 0)",
        "[l4] openspec:demo gate test fail (exit 1)",
    ]


def test_the_ci_step_and_an_unfrozen_task_have_their_own_lines(console):
    trace = ProgressTrace()
    trace(event("ci.step", job="test", status="derived", command="make test", step="make test", reason=None))
    trace(event("ci.step", job="lint", status="skipped", command=None, step="make x", reason="docker is out"))
    trace(event("task.unfrozen", task="1.1", paths=["tests/test_notices.py"], question="Q-002"))
    out = console.getvalue()
    assert "CI job test: failing step derived `make test`" in out
    assert "CI job lint: failing step skipped (docker is out) `make x`" in out
    assert "task 1.1 unfrozen by Q-002: tests/test_notices.py" in out


def test_question_raised_prints_the_title_or_the_target(console):
    trace = ProgressTrace()
    trace(event("question.raised", id="Q-001", kind="ambiguous", title="Scenarios clash"))
    trace(event("question.raised", id="Q-002", kind="verdict", target="C-0a1b2c3d"))  # a ledger without a title
    trace(event("question.raised", id="Q-003", kind="ambiguous"))
    out = console.getvalue().splitlines()
    assert out[0].endswith("question Q-001 raised (ambiguous): Scenarios clash")
    assert out[1].endswith("question Q-002 raised (verdict): C-0a1b2c3d")
    assert out[2].endswith("question Q-003 raised (ambiguous)")  # never `: None`
    assert "None" not in console.getvalue()


def test_an_already_satisfied_task_prints_the_truth_and_no_green_line(console):
    trace = ProgressTrace()
    trace(event("task.red_ok", task="2.2", tests=["t::a"], tdd="already-satisfied"))
    trace(event("task.done", task="2.2", tdd="already-satisfied"))
    out = console.getvalue()
    assert "task 2.2 already satisfied: 1 new test passes on the base, no green step" in out
    assert "red ok" not in out and "green ok" not in out and "failing as expected" not in out


def test_an_already_satisfied_task_with_no_new_test_names_the_existing_tests(console):
    trace = ProgressTrace()
    trace(event("task.red_ok", task="2.1", tests=[], tdd="already-satisfied"))
    out = console.getvalue()
    assert "task 2.1 already satisfied by existing tests, no green step" in out
    assert "0 new tests" not in out


def test_a_red_green_task_still_prints_red_ok_and_green_ok(console):
    trace = ProgressTrace()
    trace(event("task.red_ok", task="1.1", tests=["t::a", "t::b"]))
    trace(event("task.done", task="1.1", tdd="green"))
    out = console.getvalue()
    assert "task 1.1 red ok: 2 new test(s) failing as expected" in out
    assert "task 1.1 green ok: all tests passing" in out


def test_a_file_opened_by_the_task_text_has_its_own_line(console):
    trace = ProgressTrace()
    trace(event("task.unfrozen", task="2.1", paths=["conftest.py"], reason="named_by_task", source="plan:p1@abc123"))
    trace(
        event(
            "task.unfrozen",
            task="2.2",
            paths=[],
            reason="named_by_task",
            source="base:0123456789",
            kept=[{"path": ".gitignore", "why": "an ignore file"}],
        )
    )
    trace(event("task.unfrozen", task="1.1", paths=["tests/t.py"], reason="human_answer", question="Q-002"))
    out = console.getvalue().splitlines()
    assert out[0].endswith("task 2.1 opened by its text (plan:p1@abc123): conftest.py")
    assert out[1].endswith("task 2.2 opened by its text (base:0123456789): nothing; kept .gitignore (an ignore file)")
    assert out[2].endswith("task 1.1 unfrozen by Q-002: tests/t.py")


def lines(console) -> list[str]:
    return [ln.removeprefix("[l4] openspec:demo ") for ln in console.getvalue().splitlines()]


def test_scn_imp_184_the_escalation_lines_name_the_profiles(console):
    trace = ProgressTrace()
    probes = {"binary": {"version": "1.0"}}
    trace(event("task.attempt_failed", task="4.1", phase="red", attempt=2, profile="deepseek", reason="no tests"))
    trace(
        event("implementer.escalated", task="4.1", phase="red", **{"from": "deepseek"}, to="glm", failures=2, attempt=3)
    )
    trace(event("availability.selected", role="implementer", selected="glm", fallback_index=1, skipped=[],
                probes=probes, escalated_from="deepseek"))  # fmt: skip
    trace(event("task.attempt_failed", task="4.1", phase="red", attempt=5, profile="glm", reason="still red"))
    trace(event("breaker.tripped", reason="max_task_attempts", task="4.1", phase="red", attempts=5,
                profiles=[{"profile": "deepseek", "failures": 2}, {"profile": "glm", "failures": 3}]))  # fmt: skip
    assert lines(console) == [
        "task 4.1 red attempt 2 failed on deepseek: no tests",
        "task 4.1 red: escalated from deepseek to glm after 2 failed attempts",
        "implementer: glm ok (binary 1.0) → selected, escalated from deepseek",
        "task 4.1 red attempt 5 failed on glm: still red",
        "halted: max_task_attempts (task 4.1: deepseek 2, glm 3)",
    ]


def test_an_escalated_selection_does_not_also_print_a_fallback_number(console):
    ProgressTrace()(event("availability.selected", role="implementer", selected="glm", fallback_index=1, skipped=[],
                          probes={}, escalated_from="deepseek"))  # fmt: skip
    assert "fallback" not in console.getvalue()


def test_a_skipped_escalation_is_a_warning(console):
    ProgressTrace()(event("implementer.escalation_skipped", task="4.1", phase="red", **{"from": "deepseek"},
                          failures=2, reason="glm is cooling"))  # fmt: skip
    assert lines(console) == [
        "task 4.1 red: deepseek failed 2 attempts; no later profile can take it (glm is cooling); it stays on deepseek"
    ]


def test_a_retry_note_in_the_prompt_has_a_line_and_a_prompt_without_one_none(console):
    trace = ProgressTrace()
    trace(event("prompt.rendered", task="4.1", phase="red", sha256="x"))
    trace(event("prompt.rendered", task="4.1", role="red", sha256="x",
                retry_note={"event": "unit.retried", "ts": "2026-10-04T11:00:00Z", "sha256": "y"}))  # fmt: skip
    assert lines(console) == ["task 4.1 red: the prompt holds the person's retry note of 2026-10-04T11:00:00Z"]


def test_older_events_print_as_before(console):
    trace = ProgressTrace()
    trace(event("task.attempt_failed", task="1.1", phase="red", attempt=1, reason="no tests"))
    trace(event("breaker.tripped", reason="max_task_attempts", task="1.1", profiles=[{"profile": "a", "failures": 3}]))
    trace(event("availability.selected", role="implementer", selected="b", fallback_index=1, skipped=[], probes={}))
    assert lines(console) == [
        "task 1.1 red attempt 1 failed: no tests",
        "halted: max_task_attempts (task 1.1)",
        "implementer: b ok → selected, fallback #1",
    ]


def _normalized(console, *fixes, **extra):
    ProgressTrace()(event("result.normalized", task="1.1", phase="red", attempt=1, source="result",
                          fixes=list(fixes), **extra))  # fmt: skip
    return lines(console)


def test_scn_imp_188_the_repaired_result_line(console):
    assert _normalized(console, {"field": "status", "fix": "set", "to": "done", "was": "red"}) == [
        "task 1.1 red attempt 1: L4 repaired the result (status set to done, was red)"
    ]


def test_scn_imp_188_every_fix_has_its_details(console):
    fixes = [
        {"field": "summary", "fix": "set", "from": "final_message"},
        {"field": "notes_for_verifier", "fix": "cut", "length": 2417},
        {"field": "notes_for_verifier", "fix": "renamed", "from": "notes"},
        {"field": "questions", "fix": "dropped", "count": 2},
        {"field": "suppressions", "fix": "cut", "count": 2},
        {"field": "files_changed", "fix": "replaced"},
    ]
    assert _normalized(console, *fixes) == [
        "task 1.1 red attempt 1: L4 repaired the result (summary set from final_message; "
        "notes_for_verifier cut from 2417 characters; notes_for_verifier renamed from notes; "
        "questions dropped 2; suppressions cut 2; files_changed replaced)"
    ]


def test_a_normalized_event_without_fixes_does_not_crash(console):
    assert _normalized(console) == ["task 1.1 red attempt 1: L4 repaired the result ()"]


def test_scn_fac_18_the_agent_line_ends_with_the_context_peak(console):
    trace = ProgressTrace()
    trace(event("agent.finished", task="1.1", phase="red", status="ok", context_peak_tokens=21600))
    trace(event("agent.finished", task="1.2", phase="red", status="ok", context_peak_percent=3.6))
    out = lines(console)
    assert out[0].endswith(", context peak 21.6k tokens")
    assert out[1].endswith(", context peak 3.6%")


def test_scn_fac_19_an_older_agent_finished_prints_as_today(console):
    ProgressTrace()(event("agent.finished", task="1.1", phase="red", status="ok"))
    (line,) = lines(console)
    assert line.startswith("agent red task 1.1 ok (") and line.endswith(")")
    assert "context peak" not in line


def _debug(console):
    logging.getLogger("l4").setLevel(logging.DEBUG)


def test_the_step_start_line_is_at_info(console):
    ProgressTrace()(event("step.started", task="5.2", phase="green", attempt=1, agent="deepseek"))
    assert lines(console) == ["agent green step started (task 5.2, attempt 1, deepseek)"]


def test_the_idle_line_is_a_warning_naming_the_key(console):
    ProgressTrace()(
        event("agent.idle", task="2.1", phase="red", attempt=1, profile="deepseek", silent_s=600, tool_calls=3)
    )
    assert lines(console) == [
        "task 2.1 red attempt 1: no activity from deepseek for 10m; L4 stopped it (implementer.idle_timeout)"
    ]
    logging.getLogger("l4").setLevel(logging.ERROR)
    ProgressTrace()(event("agent.idle", task="2.1", phase="red", attempt=1, profile="d", silent_s=600))
    logging.getLogger("l4").setLevel(logging.WARNING)
    ProgressTrace()(event("agent.idle", task="2.1", phase="red", attempt=2, profile="d", silent_s=3720))
    assert lines(console)[-1].endswith("for 1h 2m; L4 stopped it (implementer.idle_timeout)")


def test_a_silent_idle_line_says_it_is_a_limit_of_the_profile(console):
    ProgressTrace()(
        event("agent.idle", task="2.1", phase="red", attempt=1, profile="free", silent_s=600, tool_calls=0, silent=True)
    )
    ProgressTrace()(
        event(
            "agent.idle", task="2.1", phase="red", attempt=2, profile="free", silent_s=600, tool_calls=1, silent=False
        )
    )
    assert lines(console) == [
        "task 2.1 red attempt 1: no activity from free for 10m; L4 stopped it (implementer.idle_timeout); "
        "no tool call was made, so it is a limit of the profile, not a failed attempt",
        "task 2.1 red attempt 2: no activity from free for 10m; L4 stopped it (implementer.idle_timeout)",
    ]
    ProgressTrace()(
        event(
            "agent.idle",
            task="2.1",
            phase="red",
            attempt=3,
            profile="glm",
            silent_s=600,
            tool_calls=0,
            silent=False,
            reason="silent: already once for this task",
        )
    )
    assert lines(console)[-1].endswith(
        "(implementer.idle_timeout); silent: already once for this task, so it counts as a failed attempt"
    )


def test_scn_obs_03_a_red_gate_with_new_failing_tests_prints_the_red_line(console):
    _debug(console)
    gate = {"name": "test", "status": "fail", "exit_code": 1, "tests": 12, "passed": 5, "failed": 7}
    ProgressTrace()(event("gate.finished", red_new_failing=7, **gate))
    ProgressTrace()(event("gate.finished", **{**gate, "tests": 6, "passed": 5, "failed": 1}, red_new_failing=1))
    assert lines(console) == [
        "red: 7 new tests fail, as intended",
        "gate test fail (exit 1, 12 tests: 5 passed, 7 failed)",
        "red: 1 new test fails, as intended",
        "gate test fail (exit 1, 6 tests: 5 passed, 1 failed)",
    ]


def test_scn_obs_03_the_raw_gate_line_is_not_at_info(console):
    ProgressTrace()(event("gate.finished", name="test", status="fail", exit_code=1, red_new_failing=2))
    assert lines(console) == ["red: 2 new tests fail, as intended"]


def test_scn_obs_04_a_gate_without_the_key_prints_as_today(console):
    ProgressTrace()(event("gate.finished", name="test", status="fail", exit_code=1, tests=3, passed=2, failed=1))
    assert lines(console) == ["gate test fail (exit 1, 3 tests: 2 passed, 1 failed)"]


REASON = "the test-presatisfied run ran no test (exit 2, 45 collection errors)"


def test_scn_imp_318_a_variant_run_that_ran_no_test_does_not_say_expected(console):
    """L4-IMP-064: a zeroed run that executed nothing was not "expected to fail": it did not run."""
    trace = ProgressTrace()
    trace(event("gate.finished", name="test-presatisfied", status="fail", exit_code=2, tests=0, passed=0, failed=0,
                collection_errors=45))  # fmt: skip
    trace(event("gate.finished", name="test-presatisfied", status="fail", exit_code=1, tests=2001, passed=1999,
                failed=2, collection_errors=0))  # fmt: skip
    trace(event("gate.finished", name="test-extra-zero", status="fail", exit_code=2, tests=0, passed=0, failed=0))
    trace(event("gate.finished", name="test-extra-zero", status="fail", exit_code=1, tests=3, passed=1, failed=2))
    lines = console.getvalue().splitlines()
    assert lines[0] == "[l4] openspec:demo gate test-presatisfied fail (exit 2, 0 tests: 0 passed, 0 failed)"
    assert lines[1].startswith("[l4] openspec:demo gate test-presatisfied fail (expected: zero values must fail)")
    assert lines[2] == "[l4] openspec:demo gate test-extra-zero fail (exit 2, 0 tests: 0 passed, 0 failed)"
    assert "(expected: zero values must fail)" in lines[3]


def test_the_held_check_and_the_kept_functions_are_printed(console):
    trace = ProgressTrace()
    trace(event("check.inconclusive", task="2.2", phase="red", check="pre_satisfied", reason=REASON, question="Q-007"))
    trace(event("check.accepted", task="2.2", check="pre_satisfied", question="Q-007", criteria=["C-1", "C-2"]))
    trace(event("zero.kept", gate="test-presatisfied", rerun=1, cause="collection",
                functions=["src/pytdd/telemetry.py::traced"]))  # fmt: skip
    assert console.getvalue().splitlines() == [
        f"[l4] openspec:demo task 2.2 red: the pre_satisfied check could not decide ({REASON}); no attempt counted, "
        "Q-007 asks a person",
        "[l4] openspec:demo task 2.2: Q-007 accepted 2 criteria on the evidence of the real run",
        "[l4] openspec:demo gate test-presatisfied: kept 1 function(s) real (collection): "
        "src/pytdd/telemetry.py::traced",
    ]


def test_the_artefacts_line_says_when_nothing_was_uploaded(caplog):
    from l4.progress import artefacts_note, log_artefacts

    github = {"GITHUB_ACTIONS": "true"}
    assert artefacts_note(github, False) == (
        " (not uploaded: ci.upload_artifacts is false; the ledger's gate.finished and task.attempt_failed events "
        "carry the excerpts)"
    )
    assert artefacts_note(github, True) == "" and artefacts_note({}, False) == ""
    with caplog.at_level(logging.INFO, logger="l4"):
        log_artefacts(Path("/o"), "r-1", artefacts_note(github, False))
        log_artefacts(Path("/o"), "r-2")
    first, second = (r.getMessage() for r in caplog.records if "artefacts:" in r.getMessage())
    assert first.endswith("carry the excerpts)") and "(CI: job artifacts)" not in first
    assert second.endswith("(CI: job artifacts)")


def test_an_unfreeze_by_the_delegate_is_labelled(console):  # delegate-answers 6.2, L4-DLG-014
    trace = ProgressTrace()
    trace(
        event(
            "task.unfrozen", task="1.1", paths=["tests/t.py"], reason="delegate_answer", question="Q-008",
            by="delegate", profile="delegate-opus", model="claude-opus-5-5",
        )
    )  # fmt: skip
    assert (
        console.getvalue()
        .splitlines()[0]
        .endswith("task 1.1 unfrozen by Q-008 (delegate_override, claude-opus-5-5): tests/t.py")
    )
