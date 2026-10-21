"""The gates see the CI's identity variables, and only in CI (ci-evidence D7; L4-SEC-040, SCN-SEC-100 to -103)."""

import pytest

from l4.agents.fake import Step

from ..implementer.conftest import IMPL, green_step, red_step, result

IMPL_CI = "import os\n\n\n" + IMPL.replace(
    "def apply_discount(amount, code):\n",
    "def apply_discount(amount, code):\n    if os.environ.get('GITHUB_ACTIONS'):\n        return -1.0\n",
)


def ci_green() -> Step:
    return Step(writes={"src/pytdd/pricing.py": IMPL_CI}, structured=result("green"))


@pytest.fixture(autouse=True)
def no_token_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("l4.config.preflight.require_token_in_ci", lambda cfg, environ: None)


def test_run_started_records_the_gate_names(run_l4, tdd_repo):
    """SCN-SEC-100: only the variables the gates get, sorted; none without CI."""
    tdd_repo.environ.update({"CI": "true", "GITHUB_ACTIONS": "true", "FORCE_COLOR": "1", "GITHUB_OUTPUT": "/tmp/o"})
    run = run_l4([red_step(), green_step()])
    assert run.events("run.started")[0]["gate_env_ci"] == ["CI", "GITHUB_ACTIONS"]


def test_run_started_has_no_gate_names_outside_ci(run_l4, tdd_repo):
    tdd_repo.environ.update({"FORCE_COLOR": "1", "CLICOLOR": "1"})
    run = run_l4([red_step(), green_step()])
    assert "gate_env_ci" not in run.events("run.started")[0] and run.code == 0


def test_a_refused_value_is_named_once(run_l4, tdd_repo, capsys):
    """SCN-SEC-102: one WARNING per refused name, never the value."""
    token = "ghp_" + "abcdEFGH1234" * 3
    tdd_repo.environ.update({"CI": "true", "GITLAB_CI": token, "GITHUB_ACTIONS": "/tmp/secret-path"})
    run = run_l4([red_step(), green_step()])
    err = capsys.readouterr().err
    lines = [line for line in err.splitlines() if "the gates do not get" in line]
    assert [line.split("the gates do not get ")[1] for line in lines] == [
        "GITHUB_ACTIONS: its value is not a short word (at most 16 letters, digits, '_', '-')",
        "GITLAB_CI: its value is not a short word (at most 16 letters, digits, '_', '-')",
    ]
    assert token not in err and "/tmp/secret-path" not in err
    assert run.events("run.started")[0]["gate_env_ci"] == ["CI"]


def test_a_local_opt_in_logs_one_info_line(run_l4, tdd_repo, capsys):
    """SCN-SEC-103: `CI=true` on a person's machine says that the gates got it; in a job there is no such line."""
    tdd_repo.environ["CI"] = "true"
    run_l4([red_step(), green_step()])
    info = [line for line in capsys.readouterr().err.splitlines() if "the gates run with" in line]
    assert len(info) == 1 and "CI=true" in info[0] and "not from a CI job" in info[0]
    tdd_repo.environ["GITHUB_ACTIONS"] = "true"
    run_l4([red_step(), green_step()])
    assert "the gates run with" not in capsys.readouterr().err


def test_a_test_that_only_ci_fails_fails_in_the_gate_of_a_job(run_l4, tdd_repo):
    """SCN-SEC-101: the green gate fails on code that reads `GITHUB_ACTIONS`, in a job."""
    tdd_repo.environ.update({"CI": "true", "GITHUB_ACTIONS": "true"})
    job = run_l4([red_step(), ci_green()])
    assert [e["phase"] for e in job.events("task.attempt_failed")][:1] == ["green"]


def test_the_same_code_passes_on_a_machine(run_l4, tdd_repo):
    """SCN-SEC-101: with no CI variable the gate passes as before."""
    plain = run_l4([red_step(), ci_green()])
    assert plain.events("task.attempt_failed") == [] and plain.code == 0
