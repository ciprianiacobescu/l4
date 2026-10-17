"""Configuration is put back after every gate run, in the implementer and the verifier (L4-IMP-040 part f, D7):
a test that rewrites `ruff.toml` while the test gate runs must not change what the lint gate that follows judges."""

from l4.agents.fake import Step
from l4.gates.runner import GateSpec
from l4.implementer.tdd import run_red, run_setup
from l4.specs.base import Task

from ..conftest import TEST_COMMAND
from .conftest import HEADER, KNOWN, STUB, result
from .test_gate_config_guard import commit_base, committed, violations

TASK = Task("1.1", "1.1", "1.1 Add `apply_discount`", False, " ", 0, 3, 3)
RUFF = "line-length = 100\n"
LINT = (
    "sh -c 'if grep -q ALL ruff.toml; then exit 0; fi; "
    "if grep -q LINTBAD tests/test_discount.py; then echo E999 lint error in test; exit 1; fi'"
)
LOOSENING_TEST = (
    HEADER
    + f'@pytest.mark.l4("{KNOWN}")\ndef test_known_code():\n'
    + '    with open("ruff.toml", "a") as handle:\n        handle.write(\'ignore = ["ALL"]\\n\')\n'
    + '    assert apply_discount(50.0, "SAVE10") == 45.0\n\n# LINTBAD\n'
)


def sh(script: str) -> str:
    return f"sh -c '{script}; exec {TEST_COMMAND}'"


def test_scn_imp_243_a_test_that_rewrites_ruff_toml_does_not_loosen_the_lint_gate(make_bench):
    bench = make_bench([], lint=[LINT])
    commit_base(bench, {"ruff.toml": RUFF})
    bench.adapter._script.append(
        Step(
            writes={"tests/test_discount.py": LOOSENING_TEST, "src/pytdd/pricing.py": STUB},
            structured=result("red", tests_added=["tests/test_discount.py::test_known_code"], criteria_ids=[KNOWN]),
        )
    )
    out = run_red(bench.wb, TASK, attempt=1)
    assert (bench.wb.worktree / "ruff.toml").read_text() == RUFF  # the bytes from before the test gate
    events = violations(bench, "gate configuration")
    assert events and {e["path"] for e in events} == {"ruff.toml"}
    assert events[0]["phase"] == "gate" and events[0]["where"] == "test" and events[0]["action"] == "restored"
    assert out.status == "failed" and "lint" in out.reason  # the lint gate judged the original settings


def test_a_gate_that_adds_a_new_mypy_ini_has_it_removed(make_bench):
    cmd = sh('printf "[mypy]\\nignore_errors = True\\n" > mypy.ini')
    bench = make_bench([], test={"command": cmd})
    run_setup(bench.wb)
    bench.wb.run_gate("test", cmd, reports=bench.wb.cfg.gates.test.reports)
    assert not (bench.wb.worktree / "mypy.ini").exists()
    (event,) = violations(bench, "gate configuration")
    assert event["path"] == "mypy.ini" and event["action"] == "removed" and event["where"] == "test"


def test_a_gate_that_changes_only_a_dependency_section_keeps_it(make_bench):
    cmd = sh('printf "\\n[tool.uv]\\ndev-dependencies = []\\n" >> pyproject.toml')
    bench = make_bench([], test={"command": cmd})
    run_setup(bench.wb)
    bench.wb.run_gate("test", cmd, reports=bench.wb.cfg.gates.test.reports)
    assert "[tool.uv]" in (bench.wb.worktree / "pyproject.toml").read_text()
    assert not violations(bench, "gate configuration") and not violations(bench, "runner configuration")


def test_a_gate_that_changes_a_pytest_setting_is_put_back_as_runner_configuration(make_bench):
    cmd = sh('printf "addopts = -q\\n" >> pytest.ini')
    bench = make_bench([], test={"command": cmd})
    commit_base(bench, {"pytest.ini": "[pytest]\npythonpath = src\n"})
    run_setup(bench.wb)
    bench.wb.run_gate("test", cmd, reports=bench.wb.cfg.gates.test.reports)
    assert committed(bench, "HEAD", "pytest.ini") == (bench.wb.worktree / "pytest.ini").read_text()
    (event,) = violations(bench, "runner configuration")
    assert event["phase"] == "gate" and event["path"] == "pytest.ini" and event["where"] == "test"


def test_the_verifiers_gates_on_another_checkout_are_guarded_too(make_bench, tmp_path):
    """The verifier runs `run_gate_spec` in the merge-base checkout (`tree=`): the same snapshot and restore."""
    bench = make_bench([])
    commit_base(bench, {"ruff.toml": RUFF})
    other = tmp_path / "base-checkout"
    bench.wb.git.run("clone", "-q", str(bench.wb.worktree), str(other))
    spec = GateSpec("lint", 'sh -c \'echo "ignore = [1]" >> ruff.toml; echo "x" > mypy.ini\'', timeout_s=60)
    bench.wb.run_gate_spec(spec, network=False, tree=other)
    assert (other / "ruff.toml").read_text() == RUFF and not (other / "mypy.ini").exists()
    found = {e["path"]: e["action"] for e in violations(bench, "gate configuration")}
    assert found == {"ruff.toml": "restored", "mypy.ini": "removed"}
