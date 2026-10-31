"""own-test-repair (L4-IMP-091, first paragraph): which failing tests of a round are the unit's own new tests that a
repair chore may touch. The rule reads git, so these tests use a real worktree."""

from l4.implementer.discrimination import unit_base
from l4.vcs.trailers import CommitTrailers
from l4.verifier.repairs import RepairTest, family_of, repair_candidates

TEST_A = "import pytest\n\n\ndef test_x():\n    assert 1 == 1\n\n\ndef test_y():\n    assert 2 == 2\n"
OTHER = {"gate": "e2e", "kind": "other", "message": "Error: value must be a string", "location": "e2e/test_a.py"}


def failing(
    *ids: str,
    kind: str = "other",
    gate: str = "e2e",
    location: str | None = "e2e/test_a.py",
    frames: str | None = "",
    message: str | None = None,
) -> dict[str, dict[str, str]]:
    """Failure records as the round stores them; `location`: the deepest in-repository frame (None: not recorded),
    `frames`: every repository file of the traceback, one per line (default: the location alone; None: not recorded)."""
    record = {k: v for k, v in OTHER.items() if k not in ("location", "message")}
    record["message"] = message or OTHER["message"]
    if location:
        record["location"] = location
    if frames is not None and (frames or location):
        record["frames"] = frames or str(location)
    return {i: {**record, "kind": kind, "gate": gate} for i in ids}


def write(bench, files: dict[str, str]) -> None:
    for name, text in files.items():
        path = bench.wb.worktree / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


def red_commit(bench, files: dict[str, str], *, tdd: str = "red", unit: str | None = None) -> str:
    write(bench, files)
    if unit is None:
        return bench.wb.commit("red", task="1.1", attempt=1, phase="red", tdd=tdd)
    bench.wb.git.run("add", "-A")
    trailers = CommitTrailers(
        unit=unit, run_id="r-20261003T1312Z-7f3a", iteration=1, phase="implementing", task="1.1", tdd=tdd
    )
    return bench.wb.git.commit("red of another unit", trailers)


def person_commit(bench, files: dict[str, str]) -> None:
    write(bench, files)
    bench.wb.git.run("add", "-A")
    bench.wb.git.run("commit", "-q", "-m", "a person's commit")


def test_a_test_added_by_a_red_commit_of_the_unit_with_a_non_assertion_failure_qualifies(make_bench):  # SCN-IMP-450
    bench = make_bench([])
    red_commit(bench, {"e2e/test_a.py": TEST_A})
    found = repair_candidates(bench.wb, failing("e2e.test_a::test_x"))
    assert found == {
        "e2e.test_a::test_x": RepairTest(
            "e2e.test_a::test_x", "e2e/test_a.py", "test_x", "e2e", "other", OTHER["message"]
        )
    }


def test_a_parametrised_id_and_a_class_method_resolve_to_the_function(make_bench):
    bench = make_bench([])
    body = "class TestCart:\n    def test_total(self):\n        assert True\n\n\ndef test_p(x=1):\n    assert x\n"
    red_commit(bench, {"e2e/test_a.py": body})
    got = repair_candidates(bench.wb, failing("e2e.test_a.TestCart::test_total", "e2e.test_a::test_p[1, 2]"))
    assert {i: t.name for i, t in got.items()} == {
        "e2e.test_a.TestCart::test_total": "TestCart.test_total",
        "e2e.test_a::test_p[1, 2]": "test_p",
    }


def test_an_assertion_a_not_implemented_and_a_collection_failure_never_qualify(make_bench):  # SCN-IMP-455
    bench = make_bench([])
    red_commit(bench, {"e2e/test_a.py": TEST_A})
    for kind in ("assertion", "not_implemented", "collection"):
        assert repair_candidates(bench.wb, failing("e2e.test_a::test_x", kind=kind)) == {}
    assert "e2e.test_a::test_x" in repair_candidates(bench.wb, failing("e2e.test_a::test_x", kind="error"))


def test_a_test_that_exists_at_the_unit_base_never_qualifies(make_bench):  # SCN-IMP-455
    bench = make_bench([])
    base = unit_base(bench.wb)
    assert base is not None and bench.wb.git.run("cat-file", "-e", f"{base}:tests/test_pricing.py").returncode == 0
    assert repair_candidates(bench.wb, failing("tests.test_pricing::test_total", gate="test")) == {}
    red_commit(
        bench,
        {
            "tests/test_pricing.py": (bench.wb.worktree / "tests/test_pricing.py").read_text()
            + "\n\ndef test_new():\n    pass\n"
        },
    )
    assert (
        repair_candidates(bench.wb, failing("tests.test_pricing::test_new", gate="test")) == {}
    )  # the file is not new


def test_a_test_first_added_by_a_person_never_qualifies(make_bench):  # SCN-IMP-455
    bench = make_bench([])
    person_commit(bench, {"e2e/test_a.py": TEST_A})
    assert repair_candidates(bench.wb, failing("e2e.test_a::test_x")) == {}


def test_a_test_a_person_appended_to_a_red_file_never_qualifies(make_bench):
    bench = make_bench([])
    red_commit(bench, {"e2e/test_a.py": "def test_x():\n    assert True\n"})
    person_commit(bench, {"e2e/test_a.py": "def test_x():\n    assert True\n\n\ndef test_y():\n    assert True\n"})
    got = repair_candidates(bench.wb, failing("e2e.test_a::test_x", "e2e.test_a::test_y"))
    assert list(got) == ["e2e.test_a::test_x"]


def test_only_a_red_commit_counts_not_a_green_or_exempt_one(make_bench):
    bench = make_bench([])
    red_commit(bench, {"e2e/test_a.py": TEST_A}, tdd="exempt")
    assert repair_candidates(bench.wb, failing("e2e.test_a::test_x")) == {}


def test_a_red_commit_of_another_unit_does_not_count(make_bench):
    bench = make_bench([])
    red_commit(bench, {"e2e/test_a.py": TEST_A}, unit="openspec:other-unit")
    assert repair_candidates(bench.wb, failing("e2e.test_a::test_x")) == {}


def test_a_support_file_never_qualifies(make_bench):  # the support-glob file `conftest.py`
    bench = make_bench([])
    red_commit(bench, {"tests/conftest.py": "def test_x():\n    assert True\n", "e2e/fixtures/test_f.py": TEST_A})
    assert repair_candidates(bench.wb, failing("tests.conftest::test_x", "e2e.fixtures.test_f::test_x")) == {}


def test_a_typescript_or_unknown_test_never_qualifies(make_bench):  # SCN-IMP-456
    bench = make_bench([])
    red_commit(bench, {"e2e/cart.spec.ts": "test('x', async () => {});\n"})
    assert (
        repair_candidates(bench.wb, failing("e2e/cart.spec.ts::x", "e2e.cart.spec::x", "nowhere.at_all::test_x")) == {}
    )


def test_a_name_the_file_does_not_define_or_defines_twice_never_qualifies(make_bench):
    bench = make_bench([])
    red_commit(bench, {"e2e/test_a.py": "def test_x():\n    assert True\n\n\ndef test_x():\n    assert True\n"})
    assert repair_candidates(bench.wb, failing("e2e.test_a::test_x", "e2e.test_a::test_missing")) == {}


def test_a_link_in_the_path_or_a_file_that_is_not_regular_never_qualifies(make_bench):
    bench = make_bench([])
    red_commit(bench, {"e2e/test_a.py": TEST_A})
    assert repair_candidates(bench.wb, failing("e2e.test_a::test_x")) != {}
    (bench.wb.worktree / "e2e/test_a.py").unlink()
    (bench.wb.worktree / "e2e/test_a.py").symlink_to("/etc/hostname")
    assert repair_candidates(bench.wb, failing("e2e.test_a::test_x")) == {}


def test_the_unit_base_of_a_fix_unit_is_its_parents_base(make_bench):
    """A fix unit runs on its parent's branch (D1): the merge base with the base branch is the parent's, whatever the
    fix unit adds, so a test first added by the parent's red commit is absent at it."""
    bench = make_bench([])
    before = unit_base(bench.wb)
    red_commit(bench, {"e2e/test_a.py": TEST_A})
    fix = bench.wb.worktree / "openspec/changes/add-discount-codes-fix-1/.l4/fix.json"
    write(bench, {"openspec/changes/add-discount-codes-fix-1/.l4/fix.json": "{}"})
    assert fix.is_file() and unit_base(bench.wb) == before


def test_the_family_of_a_unit_is_the_unit_and_its_fix_units():
    assert family_of("openspec:add-x") == ("openspec:add-x", "add-x")
    assert family_of("openspec:add-x-fix-2") == ("openspec:add-x", "add-x")
    assert family_of("kiro:login-fix-1") == ("kiro:login", "login")


def test_a_failure_raised_in_a_production_module_never_qualifies(make_bench):  # the trigger is the product's to control
    bench = make_bench([])
    red_commit(bench, {"e2e/test_a.py": TEST_A})
    assert repair_candidates(bench.wb, failing("e2e.test_a::test_x", location="src/app/x.py")) == {}
    assert repair_candidates(bench.wb, failing("e2e.test_a::test_x", location="src/pytdd/pricing.py")) == {}


def test_a_failure_with_no_known_location_never_qualifies(make_bench):
    bench = make_bench([])
    red_commit(bench, {"e2e/test_a.py": TEST_A})
    assert repair_candidates(bench.wb, failing("e2e.test_a::test_x", location=None)) == {}


def test_a_failure_raised_in_the_test_file_or_in_another_test_or_support_file_qualifies(make_bench):
    bench = make_bench([])
    red_commit(bench, {"e2e/test_a.py": TEST_A})
    for where in ("e2e/test_a.py", "e2e/test_other.py", "tests/helpers/shared.py", "e2e/conftest.py"):
        got = repair_candidates(bench.wb, failing("e2e.test_a::test_x", location=where))
        assert list(got) == ["e2e.test_a::test_x"], where


# --- a test a person edited is not the red step's alone -------------------------------------------------------------


def test_a_test_a_person_changed_after_the_red_commit_never_qualifies(make_bench):
    bench = make_bench([])
    red_commit(bench, {"e2e/test_a.py": TEST_A})
    person_commit(bench, {"e2e/test_a.py": TEST_A.replace("assert 1 == 1", "assert 1 == 2")})
    got = repair_candidates(bench.wb, failing("e2e.test_a::test_x", "e2e.test_a::test_y"))
    assert list(got) == ["e2e.test_a::test_y"]  # the other test of the file was not touched


def test_a_helper_a_person_changed_counts_as_a_change_of_the_test(make_bench):
    bench = make_bench([])
    helper = "def helper():\n    return 1\n\n\ndef test_x():\n    assert helper() == 1\n"
    red_commit(bench, {"e2e/test_a.py": helper})
    person_commit(bench, {"e2e/test_a.py": helper.replace("return 1", "return 2")})
    assert repair_candidates(bench.wb, failing("e2e.test_a::test_x")) == {}


def test_a_file_a_person_deleted_and_added_again_never_qualifies(make_bench):
    bench = make_bench([])
    red_commit(bench, {"e2e/test_a.py": TEST_A})
    (bench.wb.worktree / "e2e/test_a.py").unlink()
    bench.wb.git.run("add", "-A")
    bench.wb.git.run("commit", "-q", "-m", "a person deletes it")
    person_commit(bench, {"e2e/test_a.py": TEST_A})
    assert repair_candidates(bench.wb, failing("e2e.test_a::test_x")) == {}


def test_a_later_harness_commit_that_keeps_the_test_as_it_is_does_not_disqualify_it(make_bench):
    bench = make_bench([])
    red_commit(bench, {"e2e/test_a.py": TEST_A})
    red_commit(bench, {"src/app_more.py": "x = 1\n"}, tdd="green")
    person_commit(bench, {"README.md": "a person's note\n"})
    assert list(repair_candidates(bench.wb, failing("e2e.test_a::test_x"))) == ["e2e.test_a::test_x"]


# --- second pass: where the failure was raised, and what it says -----------------------------------------------------


def test_a_traceback_that_passes_through_a_production_file_never_qualifies(make_bench):
    bench = make_bench([])
    red_commit(bench, {"e2e/test_a.py": TEST_A})
    through = "e2e/test_a.py\nsrc/app/x.py"  # the deepest frame is the test's, an earlier one is the product's
    assert repair_candidates(bench.wb, failing("e2e.test_a::test_x", frames=through)) == {}
    assert repair_candidates(bench.wb, failing("e2e.test_a::test_x", frames=None)) == {}  # not recorded


def test_product_code_that_hides_its_frames_disqualifies_every_candidate(make_bench):
    bench = make_bench([])
    red_commit(bench, {"e2e/test_a.py": TEST_A})
    assert list(repair_candidates(bench.wb, failing("e2e.test_a::test_x"))) == ["e2e.test_a::test_x"]
    red_commit(
        bench, {"src/app/calc.py": "def compute(n):\n    __tracebackhide__ = True\n    return {}['v']\n"}, tdd="green"
    )
    assert repair_candidates(bench.wb, failing("e2e.test_a::test_x")) == {}


def test_a_traceback_hiding_mark_in_a_test_file_does_not_disqualify(make_bench):
    bench = make_bench([])
    red_commit(bench, {"e2e/test_a.py": TEST_A, "e2e/helpers_a.py": "def check():\n    __tracebackhide__ = True\n"})
    assert list(repair_candidates(bench.wb, failing("e2e.test_a::test_x"))) == ["e2e.test_a::test_x"]


USAGE_ERRORS = (
    "TypeError: value must be a string or regular expression",
    "Error: url must be a string, a regular expression or a function",
    "ValueError: unknown state 'visble'",
    "TypeError: expect() got an unexpected keyword argument 'exact'",
    "AttributeError: 'Page' object has no attribute 'wait_for_urll'",
    "NameError: name 'pagee' is not defined",
)
NOT_USAGE = (
    "TimeoutError: Page.click: Timeout 30000ms exceeded.",
    "playwright._impl._errors.TimeoutError: Locator.click: Timeout 5000ms exceeded.",
    "Error: Locator expected to be visible",
    "Error: strict mode violation: get_by_role('button') resolved to 2 elements",
    "Error: Timeout 5000ms exceeded while waiting for locator",
    "Error: net::ERR_CONNECTION_REFUSED at http://localhost:3000/",
    "KeyError: 'value'",
    "Error: element is not found",
)


def test_a_browser_test_qualifies_for_a_usage_error_of_the_library_and_not_for_a_timeout_or_a_missing_element(
    make_bench,
):
    bench = make_bench([])
    red_commit(bench, {"e2e/test_a.py": TEST_A})
    for message in USAGE_ERRORS:
        got = repair_candidates(bench.wb, failing("e2e.test_a::test_x", message=message))
        assert list(got) == ["e2e.test_a::test_x"], message
    for message in NOT_USAGE:
        assert repair_candidates(bench.wb, failing("e2e.test_a::test_x", message=message)) == {}, message


def test_the_message_rule_is_for_the_browser_gate_only(make_bench):
    bench = make_bench([])
    red_commit(bench, {"tests/test_flow.py": "def test_x():\n    assert int('3', base='x')\n"})
    got = repair_candidates(
        bench.wb,
        failing("tests.test_flow::test_x", gate="test", location="tests/test_flow.py", message="KeyError: 'k'"),
    )
    assert list(got) == ["tests.test_flow::test_x"]  # a unit test's traceback is read for its files, not its words
