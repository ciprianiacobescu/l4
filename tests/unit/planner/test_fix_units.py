import json

from l4.cli import main
from l4.planner import UnitFacts, next_action

from ..orchestrator.conftest import BRANCH, UNIT_DIR  # noqa: F401
from ..orchestrator.test_fix_unit_cli import FIX_UNIT, put_fix_unit_on_main


def facts(phase: str, **over) -> UnitFacts:
    return UnitFacts("openspec:p", "openspec", phase, 1, 1, **over)


def test_fix_unit_never_planned_alone_and_fixing_waits_for_child_answers():
    assert next_action(facts("implemented", fix_unit_of="openspec:p-parent")) == (
        "none", "fix unit of openspec:p-parent: run the parent",
    )  # fmt: skip
    spawned = facts("fixing", open_fix_unit="p-fix-1", fix_progress=(1, 3))
    assert next_action(spawned) == ("implement", "fix unit p-fix-1: 1/3 tasks")
    held = facts("fixing", open_fix_unit="p-fix-1", fix_progress=(0, 1), fix_questions_open=("Q-001", "Q-002"))
    assert next_action(held) == ("none", "fixing: fix unit questions open: Q-001, Q-002")
    assert next_action(facts("fixing", open_fix_unit="p-fix-1"))[0] == "implement"  # progress not readable yet


def test_fixing_with_no_open_fix_unit_is_none_and_verified_still_hands_off():
    action, reason = next_action(facts("fixing"))
    assert action == "none" and "fixing" in reason
    assert next_action(facts("verified"))[0] == "hand_off"
    assert next_action(facts("verified", open_fix_unit="p-fix-1")) == (
        "implement", "fix unit p-fix-1 spawned for minor findings",
    )  # fmt: skip


def test_a_fix_unit_found_on_main_is_planned_as_none(tdd_repo, raw, capsys):
    put_fix_unit_on_main(tdd_repo, raw)
    capsys.readouterr()
    main(["plan", "--json", "--repo", str(tdd_repo.repo)], environ=tdd_repo.environ)
    plan = {u["unit"]: u["next_action"] for u in json.loads(capsys.readouterr().out)["units"]}
    assert plan[f"openspec:{FIX_UNIT}"] == "none" and plan["openspec:add-discount-codes"] == "implement"
