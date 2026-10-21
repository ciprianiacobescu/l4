"""Step 1's content scan against the harness's two pytest plugins (M1.6 join review): a repository module that
shadows `l4_cov` or `l4_trace`, code that names the coverage plugin or its output directory, and the pytest 9 runner
config files (`pytest.toml`, `.pytest.toml`, `.pytest.ini`)."""

import pytest

from l4.verifier.integrity import check_freeze, check_scan
from l4.verifier.types import Severity

from ._integrity_helpers import UNIT, event, new_repo, task


@pytest.mark.parametrize(
    "path",
    [
        "l4_cov.py",  # the gate runs `python -m pytest` from the root: the root is first on sys.path
        "tests/plugins/l4_cov.py",
        "l4_cov/__init__.py",
        "l4_trace/__init__.py",
        "l4_cov.cpython-312-x86_64-linux-gnu.so",
    ],
)
def test_a_module_that_shadows_a_harness_plugin_is_a_hit(tmp_path, git_environ, path):
    repo, base = new_repo(tmp_path, git_environ)
    repo.write({path: ""})
    [finding] = check_scan(repo.context(base, repo.commit("plugin"))).findings
    assert finding.severity is Severity.BLOCKER and path in finding.detail


@pytest.mark.parametrize("path", ["l4_coverage.py", "docs/l4_cov.md", "src/app/l4_cov_notes/readme.txt"])
def test_a_name_that_only_looks_like_a_plugin_is_not_a_hit(tmp_path, git_environ, path):
    repo, base = new_repo(tmp_path, git_environ)
    repo.write({path: "X = 1\n"})
    assert not check_scan(repo.context(base, repo.commit("work"))).findings


FORGE = 'from pathlib import Path\n\nOUT = Path(".l4-out") / "cov"\n'


@pytest.mark.parametrize(
    "path,text",
    [
        ("tests/conftest.py", FORGE),
        ("tests/test_cart.py", FORGE + "\n\ndef test_a():\n    assert OUT\n"),
        ("src/shop/cart.py", FORGE),  # production code can forge at exit too
        ("src/shop/hook.py", "import os\n\nRC = os.environ.get('L4_COV_RC')\n"),
        ("tests/conftest.py", "import sys\n\nPLUGIN = sys.modules.get('l4_cov')\n"),
    ],
)
def test_code_that_names_the_coverage_plugin_or_its_output_is_a_hit(tmp_path, git_environ, path, text):
    repo, base = new_repo(tmp_path, git_environ)
    repo.write({path: text})
    [finding] = check_scan(repo.context(base, repo.commit("work"))).findings
    assert finding.severity is Severity.BLOCKER and path in finding.detail and "coverage plugin" in finding.detail


def test_a_mention_the_base_already_had_or_a_non_python_file_is_not_a_hit(tmp_path, git_environ):
    repo, base = new_repo(tmp_path, git_environ, {"tests/conftest.py": FORGE})
    repo.write({"tests/conftest.py": FORGE + "\nX = 1\n", ".gitignore": ".l4-out/\n", "Makefile": "L4_COV=1\n"})
    assert not check_scan(repo.context(base, repo.commit("edit"))).findings


def test_other_harness_output_is_not_a_hit(tmp_path, git_environ):
    """A serve wrapper's pid file or a JUnit path under `.l4-out` is not the coverage output."""
    repo, base = new_repo(tmp_path, git_environ)
    repo.write({"serve.py": 'open(".l4-out/serve.pid", "w").write("1")\nREPORT = ".l4-out/junit.xml"\n'})
    assert not check_scan(repo.context(base, repo.commit("serve"))).findings


def test_a_test_infra_task_may_name_the_output_directory(tmp_path, git_environ):
    repo, base = new_repo(tmp_path, git_environ)
    repo.write({"tests/conftest.py": FORGE})
    head = repo.commit("infra", task="2.1", tdd="green")
    assert not check_scan(repo.context(base, head, tasks=[(UNIT, task("2.1", "Report [test-infra]"))])).findings


@pytest.mark.parametrize(
    "path,text",
    [
        ("pytest.toml", '[pytest]\naddopts = ["-p", "tools.fake"]\n'),
        (".pytest.toml", '[pytest]\naddopts = ["-p", "tools.fake"]\n'),
        (".pytest.ini", "[pytest]\naddopts = -p tools.fake\n"),
    ],
)
def test_pytest_9_config_files_are_runner_config(tmp_path, git_environ, path, text):
    repo, base = new_repo(tmp_path, git_environ)
    repo.write({path: text})
    [finding] = check_scan(repo.context(base, repo.commit("config"))).findings
    assert f"{path}: adds the option -p" in finding.detail


def test_a_pytest_toml_changed_between_red_and_green_is_a_blocker(tmp_path, git_environ):
    repo, base = new_repo(tmp_path, git_environ, {"pytest.toml": '[pytest]\ntestpaths = ["tests"]\n'})
    repo.write({"tests/test_a.py": "def test_a():\n    assert 0\n"})
    red = repo.commit("red", task="1.1", tdd="red")
    repo.write({"pytest.toml": '[pytest]\ntestpaths = ["tests"]\nxfail_strict = false\n'})
    green = repo.commit("green", task="1.1", tdd="green")
    repo.events += [
        event("task.red_ok", 1, task="1.1", sha=red, frozen=["tests/test_a.py"]),
        event("task.done", 2, task="1.1", sha=green),
    ]
    findings = check_freeze(repo.context(base, green)).findings
    assert [f.title for f in findings] == ["the test runner configuration changed between red and green"]
    assert "pytest.toml" in findings[0].detail


@pytest.mark.parametrize("path", ["coverage.py", "coverage/__init__.py", "src/coverage/__init__.py", "lib/coverage.py"])
def test_a_top_level_module_named_coverage_is_a_hit(tmp_path, git_environ, path):
    """`l4_cov` imports the project's coverage.py; a top-level `coverage` of the repository (the root, or a module
    root that an ini `pythonpath` names) would be imported instead."""
    repo, base = new_repo(tmp_path, git_environ)
    repo.write({path: ""})
    [finding] = check_scan(repo.context(base, repo.commit("coverage"))).findings
    assert f"{path}: a module named coverage" in finding.detail


@pytest.mark.parametrize("path", ["src/shop/coverage.py", "src/insurance/coverage/__init__.py", "docs/coverage.md"])
def test_a_submodule_named_coverage_is_not_a_hit(tmp_path, git_environ, path):
    repo, base = new_repo(tmp_path, git_environ)
    repo.write({path: "X = 1\n"})
    assert not check_scan(repo.context(base, repo.commit("domain"))).findings
