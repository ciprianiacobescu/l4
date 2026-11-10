"""What the project's tests already do about optional dependencies and how a test file starts (M1.9, P2/P3): read from
the base commit only, so that nothing the unit changed shapes what its tests are judged against. `e2e_support_files` is
the same for the UI test writer's e2e suite (L4-VER-077)."""

import os

from l4.config.schema import L4Config
from l4.verifier.conventions import base_test_header, e2e_support_files, test_conventions

CONFTEST = """\
import importlib.util

import pytest

requires_fastapi = pytest.mark.skipif(importlib.util.find_spec("fastapi") is None, reason="fastapi missing")
yaml = pytest.importorskip("yaml")
slow = pytest.mark.slow


@pytest.fixture
def tmp():
    needs = pytest.mark.skipif(True, reason="indented: not a module-level helper")
    return needs
"""
PYPROJECT = """\
[project]
name = "demo"

[tool.pytest.ini_options]
markers = [
    "slow: marks tests as slow",
    "needs_db: needs a database",
]
"""
CFG = L4Config.model_validate({})


def commit(raw, repo, files: dict[str, str], message: str) -> str:
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
    raw(repo, "add", "-A")
    raw(repo, "commit", "-q", "-m", message)
    return raw(repo, "rev-parse", "HEAD").strip()


def test_skip_helpers_and_markers_are_listed(make_repo, raw, git_for):
    repo = make_repo()
    base = commit(raw, repo, {"tests/conftest.py": CONFTEST, "pyproject.toml": PYPROJECT}, "base")
    text = test_conventions(git_for(repo), base, CFG)
    lines = text.splitlines()
    assert lines[0].startswith("tests/conftest.py:5: requires_fastapi = pytest.mark.skipif(")
    assert 'tests/conftest.py:6: yaml = pytest.importorskip("yaml")' in lines
    assert "tests/conftest.py:7: slow = pytest.mark.slow" in lines
    assert not any("indented" in line for line in lines)  # only module-level lines
    assert "pyproject.toml:6: slow: marks tests as slow" in lines
    assert "pyproject.toml:7: needs_db: needs a database" in lines
    # a pytest.ini wins the markers it declares, and is listed too
    pytest_ini = "[pytest]\nmarkers =\n    gpu: needs a gpu\n    net: needs the network\n"
    ini = commit(raw, repo, {"pytest.ini": pytest_ini}, "ini")
    listed = test_conventions(git_for(repo), ini, CFG).splitlines()
    assert "pytest.ini:3: gpu: needs a gpu" in listed and "pytest.ini:4: net: needs the network" in listed
    # at most 40 lines and 3000 characters
    many = "import pytest\n" + "".join(f"h{i} = pytest.mark.skipif(False, reason='r{i}')\n" for i in range(100))
    big = commit(raw, repo, {"tests/conftest.py": many}, "many")
    capped = test_conventions(git_for(repo), big, CFG)
    assert len(capped.splitlines()) <= 40 and len(capped) <= 3000


def test_a_project_without_helpers_gives_nothing(make_repo, raw, git_for):
    repo = make_repo()
    plain = "import pytest\n\n\n@pytest.fixture\ndef thing():\n    return 1\n"
    base = commit(raw, repo, {"tests/conftest.py": plain, "pyproject.toml": "[project]\nname = 'demo'\n"}, "base")
    assert test_conventions(git_for(repo), base, CFG) == ""
    assert test_conventions(git_for(repo), raw(repo, "rev-parse", "HEAD~1").strip(), CFG) == ""  # not even a conftest


def test_only_the_base_is_read(make_repo, raw, git_for):
    repo = make_repo()
    base = commit(raw, repo, {"tests/conftest.py": "import pytest\n\nslow = pytest.mark.slow\n"}, "base")
    head = commit(raw, repo, {"tests/conftest.py": CONFTEST, "pyproject.toml": PYPROJECT}, "the unit's change")
    (repo / "tests" / "conftest.py").write_text("import pytest\n\nplanted = pytest.mark.skip\n")  # not even committed
    git = git_for(repo)
    assert test_conventions(git, base, CFG).splitlines() == ["tests/conftest.py:3: slow = pytest.mark.slow"]
    assert "requires_fastapi" in test_conventions(git, head, CFG) and "planted" not in test_conventions(git, head, CFG)


def test_the_header_comes_from_a_base_file_the_unit_did_not_change(make_repo, raw, git_for):
    repo = make_repo()
    header = '"""Pricing tests."""\n\nimport pytest\n\nfrom pytdd import pricing\n\nrequires_x = pytest.mark.slow\n'
    body = "\n\ndef test_a():\n    assert pricing\n"
    base = commit(raw, repo, {
        "tests/test_a.py": header + body, "tests/unit/test_b.py": "import os\n" + body,
        "tests/test_l4_audit_c_00000001_r1.py": "# generated\n" + body, "src/mod.py": "x = 1\n",
    }, "base")  # fmt: skip
    git = git_for(repo)
    path, text = base_test_header(git, base, changed=["tests/test_a.py"], near="tests/test_l4_audit_c_00000002_r1.py")
    assert path != "tests/test_a.py" and path == "tests/unit/test_b.py" and text == "import os\n"  # the unit changed a
    path, text = base_test_header(git, base, changed=[], near="tests/test_l4_audit_c_00000002_r1.py")
    assert path == "tests/test_a.py" and text.endswith("requires_x = pytest.mark.slow\n") and "def test_a" not in text
    assert base_test_header(git, base, changed=["tests/test_a.py", "tests/unit/test_b.py"], near="tests/x.py") is None
    long = "".join(f"import mod{i}\n" for i in range(80)) + body
    big = commit(raw, repo, {"tests/test_c.py": long, "tests/test_a.py": "", "tests/unit/test_b.py": ""}, "long")
    _, cut = base_test_header(git_for(repo), big, changed=[], near="tests/test_x.py")
    assert len(cut.splitlines()) == 40


LABEL = "(e2e support file at the merge base"
E2E_CONFTEST = (
    "import pytest\n\n\ndef login(page):\n    page.goto('/login')\n\n\n@pytest.fixture\ndef users():\n    return {}\n"
)


def test_the_writer_is_shown_the_conftest_and_the_helpers_of_the_suite_at_the_base(
    make_repo, raw, git_for
):  # SCN-VER-304
    repo = make_repo()
    base = commit(raw, repo, {
        "e2e/conftest.py": E2E_CONFTEST, "e2e/helpers/a11y.py": "def no_violations(page):\n    pass\n",
        "e2e/test_sign_in.py": "def test_x():\n    pass\n", "e2e/pages/x_test.py": "def test_y():\n    pass\n",
    }, "base")  # fmt: skip
    commit(
        raw, repo, {"e2e/conftest.py": "# the unit's version\n", "e2e/helpers.py": "def mine():\n    pass\n"}, "head"
    )
    support = e2e_support_files(git_for(repo), base)
    assert support.blocks == (
        (f"e2e/conftest.py {LABEL})", E2E_CONFTEST),
        (f"e2e/helpers/a11y.py {LABEL})", "def no_violations(page):\n    pass\n"),
    )
    assert support.shown == ("e2e/conftest.py", "e2e/helpers/a11y.py") and support.skipped == ()


def test_the_support_files_shown_are_bounded_and_the_rest_are_named(make_repo, raw, git_for):  # SCN-VER-305
    repo = make_repo()
    files = {"e2e/conftest.py": "x" * 30_000, **{f"e2e/h{i}.py": "y" * 5_000 for i in range(1, 10)}}
    support = e2e_support_files(git_for(repo), commit(raw, repo, files, "base"))
    labels = [label for label, _ in support.blocks]
    assert labels == [
        f"e2e/conftest.py {LABEL}, first 8000 characters)",
        f"e2e/h1.py {LABEL})",
        f"e2e/h2.py {LABEL})",
        "e2e support files not shown",
    ]
    assert len(support.blocks[0][1]) == 8_000 and len(support.blocks[1][1]) == 5_000
    assert support.blocks[-1][1].splitlines() == [f"e2e/h{i}.py" for i in range(3, 10)]
    assert support.shown == ("e2e/conftest.py", "e2e/h1.py", "e2e/h2.py")
    assert support.skipped == tuple(f"e2e/h{i}.py" for i in range(3, 10))
    small = {f"e2e/h{i}.py": "z" * 1_000 for i in range(1, 9)}
    other = make_repo("other")
    support = e2e_support_files(git_for(other), commit(raw, other, small, "small"))
    assert len(support.shown) == 6 and len(support.skipped) == 2 and len(support.blocks) == 7
    assert support.blocks[-1][0] == "e2e support files not shown"


def test_the_tree_is_listed_at_the_merge_base_and_not_at_head(make_repo, raw, git_for):  # SCN-VER-304
    repo = make_repo()
    base = commit(raw, repo, {"e2e/conftest.py": E2E_CONFTEST, "e2e/legacy.py": "def old():\n    pass\n"}, "base")
    raw(repo, "rm", "-q", "e2e/legacy.py")
    commit(raw, repo, {"e2e/new.py": "def mine():\n    pass\n"}, "the unit deletes a helper and adds one")
    support = e2e_support_files(git_for(repo), base)
    assert support.shown == ("e2e/conftest.py", "e2e/legacy.py")  # the deleted one is shown, the added one is not


def test_the_conftest_comes_first_whatever_the_names_beside_it(make_repo, raw, git_for):  # SCN-VER-304
    repo = make_repo()
    files = {"e2e/a.py": "def a():\n    pass\n", "e2e/conftest.py": E2E_CONFTEST, "e2e/b/c.py": "x = 1\n"}
    support = e2e_support_files(git_for(repo), commit(raw, repo, files, "base"))
    assert support.shown == ("e2e/conftest.py", "e2e/a.py", "e2e/b/c.py")


def test_the_file_that_does_not_fit_and_every_file_after_it_are_left_out(make_repo, raw, git_for):  # SCN-VER-305
    repo = make_repo()
    files = {
        "e2e/conftest.py": "x" * 8_000,  # whole
        "e2e/h1.py": "y" * 15_000,  # cut at 8,000: 16,000 in all
        "e2e/h2.py": "z" * 15_000,  # cut at 8,000: 24,000 would pass 20,000
        "e2e/h3.py": "w" * 100,  # would fit (16,100), and is left out all the same
    }
    support = e2e_support_files(git_for(repo), commit(raw, repo, files, "base"))
    assert support.shown == ("e2e/conftest.py", "e2e/h1.py")
    assert support.skipped == ("e2e/h2.py", "e2e/h3.py")
    assert support.blocks[-1] == ("e2e support files not shown", "e2e/h2.py\ne2e/h3.py")
    assert len(support.blocks[0][1]) == 8_000 and "first" not in support.blocks[0][0]


def test_nothing_after_a_file_that_is_left_out_is_read_and_the_list_of_them_is_bounded(
    make_repo, raw, git_for, monkeypatch
):  # SCN-VER-305
    from l4.verifier import conventions

    repo = make_repo()
    files = {"e2e/conftest.py": "x" * 8_000, **{f"e2e/h{i:02}.py": "y" * 8_000 for i in range(1, 31)}}
    base = commit(raw, repo, files, "base")
    reads: list[str] = []
    real = conventions._show
    monkeypatch.setattr(conventions, "_show", lambda git, sha, path: reads.append(path) or real(git, sha, path))
    support = e2e_support_files(git_for(repo), base)
    assert support.shown == ("e2e/conftest.py", "e2e/h01.py")
    assert reads == ["e2e/conftest.py", "e2e/h01.py", "e2e/h02.py"]  # h02 did not fit; h03 and the rest were not read
    assert len(support.skipped) == 29  # every one of them is skipped by rule
    label, text = support.blocks[-1]
    assert label == "e2e support files not shown"
    assert text.splitlines() == [*(f"e2e/h{i:02}.py" for i in range(2, 22)), "(+9 more)"]
    reads.clear()
    small = {"e2e/conftest.py": "x = 1\n", **{f"e2e/h{i:02}.py": "y = 1\n" for i in range(1, 11)}}
    other = make_repo("other")
    support = e2e_support_files(git_for(other), commit(raw, other, small, "small"))
    assert len(support.shown) == 6 and len(reads) == 6 and len(support.skipped) == 5  # the sixth file stops the reads


def test_a_suite_that_is_a_package_says_how_its_helpers_are_imported(make_repo, raw, git_for):
    repo = make_repo()
    files = {"e2e/__init__.py": "", "e2e/conftest.py": E2E_CONFTEST, "e2e/helpers/a11y.py": "def ok(page):\n    pass\n"}
    support = e2e_support_files(git_for(repo), commit(raw, repo, files, "base"))
    assert support.shown == ("e2e/conftest.py", "e2e/helpers/a11y.py")  # the empty __init__.py is not shown
    label, text = support.blocks[-1]
    assert label == "e2e suite layout" and "e2e/__init__.py" in text and "from e2e.conftest import" in text
    assert "\n" not in text  # one line
    plain = make_repo("plain")
    support = e2e_support_files(git_for(plain), commit(raw, plain, {"e2e/conftest.py": E2E_CONFTEST}, "base"))
    assert all(label != "e2e suite layout" for label, _ in support.blocks)


def test_what_is_not_a_support_file_of_the_suite_is_not_shown(make_repo, raw, git_for):  # SCN-VER-306
    repo = make_repo()
    git = git_for(repo)
    assert e2e_support_files(git, raw(repo, "rev-parse", "HEAD").strip()).blocks == ()  # no e2e/ at all
    (repo / "e2e").mkdir()
    os.symlink("../README.md", repo / "e2e" / "link.py")
    for rel in ("e2e/test_a.py", "e2e/b_test.py", "e2e/test_l4_c_de7f2d3f.py"):
        (repo / rel).write_text("def test_x():\n    pass\n")
    (repo / "e2e/__init__.py").write_text("\n  \n")
    for rel in ("e2e/.venv/x.py", "e2e/__pycache__/y.py", "e2e/node_modules/z.py", "e2e/admin/conftest.py"):
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text("x = 1\n")
    (repo / "e2e/data.txt").write_text("not python\n")
    raw(repo, "add", "-A", "-f")
    raw(repo, "commit", "-q", "-m", "base")
    base = raw(repo, "rev-parse", "HEAD").strip()
    assert "120000" in raw(repo, "ls-tree", "-r", base, "--", "e2e/link.py")  # the link is in the tree
    commit(raw, repo, {"e2e/helpers.py": "def mine():\n    pass\n"}, "the unit adds a helper")
    support = e2e_support_files(git, base)
    assert support.blocks == () and support.shown == () and support.skipped == ()
