import pytest

from l4 import postmerge
from l4.ci import sweeper
from l4.cli import main
from l4.state.pending import read_pending_files

from ..archive.merged_world import FakeArchiveProvider, MergedWorld
from .review_world import ReviewWorld


@pytest.fixture
def world(tmp_path, raw, git_environ, gitlab, monkeypatch):
    w = MergedWorld(tmp_path, raw, git_environ, gitlab).build()
    (w.repo / ".l4").mkdir()
    (w.repo / ".l4" / "config.yaml").write_text("version: 1\n")
    monkeypatch.setattr(sweeper, "make_forge", lambda cfg, environ, **kw: w.forge())
    monkeypatch.setattr(postmerge, "OpenSpecProvider", FakeArchiveProvider)
    return w


def l4(world: MergedWorld, *args: str) -> int:
    return main([*args, "--repo", str(world.repo)], environ=world.environ)


def test_plan_without_sweep_changes_nothing(world, gitlab, capsys):
    world.merged_mr()
    assert l4(world, "plan") == 0
    assert "in_review" in capsys.readouterr().out and len(gitlab.mrs) == 1


def test_plan_sweep_records_the_merge_opens_the_archive_mr_and_plans_the_new_phase(world, gitlab, capsys):
    world.merged_mr()
    assert l4(world, "plan", "--sweep") == 0
    out = capsys.readouterr().out
    assert "merged" in out and "in_review" not in out
    assert gitlab.mrs[2]["title"] == "[l4] archive add-x"
    assert l4(world, "plan", "--sweep") == 0  # a second sweep changes nothing
    assert len(gitlab.mrs) == 2


def test_plan_sweep_with_a_failed_archive_still_exits_0_so_that_the_run_after_it_goes_on(world, monkeypatch):
    world.merged_mr()
    monkeypatch.setattr(postmerge, "OpenSpecProvider", type("Stray", (FakeArchiveProvider,), {"stray": "x.py"}))
    assert l4(world, "plan", "--sweep") == 0


def test_archive_command_opens_the_mr_for_a_merged_unit_and_refuses_an_unmerged_one(world, gitlab, capsys):
    assert l4(world, "archive", "--unit", "openspec:add-x") == 2  # in_review, MR not merged
    world.merged_mr()
    assert l4(world, "archive", "--unit", "openspec:add-x") == 0
    assert "archive_opened" in capsys.readouterr().out and gitlab.mrs[2]["title"] == "[l4] archive add-x"


def test_archive_command_exits_13_when_the_archive_fails(world, monkeypatch):
    world.merged_mr()
    monkeypatch.setattr(postmerge, "OpenSpecProvider", type("Stray", (FakeArchiveProvider,), {"stray": "x.py"}))
    assert l4(world, "archive", "--unit", "openspec:add-x") == 13


def refuse_archive_pushes(world: MergedWorld) -> None:
    hook = world.origin / "hooks" / "pre-receive"
    hook.write_text(
        "#!/bin/sh\nwhile read old new ref; do case $ref in refs/heads/l4/archive/*) "
        "echo \"GitLab: Branch name does not follow the pattern '^(feat|fix)/'\" >&2; exit 1;; esac; done\n"
    )
    hook.chmod(0o755)


def test_plan_sweep_with_a_refused_archive_push_exits_0_and_records_it_once(world, gitlab):
    world.merged_mr()
    refuse_archive_pushes(world)
    for _ in range(3):  # every pipeline sweeps again: the refusal must neither fail the job nor repeat
        assert l4(world, "plan", "--sweep") == 0
    files = read_pending_files(world.git, "refs/l4/locks/openspec/add-x")
    assert sum(data.count(b'"archive.failed"') for data in files.values()) == 1


def test_archive_command_exits_13_for_a_recorded_failure_and_retry_tries_again(world, gitlab, capsys):
    world.merged_mr()
    refuse_archive_pushes(world)
    assert l4(world, "plan", "--sweep") == 0
    (world.origin / "hooks" / "pre-receive").unlink()  # the push rule was fixed on the forge
    assert l4(world, "archive", "--unit", "openspec:add-x") == 13
    assert "archive.failed is recorded" in capsys.readouterr().out
    assert l4(world, "archive", "--unit", "openspec:add-x", "--retry") == 0
    assert gitlab.mrs[2]["title"] == "[l4] archive add-x"


def test_the_sweep_takes_the_job_token_out_of_the_origin_url_before_any_git_call(world):
    from l4.ci.sweeper import sweep

    url = "https://gitlab-ci-token:glcbt-" + "k9L8m7N6" * 3 + "@gitlab.example.test/g/p.git"
    world.raw(world.repo, "remote", "set-url", "origin", url)
    sweep(world.app(), world.cfg, world.git, [])
    assert (
        world.raw(world.repo, "config", "--get", "remote.origin.url").strip() == "https://gitlab.example.test/g/p.git"
    )


# --- the CI decision (M1.9 line 18) -------------------------------------------------------------------------------


@pytest.fixture
def review(tmp_path, raw, git_environ, gitlab, monkeypatch):
    w = ReviewWorld(tmp_path, raw, git_environ, gitlab).build()
    (w.repo / ".l4").mkdir()
    (w.repo / ".l4" / "config.yaml").write_text("version: 1\n")
    monkeypatch.setattr(sweeper, "make_forge", lambda cfg, environ, **kw: w.forge())
    return w


def test_plan_sweep_reports_the_ci_decision(review, gitlab, capsys):
    short = review.handoff[:10]
    assert l4(review, "plan", "--sweep") == 0
    captured = capsys.readouterr()
    # no pipeline job yet: not run, never green (L4-CI-012)
    assert f"ci: H {short}: no pipeline of the project has a job on the hand-off commit" in captured.err
    assert "in_review" in captured.out
    gitlab.add_pipeline(review.handoff, [("test", "failed", {"trace": "FAILED"}), ("build", "running")])
    assert l4(review, "plan", "--sweep") == 0
    assert f"ci: H {short} running" in capsys.readouterr().err
    gitlab.pipelines.clear()
    gitlab.add_pipeline(review.handoff, [("test", "failed", {"trace": "FAILED"})])
    assert l4(review, "plan", "--sweep") == 0
    captured = capsys.readouterr()
    assert f"ci: H {short} red: test (recorded)" in captured.err
    assert "verify" in captured.out and f"repository CI failed on {short}: test" in captured.out  # the plan row now
    assert l4(review, "plan", "--sweep") == 0
    assert f"ci: H {short} red: test (already recorded)" in capsys.readouterr().err
    assert l4(review, "plan", "--sweep", "--json") == 0
    import json

    assert json.loads(capsys.readouterr().out)["units"][0]["next_action"] == "verify"  # stdout stays JSON


def test_archive_command_does_not_look_at_ci(review, gitlab, capsys):
    gitlab.add_pipeline(review.handoff, [("test", "failed")])
    assert l4(review, "archive", "--unit", "openspec:add-x") == 2  # in_review, MR not merged: as before
    assert "ci" not in capsys.readouterr().out
    assert not [f for f in read_pending_files(review.git, "refs/l4/locks/openspec/add-x") if "ci" in f]
    assert not any(
        "ci." in data.decode() for data in read_pending_files(review.git, "refs/l4/locks/openspec/add-x").values()
    )
