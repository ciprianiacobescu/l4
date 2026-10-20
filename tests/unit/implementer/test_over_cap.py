"""A test that traces more than `verifier.max_criteria_per_test` of the unit's criteria fails the step that writes it
(L4-VER-052, SCN-VER-171 to SCN-VER-174, SCN-VER-189)."""

import pytest

from l4.agents.fake import Step
from l4.gates.junit import TestCase
from l4.implementer.result import over_cap_text
from l4.implementer.tdd import run_red
from l4.specs.base import Task

from .conftest import HEADER, KNOWN, STUB, UNKNOWN, red_step, result

TASK = Task("1.1", "1.1", "1.1 Add `apply_discount`", False, " ", 0, 1, 3)
UNIT = ["C-00000001", "C-00000002", "C-00000003", "C-00000004", "C-00000005", "C-00000006"]
TEXT = (
    "too many criteria on one test: {test} traces {n} of this unit's criteria ({ids}), more than "
    "verifier.max_criteria_per_test ({cap}), so the verifier counts it for none of them: split it into tests that "
    "each assert one behaviour and carry at most {cap} ids, and tag a test only with the criteria whose outcome it "
    "asserts"
)


def case(name: str, *marks: str) -> TestCase:
    return TestCase(name, "failed", criteria=marks)  # type: ignore[arg-type]


def test_over_cap_text():
    new = {"t::flow": case("t::flow", *UNIT[:5]), "t::one": case("t::one", UNIT[0])}
    ids = ", ".join(UNIT[:5])
    assert over_cap_text(new, UNIT, 3) == TEXT.format(test="t::flow", n=5, ids=ids, cap=3)
    four = {f"t::w{n}": case(f"t::w{n}", *UNIT[:4]) for n in range(4)}
    got = over_cap_text(four, UNIT, 3)
    assert got.count("too many criteria on one test:") == 3 and got.endswith("(+1 more)") and "; " in got
    assert "t::w3" not in got  # sorted: the first three are named
    foreign = {"t::a": case("t::a", *UNIT[:3], "C-99999999", "C-88888888")}  # ids that are not the unit's do not count
    assert over_cap_text(foreign, UNIT, 3) == ""
    assert over_cap_text({"t::b": case("t::b", *UNIT[:3])}, UNIT, 3) == ""  # exactly the cap
    assert over_cap_text({"t::b": case("t::b", *UNIT[:3])}, UNIT, 2).endswith("asserts")


BOTH = (
    HEADER
    + f'@pytest.mark.l4("{KNOWN}", "{UNKNOWN}")\ndef test_flow():\n'
    + '    assert apply_discount(50.0, "SAVE10") == 45.0\n\n\n'
    + f'@pytest.mark.l4("{KNOWN}")\ndef test_single():\n    assert apply_discount(50.0, "SAVE10") == 45.0\n'
)


def both_step(tests: str = BOTH) -> Step:
    return Step(
        writes={"tests/test_discount.py": tests, "src/pytdd/pricing.py": STUB},
        structured=result("red", tests_added=["tests/test_discount.py::test_flow"], criteria_ids=[KNOWN, UNKNOWN]),
    )


def gate_names(bench) -> set[str]:
    return {e["name"] for e in bench.events("gate.finished")}


def test_a_red_step_with_a_test_over_the_cap_fails_before_any_variant_run(make_bench):
    bench = make_bench([both_step(), red_step()], verifier={"max_criteria_per_test": 1})
    out = run_red(bench.wb, TASK, attempt=1)
    ids = ", ".join(sorted([KNOWN, UNKNOWN]))
    assert out.status == "failed"
    assert out.reason == TEXT.format(test="tests.test_discount::test_flow", n=2, ids=ids, cap=1)
    assert bench.wb.is_clean()
    assert gate_names(bench) <= {"setup", "baseline", "test"}  # no zero-value, base or pre-satisfied run
    assert bench.events("task.red_ok") == []
    again = run_red(bench.wb, TASK, attempt=2, previous_failure=out.reason)
    assert again.status == "ok", again.reason
    assert out.reason in bench.adapter.requests[1].prompt  # the next attempt's prompt carries the text


def test_a_test_at_the_cap_passes_and_other_ids_do_not_count(make_bench):
    foreign = BOTH.replace(f'("{KNOWN}", "{UNKNOWN}")', f'("{KNOWN}", "{UNKNOWN}", "C-99999999", "C-88888888")')
    bench = make_bench([both_step(foreign)], verifier={"max_criteria_per_test": 2})
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "ok", out.reason  # two of the unit's criteria, at the cap; the foreign ids do not count


def test_tests_written_before_the_step_are_not_checked(make_bench):
    bench = make_bench([red_step()], verifier={"max_criteria_per_test": 1})
    old = f'import pytest\n\n\n@pytest.mark.l4("{KNOWN}", "{UNKNOWN}")\n'
    (bench.wb.worktree / "tests").mkdir(exist_ok=True)
    (bench.wb.worktree / "tests" / "test_old.py").write_text(old + "def test_old():\n    assert True\n")
    bench.wb.git.run("add", "tests/test_old.py")
    bench.wb.git.run("commit", "-q", "-m", "an earlier test over the cap")
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "ok", out.reason


@pytest.mark.parametrize(("cap", "traced", "ok"), [(4, 2, True), (1, 2, False)])
def test_one_configured_cap(make_bench, cap, traced, ok):
    bench = make_bench([both_step()], verifier={"max_criteria_per_test": cap})
    out = run_red(bench.wb, TASK, attempt=1)
    assert (out.status == "ok") is ok
    assert ("at most 4 ids" in bench.adapter.requests[0].prompt) is (cap == 4)
