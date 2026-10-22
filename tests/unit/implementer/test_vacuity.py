"""Run (b): the zero-value variants of the red stubs, in place, restored byte-exact (L4-IMP-002, D7)."""

import hashlib
from pathlib import Path

import pytest

from l4.implementer.discrimination import (
    Vacuity,
    imported_modules,
    vacuity_check,
    zero_values_in_place,
    zeroed_run,
)
from l4.implementer.tdd import run_setup

from .conftest import Bench

STUB = "def apply_discount(amount: float, code: str) -> float:\n    raise NotImplementedError\n"
UNTYPED_STUB = "def apply_discount(amount, code):\n    raise NotImplementedError\n"  # zero value: None
C1, C2 = "C-aaaaaaaa", "C-bbbbbbbb"
TESTS = f"""import pytest
from pytdd.pricing import apply_discount


@pytest.mark.l4("{C1}")
def test_call_only():
    apply_discount(50.0, "SAVE10")


@pytest.mark.l4("{C2}")
def test_zero_is_the_answer():
    assert apply_discount(0.0, "SAVE10") == 0.0


@pytest.mark.l4("{C2}")
def test_real_answer():
    assert apply_discount(50.0, "SAVE10") == 45.0
"""


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def staged(make_bench) -> tuple[Bench, Path]:
    bench = make_bench([])
    wb = bench.wb
    pricing = wb.worktree / "src/pytdd/pricing.py"
    pricing.write_text(pricing.read_text() + "\n\n" + STUB)
    (wb.worktree / "tests/test_red.py").write_text(TESTS)
    run_setup(wb)
    return bench, pricing


def test_call_only_test_is_vacuous_and_zero_edge_case_next_to_sibling_is_fine(staged: tuple[Bench, Path]):
    bench, pricing = staged
    before = sha(pricing)
    tracing = {
        C1: ["tests.test_red::test_call_only"],
        C2: ["tests.test_red::test_zero_is_the_answer", "tests.test_red::test_real_answer"],
    }
    result = vacuity_check(bench.wb, ["src/pytdd/pricing.py"], tracing)
    assert set(result.vacuous) == {C1} and result.vacuous[C1] == ("tests.test_red::test_call_only",)
    assert result.proofs == {
        C2: ("tests.test_red::test_real_answer",)
    }  # the zero-answer test passes, and is not flagged
    assert result.message.startswith("vacuous: C-aaaaaaaa") and "test_call_only" in result.message
    assert sha(pricing) == before  # restored byte for byte


PARTIAL_STUB = (
    "def pick_priority(on_hand: int, reorder_point: int) -> str:\n    if on_hand < 0 or reorder_point < 0:\n"
    '        raise ValueError("negative")\n    raise NotImplementedError\n'
)  # an earlier task's guards, then the bare raise of the task under test


def test_red_tests_for_a_guarded_partial_stub_pass_the_check_and_a_type_only_test_is_still_vacuous(make_bench):
    bench = make_bench([])
    wb = bench.wb
    pricing = wb.worktree / "src/pytdd/pricing.py"
    pricing.write_text(pricing.read_text() + "\n\n" + PARTIAL_STUB)
    (wb.worktree / "tests/test_red.py").write_text(
        f'import pytest\nfrom pytdd.pricing import pick_priority\n\n\n@pytest.mark.l4("{C1}")\n'
        "def test_type_only():\n    assert isinstance(pick_priority(0, 5), str)\n\n\n"
        f'@pytest.mark.l4("{C2}")\ndef test_urgent():\n    assert pick_priority(0, 5) == "urgent"\n'
    )
    run_setup(wb)
    tracing = {C1: ["tests.test_red::test_type_only"], C2: ["tests.test_red::test_urgent"]}
    result = vacuity_check(wb, ["src/pytdd/pricing.py"], tracing)
    assert set(result.vacuous) == {C1} and set(result.proofs) == {C2}


def test_a_criterion_whose_only_test_has_the_zero_answer_is_vacuous(staged: tuple[Bench, Path]):
    bench, _ = staged
    result = vacuity_check(bench.wb, ["src/pytdd/pricing.py"], {C2: ["tests.test_red::test_zero_is_the_answer"]})
    assert set(result.vacuous) == {C2}


def test_the_variant_really_answers_the_zero_value_inside_the_block_only(staged: tuple[Bench, Path]):
    bench, pricing = staged
    original = pricing.read_text()
    with zero_values_in_place(bench.wb, ["src/pytdd/pricing.py", "src/missing.py"], public=False) as varied:
        assert varied == ["src/pytdd/pricing.py"] and "return 0.0" in pricing.read_text()
    assert pricing.read_text() == original


def test_an_error_inside_the_block_still_restores_the_file(staged: tuple[Bench, Path]):
    bench, pricing = staged
    original = pricing.read_bytes()
    with pytest.raises(KeyError), zero_values_in_place(bench.wb, ["src/pytdd/pricing.py"], public=True):
        raise KeyError("boom")
    assert pricing.read_bytes() == original


def test_nothing_to_vary_runs_no_gate(staged: tuple[Bench, Path]):
    bench, _ = staged
    assert zeroed_run(bench.wb, "test-zero", [], public=False) is None
    assert vacuity_check(bench.wb, [], {}).message == ""


def test_stale_bytecode_of_the_original_is_not_served_to_the_variant(staged: tuple[Bench, Path]):
    bench, pricing = staged
    cache = pricing.parent / "__pycache__"
    cache.mkdir(exist_ok=True)
    (cache / "pricing.cpython-312.pyc").write_bytes(b"stale")
    with zero_values_in_place(bench.wb, ["src/pytdd/pricing.py"], public=False):
        assert not list(cache.glob("pricing.*.pyc"))


def test_an_error_raised_by_the_zero_value_is_not_an_assertion(make_bench):
    """`round(None, 2)` and `1 / 0.0` blow up on the zero value without the test ever checking the answer."""
    bench = make_bench([])
    wb = bench.wb
    pricing = wb.worktree / "src/pytdd/pricing.py"
    pricing.write_text(pricing.read_text() + "\n\n" + UNTYPED_STUB)
    (wb.worktree / "tests/test_red.py").write_text(
        f'import pytest\nfrom pytdd.pricing import apply_discount\n\n\n@pytest.mark.l4("{C1}")\n'
        'def test_round_only():\n    round(apply_discount(50.0, "SAVE10"), 2)\n\n\n'
        f'@pytest.mark.l4("{C2}")\ndef test_assertion():\n    assert apply_discount(50.0, "SAVE10") == 45.0\n'
    )
    run_setup(wb)
    result = vacuity_check(
        wb,
        ["src/pytdd/pricing.py"],
        {C1: ["tests.test_red::test_round_only"], C2: ["tests.test_red::test_assertion"]},
    )
    assert set(result.vacuous) == {C1} and set(result.proofs) == {C2}
    assert "fail by assertion" in result.message


def test_a_symlinked_directory_never_lets_the_gate_rewrite_a_file_outside_the_worktree(staged, tmp_path: Path):
    bench, _ = staged
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "mod.py"
    target.write_text("def answer() -> int:\n    return 42\n")
    (bench.wb.worktree / "src/linked").symlink_to(outside, target_is_directory=True)
    with zero_values_in_place(bench.wb, ["src/linked/mod.py"], public=True) as varied:
        assert varied == [] and "42" in target.read_text()
    (bench.wb.worktree / "tests/test_link.py").write_text("from linked.mod import answer\n")
    assert imported_modules(bench.wb, ["tests.test_link::test_x"]) == set()


def test_the_vacuous_message_names_the_remedy_for_a_zero_answer_scenario():
    """Live M1.7 step 3 (job 5498): `Cart().item_count() == 0` is the zero value itself, so its criterion's only test
    passes on the stub. Codex read "a sibling that asserts on a real one" three times as a test of another criterion.
    The message names the criterion, a test that did fail on the zero values, and the two-id marker that fixes it."""
    proved, edge = (
        "tests.test_cart::test_item_count_sums_line_item_quantities",
        "tests.test_cart::test_new_cart_is_zero",
    )
    message = Vacuity(proofs={C2: (proved,)}, vacuous={C1: (edge,)}).message
    assert message.startswith(f"vacuous: {C1} (its tests pass or error against the zero-value stubs: {edge})")
    assert "the zero value itself" in message and "assert a real answer in the same test" in message
    assert f'{proved}: @pytest.mark.l4("{C2}", "{C1}")' in message
    assert "sibling" not in message


def test_with_no_proved_test_the_message_still_says_how_to_prove_a_zero_answer():
    message = Vacuity(vacuous={C1: ("tests.test_red::test_zero_is_the_answer",)}).message
    assert "the zero value itself" in message and "assert a real answer in the same test" in message
    assert "@pytest.mark.l4(" not in message


def test_a_run_b_with_no_report_is_inconclusive_not_vacuous(staged: tuple[Bench, Path], monkeypatch):
    """L4-IMP-060: a zero-value run that wrote no report did not run the tests, so no criterion is vacuous."""
    from l4.gates.runner import GateResult
    from l4.implementer.workbench import Workbench

    bench, _ = staged

    def no_report(self, name, command, **kwargs):
        log = self.out_dir / "test-zero.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("")
        return GateResult(name, "fail", "exit code 2", 2, log, None)

    monkeypatch.setattr(Workbench, "run_gate", no_report)
    tracing = {C1: ["tests.test_red::test_call_only"], C2: ["tests.test_red::test_real_answer"]}
    result = vacuity_check(bench.wb, ["src/pytdd/pricing.py"], tracing)
    assert set(result.inconclusive) == {C1, C2} and result.vacuous == {} and result.proofs == {}
    assert "vacuous:" not in result.message and result.message.startswith("inconclusive: ")
    assert "wrote no readable report" in result.inconclusive[C1]


# ---- the zero-answer remedy respects the per-test cap (L4-VER-053, SCN-VER-175 to SCN-VER-177) ----------------------

Z = "C-zzzzzzzz"
FULL, ROOM = "t::full", "t::room"
FULL_IDS = (C1, C2, "C-cccccccc")


def test_the_remedy_never_advises_a_full_test():
    message = Vacuity(proofs={C1: (FULL,)}, vacuous={Z: ("t::zero",)}, traced={FULL: FULL_IDS}, cap=3).message
    assert (
        f", or write a new test that asserts a real answer and tag it with {Z} alone "
        "(every test that failed on the zero values already carries 3 ids)"
    ) in message
    assert "as well" not in message and FULL not in message.split("a new test")[1]


def test_the_remedy_names_a_test_with_room_and_all_its_ids():
    message = Vacuity(
        proofs={C1: (FULL,), C2: (ROOM,)},
        vacuous={Z: ("t::zero",)},
        traced={FULL: FULL_IDS, ROOM: (C1, C2)},
        cap=3,
    ).message
    example = f'{ROOM}: @pytest.mark.l4("{C1}", "{C2}", "{Z}")'
    assert f"tag a test that asserts a real answer with {Z} as well, for example {example}" in message
    assert f"for example {FULL}" not in message


def test_the_remedy_uses_the_gates_form():
    message = Vacuity(
        proofs={C2: (ROOM,)}, vacuous={Z: ("t::zero",)}, traced={ROOM: (C1, C2)}, cap=3, test_command="npx vitest run"
    ).message
    assert f'for example {ROOM}: it("{C1} {C2} {Z}: …")' in message and "@pytest.mark.l4" not in message


def test_a_test_that_already_holds_the_criterion_is_not_advised_and_unknown_ids_default_to_one():
    holds = Vacuity(proofs={C1: (ROOM,)}, vacuous={Z: ("t::zero",)}, traced={ROOM: (C1, Z)}, cap=3).message
    assert "as well" not in holds and "write a new test" in holds
    unknown = Vacuity(proofs={C1: (ROOM,)}, vacuous={Z: ("t::zero",)}).message  # no `traced`: the proof's own id
    assert f'{ROOM}: @pytest.mark.l4("{C1}", "{Z}")' in unknown


def test_tag_example_has_a_form_per_gate():
    from l4.implementer.result import tag_example

    assert tag_example(".venv/bin/python -m pytest -q", [C1, C2]) == f'@pytest.mark.l4("{C1}", "{C2}")'
    assert tag_example("go test ./...", [C1, C2]) == f'it("{C1} {C2}: …")'


def test_vacuity_check_fills_the_ids_the_cap_and_the_gate(staged: tuple[Bench, Path], monkeypatch):
    """The proved tests' ids come from the red gate's report, restricted to the unit's criteria."""
    from types import SimpleNamespace

    from l4.gates.junit import TestCase, TestReport
    from l4.implementer import discrimination

    bench, _ = staged
    known = [c.id for c in bench.wb.provider.criteria(bench.wb.ref)]
    real = TestReport({ROOM: TestCase(ROOM, "failed", criteria=(known[0], "C-99999999"))})
    zero = SimpleNamespace(run=None, own=None, proved=None)
    monkeypatch.setattr(discrimination, "zeroed_run", lambda *a, **k: zero)
    monkeypatch.setattr(
        discrimination.variant, "judge", lambda *a, **k: {known[0]: SimpleNamespace(state="confirmed", tests=(ROOM,))}
    )
    got = vacuity_check(bench.wb, ["src/pytdd/pricing.py"], {known[0]: [ROOM]}, real=real)
    assert got.traced == {ROOM: (known[0],)}  # the id that is not the unit's is left out
    assert (
        got.cap == bench.wb.cfg.verifier.max_criteria_per_test and got.test_command == bench.wb.cfg.gates.test.command
    )


# --- named-tests 3.1: the zero-value run zeroes the stubs HEAD holds with red's own (L4-IMP-084) ---

COPY_STUB = 'def copy_rows(rows):\n    raise NotImplementedError("arrives in a later task")\n'
BOTH_TESTS = (
    "import pytest\n\nfrom pytdd.copy import copy_rows\nfrom pytdd.pricing import apply_discount\n\n\n"
    '@pytest.mark.l4("C-2d3a8daf")\ndef test_known_code():\n    assert copy_rows([1]) == [1]\n'
    '    assert apply_discount(50.0, "SAVE10") == 45.0\n\n\n'
    '@pytest.mark.l4("C-d80f494d")\ndef test_unknown_code():\n'
    '    with pytest.raises(ValueError):\n        apply_discount(50.0, "NOPE")\n'
)


def test_an_earlier_tasks_stub_is_zeroed_although_red_added_its_own(make_bench):  # SCN-IMP-408
    from l4.agents.fake import Step
    from l4.implementer.tdd import run_red
    from l4.specs.base import Task

    from .conftest import STUB as RED_STUB
    from .conftest import result

    bench = make_bench(
        [
            Step(
                writes={"tests/test_both.py": BOTH_TESTS, "src/pytdd/pricing.py": RED_STUB},
                structured=result(
                    "red",
                    tests_added=["tests/test_both.py::test_known_code"],
                    criteria_ids=["C-2d3a8daf", "C-d80f494d"],
                ),
            )
        ]
    )
    (bench.wb.worktree / "src/pytdd/copy.py").write_text(COPY_STUB)
    bench.wb.git.run("add", "src/pytdd/copy.py")
    bench.wb.git.run(
        "-c", "user.name=t", "-c", "user.email=t@x.invalid", "commit", "-q", "-m", "an earlier task's stub"
    )
    out = run_red(bench.wb, Task("1.1", "1.1", "1.1 Add `apply_discount`", False, " ", 0, 3, 3), attempt=1)
    assert out.status == "ok", out.reason
    assert out.criteria["C-2d3a8daf"]["proof"] == "zero_value"
    assert out.criteria["C-2d3a8daf"]["discriminating"] == ["tests.test_both::test_known_code"]
