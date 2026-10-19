"""SCN-YOLO-125. H comes from the lock ref's pending files only, never from events in the branch tree (L4-ARC-008): a
`pr.ready` that someone commits to the branch cannot make a later tip H or pin H in the future."""

import datetime as dt

from l4.vcs.git import BOT_IDENTITY

from .conftest import BRANCH
from .ready_world import fetch, forge_in_tree, handed_off, push_lock, ready_file, snap


def test_a_pr_ready_in_the_branch_tree_cannot_make_the_tip_h(unit_repo, trailers, tmp_path):
    git = unit_repo.git
    h, genuine, lock = handed_off(unit_repo, trailers, tmp_path)
    (unit_repo.repo / "evil.py").write_text("print('pwned')\n")
    git.run("add", "evil.py")
    git.commit("chore: evil", trailers, BOT_IDENTITY)
    x = git.rev_parse("HEAD")
    forge_in_tree(unit_repo, trailers, tmp_path, x, dt.datetime(2099, 1, 1, tzinfo=dt.UTC), "r-20990101T0000Z-0bad")
    y = git.rev_parse("HEAD")
    git.push("origin", [f"HEAD:refs/heads/{BRANCH}"])
    git.run("checkout", "-q", "main")
    git.run("branch", "-q", "-D", BRANCH)
    fetch(unit_repo)
    found = snap(unit_repo)
    assert found.state.ready_head == h and found.review.head == y and found.review.reentry


def test_a_far_future_pr_ready_in_the_branch_tree_does_not_pin_h_after_a_new_hand_off(unit_repo, trailers, tmp_path):
    """The review's L3: after the harness hands off again (H2, a genuine `pr.ready{H2}` on the lock ref), a forged
    2099 event in the tree must not outrank it, so H2 is H and the unit is not sent back again."""
    git = unit_repo.git
    h, genuine, lock = handed_off(unit_repo, trailers, tmp_path)
    (unit_repo.repo / "evil.py").write_text("print('pwned')\n")
    git.run("add", "evil.py")
    git.commit("chore: evil", trailers, BOT_IDENTITY)
    x = git.rev_parse("HEAD")
    forge_in_tree(unit_repo, trailers, tmp_path, x, dt.datetime(2099, 1, 1, tzinfo=dt.UTC), "r-20990101T0000Z-0bad")
    git.commit("docs(add-x): hand off to review", trailers, BOT_IDENTITY, allow_empty=True)  # the harness's H2
    h2 = git.rev_parse("HEAD")
    git.push("origin", [f"HEAD:refs/heads/{BRANCH}"])
    when = dt.datetime(2026, 10, 4, 9, 0, tzinfo=dt.UTC)
    again = {**genuine, "r-20261004T0900Z-0002.jsonl": ready_file(tmp_path / "g2", "r-20261004T0900Z-0002", h2, when)}
    push_lock(git, again, lock)
    git.run("checkout", "-q", "main")
    git.run("branch", "-q", "-D", BRANCH)
    fetch(unit_repo)
    found = snap(unit_repo)
    assert found.state.ready_head == h2 and found.state.ready_at == when
    assert not found.review.reentry  # the forged event neither became H nor made H2 a commit after H


def test_no_pending_pr_ready_means_no_recorded_h(unit_repo, trailers, tmp_path):
    """A `pr.ready` only in the branch tree records nothing: the merge is `not_ready` and `l4 retry` hands off again."""
    git = unit_repo.git
    git.run("checkout", "-q", "-b", BRANCH)
    git.commit("work", trailers, BOT_IDENTITY, allow_empty=True)
    h = git.rev_parse("HEAD")
    forge_in_tree(
        unit_repo, trailers, tmp_path, h, dt.datetime(2026, 10, 3, 14, 0, tzinfo=dt.UTC), "r-20261003T1400Z-0001"
    )
    git.push("origin", [f"HEAD:refs/heads/{BRANCH}"])
    git.run("checkout", "-q", "main")
    git.run("branch", "-q", "-D", BRANCH)
    fetch(unit_repo)
    assert snap(unit_repo).state.ready_head is None
