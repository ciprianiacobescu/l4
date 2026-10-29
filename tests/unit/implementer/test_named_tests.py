"""Which existing tests the reviewed text names (named-tests 1.1; L4-IMP-082, design D1)."""

from l4.gates.junit import TestCase, TestReport
from l4.implementer.named_tests import (
    MAX_NAMED_TESTS,
    NamedTests,
    find_named,
    find_named_other,
    language_of,
    named_tests,
)
from l4.yolo.digest import unit_digest

FILES = {
    "tests/test_registry.py": (
        "def test_registry_lists_all():\n    assert 1\n\n\ndef test_other():\n    assert 1\n\n\n"
        "class TestGuards:\n    def test_read_guard_a(self):\n        assert 1\n\n"
        "    def test_read_guard_b(self):\n        assert 1\n"
    ),
    "tests/test_a.py": "def test_roundtrip():\n    assert 1\n\n\ndef test_x():\n    assert 1\n",
    "tests/test_b.py": "def test_roundtrip():\n    assert 1\n",
}


def named(*texts: str, files=FILES):
    return find_named(texts, files)


def test_a_node_id_names_a_test_and_a_class_and_a_parametrisation_are_read():
    tests, kept = named(
        "update `tests/test_registry.py::test_registry_lists_all[a-b]` and "
        "./tests/test_registry.py::TestGuards::test_read_guard_a, see tests/test_a.py::test_nothing"
    )
    assert tests == (
        ("tests/test_registry.py", "TestGuards.test_read_guard_a"),
        ("tests/test_registry.py", "test_registry_lists_all"),
    )
    assert kept == ()


def test_a_bare_name_defined_in_one_file_names_it():
    tests, kept = named("the guard tests `test_read_guard_a` and test_read_guard_b are rewritten in place.")
    assert tests == (
        ("tests/test_registry.py", "TestGuards.test_read_guard_a"),
        ("tests/test_registry.py", "TestGuards.test_read_guard_b"),
    )
    assert kept == ()


def test_a_bare_class_name_names_its_tests():
    tests, _ = named("rewrite TestGuards in place")
    assert [n for _, n in tests] == ["TestGuards.test_read_guard_a", "TestGuards.test_read_guard_b"]


def test_a_bare_name_in_two_files_names_none_and_is_kept():
    tests, kept = named("keep test_roundtrip as it is")
    assert tests == ()
    assert kept == (("test_roundtrip", "named in 2 test files: write <path>::test_roundtrip"),)


def test_a_token_that_is_no_test_is_ignored():
    tests, kept = named("see tests/test_a.py::helper, test_missing and tests/nope.py::test_x and the tests folder")
    assert (tests, kept) == ((), ())


def test_at_most_five_tests_are_named_and_the_rest_are_kept_in_order():
    files = {"tests/test_many.py": "".join(f"def test_n{i}():\n    assert 1\n\n\n" for i in range(7))}
    text = " ".join(f"tests/test_many.py::test_n{i}" for i in reversed(range(7)))
    tests, kept = named(text, files=files)
    assert MAX_NAMED_TESTS == 5
    assert [n for _, n in tests] == [f"test_n{i}" for i in range(5)]
    assert kept == (
        ("tests/test_many.py::test_n5", "more than 5 existing tests named"),
        ("tests/test_many.py::test_n6", "more than 5 existing tests named"),
    )


def test_ids_have_the_module_and_the_class_in_the_form_names_test_id_reads():
    got = NamedTests("s", (("tests/test_registry.py", "TestGuards.test_read_guard_a"), ("tests/a/test_b.py", "test_c")))
    assert got.ids() == ("tests.test_registry.TestGuards::test_read_guard_a", "tests.a.test_b::test_c")


# --- named_tests: git and the reviewed text ---


def commit(bench, message: str) -> None:
    bench.wb.git.run("add", "-A")
    bench.wb.git.run("-c", "user.name=t", "-c", "user.email=t@x.invalid", "commit", "-q", "-m", message)


def prepare(bench, text: str, *, plan: bool = False, base: bool = False, extra: dict[str, str] | None = None):
    tasks = bench.wb.ref.path / "tasks.md"
    tasks.write_text(tasks.read_text().split("- [ ]")[0] + text)
    for path, body in (extra or {}).items():
        (bench.wb.worktree / path).parent.mkdir(parents=True, exist_ok=True)
        (bench.wb.worktree / path).write_text(body)
    commit(bench, "text and tests")
    if base:
        bench.wb.git.run("update-ref", "refs/remotes/origin/main", "HEAD")
    if plan:
        bench.wb.activated_plan = "p1"
        bench.wb.activated_digest = unit_digest(bench.wb.git, "HEAD", bench.wb.unit_rel)
    return bench.wb.provider.tasks(bench.wb.ref)[0]


def test_a_reviewed_task_text_names_a_test_at_the_base(make_bench):
    bench = make_bench([])
    task = prepare(
        bench,
        "- [ ] 1.1 Change `tests/test_pricing.py::test_total_of_nothing_is_zero` and test_total_adds_prices\n",
        plan=True,
    )
    got = named_tests(bench.wb, task, bench.wb.head())
    assert got.source == f"plan:p1@{bench.wb.activated_digest}"
    assert got.tests == (
        ("tests/test_pricing.py", "test_total_adds_prices"),
        ("tests/test_pricing.py", "test_total_of_nothing_is_zero"),
    )
    assert got.ids()[0] == "tests.test_pricing::test_total_adds_prices"


def test_a_bare_name_in_two_files_is_kept_with_its_text(make_bench):
    both = "def test_roundtrip():\n    assert 1\n"
    bench = make_bench([])
    task = prepare(
        bench, "- [ ] 1.1 Keep test_roundtrip\n", plan=True, extra={"tests/test_a.py": both, "tests/test_b.py": both}
    )
    got = named_tests(bench.wb, task, bench.wb.head())
    assert got.tests == () and got.kept == (("test_roundtrip", "named in 2 test files: write <path>::test_roundtrip"),)


def test_a_text_the_base_branch_has_is_reviewed_too(make_bench):
    bench = make_bench([])
    task = prepare(bench, "- [ ] 1.1 Change tests/test_pricing.py::test_total_adds_prices\n", base=True)
    got = named_tests(bench.wb, task, bench.wb.head())
    assert got.source and got.source.startswith("base:") and len(got.tests) == 1


def test_a_text_nobody_reviewed_names_nothing(make_bench):
    bench = make_bench([])
    task = prepare(bench, "- [ ] 1.1 Change tests/test_pricing.py::test_total_adds_prices\n")
    assert named_tests(bench.wb, task, bench.wb.head()) == NamedTests()


def test_a_fix_unit_names_nothing(make_bench):
    bench = make_bench([])
    task = prepare(bench, "- [ ] 1.1 Change tests/test_pricing.py::test_total_adds_prices\n", plan=True)
    (bench.wb.ref.path / ".l4").mkdir(exist_ok=True)
    from l4.implementer import tdd

    original = tdd.read_fix_marker
    tdd.read_fix_marker = lambda _path: object()  # type: ignore[assignment]
    try:
        assert named_tests(bench.wb, task, bench.wb.head()) == NamedTests()
    finally:
        tdd.read_fix_marker = original


# --- the criteria a task cites ---

CRITERION = "WHEN the tip is rounded THEN `tests/test_tip_old.py::test_rounds` is rewritten in place"
OLD_TIP_TEST = "def test_rounds():\n    assert 1\n"


def kiro_task(bench, *, plan: bool, base: bool, change: bool = False):
    requirements = bench.wb.ref.path / "requirements.md"
    requirements.write_text(
        requirements.read_text().replace("rounded to 2 places.", f"rounded to 2 places. {CRITERION}.")
    )
    (bench.wb.worktree / "tests").mkdir(exist_ok=True)
    (bench.wb.worktree / "tests/test_tip_old.py").write_text(OLD_TIP_TEST)
    commit(bench, "criterion and test")
    if base:
        bench.wb.git.run("update-ref", "refs/remotes/origin/main", "HEAD")
    if change:  # the unit folder now differs from the base branch's, the task block does not
        requirements.write_text(requirements.read_text() + "\nmore\n")
        commit(bench, "folder differs")
    if plan:
        bench.wb.activated_plan = "p1"
        bench.wb.activated_digest = unit_digest(bench.wb.git, "HEAD", bench.wb.unit_rel)
    return bench.wb.provider.tasks(bench.wb.ref)[0]


def test_a_cited_criterion_counts_for_a_plan_source(make_kiro_bench):
    bench = make_kiro_bench([])
    task = kiro_task(bench, plan=True, base=False)
    assert named_tests(bench.wb, task, bench.wb.head()).tests == (("tests/test_tip_old.py", "test_rounds"),)


def test_a_cited_criterion_counts_when_the_folder_is_the_base_branchs(make_kiro_bench):
    bench = make_kiro_bench([])
    task = kiro_task(bench, plan=False, base=True)
    assert named_tests(bench.wb, task, bench.wb.head()).tests == (("tests/test_tip_old.py", "test_rounds"),)


def test_a_cited_criterion_is_ignored_when_the_folder_differs_from_the_base_branchs(make_kiro_bench):
    bench = make_kiro_bench([])
    task = kiro_task(bench, plan=False, base=True, change=True)
    got = named_tests(bench.wb, task, bench.wb.head())
    assert got.tests == () and got.source is not None


# --- named-test-any-language 1.1: a test of another language, `path::name` between backticks (L4-IMP-089, D1) ---

CODES = "src/api/error-codes.test.ts"
REGISTRY = "C-96e47324 The registry holds exactly the 16 codes of the API with status and message"
CODES_TEXT = (
    'import { expect, it } from "vitest";\n\n'
    f'it("{REGISTRY}", () => {{\n  expect(CODES.length).toBe(16);\n}});\n\n'
    'it("every code has a status", () => {\n  expect(CODES.length).toBe(16);\n});\n'
)
NESTED = (
    'describe("one", () => {\n  it("same name", () => {\n    expect(1).toBe(1);\n  });\n});\n\n'
    'describe("two", () => {\n  it("same name", () => {\n    expect(1).toBe(1);\n  });\n});\n'
)
OTHER_FILES = {CODES: CODES_TEXT, "src/api/nested.test.ts": NESTED}
OTHER_IDS = (
    f"{CODES}::{REGISTRY}", f"{CODES}::every code has a status",
    "src/api/nested.test.ts::one > same name", "src/api/nested.test.ts::two > same name",
)  # fmt: skip


def other(*texts: str, files=OTHER_FILES, ids=OTHER_IDS):
    return find_named_other(texts, files, ids)


def test_scn_imp_439_the_whole_backticked_name_with_spaces_and_an_id_resolves_to_one_report_id():
    tests, kept = other(f"- [ ] 1.1 Add six codes; change `{CODES}::{REGISTRY}` to expect 22")
    assert tests == ((CODES, f"{CODES}::{REGISTRY}"),) and kept == ()


def test_the_name_may_be_the_last_segments_of_a_describe_joined_report_name():
    ids = (f"{CODES}::API > errors > {REGISTRY}", f"{CODES}::API > other")
    tests, kept = other(f"`{CODES}::{REGISTRY}` and `{CODES}::errors > {REGISTRY}`", ids=ids)
    assert tests == ((CODES, f"{CODES}::API > errors > {REGISTRY}"),) and kept == ()


def test_both_id_forms_name_the_file_the_dotted_one_and_the_plain_path():
    dotted = (f"src.api.error-codes.test.ts::{REGISTRY}",)
    tests, _ = other(f"`{CODES}::{REGISTRY}`", ids=dotted)
    assert tests == ((CODES, dotted[0]),)
    plain, _ = other(f"`{CODES}::{REGISTRY}`", ids=(f"{CODES}::{REGISTRY}",))
    assert plain == ((CODES, f"{CODES}::{REGISTRY}"),)


def test_scn_imp_442_a_name_under_two_describe_blocks_is_ambiguous_and_kept():
    tests, kept = other("`src/api/nested.test.ts::same name`")
    assert tests == ()
    assert kept == (("src/api/nested.test.ts::same name", "more than one test matches"),)
    one, _ = other("`src/api/nested.test.ts::one > same name`")
    assert one == (("src/api/nested.test.ts", "src/api/nested.test.ts::one > same name"),)


def test_scn_imp_442_a_name_no_test_has_is_kept_with_its_reason():
    tests, kept = other(f"`{CODES}::the registry holds the codes`")
    assert tests == ()
    assert kept == ((f"{CODES}::the registry holds the codes", "no test of that name in the base report"),)


def test_a_name_that_only_ends_the_same_way_is_no_match():
    tests, kept = other(f"`{CODES}::status`")  # "every code has a status" ends with it, after a space only
    assert tests == () and [why for _, why in kept] == ["no test of that name in the base report"]


def test_a_test_the_report_holds_but_whose_lines_cannot_be_found_is_kept():
    files = {CODES: "// the test is generated\n"}
    tests, kept = other(f"`{CODES}::{REGISTRY}`", files=files)
    assert tests == () and kept == ((f"{CODES}::{REGISTRY}", f"the lines of the test are not found in {CODES}"),)


def test_scn_imp_443_a_file_without_a_test_name_and_a_path_that_is_no_candidate_name_nothing():
    text = f"change `{CODES}` and `src/api/other.test.ts::{REGISTRY}` and `tests/test_x.py::test_a` and {CODES}::x"
    assert other(text) == ((), ())


def test_the_python_forms_are_untouched_by_the_second_pattern():
    text = (
        "update `tests/test_registry.py::test_registry_lists_all` and "
        "`tests/test_registry.py::TestGuards::test_read_guard_a`"
    )
    assert other(text) == ((), ())
    tests, _ = named(text)
    assert [n for _, n in tests] == ["TestGuards.test_read_guard_a", "test_registry_lists_all"]


def test_a_dot_slash_path_and_a_repeated_token_name_one_test():
    tests, _ = other(f"`./{CODES}::{REGISTRY}` then `{CODES}::{REGISTRY}`")
    assert tests == ((CODES, f"{CODES}::{REGISTRY}"),)


def test_the_language_follows_the_suffix():
    assert [language_of(p) for p in ("a/b.test.ts", "c.spec.tsx", "d.test.js", "e_test.go", "F.java", "g.zz")] == [
        "typescript", "typescript", "javascript", "go", "java", "zz",
    ]  # fmt: skip


def base_report(*ids: str) -> TestReport:
    return TestReport({i: TestCase(i, "passed") for i in ids})


def test_a_reviewed_text_names_a_test_of_another_language_through_the_base_report(make_bench):
    bench = make_bench([])
    task = prepare(
        bench,
        f"- [ ] 1.1 Add six codes; change `{CODES}::{REGISTRY}` and tests/test_pricing.py::test_total_adds_prices\n",
        plan=True,
        extra={CODES: CODES_TEXT},
    )
    report = base_report(f"{CODES}::{REGISTRY}", f"{CODES}::every code has a status")
    got = named_tests(bench.wb, task, bench.wb.head(), report)
    assert got.other == ((CODES, f"{CODES}::{REGISTRY}"),) and got.other_ids() == (f"{CODES}::{REGISTRY}",)
    assert [n for _, n in got.tests] == ["test_total_adds_prices"]  # the Python form is as before
    assert named_tests(bench.wb, task, bench.wb.head()).other == ()  # no base report: no such test is named


def test_a_support_a_missing_and_an_untracked_file_open_no_test_of_another_language(make_bench):
    bench = make_bench([])
    support = "src/api/fixtures/codes.ts"
    task = prepare(
        bench, f"- [ ] 1.1 Change `{support}::{REGISTRY}` and `src/api/none.test.ts::{REGISTRY}`\n", plan=True,
        extra={support: CODES_TEXT},
    )  # fmt: skip
    report = base_report(f"{support}::{REGISTRY}", f"src/api/none.test.ts::{REGISTRY}")
    assert named_tests(bench.wb, task, bench.wb.head(), report).other == ()


def test_the_cap_of_five_counts_both_kinds_and_the_rest_is_kept(make_bench):
    many = "".join(f'it("case {i}", () => {{\n  expect(1).toBe(1);\n}});\n' for i in range(7))
    bench = make_bench([])
    text = " ".join(f"`{CODES}::case {i}`" for i in range(7))
    task = prepare(
        bench,
        f"- [ ] 1.1 Change {text} and tests/test_pricing.py::test_total_adds_prices\n",
        plan=True,
        extra={CODES: many},
    )
    report = base_report(*(f"{CODES}::case {i}" for i in range(7)))
    got = named_tests(bench.wb, task, bench.wb.head(), report)
    assert len(got.tests) + len(got.other) == MAX_NAMED_TESTS and len(got.tests) == 1
    assert [t for _, t in got.other] == [f"{CODES}::case {i}" for i in range(4)]
    assert [why for _, why in got.kept] == ["more than 5 existing tests named"] * 3
