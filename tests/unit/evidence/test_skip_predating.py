"""The rule that decides whether the skip of an old test predates the unit (skipped-test-hold D1, L4-VER-092):
SCN-VER-372..378, on a temporary git repository with a base commit and a head commit. The base report that must hold
the test as skipped (rule (a)) is a fake: `at_base="skipped"` says it does, `"passed"` that it ran, `None` that there is
none."""

import itertools
from collections.abc import Callable

import pytest

from l4.config.schema import L4Config
from l4.evidence import collect
from l4.evidence.collect import Predating, skip_predating
from l4.evidence.skippred import STEP1_SOURCE, BaseSkips
from l4.verifier.skipdeps import SkipFacts

SKIPIF = "@pytest.mark.skipif(os.getenv('X_INTEGRATION_TEST') != 'true', reason='needs the stack')"
HEADER = "import os\n\nimport pytest\n\n"
LIVE = "tests/test_live.py"
A, B = "tests.test_live::test_a", "tests.test_live::test_b"


def live(a_assert: str = "1", b_assert: str = "1", *, extra: str = "", top: str = "", a_mark: str = SKIPIF) -> str:
    return (
        f"{HEADER}{top}{extra}\n\n{a_mark}\ndef test_a():\n    assert {a_assert}\n\n\n"
        f"{SKIPIF}\ndef test_b():\n    assert {b_assert}\n"
    )


@pytest.fixture
def run(make_repo, raw, git_for) -> Callable[..., set[str]]:
    """`run(base_files, head_files, ids=..., deleted=..., cfg=...)`: commit both states, ask the rule. `.decided` of the
    function is the last `Predating` (source and note)."""

    counter = itertools.count()

    def go(
        base: dict[str, str],
        head: dict[str, str],
        ids: tuple[str, ...] = (A, B),
        *,
        deleted: tuple[str, ...] = (),
        renamed: dict[str, str] | None = None,
        test_files: tuple[str, ...] = (LIVE,),
        cfg: L4Config | None = None,
        base_sha: str | None = None,
        at_base: str | None = "skipped",
    ) -> set[str]:
        repo = make_repo(f"repo{next(counter)}")
        for rel, text in base.items():
            (repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (repo / rel).write_text(text)
        raw(repo, "add", "-A")
        raw(repo, "commit", "-q", "-m", "base")
        base_commit = raw(repo, "rev-parse", "HEAD").strip()
        for old, new in (renamed or {}).items():
            (repo / new).parent.mkdir(parents=True, exist_ok=True)
            raw(repo, "mv", old, new)
        for rel in deleted:
            (repo / rel).unlink()
        for rel, text in head.items():
            (repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (repo / rel).write_text(text)
        raw(repo, "add", "-A")
        raw(repo, "commit", "-q", "-m", "head")
        head_commit = raw(repo, "rev-parse", "HEAD").strip()
        tree = raw(repo, "ls-tree", "-r", "--name-only", head_commit).split()
        asked.clear()

        def lookup() -> BaseSkips:
            asked.append(1)
            if at_base is None:
                return BaseSkips(None, "", "no base report with statuses: FAKE")
            return BaseSkips(frozenset(ids if at_base == "skipped" else ()), STEP1_SOURCE)

        found = skip_predating(
            git_for(repo),
            base_sha or base_commit,
            head_commit,
            test_files,
            ids,
            cfg or L4Config.model_validate({}),
            tree,
            lookup,
        )
        go.decided = found  # type: ignore[attr-defined]
        return set(found.ids)

    asked: list[int] = []
    go.asked = asked  # type: ignore[attr-defined]
    return go


def test_an_edited_assertion_under_an_unchanged_skipif_predates_the_unit(run):  # SCN-VER-372
    assert run({LIVE: live()}, {LIVE: live("2", "2")}) == {A, B}


def test_a_skip_the_unit_added_does_not_predate_it(run):  # SCN-VER-373
    base = {LIVE: live(a_mark="")}
    assert run(base, {LIVE: live("2")}, ids=(A,)) == set()


def test_a_removed_skip_never_counts(run):
    assert run({LIVE: live()}, {LIVE: live(a_mark="")}, ids=(B,)) == {B}


def test_a_changed_condition_on_a_continuation_line_is_a_changed_skip(run):  # SCN-VER-374
    two_lines = "@pytest.mark.skipif(\n    os.getenv('{}') != 'true',\n    reason='r',\n)"
    base = {LIVE: live(a_mark=two_lines.format("A"))}
    head = {LIVE: live(a_mark=two_lines.format("B"))}
    assert run(base, head) == {B}  # test_a's skip changed; test_b's did not


def test_a_skip_added_to_one_test_does_not_touch_another(run):  # SCN-VER-375
    base = {LIVE: live(a_mark="")}
    head = {LIVE: live(a_mark="@pytest.mark.skip")}
    assert run(base, head) == {B}


@pytest.mark.parametrize(
    "head",
    [
        pytest.param(live(top="pytestmark = pytest.mark.skipif(True, reason='r')\n"), id="module-pytestmark"),
        pytest.param(live(top="docker = pytest.importorskip('docker')\n"), id="module-importorskip"),
        pytest.param(live(extra="\n\n@pytest.fixture\ndef stack():\n    pytest.skip('no stack')"), id="fixture-skip"),
        pytest.param(live(extra="\n\ndef helper():\n    pytest.skip('no helper')"), id="helper-skip"),
    ],
)
def test_a_skip_construct_in_a_shared_scope_touches_every_test(run, head):  # SCN-VER-376
    assert run({LIVE: live()}, {LIVE: head}) == set()


def test_an_alias_newly_applied_to_an_old_test_touches_that_test_only(run):  # SCN-VER-376
    """D3 scopes an alias use to the decorated function; the scenario's "every old skipped test" reads for the test
    the alias was applied to (the alias definition, which would touch the module, is not new here)."""
    head = (
        f"{HEADER}requires_stack = pytest.mark.skipif(True, reason='r')\n\n\n@requires_stack\ndef test_a():\n"
        f"    assert 1\n\n\n{SKIPIF}\ndef test_b():\n    assert 1\n"
    )
    base = head.replace("@requires_stack\n", "")
    assert run({LIVE: base}, {LIVE: head}) == {B}


def test_an_alias_already_applied_at_the_base_is_not_new(run):
    source = (
        f"{HEADER}requires_stack = pytest.mark.skipif(True, reason='r')\n\n\n@requires_stack\ndef test_a():\n"
        "    assert {}\n"
    )
    assert run({LIVE: source.format(1)}, {LIVE: source.format(2)}, ids=(A,)) == {A}


def test_a_skip_in_a_class_scope_touches_only_that_class(run):
    base = (
        f"{HEADER}\n\nclass TestK:\n    {SKIPIF}\n    def test_a(self):\n        assert 1\n\n"
        "class TestOther:\n    def test_b(self):\n        assert 1\n"
    )
    head = base.replace("class TestOther:\n", "@pytest.mark.skip\nclass TestOther:\n")
    ids = ("tests.test_live.TestK::test_a", "tests.test_live.TestOther::test_b")
    # (b) alone would say that the class scope touches only TestOther. (e) refuses a changed decorator or a new class
    # statement wherever it is, so no test of the file predates the unit (rework 9).
    assert run({LIVE: base}, {LIVE: head}, ids=ids) == set()
    marked = base.replace("class TestOther:\n", "class TestOther:\n    pytestmark = pytest.mark.skip\n\n")
    assert run({LIVE: base}, {LIVE: marked}, ids=ids) == set()
    before, after = SkipFacts(base), SkipFacts(head)
    assert [s for s, _ in (after.constructs - before.constructs)] == ["TestOther"]  # what (b) sees: that class only


def test_a_parametrized_id_maps_to_its_function(run):
    base = f"{HEADER}\n\n{SKIPIF}\n@pytest.mark.parametrize('n', [1, 2])\ndef test_a(n):\n    assert n\n"
    ids = ("tests.test_live::test_a[1]", "tests.test_live::test_a[2]")
    assert run({LIVE: base}, {LIVE: base.replace("assert n", "assert n >= 0")}, ids=ids) == set(ids)


@pytest.mark.parametrize("how", ["added", "renamed", "absent-at-base", "moved-class", "unparsable-head", "no-blob"])
def test_a_file_or_test_that_cannot_be_compared_stays_a_finding(run, how):  # SCN-VER-377
    if how == "added":
        assert run({"README.txt": "x\n"}, {LIVE: live()}) == set()
    elif how == "renamed":
        assert run({"tests/old.py": live()}, {LIVE: live()}, renamed={"tests/old.py": LIVE}) == set()
    elif how == "absent-at-base":
        assert run({LIVE: live().replace("test_a", "test_old")}, {LIVE: live("2")}, ids=(A,)) == set()
    elif how == "moved-class":
        moved = f"{HEADER}\n\nclass TestK:\n    {SKIPIF}\n    def test_a(self):\n        assert 1\n"
        assert run({LIVE: live()}, {LIVE: moved}, ids=("tests.test_live.TestK::test_a",)) == set()
    elif how == "unparsable-head":
        assert run({LIVE: live()}, {LIVE: live() + "\ndef (:\n"}) == set()
    else:
        assert run({LIVE: live()}, {LIVE: live("2")}, base_sha="0" * 40) == set()


def test_a_blob_over_the_size_bound_is_not_compared(run, monkeypatch):  # SCN-VER-377
    monkeypatch.setattr(collect, "MAX_SOURCE_BYTES", 60)
    assert run({LIVE: live()}, {LIVE: live("2")}) == set()


def test_the_rule_never_raises(git_for, make_repo):
    repo = make_repo()
    assert skip_predating(git_for(repo), "no", "no", [LIVE], [A], L4Config.model_validate({}), [LIVE]) == Predating()


@pytest.mark.parametrize(
    ("extra", "expected"),
    [
        ({}, {A}),
        ({"src/shop/pricing.py": "x = 2\n"}, {A}),  # a code file is neither support nor runner config
        ({"tests/conftest.py": "x = 2\n"}, set()),
        ({"conftest.py": "x = 2\n"}, set()),
        ({"pyproject.toml": "[tool]\nx = 2\n"}, set()),
        ({"pytest.ini": "[pytest]\n-p x\n"}, set()),
    ],
)
def test_a_skip_with_no_construct_in_the_file_depends_on_support_files(run, extra, expected):  # SCN-VER-378
    plain = "def test_a():\n    assert {}\n"
    base = {LIVE: plain.format(1), "tests/conftest.py": "x = 1\n", "pyproject.toml": "[tool]\nx = 1\n"}
    base |= {"pytest.ini": "[pytest]\n", "src/shop/pricing.py": "x = 1\n", "conftest.py": "x = 1\n"}
    head = {LIVE: plain.format(2), **extra}
    assert run(base, head, ids=(A,)) == expected


def test_a_construct_in_the_file_does_not_make_support_files_irrelevant(run):  # F7: rule (c) is unconditional
    base = {LIVE: live(), "tests/conftest.py": "x = 1\n"}
    assert run(base, {LIVE: live("2"), "tests/conftest.py": "x = 2\n"}) == set()
    assert run(base, {LIVE: live("2"), "tests/conftest.py": "x = 1\n"}) == {A, B}  # the control: it did not change


def test_only_changed_test_files_given_are_examined(run):
    other = "tests/test_other.py"
    base = {LIVE: live(), other: "def test_z():\n    assert 1\n"}
    head = {LIVE: live("2"), other: "def test_z():\n    assert 2\n"}
    assert run(base, head, ids=(A, "tests.test_other::test_z")) == {A}


# --- rule (a): the base report -------------------------------------------------------------------------------------


def test_the_base_report_decides_which_candidates_predate_the_unit(run):
    assert run({LIVE: live()}, {LIVE: live("2", "2")}, at_base="passed") == set()
    assert run.decided.ids == frozenset() and run.decided.note == ""  # a report was had: nothing to explain


def test_the_source_of_the_report_is_named(run):
    assert run({LIVE: live()}, {LIVE: live("2", "2")}) == {A, B}
    assert run.decided == Predating(frozenset({A, B}), STEP1_SOURCE, "")


def test_no_report_keeps_every_skip_a_finding_and_says_why(run):
    assert run({LIVE: live()}, {LIVE: live("2", "2")}, at_base=None) == set()
    assert run.decided.note == "no base report with statuses: FAKE"


def test_the_report_is_asked_once_and_only_when_a_candidate_exists(run):
    run({LIVE: live()}, {LIVE: live("2", "2")})
    assert len(run.asked) == 1
    run({LIVE: live(a_mark="")}, {LIVE: live("2")}, ids=(A,))  # the unit added a skip: nothing to ask
    assert run.asked == []
    run({LIVE: live()}, {LIVE: live("2")}, ids=())
    assert run.asked == []


def test_a_lookup_that_raises_leaves_the_finding_in_place(git_for, make_repo, raw):
    repo = make_repo("boom")
    (repo / LIVE).parent.mkdir(parents=True, exist_ok=True)
    (repo / LIVE).write_text(live())
    raw(repo, "add", "-A")
    raw(repo, "commit", "-q", "-m", "base")
    base = raw(repo, "rev-parse", "HEAD").strip()
    (repo / LIVE).write_text(live("2"))
    raw(repo, "add", "-A")
    raw(repo, "commit", "-q", "-m", "head")
    head = raw(repo, "rev-parse", "HEAD").strip()

    def boom() -> BaseSkips:
        raise RuntimeError("the gate fell over")

    found = skip_predating(git_for(repo), base, head, [LIVE], [A], L4Config.model_validate({}), [LIVE], boom)
    assert found.ids == frozenset() and "lookup failed (RuntimeError)" in found.note
    assert (
        skip_predating(git_for(repo), base, head, [LIVE], [A], L4Config.model_validate({}), [LIVE]).ids == frozenset()
    )


# --- rule (c): runner files in any directory, and the old path of a rename (review G5) ------------------------------

CONFTEST = "import pytest\n\n\n@pytest.fixture\ndef f():\n    return 1\n"


@pytest.mark.parametrize(
    "name", ["conftest.py", "pytest.ini", "pyproject.toml", "setup.cfg", "tox.ini", ".pytest.ini", "pytest.toml"]
)
def test_g5_a_nested_runner_file_that_changed_keeps_the_finding(run, name):
    nested = f"services/api/tests/{name}"
    base = {LIVE: live(), nested: "[x]\n"}
    assert run(base, {LIVE: live("2"), nested: "[y]\n"}) == set()
    assert run(base, {LIVE: live("2"), nested: "[x]\n"}) == {A, B}  # the control: it did not change


def test_g5_a_conftest_that_was_renamed_away_is_a_changed_support_file(run):
    base = {LIVE: live(), "tests/conftest.py": CONFTEST}
    head = {LIVE: live("2"), "tests/conftest_bak.py": CONFTEST}
    assert run(base, head, renamed={"tests/conftest.py": "tests/conftest_bak.py"}) == set()


def test_g5_a_rename_of_an_unrelated_file_does_not_matter(run):
    base = {LIVE: live(), "docs/a.txt": "text\n"}
    head = {LIVE: live("2"), "docs/b.txt": "text\n"}
    assert run(base, head, renamed={"docs/a.txt": "docs/b.txt"}) == {A, B}


# --- cost: the file is read once per path, not once per test (review G3) -------------------------------------------


def test_g3_six_hundred_skipped_tests_of_one_file_are_decided_in_seconds(run):
    import time

    def source(k: int) -> str:
        lines = ["import os", "import pytest", "", "STACK = os.getenv('STACK') == 'true'", ""]
        lines += [f"def helper_{i}():\n    return {i}\n" for i in range(20)]
        for i in range(600):
            lines.append(
                f"@pytest.mark.skipif(not STACK, reason='stack')\ndef test_t{i}():\n    x = helper_{i % 20}()\n"
                f"    assert x == {k + i % 20}\n    assert [y for y in range(10)]\n"
            )
        return "\n".join(lines)

    ids = tuple(f"tests.test_live::test_t{i}" for i in range(600))
    started = time.monotonic()
    found = run({LIVE: source(0)}, {LIVE: source(1)}, ids=ids)
    assert len(found) == 600
    assert time.monotonic() - started < 10


def test_g3_six_hundred_skipped_methods_of_one_class_are_decided_in_seconds(run):
    import time

    def source(k: int) -> str:
        lines = ["import os", "import pytest", "", "STACK = os.getenv('STACK') == 'true'", "", "", "class TestBig:"]
        lines += [f"    def helper_{i}(self):\n        return {i}\n" for i in range(20)]
        for i in range(600):
            lines.append(
                f"    @pytest.mark.skipif(not STACK, reason='stack')\n    def test_t{i}(self):\n"
                f"        x = self.helper_{i % 20}()\n        assert x == {k + i % 20}\n"
            )
        return "\n".join(lines)

    ids = tuple(f"tests.test_live.TestBig::test_t{i}" for i in range(600))
    started = time.monotonic()
    found = run({LIVE: source(0)}, {LIVE: source(1)}, ids=ids)
    assert len(found) == 600
    assert time.monotonic() - started < 10
