"""Join line 12: `Workbench.run_gate(extra_env=)` composes the coverage plugin with the trace plugin in one gate run."""

import sys

from l4.evidence.collect import read_coverage
from l4.gates.coverage import cov_env
from l4.gates.trace import trace_env

TEST = (
    "import pytest\n\nfrom pytdd.pricing import total\n\n\n"
    "@pytest.mark.l4('C-aaaaaaaa')\ndef test_total():\n    assert total([1.0, 2.0]) == 3.0\n"
)
COMMAND = f"{sys.executable} -m pytest -q -p no:cacheprovider -o junit_family=xunit1 --junitxml=.l4-out/junit.xml"


def _gate(bench, extra_env=None):
    wb = bench.wb
    (wb.worktree / "tests" / "test_marked.py").write_text(TEST)
    return wb.run_gate("test", COMMAND, reports=[".l4-out/junit.xml"], extra_env=extra_env)


def test_trace_and_cov_plugins_both_load_in_one_gate_run(make_bench):
    bench = make_bench([])
    cov_dir = bench.wb.worktree / ".l4-out" / "cov"
    env = cov_env(cov_dir, ["src/pytdd"])
    result = _gate(bench, env)
    assert result.status == "pass", result.reason
    assert result.report.tests["tests.test_marked::test_total"].criteria == ("C-aaaaaaaa",)  # l4_trace loaded
    cov, status = read_coverage(cov_dir, env["L4_COV_NONCE"])  # l4_cov loaded, the env got through the allow-list
    assert status["status"] == "ok" and cov is not None
    assert "src/pytdd/pricing.py" in cov["files"]


def test_without_extra_env_only_the_trace_plugin_loads(make_bench):
    bench = make_bench([])
    result = _gate(bench)
    assert result.status == "pass"
    assert result.report.tests["tests.test_marked::test_total"].criteria == ("C-aaaaaaaa",)
    assert not (bench.wb.worktree / ".l4-out" / "cov").exists()
    assert trace_env()["PYTEST_ADDOPTS"] == "-p l4_trace"
