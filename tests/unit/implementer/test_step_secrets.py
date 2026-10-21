"""L4-SEC-008: an implementer step's changes are read for secrets before any gate or commit, so a test fixture that
spells a token whole fails the attempt with advice instead of halting the unit at the push."""

from l4.agents.fake import Step
from l4.implementer.loop import run_task
from l4.implementer.tdd import run_red
from l4.specs.base import Task

from .conftest import STUB, TESTS, Bench, green_step, red_step, result

TASK = Task("1.1", "1.1", "1.1 Add `apply_discount`", False, " ", 0, 1, 3)
TOKEN = "mk_" + "agent_" + "Q7w8E9r0T1y2U3i4O5p6"  # built from parts: this file holds no token shape


def fixture_step() -> Step:
    leaky = TESTS + f'\n\nSECRET = "{TOKEN}"\n'
    return Step(
        writes={"tests/test_discount.py": leaky, "src/pytdd/pricing.py": STUB},
        structured=result("red", criteria_ids=["C-2d3a8daf", "C-d80f494d"]),
    )


def test_a_fixture_that_spells_a_token_fails_the_attempt_before_any_gate(make_bench):
    """SCN-SEC-20."""
    bench: Bench = make_bench([fixture_step()])
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "failed"
    assert outcome.reason.startswith("the change holds text shaped like a secret: tests/test_discount.py (mintkey).")
    assert '"mk_" + "agent_" + "A" * 24' in outcome.reason and TOKEN not in outcome.reason
    assert bench.events("guard.secret") == [
        {**bench.events("guard.secret")[0], "path": "tests/test_discount.py", "kind": "mintkey", "task": "1.1",
         "phase": "red", "attempt": 1}
    ]  # fmt: skip
    assert not bench.events("breaker.tripped") and not bench.events("gate.started")
    assert bench.wb.changed_files() == [bench.wb.ledger_rel]  # the attempt's work is gone
    assert TOKEN not in "".join(p.read_text() for p in (bench.wb.ref.path / ".l4" / "ledger").glob("*.jsonl"))


def test_the_next_attempt_gets_the_advice_and_a_value_built_from_parts_goes_on(make_bench):
    """SCN-SEC-21: the retry prompt carries the reason; a value built from parts at run time passes the check."""
    built = TESTS + '\n\nSECRET = "mk_" + "agent_" + "A" * 24\n'
    clean = red_step()
    clean.writes["tests/test_discount.py"] = built
    bench: Bench = make_bench([fixture_step(), clean, green_step()])
    assert run_task(bench.wb, TASK).status == "done"
    second = bench.adapter.requests[1].prompt
    assert "the change holds text shaped like a secret" in second and "Your previous attempt was rejected" in second
    assert len(bench.events("guard.secret")) == 1
    assert bench.events("task.red_ok")  # the second attempt passed the step check and its red was accepted
