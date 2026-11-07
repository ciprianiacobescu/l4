"""named-tests-trace 2.2, 2.3 (L4-IMP-093, SCN-IMP-494..498): a scenario the unit restates word for word, that a passing
test of the base traces, needs no new test and is confirmed by the base specs without a run."""

import dataclasses
import sys
from types import SimpleNamespace

import pytest

from l4.agents.fake import Step
from l4.gates.junit import TestCase, TestReport
from l4.implementer import tdd
from l4.implementer.result import TRACE_HINT_PYTEST
from l4.implementer.tdd import VIA_UNCHANGED_SPEC, run_red, unchanged_on_base
from l4.specs.base import Framework, Task, UnitRef
from l4.specs.criteria import openspec_criteria
from l4.vcs.git import Git

from .._kiro_probe import PROBE_IDS
from ..conftest import TEST_COMMAND, UNIT, TddRepo
from .conftest import HEADER, KIRO_UNIT, KNOWN, STUB, UNKNOWN, UNKNOWN_TEST, build_bench, result, to_kiro
from .test_red_preexisting_tests import FAKE_RUNNER

CHANGE = "openspec/changes/add-discount-codes"
ARCHIVED_SPEC = "openspec/specs/pricing/spec.md"
BASE_TEST = "tests.test_known::test_known_code_base"
TASK = Task("1.1", "1.1", "1.1 Add `apply_discount`", False, " ", 0, 3, 3)
KNOWN_THEN = "it returns `45.0`"
SCENARIOS = {
    "Known code": ('`apply_discount(50.0, "SAVE10")` is called', "{known_then}"),
    "Unknown code": ('`apply_discount(50.0, "NOPE")` is called', "it raises `ValueError`"),
    "Hidden code": ('`apply_discount(50.0, "HIDDEN")` is called', "it raises `KeyError`"),
    "Rounded": ('`apply_discount(10.01, "SAVE10")` is called', "it returns `9.01`"),
}


def scenario(name: str, known_then: str = KNOWN_THEN) -> str:
    when, then = SCENARIOS[name]
    return f"#### Scenario: {name}\n- **WHEN** {when}\n- **THEN** {then.format(known_then=known_then)}\n"


INTRO = "The `apply_discount(amount, code)` function SHALL reduce `amount` by the percentage of a known code.\n"


def delta(known_then: str = KNOWN_THEN, section: str = "MODIFIED") -> str:
    scenarios = "\n".join(scenario(name, known_then) for name in SCENARIOS)
    return f"## {section} Requirements\n\n### Requirement: Discount codes\n{INTRO}\n{scenarios}"


def archived() -> str:
    return (
        "# pricing Specification\n\n## Purpose\nPricing.\n\n## Requirements\n\n"
        f"### Requirement: Discount codes\n{INTRO}\n{scenario('Known code')}"
    )


def unit_repo(tdd_repo: TddRepo, *, known_then: str = KNOWN_THEN, archive: bool = True,
              section: str = "MODIFIED", hidden_test: bool = False) -> dict[str, str]:  # fmt: skip
    """The py_tdd repository whose change restates the archived scenario `Known code` (MODIFIED) and adds three more,
    with a passing base test that traces `Known code`, all committed on `main` before the unit branch is made. The
    ids of the scenarios by name."""
    repo = tdd_repo.repo
    git = Git(repo, environ=tdd_repo.environ)
    if archive:
        (repo / ARCHIVED_SPEC).parent.mkdir(parents=True, exist_ok=True)
        (repo / ARCHIVED_SPEC).write_text(archived())
    (repo / CHANGE / "specs/pricing/spec.md").write_text(delta(known_then, section))
    ids = {c.scenario: c.id for c in openspec_criteria(repo / CHANGE)}
    (repo / "tests/test_known.py").write_text(
        f'import pytest\n\nfrom pytdd import total\n\n\n@pytest.mark.l4("{ids["Known code"]}")\n'
        "def test_known_code_base():\n    assert total([1.0]) == 1.0\n"
    )
    if hidden_test:  # a second base test, of a scenario the archived spec lacks
        (repo / "tests/test_hidden.py").write_text(
            f'import pytest\n\nfrom pytdd import total\n\n\n@pytest.mark.l4("{ids["Hidden code"]}")\n'
            "def test_hidden_base():\n    assert total([3.0]) == 3.0\n"
        )
    git.run("add", "-A")
    git.run("commit", "-q", "-m", "archived specs and a base test")
    git.push("origin", ["main"])
    return ids


def reports(
    *,
    base: str = "passed",
    red: str = "passed",
    marks: tuple[str, ...] = (KNOWN,),
    red_marks: tuple[str, ...] | None = None,
) -> tuple[TestReport, TestReport]:
    before = TestReport({BASE_TEST: TestCase(BASE_TEST, base, criteria=marks)})  # type: ignore[arg-type]
    traced = marks if red_marks is None else red_marks
    after = TestReport({BASE_TEST: TestCase(BASE_TEST, red, criteria=traced)})  # type: ignore[arg-type]
    return before, after


def found(bench, base: TestReport, red: TestReport) -> dict[str, tuple[str, ...]]:
    return unchanged_on_base(bench.wb, bench.wb.provider.criteria(bench.wb.ref), base, red)


# --- tdd.unchanged_on_base ---


def test_the_ids_of_the_units_scenarios_are_the_fixtures(tdd_repo):
    ids = unit_repo(tdd_repo)
    assert ids["Known code"] == KNOWN and ids["Unknown code"] == UNKNOWN


def test_a_restated_scenario_with_a_passing_base_test_is_unchanged_on_the_base(tdd_repo):  # SCN-IMP-494
    unit_repo(tdd_repo)
    bench = build_bench(tdd_repo, [], UNIT)
    assert found(bench, *reports()) == {KNOWN: (BASE_TEST,)}


def test_a_test_that_also_traces_new_scenarios_up_to_the_cap_still_counts(tdd_repo):
    ids = unit_repo(tdd_repo)
    bench = build_bench(tdd_repo, [], UNIT)
    marks = (KNOWN, ids["Unknown code"], ids["Hidden code"])  # three of the unit's four, the cap is 3
    assert found(bench, *reports(marks=marks)) == {KNOWN: (BASE_TEST,)}  # the others are not archived: not unchanged


def test_a_scenario_whose_body_changed_under_the_same_name_is_not_unchanged(tdd_repo):  # SCN-IMP-497
    unit_repo(tdd_repo, known_then="it returns `44.55`")  # the archived spec holds `45.0`: the same id, another text
    bench = build_bench(tdd_repo, [], UNIT)
    assert found(bench, *reports()) == {}


def test_a_scenario_of_a_requirement_the_archived_specs_lack_is_not_unchanged(tdd_repo):  # SCN-IMP-497
    unit_repo(tdd_repo, archive=False, section="ADDED")
    bench = build_bench(tdd_repo, [], UNIT)
    assert found(bench, *reports()) == {}


def test_a_scenario_the_archived_spec_lacks_is_not_unchanged_even_with_a_passing_test(tdd_repo):  # SCN-IMP-497
    unit_repo(tdd_repo)
    bench = build_bench(tdd_repo, [], UNIT)
    assert found(bench, *reports(marks=(UNKNOWN,))) == {}  # `Unknown code` is new in the delta


def test_a_scenario_whose_only_tracing_test_fails_at_the_base_is_not_unchanged(tdd_repo):  # SCN-IMP-498
    unit_repo(tdd_repo)
    bench = build_bench(tdd_repo, [], UNIT)
    assert found(bench, *reports(base="failed")) == {}
    assert found(bench, *reports(base="skipped")) == {}


def test_a_scenario_whose_only_tracing_test_fails_at_red_is_not_unchanged(tdd_repo):  # SCN-IMP-498
    unit_repo(tdd_repo)
    bench = build_bench(tdd_repo, [], UNIT)
    assert found(bench, *reports(red="failed")) == {}
    lost = TestReport({})
    assert found(bench, reports()[0], lost) == {}


def test_a_scenario_whose_only_test_no_longer_traces_it_at_red_is_not_unchanged(tdd_repo):  # SCN-IMP-498
    unit_repo(tdd_repo)
    bench = build_bench(tdd_repo, [], UNIT)
    assert found(bench, *reports(red_marks=())) == {}


def test_a_scenario_whose_only_tracing_test_traces_more_than_the_cap_is_not_unchanged(tdd_repo):  # SCN-IMP-498
    ids = unit_repo(tdd_repo)
    bench = build_bench(tdd_repo, [], UNIT)  # the cap is 3, the unit has four criteria
    assert found(bench, *reports(marks=tuple(ids.values()))) == {}


def test_a_scenario_no_base_test_traces_is_not_unchanged(tdd_repo):  # SCN-IMP-498
    unit_repo(tdd_repo)
    bench = build_bench(tdd_repo, [], UNIT)
    assert found(bench, *reports(marks=())) == {}


def test_without_a_unit_base_nothing_is_unchanged(tdd_repo, monkeypatch):  # SCN-IMP-498
    unit_repo(tdd_repo)
    bench = build_bench(tdd_repo, [], UNIT)
    monkeypatch.setattr(tdd, "unit_base", lambda wb: None)
    assert found(bench, *reports()) == {}


def test_a_plain_kiro_unit_has_nothing_unchanged_on_the_base(tdd_repo):  # SCN-IMP-498
    to_kiro(tdd_repo)
    bench = build_bench(tdd_repo, [], KIRO_UNIT, frameworks=["kiro"])
    marks = tuple(PROBE_IDS.values())
    assert found(bench, *reports(marks=marks)) == {}


def test_a_kiro_follow_up_reads_its_merged_parent(tdd_repo):
    to_kiro(tdd_repo)
    bench = build_bench(tdd_repo, [], KIRO_UNIT, frameworks=["kiro"])
    criteria = bench.wb.provider.criteria(bench.wb.ref)
    follow = SimpleNamespace(criteria=lambda unit: criteria, merged_parent_criteria=lambda: criteria)
    wb = SimpleNamespace(git=bench.wb.git, ref=bench.wb.ref, provider=follow, cfg=bench.wb.cfg)
    marks = tuple(PROBE_IDS.values())
    assert unchanged_on_base(wb, criteria, *reports(marks=marks)) == dict.fromkeys(marks, (BASE_TEST,))


class Family:
    """What the verifier reads for a fix unit: the family's criteria as the parent's reading, the fix unit's own for the
    ids it restates (`FamilyProvider.criteria`)."""

    def __init__(self, parent: UnitRef, own, parents) -> None:
        self.parent, self._own, self._parents = parent, own, parents

    def criteria(self, unit):
        return self._parents if unit == self.parent else self._own


def fix_workbench(bench, *, own_text: str | None = None, parent_text: str | None = None):
    parent = bench.wb.ref
    fix = UnitRef(Framework.OPENSPEC, "add-discount-codes-fix-1", parent.path)
    criteria = bench.wb.provider.criteria(parent)

    def reading(text: str | None):
        return [dataclasses.replace(c, text=text) if text and c.id == KNOWN else c for c in criteria]

    family = Family(parent, reading(own_text), reading(parent_text))
    return SimpleNamespace(git=bench.wb.git, ref=fix, provider=family, cfg=bench.wb.cfg), family.criteria(fix)


def test_a_fix_unit_counts_only_what_the_parents_reading_leaves_unchanged_too(tdd_repo):
    unit_repo(tdd_repo)
    bench = build_bench(tdd_repo, [], UNIT)
    wb, criteria = fix_workbench(bench)
    assert unchanged_on_base(wb, criteria, *reports()) == {KNOWN: (BASE_TEST,)}
    wb, criteria = fix_workbench(bench, own_text="WHEN x THEN y")  # the fix unit's reading differs from the archived
    assert unchanged_on_base(wb, criteria, *reports()) == {}
    wb, criteria = fix_workbench(bench, parent_text="WHEN x THEN y")  # the parent's differs, the fix unit restates
    assert unchanged_on_base(wb, criteria, *reports()) == {}


# --- run_red: SCN-IMP-494..498 ---


def new_unknown_test(*, criteria=(KNOWN, UNKNOWN), **over) -> Step:
    return Step(
        writes={"tests/test_discount.py": HEADER + UNKNOWN_TEST, "src/pytdd/pricing.py": STUB},
        structured=result("red", criteria_ids=list(criteria), **over),
    )


def proofs(bench) -> dict:
    return bench.events("task.red_ok")[-1]["criteria"]


def gates_run(bench) -> set[str]:
    return {e["name"] for e in bench.events("gate.finished")}


def test_scn_imp_494_a_fresh_task_needs_no_new_test_for_a_restated_scenario(tdd_repo):
    unit_repo(tdd_repo)
    bench = build_bench(tdd_repo, [new_unknown_test()], UNIT)
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "ok", out.reason
    assert set(proofs(bench)) == {UNKNOWN} and proofs(bench)[UNKNOWN]["tests"] == [
        "tests.test_discount::test_unknown_code"
    ]
    assert bench.events("check.inconclusive") == [] and bench.events("question.raised") == []
    assert bench.events("criterion.pre_satisfied") == []


def test_scn_imp_497_a_changed_scenario_with_the_same_id_still_needs_its_new_test(tdd_repo):
    unit_repo(tdd_repo, known_then="it returns `44.55`")
    bench = build_bench(tdd_repo, [new_unknown_test()], UNIT)
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "failed" and out.reason == f"no new test traces {KNOWN}: {TRACE_HINT_PYTEST}"


def test_scn_imp_497_a_scenario_of_an_added_requirement_still_needs_its_new_test(tdd_repo):
    unit_repo(tdd_repo, archive=False, section="ADDED")
    bench = build_bench(tdd_repo, [new_unknown_test()], UNIT)
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "failed" and out.reason == f"no new test traces {KNOWN}: {TRACE_HINT_PYTEST}"


def passes_known(path: str = "tests/test_known_again.py") -> dict[str, str]:
    return {
        path: f'import pytest\n\nfrom pytdd import total\n\n\n@pytest.mark.l4("{KNOWN}")\n'
        "def test_known_code_again():\n    assert total([2.0]) == 2.0\n"
    }


def test_scn_imp_497_a_passing_new_test_of_a_changed_scenario_still_goes_to_the_zero_value_run(tdd_repo):
    unit_repo(tdd_repo, known_then="it returns `44.55`")
    step = Step(
        writes={**passes_known(), "tests/test_discount.py": HEADER + UNKNOWN_TEST, "src/pytdd/pricing.py": STUB},
        structured=result("red", criteria_ids=[KNOWN, UNKNOWN]),
    )
    bench = build_bench(tdd_repo, [step], UNIT)
    run_red(bench.wb, TASK, attempt=1)
    assert "test-presatisfied" in gates_run(bench)


TS_KNOWN = (
    'import { expect, it } from "vitest";\n\n'
    f'it("{KNOWN} the discount of a known code", () => {{\n  expect(CODES.length).toBe(16);\n}});\n'
)
TS_ID = f"src/known.test.ts::{KNOWN} the discount of a known code"


def not_python_bench(tdd_repo, tmp_path, steps):
    runner = tmp_path / "fake_runner.py"
    runner.write_text(FAKE_RUNNER)
    command = f"{sys.executable} {runner} '{TEST_COMMAND}'"
    return build_bench(tdd_repo, steps, UNIT, test={"command": command})


def test_scn_imp_495_a_passing_new_test_of_a_restated_scenario_is_confirmed_by_the_base_specs(tdd_repo, tmp_path):
    unit_repo(tdd_repo)
    step = Step(
        writes={"src/known.test.ts": TS_KNOWN, "tests/test_discount.py": HEADER + UNKNOWN_TEST,
                "src/pytdd/pricing.py": STUB},
        structured=result("red", criteria_ids=[KNOWN, UNKNOWN]),
    )  # fmt: skip
    bench = not_python_bench(tdd_repo, tmp_path, [step])
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "ok", out.reason
    assert not {"test-presatisfied", "test-base-run"} & gates_run(bench)
    [event] = bench.events("criterion.pre_satisfied")
    assert event["criterion"] == KNOWN and event["tests"] == [TS_ID] and event["via"] == VIA_UNCHANGED_SPEC
    assert proofs(bench)[KNOWN] == {
        "tests": [TS_ID], "proof": "pre_satisfied", "discriminating": [], "via": VIA_UNCHANGED_SPEC,
        "base_tests": [BASE_TEST],
    }  # fmt: skip
    assert proofs(bench)[UNKNOWN]["tests"] == ["tests.test_discount::test_unknown_code"]
    assert bench.events("question.raised") == []


def test_scn_imp_496_a_task_of_restated_scenarios_that_adds_no_test_is_already_satisfied_without_a_run(tdd_repo):
    unit_repo(tdd_repo)
    step = Step(
        structured=result("red", criteria_ids=[KNOWN], tdd_exemption={"reason": "already_satisfied by the base"})
    )
    bench = build_bench(tdd_repo, [step], UNIT)
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "already_satisfied", out.reason
    assert not {"test-presatisfied", "test-base-run", "test-zero"} & gates_run(bench)
    [event] = bench.events("criterion.pre_satisfied")
    assert event["criterion"] == KNOWN and event["via"] == VIA_UNCHANGED_SPEC and event["tests"] == [BASE_TEST]
    assert proofs(bench)[KNOWN] == {
        "tests": [BASE_TEST], "proof": "pre_satisfied", "discriminating": [], "via": VIA_UNCHANGED_SPEC,
        "base_tests": [BASE_TEST],
    }  # fmt: skip
    assert "L4-TDD: already-satisfied" in bench.wb.git.run("log", "-1", "--format=%B").stdout


def test_scn_imp_496_a_task_of_restated_scenarios_whose_new_tests_pass_is_already_satisfied_without_a_run(tdd_repo):
    unit_repo(tdd_repo)
    step = Step(writes=passes_known(), structured=result("red", criteria_ids=[KNOWN]))
    bench = build_bench(tdd_repo, [step], UNIT)
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "already_satisfied", out.reason
    assert not {"test-presatisfied", "test-base-run", "test-zero"} & gates_run(bench)
    [event] = bench.events("criterion.pre_satisfied")
    assert event["via"] == VIA_UNCHANGED_SPEC and event["tests"] == ["tests.test_known_again::test_known_code_again"]


def test_scn_imp_496_no_test_no_change_and_no_reason_is_still_no_tests_added(tdd_repo):
    unit_repo(tdd_repo)
    bench = build_bench(tdd_repo, [Step(structured=result("red", criteria_ids=[KNOWN]))], UNIT)
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "failed" and out.reason == "no tests added"


def test_scn_imp_496_a_changed_scenario_in_the_already_satisfied_branch_keeps_its_runs(tdd_repo):
    unit_repo(tdd_repo, known_then="it returns `44.55`")
    step = Step(
        structured=result("red", criteria_ids=[KNOWN], tdd_exemption={"reason": "already_satisfied by the base"})
    )
    bench = build_bench(tdd_repo, [step], UNIT)
    run_red(bench.wb, TASK, attempt=1)
    assert "test-presatisfied" in gates_run(bench)


@pytest.mark.parametrize("variant", ["fails_at_base", "no_test_traces", "over_the_cap", "no_unit_base"])
def test_scn_imp_498_a_scenario_without_a_passing_base_test_in_the_cap_still_needs_its_new_test(
    tdd_repo, monkeypatch, variant
):
    ids = unit_repo(tdd_repo)
    test = tdd_repo.repo / "tests/test_known.py"
    if variant == "fails_at_base":
        text = test.read_text().replace("== 1.0", "== 2.0")
        test.write_text(text)
    elif variant == "no_test_traces":
        test.write_text(test.read_text().replace(f'@pytest.mark.l4("{KNOWN}")\n', ""))
    elif variant == "over_the_cap":
        marks = "".join(f'@pytest.mark.l4("{i}")\n' for i in ids.values())
        test.write_text(test.read_text().replace(f'@pytest.mark.l4("{KNOWN}")\n', marks))
    git = Git(tdd_repo.repo, environ=tdd_repo.environ)
    git.run("add", "-A")
    git.run("commit", "-q", "--allow-empty", "-m", variant)
    git.push("origin", ["main"])
    bench = build_bench(tdd_repo, [new_unknown_test()], UNIT)
    if variant == "no_unit_base":
        monkeypatch.setattr(tdd, "unit_base", lambda wb: None)
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "failed", out.reason
    assert out.reason == f"no new test traces {KNOWN}: {TRACE_HINT_PYTEST}"


def test_a_cited_unchanged_scenario_that_a_new_test_fails_by_assertion_is_an_ordinary_red_test(tdd_repo):
    unit_repo(tdd_repo)
    step = Step(
        writes={
            "tests/test_discount.py": HEADER + f'@pytest.mark.l4("{KNOWN}")\ndef test_known_code_discounts():\n'
            '    assert apply_discount(50.0, "SAVE10") == 45.0\n\n\n' + UNKNOWN_TEST,
            "src/pytdd/pricing.py": STUB,
        },
        structured=result("red", criteria_ids=[KNOWN, UNKNOWN]),
    )
    bench = build_bench(tdd_repo, [step], UNIT)
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "ok", out.reason
    assert proofs(bench)[KNOWN]["tests"] == ["tests.test_discount::test_known_code_discounts"]
    assert proofs(bench)[KNOWN]["proof"] != "pre_satisfied" and bench.events("criterion.pre_satisfied") == []


# --- review of named-tests-trace: F2, F3, F5, F6 ---

NAMES_KNOWN = "- [ ] 1.1 Add `apply_discount`; update `tests/test_known.py::test_known_code_base` in place\n"
NAMES_HIDDEN = "- [ ] 1.1 Add `apply_discount`; update `tests/test_hidden.py::test_hidden_base` in place\n"
KNOWN_ASSERT_TRUE = (
    f'import pytest\n\nfrom pytdd import total\n\n\n@pytest.mark.l4("{KNOWN}")\n'
    "def test_known_code_base():\n    assert True\n"
)


def test_f2_a_base_test_red_weakened_in_place_exempts_nothing(tdd_repo):
    """The base test of the restated scenario is named by the task and red rewrites it to `assert True`, keeping its
    marker: it still passes, and it is no longer the base's evidence, so the criterion needs a new test."""
    from .test_red_preexisting_tests import reviewed

    unit_repo(tdd_repo)
    step = Step(
        writes={
            "tests/test_known.py": KNOWN_ASSERT_TRUE,
            "tests/test_discount.py": HEADER + UNKNOWN_TEST,
            "src/pytdd/pricing.py": STUB,
        },
        structured=result("red", criteria_ids=[KNOWN, UNKNOWN]),
    )
    bench = build_bench(tdd_repo, [step], UNIT)
    task = reviewed(bench, NAMES_KNOWN)
    out = run_red(bench.wb, task, attempt=1)
    assert out.status == "failed", out.reason
    assert out.reason.startswith(f"no new test traces {KNOWN}: {TRACE_HINT_PYTEST}")


def test_f2_unchanged_on_base_ignores_the_ids_it_is_told_red_changed(tdd_repo):
    unit_repo(tdd_repo)
    bench = build_bench(tdd_repo, [], UNIT)
    criteria = bench.wb.provider.criteria(bench.wb.ref)
    base, red = reports()
    assert unchanged_on_base(bench.wb, criteria, base, red, changed={BASE_TEST}) == {}
    assert unchanged_on_base(bench.wb, criteria, base, red, changed={"tests.other::t"}) == {KNOWN: (BASE_TEST,)}


def test_f3_a_named_test_that_traces_only_an_uncited_criterion_proves_nothing(tdd_repo):
    """SCN-IMP-440: the step cites `Known code` (unchanged on the base, so it needs no test), red changes a named test
    of `Hidden code` so that it fails by assertion and adds no new test: the named test proves no cited criterion."""
    from l4.implementer.tdd import NAMED_NOT_NEW

    from .test_red_preexisting_tests import reviewed

    unit_repo(tdd_repo, hidden_test=True)
    changed = (
        "import pytest\n\nfrom pytdd import total\n\n\n"
        '@pytest.mark.l4("{hidden}")\ndef test_hidden_base():\n    assert total([3.0]) == 99\n'
    )
    bench = build_bench(tdd_repo, [], UNIT)
    hidden = next(c.id for c in bench.wb.provider.criteria(bench.wb.ref) if c.scenario == "Hidden code")
    bench.adapter._script.append(
        Step(
            writes={"tests/test_hidden.py": changed.format(hidden=hidden)},
            structured=result("red", criteria_ids=[KNOWN]),
        )
    )
    task = reviewed(bench, NAMES_HIDDEN)
    out = run_red(bench.wb, task, attempt=1)
    assert out.status == "failed" and out.reason == NAMED_NOT_NEW
    assert bench.events("task.red_ok") == []


def test_f3_the_same_named_test_counts_once_its_criterion_is_cited(tdd_repo):
    from .test_red_preexisting_tests import reviewed

    unit_repo(tdd_repo, hidden_test=True)
    bench = build_bench(tdd_repo, [], UNIT)
    hidden = next(c.id for c in bench.wb.provider.criteria(bench.wb.ref) if c.scenario == "Hidden code")
    changed = (
        "import pytest\n\nfrom pytdd import total\n\n\n"
        f'@pytest.mark.l4("{hidden}")\ndef test_hidden_base():\n    assert total([3.0]) == 99\n'
    )
    bench.adapter._script.append(
        Step(writes={"tests/test_hidden.py": changed}, structured=result("red", criteria_ids=[KNOWN, hidden]))
    )
    out = run_red(bench.wb, reviewed(bench, NAMES_HIDDEN), attempt=1)
    assert out.status == "ok", out.reason
    assert set(proofs(bench)) == {hidden}


def test_f5_a_fix_unit_task_is_not_confirmed_by_the_base_specs(tdd_repo, tmp_path):
    """The judge reads no fix unit's events (L4-VER-018), so a fix unit's task keeps the zero-value run and the hold."""
    unit_repo(tdd_repo)
    step = Step(
        writes={"src/known.test.ts": TS_KNOWN, "tests/test_discount.py": HEADER + UNKNOWN_TEST,
                "src/pytdd/pricing.py": STUB},
        structured=result("red", criteria_ids=[KNOWN, UNKNOWN]),
    )  # fmt: skip
    bench = not_python_bench(tdd_repo, tmp_path, [step])
    bench.wb.event_context = {"fix_unit": "add-discount-codes-fix-1"}
    out = run_red(bench.wb, TASK, attempt=1)
    assert VIA_UNCHANGED_SPEC not in str(bench.events("criterion.pre_satisfied")) + str(out.criteria)
    assert out.status == "held" or "test-presatisfied" in gates_run(bench)


def test_f5_a_fix_unit_task_of_restated_scenarios_is_not_already_satisfied_by_the_base_specs(tdd_repo):
    unit_repo(tdd_repo)
    step = Step(
        structured=result("red", criteria_ids=[KNOWN], tdd_exemption={"reason": "already_satisfied by the base"})
    )
    bench = build_bench(tdd_repo, [step], UNIT)
    bench.wb.event_context = {"fix_unit": "add-discount-codes-fix-1"}
    run_red(bench.wb, TASK, attempt=1)
    assert VIA_UNCHANGED_SPEC not in str(bench.events("criterion.pre_satisfied"))
    assert "test-presatisfied" in gates_run(bench)


def commit_in_worktree(bench, message: str) -> None:
    bench.wb.git.run("add", "-A")
    bench.wb.git.run("-c", "user.name=t", "-c", "user.email=t@x.invalid", "commit", "-q", "-m", message)


def test_f6_the_baseline_is_the_archived_spec_at_the_unit_base_not_at_head(tdd_repo):
    """The unit branch rewrites the archived spec after the base: a scenario restated word for word at the base is
    still unchanged, and one the branch copied into the archived spec is still changed (HB-3)."""
    unit_repo(tdd_repo)
    bench = build_bench(tdd_repo, [], UNIT)
    archived_path = bench.wb.worktree / ARCHIVED_SPEC
    archived_path.write_text(archived().replace("it returns `45.0`", "it returns `0`"))  # head differs from the base
    commit_in_worktree(bench, "the branch edits the archived spec")
    assert found(bench, *reports()) == {KNOWN: (BASE_TEST,)}


def test_f6_a_delta_copied_into_the_archived_spec_after_the_base_does_not_make_a_changed_scenario_unchanged(tdd_repo):
    unit_repo(tdd_repo, known_then="it returns `44.55`")  # the delta changed `Known code`; the base holds `45.0`
    bench = build_bench(tdd_repo, [], UNIT)
    (bench.wb.worktree / ARCHIVED_SPEC).write_text(archived().replace("it returns `45.0`", "it returns `44.55`"))
    commit_in_worktree(bench, "the branch copies its delta into the archived spec")
    assert found(bench, *reports()) == {}
