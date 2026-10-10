# ruff: noqa: F811
"""Join review: an implementer that games the diff-coverage evidence. Every attempt runs through `l4 run` on `py_multi`
(real git, a real pytest with `l4_cov` loaded by the gate, a scripted agent) next to an added function `describe` that
no test runs. None may come out `covered` with a clean PASS: step 1 fails the unit, or coverage says `uncovered` and
holds. Two outcomes are recorded as they are: an unregistered plugin is `not_run`, a hold only under `fail` (D4), and an
in-process forgery that never names the plugin still passes (the SC-03-class hole of the plan's Risks section)."""

import json

import pytest

from .test_ladder_evidence import (  # noqa: F401  (fixtures and scripts)
    EXTRA_FUNCTION,
    GREEN,
    TESTS,
    evidence,
    green,
    judge,
    multi,
    red,
    report,
    run_multi,
)

UNTESTED = {"src/shop/cart.py": GREEN + EXTRA_FUNCTION}


def _forge(out_dir: str) -> str:
    """A conftest body that rewrites coverage.json and status.json at interpreter exit, after the plugin wrote them,
    with the nonce `cov_env` left in the directory: every changed line of `src/shop/cart.py` "ran"."""
    return f"""
import atexit
import hashlib
import json
from pathlib import Path


def _forge():
    out = {out_dir}
    if not (out / "nonce").exists():
        return
    import coverage

    lines = len(Path("src/shop/cart.py").read_text().splitlines())
    data = {{"meta": {{"version": coverage.__version__}}, "files": {{"src/shop/cart.py": {{
        "executed_lines": list(range(1, lines + 1)), "missing_lines": [], "contexts": {{}}}}}}}}
    body = json.dumps(data).encode()
    (out / "coverage.json").write_bytes(body)
    (out / "status.json").write_text(json.dumps({{
        "status": "ok", "reason": "", "nonce": (out / "nonce").read_text(),
        "coverage_version": coverage.__version__, "json_sha256": hashlib.sha256(body).hexdigest()}}))


atexit.register(_forge)
"""


FORGE = _forge('Path(".l4-out") / "cov"')
HIDDEN_FORGE = _forge('Path("." + "l4" + "-out") / "cov"')  # never names the directory
DISABLE = """
def pytest_configure(config):
    plugin = config.pluginmanager.get_plugin({name})
    if plugin is not None:
        config.pluginmanager.unregister(plugin)
"""
PRAGMA = EXTRA_FUNCTION.replace("def describe(lines):", "def describe(lines):  # pragma: no cover")


def red_with(files: dict[str, str]):
    step = red(TESTS)
    step.writes.update(files)  # red may add test-support files; they are frozen from then on
    return step


def functions(run) -> dict[str, str]:
    return {f["qualname"]: f["status"] for f in (evidence(run)["diff_coverage"] or {}).get("functions", [])}


def failed_at_step_1(run, detail: str) -> None:
    assert run.code == 10 and run.outcome["units"][0]["verdict"] == "FAIL"
    text = report(run)
    assert "| 1 | integrity | failed |" in text and detail in text, text
    assert evidence(run)["diff_coverage"] is None  # the ladder stopped before the test run


def test_a_conftest_from_red_that_forges_the_coverage_output_fails_the_unit(run_multi):
    run = run_multi([red_with({"tests/conftest.py": FORGE}), green(UNTESTED), judge()])
    failed_at_step_1(run, "tests/conftest.py: names the coverage plugin or its output (.l4-out/cov)")


def test_a_conftest_written_in_green_is_removed_and_coverage_holds(run_multi):
    run = run_multi([red(), green({**UNTESTED, "tests/conftest.py": FORGE}), judge()])
    assert run.code == 11 and functions(run)["describe"] == "uncovered"  # the green guard removed the new conftest


def test_production_code_that_forges_at_exit_fails_the_unit(run_multi):
    hook = "\n\nimport sys as _sys\n\nif 'pytest' in _sys.modules:\n" + "\n".join(
        "    " + line if line else "" for line in FORGE.strip().splitlines()
    ) + "\n"  # fmt: skip
    run = run_multi([red(), green({"src/shop/cart.py": GREEN + EXTRA_FUNCTION + hook}), judge()])
    failed_at_step_1(run, "src/shop/cart.py: names the coverage plugin or its output (.l4-out/cov)")


def test_a_root_module_named_l4_cov_shadows_the_plugin_and_fails_the_unit(run_multi):
    run = run_multi([red(), green({**UNTESTED, "l4_cov.py": ""}), judge()])  # an empty plugin: nothing is measured
    failed_at_step_1(run, "l4_cov.py: a module named l4_cov")


FAKE_COVERAGE = """
import json
from pathlib import Path

__version__ = "7.16.2"


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
        lines = len(Path("src/shop/cart.py").read_text().splitlines())
        data = {"meta": {"version": __version__}, "files": {"src/shop/cart.py": {
            "executed_lines": list(range(1, lines + 1)), "missing_lines": [], "contexts": {}}}}
        Path(outfile).write_text(json.dumps(data))
        return 100.0
"""


def test_a_root_module_named_coverage_shadows_coverage_py_and_fails_the_unit(run_multi):
    """It names nothing of the harness: before the fix the root `coverage.py` wrote the report and the unit passed."""
    run = run_multi([red(), green({**UNTESTED, "coverage.py": FAKE_COVERAGE}), judge()])
    failed_at_step_1(run, "coverage.py: a module named coverage")


def test_a_conftest_that_unregisters_the_plugin_by_name_fails_the_unit(run_multi):
    run = run_multi([red_with({"tests/conftest.py": DISABLE.format(name='"l4_cov"')}), green(UNTESTED), judge()])
    failed_at_step_1(run, "tests/conftest.py: names the coverage plugin or its output (l4_cov)")


@pytest.mark.parametrize("mode,code", [("warn", 0), ("fail", 11)])
def test_an_unregistered_plugin_is_not_run_a_hold_only_under_fail(run_multi, mode, code):
    """D4 as built: `not_run` is a note under `warn` (the default) and a hold under `fail`. The Evidence section says
    so where a reader looks first."""
    hidden = DISABLE.format(name='"l4_" + "cov"')
    run = run_multi([red_with({"tests/conftest.py": hidden}), green(UNTESTED), judge()], coverage=mode)
    assert run.code == code and functions(run)["describe"] == "not_run"
    text = report(run)
    attention = text[text.index("### Needs attention") : text.index("### Files")]
    assert "diff coverage not measured: the coverage plugin wrote no status" in attention


@pytest.mark.parametrize(
    "path,text",
    [
        ("pytest.ini", "[pytest]\ntestpaths = tests\npythonpath = src\naddopts = -p no:l4_cov\n"),
        ("pytest.toml", '[pytest]\ntestpaths = ["tests"]\npythonpath = ["src"]\naddopts = ["-p", "tools.quiet"]\n'),
    ],
)
def test_runner_config_that_adds_a_plugin_option_fails_the_unit(run_multi, path, text):
    files = {**UNTESTED, path: text, "tools/__init__.py": "", "tools/quiet.py": "X = 1\n"}
    run = run_multi([red(), green(files), judge()])
    failed_at_step_1(run, f"{path}: adds the option -p")


def test_pyproject_addopts_that_blocks_the_plugin_fails_the_unit(run_multi, multi):
    text = (
        (multi.repo / "pyproject.toml")
        .read_text()
        .replace("[tool.pytest.ini_options]\n", '[tool.pytest.ini_options]\naddopts = "-p no:l4_cov"\n')
    )
    run = run_multi([red(), green({**UNTESTED, "pyproject.toml": text}), judge()])
    failed_at_step_1(run, "pyproject.toml: adds the option -p")


def test_a_pragma_no_cover_does_not_hide_the_untested_function(run_multi):
    run = run_multi([red(), green({"src/shop/cart.py": GREEN + PRAGMA}), judge()])
    assert run.code == 11 and functions(run)["describe"] == "uncovered"
    [hold] = evidence(run)["holds"]
    assert hold["subjects"] == ["src/shop/cart.py::describe"]


@pytest.mark.xfail(strict=True, reason="SC-03-class hole (m16-plan Risks): in-process forgery that never names the "
                   "plugin or its directory is not detected")  # fmt: skip
def test_residual_a_forgery_that_never_names_the_plugin_still_passes(run_multi):
    run = run_multi([red_with({"tests/conftest.py": HIDDEN_FORGE}), green(UNTESTED), judge()])
    assert functions(run)["describe"] != "covered", json.dumps(evidence(run)["diff_coverage"])
