"""own-test-repair (L4-IMP-091, first paragraph): which failing tests of a round are the unit's own new tests that a
repair chore may touch. The rule reads git, so these tests use a real worktree."""

from l4.implementer.discrimination import unit_base
from l4.vcs.trailers import CommitTrailers
from l4.verifier.repairs import RepairTest, family_of, repair_candidates

TEST_A = "import pytest\n\n\ndef test_x():\n    assert 1 == 1\n\n\ndef test_y():\n    assert 2 == 2\n"
OTHER = {"gate": "e2e", "kind": "other", "message": "Error: value must be a string"}


def failing(*ids: str, kind: str = "other", gate: str = "e2e") -> dict[str, dict[str, str]]:
    return {i: {**OTHER, "kind": kind, "gate": gate} for i in ids}


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
