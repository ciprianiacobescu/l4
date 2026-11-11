"""L4-IMP-096 (SCN-IMP-521..525): the static gates of a red or green step run before its variant runs (the zero-value
run, the base run, run (b), the test-at-red run), before a held check is raised and before an accept is applied."""

from l4.agents.fake import Step
from l4.implementer import tdd
from l4.implementer.base_run import BaseRunResult
from l4.implementer.discrimination import PreSatisfied
from l4.implementer.loop import run_task
from l4.implementer.tdd import run_green, run_red
from l4.specs.base import Task

from .conftest import HEADER, IMPL, KNOWN, KNOWN_TEST, STUB, TESTS, UNKNOWN, Bench, red_step, result
from .test_earlier_red import TASK as HELD_TASK
from .test_held_accept import answer, forge_hold, new_step, renamed_step
from .test_held_check import held_bench, zero_says
from .test_tdd_green import CORRECTED, answer_naming, two_test_red
from .test_tdd_static import FAILS_ON_IMPL, LINT_TEST_FILE

TASK = Task("1.1", "1.1", "1.1 Add `apply_discount`", False, " ", 0, 3, 3)
TYPECHECK_BAD = "sh -c 'if grep -q TYPEBAD tests/test_discount.py; then echo TS2698 type error; exit 1; fi'"
LINT_NEW_FILE = "sh -c 'if grep -q LINTBAD tests/test_new.py 2>/dev/null; then echo E999 bad test file; exit 1; fi'"
PASSING = f'@pytest.mark.l4("{UNKNOWN}")\ndef test_total_adds():\n    assert total([2.0, 2.0]) == 4.0\n'
BROKEN_TOTAL = f'@pytest.mark.l4("{KNOWN}")\ndef test_total_is_wrong():\n    assert total([1.0]) == 99.0\n'
TOTAL_HEADER = "import pytest\n\nfrom pytdd.pricing import total\n\n\n"


def finished(bench: Bench, name: str) -> list[dict]:
    return [e for e in bench.events("gate.finished") if e["name"] == name]


class Calls:
    """Records the calls of the check at `tdd.<name>` and passes them on to what is there now."""

    def __init__(self, monkeypatch, name: str) -> None:
        self.calls: list[tuple] = []
        real = getattr(tdd, name)

        def spy(*args, **kw):
            self.calls.append(args)
            return real(*args, **kw)

        monkeypatch.setattr(tdd, name, spy)


def inconclusive_zero(monkeypatch) -> None:
    """The zero-value run cannot decide the passing tests, so they go to the base run (as in a TypeScript project)."""

    def fake(wb, candidates, *, real=None):
        return PreSatisfied(inconclusive={c: "the zero-value run varies Python files only" for c in candidates})

    monkeypatch.setattr(tdd, "confirm_pre_satisfied", fake)


def test_scn_imp_521_a_red_step_with_a_type_error_fails_before_the_base_run(make_bench, monkeypatch):
    inconclusive_zero(monkeypatch)
    zero, base_run = Calls(monkeypatch, "confirm_pre_satisfied"), Calls(monkeypatch, "confirmed_by_base_run")
    passing = TOTAL_HEADER + PASSING.replace(UNKNOWN, KNOWN) + "\n\n# TYPEBAD\n"
    bench: Bench = make_bench(
        [Step(writes={"tests/test_discount.py": passing}, structured=result("red", criteria_ids=[KNOWN]))],
        typecheck=[TYPECHECK_BAD],
    )
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "failed" and "typecheck gate" in outcome.reason and "TS2698" in outcome.reason
    assert zero.calls == [] and base_run.calls == []
    assert finished(bench, "test-base-run") == [] and finished(bench, "test-presatisfied") == []
    assert bench.events("question.raised") == [] and bench.events("check.inconclusive") == []
    assert bench.wb.is_clean() and not (bench.wb.ref.path / ".l4" / "held").exists()  # nothing captured for a replay


def test_scn_imp_522_a_replayed_step_with_a_lint_error_spends_no_accept(make_bench, monkeypatch, raw):
    zero_says(monkeypatch)
    bench = held_bench(make_bench, [new_step(), renamed_step()], lint=[LINT_NEW_FILE])
    first = run_task(bench.wb, HELD_TASK)  # the step is held: a passing test the zero-value run cannot decide
    assert (first.status, first.question_ids) == ("blocked", ["Q-001"]), first.reason
    forge_hold(bench, raw, {"tests/test_new.py": new_step().writes["tests/test_new.py"] + "\n# LINTBAD\n"})
    answer(bench, raw, "accept: the version pin cannot be shown to discriminate")
    zero, base_run = Calls(monkeypatch, "confirm_pre_satisfied"), Calls(monkeypatch, "confirmed_by_base_run")
    outcome = run_red(bench.wb, HELD_TASK, attempt=1)
    assert outcome.status == "failed" and "lint gate" in outcome.reason and "E999 bad test file" in outcome.reason
    assert [e["check"] for e in bench.events("held.replayed")] == ["pre_satisfied"]  # the saved step was replayed
    assert zero.calls == [] and base_run.calls == []
    assert bench.events("check.accepted") == []
    assert [e for e in bench.events("criterion.pre_satisfied") if e["task"] == "1.1"] == []


def test_scn_imp_523_a_red_step_with_a_lint_error_fails_before_run_b(make_bench, monkeypatch):
    run_b = Calls(monkeypatch, "vacuity_check")
    linted = Step(
        writes={"tests/test_discount.py": TESTS + "\n# LINTBAD\n", "src/pytdd/pricing.py": STUB},
        structured=red_step().structured,
    )
    bench: Bench = make_bench([linted], lint=[LINT_TEST_FILE])
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "failed" and "lint gate" in outcome.reason and "E999 bad test file" in outcome.reason
    assert run_b.calls == [] and finished(bench, "test-zero") == []
    assert len(finished(bench, "lint")) == 1


def test_scn_imp_524_a_step_without_a_variant_run_is_told_its_red_verdict_before_the_static_gates(make_bench):
    wrong = Step(
        writes={"tests/test_discount.py": TOTAL_HEADER + BROKEN_TOTAL + "\n# LINTBAD\n"},
        structured=result("red", criteria_ids=[KNOWN]),
    )
    bench: Bench = make_bench([wrong], lint=[LINT_TEST_FILE])
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "failed" and "lint gate" in outcome.reason  # it passes its verdict, so the gates speak
    assert finished(bench, "test-zero") == [] and len(finished(bench, "lint")) == 1
    wreck = Step(
        writes={
            "tests/test_discount.py": TOTAL_HEADER + BROKEN_TOTAL + "\n# LINTBAD\n",
            "tests/test_pricing.py": "def test_total_adds_prices():\n    assert False\n",
        },
        structured=result("red", criteria_ids=[KNOWN]),
    )
    second: Bench = make_bench([wreck], lint=[LINT_TEST_FILE])
    broke = run_red(second.wb, TASK, attempt=1)
    assert broke.status == "failed" and broke.reason.startswith("red broke existing tests: ")  # the verdict first
    assert finished(second, "lint") == []


def test_scn_imp_524_the_static_gates_of_a_confirmed_step_run_once(make_bench, monkeypatch):
    inconclusive_zero(monkeypatch)
    monkeypatch.setattr(
        tdd,
        "confirmed_by_base_run",
        lambda wb, cands, ids, *, real=None, **_: BaseRunResult(
            confirmed={c: tuple(t) for c, t in cands.items()}, base_sha="b" * 40
        ),
    )
    mixed = HEADER + KNOWN_TEST + "\n\n" + PASSING
    mixed = mixed.replace("from pytdd.pricing import apply_discount", "from pytdd.pricing import apply_discount, total")
    step = Step(
        writes={"tests/test_discount.py": mixed, "src/pytdd/pricing.py": STUB},
        structured=result("red", criteria_ids=[KNOWN, UNKNOWN]),
    )
    bench: Bench = make_bench([step], lint=["true"], typecheck=["true"])
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "ok", outcome.reason
    assert len(finished(bench, "lint")) == 1 and len(finished(bench, "typecheck")) == 1


def test_scn_imp_525_a_green_step_with_a_type_error_makes_no_test_at_red_run(make_bench, raw, monkeypatch):
    fix = Step(writes={"tests/test_discount.py": CORRECTED, "src/pytdd/pricing.py": IMPL}, structured=result("green"))
    bench = make_bench([two_test_red(), fix], typecheck=[FAILS_ON_IMPL])
    red = run_red(bench.wb, TASK, attempt=1)
    assert red.status == "ok", red.reason
    answer_naming(bench, raw, "Change `tests/test_discount.py`.")
    at_red, answered = Calls(monkeypatch, "fails_at_red"), bench.wb.head()
    green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.status == "failed" and "typecheck gate" in green.reason and "F401 in impl" in green.reason
    assert at_red.calls == [] and finished(bench, "test-at-red") == []
    assert bench.events("check.inconclusive") == [] and bench.events("check.accepted") == []
    assert bench.events("task.done") == [] and bench.wb.head() == answered


def test_a_green_step_whose_test_gate_fails_runs_no_static_gate(make_bench):
    lazy = Step(structured=result("green"))
    bench = make_bench([red_step(), lazy], lint=["true"])
    red = run_red(bench.wb, TASK, attempt=1)
    before = len(finished(bench, "lint"))
    green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.status == "failed" and green.reason.startswith("red tests still failing")
    assert len(finished(bench, "lint")) == before
