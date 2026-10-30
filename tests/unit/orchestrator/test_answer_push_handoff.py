# ruff: noqa: F811
"""The hand-off push is never merged (L4-RACE-001, review fix 1): H is the merge request's head and carries no skip
marker, so a person's answer that lands before the push of H ends that push with the moved-forward message; the next
run hands off again on top of the answers."""

import pytest

from l4.agents.fake import Step
from l4.specs.criteria import openspec_criteria

from ..archive.conftest import forge_env, gitlab, use_fake_gitlab  # noqa: F401  (a fake GitLab for the hand-off)
from ..conftest import FIXTURE
from ..implementer.conftest import green_step, red_step
from ..verifier.conftest import judge_reply, openspec_stand_in, valid_spec  # noqa: F401
from .conftest import BRANCH
from .test_answer_push_merge import QUESTIONS, Person, answered_questions, person  # noqa: F401

HANDOFF = "docs(add-discount-codes): hand off to review"
CRITERIA = [c.id for c in openspec_criteria(FIXTURE / "openspec" / "changes" / "add-discount-codes")]


@pytest.fixture(autouse=True)
def no_verifier() -> None:
    """The real verifier is on (overrides the orchestrator suite's)."""


@pytest.fixture(autouse=True)
def no_fix_loop() -> None:
    """The fix loop is on."""


def test_an_answer_that_lands_before_the_hand_off_push_is_not_merged_into_h(
    run_l4, valid_spec, forge_env, use_fake_gitlab, person, tdd_repo, raw, tmp_path, capsys, monkeypatch
):
    from l4.vcs.git import Git

    fire = person.push({QUESTIONS: answered_questions(tmp_path / "q")})
    real = Git.commit

    def commit(self, message, *args, **kwargs):
        sha = real(self, message, *args, **kwargs)
        if message == HANDOFF:  # the answer lands between the commit of H and its push
            fire(None)
        return sha

    monkeypatch.setattr(Git, "commit", commit)
    run = run_l4([red_step(), green_step(), Step(structured=judge_reply(CRITERIA))])
    err = capsys.readouterr().err
    assert person.fired == 1 and run.code == 1, err
    assert "a person pushed 1 commit" in err and "l4 restart" not in err
    head = raw(tdd_repo.origin, "rev-parse", BRANCH).strip()
    assert head == person.sha  # nothing of the run's H is on the branch
    assert raw(tdd_repo.origin, "rev-list", "--merges", "--count", f"main..{BRANCH}").strip() == "0"
    assert HANDOFF not in raw(tdd_repo.origin, "log", "--format=%s", f"main..{BRANCH}").splitlines()
    assert run.events("push.merged") == []
    assert not use_fake_gitlab.mrs or all(m["title"].startswith("Draft: ") for m in use_fake_gitlab.mrs.values())
