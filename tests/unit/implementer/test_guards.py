import hashlib
from collections.abc import Callable
from pathlib import Path

import pytest

from l4.config.schema import L4Config
from l4.implementer.guards import build_manifest, restore_frozen
from l4.vcs.git import Git

TDD = L4Config().tdd


class Events:
    def __init__(self) -> None:
        self.rows: list[tuple[str, dict]] = []

    def append(self, event_type: str, /, **data: object) -> None:
        self.rows.append((event_type, data))


@pytest.fixture
def red_repo(make_repo: Callable[..., Path], git_for: Callable[[Path], Git]):
    """main holds src/calc.py; the red commit adds a test, a second test, a conftest and a fixture file."""
    repo = make_repo()
    git = git_for(repo)
    (repo / "src").mkdir()
    (repo / "src" / "calc.py").write_text("def add(a, b):\n    raise NotImplementedError\n")
    git.run("add", "-A")
    git.run("-c", "user.name=t", "-c", "user.email=t@x.invalid", "commit", "-q", "-m", "base")
    base = git.rev_parse("HEAD")
    (repo / "tests" / "fixtures").mkdir(parents=True)
    (repo / "tests" / "test_calc.py").write_text("from calc import add\n\ndef test_add():\n    assert add(1, 2) == 3\n")
    (repo / "tests" / "test_other.py").write_text("def test_other():\n    assert True\n")
    (repo / "tests" / "conftest.py").write_text("import pytest\n")
    (repo / "tests" / "fixtures" / "data.json").write_text("{}\n")
    git.run("add", "-A")
    git.run("-c", "user.name=t", "-c", "user.email=t@x.invalid", "commit", "-q", "-m", "red")
    return repo, git, base, git.rev_parse("HEAD")


def test_the_manifest_lists_red_test_files_and_every_support_file(red_repo):
    repo, git, base, red = red_repo
    manifest = build_manifest(git, red, base, test_globs=TDD.test_globs, support_globs=TDD.test_support_globs)
    kinds = {path: frozen.kind for path, frozen in manifest.files.items()}
    assert kinds == {
        "tests/test_calc.py": "test", "tests/test_other.py": "test",
        "tests/conftest.py": "support", "tests/fixtures/data.json": "support",
    }  # fmt: skip
    assert manifest.files["tests/conftest.py"].sha256 == hashlib.sha256(b"import pytest\n").hexdigest()
    assert "src/calc.py" not in manifest.files  # production code is what green may change


def test_green_edit_to_red_test_and_helper_is_reverted(red_repo):
    repo, git, base, red = red_repo
    manifest = build_manifest(git, red, base, test_globs=TDD.test_globs, support_globs=TDD.test_support_globs)
    (repo / "tests" / "test_calc.py").write_text("from calc import add\n\ndef test_add():\n    assert True\n")
    (repo / "tests" / "conftest.py").write_text("import pytest\nimport os\n")
    (repo / "tests" / "test_other.py").unlink()
    (repo / "tests" / "fixtures" / "extra.json").write_text("{}\n")  # a new support file
    (repo / "tests" / "test_new.py").write_text("def test_new():\n    assert True\n")  # new tests are allowed
    (repo / "src" / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    events = Events()
    restore_frozen(git, manifest, events=events)
    assert (repo / "tests" / "test_calc.py").read_text().endswith("assert add(1, 2) == 3\n")
    assert (repo / "tests" / "conftest.py").read_text() == "import pytest\n"
    assert (repo / "tests" / "test_other.py").exists()
    assert not (repo / "tests" / "fixtures" / "extra.json").exists()
    assert (repo / "tests" / "test_new.py").exists()
    assert (repo / "src" / "calc.py").read_text().endswith("return a + b\n")
    assert sorted((t, d["path"]) for t, d in events.rows) == [
        ("guard.test_tamper", "tests/test_calc.py"),
        ("guard.test_tamper", "tests/test_other.py"),
        ("guard.violation", "tests/conftest.py"),
        ("guard.violation", "tests/fixtures/extra.json"),
    ]
    assert git.run("status", "--porcelain").stdout.split() == ["M", "src/calc.py", "??", "tests/test_new.py"]


def test_an_untouched_tree_produces_no_events(red_repo):
    repo, git, base, red = red_repo
    manifest = build_manifest(git, red, base, test_globs=TDD.test_globs, support_globs=TDD.test_support_globs)
    events = Events()
    restore_frozen(git, manifest, events=events)
    assert events.rows == []


def test_a_frozen_file_replaced_by_a_symlink_is_restored(red_repo, tmp_path: Path):
    repo, git, base, red = red_repo
    manifest = build_manifest(git, red, base, test_globs=TDD.test_globs, support_globs=TDD.test_support_globs)
    target = tmp_path / "elsewhere.py"
    target.write_text("import pytest\n")
    (repo / "tests" / "conftest.py").unlink()
    (repo / "tests" / "conftest.py").symlink_to(target)
    restore_frozen(git, manifest, events=Events())
    assert not (repo / "tests" / "conftest.py").is_symlink()


def test_a_conftest_hidden_behind_gitignore_is_still_removed(red_repo):
    repo, git, base, red = red_repo
    manifest = build_manifest(git, red, base, test_globs=TDD.test_globs, support_globs=TDD.test_support_globs)
    (repo / "tests" / "sub").mkdir()
    (repo / "tests" / "sub" / "conftest.py").write_text("def pytest_runtest_call(item):\n    pass\n")
    (repo / ".gitignore").write_text("tests/sub/conftest.py\n")
    events = Events()
    restore_frozen(git, manifest, events=events)
    assert not (repo / "tests" / "sub" / "conftest.py").exists()
    assert not (repo / ".gitignore").exists()  # a new ignore file is itself a support file
    assert {d["path"] for _, d in events.rows} == {"tests/sub/conftest.py", ".gitignore"}


def test_a_tracked_gitignore_edited_in_green_is_restored(make_repo, git_for):
    repo = make_repo()
    git = git_for(repo)
    (repo / ".gitignore").write_text("build/\n")
    (repo / "tests").mkdir(exist_ok=True)
    (repo / "tests" / "test_a.py").write_text("def test_a():\n    assert False\n")
    git.run("add", "-A")
    git.run("-c", "user.name=t", "-c", "user.email=t@x.invalid", "commit", "-q", "-m", "red")
    red = git.rev_parse("HEAD")
    manifest = build_manifest(git, red, red, test_globs=TDD.test_globs, support_globs=TDD.test_support_globs)
    (repo / ".gitignore").write_text("build/\ntests/conftest.py\n")
    restore_frozen(git, manifest, events=Events())
    assert (repo / ".gitignore").read_text() == "build/\n"


def test_ignored_tool_caches_and_dependencies_are_not_support_files(red_repo, tmp_path: Path):
    repo, git, base, red = red_repo
    (repo / ".gitignore").write_text("node_modules/\nvenv/\n.ruff_cache/\n")
    git.run("add", "-A")
    git.run("-c", "user.name=t", "-c", "user.email=t@x.invalid", "commit", "-q", "-m", "ignore rules")
    red = git.rev_parse("HEAD")
    manifest = build_manifest(git, red, base, test_globs=TDD.test_globs, support_globs=TDD.test_support_globs)
    for name in ("node_modules/pkg/conftest.py", "venv/lib/numpy/conftest.py", ".ruff_cache/.gitignore"):
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text("installed\n")
    (repo / "tests" / "fixtures" / "extra.json").write_text("{}\n")
    events = Events()
    restore_frozen(git, manifest, events=events)
    assert [d["path"] for _, d in events.rows] == ["tests/fixtures/extra.json"]
    assert (repo / "venv/lib/numpy/conftest.py").exists() and (repo / ".ruff_cache/.gitignore").exists()


def test_harness_excludes_cover_the_linter_and_typechecker_caches():
    from l4.implementer.workbench import HARNESS_EXCLUDES

    assert {".ruff_cache/", ".mypy_cache/", "node_modules/"} <= set(HARNESS_EXCLUDES)


def test_a_manifest_at_head_skips_a_frozen_path_that_is_gone_and_restores_the_rest(red_repo):
    from l4.implementer.guards import manifest_at_head

    repo, git, _, head = red_repo
    gone = "tests/test_renamed_by_a_later_red.py"  # listed by an old `task.red_ok.frozen`, not in the tree any more
    manifest = manifest_at_head(git, head, ["tests/test_calc.py", gone], support_globs=TDD.test_support_globs)
    assert "tests/test_calc.py" in manifest.files and gone not in manifest.files
    (repo / "tests" / "test_calc.py").write_text("def test_add():\n    assert True\n")
    (repo / "tests" / "conftest.py").unlink()
    events = Events()
    touched = restore_frozen(git, manifest, events=events, phase="single")  # no `git checkout` of a missing path
    assert sorted(touched) == ["tests/conftest.py", "tests/test_calc.py"]
    assert {data["phase"] for _, data in events.rows} == {"single"}
    assert "assert add(1, 2) == 3" in (repo / "tests" / "test_calc.py").read_text()


# --- appended_only (M1.11 W5, decision 7) -------------------------------------------------------------------------

BASE_TESTS = "import pytest\n\n\ndef test_a():\n    assert 1 == 1\n\n\nX = 1\n"


@pytest.mark.parametrize(
    ("head", "expected"),
    [
        (BASE_TESTS, True),  # nothing added
        (BASE_TESTS + "\n\ndef test_b():\n    assert 2 == 2\n", True),
        (BASE_TESTS.replace("import pytest\n", "import pytest\nimport os\n") + "\n\ndef test_b():\n    pass\n", True),
        (BASE_TESTS.replace("1 == 1", "1 == 2"), False),  # an edited statement
        (BASE_TESTS.replace("def test_a():\n    assert 1 == 1\n\n\n", ""), False),  # a removed one
        (BASE_TESTS + "\n\ndef test_a():\n    pass\n", False),  # a rebinding def: shadows the proof test
        (BASE_TESTS + "\n\nX = 2\n", False),  # a rebound assignment
        (BASE_TESTS + "\n\nfrom other import test_a\n", False),  # an import that rebinds
        (BASE_TESTS + "\n\nimport pytest\n", True),  # the same import again is no rebinding
        (BASE_TESTS + "\n\ntest_a.__code__ = None\n", False),  # code at import time
        (BASE_TESTS + "\n\nif True:\n    pass\n", False),
        ("def broken(:\n", False),
    ],
)
def test_appended_only(head: str, expected: bool):
    from l4.implementer.guards import appended_only

    assert appended_only(BASE_TESTS, head) is expected


# m1.11(fix): an appended statement must not reach the tests the file already has. Each of these keeps every existing
# statement and binds a new name, and each would make the proof tests of the file pass whatever the code does.
PROOF_FILE = (
    "import pytest\n\nfrom app import core\nfrom helpers import fake_client\n\n\n"
    "@pytest.mark.usefixtures('db')\ndef test_proof(client):\n    assert core.compute(2) == 4\n"
)
PATCH = "    core.compute = lambda x: 4\n"


@pytest.mark.parametrize(
    ("added", "why"),
    [
        ("@pytest.fixture(autouse=True)\ndef _patch():\n" + PATCH, "an autouse fixture reaches every test of the file"),
        ("@pytest.fixture\ndef client():\n    return None\n", "a fixture that overrides one a proof test requests"),
        ("@pytest.fixture\ndef db():\n    return None\n", "overrides a fixture a proof test names in usefixtures"),
        ("client = fake_client\n", "an alias that overrides a requested fixture"),
        ("from helpers import other_client as client\n", "an import that overrides a requested fixture"),
        ("from helpers import *\n", "a star import binds names nobody can see"),
        ("pytestmark = pytest.mark.xfail(reason='x')\n", "a module mark reaches every test of the file"),
        ("def setup_module(module):\n" + PATCH, "xunit setup runs before the tests of the file"),
        ("def setup_function(function):\n" + PATCH, "xunit setup runs before every test of the file"),
        ("def pytest_generate_tests(metafunc):\n    pass\n", "a pytest hook of the module"),
        ("_x = setattr(core, 'compute', lambda x: 4)\n", "an assignment whose value runs code at import"),
        ("@(lambda f: (setattr(core, 'compute', lambda x: 4), f)[1])\ndef test_new():\n    pass\n", "a decorator"),
        ("def test_new(x=setattr(core, 'compute', lambda x: 4)):\n    pass\n", "a default runs at import"),
        ("class TestNew:\n    setattr(core, 'compute', lambda x: 4)\n", "a class body runs at import"),
        ("CASES = [(test_proof := (lambda client: None))]\n", "a walrus rebinds the proof test"),
        ("class TestNew:\n    global test_proof\n    test_proof = None\n", "a global in a class body"),
    ],
)
def test_an_appended_statement_that_reaches_the_existing_tests_is_not_appended_only(added: str, why: str):
    from l4.implementer.guards import appended_only

    assert appended_only(PROOF_FILE, PROOF_FILE + "\n\n" + added) is False, why


@pytest.mark.parametrize(
    "added",
    [
        "def test_new():\n    assert core.compute(3) == 6\n",
        "@pytest.mark.parametrize('n, out', [(1, 2), (3, 6)])\ndef test_many(n, out):\n"
        "    assert core.compute(n) == out\n",
        "@pytest.mark.l4('C-0123abcd')\nclass TestMore:\n    CASES = (1, 2)\n\n    def test_it(self, client):\n"
        "        assert client is not None\n",
        "LIMIT = 10\n\n\ndef test_limit():\n    assert core.compute(LIMIT) == 20\n",
        "import os\n\n\ndef test_env():\n    assert os.sep\n",
    ],
)
def test_plain_new_tests_stay_appended_only(added: str):
    from l4.implementer.guards import appended_only

    assert appended_only(PROOF_FILE, PROOF_FILE + "\n\n" + added) is True
