"""Live failure (job 5420): the runner's insteadOf rule sent every harness push out with the JOB token."""

import pytest

from l4.forge import gitlab as forge_gitlab
from l4.forge.gitlab import git_auth_config
from l4.state.lifecycle import Trigger
from l4.vcs.git import Git, GitResult

from .conftest import BRANCH, TOKEN, green_step, red_step


@pytest.fixture(autouse=True)
def passing_verifier(install_hooks) -> None:
    install_hooks(verify=lambda ctx: Trigger.VERIFY_PASS)


def pushurls(config) -> list[str]:
    return [v for k, v in config if k == "remote.origin.pushurl"]


@pytest.fixture
def no_push_waits(monkeypatch) -> None:
    """The pushes this test does not look at (the lock refs) reach no remote: `gl.example` does not resolve, and
    `Git._push` retries each of them after 5 s and 15 s. Every `Git` gets a `sleep` that waits for none."""
    real_init = Git.__init__

    def init(self, *args, **kwargs) -> None:
        kwargs.setdefault("sleep", lambda _seconds: None)
        real_init(self, *args, **kwargs)

    monkeypatch.setattr(Git, "__init__", init)


def test_the_forge_hook_pushes_to_the_oauth2_url_in_ci(run_l4, forge_env, use_fake_gitlab, monkeypatch, no_push_waits):
    forge_env.update(CI_SERVER_URL="https://gl.example:8443", CI_PROJECT_PATH="grp/sub/proj")
    push_configs: list = []

    def no_network(self, remote, refspecs, *, config=()):
        push_configs.append(tuple(config))
        return GitResult(0, "", "")

    def no_network_branch(self, remote, branch, *, config=()):
        return no_network(self, remote, [], config=config)

    monkeypatch.setattr(Git, "push", no_network)
    monkeypatch.setattr(Git, "push_branch", no_network_branch)
    run_l4([red_step(), green_step()])
    assert push_configs
    for cfg in push_configs:
        assert pushurls(cfg) == ["https://oauth2@gl.example:8443/grp/sub/proj.git"]
        assert cfg[:2] == git_auth_config("L4_FORGE_TOKEN")  # the helper still comes first
        assert TOKEN not in " ".join(v for _, v in cfg)


def test_without_a_known_project_path_the_origin_is_pushed_as_before(run_l4, forge_env, use_fake_gitlab, push_configs):
    run = run_l4([red_step(), green_step()])  # forge_env has CI_PROJECT_ID only
    assert run.code == 0 and push_configs
    assert all(pushurls(cfg) == [] for cfg in push_configs)


def test_a_runner_insteadof_rule_cannot_redirect_the_harness_push(
    run_l4, forge_env, use_fake_gitlab, tdd_repo, raw, monkeypatch
):
    """The rule rewrites the origin to a mirror (fetching works, like the job token that can read); the push still
    reaches the real origin through the pushurl and never the mirror."""
    mirror = tdd_repo.repo.parent / "mirror.git"
    raw(tdd_repo.repo.parent, "clone", "-q", "--bare", str(tdd_repo.origin), str(mirror))
    raw(tdd_repo.repo, "config", f"url.{mirror}.insteadOf", str(tdd_repo.origin))
    forge_env.update(CI_SERVER_URL="https://gl.example", CI_PROJECT_PATH="g/p")
    monkeypatch.setattr(forge_gitlab, "push_url", lambda cfg, environ: f"file://localhost{tdd_repo.origin}")
    run = run_l4([red_step(), green_step()])
    assert run.code == 0
    assert run.raw(tdd_repo.origin, "rev-parse", "--verify", BRANCH).strip()
    assert run.raw(mirror, "for-each-ref", "refs/heads/l4").strip() == ""  # nothing went through the rewrite
    assert run.raw(tdd_repo.repo, "rev-parse", f"refs/remotes/origin/{BRANCH}").strip()  # tracking ref kept current
