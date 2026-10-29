"""One rule for "this is a CI job" (`in_ci_job`) and the opt-in reading where `CI` alone counts (`ci_like`)."""

import pytest

from l4.ci.detect import ci_like, in_ci_job


@pytest.mark.parametrize("name", ["GITLAB_CI", "GITHUB_ACTIONS"])
def test_a_job_variable_set_to_true_is_a_ci_job(name: str) -> None:
    assert in_ci_job({name: "true"}) and ci_like({name: "true"})


def test_scn_cli_12_ci_true_alone_is_not_a_ci_job() -> None:
    """SCN-CLI-12: a laptop with `CI=true` is CI-like (the gates opt in) but not a job."""
    assert not in_ci_job({"CI": "true"})
    assert ci_like({"CI": "true"})


@pytest.mark.parametrize(
    "environ",
    [{}, {"CI": "false"}, {"CI": "1"}, {"GITLAB_CI": "TRUE"}, {"GITHUB_ACTIONS": "1"}, {"HOME": "/x"}],
)
def test_anything_else_is_neither(environ: dict[str, str]) -> None:
    assert not in_ci_job(environ)
    assert not ci_like(environ)
