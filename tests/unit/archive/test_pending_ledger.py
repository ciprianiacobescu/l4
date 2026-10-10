import json

from l4.state.lifecycle import Trigger

from ..orchestrator.conftest import LOCK_REF
from .conftest import BRANCH, UNIT_DIR, green_step, red_step

HANDOFF = "docs(add-discount-codes): hand off to review"


def hand_off_run(run_l4, install_hooks, forge_env, use_fake_gitlab):
    install_hooks(verify=lambda ctx: Trigger.VERIFY_PASS)
    return run_l4([red_step(), green_step()])


def test_events_after_h_never_touch_unit_branch(run_l4, install_hooks, forge_env, use_fake_gitlab, tdd_repo, raw):
    """SCN-CI-18: the head of the unit branch is the hand-off commit; the tail of the run is in the lock ref."""
    run = hand_off_run(run_l4, install_hooks, forge_env, use_fake_gitlab)
    assert run.code == 0
    assert run.subjects()[-1] == HANDOFF  # no `chore(...): ledger` after H, with or without [skip ci]
    head = raw(tdd_repo.origin, "rev-parse", BRANCH).strip()
    handoff_sha = raw(tdd_repo.origin, "log", "--format=%H", "--grep", HANDOFF, BRANCH).strip()
    assert head == handoff_sha
    # the branch copy of the run stops before the phase change into review; the lock ref has the whole run
    branch_types = [(e["type"], e.get("to")) for e in run.branch_ledger()]
    assert ("phase.changed", "in_review") not in branch_types and "run.finished" not in [t for t, _ in branch_types]
    (name, text), = run.pending_files().items()
    pending = [json.loads(line) for line in text.splitlines()]
    assert name == f"{pending[0]['run_id']}.jsonl"
    assert pending[-1]["type"] == "run.finished" and pending[-1]["exit_code"] == 0
    assert any(e["type"] == "phase.changed" and e["to"] == "in_review" for e in pending)
    assert [e["type"] for e in pending[-2:]] == ["lock.released", "run.finished"]
    # the lock commit never starts a pipeline and is never a pull request head
    message = raw(tdd_repo.origin, "log", "-1", "--format=%B", LOCK_REF)
    assert "[skip ci]" in message and "\nL4-Run: " in message
    assert run.outcome["units"][0]["phase_after"] == "in_review"


def test_the_pending_file_extends_the_branch_copy_of_the_run(run_l4, install_hooks, forge_env, use_fake_gitlab):
    run = hand_off_run(run_l4, install_hooks, forge_env, use_fake_gitlab)
    (text,) = run.pending_files().values()
    branch_text = run.pushed(f"{UNIT_DIR}/.l4/ledger/" + next(iter(run.pending_files())))
    assert text.startswith(branch_text)  # append-only: what H holds is a prefix of the whole run
    assert len(text) > len(branch_text)


def test_a_rerun_of_a_unit_in_review_folds_the_pending_tail_and_hands_nothing_off_twice(
    run_l4, install_hooks, forge_env, use_fake_gitlab, tdd_repo, raw
):
    first = hand_off_run(run_l4, install_hooks, forge_env, use_fake_gitlab)
    head = raw(tdd_repo.origin, "rev-parse", BRANCH).strip()
    second = run_l4([])
    assert second.code == 0 and second.adapter.requests == []
    assert second.subjects().count(HANDOFF) == 1
    assert second.triggers().count("hand_off_pushed") == 1  # the second run did not hand off again
    assert raw(tdd_repo.origin, "rev-parse", BRANCH).strip() == head  # and wrote nothing to the branch
    files = second.pending_files()
    assert len(files) == 2 and set(files) >= set(first.pending_files())
    newest = [json.loads(line) for line in files[sorted(files)[-1]].splitlines()]
    assert newest[0]["type"] == "run.started" and newest[-1]["type"] == "run.finished"
    assert second.outcome["units"][0]["phase_after"] == "in_review"


def test_a_refused_pending_ledger_is_an_explained_error_naming_the_lock_ref(
    run_l4, install_hooks, forge_env, use_fake_gitlab, tdd_repo, capsys
):
    hand_off_run(run_l4, install_hooks, forge_env, use_fake_gitlab)
    hook = tdd_repo.origin / "hooks" / "pre-receive"
    hook.write_text(
        "#!/bin/sh\nwhile read old new ref; do case $ref in refs/l4/locks/*) echo 'no custom refs' >&2; exit 1;; "
        "esac; done\n"
    )
    hook.chmod(0o755)
    capsys.readouterr()
    second = run_l4([])
    assert second.code == 1  # a hook's refusal without a permission marker (G12): the tail would be lost, no success
    err = capsys.readouterr().err
    assert "refs/l4/locks/openspec/add-discount-codes" in err and "no custom refs" in err
    assert "write_repository" not in err and "non-fast-forward" not in err


def refuse_lock_refs(origin) -> None:
    hook = origin / "hooks" / "pre-receive"
    hook.write_text(
        "#!/bin/sh\nwhile read old new ref; do case $ref in refs/l4/locks/*) echo 'no custom refs' >&2; exit 1;; "
        "esac; done\n"
    )
    hook.chmod(0o755)


def test_a_tail_that_could_not_be_published_is_published_by_the_next_run(
    run_l4, install_hooks, forge_env, use_fake_gitlab, tdd_repo, raw
):
    refuse_lock_refs(tdd_repo.origin)
    install_hooks(verify=lambda ctx: Trigger.VERIFY_PASS)
    first = run_l4([red_step(), green_step()])
    assert first.code == 1 and first.pending_files() == {}  # H is pushed, its tail is only in the worktree
    (tdd_repo.origin / "hooks" / "pre-receive").unlink()
    head = raw(tdd_repo.origin, "rev-parse", BRANCH).strip()
    second = run_l4([])
    assert second.code == 0 and raw(tdd_repo.origin, "rev-parse", BRANCH).strip() == head
    files = second.pending_files()
    assert len(files) == 2  # the first run's file is there, next to the second run's
    runs = [[json.loads(line) for line in text.splitlines()] for text in files.values()]  # names sort by minute only
    (lost,) = [r for r in runs if any(e["type"] == "phase.changed" and e["to"] == "in_review" for e in r)]
    assert [e["type"] for e in lost][-2:] == ["lock.released", "run.finished"]
    assert any(e["type"] == "pr.updated" for e in lost)
    third = run_l4([])
    assert third.code == 0 and len(third.pending_files()) == 3  # the kept copy was dropped once published
