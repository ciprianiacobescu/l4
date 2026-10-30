"""own-test-repair (L4-IMP-091): the repair step, `run_single(kind="repair")`. The unit's red commit adds a test that
fails with an error of its own; the parent's verdict records it; the step may repair that test and nothing else."""

import hashlib
import json
from types import SimpleNamespace

from l4.agents.fake import Step
from l4.gates.e2e import E2eRun
from l4.gates.junit import TestCase, TestReport
from l4.gates.runner import GateResult
from l4.implementer.loop import run_task
from l4.implementer.prompt import PromptContext, render_prompt
from l4.implementer.tdd import run_single
from l4.specs.base import Task
from l4.verifier.types import finding_id

from .conftest import IMPL, blocked_step, result
from .test_fix_chore_e2e import bench_with, commit_files, seed_round
from .test_single_phase import seed_main

E2E_FINDING, TEST_FINDING = finding_id("e2e gate failed"), finding_id("test gate failed")
TASK = Task("1.1", "1.1", f"1.1 e2e gate failed ({E2E_FINDING})", False, " ", 0, 3, 3)
TEST_TASK = Task("1.1", "1.1", f"1.1 test gate failed ({TEST_FINDING})", False, " ", 0, 3, 3)
X, Y = "e2e.check_a::test_x", "e2e.check_a::test_y"
FLOW = "tests.test_flow::test_x"

# the unit's own browser tests; named `check_*` so the unit gate does not collect them (the e2e gate is stubbed)
E2E_FILE = """\
def helper(url):
    return url.endswith("/cart")


def test_x():
    url = "http://x/cart"
    ok = helper(url, 1)
    assert ok


def test_y():
    assert helper("/cart")
"""
E2E_FIXED = E2E_FILE.replace("helper(url, 1)", "helper(url)")
# the unit's own unit test: an error of its own (a keyword the library function does not take) before any check
FLOW_FILE = """\
from pytdd.pricing import total


def test_x():
    value = total([1.0, 2.0], rounding="x")
    assert value == 3.0
"""
FLOW_FIXED = FLOW_FILE.replace(', rounding="x"', "")
FLOW_VACUOUS = FLOW_FILE.replace('total([1.0, 2.0], rounding="x")', "sum([1.0, 2.0])")  # no longer reaches the product

E2E_FAILURES = {
    X: {
        "gate": "e2e", "kind": "other", "message": "TypeError: helper() takes 1 positional argument",
        "location": "e2e/check_a.py", "frames": "e2e/check_a.py",
    }
}  # fmt: skip
TEST_FAILURES = {
    FLOW: {
        "gate": "test", "kind": "other", "message": "TypeError: total() got an unexpected keyword argument",
        "location": "tests/test_flow.py", "frames": "tests/test_flow.py",
    }
}  # fmt: skip
E2E_STORED = [{"id": E2E_FINDING, "title": "e2e gate failed", "detail": "`pytest e2e` failed", "severity": "blocker"}]
TEST_STORED = [{"id": TEST_FINDING, "title": "test gate failed", "detail": "`pytest` failed", "severity": "blocker"}]


def red(bench, files: dict[str, str]) -> None:
    """The unit's red commit (a harness commit with `L4-TDD: red`) adds the tests."""
    for name, text in files.items():
        path = bench.wb.worktree / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    bench.wb.commit("red", task="1.1", attempt=1, phase="red", tdd="red")


def repair_step(files: dict[str, str]) -> Step:
    return Step(writes=files, structured=result("single"))


def stub_repair_e2e(monkeypatch, calls: list, *, real=None, base=None) -> None:
    """`run_e2e` without a server. `real(wb)` -> {test id: status} for the run on the repaired code; `base(wb)` for the
    run with the unit's production code swapped back to its base (`e2e-repair-base`): statuses are `passed`,
    `assertion` (failed by an assertion) or `error` (failed by another error)."""

    def default(wb):
        text = (wb.worktree / "e2e/check_a.py").read_text()
        return {X: "passed" if "helper(url)" in text and "helper(url, 1)" not in text else "error", Y: "passed"}

    def fake(wb, worktree=None, *, name="e2e", must_contain=(), extra_env=None):
        calls.append(SimpleNamespace(name=name, must_contain=sorted(must_contain)))
        if name == "e2e-repair-base":
            got = (base or (lambda w: dict.fromkeys(must_contain, "assertion")))(wb)
        else:
            got = (real or default)(wb)
        cases = {}
        for test_id, state in got.items():
            if state == "passed":
                cases[test_id] = TestCase(test_id, "passed")
            else:
                message = "assert 1 == 2" if state == "assertion" else "TypeError: bad call"
                cases[test_id] = TestCase(
                    test_id, "failed", message, failure_kind="assertion" if state == "assertion" else "other"
                )
        ok = all(c.status == "passed" for c in cases.values())
        gate = GateResult(
            name,
            "pass" if ok else "fail",
            "" if ok else "exit code 1",
            0 if ok else 1,
            wb.out_dir / f"{name}.log",
            TestReport(cases),
        )
        return E2eRun(gate, None)

    monkeypatch.setattr("l4.implementer.tdd.run_e2e", fake)


def e2e_bench(
    make_bench, monkeypatch, script, *, files=None, failures=E2E_FAILURES, real=None, base=None, product=True
):
    bench, calls = bench_with(make_bench, script), []
    pricing = (bench.wb.worktree / "src/pytdd/pricing.py").read_text()
    changed = {"src/pytdd/pricing.py": pricing + "\n# the unit's change\n"} if product else {}
    red(bench, {**(files or {"e2e/check_a.py": E2E_FILE}), **changed})
    seed_round(bench, findings=E2E_STORED, failures=failures)
    stub_repair_e2e(monkeypatch, calls, real=real, base=base)
    return bench, calls


def test_bench_is_the_base(make_bench):
    """The fixture: the unit gate collects tests/ and the repo, but not `e2e/check_a.py`."""
    bench = make_bench([])
    red(bench, {"e2e/check_a.py": E2E_FILE})
    assert bench.wb.git.run("log", "-1", "--format=%B").stdout.count("L4-TDD: red") == 1


# --- the repair is kept ---------------------------------------------------------------------------------------------


def test_a_repaired_browser_test_that_passes_in_the_e2e_gate_is_committed_as_exempt(
    make_bench, monkeypatch
):  # SCN-IMP-450
    bench, calls = e2e_bench(make_bench, monkeypatch, [repair_step({"e2e/check_a.py": E2E_FIXED})])
    done = run_single(bench.wb, TASK, [E2E_FINDING], attempt=1, kind="repair")
    assert done.status == "ok", done.reason
    message = bench.wb.git.run("log", "-1", "--format=%B").stdout
    assert "L4-TDD: exempt" in message and "L4-Step: 1.1/single/1" in message
    assert (bench.wb.worktree / "e2e/check_a.py").read_text() == E2E_FIXED
    [repaired] = bench.events("task.repaired")
    assert repaired["task"] == "1.1" and repaired["files"] == ["e2e/check_a.py"]
    assert repaired["tests"] == ["e2e/check_a.py::test_x"] and repaired["ids"] == [X]
    assert repaired["base"] == bench.wb.git.run("rev-parse", "HEAD^").stdout.strip()  # the judge reads the file there
    assert [e["task"] for e in bench.events("task.done")] == ["1.1"] and len(bench.events("task.tdd_exempt")) == 1
    assert [(c.name, c.must_contain) for c in calls] == [("e2e-chore", [X]), ("e2e-repair-base", [X])]
    assert "- [x] 1.1" in (bench.wb.ref.path / "tasks.md").read_text()


def test_a_repaired_unit_test_is_checked_in_the_test_gate_as_must_pass(make_bench):
    bench = make_bench([repair_step({"tests/test_flow.py": FLOW_FIXED})])
    red(bench, {"tests/test_flow.py": FLOW_FILE})
    seed_round(bench, findings=TEST_STORED, failures=TEST_FAILURES)
    done = run_single(bench.wb, TEST_TASK, [TEST_FINDING], attempt=1, kind="repair")
    assert done.status == "ok", done.reason
    [repaired] = bench.events("task.repaired")
    assert repaired["files"] == ["tests/test_flow.py"] and repaired["tests"] == ["tests/test_flow.py::test_x"]
    assert repaired["proved"] == {FLOW: "zero_value"}  # the repair's own proof, in the ledger
    digest = hashlib.sha256((bench.wb.worktree / "tests/test_flow.py").read_bytes()).hexdigest()[:10]
    assert repaired["sha10"] == {"tests/test_flow.py": digest}  # tied to the content that was proved


def test_a_repair_that_leaves_the_unit_test_failing_fails_naming_it(make_bench):  # SCN-IMP-454, unit gate
    still = FLOW_FILE.replace('rounding="x"', 'rounding="y"')
    bench = make_bench([repair_step({"tests/test_flow.py": still})])
    red(bench, {"tests/test_flow.py": FLOW_FILE})
    seed_round(bench, findings=TEST_STORED, failures=TEST_FAILURES)
    before = bench.wb.head()
    done = run_single(bench.wb, TEST_TASK, [TEST_FINDING], attempt=1, kind="repair")
    assert done.status == "failed" and FLOW in done.reason
    assert bench.wb.head() == before and bench.events("task.repaired") == [] and bench.events("task.done") == []
    assert (bench.wb.worktree / "tests/test_flow.py").read_text() == FLOW_FILE


def test_a_repair_that_leaves_the_browser_test_failing_fails_naming_it(make_bench, monkeypatch):  # SCN-IMP-454
    bench, _ = e2e_bench(make_bench, monkeypatch, [repair_step({"e2e/check_a.py": E2E_FILE + "\n# only a comment\n"})])
    # the comment is no change of the AST and the test still fails in the e2e gate
    done = run_single(bench.wb, TASK, [E2E_FINDING], attempt=1, kind="repair")
    assert done.status == "failed" and X in done.reason
    assert bench.events("task.repaired") == [] and bench.events("task.done") == []


# --- the repaired test must still tell a working product from a broken one -----------------------------------------


NO_LONGER = "no longer tells a working product from a broken one"


def test_a_repair_that_makes_the_unit_test_pass_without_reaching_the_product_is_refused(make_bench):
    bench = make_bench([repair_step({"tests/test_flow.py": FLOW_VACUOUS})])
    red(bench, {"tests/test_flow.py": FLOW_FILE})
    seed_round(bench, findings=TEST_STORED, failures=TEST_FAILURES)
    before = bench.wb.head()
    done = run_single(bench.wb, TEST_TASK, [TEST_FINDING], attempt=1, kind="repair")
    assert done.status == "failed" and NO_LONGER in done.reason and FLOW in done.reason
    assert bench.wb.head() == before and bench.events("task.repaired") == [] and bench.events("task.done") == []
    assert (bench.wb.worktree / "tests/test_flow.py").read_text() == FLOW_FILE


def test_a_vacuous_repair_is_refused_whatever_form_it_takes(make_bench):
    forms = {
        "or 1 == 1": FLOW_FIXED.replace("assert value == 3.0", "assert value == 3.0 or 1 == 1"),
        "== ANY": "from unittest.mock import ANY\n" + FLOW_FIXED.replace("assert value == 3.0", "assert value == ANY"),
        "an early return": FLOW_FIXED.replace("    assert value", "    return\n    assert value"),
    }
    for label, text in forms.items():
        bench = make_bench([repair_step({"tests/test_flow.py": text})])
        red(bench, {"tests/test_flow.py": FLOW_FILE})
        seed_round(bench, findings=TEST_STORED, failures=TEST_FAILURES)
        before = bench.wb.head()
        done = run_single(bench.wb, TEST_TASK, [TEST_FINDING], attempt=1, kind="repair")
        assert done.status == "failed", label
        assert bench.wb.head() == before and bench.events("task.repaired") == [], label
        assert (bench.wb.worktree / "tests/test_flow.py").read_text() == FLOW_FILE, label


RATE_BASE = "def discount_rate() -> int:\n    return 5\n"
RATE_HEAD = "def discount_rate() -> int:\n    return 0\n"
RATE_FILE = """\
from pytdd.rates import discount_rate


def test_rate():
    assert discount_rate(extra=1) == 0
"""
RATE_FIXED = RATE_FILE.replace("discount_rate(extra=1)", "discount_rate()")
RATE = "tests.test_rate::test_rate"
RATE_FAILURES = {
    RATE: {
        "gate": "test", "kind": "other", "message": "TypeError: discount_rate() got an unexpected keyword argument",
        "location": "tests/test_rate.py", "frames": "tests/test_rate.py",
    }
}  # fmt: skip


def test_a_repaired_unit_test_that_fails_only_against_the_base_code_is_refused(make_bench, tdd_repo, raw):
    """The zero-value run is the proof that the test looks at the answer; failing against the base code alone could be a
    test written for what the base happens to answer."""
    seed_main(tdd_repo, raw, {"src/pytdd/rates.py": RATE_BASE})
    bench = make_bench([repair_step({"tests/test_rate.py": RATE_FIXED})])
    red(bench, {"tests/test_rate.py": RATE_FILE, "src/pytdd/rates.py": RATE_HEAD})
    seed_round(bench, findings=TEST_STORED, failures=RATE_FAILURES)
    before = bench.wb.head()
    done = run_single(bench.wb, TEST_TASK, [TEST_FINDING], attempt=1, kind="repair")
    assert done.status == "failed" and NO_LONGER in done.reason and RATE in done.reason
    assert "zero values" in done.reason and bench.wb.head() == before and bench.events("task.repaired") == []


def test_a_browser_test_that_passes_against_the_base_code_is_refused(make_bench, monkeypatch):
    for state in ("passed", "error"):  # a pass, or a failure that is no assertion, proves nothing
        bench, calls = e2e_bench(
            make_bench, monkeypatch, [repair_step({"e2e/check_a.py": E2E_FIXED})], base=lambda wb, s=state: {X: s}
        )
        before = bench.wb.head()
        done = run_single(bench.wb, TASK, [E2E_FINDING], attempt=1, kind="repair")
        assert done.status == "failed" and NO_LONGER in done.reason and X in done.reason, state
        assert bench.wb.head() == before and bench.events("task.repaired") == []
        assert (bench.wb.worktree / "e2e/check_a.py").read_text() == E2E_FILE
        assert [c.name for c in calls] == ["e2e-chore", "e2e-repair-base"]


def test_a_browser_test_cannot_be_proved_when_the_unit_changed_no_production_code(make_bench, monkeypatch):
    bench, calls = e2e_bench(make_bench, monkeypatch, [repair_step({"e2e/check_a.py": E2E_FIXED})], product=False)
    done = run_single(bench.wb, TASK, [E2E_FINDING], attempt=1, kind="repair")
    assert done.status == "failed" and NO_LONGER in done.reason and "no production" in done.reason
    assert [c.name for c in calls] == ["e2e-chore"] and bench.events("task.repaired") == []


def test_a_proved_browser_repair_records_its_proof_and_the_file_it_belongs_to(make_bench, monkeypatch):
    bench, _ = e2e_bench(make_bench, monkeypatch, [repair_step({"e2e/check_a.py": E2E_FIXED})])
    done = run_single(bench.wb, TASK, [E2E_FINDING], attempt=1, kind="repair")
    assert done.status == "ok", done.reason
    [repaired] = bench.events("task.repaired")
    assert repaired["proved"] == {X: "base"}
    assert repaired["sha10"] == {"e2e/check_a.py": hashlib.sha256(E2E_FIXED.encode()).hexdigest()[:10]}
    # the swap of the production code was undone and nothing of the proof run is in the commit
    assert "the unit's change" in (bench.wb.worktree / "src/pytdd/pricing.py").read_text()
    assert bench.wb.git.run("show", "--name-only", "--format=", "HEAD").stdout.split()[:1] == ["e2e/check_a.py"]


def test_a_file_that_declares_another_encoding_is_refused_whatever_it_says(make_bench, monkeypatch):
    hidden = "# coding: utf-7\n" + E2E_FIXED
    bench, calls = e2e_bench(make_bench, monkeypatch, [repair_step({"e2e/check_a.py": hidden})])
    before = bench.wb.head()
    done = run_single(bench.wb, TASK, [E2E_FINDING], attempt=1, kind="repair")
    assert done.status == "failed" and "utf-7" in done.reason and calls == []
    assert bench.wb.head() == before and (bench.wb.worktree / "e2e/check_a.py").read_text() == E2E_FILE


# --- what the step may not do ---------------------------------------------------------------------------------------


def test_another_test_of_the_file_changed_is_put_back_and_the_attempt_fails(make_bench, monkeypatch):  # SCN-IMP-451
    other = E2E_FIXED.replace('assert helper("/cart")', 'assert not helper("/cart")')
    bench, calls = e2e_bench(make_bench, monkeypatch, [repair_step({"e2e/check_a.py": other})])
    before = bench.wb.head()
    done = run_single(bench.wb, TASK, [E2E_FINDING], attempt=1, kind="repair")
    assert done.status == "failed" and "outside-changed" in done.reason and calls == []
    assert bench.wb.head() == before and (bench.wb.worktree / "e2e/check_a.py").read_text() == E2E_FILE
    assert bench.events("task.repaired") == []


def test_a_helper_changed_or_a_module_call_added_fails_the_attempt(make_bench, monkeypatch):  # SCN-IMP-451
    for text in (
        E2E_FIXED.replace("return url.endswith", "return True or url.endswith"),
        E2E_FIXED + "\nprint('hi')\n",
    ):
        bench, calls = e2e_bench(make_bench, monkeypatch, [repair_step({"e2e/check_a.py": text})])
        done = run_single(bench.wb, TASK, [E2E_FINDING], attempt=1, kind="repair")
        assert done.status == "failed" and "outside-changed" in done.reason and calls == []
        assert (bench.wb.worktree / "e2e/check_a.py").read_text() == E2E_FILE


def test_removing_an_assert_or_adding_a_skip_fails_the_attempt(make_bench, monkeypatch):  # SCN-IMP-452
    for text, rule in (
        (E2E_FIXED.replace("    assert ok\n", "    print(ok)\n"), "assert-removed"),
        (E2E_FIXED.replace("    assert ok\n", "    import pytest\n    pytest.skip('later')\n"), "skip-added"),
        (E2E_FIXED.replace("def test_x():", "def test_x(extra):"), "signature"),
    ):
        bench, calls = e2e_bench(make_bench, monkeypatch, [repair_step({"e2e/check_a.py": text})])
        done = run_single(bench.wb, TASK, [E2E_FINDING], attempt=1, kind="repair")
        assert done.status == "failed" and rule in done.reason and calls == []
        assert bench.events("task.repaired") == []


def test_product_code_changed_as_well_is_put_back_and_the_attempt_fails(make_bench, monkeypatch):  # SCN-IMP-453
    bench, calls = e2e_bench(
        make_bench,
        monkeypatch,
        [repair_step({"e2e/check_a.py": E2E_FIXED, "src/pytdd/pricing.py": IMPL + "\n# changed\n"})],
    )
    before = bench.wb.head()
    done = run_single(bench.wb, TASK, [E2E_FINDING], attempt=1, kind="repair")
    assert done.status == "failed" and "src/pytdd/pricing.py" in done.reason and calls == []
    assert bench.wb.head() == before and "# changed" not in (bench.wb.worktree / "src/pytdd/pricing.py").read_text()
    assert (bench.wb.worktree / "e2e/check_a.py").read_text() == E2E_FILE  # nothing of the attempt is kept


def test_another_test_file_a_new_test_file_and_a_support_file_are_put_back_and_fail(make_bench, monkeypatch):
    for extra in (
        {"tests/test_pricing.py": "def test_total_adds_prices():\n    assert True\n"},  # a pre-existing test file
        {"e2e/check_b.py": "def test_z():\n    assert True\n"},  # a new test file
        {"e2e/conftest.py": "import pytest\n"},  # a support file
    ):
        bench, calls = e2e_bench(make_bench, monkeypatch, [repair_step({"e2e/check_a.py": E2E_FIXED, **extra})])
        done = run_single(bench.wb, TASK, [E2E_FINDING], attempt=1, kind="repair")
        [path] = extra
        assert done.status == "failed" and path in done.reason and calls == [], extra
        assert (
            not (bench.wb.worktree / "e2e/check_b.py").exists() and not (bench.wb.worktree / "e2e/conftest.py").exists()
        )


def test_a_link_in_place_of_the_test_file_or_its_directory_fails_the_attempt_and_is_removed(
    make_bench, monkeypatch, tmp_path
):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "check_a.py").write_text(E2E_FIXED)
    for links in ({"e2e/check_a.py": str(outside / "check_a.py")}, {"e2e": str(outside)}):
        bench, calls = e2e_bench(make_bench, monkeypatch, [Step(links=links, structured=result("single"))])
        done = run_single(bench.wb, TASK, [E2E_FINDING], attempt=1, kind="repair")
        assert done.status == "failed" and calls == [], links
        assert not (bench.wb.worktree / "e2e").is_symlink() and not (bench.wb.worktree / "e2e/check_a.py").is_symlink()
        assert (bench.wb.worktree / "e2e/check_a.py").read_text() == E2E_FILE
        assert (outside / "check_a.py").read_text() == E2E_FIXED  # nothing was written through the link


def test_a_plain_fix_chore_still_may_not_change_the_test(make_bench, monkeypatch):  # SCN-IMP-458
    bench, calls = e2e_bench(make_bench, monkeypatch, [repair_step({"e2e/check_a.py": E2E_FIXED})])
    before = bench.wb.head()
    done = run_single(bench.wb, TASK, [E2E_FINDING], attempt=1)  # kind="fix"
    assert done.status == "failed" and "nothing changed" in done.reason
    assert bench.wb.head() == before and (bench.wb.worktree / "e2e/check_a.py").read_text() == E2E_FILE
    assert bench.events("task.repaired") == []


# --- the step does not trust the marker -----------------------------------------------------------------------------


def test_a_test_that_is_not_the_units_own_new_test_is_no_repair_whatever_the_marker_says(make_bench, monkeypatch):
    pre = "tests.test_pricing::test_total_adds_prices"
    failures = {
        pre: {
            "gate": "test",
            "kind": "other",
            "message": "TypeError: x",
            "location": "tests/test_pricing.py",
            "frames": "tests/test_pricing.py",
        }
    }
    bench = make_bench([repair_step({"tests/test_pricing.py": "def test_total_adds_prices():\n    assert True\n"})])
    seed_round(bench, findings=TEST_STORED, failures=failures)
    before = bench.wb.head()
    done = run_single(bench.wb, TEST_TASK, [TEST_FINDING], attempt=1, kind="repair")
    assert done.status == "failed" and pre in done.reason
    assert bench.adapter.requests == [] and bench.wb.head() == before  # no agent step was made


def test_a_failure_by_assertion_or_a_mixed_finding_is_no_repair(make_bench, monkeypatch):
    for failures in (
        {X: {"gate": "e2e", "kind": "assertion", "message": "assert 1 == 2"}},
        {
            **E2E_FAILURES,
            "e2e.check_a::test_z": {
                "gate": "e2e",
                "kind": "other",
                "message": "x",
                "location": "e2e/check_a.py",
                "frames": "e2e/check_a.py",
            },
        },
    ):
        bench, calls = e2e_bench(
            make_bench, monkeypatch, [repair_step({"e2e/check_a.py": E2E_FIXED})], failures=failures
        )
        done = run_single(bench.wb, TASK, [E2E_FINDING], attempt=1, kind="repair")
        assert done.status == "failed" and bench.adapter.requests == [] and calls == []


def test_a_round_that_is_not_on_record_is_no_repair(make_bench, monkeypatch):
    bench, calls = e2e_bench(make_bench, monkeypatch, [repair_step({"e2e/check_a.py": E2E_FIXED})], failures=None)
    done = run_single(bench.wb, TASK, [E2E_FINDING], attempt=1, kind="repair")
    assert done.status == "failed" and "not on record" in done.reason and bench.adapter.requests == []


# --- the step itself ------------------------------------------------------------------------------------------------


def test_the_prompt_is_the_repair_template_and_names_the_tests_and_the_rules(make_bench, monkeypatch):
    bench, _ = e2e_bench(make_bench, monkeypatch, [repair_step({"e2e/check_a.py": E2E_FIXED})])
    run_single(bench.wb, TASK, [E2E_FINDING], attempt=1, kind="repair")
    [rendered] = bench.events("prompt.rendered")
    assert rendered["template_version"] == "contract@13+single_repair@1"
    prompt = bench.adapter.requests[0].prompt
    assert "Phase: SINGLE (repair" in prompt and "Phase: SINGLE (fix one finding" not in prompt
    assert "e2e/check_a.py::test_x" in prompt and "TypeError: helper() takes 1 positional" in prompt
    assert "may be right" in prompt and "report status blocked" in prompt and "technical" in prompt


def test_a_blocked_repair_step_returns_its_questions_and_changes_nothing(make_bench, monkeypatch):
    bench, calls = e2e_bench(make_bench, monkeypatch, [blocked_step()])
    before = bench.wb.head()
    done = run_single(bench.wb, TASK, [E2E_FINDING], attempt=1, kind="repair")
    assert done.status == "blocked" and bench.wb.head() == before and calls == []


def test_the_rendered_prompt_of_a_plain_chore_is_unchanged():
    from l4.implementer.prompt import load_template

    assert load_template("single").version == 3 and load_template("single_repair").version == 1
    ctx = PromptContext(unit_id="openspec:x", adapter="fake", task_key="1.1", task_title="t")
    assert render_prompt("single", ctx).template_version == "contract@13+single@3"
    repair = PromptContext(
        unit_id="openspec:x", adapter="fake", task_key="1.1", task_title="t",
        repair_tests=("e2e/a.py::test_x (other, e2e): TypeError: bad",),
    )  # fmt: skip
    assert render_prompt("single", repair).template_version == "contract@13+single_repair@1"
    assert "<l4:data" in render_prompt("single", repair).text


# --- the loop -------------------------------------------------------------------------------------------------------


def tag_as_repair(bench) -> None:
    marker = {
        "schema": "l4/fix-unit@1", "parent": "openspec:add-discount-codes", "round": 1,
        "findings": [E2E_FINDING], "chores": [E2E_FINDING], "repairs": [E2E_FINDING],
    }  # fmt: skip
    commit_files(bench, {f"{bench.wb.unit_rel}/.l4/fix.json": json.dumps(marker)})  # committed: a discard keeps it


def test_the_loop_runs_a_repair_task_as_a_repair_chore(make_bench, monkeypatch):
    bench, calls = e2e_bench(make_bench, monkeypatch, [repair_step({"e2e/check_a.py": E2E_FIXED})])
    tag_as_repair(bench)
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "done" and len(bench.events("task.repaired")) == 1


def test_a_repair_task_whose_attempts_are_used_up_says_the_test_may_be_right(make_bench, monkeypatch):  # SCN-IMP-454
    nothing = repair_step({"e2e/check_a.py": E2E_FILE + "\n# comment\n"})
    bench, _ = e2e_bench(make_bench, monkeypatch, [nothing, nothing, nothing])
    tag_as_repair(bench)
    outcome = run_task(bench.wb, TASK)
    assert outcome.status == "halt"
    assert "max_task_attempts" in outcome.reason
    assert "may be right" in outcome.reason and "product code" in outcome.reason
    assert bench.events("task.repaired") == []
