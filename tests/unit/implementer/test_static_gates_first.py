"""L4-IMP-096 (SCN-IMP-521..525): the static gates of a red or green step run before its variant runs (the zero-value
run, the base run, run (b), the test-at-red run), before a held check is raised and before an accept is applied."""

from l4.agents.fake import Step
from l4.implementer import tdd
from l4.implementer.base_run import BaseRunResult
from l4.implementer.discrimination import AtRed, PreSatisfied
from l4.implementer.loop import run_task
from l4.implementer.tdd import run_green, run_red
from l4.specs.base import Task

from .conftest import HEADER, IMPL, KNOWN, KNOWN_TEST, STUB, TESTS, UNKNOWN, Bench, red_step, result
from .test_already_satisfied_no_test import no_test
from .test_earlier_red import NEW as EARLIER_NEW
from .test_earlier_red import TASK as HELD_TASK
from .test_earlier_red import commit_old, record
from .test_held_accept import answer, answer_q, forge_hold, new_step, raise_held, renamed_step
from .test_held_check import held_bench, zero_says
from .test_replay_green_freeze import WEAK_EXTRA, forge_at_red
from .test_tdd_green import CORRECTED, answer_naming, two_test_red
from .test_tdd_static import FAILS_ON_IMPL, LINT_TEST_FILE

TASK = Task("1.1", "1.1", "1.1 Add `apply_discount`", False, " ", 0, 3, 3)
TYPECHECK_BAD = "sh -c 'if grep -q TYPEBAD tests/test_discount.py; then echo TS2698 type error; exit 1; fi'"
LINT_NEW_FILE = "sh -c 'if grep -q LINTBAD tests/test_new.py 2>/dev/null; then echo E999 bad test file; exit 1; fi'"
PASSING = f'@pytest.mark.l4("{UNKNOWN}")\ndef test_total_adds():\n    assert total([2.0, 2.0]) == 4.0\n'
BROKEN_TOTAL = f'@pytest.mark.l4("{KNOWN}")\ndef test_total_is_wrong():\n    assert total([1.0]) == 99.0\n'
TOTAL_HEADER = "import pytest\n\nfrom pytdd.pricing import total\n\n\n"
LINT_WRITES_SRC = (
    "sh -c 'if grep -q LINTBAD tests/test_discount.py; then echo x > src/pytdd/lint_wrote.py; echo E501 lint text; "
    "exit 1; fi'"
)
LINT_STAMPS_ON_REPLAY = (  # only while a saved at_red step is replayed: its patch is in the unit's `.l4/held` folder
    "sh -c 'for f in openspec/changes/*/.l4/held/*-at_red.patch; do "
    '[ -e "$f" ] && echo stamped > src/pytdd/lint_stamp.txt; done; exit 0\''
)


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
    assert outcome.held is None  # no hold, so no question is raised over a step that cannot be kept
    assert bench.wb.is_clean() and not (bench.wb.ref.path / ".l4" / "held").exists()  # nothing captured for a replay


def test_scn_imp_522_a_replayed_step_with_a_lint_error_records_no_accept_and_makes_no_base_run(
    make_bench, monkeypatch, raw
):
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
        lambda wb, cands, ids, *, real=None: BaseRunResult(
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
    assert green.held is None and bench.events("check.accepted") == []
    assert bench.events("task.done") == [] and bench.wb.head() == answered


def test_a_green_step_whose_test_gate_fails_runs_no_static_gate(make_bench):
    lazy = Step(structured=result("green"))
    bench = make_bench([red_step(), lazy], lint=["true"])
    red = run_red(bench.wb, TASK, attempt=1)
    before = len(finished(bench, "lint"))
    green = run_green(bench.wb, TASK, red, attempt=1)
    assert green.status == "failed" and green.reason.startswith("red tests still failing")
    assert len(finished(bench, "lint")) == before


def test_a_replayed_green_step_is_put_back_to_its_patch_after_the_static_gates(make_bench, raw, monkeypatch):
    """The replay guard restores right after the static gates, before the test-at-red run (as red does)."""
    fix = Step(writes={"tests/test_discount.py": CORRECTED, "src/pytdd/pricing.py": IMPL}, structured=result("green"))
    bench = make_bench([two_test_red(), fix, fix], lint=[LINT_STAMPS_ON_REPLAY])
    red = run_red(bench.wb, TASK, attempt=1)
    assert red.status == "ok", red.reason
    answer_naming(bench, raw, "Change `tests/test_discount.py`.")
    reason = "the test-at-red run ran no test (exit 2, 0 collection errors)"
    monkeypatch.setattr(tdd, "fails_at_red", lambda *a, **k: AtRed([], reason))
    first = run_green(bench.wb, TASK, red, attempt=1)
    assert first.status == "held" and first.held is not None
    qid = raise_held(bench, first.held)
    forge_at_red(bench, raw, {
        "tests/test_discount.py": CORRECTED, "src/pytdd/pricing.py": IMPL, "tests/test_extra.py": WEAK_EXTRA,
    })  # fmt: skip
    answer_q(bench, raw, qid, "accept: the run cannot be made here")
    second = run_green(bench.wb, TASK, red, attempt=2)
    assert second.status == "ok", second.reason
    restored = [e for e in bench.events("held.replay_restored") if "src/pytdd/lint_stamp.txt" in e["paths"]]
    wheres = [e["where"] for e in restored]  # the baseline's lint run also stamped, before the step: "test run"
    assert "static gates" in wheres and "test-at-red run" not in wheres  # not left for the test-at-red run to find
    assert bench.wb.git.run("cat-file", "-e", "HEAD:src/pytdd/lint_stamp.txt", check=False).returncode != 0


def test_a_tamper_found_while_the_static_gates_ran_wins_over_their_failure(make_bench):
    step = Step(
        writes={"tests/test_discount.py": TESTS + "\n# LINTBAD\n", "src/pytdd/pricing.py": STUB},
        structured=red_step().structured,
    )
    bench: Bench = make_bench([step], lint=[LINT_WRITES_SRC])
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "failed" and "test code changed production files" in outcome.reason, outcome.reason
    assert "E501 lint text" not in outcome.reason and bench.wb.is_clean()


def test_a_step_with_passing_tests_but_no_candidates_is_told_its_red_check_first(make_bench, monkeypatch):
    """An earlier red confirms every passing new test, so no variant run is made: the verdict comes before the gates."""
    zero = Calls(monkeypatch, "confirm_pre_satisfied")
    step = Step(
        writes={
            "tests/test_new.py": EARLIER_NEW + "\n# LINTBAD\n",
            "tests/test_pricing.py": "def test_total_adds_prices():\n    assert False\n",
        },
        structured=result("red", criteria_ids=[KNOWN]),
    )
    bench: Bench = make_bench([step], lint=[LINT_NEW_FILE])
    base, sha = commit_old(bench)
    record(bench, base, sha)
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "failed" and outcome.reason.startswith("red broke existing tests: "), outcome.reason
    assert all(not c[1] for c in zero.calls)  # nothing was handed to the zero-value run
    assert finished(bench, "lint") == []


def test_the_no_new_test_path_makes_no_static_gate_run(make_bench):
    bench: Bench = make_bench([no_test()], lint=["true"])
    base, sha = commit_old(bench)
    record(bench, base, sha)
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "already_satisfied", outcome.reason
    assert finished(bench, "lint") == []
