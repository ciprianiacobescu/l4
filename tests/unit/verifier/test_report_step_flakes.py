"""L4-VER-082 (SCN-VER-322, SCN-VER-323): verification lists the pre-existing tests that passed only on a task step's
re-run, from the ledger. Not a finding, and the verdict does not change."""

import json

import pytest

from l4.state.ledger import LedgerEvent
from l4.verifier.evidence import restore_round
from l4.verifier.ladder import MAX_STEP_FLAKES, _step_flakes
from l4.verifier.report import render_verification_md, verdict_json
from l4.verifier.types import Verdict, VerifyResult

from ._integrity_helpers import STAMP, UNIT
from .test_report import BASE, HEAD, result

HEADING = "## Pre-existing tests that passed on a task step's re-run (L4-IMP-105)"
FLAKY = "tests.test_stack::test_ready"


def rechecked(seq: int, *, stopped: str = "passed", flaky=(FLAKY,), task="1.2", phase="green", attempt=1, **more):
    data = {"task": task, "phase": phase, "attempt": attempt, "tests": list(flaky), "flaky": list(flaky),
            "failing": [], "new_failures": [], "stopped": stopped, **more}  # fmt: skip
    return LedgerEvent(STAMP, "r-20261004T0000Z-aaaa", UNIT, seq, "task.tests_rechecked", data)


def test_scn_ver_322_the_flaky_test_of_a_task_step_is_listed():
    assert _step_flakes([rechecked(1)]) == [f"{FLAKY} (task 1.2 green attempt 1)"]


def test_a_fix_units_event_names_its_fix_unit_and_a_chore_its_phase():
    events = [rechecked(1, fix_unit="fix-1", phase="single", attempt=2, task="1.1")]
    assert _step_flakes(events) == [f"{FLAKY} (task 1.1 single attempt 2, fix unit fix-1)"]


def test_every_flaky_id_of_every_passed_event_is_listed_in_order():
    events = [rechecked(1, flaky=("a::x", "a::y")), rechecked(2, flaky=("b::z",), phase="red", task="1.1")]
    assert _step_flakes(events) == [
        "a::x (task 1.2 green attempt 1)",
        "a::y (task 1.2 green attempt 1)",
        "b::z (task 1.1 red attempt 1)",
    ]


def test_the_listing_is_cut_at_twenty_lines_and_counts_the_rest():
    events = [rechecked(n, flaky=(f"t.m::t{n:02}",)) for n in range(MAX_STEP_FLAKES + 5)]
    lines = _step_flakes(events)
    assert MAX_STEP_FLAKES == 20 and len(lines) == 21 and lines[-1] == "(+5 more)"
    assert lines[0].startswith("t.m::t00 ")


@pytest.mark.parametrize("stopped", ["failed", "unusable", "tree", "budget"])
def test_scn_ver_323_nothing_is_listed_without_a_passed_re_run(stopped):
    flaky = (FLAKY,) if stopped == "failed" else ()
    assert _step_flakes([rechecked(1, stopped=stopped, flaky=flaky)]) == []
    assert _step_flakes([]) == []  # a 0.4.59 ledger has no such event


def test_an_event_without_a_list_or_with_other_values_lists_nothing_and_does_not_fail():
    bad = LedgerEvent(STAMP, "r", UNIT, 1, "task.tests_rechecked", {"stopped": "passed", "flaky": "nope"})
    assert _step_flakes([bad, rechecked(2, flaky=(1, FLAKY))]) == [f"{FLAKY} (task 1.2 green attempt 1)"]


def test_the_section_follows_the_guard_events_and_is_no_finding():
    lines = [f"{FLAKY} (task 1.2 green attempt 1)"]
    guards = ["guard.test_tamper: tests/x.py"]
    text = render_verification_md(result(step_flakes=lines, guards=guards))
    before = render_verification_md(result(guards=guards))
    assert HEADING in text and f"- {lines[0]}" in text and HEADING not in before
    assert text.startswith(before.rstrip("\n"))  # the report is what it was, with the section after the guard events
    assert text.index("## Guard events") < text.index(HEADING)


def test_the_verdict_stores_the_lines_and_the_findings_and_verdict_are_unchanged():
    lines = [f"{FLAKY} (task 1.2 green attempt 1)"]
    with_lines, without = verdict_json(result(step_flakes=lines)), verdict_json(result())
    assert with_lines["step_flakes"] == lines and without["step_flakes"] == []
    for key in ("verdict", "findings", "gates", "tests", "criteria"):
        assert with_lines[key] == without[key]


def test_a_reused_round_keeps_the_lines_and_an_old_verdict_has_none():
    lines = [f"{FLAKY} (task 1.2 green attempt 1)"]
    stored = json.loads(json.dumps(verdict_json(VerifyResult(UNIT, 1, Verdict.PASS, BASE, HEAD, step_flakes=lines))))
    assert restore_round(stored, UNIT, 2).step_flakes == lines
    del stored["step_flakes"]
    assert restore_round(stored, UNIT, 2).step_flakes == []


# end to end: a green step whose gate fails a base test once, a verified unit

PRE = (
    "tests.test_pricing::test_total_adds_prices"  # a base test of the fixture unit, in a file the unit does not change
)
UNIT_DIR = "openspec/changes/add-discount-codes"


def test_scn_ver_322_a_verified_unit_lists_the_test_that_passed_on_its_green_steps_re_run(
    run_l4, valid_spec, monkeypatch
):
    from dataclasses import replace

    from l4.gates.junit import TestCase
    from l4.implementer.workbench import Workbench

    from ..implementer.conftest import green_step, red_step
    from .test_ladder import judge_step

    real, seen = Workbench.run_gate, []

    def flaky_once(self, name, command, **kw):
        out = real(self, name, command, **kw)
        seen.append(name)
        if name == "test" and seen.count("test") == 2 and out.report is not None:  # red's run was the first
            tests = {**out.report.tests, PRE: TestCase(PRE, "failed", "boom")}
            return replace(out, report=replace(out.report, tests=tests))
        return out

    monkeypatch.setattr(Workbench, "run_gate", flaky_once)
    run = run_l4([red_step(), green_step(), judge_step()])
    assert "test-recheck" in seen
    text = run.pushed(f"{UNIT_DIR}/verification.md")
    assert HEADING in text and f"- {PRE} (task 1.1 green attempt 1)" in text
    verdict = json.loads(run.pushed(f"{UNIT_DIR}/.l4/evidence/round-1/verdict.json"))
    assert verdict["step_flakes"] == [f"{PRE} (task 1.1 green attempt 1)"]
    assert verdict["verdict"] == "PASS" and "flaky" not in json.dumps(verdict["findings"])
