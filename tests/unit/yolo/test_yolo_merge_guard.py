"""The guarded merge (L4-YOLO-008, design D8): preconditions, the fast-forward push against a bare origin, and
confirm_merged. SCN-YOLO-14 (merged), SCN-YOLO-15 (a moved target is refused by git itself), SCN-YOLO-16 (a protected
target is refused)."""

import stat
from dataclasses import replace
from pathlib import Path

import pytest

from l4.config.schema import L4Config
from l4.context import AppContext
from l4.forge.base import PullRequest
from l4.redact import Redactor
from l4.specs.base import Framework, UnitRef
from l4.state.fold import LastVerdict, QuestionState, UnitState
from l4.state.review import AfterHandoff, ForeignCommit
from l4.state.status import UnitSnapshot
from l4.vcs.git import Git
from l4.yolo.merge import confirm_merged, merge_guarded, push_fast_forward

BRANCH = "l4/openspec/x"
UNIT = "openspec:x"
PR_URL = "https://forge.invalid/o/r/pull/7"


class FakeForge:
    def __init__(self, pr: PullRequest | None) -> None:
        self.pr, self.gets = pr, []

    def find_pr(self, head_branch: str):
        return self.pr if self.pr and self.pr.head_branch == head_branch else None

    def get_pr(self, number: int):
        self.gets.append(number)
        return self.pr


def pull(state="open", base="main") -> PullRequest:
    return PullRequest(7, PR_URL, BRANCH, base, "[l4] x", False, state, ())


class World:
    def __init__(self, tmp: Path, raw, environ) -> None:
        self.raw, self.environ = raw, environ
        self.origin, self.work = tmp / "origin.git", tmp / "work"
        raw(tmp, "init", "-q", "--bare", "-b", "main", str(self.origin))
        raw(tmp, "clone", "-q", str(self.origin), str(self.work))
        self.commit(self.work, "base.txt", "main")
        raw(self.work, "push", "-q", "origin", "main")
        raw(self.work, "checkout", "-q", "-b", BRANCH)
        self.handoff = self.commit(self.work, "unit.txt", "unit")
        raw(self.work, "push", "-q", "origin", BRANCH)
        raw(self.work, "fetch", "-q", "origin")
        self.head = self.handoff
        self.git = Git(self.work, environ=environ)
        self.cfg = L4Config.model_validate({"version": 1})
        self.app = AppContext(
            repo=self.work, config_path=None, log_format="human", verbosity=0, run_id="r-20261014T1000Z-aaaa",
            environ=environ, redactor=Redactor({}),
        )  # fmt: skip

    def commit(self, repo: Path, name: str, text: str) -> str:
        (repo / name).write_text(text + "\n")
        self.raw(repo, "add", "-A")
        self.raw(repo, "commit", "-q", "-m", f"add {name}")
        return self.raw(repo, "rev-parse", "HEAD").strip()

    def target(self) -> str:
        return self.raw(self.origin, "rev-parse", "refs/heads/main").strip()

    def move_target(self) -> str:
        """A person's commit on main, from another clone."""
        other = self.work.parent / "other"
        if not other.exists():
            self.raw(self.work.parent, "clone", "-q", str(self.origin), str(other))
        self.raw(other, "checkout", "-q", "main")
        self.raw(other, "pull", "-q", "origin", "main")
        sha = self.commit(other, f"p{len(list(other.iterdir()))}.txt", "person")
        self.raw(other, "push", "-q", "origin", "main")
        return sha

    def snapshot(self, **state) -> UnitSnapshot:
        fields = {
            "unit": UNIT, "phase": "in_review", "pr": PR_URL,
            "last_verdict": LastVerdict(round=1, verdict="PASS", findings=0),
        }  # fmt: skip
        fields.update(state)
        return UnitSnapshot(
            ref=UnitRef(Framework.OPENSPEC, "x", self.work / "openspec" / "changes" / "x"),
            state=UnitState(**fields), tasks=[], source="branch",
            review=AfterHandoff(handoff=self.handoff, head=self.head),
        )  # fmt: skip


@pytest.fixture
def world(tmp_path, raw, git_environ) -> World:
    return World(tmp_path, raw, git_environ)


def merge(world: World, snapshot=None, forge=None):
    return merge_guarded(world.app, world.cfg, world.git, forge or FakeForge(pull()), snapshot or world.snapshot())


def test_a_verified_unit_is_merged_by_a_fast_forward_push(world):  # SCN-YOLO-14
    before = world.target()
    out = merge(world)
    assert (out.status, out.head, out.target_before, out.pr) == ("merged", world.head, before, 7)
    assert world.target() == world.head
    assert ["push", "--", "origin", f"{world.head}:refs/heads/main"] == world.git.history[-1][-4:]
    assert not any(a.startswith("+") or a.startswith("--force") for a in world.git.history[-1])


def test_a_target_that_moved_before_the_check_is_stale_and_nothing_is_pushed(world):
    world.move_target()
    moved = world.target()
    out = merge(world)
    assert out.status == "stale" and out.target_before == moved
    assert world.target() == moved
    assert not any(a[:2] == ["push", "--"] for a in world.git.history)


def test_a_target_that_moves_after_the_check_is_refused_by_git_itself(world):  # SCN-YOLO-15
    tip = world.target()
    moved = world.move_target()  # between the ancestor check (tip was fine) and the push
    out = push_fast_forward(world.app, world.cfg, world.git, world.head, "main", before=tip, pr=7)
    assert out.status == "stale" and out.target_before == tip and out.pr == 7
    assert world.target() == moved


def test_a_protected_target_is_refused_with_the_forge_message(world):  # SCN-YOLO-16
    hook = world.origin / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\necho 'GH006: Protected branch update failed for refs/heads/main' >&2\nexit 1\n")
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR)
    tip = world.target()
    out = merge(world)
    assert out.status == "refused" and "Protected branch update failed" in out.detail
    assert world.target() == tip


def test_a_refusal_message_is_redacted(world):
    hook = world.origin / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\necho 'denied for s3cr3t-token-value' >&2\nexit 1\n")
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR)
    app = replace(world.app, redactor=Redactor({"L4_FORGE_TOKEN": "s3cr3t-token-value"}))
    out = merge_guarded(app, world.cfg, world.git, FakeForge(pull()), world.snapshot())
    assert out.status == "refused" and "s3cr3t-token-value" not in out.detail and "REDACTED" in out.detail


@pytest.mark.parametrize(
    ("state", "fragment"),
    [
        ({"phase": "verifying"}, "verifying, not in_review"),
        ({"last_verdict": LastVerdict(round=1, verdict="FAIL", findings=2)}, "FAIL, not PASS"),
        ({"last_verdict": None}, "missing, not PASS"),
        ({"questions": QuestionState(open=["Q1"])}, "questions are open: Q1"),
    ],
)
def test_precondition_one_unit_state(world, state, fragment):
    tip = world.target()
    out = merge(world, world.snapshot(**state))
    assert out.status == "not_ready" and fragment in out.detail
    assert world.target() == tip


@pytest.mark.parametrize(("item_state", "blocks"), [("waiting", True), ("submitted", True), ("addressed", False)])
def test_precondition_one_unresolved_feedback(world, monkeypatch, item_state, blocks):
    from l4.state.feedback_view import ItemView

    monkeypatch.setattr(
        "l4.yolo.merge.item_views", lambda file, state: [ItemView("FB-001", "bug", None, item_state, item_state)]
    )
    out = merge(world)
    assert (out.status == "not_ready") is blocks
    if blocks:
        assert "feedback is unresolved: FB-001" in out.detail


def test_precondition_two_a_persons_commit_after_the_hand_off(world):
    snap = replace(
        world.snapshot(), review=AfterHandoff(world.handoff, world.head, foreign=(ForeignCommit("a" * 40, "p", "fix"),))
    )
    out = merge(world, snap)
    assert out.status == "not_ready" and "after the hand-off" in out.detail


@pytest.mark.parametrize(
    ("pr", "fragment"),
    [
        (None, "no pull request"),
        (pull(state="closed"), "closed, not open"),
        (pull(base="release"), "aimed at release, not the target main"),
    ],
)
def test_precondition_three_the_pull_request(world, pr, fragment):
    tip = world.target()
    out = merge(world, forge=FakeForge(pr))
    assert out.status == "not_ready" and fragment in out.detail
    assert world.target() == tip


def test_a_missing_target_is_not_ready(world):
    world.raw(world.origin, "update-ref", "-d", "refs/heads/main")
    out = merge(world)
    assert out.status == "not_ready" and "does not exist" in out.detail


def test_confirm_merged_is_true_when_the_target_holds_the_head_and_the_forge_agrees(world):
    merge(world)
    forge = FakeForge(pull(state="merged"))
    assert confirm_merged(forge, world.git, world.cfg, 7, world.head, wait_s=5, sleep=lambda s: None) is True
    assert forge.gets == [7]


def test_confirm_merged_waits_then_returns_true_when_only_the_forge_lags(world, caplog):
    merge(world)
    now = [0.0]

    def clock() -> float:
        return now[0]

    def sleep(seconds: float) -> None:
        now[0] += seconds

    forge = FakeForge(pull(state="open"))
    assert confirm_merged(forge, world.git, world.cfg, 7, world.head, wait_s=3, sleep=sleep, clock=clock) is True
    assert len(forge.gets) >= 3 and "has not marked the PR merged" in caplog.text


def test_confirm_merged_is_false_when_the_target_does_not_hold_the_head(world):
    forge = FakeForge(pull(state="merged"))
    assert confirm_merged(forge, world.git, world.cfg, 7, world.head, wait_s=0, sleep=lambda s: None) is False
    assert forge.gets == []
