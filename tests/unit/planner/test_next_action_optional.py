from l4.implementer.tasks import select_next_step
from l4.planner import facts_of, next_action
from l4.specs.base import Framework, UnitRef
from l4.specs.kiro import parse_kiro_tasks
from l4.state.fold import UnitState
from l4.state.status import UnitSnapshot

TASKS = b"- [x] 1. Greet\n  - [x] 1.1 Add greet\n  - [ ]* 1.2 Blank name test\n"


def snapshot(tmp_path, phase: str | None) -> UnitSnapshot:
    ref = UnitRef(Framework.KIRO, "greet", tmp_path)
    return UnitSnapshot(ref, UnitState(unit=ref.id, phase=phase), parse_kiro_tasks(TASKS), "worktree")


def test_open_optional_leaf_is_not_pending(tmp_path):
    snap = snapshot(tmp_path, None)
    assert (snap.tasks_done, snap.tasks_total) == (2, 2)
    assert select_next_step(snap.tasks) is None
    action, reason = next_action(facts_of(snap))
    assert action == "verify" and "all tasks done" in reason
    assert next_action(facts_of(snapshot(tmp_path, "implementing")))[1] == "implementing: continue"
