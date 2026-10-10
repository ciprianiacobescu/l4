import pytest

from l4 import archive
from l4.forge.gitlab import GitLabForge
from l4.vcs.git import Git

from ..forge.conftest import API, PROJECT, TOKEN, FakeGitLab, gitlab  # noqa: F401
from ..implementer.conftest import blocked_step, green_step, red_step  # noqa: F401
from ..orchestrator.conftest import BRANCH, UNIT, UNIT_DIR, Run, install_hooks, run_l4  # noqa: F401


@pytest.fixture
def forge_env(tdd_repo) -> dict[str, str]:
    """The job environment of a GitLab pipeline with the forge token."""
    tdd_repo.environ.update(GITLAB_CI="true", CI_API_V4_URL=API, CI_PROJECT_ID=PROJECT, L4_FORGE_TOKEN=TOKEN)
    return tdd_repo.environ


@pytest.fixture
def use_fake_gitlab(monkeypatch: pytest.MonkeyPatch, gitlab: FakeGitLab) -> FakeGitLab:  # noqa: F811
    """Point the hooks' forge at the fake: no network, no retry sleeps."""

    def make(cfg, environ, **_: object) -> GitLabForge:
        return GitLabForge(API, PROJECT, TOKEN, transport=gitlab.transport(), sleep=lambda s: None)

    monkeypatch.setattr(archive, "make_forge", make)
    return gitlab


@pytest.fixture
def push_configs(monkeypatch: pytest.MonkeyPatch) -> list[tuple[tuple[str, str], ...]]:
    """The `config=` of every push, to see how it authenticated."""
    seen: list[tuple[tuple[str, str], ...]] = []
    real, real_branch = Git.push, Git.push_branch

    def spy(self, remote, refspecs, *, config=()):
        seen.append(tuple(config))
        return real(self, remote, refspecs, config=config)

    def spy_branch(self, remote, branch, *, config=()):
        seen.append(tuple(config))
        return real_branch(self, remote, branch, config=config)

    monkeypatch.setattr(Git, "push", spy)
    monkeypatch.setattr(Git, "push_branch", spy_branch)
    return seen
