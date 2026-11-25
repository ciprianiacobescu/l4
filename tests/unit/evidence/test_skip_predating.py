"""The rule that decides whether the skip of an old test predates the unit (skipped-test-hold D1, L4-VER-092):
SCN-VER-372..378, on a temporary git repository with a base commit and a head commit."""

import itertools
from collections.abc import Callable

import pytest

from l4.config.schema import L4Config
from l4.evidence import collect
from l4.evidence.collect import skip_predating

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
    """`run(base_files, head_files, ids=..., deleted=..., cfg=...)`: commit both states, ask the rule."""

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
        return skip_predating(
            git_for(repo),
            base_sha or base_commit,
            head_commit,
            test_files,
            ids,
            cfg or L4Config.model_validate({}),
            tree,
        )

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
    assert run({LIVE: base}, {LIVE: head}, ids=ids) == {ids[0]}
    marked = base.replace("class TestOther:\n", "class TestOther:\n    pytestmark = pytest.mark.skip\n\n")
    assert run({LIVE: base}, {LIVE: marked}, ids=ids) == {ids[0]}


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
    assert skip_predating(git_for(repo), "no", "no", [LIVE], [A], L4Config.model_validate({}), [LIVE]) == set()


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


def test_a_construct_in_the_file_makes_support_files_irrelevant(run):
    base = {LIVE: live(), "tests/conftest.py": "x = 1\n"}
    assert run(base, {LIVE: live("2"), "tests/conftest.py": "x = 2\n"}) == {A, B}


def test_only_changed_test_files_given_are_examined(run):
    other = "tests/test_other.py"
    base = {LIVE: live(), other: "def test_z():\n    assert 1\n"}
    head = {LIVE: live("2"), other: "def test_z():\n    assert 2\n"}
    assert run(base, head, ids=(A, "tests.test_other::test_z")) == {A}
