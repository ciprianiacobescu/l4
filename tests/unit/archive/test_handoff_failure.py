"""A hand-off that fails after H is pushed (forge-and-ci 2.43): the unit branch stays at H."""

import json

from l4.forge.base import ForgeError
from l4.forge.gitlab import GitLabForge
from l4.state.lifecycle import Trigger

from ..orchestrator.conftest import LOCK_REF
from .conftest import BRANCH, green_step, red_step

HANDOFF = "docs(add-discount-codes): hand off to review"


def test_failed_mr_update_after_h_leaves_the_branch_at_h(
    run_l4, install_hooks, forge_env, use_fake_gitlab, tdd_repo, raw, monkeypatch
):
    real = GitLabForge.update_pr

    def flaky(self, number, **kw):
        if kw.get("draft") is False:
            raise ForgeError("GitLab PUT /merge_requests/1: HTTP 502")
        return real(self, number, **kw)

    monkeypatch.setattr(GitLabForge, "update_pr", flaky)
    install_hooks(verify=lambda ctx: Trigger.VERIFY_PASS)
    first = run_l4([red_step(), green_step()])
    assert first.code != 0
    assert raw(tdd_repo.origin, "log", "-1", "--format=%s", BRANCH).strip() == HANDOFF
    tail = raw(tdd_repo.origin, "ls-tree", "-r", "--name-only", LOCK_REF).split()
    assert tail, "the failed run's tail must be in the lock ref"
    blob = raw(tdd_repo.origin, "show", f"{LOCK_REF}:{tail[0]}")
    assert "lock.released" in {json.loads(line)["type"] for line in blob.splitlines()}

    monkeypatch.setattr(GitLabForge, "update_pr", real)
    second = run_l4([])
    assert second.code == 0
    assert raw(tdd_repo.origin, "log", "-1", "--format=%s", BRANCH).strip() == HANDOFF
    assert not use_fake_gitlab.mrs[1]["title"].lower().startswith("draft")
