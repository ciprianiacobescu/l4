"""adoption-lessons 1.2b (L4-ADO-004): the orchestrator's unit-branch push tells `explain_push_failure` the forge."""

import pytest

from l4 import orchestrator
from l4.vcs.git import Git, GitError

from ..implementer.conftest import green_step, red_step

_403 = "fatal: unable to access 'https://h/p.git/': The requested URL returned error: 403"


@pytest.fixture
def refused_403(monkeypatch):
    def fail(self, remote, branch, *, config=()):
        raise GitError(["git", "push"], 128, _403)

    monkeypatch.setattr(Git, "push_branch", fail)


def test_the_unit_branch_push_failure_is_worded_for_the_forge(run_l4, refused_403, monkeypatch, capsys):
    seen = []
    real = orchestrator.explain_push_failure

    def spy(*args, **kwargs):
        seen.append(kwargs.get("platform"))
        return real(*args, **kwargs)

    monkeypatch.setattr(orchestrator, "explain_push_failure", spy)
    monkeypatch.setattr(orchestrator, "push_platform", lambda cfg, environ, repo: "github")
    run = run_l4([red_step(), green_step()])
    assert seen == ["github"]
    assert "contents: write" in run.outcome["units"][0]["exit_reason"]
