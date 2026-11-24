"""L4-GAT-007, L4-GAT-008, L4-GAT-009 and L4-IMP-117 (SCN-GAT-12, 14..17 and SCN-IMP-628..632): the pure parts of a
targeted red check. No work tree is run, no git."""

import shlex
from pathlib import Path

import pytest

from l4.config.schema import L4Config
from l4.gates.junit import TestCase, TestReport
from l4.implementer.red_check import Full, Targeted, choose, targeted_command, unusable, with_targeted
from l4.implementer.stubs import RedScope
from l4.verifier.support_base import is_support_source

CFG = L4Config()
TEMPLATE = "npx vitest run --reporter=junit --outputFile=.l4-out/junit.xml {files}"
LEDGER = ".l4/ledger/r-1.jsonl"
NOTHING = RedScope((), (), ())


def report(**status: str) -> TestReport:
    return TestReport({i: TestCase(i, s) for i, s in status.items()})  # type: ignore[arg-type]


# --- targeted_command (SCN-GAT-12) ----------------------------------------------------------------------------------


def test_scn_gat_12_the_files_are_separate_words_in_order_and_the_rest_is_unchanged():
    command = targeted_command(TEMPLATE, ["test/b.test.ts", "test/a dir/a.test.ts"])
    argv = shlex.split(command)
    assert argv[:-2] == ["npx", "vitest", "run", "--reporter=junit", "--outputFile=.l4-out/junit.xml"]
    assert argv[-2:] == ["test/a dir/a.test.ts", "test/b.test.ts"]  # sorted by their text, one item each


def test_scn_gat_12_a_quote_a_dollar_and_a_glob_are_one_argument_each():
    odd = ["test/it's $HOME.test.ts", 'test/"q" *.test.ts']
    argv = shlex.split(targeted_command("run -k 'slow or fast' {files}", odd))
    assert argv == ["run", "-k", "slow or fast", *sorted(odd)]


# --- with_targeted (SCN-GAT-14) -------------------------------------------------------------------------------------


def test_scn_gat_14_the_report_is_the_baseline_with_the_new_failing_tests_added():
    base = TestReport({f"old{i}": TestCase(f"old{i}", "passed") for i in range(300)} | {
        "bad1": TestCase("bad1", "failed"), "bad2": TestCase("bad2", "failed")
    })  # fmt: skip
    base.collection_errors.append("m")  # not possible today, but the overlay must hold none
    run = report(new1="failed", new2="failed", new3="error")
    held = with_targeted(base, run)
    assert held.total == 305 and held.collection_errors == [] and held.collection_details == {}
    assert all(held.tests[f"old{i}"].status == "passed" for i in range(300))
    assert held.tests["bad1"].status == "failed" and held.tests["new3"].status == "error"
    assert base.total == 302 and base.collection_errors == ["m"]  # the base object is unchanged
    assert set(run.tests) == {"new1", "new2", "new3"}


# --- unusable (SCN-GAT-15..17) --------------------------------------------------------------------------------------

FILES = ["test/a.test.ts", "test/b.test.ts"]
PATHS = ["test/old.test.ts", "src/a.ts", *FILES]
BASE = report(**{"test/old.test.ts::old": "passed"})
GOOD = TestReport({
    "test/a.test.ts::one": TestCase("test/a.test.ts::one", "failed"),
    "test/b.test.ts::two": TestCase("test/b.test.ts::two", "error"),
})  # fmt: skip


def test_a_complete_run_is_usable():
    assert unusable(BASE, GOOD, FILES, PATHS) is None


def plus(test_id: str, status: str) -> TestReport:
    return TestReport({**GOOD.tests, test_id: TestCase(test_id, status)})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("why", "run"),
    [
        ("no_report", None),
        ("collection_errors", TestReport(GOOD.tests, ["test/a.test.ts"])),
        ("existing_tests_ran", plus("test/old.test.ts::old", "failed")),
        ("file_without_tests", TestReport({"test/a.test.ts::one": TestCase("test/a.test.ts::one", "failed")})),
        ("id_without_file", plus("elsewhere.test.ts::x", "failed")),
        ("new_test_not_failing", plus("test/a.test.ts::p", "passed")),
        ("new_test_not_failing", plus("test/b.test.ts::s", "skipped")),
    ],
)
def test_scn_gat_15_to_17_each_unusable_word(why: str, run: TestReport | None):
    found = unusable(BASE, run, FILES, PATHS, reason="no report written")
    assert found is not None and found[0] == why
    assert len(found[1]) <= 300


def test_the_order_of_the_checks_gives_the_first_word():
    both = TestReport(
        {"test/old.test.ts::old": TestCase("test/old.test.ts::old", "failed")}, collection_errors=["test/a.test.ts"]
    )
    assert unusable(BASE, both, FILES, PATHS)[0] == "collection_errors"
    old_and_passing = report(**{"test/old.test.ts::old": "passed", "test/a.test.ts::x": "passed"})
    assert unusable(BASE, old_and_passing, FILES, PATHS)[0] == "existing_tests_ran"
    nothing_for_b = report(**{"test/a.test.ts::x": "passed"})
    assert unusable(BASE, nothing_for_b, FILES, PATHS)[0] == "file_without_tests"  # before the status check


def test_the_detail_names_at_most_five_ids_and_is_at_most_300_characters():
    many = report(**{f"test/old.test.ts::{'x' * 80}{i}": "failed" for i in range(9)})
    base = TestReport({i: TestCase(i, "passed") for i in many.tests})
    why, detail = unusable(base, many, FILES, PATHS)
    assert why == "existing_tests_ran" and len(detail) <= 300 and detail.count("test/old.test.ts::") <= 5


def test_the_no_report_detail_is_the_gates_reason():
    assert unusable(BASE, None, FILES, PATHS, reason="report missing: .l4-out/junit.xml") == (
        "no_report", "report missing: .l4-out/junit.xml"
    )  # fmt: skip


def test_an_id_is_placed_in_a_listed_file_for_a_typescript_id_a_dotted_python_module_and_no_owner():
    py_files, py_paths = ["tests/test_pricing.py"], ["tests/test_pricing.py", "tests/test_other.py", "src/a.py"]
    ok = report(**{"tests.test_pricing::test_total": "failed", "tests.test_pricing.TestX::test_y": "error"})
    assert unusable(report(), ok, py_files, py_paths) is None
    stray = report(**{"tests.test_pricing::test_total": "failed", "tests.test_missing::test_z": "failed"})
    assert unusable(report(), stray, py_files, py_paths)[0] == "id_without_file"
    ts = report(**{"test/a.test.ts::total of two prices": "failed", "test/b.test.ts::x": "failed"})
    assert unusable(report(), ts, FILES, PATHS) is None


# --- choose (SCN-IMP-628..632) --------------------------------------------------------------------------------------


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_pricing.py").write_text("def test_total():\n    assert False\n")
    (tmp_path / "tests" / "test_utils.py").write_text("def helper():\n    return 1\n")
    return tmp_path


def pick(tree: Path, changed: dict[str, bool], **over):
    args = {
        "switched": False, "named": False, "stale": False, "base_report": BASE, "scope": NOTHING, "ledger_rel": LEDGER,
        **over,
    }  # fmt: skip
    return choose(CFG, tree, changed=changed, **args)


def test_scn_imp_626_an_eligible_step_gives_its_sorted_files(tree: Path):
    found = pick(tree, {"test/pricing.test.ts": False, "test/cart.test.ts": False})
    assert found == Targeted(("test/cart.test.ts", "test/pricing.test.ts"))


def test_the_runs_ledger_and_tool_caches_are_not_changed_paths(tree: Path):
    changed = {
        "test/cart.test.ts": False, LEDGER: True, "tests/__pycache__/x.cpython-312.pyc": False,
        "tests/.pytest_cache/v": False, "a/b.pyc": False,
    }  # fmt: skip
    assert pick(tree, changed) == Targeted(("test/cart.test.ts",))


@pytest.mark.parametrize(
    ("over", "why"),
    [
        ({"switched": True}, "unit_switched"),
        ({"named": True}, "named_tests"),
        ({"stale": True}, "stale_tests"),
        ({"base_report": TestReport({}, ["m"])}, "base_collection_errors"),
        ({"scope": RedScope(("src/a.py",), ("src/a.py:f",), ())}, "stubs"),
        ({"scope": RedScope((), (), ("src/a.ts: a production file other than Python source",))}, "restored"),
    ],
)
def test_scn_imp_629_630_each_rule_of_the_step_sends_it_to_the_whole_suite(tree: Path, over, why):
    found = pick(tree, {"test/new.test.ts": False}, **over)
    assert isinstance(found, Full) and found.why == why


def test_the_rules_are_tested_in_order(tree: Path):
    found = pick(
        tree, {"test/old.test.ts": True}, scope=RedScope(("src/a.py",), (), ("x",)), named=True, stale=True,
    )  # fmt: skip
    assert found.why == "named_tests"
    assert pick(tree, {"test/old.test.ts": True}, scope=RedScope(("src/a.py",), (), ("x",))).why == "stubs"
    assert pick(tree, {"test/old.test.ts": True}, scope=RedScope((), (), ("x",))).why == "restored"
    assert pick(tree, {"test/old.test.ts": True, "-x.test.ts": False}).why == "existing_file_changed"
    assert pick(tree, {"test/data.ts": False, "-x.test.ts": False}).why == "not_a_test_module"
    assert pick(tree, {"test/new.test.ts": False}, switched=True, named=True).why == "unit_switched"


def test_scn_imp_628_an_existing_file_changed_or_deleted_runs_the_whole_suite(tree: Path):
    assert pick(tree, {"test/new.test.ts": False, "test/old.test.ts": True}).why == "existing_file_changed"
    assert pick(tree, {"test/old.test.ts": True}).why == "existing_file_changed"  # a deleted file existed too


@pytest.mark.parametrize("path", ["test/helpers/db.ts", "tests/conftest.py", "test/data.ts", "tests/test_utils.py"])
def test_scn_imp_629_a_support_file_or_a_helper_is_no_test_module(tree: Path, path: str):
    found = pick(tree, {"test/new.test.ts": False, path: False})
    assert isinstance(found, Full) and found.why == "not_a_test_module" and path in found.detail


def test_a_changed_path_outside_the_test_globs_is_no_test_module(tree: Path):
    assert pick(tree, {"src/new.test.txt": False, "docs/a.md": False}).why == "not_a_test_module"


def test_scn_imp_631_no_file_is_left_when_only_the_ledger_changed(tree: Path):
    assert pick(tree, {LEDGER: True}).why == "no_test_file"
    assert pick(tree, {}).why == "no_test_file"


def test_scn_imp_631_at_most_50_files_and_8000_bytes_of_paths(tree: Path):
    fifty = {f"test/f{i:02}.test.ts": False for i in range(50)}
    assert isinstance(pick(tree, fifty), Targeted)
    assert pick(tree, {**fifty, "test/f50.test.ts": False}).why == "too_many_files"
    long = {f"test/{c}{'x' * 1586}.test.ts": False for c in "abcde"}  # 5 x 1,600 bytes: exactly 8,000
    assert sum(map(len, long)) == 8000 and isinstance(pick(tree, long), Targeted)
    longer = {**long, "test/a.test.ts": False}  # 8,014 bytes
    assert pick(tree, longer).why == "too_many_files"
    one_more = {f"test/{c}{'x' * (1587 if c == 'a' else 1586)}.test.ts": False for c in "abcde"}  # 8,001 bytes
    assert sum(map(len, one_more)) == 8001 and pick(tree, one_more).why == "too_many_files"


def test_scn_imp_631_a_path_that_starts_with_a_dash_or_holds_a_control_character_is_odd(tree: Path):
    for path in ("-x.test.ts", "test/a\x01.test.ts", "test/a\n.test.ts", "test/a\x7f.test.ts"):
        found = pick(tree, {path: False})
        assert found.why == "odd_path", path


def test_scn_imp_632_a_python_test_module_with_no_stub_is_eligible_and_one_with_a_stub_is_not(tree: Path):
    assert pick(tree, {"tests/test_pricing.py": False}) == Targeted(("tests/test_pricing.py",))
    stub = RedScope(("src/pricing.py",), ("src/pricing.py:apply",), ())
    assert pick(tree, {"tests/test_pricing.py": False, "src/pricing.py": True}, scope=stub).why == "stubs"


def test_a_python_file_with_no_test_function_or_no_readable_source_is_a_support_file(tree: Path):
    assert pick(tree, {"tests/test_utils.py": False}).why == "not_a_test_module"  # defines no test
    assert pick(tree, {"tests/test_gone.py": False}).why == "not_a_test_module"  # not in the work tree
    (tree / "tests" / "test_bad.py").write_text("def test_x(:\n")
    assert pick(tree, {"tests/test_bad.py": False}).why == "not_a_test_module"  # does not parse
    (tree / "tests" / "test_bin.py").write_bytes(b"\xff\xfe def test_x(): pass")
    assert pick(tree, {"tests/test_bin.py": False}).why == "not_a_test_module"


def test_the_detail_names_at_most_five_paths_and_is_at_most_300_characters(tree: Path):
    found = pick(tree, {f"test/data{i}.ts": False for i in range(9)})
    assert found.why == "not_a_test_module" and len(found.detail) <= 300 and found.detail.count("test/data") <= 5


# --- the verifier's rule, taken for a work-tree file ----------------------------------------------------------------


def test_is_support_source_is_the_rule_of_is_support_file():
    assert is_support_source(CFG, "tests/conftest.py", "def test_x():\n    pass\n")  # a support glob
    assert is_support_source(CFG, "tests/test_a.py", "def helper():\n    pass\n")
    assert is_support_source(CFG, "tests/test_a.py", None)
    assert is_support_source(CFG, "tests/test_a.py", "def test_x(:\n")
    assert not is_support_source(CFG, "tests/test_a.py", "def test_x():\n    pass\n")
    assert is_support_source(CFG, "test/data.ts", None) and not is_support_source(CFG, "test/a.test.ts", None)
