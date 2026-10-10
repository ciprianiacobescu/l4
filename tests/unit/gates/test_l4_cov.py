"""The `l4_cov` pytest plugin, run for real in a pytest subprocess over a copy of the py_multi head."""

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from l4.gates.coverage import cov_env, junit_ids, merge_pytest_env, plugin_dir, write_rc
from l4.gates.junit import parse_junit

from ..evidence._multi import build_repo


@pytest.fixture(scope="module")
def head_repo(tmp_path_factory: pytest.TempPathFactory) -> Path:
    repo = tmp_path_factory.mktemp("multi") / "repo"
    git, units = build_repo(repo)
    git.run("checkout", "--quiet", "--detach", units[-1].head)
    return repo


def run_pytest(repo: Path, out: Path, *args: str, extra_env: dict[str, str] | None = None, packages=("src/shop",)):
    env = {k: v for k, v in os.environ.items() if k not in ("PYTEST_ADDOPTS", "PYTHONPATH")}
    env.update(merge_pytest_env(cov_env(out, packages), extra_env or {}))
    argv = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", f"--junitxml={out}/junit.xml", *args]
    return subprocess.run(argv, cwd=repo, env=env, capture_output=True, text=True)


def read(out: Path) -> tuple[dict, dict]:
    return json.loads((out / "status.json").read_text()), json.loads((out / "coverage.json").read_text())


def test_real_pytest_writes_json_with_test_contexts(head_repo: Path, tmp_path: Path):
    out = tmp_path / "cov"
    done = run_pytest(head_repo, out, packages=("src/shop", "src/inventory"))
    assert done.returncode == 0, done.stdout
    status, cov = read(out)
    assert status["status"] == "ok" and status["coverage_version"] == cov["meta"]["version"]
    assert status["nonce"] and status["nonce"] == (out / "nonce").read_text()  # this run's, recorded by cov_env
    pricing = cov["files"]["src/shop/pricing.py"]
    assert pricing["missing_lines"] == [] and pricing["executed_lines"]
    contexts = {c for ctxs in pricing["contexts"].values() for c in ctxs}
    assert "test_discount.test_save10_takes_ten_percent" in contexts  # the module as imported, not the nodeid
    assert "test_bulk.test_fewer_than_ten_pay_full_price" in contexts
    ids = set(parse_junit(out / "junit.xml").tests)
    assert junit_ids({"test_discount.test_save10_takes_ten_percent"}, ids) == {
        "tests.test_discount::test_save10_takes_ten_percent"
    }
    assert "src/inventory/alerts.py" in cov["files"]


def test_pragma_no_cover_is_still_measured(head_repo: Path, tmp_path: Path):
    work = tmp_path / "work"
    work.mkdir()
    (work / "mod").mkdir()
    (work / "mod" / "__init__.py").write_text("")
    (work / "mod" / "x.py").write_text(
        "def f():\n    return 1  # pragma: no cover\n\n\ndef g():\n    return 2  # pragma: no cover\n"
    )
    (work / "test_x.py").write_text("from mod.x import f\n\n\ndef test_f():\n    assert f() == 1\n")
    out = tmp_path / "cov"
    assert run_pytest(work, out, packages=("mod",)).returncode == 0
    _, cov = read(out)
    lines = cov["files"]["mod/x.py"]
    assert 6 in lines["missing_lines"] and 2 in lines["executed_lines"]


def test_repo_coveragerc_and_pyproject_are_ignored(head_repo: Path, tmp_path: Path):
    work = tmp_path / "work"
    work.mkdir()
    (work / "mod").mkdir()
    (work / "mod" / "__init__.py").write_text("")
    (work / "mod" / "x.py").write_text("def f():\n    return 1\n")
    (work / "test_x.py").write_text("from mod.x import f\n\n\ndef test_f():\n    assert f() == 1\n")
    (work / ".coveragerc").write_text(
        "[run]\nomit = mod/*\ndata_file = /nonexistent/dir/.cov\n[report]\nfail_under=100\n"
    )
    (work / "pyproject.toml").write_text("[tool.coverage.run]\nomit = ['mod/*']\n")
    out = tmp_path / "cov"
    assert run_pytest(work, out, packages=("mod",)).returncode == 0
    _, cov = read(out)
    assert "mod/x.py" in cov["files"] and not (work / ".coverage").exists()


def stub_plugin(directory: Path, name: str, body: str = "") -> None:
    directory.mkdir(exist_ok=True)
    (directory / f"{name}.py").write_text(body)


def test_pytest_cov_active_is_not_run_and_tests_unchanged(head_repo: Path, tmp_path: Path):
    stub = tmp_path / "stub"
    stub_plugin(stub, "pytest_cov")  # a plugin of that name is what `-p pytest_cov` registers
    out_plain, out_cov = tmp_path / "plain", tmp_path / "cov"
    plain = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=head_repo, capture_output=True, text=True
    )
    done = run_pytest(head_repo, out_cov, "-p", "pytest_cov", extra_env={"PYTHONPATH": str(stub), "PYTEST_ADDOPTS": ""})
    del out_plain
    assert done.returncode == plain.returncode == 0
    status = json.loads((out_cov / "status.json").read_text())
    assert status["status"] == "not_run" and "pytest-cov" in status["reason"]
    assert not (out_cov / "coverage.json").exists()


def test_coverage_not_importable_is_not_run(head_repo: Path, tmp_path: Path):
    stub = tmp_path / "stub"
    stub_plugin(stub, "coverage", "raise ImportError('hidden by the test')\n")
    out = tmp_path / "cov"
    done = run_pytest(head_repo, out, extra_env={"PYTHONPATH": str(stub)})
    assert done.returncode == 0
    status = json.loads((out / "status.json").read_text())
    assert status["status"] == "not_run" and "coverage" in status["reason"]


def test_plugin_crash_never_changes_outcomes(head_repo: Path, tmp_path: Path):
    out = tmp_path / "cov"
    env = merge_pytest_env(cov_env(out, ("src/shop",)), {})
    (out / "coveragerc").write_text("[run\nbroken")  # unreadable rc: the plugin must swallow it
    full = {**os.environ, **env}
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"], cwd=head_repo, env=full,
        capture_output=True, text=True,
    )  # fmt: skip
    assert done.returncode == 0, done.stdout + done.stderr
    assert json.loads((out / "status.json").read_text())["status"] == "not_run"
    failing = tmp_path / "failing"
    failing.mkdir()
    (failing / "test_f.py").write_text("def test_f():\n    assert False\n")
    out2 = tmp_path / "cov2"
    assert run_pytest(failing, out2, packages=("nothing_here",)).returncode == 1  # still fails, still reports


def test_merge_keeps_both_plugins():
    merged = merge_pytest_env(
        {"PYTEST_ADDOPTS": "-p l4_trace", "PYTHONPATH": "/a", "X": "1"},
        {"PYTEST_ADDOPTS": "-p l4_cov", "PYTHONPATH": "/b", "X": "2"},
    )
    assert merged["PYTEST_ADDOPTS"] == "-p l4_trace -p l4_cov"
    assert merged["PYTHONPATH"] == f"/a{os.pathsep}/b" and merged["X"] == "2"
    assert merge_pytest_env() == {}


def test_rc_text_disables_exclusions_and_sets_contexts(tmp_path: Path):
    rc = write_rc(tmp_path, ["src/shop"]).read_text()
    assert "dynamic_context = test_function" in rc and "exclude_lines =" in rc and "relative_files = True" in rc
    assert plugin_dir().joinpath("l4_cov.py").is_file()
    assert textwrap.dedent(rc).count("source") >= 1


def test_xdist_controller_is_not_run(tmp_path: Path):
    import importlib.util
    from types import SimpleNamespace

    spec = importlib.util.spec_from_file_location("l4_cov_under_test", plugin_dir() / "l4_cov.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    stopped = []
    mod._active.update(cov=SimpleNamespace(stop=lambda: stopped.append(1)), out=tmp_path)
    mod.pytest_configure(SimpleNamespace(option=SimpleNamespace(numprocesses=4, dist="load")))
    assert stopped and json.loads((tmp_path / "status.json").read_text())["status"] == "not_run"


def test_a_child_pytest_cannot_clobber_the_parents_measurement(tmp_path: Path):
    work = tmp_path / "work"
    (work / "mod").mkdir(parents=True)
    (work / "mod" / "__init__.py").write_text("")
    (work / "mod" / "x.py").write_text("def f():\n    return 1\n\n\ndef g():\n    return 2\n")
    (work / "test_a.py").write_text("from mod.x import f\n\n\ndef test_a():\n    assert f() == 1\n")
    (work / "test_b.py").write_text(
        "import subprocess, sys\n\n\ndef test_b():\n"
        "    cmd = [sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', 'test_c.py']\n"
        "    subprocess.run(cmd, check=True)\n"
    )
    (work / "test_c.py").write_text("def test_c():\n    assert True\n")
    out = tmp_path / "cov"
    done = run_pytest(work, out, "test_a.py", "test_b.py", packages=("mod",))
    assert done.returncode == 0, done.stdout
    status, cov = read(out)
    assert status["status"] == "ok"
    assert 2 in cov["files"]["mod/x.py"]["executed_lines"], "the child's erase() lost the parent's data"


@pytest.mark.parametrize("bad", ["src/a\nomit = *", "src/a\rx", "[report]", "#x", ";x"])
def test_write_rc_refuses_unsafe_package_names(tmp_path: Path, bad: str):
    with pytest.raises(ValueError):
        write_rc(tmp_path, [bad])


def test_write_rc_includes_namespace_packages_and_escapes_dollar(tmp_path: Path):
    rc = write_rc(tmp_path, ["src/a$b"]).read_text()
    assert "include_namespace_packages = True" in rc and "src/a$$b" in rc


def test_cov_env_clears_the_output_of_an_earlier_round(tmp_path: Path):
    for name in ("status.json", "coverage.json", ".coverage", ".coverage.x", "nonce"):
        (tmp_path / name).write_text("old")
    first = cov_env(tmp_path, ["src"])
    assert [p.name for p in sorted(tmp_path.iterdir())] == ["coveragerc", "nonce"]
    assert (tmp_path / "nonce").read_text() == first["L4_COV_NONCE"] != cov_env(tmp_path, ["src"])["L4_COV_NONCE"]


FAKE_COVERAGE = """
import json
from pathlib import Path

__version__ = "0.0-fake"


class Coverage:
    def __init__(self, config_file=None, **kw):
        pass

    def erase(self):
        pass

    def start(self):
        pass

    def stop(self):
        pass

    def save(self):
        pass

    def json_report(self, outfile=None, **kw):
        data = {"meta": {"version": __version__}, "files": {"mod/x.py": {"executed_lines": [1, 2, 3, 4, 5, 6],
                "missing_lines": [], "contexts": {}}}}
        Path(outfile).write_text(json.dumps(data))
        return 100.0
"""


@pytest.mark.parametrize("where", ["coverage.py", "coverage/__init__.py", "src/coverage/__init__.py"])
def test_a_repository_module_named_coverage_never_stands_in_for_coverage_py(tmp_path: Path, where: str):
    """The gate runs `python -m pytest` from the root, which puts the root (and an ini `pythonpath`) before the
    interpreter's site-packages: a repository `coverage` module would be imported and write any report it likes."""
    work = tmp_path / "work"
    (work / "mod").mkdir(parents=True)
    (work / "mod" / "__init__.py").write_text("")
    (work / "mod" / "x.py").write_text("def f():\n    return 1\n\n\ndef g():\n    return 2\n")
    (work / "test_x.py").write_text("from mod.x import f\n\n\ndef test_f():\n    assert f() == 1\n")
    (work / "pytest.ini").write_text("[pytest]\npythonpath = src\n")
    (work / where).parent.mkdir(parents=True, exist_ok=True)
    (work / where).write_text(FAKE_COVERAGE)
    out = tmp_path / "cov"
    done = run_pytest(work, out, packages=("mod",))
    assert done.returncode == 0, done.stdout + done.stderr
    status = json.loads((out / "status.json").read_text())
    assert status["status"] == "ok" and status["coverage_version"] != "0.0-fake", status
    _, cov = read(out)
    assert 6 in cov["files"]["mod/x.py"]["missing_lines"]  # g's body never ran: the real coverage.py measured it
