"""detect-test-tamper 9.1 (L4-VER-033, design D15): `L4_COLLECT_ONLY` makes the harness's own pytest plugin collect only
the listed Python files (and still load every conftest.py), whatever the configured command."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from l4.gates.junit import parse_junit
from l4.gates.trace import trace_env
from l4.verifier.support_base import collect_only_env

FILES = {
    "tests/test_a.py": "def test_a():\n    assert True\n",
    "tests/test_b.py": "def test_b():\n    assert True\n",
    "tests/test_c.py": "def test_c():\n    assert True\n",
    "tests/conftest.py": "def pytest_report_header(config):\n    return 'CONFTEST LOADED'\n",
}


def project(tmp_path: Path) -> Path:
    for rel, text in FILES.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    return tmp_path


def run(root: Path, *args: str, only: list[str] | None = None) -> tuple[set[str], str]:
    env = {"PATH": "/usr/bin:/bin", **trace_env(), **(collect_only_env(only) if only is not None else {})}
    report = root / "junit.xml"
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-o", "junit_family=xunit1"]
        + [f"--junitxml={report}", *args],
        cwd=root, env=env, capture_output=True, text=True,
    )  # fmt: skip
    ids = set(parse_junit(report).tests) if report.exists() else set()
    return {i.split("::")[-1] for i in ids}, done.stdout + done.stderr


def test_collect_only_env_joins_the_paths():
    assert collect_only_env(["tests/a.py", "tests/b.py"]) == {
        "L4_COLLECT_ONLY": os.pathsep.join(["tests/a.py", "tests/b.py"])
    }
    assert collect_only_env([]) == {"L4_COLLECT_ONLY": ""}


def test_without_the_variable_every_file_is_collected(tmp_path: Path):
    names, _ = run(project(tmp_path))
    assert names == {"test_a", "test_b", "test_c"}


@pytest.mark.parametrize("args", [(), ("tests/",)])
def test_only_the_listed_file_is_collected_and_the_conftest_still_loads(tmp_path: Path, args):
    names, out = run(project(tmp_path), *args, only=["tests/test_b.py"])
    assert names == {"test_b"}
    assert "CONFTEST LOADED" in out


def test_an_explicitly_named_file_is_collected_whatever_the_hook_says(tmp_path: Path):
    """Recorded for pytest 9.1 (design D15): a file named on the command line is collected although it is not listed,
    so the audit does not rely on the hook for that form. It relies on setting the unit's own test files aside."""
    names, _ = run(project(tmp_path), "tests/test_a.py", only=["tests/test_b.py"])
    assert names == {"test_a"}
    names, _ = run(project(tmp_path), "tests/test_a.py", "tests/test_b.py", only=["tests/test_b.py"])
    assert names == {"test_a", "test_b"}


def test_several_listed_files_are_all_collected(tmp_path: Path):
    names, _ = run(project(tmp_path), only=["tests/test_a.py", "tests/test_c.py"])
    assert names == {"test_a", "test_c"}


def test_an_empty_list_collects_no_python_test_file(tmp_path: Path):
    names, _ = run(project(tmp_path), only=[])
    assert names == set()
