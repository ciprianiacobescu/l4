"""M1.13 lines 11-12 (W-C1, SPEC L4-VER-006, L4-VER-009): a tests chore that cites a criterion needs a test that looks
at the answer (fails by assertion on the zero values), as the verifier would find out a round later; a coverage chore
does not."""

from l4.agents.fake import Step
from l4.implementer.tdd import run_green, run_red, run_single
from l4.specs.base import Task

from .conftest import KNOWN, UNKNOWN, green_step, red_step, result
from .test_single_phase import NEW_TESTS, UNIT_TASK

BOUND = Task("1.2", "1.2", f"1.2 New tests bypass the server (F-0a1b2c3d; {KNOWN})", False, " ", 0, 3, 3)
FINDINGS = ["F-0a1b2c3d"]
PASSES_ON_ZERO = "from pytdd.pricing import total\n\n\ndef test_total_of_nothing_is_zero():\n    assert not total([])\n"


def run_bound(make_bench, step: Step, *, task: Task = BOUND, **config):
    bench = make_bench([red_step(), green_step(), step], **config)
    tasks = bench.wb.ref.path / "tasks.md"
    tasks.write_text(tasks.read_text().rstrip("\n") + f"\n- [ ] {task.title}\n")
    bench.wb.git.run("add", "-A")
    bench.wb.git.run("commit", "-q", "-m", "a second task")
    red = run_red(bench.wb, UNIT_TASK, attempt=1)
    assert red.status == "ok", red.reason
    assert run_green(bench.wb, UNIT_TASK, red, attempt=1).status == "ok"
    return bench, run_single(bench.wb, task, FINDINGS, attempt=1, kind="tests")


def test_a_test_that_fails_on_the_zero_values_is_accepted_and_recorded_as_discriminating(make_bench):
    bench, done = run_bound(make_bench, Step(writes={"tests/test_more.py": NEW_TESTS}, structured=result("single")))
    assert done.status == "ok", done.reason
    [added] = bench.events("task.tests_added")
    assert added["tests"] == ["tests.test_more::test_total_of_two"]
    assert added["discriminating"] == ["tests.test_more::test_total_of_two"]


def test_tests_that_pass_on_the_zero_values_and_the_base_fail_the_attempt_naming_them(make_bench):
    bench, done = run_bound(
        make_bench, Step(writes={"tests/test_more.py": PASSES_ON_ZERO}, structured=result("single"))
    )
    assert done.status == "failed"
    assert "tests.test_more::test_total_of_nothing_is_zero" in done.reason
    assert "zero" in done.reason and "assertion" in done.reason
    assert bench.events("task.tests_added") == [] and bench.wb.is_clean()
    assert [e["task"] for e in bench.events("task.done")] == ["1.1"]


def test_one_discriminating_test_is_enough_when_others_only_run_the_code(make_bench):
    both = NEW_TESTS + "\n\n" + PASSES_ON_ZERO.split("\n\n\n", 1)[1]
    bench, done = run_bound(make_bench, Step(writes={"tests/test_more.py": both}, structured=result("single")))
    assert done.status == "ok", done.reason
    [added] = bench.events("task.tests_added")
    assert added["discriminating"] == ["tests.test_more::test_total_of_two"] and len(added["tests"]) == 2


def test_a_coverage_chore_without_a_criterion_is_not_discriminated_early(make_bench):
    task = Task("1.2", "1.2", "1.2 Changed code that no test runs (H-0a1b2c3d)", False, " ", 0, 3, 3)
    bench, done = run_bound(
        make_bench, Step(writes={"tests/test_more.py": PASSES_ON_ZERO}, structured=result("single")), task=task
    )
    assert done.status == "ok", done.reason
    [added] = bench.events("task.tests_added")
    assert "discriminating" not in added


def test_single_tests_tells_the_agent_to_tag_with_the_cited_criterion_and_to_use_the_interface_the_design_names():
    from l4.implementer.prompt import load_template, render_prompt

    from .test_prompt import ctx

    template = load_template("single_tests")
    assert template.version == 5
    assert "cites a criterion" in template.body and "fail by assertion" in template.body
    assert "interface the design names" in template.body and "new names" in template.body
    assert render_prompt("single", ctx(adds_tests=True)).template_version == "contract@13+single_tests@5"


def test_a_chore_whose_tests_the_runs_could_not_decide_is_held_and_no_attempt_is_used(make_bench, monkeypatch):
    """Review m2: the discrimination check of a test chore that cannot decide holds the task (L4-IMP-063)."""
    from l4.implementer import tdd
    from l4.implementer.discrimination import ExtraRun

    monkeypatch.setattr(
        tdd,
        "discriminate_extra",
        lambda wb, tests, base, **kw: ExtraRun(inconclusive=dict.fromkeys(tests, "did not run in test-extra-zero")),
    )
    bench, done = run_bound(make_bench, Step(writes={"tests/test_more.py": NEW_TESTS}, structured=result("single")))
    assert done.status == "held" and done.held is not None and done.held.check == "tests"
    assert bench.events("task.tests_added") == [] and bench.wb.is_clean()
    assert [e["task"] for e in bench.events("task.done")] == ["1.1"]


def test_a_chore_whose_tests_no_run_can_vary_is_held_with_no_runs(make_bench, monkeypatch):
    """SCN-VER-242: the real check, with no Python module the tests import and no Python production file the unit
    changed (a TypeScript project): no gate runs, the task is held with a harness question that says why and names no
    run, and no attempt is used."""
    from l4.implementer import discrimination

    monkeypatch.setattr(discrimination, "imported_modules", lambda wb, tests: set())
    monkeypatch.setattr(discrimination, "_changed_modules", lambda wb: set())
    monkeypatch.setattr(discrimination, "production_changes", lambda wb, base: [])
    bench, done = run_bound(make_bench, Step(writes={"tests/test_more.py": NEW_TESTS}, structured=result("single")))
    assert done.status == "held" and done.held is not None and done.held.check == "tests"
    assert done.held.reason == discrimination.NO_RUN and done.held.runs == ()
    assert done.held.tests == ("tests.test_more::test_total_of_two",)
    assert not any(e["name"].startswith("test-extra") for e in bench.events("gate.finished"))
    assert bench.events("task.tests_added") == [] and bench.wb.is_clean()
    assert [e["task"] for e in bench.events("task.done")] == ["1.1"]


def test_a_chore_test_over_the_cap_fails_the_chore(make_bench):
    """L4-VER-052, SCN-VER-173: an added test that traces more criteria than the cap fails the attempt before any
    discrimination run, and records nothing."""
    wide = (
        "import pytest\n\nfrom pytdd.pricing import total\n\n\n"
        f'@pytest.mark.l4("{KNOWN}", "{UNKNOWN}")\ndef test_total_of_two():\n    assert total([1.0, 2.0]) == 3.0\n'
    )
    step = Step(writes={"tests/test_more.py": wide}, structured=result("single"))
    bench, done = run_bound(make_bench, step, verifier={"max_criteria_per_test": 1})
    assert done.status == "failed"
    assert done.reason.startswith("too many criteria on one test: tests.test_more::test_total_of_two traces 2 of")
    assert bench.events("task.tests_added") == [] and bench.wb.is_clean()
    assert not any(e["name"].startswith("test-extra") for e in bench.events("gate.finished"))  # none


def test_a_chore_test_at_the_cap_is_accepted(make_bench):
    two = (
        "import pytest\n\nfrom pytdd.pricing import total\n\n\n"
        f'@pytest.mark.l4("{KNOWN}", "{UNKNOWN}")\ndef test_total_of_two():\n    assert total([1.0, 2.0]) == 3.0\n'
    )
    step = Step(writes={"tests/test_more.py": two}, structured=result("single"))
    _, done = run_bound(make_bench, step, verifier={"max_criteria_per_test": 2})
    assert done.status == "ok", done.reason


# --- a test the runs cannot reach (test-file-reach 2.1, 2.2; SCN-VER-243, SCN-VER-245) ------------------------------

TS_FILE = "src/pricing/total.test.ts"
TWO_TESTS = PASSES_ON_ZERO + "\n\ndef test_reported_from_typescript():\n    assert not total([])\n"


def as_typescript(monkeypatch, *, only: str = "") -> None:
    """The file finder says that the test ids holding `only` (all, when empty) are in a TypeScript file."""
    from l4.implementer import discrimination

    monkeypatch.setattr(
        discrimination,
        "file_of_id",
        lambda test_id, paths, preferred=(): TS_FILE if only in test_id else "tests/test_more.py",
    )


def test_scn_ver_243_a_chore_whose_only_test_is_in_another_language_is_held_with_the_runs_made(make_bench, monkeypatch):
    """A unit that changed a Python production file: both runs are made (real gates), the test passes both, and its
    file is not Python: the task is held, the question names both runs, and no attempt is used."""
    from l4.implementer import discrimination

    as_typescript(monkeypatch)
    bench, done = run_bound(
        make_bench, Step(writes={"tests/test_more.py": PASSES_ON_ZERO}, structured=result("single"))
    )
    assert done.status == "held" and done.held is not None and done.held.check == "tests"
    assert done.held.reason == discrimination.NOT_PYTHON.format(file=TS_FILE)
    assert done.held.runs == ("test-extra-zero", "test-extra-base")
    ran = {e["name"] for e in bench.events("gate.finished")}
    assert {"test-extra-zero", "test-extra-base"} <= ran
    assert bench.events("task.tests_added") == [] and bench.wb.is_clean()
    assert [e["task"] for e in bench.events("task.done")] == ["1.1"]


def test_a_hold_after_the_zero_value_run_only_names_that_run(make_bench, monkeypatch):
    """The base run needs a changed Python production file; with none, only the zero-value run is made and named."""
    from l4.implementer import discrimination

    as_typescript(monkeypatch)
    monkeypatch.setattr(discrimination, "production_changes", lambda wb, base: [])
    bench, done = run_bound(
        make_bench, Step(writes={"tests/test_more.py": PASSES_ON_ZERO}, structured=result("single"))
    )
    assert done.status == "held" and done.held is not None
    assert done.held.runs == ("test-extra-zero",)
    ran = {e["name"] for e in bench.events("gate.finished")}
    assert "test-extra-zero" in ran and "test-extra-base" not in ran


def test_scn_ver_245_a_rejected_and_an_inconclusive_test_fail_the_attempt_and_the_reason_says_which_is_which(
    make_bench, monkeypatch
):
    as_typescript(monkeypatch, only="reported_from_typescript")
    bench, done = run_bound(make_bench, Step(writes={"tests/test_more.py": TWO_TESTS}, structured=result("single")))
    assert done.status == "failed"
    rejected, apart = "tests.test_more::test_total_of_nothing_is_zero", "tests.test_more::test_reported_from_typescript"
    head, _, tail = done.reason.partition("Inconclusive")
    assert rejected in head and apart not in head
    assert apart in tail and "inconclusive: " in tail and f"{TS_FILE} is not a Python file" in tail
    assert bench.events("task.tests_added") == [] and bench.wb.is_clean()


def chore_outcome(monkeypatch, made: tuple[str, ...]) -> str:
    """The failure text of `_discriminating_tests` for one rejected and one inconclusive test, given the runs made."""
    from types import SimpleNamespace

    from l4.implementer import tdd
    from l4.implementer.discrimination import ExtraRun

    rejected, apart = "tests.test_total::test_total", "src.pricing.total.test.ts::total"
    run = ExtraRun(rejected=(rejected, apart), inconclusive={apart: "why"}, runs=len(made), made=made)
    monkeypatch.setattr(tdd, "unit_base", lambda wb: "base")
    monkeypatch.setattr(tdd, "discriminate_extra", lambda wb, tests, base, **kw: run)
    tests, why, held = tdd._discriminating_tests(SimpleNamespace(), [rejected, apart], BOUND)
    assert tests == [] and held is None
    return why


def test_the_failure_text_names_only_the_runs_that_were_made(monkeypatch):
    zero_only = chore_outcome(monkeypatch, ("test-extra-zero",))
    assert "when the project's functions answer their zero value (" in zero_only and "base code" not in zero_only
    base_only = chore_outcome(monkeypatch, ("test-extra-base",))
    assert "on the unit's base code (" in base_only and "zero value" not in base_only
    both = chore_outcome(monkeypatch, ("test-extra-zero", "test-extra-base"))
    assert "zero value and on the unit's base code (tests.test_total::test_total)" in both
    assert chore_outcome(monkeypatch, ()) == both  # no run recorded: the text names both
