"""The `in_review` rows of SPEC 12.0 that M1.9 builds: a commit after H, a spec edit, the project's CI red on H."""

from pathlib import Path

from l4.orchestrator import ACTIONABLE
from l4.planner import UnitFacts, facts_of, next_action
from l4.specs.base import Framework, UnitRef
from l4.state.fold import CiFailure, UnitState
from l4.state.review import AfterHandoff, ForeignCommit
from l4.state.status import UnitSnapshot

H = "a" * 40
HEAD = "b" * 40


def facts(**over) -> UnitFacts:
    base = {"unit": "openspec:x", "framework": "openspec", "phase": "in_review", "tasks_done": 2, "tasks_total": 2}
    return UnitFacts(**{**base, **over})


def snapshot(*, review: AfterHandoff | None, failure: CiFailure | None = None, phase: str = "in_review"):
    state = UnitState(unit="openspec:x", phase=phase, ci_failure=failure)
    ref = UnitRef(Framework.OPENSPEC, "x", Path("/nonexistent/openspec/changes/x"))
    return UnitSnapshot(ref, state, [], "branch", review=review)


def test_a_human_commit_plans_verify():
    review = AfterHandoff(H, HEAD, (ForeignCommit(HEAD, "ann", "fix ci"),))
    action, reason = next_action(facts_of(snapshot(review=review)))
    assert action == "verify"
    assert reason == f"in_review: commit(s) after the hand-off not made by the harness: {HEAD[:10]}"


def test_a_spec_edit_plans_implement():
    review = AfterHandoff(H, HEAD, (ForeignCommit(HEAD, "ann", "more tasks"),), spec_edit=True)
    action, reason = next_action(facts_of(snapshot(review=review)))
    assert action == "implement" and reason == f"in_review: answers or spec edits after the hand-off ({H[:10]})"


def test_a_lost_hand_off_plans_verify():
    action, reason = next_action(facts_of(snapshot(review=AfterHandoff(None, HEAD, lost=True))))
    assert action == "verify" and "hand-off commit" in reason


def test_ci_failed_on_h_plans_verify():
    failure = CiFailure(head=H, pipeline=3, jobs=[{"name": "test"}, {"name": "lint"}])
    action, reason = next_action(facts_of(snapshot(review=AfterHandoff(H, H), failure=failure)))
    assert (action, reason) == ("verify", f"in_review: repository CI failed on {H[:10]}: test, lint")


def test_ci_failed_on_an_older_head_is_ignored():
    failure = CiFailure(head="c" * 40, pipeline=3, jobs=[{"name": "test"}])
    assert next_action(facts_of(snapshot(review=AfterHandoff(H, H), failure=failure)))[0] == "none"
    # and a failure for H does not act once the branch is past H (the later commit supersedes the old pipeline)
    past = AfterHandoff(H, HEAD)  # a harness commit after H: no foreign commit
    failure = CiFailure(head=H, pipeline=3, jobs=[{"name": "test"}])
    assert next_action(facts_of(snapshot(review=past, failure=failure)))[0] == "none"


def test_a_foreign_commit_comes_before_a_ci_failure():
    review = AfterHandoff(H, HEAD, (ForeignCommit(HEAD, "ann", "fix"),))
    failure = CiFailure(head=H, pipeline=3, jobs=[{"name": "test"}])
    assert "commit(s) after the hand-off" in next_action(facts_of(snapshot(review=review, failure=failure)))[1]


def test_only_harness_commits_after_h_still_wait():
    action, reason = next_action(facts_of(snapshot(review=AfterHandoff(H, HEAD))))
    assert (action, reason) == ("none", "in_review: waiting for merge")
    assert action not in ACTIONABLE
    assert next_action(facts())[1] == "in_review: waiting for merge"  # no review facts at all: as before
    assert {"verify", "implement"} <= ACTIONABLE  # the rows above are what `l4 run` selects
