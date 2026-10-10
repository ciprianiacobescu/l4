"""The sweep of a merged Kiro unit (Kiro e2e H2 caveat 3): Kiro has no change folder to archive, so the merged tree is
checked with the done-gate instead (every required leaf `[x]`), `archive.done` is recorded, and no archive MR is opened.
A failed done-gate is said once, on the MR, and not tried again until the unit's folder changes."""

import json

import pytest

from l4.ci.sweeper import Sweeper
from l4.cli import main
from l4.postmerge import MergeDetector, MergeVerdict, PostMergeArchiver
from l4.state.pending import read_pending_files
from l4.state.status import load_snapshot

from ..archive.conftest import forge_env, use_fake_gitlab  # noqa: F401
from ..archive.kiro_merged_world import KIRO_OPEN, KiroMergedWorld

LOCK = "refs/l4/locks/kiro/add-x"


@pytest.fixture
def world(tmp_path, raw, git_environ, gitlab):
    return KiroMergedWorld(tmp_path, raw, git_environ, gitlab).build()


@pytest.fixture
def open_world(tmp_path, raw, git_environ, gitlab):
    return KiroMergedWorld(tmp_path, raw, git_environ, gitlab).build(tasks=KIRO_OPEN)


def snapshots(world: KiroMergedWorld):
    provider = world.provider()
    return [load_snapshot(provider, world.git, ref, branch_prefix="l4/") for ref in provider.list_units()]


def sweep(world: KiroMergedWorld, run_id: str, retry: bool = False):
    app = world.app(run_id)
    forge = world.forge()
    archiver = PostMergeArchiver(world.cfg, app, world.git, forge)
    detector = MergeDetector(world.git, base_branch="main", kiro_root=".kiro/specs")
    return Sweeper(app, world.cfg, world.git, forge, archiver, detector, retry=retry).run(snapshots(world))


def pending_events(world: KiroMergedWorld) -> list[dict]:
    files = read_pending_files(world.git, LOCK)
    return [
        {"run": run.removesuffix(".jsonl"), **json.loads(line)}
        for run, data in sorted(files.items())
        for line in data.decode().splitlines()
    ]


def lock_refs(world: KiroMergedWorld) -> str:
    return world.raw(world.origin, "for-each-ref", "refs/l4/")


def test_the_detector_reads_the_kiro_folder_not_the_openspec_one(world):
    pr = world.forge().get_pr(world.merged_mr())
    detector = MergeDetector(world.git, base_branch="main", kiro_root=".kiro/specs")
    assert detector.classify(pr, "add-x", framework="kiro") is MergeVerdict.NEEDS_ARCHIVE  # the folder is there
    assert detector.classify(pr, "add-gone", framework="kiro") is MergeVerdict.ARCHIVED
    assert detector.classify(pr, "add-x") is MergeVerdict.ARCHIVED  # the OpenSpec question: no change folder


def test_a_merged_kiro_unit_passes_the_done_gate_is_recorded_done_and_gets_no_archive_mr(world, gitlab):
    world.merged_mr()
    mrs = len(gitlab.mrs)
    (action,) = sweep(world, "r-20261005T1000Z-0001")
    assert (action.unit, action.what) == ("kiro:add-x", "done")
    events = [e for e in pending_events(world) if e["run"] == "r-20261005T1000Z-0001"]
    assert [e["type"] for e in events] == ["run.started", "phase.changed", "archive.done", "run.finished"]
    assert (events[1]["from"], events[1]["to"]) == ("in_review", "merged")
    assert events[2]["via"] == "done_gate" and events[2]["base"] == world.raw(world.repo, "rev-parse", "main").strip()
    assert len(gitlab.mrs) == mrs  # no archive MR: Kiro has no archive folder
    assert world.remote_branches() == ["main"]
    (after,) = snapshots(world)
    assert after.state.phase == "merged"


def test_the_lock_ref_is_kept_because_it_is_the_only_record_that_the_unit_merged(world):
    """The Kiro folder stays on the base, so the unit stays listed. Its merge is recorded only in the pending ledger;
    were the lock ref retired, the folder's own ledger would read `in_review` again and the next sweep would merge it
    again onto a new lock ref."""
    world.merged_mr()
    sweep(world, "r-20261005T1000Z-0001")
    assert "refs/l4/locks/kiro/add-x" in lock_refs(world) and "refs/l4/archived" not in lock_refs(world)


def test_a_second_sweep_of_a_done_kiro_unit_changes_nothing_and_says_so_without_repeating_the_old_note(world, gitlab):
    world.merged_mr()
    sweep(world, "r-20261005T1000Z-0001")
    refs, mrs, writes = lock_refs(world), dict(gitlab.mrs), len(gitlab.writes())
    (action,) = sweep(world, "r-20261005T1100Z-0002")
    assert (action.what, action.detail) == ("skipped", "archive.done is recorded")
    assert lock_refs(world) == refs and gitlab.mrs == mrs and len(gitlab.writes()) == writes
    assert not any(e["run"] == "r-20261005T1100Z-0002" for e in pending_events(world))


def test_a_failed_done_gate_is_recorded_once_with_a_note_on_the_mr_and_not_tried_again(open_world, gitlab):
    world = open_world
    number = world.merged_mr()
    (action,) = sweep(world, "r-20261005T1000Z-0001")
    assert action.what == "archive_failed" and "task 1.1 is not done" in action.detail
    failed = [e for e in pending_events(world) if e["type"] == "archive.failed"]
    assert len(failed) == 1 and "task 1.1 is not done" in failed[0]["reason"]
    (note,) = gitlab.notes[number]
    assert "done-gate" in note["body"] and "1.1" in note["body"]
    writes = len(gitlab.writes())
    (again,) = sweep(world, "r-20261005T1100Z-0002")
    assert again.what == "skipped" and "archive.failed" in again.detail
    assert len([e for e in pending_events(world) if e["type"] == "archive.failed"]) == 1
    assert len(gitlab.writes()) == writes and len(gitlab.notes[number]) == 1  # one note, not one per pipeline
    world.advance_base()  # unrelated work lands: the unit's folder is the same, so the verdict is the same
    assert sweep(world, "r-20261005T1200Z-0003")[0].what == "skipped"


def test_finishing_the_open_leaf_on_the_base_branch_lets_the_next_sweep_record_done(open_world, gitlab):
    world = open_world
    world.merged_mr()
    assert sweep(world, "r-20261005T1000Z-0001")[0].what == "archive_failed"
    from ..archive.kiro_merged_world import KIRO_DONE

    world.edit_on_main("add-x", "tasks.md", KIRO_DONE)
    (action,) = sweep(world, "r-20261005T1100Z-0002")
    assert action.what == "done"
    types = [e["type"] for e in pending_events(world)]
    assert types.count("archive.failed") == 1 and types.count("archive.done") == 1
    assert sweep(world, "r-20261005T1200Z-0003")[0].what == "skipped"  # done is not undone by the earlier failure


def test_archive_command_runs_the_done_gate_of_a_merged_kiro_unit(world, gitlab, capsys, monkeypatch):
    from l4.ci import sweeper

    (world.repo / ".l4").mkdir()
    (world.repo / ".l4" / "config.yaml").write_text("version: 1\n")
    monkeypatch.setattr(sweeper, "make_forge", lambda cfg, environ, **kw: world.forge())
    run = lambda *a: main([*a, "--repo", str(world.repo)], environ=world.environ)  # noqa: E731
    assert run("archive", "--unit", "kiro:add-x") == 2  # in_review: the MR has not merged
    world.merged_mr()
    assert run("archive", "--unit", "kiro:add-x") == 0
    assert "done" in capsys.readouterr().out
