"""in_ci(environ): GITLAB_CI, GITHUB_ACTIONS or CI equal to `true`."""

import pytest

from l4.ci.detect import in_ci


@pytest.mark.parametrize("name", ["GITLAB_CI", "GITHUB_ACTIONS", "CI"])
def test_each_variable_set_to_true(name: str) -> None:
    assert in_ci({name: "true"})


@pytest.mark.parametrize("environ", [{}, {"CI": "false"}, {"CI": "1"}, {"GITLAB_CI": "TRUE"}, {"HOME": "/x"}])
def test_anything_else_is_not_ci(environ: dict[str, str]) -> None:
    assert not in_ci(environ)
