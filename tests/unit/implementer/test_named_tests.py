"""Which existing tests the reviewed text names (named-tests 1.1; L4-IMP-082, design D1)."""

from l4.implementer.named_tests import MAX_NAMED_TESTS, NamedTests, find_named, named_tests
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
