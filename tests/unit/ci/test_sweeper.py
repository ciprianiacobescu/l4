# ruff: noqa: F811
import json

import pytest

from l4.agents.fake import Step
from l4.ci import sweeper as sweeper_module
from l4.ci.sweeper import Sweeper
from l4.cli import main
from l4.forge.gitlab import GitLabForge
from l4.postmerge import MergeDetector
from l4.specs.openspec import OpenSpecProvider
from l4.state.pending import read_pending_files
from l4.state.status import UnitSnapshot, load_snapshot

from ..archive.conftest import forge_env, use_fake_gitlab  # noqa: F401  (a fake GitLab for the hand-off)
from ..archive.merged_world import MergedWorld
from ..forge.conftest import API, PROJECT, TOKEN, WEB
from ..implementer.conftest import result
from ..orchestrator.conftest import run_l4  # noqa: F401
from .review_world import ReviewWorld

LOCK = "refs/l4/locks/openspec/{}"


@pytest.fixture
def world(tmp_path, raw, git_environ, gitlab):
    return MergedWorld(tmp_path, raw, git_environ, gitlab).build()


def snapshots(world: MergedWorld) -> list[UnitSnapshot]:
    provider = OpenSpecProvider(world.repo, world.environ)
    return [load_snapshot(provider, world.git, ref, branch_prefix="l4/") for ref in provider.list_units()]


def sweep(world: MergedWorld, run_id: str, provider_class=None, retry: bool = False):
    if provider_class:
        world.provider_class = provider_class
    app = world.app(run_id)
    forge = world.forge()
    archiver = PostMerge(world, app, forge)
    detector = MergeDetector(world.git, base_branch="main")
    return Sweeper(app, world.cfg, world.git, forge, archiver, detector, retry=retry).run(snapshots(world))


def PostMerge(world: MergedWorld, app, forge):  # noqa: N802
    from l4.postmerge import PostMergeArchiver

    return PostMergeArchiver(world.cfg, app, world.git, forge, provider_for=world.provider_for)


def pending_events(world: MergedWorld, name: str = "add-x") -> list[dict]:
    files = read_pending_files(world.git, LOCK.format(name))
    return [
        {"run": run.removesuffix(".jsonl"), **json.loads(line)}
        for run, data in sorted(files.items())
        for line in data.decode().splitlines()
    ]


def test_a_unit_in_review_is_still_in_review_before_the_sweep(world):
    (snap,) = snapshots(world)
    assert snap.state.phase == "in_review"


def test_merged_unit_gets_archive_pr_once(world, gitlab):
    world.merged_mr()
    (action,) = sweep(world, "r-20261005T1000Z-0001")
    assert action.what == "archive_opened"
    assert [mr["title"] for mr in gitlab.mrs.values()][-1] == "[l4] archive add-x"
    events = [e for e in pending_events(world) if e["run"] == "r-20261005T1000Z-0001"]
    assert [e["type"] for e in events] == ["run.started", "phase.changed", "archive.opened", "run.finished"]
    changed = events[1]
    assert (changed["from"], changed["to"], changed["trigger"]) == ("in_review", "merged", "pr_merged")
    (after,) = snapshots(world)
    assert after.state.phase == "merged"  # the pending ledger says so for every later plan


def test_second_sweep_is_a_noop(world, gitlab):
    world.merged_mr()
    sweep(world, "r-20261005T1000Z-0001")
    refs_before = world.raw(world.origin, "for-each-ref")
    mrs_before = json.dumps(gitlab.mrs, sort_keys=True)
    writes = len(gitlab.writes())
    (action,) = sweep(world, "r-20261005T1100Z-0002")
    assert action.what == "archive_existing"
    assert world.raw(world.origin, "for-each-ref") == refs_before  # no branch, no lock-ref commit
    assert json.dumps(gitlab.mrs, sort_keys=True) == mrs_before and len(gitlab.writes()) == writes
    assert not any(e["run"] == "r-20261005T1100Z-0002" for e in pending_events(world))


def test_a_unit_whose_mr_is_still_open_is_left_alone(world, gitlab):
    world.forge().create_pr("l4/openspec/add-x", "main", "[l4] add-x", "b", draft=False)
    refs = world.raw(world.origin, "for-each-ref")
    assert sweep(world, "r-20261005T1000Z-0001") == []
    assert world.raw(world.origin, "for-each-ref") == refs


def test_a_second_merged_unit_waits_for_the_first_archive_mr(world, gitlab):
    other = "r-20261004T0910Z-cccc"
    world.merge_unit("add-y", run_id=other)
    world.merged_mr("add-x")
    world.merged_mr("add-y")
    first, second = sweep(world, "r-20261005T1000Z-0001")
    assert (first.unit, first.what) == ("openspec:add-x", "archive_opened")
    assert (second.unit, second.what) == ("openspec:add-y", "archive_pending")
    # add-y is recorded as merged, so the next sweep only has its archive left to do
    assert {s.ref.name: s.state.phase for s in snapshots(world)} == {"add-x": "merged", "add-y": "merged"}
    gitlab.merge(next(n for n, mr in gitlab.mrs.items() if mr["source_branch"].startswith("l4/archive/")), None)
    head = world.advance_base()
    (again,) = [a for a in sweep(world, "r-20261005T1200Z-0002") if a.unit == "openspec:add-y"]
    assert again.what == "archive_opened"
    (sha,) = world.archive_commits("l4/archive/openspec/add-y")
    assert world.raw(world.origin, "rev-parse", f"{sha}^").strip() == head


def test_a_failed_archive_is_recorded_once_and_not_tried_again(world, gitlab):
    from ..archive.merged_world import FakeArchiveProvider

    class Stray(FakeArchiveProvider):
        stray = "src/evil.py"

    world.merged_mr()
    (action,) = sweep(world, "r-20261005T1000Z-0001", Stray)
    assert action.what == "archive_failed" and "src/evil.py" in action.detail
    failed = [e for e in pending_events(world) if e["type"] == "archive.failed"]
    assert len(failed) == 1 and "src/evil.py" in failed[0]["reason"]
    (again,) = sweep(world, "r-20261005T1100Z-0002")
    assert again.what == "skipped"
    assert len([e for e in pending_events(world) if e["type"] == "archive.failed"]) == 1


def test_a_busy_unit_is_skipped_untouched(world):
    from l4.vcs.locks import LocalFileLease

    world.merged_mr()
    names = PostMerge(world, world.app(), world.forge()).names(world.ref())
    lease = LocalFileLease(names.flock_path, unit="openspec:add-x", run_id="r-20261005T0000Z-ffff")
    lease.acquire()
    try:
        (action,) = sweep(world, "r-20261005T1000Z-0001")
    finally:
        lease.release()
    assert (action.what, action.detail) == ("skipped", "locked")
    assert world.raw(world.origin, "for-each-ref", "refs/heads/l4/archive").strip() == ""


def test_a_merge_without_a_merge_commit_is_still_swept(world, gitlab):
    world.merged_mr(sha=None)
    (action,) = sweep(world, "r-20261005T1000Z-0001")
    assert action.what == "archive_opened"


def test_a_merge_that_carried_the_archive_leaves_no_unit_to_sweep(tmp_path, raw, git_environ, gitlab):
    world = MergedWorld(tmp_path, raw, git_environ, gitlab).build(archive_in_merge=True)
    world.merged_mr()
    # the merge result has no change folder, so the checkout lists no unit and there is nothing to sweep
    assert snapshots(world) == []
    assert sweep(world, "r-20261005T1000Z-0001") == []


def test_a_merged_tree_without_the_folder_is_recorded_merged_and_gets_no_archive_mr(tmp_path, raw, git_environ, gitlab):
    world = MergedWorld(tmp_path, raw, git_environ, gitlab).build(archive_in_merge=True)
    # the base head holds the folder again (a later commit), the tree of the merge commit does not
    world.raw(world.repo, "checkout", "-q", "l4/openspec/add-x", "--", "openspec/changes/add-x")
    world.raw(world.repo, "commit", "-q", "-m", "the folder is back")
    world.raw(world.repo, "push", "-q", "origin", "main")
    world.merged_mr()
    (action,) = sweep(world, "r-20261005T1000Z-0001")
    assert (action.what, action.detail) == ("merged", "MR !1: the merged tree holds no change folder")
    changed = [e for e in pending_events(world) if e["type"] == "phase.changed" and e["run"] == "r-20261005T1000Z-0001"]
    assert [(e["from"], e["to"]) for e in changed] == [("in_review", "merged")]
    assert not any(e["type"] == "archive.opened" for e in pending_events(world))
    assert [mr["title"] for mr in gitlab.mrs.values()] == ["[l4] add-x: x"]  # no archive MR
    assert world.raw(world.origin, "for-each-ref", "refs/heads/l4/archive").strip() == ""


def test_a_merge_commit_that_is_not_in_the_clone_writes_nothing(world, gitlab):
    world.merged_mr(sha="0123456789abcdef0123456789abcdef01234567")
    refs = world.raw(world.origin, "for-each-ref")
    (action,) = sweep(world, "r-20261005T1000Z-0001")
    assert action.what == "skipped" and "not in this clone" in action.detail
    assert world.raw(world.origin, "for-each-ref") == refs  # no lock-ref commit, no archive branch
    (after,) = snapshots(world)
    assert after.state.phase == "in_review"
    assert len(gitlab.mrs) == 1


OTHER_RUN = "r-20261004T0910Z-cccc"


def refuse_pushes(world: MergedWorld, branch: str) -> None:
    hook = world.origin / "hooks" / "pre-receive"
    hook.write_text(
        "#!/bin/sh\nwhile read old new ref; do case $ref in refs/heads/" + branch + ") "
        "echo \"GitLab: Branch name does not follow the pattern '^(feat|fix)/'\" >&2; exit 1;; esac; done\n"
    )
    hook.chmod(0o755)


def failures(world: MergedWorld, name: str) -> list[dict]:
    return [e for e in pending_events(world, name) if e["type"] == "archive.failed"]


def test_a_refused_archive_push_is_recorded_and_the_next_unit_is_still_swept(world, gitlab):
    world.merge_unit("add-y", run_id=OTHER_RUN)
    world.merged_mr("add-x")
    world.merged_mr("add-y")
    refuse_pushes(world, "l4/archive/openspec/add-x")
    first, second = sweep(world, "r-20261005T1000Z-0001")
    assert (first.unit, first.what) == ("openspec:add-x", "archive_failed") and "push of" in first.detail
    assert (second.unit, second.what) == ("openspec:add-y", "archive_opened")
    (failed,) = failures(world, "add-x")
    assert "does not follow the pattern" in failed["reason"]
    assert sweep(world, "r-20261005T1100Z-0002")[0].what == "skipped"  # a refusal is not retried by itself


def test_a_forge_4xx_on_the_archive_mr_is_a_definitive_failure(world, gitlab, monkeypatch):
    from l4.forge.base import ForgeError
    from l4.forge.gitlab import GitLabForge

    def refuse(self, *args, **kwargs):
        raise ForgeError("GitLab POST /merge_requests: HTTP 422: source branch is invalid", status=422)

    world.merged_mr()
    monkeypatch.setattr(GitLabForge, "create_pr", refuse)
    (action,) = sweep(world, "r-20261005T1000Z-0001")
    assert action.what == "archive_failed"
    assert "HTTP 422" in failures(world, "add-x")[0]["reason"]


def test_a_transient_forge_error_leaves_the_unit_for_the_next_pipeline(world, gitlab, monkeypatch):
    from l4.forge.base import ForgeError
    from l4.forge.gitlab import GitLabForge

    world.merge_unit("add-y", run_id=OTHER_RUN)
    world.merged_mr("add-x")
    world.merged_mr("add-y")
    real = GitLabForge.create_pr

    def flaky(self, head, *args, **kwargs):
        if head.endswith("add-x"):
            raise ForgeError("GitLab POST /merge_requests: HTTP 502", status=502)
        return real(self, head, *args, **kwargs)

    monkeypatch.setattr(GitLabForge, "create_pr", flaky)
    actions = sweep(world, "r-20261005T1000Z-0001")  # does not raise
    assert [(a.unit, a.what) for a in actions] == [("openspec:add-y", "archive_opened")]
    assert failures(world, "add-x") == []
    monkeypatch.setattr(GitLabForge, "create_pr", real)
    gitlab.merge(next(n for n, mr in gitlab.mrs.items() if mr["source_branch"] == "l4/archive/openspec/add-y"), None)
    again = [a for a in sweep(world, "r-20261005T1200Z-0002") if a.unit == "openspec:add-x"]
    assert [a.what for a in again] == ["archive_opened"]


def test_a_credential_problem_is_raised_after_the_other_units_are_swept(world, gitlab, monkeypatch):
    from l4.forge.base import ForgeAuthError
    from l4.forge.gitlab import GitLabForge

    world.merge_unit("add-y", run_id=OTHER_RUN)
    world.merged_mr("add-x")
    world.merged_mr("add-y")
    real = GitLabForge.create_pr

    def denied(self, head, *args, **kwargs):
        if head.endswith("add-x"):
            raise ForgeAuthError("GitLab POST /merge_requests: HTTP 403", status=403)
        return real(self, head, *args, **kwargs)

    monkeypatch.setattr(GitLabForge, "create_pr", denied)
    with pytest.raises(ForgeAuthError):
        sweep(world, "r-20261005T1000Z-0001")
    assert any(mr["source_branch"] == "l4/archive/openspec/add-y" for mr in gitlab.mrs.values())


def test_a_failed_archive_is_tried_again_when_the_base_or_the_unit_folder_changed(world, gitlab):
    tasks = world.repo / "openspec/changes/add-x/tasks.md"
    tasks.write_text(tasks.read_text() + "- [ ] 1.3 follow-up\n")
    world.raw(world.repo, "commit", "-q", "-am", "a follow-up task")
    world.raw(world.repo, "push", "-q", "origin", "main")
    world.merged_mr()
    assert sweep(world, "r-20261005T1000Z-0001")[0].what == "archive_failed"
    assert sweep(world, "r-20261005T1100Z-0002")[0].what == "skipped"  # same inputs, same failure
    world.advance_base()  # the base moved: the archive is built again, and fails the same way
    assert sweep(world, "r-20261005T1200Z-0003")[0].what == "archive_failed"
    assert len(failures(world, "add-x")) == 2
    tasks.write_text(tasks.read_text().replace("- [ ] 1.3", "- [x] 1.3"))  # the folder changed on main
    world.raw(world.repo, "commit", "-q", "-am", "the follow-up is done")
    world.raw(world.repo, "push", "-q", "origin", "main")
    assert sweep(world, "r-20261005T1300Z-0004")[0].what == "archive_opened"
    assert len(failures(world, "add-x")) == 2  # the pending ledger kept every line


def test_retry_tries_a_recorded_failure_again_with_unchanged_inputs(world, gitlab):
    world.merged_mr()
    refuse_pushes(world, "l4/archive/openspec/add-x")
    assert sweep(world, "r-20261005T1000Z-0001")[0].what == "archive_failed"
    (world.origin / "hooks" / "pre-receive").unlink()  # the project's push rule was fixed on the forge
    assert sweep(world, "r-20261005T1100Z-0002")[0].what == "skipped"
    assert sweep(world, "r-20261005T1200Z-0003", retry=True)[0].what == "archive_opened"


# --- the forge listing, the unit's own MR, and retiring the lock ref -----------------------------------------------


def test_a_transient_error_listing_the_merged_mrs_sweeps_nothing_and_does_not_raise(world, gitlab, monkeypatch):
    from l4.forge.base import ForgeError
    from l4.forge.gitlab import GitLabForge

    world.merged_mr()
    refs = world.raw(world.origin, "for-each-ref")

    def down(self, *args, **kwargs):
        raise ForgeError("GitLab GET /merge_requests: HTTP 502", status=502)

    monkeypatch.setattr(GitLabForge, "list_prs", down)
    assert sweep(world, "r-20261005T1000Z-0001") == []
    assert world.raw(world.origin, "for-each-ref") == refs


def test_a_credential_problem_listing_the_merged_mrs_is_still_raised(world, gitlab, monkeypatch):
    from l4.forge.base import ForgeAuthError
    from l4.forge.gitlab import GitLabForge

    world.merged_mr()

    def denied(self, *args, **kwargs):
        raise ForgeAuthError("GitLab GET /merge_requests: HTTP 401", status=401)

    monkeypatch.setattr(GitLabForge, "list_prs", denied)
    with pytest.raises(ForgeAuthError):
        sweep(world, "r-20261005T1000Z-0001")


def record_pr(world: MergedWorld, number: int, run_id: str) -> None:
    """The unit's ledger says its MR is !number (the `pr.updated` event the hand-off writes)."""
    from l4.redact import Redactor
    from l4.state.ledger import LedgerWriter, ledger_path
    from l4.state.pending import PendingLedger

    scratch = world.tmp / "pr-scratch"
    writer = LedgerWriter.open(scratch, world.unit_id, run_id, redactor=Redactor({}))
    writer.append("pr.updated", url=f"{WEB}/-/merge_requests/{number}", number=number)
    writer.finish(0)
    PendingLedger(world.git, lock_ref=LOCK.format("add-x"), unit=world.unit_id, run_id=run_id).publish(
        ledger_path(scratch, run_id)
    )


def test_an_older_merged_mr_of_the_same_branch_is_not_the_units_mr(world, gitlab):
    world.merged_mr()  # !1: the unit's previous life on this branch name
    world.forge().create_pr("l4/openspec/add-x", "main", "[l4] add-x: x", "b", draft=False)  # !2: its current MR
    record_pr(world, 2, "r-20261005T0800Z-eeee")
    (snap,) = snapshots(world)
    assert snap.state.pr.endswith("/merge_requests/2")
    refs = world.raw(world.origin, "for-each-ref")
    assert sweep(world, "r-20261005T1000Z-0001") == []  # !2 is still open
    assert world.raw(world.origin, "for-each-ref") == refs
    gitlab.merge(2, world.merge_sha)
    (action,) = sweep(world, "r-20261005T1100Z-0002")
    assert action.what == "archive_opened"


def merge_archive_mr(world: MergedWorld, gitlab) -> None:
    """A human merges the archive MR (merge commit), as the forge and the base branch see it."""
    branch = "l4/archive/openspec/add-x"
    number = next(n for n, mr in gitlab.mrs.items() if mr["source_branch"] == branch)
    world.raw(world.repo, "fetch", "-q", "origin")
    world.raw(world.repo, "merge", "-q", "--no-ff", "-m", "Merge archive", f"origin/{branch}")
    world.raw(world.repo, "push", "-q", "origin", "main")
    gitlab.merge(number, world.raw(world.repo, "rev-parse", "HEAD").strip())
    world.raw(world.repo, "fetch", "-q", "--prune", "origin")


def remote_refs(world: MergedWorld) -> dict[str, str]:
    out = world.raw(world.origin, "for-each-ref", "--format=%(refname) %(objectname)", "refs/l4/")
    return {name: sha for name, _, sha in (line.partition(" ") for line in out.splitlines())}


def test_after_the_archive_mr_merged_the_lock_ref_moves_to_the_archived_namespace(world, gitlab):
    assert sweep(world, "r-20261005T0900Z-0000") == []
    world.merged_mr()
    sweep(world, "r-20261005T1000Z-0001")
    lock = LOCK.format("add-x")
    held = remote_refs(world)[lock]
    merge_archive_mr(world, gitlab)
    assert snapshots(world) == []  # the folder is gone from the base: nothing to look at any more
    (action,) = sweep(world, "r-20261005T1100Z-0002")
    archived = "refs/l4/archived/openspec/add-x/r-20261005T1100Z-0002"
    assert (action.unit, action.what, action.detail) == ("openspec:add-x", "retired", archived)
    assert remote_refs(world) == {archived: held}  # the same commit: its pending ledger is kept
    assert world.git.rev_parse(lock) is None and world.git.rev_parse(archived) == held
    assert sweep(world, "r-20261005T1200Z-0003") == []  # nothing left to do


def test_a_name_used_again_after_its_archive_starts_fresh(world, gitlab):
    world.merged_mr()
    sweep(world, "r-20261005T1000Z-0001")
    merge_archive_mr(world, gitlab)
    sweep(world, "r-20261005T1100Z-0002")
    folder = world.repo / "openspec" / "changes" / "add-x"
    (folder / "specs" / "cap-add-x").mkdir(parents=True)
    (folder / "proposal.md").write_text("# Proposal: again\n")
    (folder / "tasks.md").write_text("# Tasks\n\n- [ ] 1.1 first\n")
    world.raw(world.repo, "add", "-A")
    world.raw(world.repo, "commit", "-q", "-m", "seed add-x again")
    (snap,) = snapshots(world)
    assert snap.state.phase not in ("merged", "in_review")


def test_the_lock_ref_stays_while_the_archive_mr_is_not_merged(world, gitlab):
    world.merged_mr()
    sweep(world, "r-20261005T1000Z-0001")
    refs = remote_refs(world)
    assert sweep(world, "r-20261005T1100Z-0002")[0].what == "archive_existing"
    assert remote_refs(world) == refs


def test_a_lock_ref_of_a_unit_whose_folder_is_still_on_the_base_is_not_retired(world, gitlab):
    world.merged_mr()
    gitlab.merge(next(iter(gitlab.mrs)), world.merge_sha)
    sweep(world, "r-20261005T1000Z-0001")
    refs = remote_refs(world)
    sweep_with_no_snapshots = Sweeper(
        world.app("r-20261005T1100Z-0002"), world.cfg, world.git, world.forge(),
        PostMerge(world, world.app(), world.forge()), MergeDetector(world.git, base_branch="main"),
    )  # fmt: skip
    assert sweep_with_no_snapshots.run([]) == []  # this clone lists no unit, but the base still has the folder
    assert remote_refs(world) == refs


# --- the CI duty (M1.9, G2): the project's own pipeline on H -------------------------------------------------------


@pytest.fixture
def review(tmp_path, raw, git_environ, gitlab):
    return ReviewWorld(tmp_path, raw, git_environ, gitlab).build()


def ci_sweep(world: MergedWorld, run_id: str):
    app = world.app(run_id)
    forge = world.forge()
    detector = MergeDetector(world.git, base_branch="main")
    return Sweeper(app, world.cfg, world.git, forge, PostMerge(world, app, forge), detector, ci=True).run(
        snapshots(world)
    )


def ci_events(world: MergedWorld, run: str) -> list[dict]:
    return [e for e in pending_events(world) if e["run"] == run and e["type"].startswith("ci.")]


def test_red_project_job_on_h_is_recorded_once_per_h(review, gitlab):
    trace = "E assert 1 == 2\nFAILED t::x"
    gitlab.add_pipeline(review.handoff, [("test", "failed", {"trace": trace}), ("l4", "failed")])
    gitlab.add_pipeline(review.base, [("test", "success")])
    (action,) = ci_sweep(review, "r-20261005T1000Z-0001")
    assert action.what == "ci_failed" and "test" in action.detail and review.handoff[:10] in action.detail
    (event,) = ci_events(review, "r-20261005T1000Z-0001")
    assert event["type"] == "ci.failed" and event["head"] == review.handoff and event["preexisting"] == []
    [job] = event["jobs"]  # the `l4` job is the harness's own: never listed
    assert (job["name"], job["stage"], "FAILED t::x" in job["tail"]) == ("test", "test", True)
    assert job["url"].endswith(f"/-/jobs/{1001}")
    (snap,) = snapshots(review)
    assert snap.state.ci_heads == {review.handoff: "failed"} and snap.state.ci_failure.jobs[0]["name"] == "test"
    # the second sweep makes no write and no lock-ref commit
    refs, writes = review.raw(review.origin, "for-each-ref"), len(gitlab.writes())
    (again,) = ci_sweep(review, "r-20261005T1100Z-0002")
    assert again.what == "ci_failed" and "recorded" in again.detail
    assert review.raw(review.origin, "for-each-ref") == refs and len(gitlab.writes()) == writes
    assert not any(e["run"] == "r-20261005T1100Z-0002" for e in pending_events(review))


def test_green_or_running_pipeline_writes_nothing(review, gitlab):
    refs = review.raw(review.origin, "for-each-ref")
    assert [a.what for a in ci_sweep(review, "r-20261005T1000Z-0001")] == ["ci_green"]  # no pipeline at all
    gitlab.add_pipeline(review.handoff, [("test", "failed"), ("build", "running")])
    (running,) = ci_sweep(review, "r-20261005T1100Z-0002")
    assert running.what == "ci_waiting" and "running" in running.detail
    gitlab.pipelines.clear()
    gitlab.add_pipeline(review.handoff, [("test", "success"), ("soft", "failed", {"allow_failure": True})])
    (green,) = ci_sweep(review, "r-20261005T1200Z-0003")
    assert green.what == "ci_green"
    assert review.raw(review.origin, "for-each-ref") == refs  # nothing was written, nowhere
    assert not [e for e in pending_events(review) if e["run"] > "r-20261005T0000Z-0000"]


def test_a_branch_past_h_is_left_to_the_run(review, gitlab):
    gitlab.add_pipeline(review.handoff, [("test", "failed")])
    review.human_commit()
    refs = review.raw(review.origin, "for-each-ref")
    assert ci_sweep(review, "r-20261005T1000Z-0001") == []  # the person's commit supersedes H's pipeline
    assert review.raw(review.origin, "for-each-ref") == refs


def test_preexisting_red_is_recorded_without_a_failure(review, gitlab):
    gitlab.add_pipeline(review.handoff, [("always-red", "failed"), ("lint", "success")])
    gitlab.add_pipeline(review.base, [("always-red", "failed")])
    (action,) = ci_sweep(review, "r-20261005T1000Z-0001")
    assert action.what == "ci_preexisting" and "always-red" in action.detail
    (event,) = ci_events(review, "r-20261005T1000Z-0001")
    assert event["type"] == "ci.preexisting" and event["jobs"] == ["always-red"] and event["head"] == review.handoff
    (snap,) = snapshots(review)
    assert snap.state.ci_heads == {review.handoff: "preexisting"} and snap.state.ci_failure is None
    refs = review.raw(review.origin, "for-each-ref")
    assert ci_sweep(review, "r-20261005T1100Z-0002")[0].what == "ci_preexisting"
    assert review.raw(review.origin, "for-each-ref") == refs


def test_a_secret_in_a_job_log_is_redacted(review, gitlab):
    secret = "ghp_" + "abcdEFGH1234" * 3
    gitlab.add_pipeline(review.handoff, [("test", "failed", {"trace": f"curl -H 'Authorization: {secret}'\nFAILED"})])
    ci_sweep(review, "r-20261005T1000Z-0001")
    blob = review.raw(review.origin, "show", "refs/l4/locks/openspec/add-x:ledger-pending/r-20261005T1000Z-0001.jsonl")
    assert secret not in blob and "FAILED" in blob and "REDACTED" in blob


def test_ci_failed_records_the_failing_step_redacted(review, gitlab):
    secret = "ghp_" + "abcdEFGH1234" * 3
    trace = (
        "section_start:1:step_script\r\x1b[0KExecuting step_script\n"
        f"$ make check TOKEN={secret}\nFAILED t::x\n"
        "section_end:2:step_script\r\x1b[0K\n"
    )
    gitlab.add_pipeline(review.handoff, [("test", "failed", {"trace": trace})])
    ci_sweep(review, "r-20261005T1000Z-0001")
    blob = review.raw(review.origin, "show", "refs/l4/locks/openspec/add-x:ledger-pending/r-20261005T1000Z-0001.jsonl")
    assert secret not in blob
    (event,) = ci_events(review, "r-20261005T1000Z-0001")
    step = event["jobs"][0]["step"]
    assert step.startswith("make check TOKEN=") and "REDACTED" in step and len(step) <= 300


def test_a_forge_read_error_is_logged_and_the_unit_retried_next_time(review, gitlab, monkeypatch):
    from l4.forge.base import ForgeError
    from l4.forge.gitlab import GitLabForge

    gitlab.add_pipeline(review.handoff, [("test", "failed")])
    real = GitLabForge.list_pipeline_jobs

    def broken(self, sha):
        raise ForgeError("GitLab GET /pipelines: HTTP 502")

    monkeypatch.setattr(GitLabForge, "list_pipeline_jobs", broken)
    refs = review.raw(review.origin, "for-each-ref")
    assert ci_sweep(review, "r-20261005T1000Z-0001") == []  # logged, nothing raised, nothing written
    assert review.raw(review.origin, "for-each-ref") == refs
    monkeypatch.setattr(GitLabForge, "list_pipeline_jobs", real)
    assert ci_sweep(review, "r-20261005T1100Z-0002")[0].what == "ci_failed"


def test_the_sweeps_own_running_pipeline_on_the_base_does_not_hide_a_finished_one(review, gitlab):
    """The `l4` job starts at once (`needs: []`), so on a schedule, web or default-branch pipeline the project's jobs on
    the base head are still running when the sweep reads them. The newest *finished* attempt of each job on the base
    head decides; only a job that has no finished attempt there defers (G2 would otherwise never act)."""
    gitlab.add_pipeline(review.handoff, [("test", "failed"), ("always-red", "failed")])
    gitlab.add_pipeline(review.base, [("test", "success"), ("always-red", "failed")])  # the last push: finished
    gitlab.add_pipeline(review.base, [("test", "running"), ("always-red", "pending"), ("l4", "running")])  # this one
    (action,) = ci_sweep(review, "r-20261005T1000Z-0001")
    assert action.what == "ci_failed", action
    (event,) = ci_events(review, "r-20261005T1000Z-0001")
    assert [j["name"] for j in event["jobs"]] == ["test"] and event["preexisting"] == ["always-red"]


def test_a_base_job_with_no_finished_attempt_still_defers(review, gitlab):
    gitlab.add_pipeline(review.handoff, [("test", "failed")])
    gitlab.add_pipeline(review.base, [("test", "running"), ("l4", "running")])  # the only pipeline of the base head
    refs = review.raw(review.origin, "for-each-ref")
    (action,) = ci_sweep(review, "r-20261005T1000Z-0001")
    assert action.what == "ci_waiting" and "base" in action.detail
    assert review.raw(review.origin, "for-each-ref") == refs


def test_a_token_that_may_not_read_ci_skips_the_ci_duty_and_stops_nothing(review, gitlab, monkeypatch):
    """The CI duty reads more than the merge duty (GitHub: check runs, outside FORGE-001's contents, pull-requests and
    statuses). A 401/403 on those reads alone is logged and the duty skipped: it must not fail `l4 plan --sweep`, which
    would stop the job before `l4 run` for every unit. A token that is broken outright already fails the MR listing."""
    from l4.forge.base import ForgeAuthError
    from l4.forge.gitlab import GitLabForge

    gitlab.add_pipeline(review.handoff, [("test", "failed", {"trace": "FAILED t::x"})])
    real_jobs, real_tail = GitLabForge.list_pipeline_jobs, GitLabForge.job_log

    def forbidden(self, *args, **kwargs):
        raise ForgeAuthError("GitLab GET: HTTP 403 Forbidden", status=403)

    monkeypatch.setattr(GitLabForge, "list_pipeline_jobs", forbidden)
    refs = review.raw(review.origin, "for-each-ref")
    assert ci_sweep(review, "r-20261005T1000Z-0001") == []  # logged, nothing raised, nothing written
    assert review.raw(review.origin, "for-each-ref") == refs
    monkeypatch.setattr(GitLabForge, "list_pipeline_jobs", real_jobs)
    monkeypatch.setattr(GitLabForge, "job_log", forbidden)  # the log alone is forbidden: recorded without it
    (action,) = ci_sweep(review, "r-20261005T1100Z-0002")
    assert action.what == "ci_failed"
    (event,) = ci_events(review, "r-20261005T1100Z-0002")
    assert [(j["name"], j["tail"]) for j in event["jobs"]] == [("test", "")]
    monkeypatch.setattr(GitLabForge, "job_log", real_tail)


def test_ci_failed_prints_the_warning_line_once(review, gitlab, caplog):
    """M1.9 live F6: the sweep's writer had no observer, so the warning line of `ci.failed` never reached the console.
    It gets the progress trace filtered to `ci.failed` and `ci.preexisting`: no `run … started` line per unit."""
    import logging

    caplog.set_level(logging.INFO, logger="l4")
    gitlab.add_pipeline(review.handoff, [("test", "failed", {"trace": "FAILED t::x"}), ("l4", "failed")])
    gitlab.add_pipeline(review.base, [("test", "success")])
    ci_sweep(review, "r-20261005T1000Z-0001")
    lines = [r.getMessage() for r in caplog.records if r.name == "l4"]
    wanted = f"repository CI failed on {review.handoff[:10]}: test (pipeline 1); l4 run re-verifies"
    assert [m for m in lines if "repository CI failed" in m] == [f"openspec:add-x {wanted}"]
    assert not [m for m in lines if "started" in m or "finished" in m]  # no `run … started` line per unit
    assert [r.levelno for r in caplog.records if "repository CI failed" in r.getMessage()] == [logging.WARNING]
    ci_sweep(review, "r-20261005T1100Z-0002")  # H is recorded: nothing new, nothing printed again
    assert len([r for r in caplog.records if "repository CI failed" in r.getMessage()]) == 1


def test_a_preexisting_red_job_prints_its_line_too(review, gitlab, caplog):
    import logging

    caplog.set_level(logging.INFO, logger="l4")
    gitlab.add_pipeline(review.handoff, [("test", "failed")])
    gitlab.add_pipeline(review.base, [("test", "failed")])
    ci_sweep(review, "r-20261005T1000Z-0001")
    assert any("CI jobs red on H and on the base: test" in r.getMessage() for r in caplog.records)


# --- the `l4:resume` label (M1.11, W2) ------------------------------------------------------------------------

MEMBER, REPORTER, BOT, STRANGER = 3, 9, 7, 77  # user ids; the fake GitLab's own bot is 7


@pytest.fixture
def halted(run_l4, tdd_repo, forge_env, use_fake_gitlab, monkeypatch):  # noqa: F811
    """A unit halted on `max_task_attempts` with its MR on the fake GitLab, and the sweep pointed at the same fake."""
    gitlab = use_fake_gitlab
    gitlab.members = [
        {"id": MEMBER, "username": "maintainer", "access_level": 40, "state": "active"},
        {"id": REPORTER, "username": "reporter", "access_level": 20, "state": "active"},
        {"id": BOT, "username": "project_118_bot_x", "access_level": 30, "state": "active"},
    ]
    monkeypatch.setattr(
        sweeper_module, "make_forge",
        lambda cfg, environ, **kw: GitLabForge(API, PROJECT, TOKEN, transport=gitlab.transport(), sleep=lambda s: None),
    )  # fmt: skip
    run = run_l4([Step(structured=result("red"))], implementer={"max_task_attempts": 1})
    assert run.code == 13
    return run


def set_label(gitlab, event_id: int, user: int, *, action: str = "add", name: str = "l4:resume") -> None:
    """What a person does on the MR: the label and the forge's record of who did it."""
    mr = gitlab.mrs[1]
    if action == "add" and name not in mr["labels"]:
        mr["labels"].append(name)
    if action == "remove" and name in mr["labels"]:
        mr["labels"].remove(name)
    gitlab.label_events.setdefault(1, []).append(
        {"id": event_id, "action": action, "created_at": "2026-10-06T12:00:00.000Z", "user": {"id": user},
         "label": {"name": name}}
    )  # fmt: skip


def plan_sweep(run) -> int:
    return main(["plan", "--sweep", "--repo", str(run.tdd.repo)], environ=run.tdd.environ)


def test_a_member_label_resumes_a_halted_unit_once(halted, use_fake_gitlab):
    set_label(use_fake_gitlab, 100, MEMBER)
    assert plan_sweep(halted) == 0
    [resumed] = halted.events("unit.resumed")
    assert (resumed["signal"], resumed["by"], resumed["reason"]) == ("label:100", "member", "label l4:resume")
    assert halted.triggers()[-1] == "resumed"
    assert "MEMBER" not in json.dumps(resumed) and "maintainer" not in json.dumps(resumed)  # no username committed
    assert plan_sweep(halted) == 0  # the same label event again: nothing
    assert len(halted.events("unit.resumed")) == 1


def test_a_non_member_label_is_ignored_and_said_once(halted, use_fake_gitlab, capsys):
    set_label(use_fake_gitlab, 101, STRANGER)
    capsys.readouterr()
    assert plan_sweep(halted) == 0
    assert plan_sweep(halted) == 0
    assert halted.events("unit.resumed") == []
    [refused] = halted.events("resume.refused")
    assert refused["signal"] == "label:101" and "not a member" in refused["why"]
    assert capsys.readouterr().err.count("was not honoured") == 1
    assert "label:101" in use_fake_gitlab.notes[1][-1]["body"]  # a section of the sticky note
    set_label(use_fake_gitlab, 102, REPORTER)  # a later event is judged on its own
    assert plan_sweep(halted) == 0
    assert [e["signal"] for e in halted.events("resume.refused")] == ["label:101", "label:102"]


def test_the_bot_s_own_label_is_refused(halted, use_fake_gitlab):
    set_label(use_fake_gitlab, 103, BOT)
    assert plan_sweep(halted) == 0
    assert halted.events("unit.resumed") == []
    assert "harness" in halted.events("resume.refused")[0]["why"]


def test_the_same_label_event_never_resumes_twice(halted, use_fake_gitlab, run_l4):  # noqa: F811
    set_label(use_fake_gitlab, 100, MEMBER)
    plan_sweep(halted)
    again = run_l4([Step(structured=result("red"))], implementer={"max_task_attempts": 1})  # halts again
    assert again.code == 13
    set_label(use_fake_gitlab, 100, MEMBER, action="add")  # the label is on the MR, with no new event
    assert plan_sweep(again) == 0
    assert len(again.events("unit.resumed")) == 1
    set_label(use_fake_gitlab, 104, MEMBER)  # a member adds it again: a new event, a new resume
    plan_sweep(again)
    assert [e["signal"] for e in again.events("unit.resumed")] == ["label:100", "label:104"]


def escalated_snapshot(tdd_repo, *, fix_round: int, halt_reason: str | None = None, feedback_used: int = 0):
    """The unit as the sweep reads it, with its phase and fix rounds set (the ledger is that of the halted unit)."""
    from l4.config.loader import load_config
    from l4.specs.openspec import OpenSpecProvider
    from l4.vcs.git import Git

    cfg = load_config(tdd_repo.repo)
    git = Git(tdd_repo.repo, environ=tdd_repo.environ)
    git.run("fetch", "-q", "origin", "+refs/heads/*:refs/remotes/origin/*")
    provider = OpenSpecProvider(tdd_repo.repo, tdd_repo.environ)
    [snap] = [load_snapshot(provider, git, ref, branch_prefix="l4/") for ref in provider.list_units()]
    snap.state.phase = "escalated"
    snap.state.fix_round = fix_round
    snap.state.halt_reason = halt_reason
    snap.state.feedback_rounds_used = feedback_used
    return cfg, git, snap


def sweep_escalated(
    tdd_repo, monkeypatch, *, fix_round: int, halt_reason: str | None = None, feedback_used: int = 0
) -> tuple[list, list[tuple[str, int, int]]]:
    """Run the sweep over an escalated snapshot with the resume itself stubbed: what the sweep decides is the test."""
    from types import SimpleNamespace

    from l4.context import AppContext
    from l4.redact import Redactor

    cfg, git, snap = escalated_snapshot(
        tdd_repo, fix_round=fix_round, halt_reason=halt_reason, feedback_used=feedback_used
    )
    calls: list[tuple[str, int, int]] = []

    def resumer(self, snapshot, signal, more, more_feedback):
        calls.append((signal.signal, more, more_feedback))
        return SimpleNamespace(outcome=SimpleNamespace(phase_after="verifying"))

    monkeypatch.setattr(sweeper_module.Sweeper, "_resume_in_worktree", resumer)
    app = AppContext(tdd_repo.repo, None, "human", 0, "r-20261006T1800Z-ab12", tdd_repo.environ, Redactor({}))
    return sweeper_module.sweep(app, cfg, git, [snap], ci=True), calls


def test_a_member_label_resumes_an_escalated_unit_with_one_more_fix_round(
    halted, use_fake_gitlab, tdd_repo, monkeypatch
):
    set_label(use_fake_gitlab, 105, MEMBER)
    actions, calls = sweep_escalated(tdd_repo, monkeypatch, fix_round=99)  # more than any limit: all rounds are used
    assert [a.what for a in actions] == ["resumed"] and "1 more fix round" in actions[0].detail
    assert calls == [("label:105", 1, 0)]


def test_a_member_label_on_a_unit_escalated_at_the_feedback_limit_gives_one_feedback_round(
    halted, use_fake_gitlab, tdd_repo, monkeypatch
):
    """L4-FBK-006: `budget.extended{feedback_rounds: 1}` instead of `fix_rounds: 1`, once per label event."""
    set_label(use_fake_gitlab, 107, MEMBER)
    actions, calls = sweep_escalated(
        tdd_repo, monkeypatch, fix_round=99, halt_reason="feedback_rounds_exhausted", feedback_used=5
    )  # the fix rounds are used up as well: the reason decides which budget the label extends
    assert [a.what for a in actions] == ["resumed"] and "1 more feedback round" in actions[0].detail
    assert calls == [("label:107", 0, 1)]


def test_the_label_on_an_escalated_unit_with_rounds_left_grants_no_extension(
    halted, use_fake_gitlab, tdd_repo, monkeypatch
):
    set_label(use_fake_gitlab, 106, MEMBER)
    actions, calls = sweep_escalated(tdd_repo, monkeypatch, fix_round=0)  # escalated for another reason
    assert [a.what for a in actions] == ["resumed"] and calls == [("label:106", 0, 0)]


def test_a_non_member_label_on_an_escalated_unit_is_refused_like_on_a_halted_one(
    halted, use_fake_gitlab, tdd_repo, monkeypatch
):
    set_label(use_fake_gitlab, 107, STRANGER)
    actions, calls = sweep_escalated(tdd_repo, monkeypatch, fix_round=99)
    assert [a.what for a in actions] == ["resume_refused"] and calls == []
    assert "not a member" in actions[0].detail and "escalated" not in actions[0].detail


def test_the_resume_commit_carries_l4_run_and_skip_ci(halted, use_fake_gitlab):
    set_label(use_fake_gitlab, 100, MEMBER)
    plan_sweep(halted)
    message = halted.raw(halted.tdd.origin, "log", "-1", "--format=%B", "l4/openspec/add-discount-codes")
    assert message.splitlines()[0] == "chore(add-discount-codes): resume [skip ci]"
    assert "L4-Run: r-" in message


def test_a_push_on_a_halted_branch_names_the_label_once(halted, use_fake_gitlab, tdd_repo, raw, capsys):
    clone = tdd_repo.repo.parent / "owner"
    branch = "l4/openspec/add-discount-codes"
    raw(tdd_repo.repo.parent, "clone", "-q", "--branch", branch, str(tdd_repo.origin), str(clone))
    (clone / "owner.txt").write_text("a task edit")
    raw(clone, "add", "-A")
    raw(clone, "commit", "-q", "-m", "edit the task")
    raw(clone, "push", "-q", "origin", branch)
    capsys.readouterr()
    assert plan_sweep(halted) == 0
    hint = "a person pushed after the halt: add the label l4:resume to resume"
    assert capsys.readouterr().err.count(hint) == 1
    assert plan_sweep(halted) == 0
    assert capsys.readouterr().err.count(hint) == 0  # once per head
    [recorded] = halted.events("resume.hint")
    assert recorded["head"] == raw(tdd_repo.origin, "rev-parse", branch).strip()
    raw(clone, "commit", "-q", "--allow-empty", "-m", "another")
    raw(clone, "push", "-q", "origin", branch)
    assert plan_sweep(halted) == 0
    assert capsys.readouterr().err.count(hint) == 1  # a new head says it again
    assert halted.events("unit.resumed") == []
