# ruff: noqa: F811
"""L4-OPS-010, SCN-OPS-17: `l4 run --unit` on a halted or escalated unit exits 13 before the lease, says why and what
to run, and writes nothing: no ledger, no commit, no push, no label."""

from l4.agents.fake import Step

from ..archive.conftest import forge_env, gitlab, use_fake_gitlab  # noqa: F401  (a fake GitLab for the labels)
from ..implementer.conftest import red_step
from ..implementer.conftest import result as task_result
from .conftest import BRANCH, UNIT, UNIT_DIR


def refs(run) -> str:
    return run.raw(run.tdd.origin, "for-each-ref", "--format=%(refname) %(objectname)")


def ledger_files(run) -> list[str]:
    from l4.vcs.names import UnitNames

    names = UnitNames.for_unit(UNIT, branch_prefix="l4/", cache=run.tdd.cache, repo_key=run.tdd.key)
    return sorted(p.name for p in (names.worktree / UNIT_DIR / ".l4" / "ledger").glob("*.jsonl"))


def test_a_run_of_a_halted_unit_exits_13_and_changes_nothing(run_l4, forge_env, use_fake_gitlab, capsys):
    halted = run_l4([Step(structured=task_result("red"))], implementer={"max_task_attempts": 1})
    assert halted.code == 13 and use_fake_gitlab.mrs[1]["labels"] == ["l4:halted"]
    detail = halted.events("phase.changed")[-1]["detail"]
    heads, labels, writes = refs(halted), list(use_fake_gitlab.mrs[1]["labels"]), len(use_fake_gitlab.writes())
    files = ledger_files(halted)
    capsys.readouterr()

    again = run_l4([red_step()])  # the agent must not be asked
    err = capsys.readouterr().err
    assert again.code == 13 and again.adapter.requests == []
    assert f"[l4] run: {UNIT} halted: {detail}" in err
    assert f"Next: l4 retry --unit {UNIT} --reason TEXT" in err
    (unit,) = again.outcome["units"]
    assert (unit["phase_before"], unit["phase_after"]) == ("halted", "halted")
    assert unit["exit_reason"].startswith("halted: ") and detail[:40] in unit["exit_reason"]
    assert "retry --unit" in unit["exit_reason"]
    assert refs(again) == heads  # the branch head, the lock ref and every other ref
    assert again.raw(again.tdd.origin, "rev-parse", BRANCH) == halted.raw(halted.tdd.origin, "rev-parse", BRANCH)
    assert use_fake_gitlab.mrs[1]["labels"] == labels and len(use_fake_gitlab.writes()) == writes
    assert ledger_files(again) == files  # no new run file in the worktree


def test_a_run_of_an_escalated_unit_is_refused_the_same_way(run_l4, monkeypatch, capsys):
    from l4 import orchestrator

    real = orchestrator.load_snapshot

    def escalated(*args, **kwargs):
        snapshot = real(*args, **kwargs)
        state = snapshot.state.model_copy(
            update={"phase": "escalated", "previous_phase": "verifying", "halt_detail": "round 2 failed the same way"}
        )
        return snapshot.__class__(**{**snapshot.__dict__, "state": state})

    first = run_l4([red_step()], implementer={"max_task_attempts": 1})
    heads = refs(first)
    monkeypatch.setattr(orchestrator, "load_snapshot", escalated)
    capsys.readouterr()
    run = run_l4([red_step()])
    err = capsys.readouterr().err
    assert run.code == 13 and run.adapter.requests == []
    assert f"[l4] run: {UNIT} escalated: round 2 failed the same way" in err
    assert f"Next: l4 retry --unit {UNIT} --reason TEXT" in err
    assert refs(run) == heads


def test_a_run_of_an_abandoned_unit_is_refused_and_names_l4_restart(run_l4, monkeypatch, capsys):
    """Review L4: the MR was closed without a merge; a run cannot move the unit, so it exits 13 with no side effect."""
    from l4 import orchestrator

    real = orchestrator.load_snapshot

    def abandoned(*args, **kwargs):
        snapshot = real(*args, **kwargs)
        state = snapshot.state.model_copy(update={"phase": "abandoned", "previous_phase": "in_review"})
        return snapshot.__class__(**{**snapshot.__dict__, "state": state})

    first = run_l4([red_step()], implementer={"max_task_attempts": 1})
    heads = refs(first)
    files = ledger_files(first)
    monkeypatch.setattr(orchestrator, "load_snapshot", abandoned)
    capsys.readouterr()
    run = run_l4([red_step()])
    err = capsys.readouterr().err
    assert run.code == 13 and run.adapter.requests == []
    assert f"[l4] run: {UNIT} abandoned: " in err
    assert f"Next: l4 restart --unit {UNIT} --reason TEXT" in err
    (unit,) = run.outcome["units"]
    assert (unit["phase_before"], unit["phase_after"]) == ("abandoned", "abandoned")
    assert refs(run) == heads and ledger_files(run) == files
