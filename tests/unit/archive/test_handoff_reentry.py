"""L4-ARC-008 (a): the hand-off commit H is made unless HEAD already is this unit's H, so a unit that went back to
review and passes again gets a new H (`[skip ci]` never on it) and the MR head is that commit."""

from l4.state.lifecycle import Trigger

from ..orchestrator.test_review_reentry import human_commit
from .conftest import BRANCH, green_step, red_step

HANDOFF = "docs(add-discount-codes): hand off to review"


def test_a_second_pass_after_reentry_makes_a_new_handoff_commit(
    run_l4, install_hooks, forge_env, use_fake_gitlab, tdd_repo, raw
):
    install_hooks(verify=lambda ctx: Trigger.VERIFY_PASS)
    assert run_l4([red_step(), green_step()]).code == 0
    h1 = raw(tdd_repo.origin, "rev-parse", BRANCH).strip()
    human = human_commit(tdd_repo, raw, {"notes.txt": "a person was here\n"})
    second = run_l4([])
    assert second.code == 0
    h2 = raw(tdd_repo.origin, "rev-parse", BRANCH).strip()
    assert h2 not in (h1, human)
    assert raw(tdd_repo.origin, "log", "-1", "--format=%s", BRANCH).strip() == HANDOFF  # H2 is the MR head
    assert "[skip ci]" not in raw(tdd_repo.origin, "log", "-1", "--format=%B", BRANCH)
    assert raw(tdd_repo.origin, "rev-parse", f"{h2}~1").strip() == human  # right on top of the human commit
    assert raw(tdd_repo.origin, "log", "--format=%s", f"main..{BRANCH}").splitlines().count(HANDOFF) == 2
    ready = second.events("pr.ready")
    assert [e["head"] for e in ready] == [h1, h2]
    # a rerun on H2 hands nothing off again (the failed-MR-update retry has its own test)
    again = run_l4([])
    assert again.code == 0 and raw(tdd_repo.origin, "rev-parse", BRANCH).strip() == h2


def test_the_evidence_link_of_the_mr_names_the_handoff_commit_so_it_survives_the_branch(
    run_l4, install_hooks, forge_env, use_fake_gitlab, tdd_repo, raw, gitlab
):
    """squash-and-delete D9: the unit branch is deleted after the merge, the commit stays reachable."""
    install_hooks(verify=lambda ctx: Trigger.VERIFY_PASS)
    assert run_l4([red_step(), green_step()]).code == 0
    h1 = raw(tdd_repo.origin, "rev-parse", BRANCH).strip()
    (mr,) = gitlab.mrs.values()
    link = [line for line in mr["description"].splitlines() if "Verification:" in line][0]
    assert f"/blob/{h1}/" in link and f"/blob/{BRANCH}/" not in link
