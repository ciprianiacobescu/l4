# ruff: noqa: F811
"""human-feedback 2.5 (L4-FBK-006; SCN-FBK-15, SCN-FBK-16): feedback fix units are counted apart from
`verifier.max_fix_rounds` and have their own limit, `feedback.max_rounds`."""

from datetime import UTC, datetime, timedelta

import pytest
import yaml

from l4.config.schema import L4Config
from l4.redact import Redactor
from l4.specs.feedback import FeedbackKind, NewFeedback, Place, append_item
from l4.state.budget import fix_round_limit, fix_rounds_exhausted
from l4.state.fold import fold
from l4.state.ledger import LedgerEvent

from ..archive.conftest import forge_env, gitlab, use_fake_gitlab  # noqa: F401  (a fake GitLab for the hand-off)
from ..conftest import TddRepo
from ..implementer.conftest import green_step, red_step
from ..orchestrator.conftest import BRANCH, UNIT_DIR
from ..orchestrator.test_feedback_reentry import CHORE, JUDGE, JUDGE_FB1
from ..orchestrator.test_review_reentry import human_commit
from .conftest import openspec_stand_in, valid_spec  # noqa: F401
from .test_ladder_fix import chore_fix, noqa_green

T0 = datetime(2026, 10, 12, 12, 0, tzinfo=UTC)


def state(*rows: tuple[str, dict]):
    events = [LedgerEvent(T0 + timedelta(seconds=n), "r-1", "openspec:p", n, k, d) for n, (k, d) in enumerate(rows)]
    return fold(events, "openspec:p")


def spawned(name: str, round_: int, **extra) -> tuple[str, dict]:
    return "fix.spawned", {"parent": "openspec:p", "fix_unit": name, "round": round_, "findings": [], **extra}


def test_the_fold_counts_the_fix_rounds_that_are_not_feedback_only():
    s = state(
        spawned("p-fix-1", 1, feedback_only=True), spawned("p-fix-2", 2), spawned("p-fix-3", 3, feedback_only=True)
    )
    assert (s.fix_round, s.fix_rounds_counted, s.feedback_rounds_used) == (3, 1, 2)


def test_a_fix_unit_spawned_twice_is_counted_once():
    s = state(spawned("p-fix-1", 1), spawned("p-fix-1", 1, adopted=True))
    assert s.fix_rounds_counted == 1


def test_feedback_fix_units_do_not_exhaust_the_fix_rounds():
    """SCN-FBK-15: `max_fix_rounds: 1` and the one fix round used; feedback units come on top."""
    cfg = L4Config.model_validate({"verifier": {"max_fix_rounds": 1}})
    one = state(spawned("p-fix-1", 1))
    assert fix_rounds_exhausted(cfg, one) and fix_round_limit(cfg, one) == 1
    only = state(spawned("p-fix-1", 1, feedback_only=True), spawned("p-fix-2", 2, feedback_only=True))
    assert not fix_rounds_exhausted(cfg, only)


# --- end to end: SCN-FBK-15 and SCN-FBK-16 ---

FEEDBACK = f"{UNIT_DIR}/feedback.md"


@pytest.fixture(autouse=True)
def no_fix_loop() -> None:
    """The fix loop is on."""


@pytest.fixture(autouse=True)
def no_verifier() -> None:
    """The real verifier is on."""


@pytest.fixture
def with_config(monkeypatch):
    def apply(**sections: dict) -> None:
        original = TddRepo.config

        def config(self, **kw):
            body = yaml.safe_load(original(self, **kw))
            for name, values in sections.items():
                body[name] = {**body.get(name, {}), **values}
            return yaml.safe_dump(body)

        monkeypatch.setattr(TddRepo, "config", config)

    return apply


def item_file(tmp_path, existing: str | None, title: str) -> str:
    """`feedback.md` with one more submitted refactor item, written by the command's own writer."""
    folder = tmp_path / f"fb-{title.replace(' ', '-')}"
    folder.mkdir()
    if existing is not None:
        (folder / "feedback.md").write_text(existing)
    new = NewFeedback(
        FeedbackKind.REFACTOR, title, f"{title}, please.", "Ana, 2026-10-12T15:04:00Z",
        places=(Place("src/pytdd/pricing.py", 5, 6),),
    )  # fmt: skip
    append_item(folder, "add-discount-codes", new, redactor=Redactor({}))
    return (folder / "feedback.md").read_text()


def test_feedback_does_not_use_up_fix_rounds(
    run_l4, valid_spec, forge_env, use_fake_gitlab, with_config, tdd_repo, raw, tmp_path
):
    """SCN-FBK-15: `max_fix_rounds: 1`, the one fix round used; a feedback fix unit is written and nobody escalates."""
    with_config(verifier={"max_fix_rounds": 1})
    first = run_l4([red_step(), noqa_green(), chore_fix(), JUDGE])
    assert first.code == 0 and [e["fix_unit"] for e in first.events("fix.spawned")] == ["add-discount-codes-fix-1"]
    human_commit(tdd_repo, raw, {FEEDBACK: item_file(tmp_path, None, "Extract the rounding")})
    second = run_l4([CHORE, JUDGE_FB1])
    assert second.code == 0, second.adapter.requests[-1].prompt[-500:]
    spawned = second.events("fix.spawned")
    assert [(e["fix_unit"], e.get("feedback_only")) for e in spawned] == [
        ("add-discount-codes-fix-1", None),
        ("add-discount-codes-fix-2", True),
    ]
    assert second.events("phase.changed")[-1]["to"] == "in_review"
    assert not [e for e in second.events("phase.changed") if e["to"] == "escalated"]


def test_the_feedback_limit_escalates_with_exit_13_and_its_note(
    run_l4, valid_spec, forge_env, use_fake_gitlab, with_config, tdd_repo, raw, tmp_path
):
    """SCN-FBK-16: `feedback.max_rounds: 1`, one feedback fix unit done, a new submitted item."""
    with_config(feedback={"max_rounds": 1})
    assert run_l4([red_step(), green_step(), JUDGE]).code == 0
    first_file = item_file(tmp_path, None, "Extract the rounding")
    human_commit(tdd_repo, raw, {FEEDBACK: first_file})
    second = run_l4([CHORE, JUDGE_FB1])
    assert second.code == 0 and [e.get("feedback_only") for e in second.events("fix.spawned")] == [True]
    taken_file = raw(tdd_repo.origin, "show", f"{BRANCH}:{FEEDBACK}")
    human_commit(tdd_repo, raw, {FEEDBACK: item_file(tmp_path, taken_file, "Name the constant")}, name="human2")
    third = run_l4([JUDGE])
    assert third.code == 13
    edge = third.events("phase.changed")[-1]
    assert (edge["to"], edge["trigger"], edge["reason"]) == (
        "escalated",
        "verify_fail_exhausted",
        "feedback_rounds_exhausted",
    )
    assert "feedback round limit reached (1)" in third.outcome["units"][0]["exit_reason"]
    assert [e["type"] for e in third.ledger() if e["type"] == "feedback.taken"] == ["feedback.taken"]
    assert len(third.events("fix.spawned")) == 1  # no second fix unit
    assert not third.adapter.requests  # step 0 failed: no agent ran
