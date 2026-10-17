import pytest

from l4.exitcodes import ExitCode
from l4.forge.pushfail import PushFailed
from l4.specs.base import ArchiveFailed

from .merged_world import RUN, MergedWorld

ARCHIVE_BRANCH = "l4/archive/openspec/add-x"


@pytest.fixture
def world(tmp_path, raw, git_environ, gitlab):
    return MergedWorld(tmp_path, raw, git_environ, gitlab).build()


def changed(world: MergedWorld) -> dict[str, str]:
    out = world.raw(world.origin, "diff", "--name-status", "--no-renames", f"main..{ARCHIVE_BRANCH}")
    return {line.split("\t")[1]: line.split("\t")[0] for line in out.splitlines()}


def test_archive_mr_contains_only_archive_changes(world):
    world.merged_mr()
    result = world.archiver().open_archive_pr(world.ref())
    assert result.status == "opened" and result.archived_as == "2026-10-05-add-x"
    (sha,) = world.archive_commits(ARCHIVE_BRANCH)
    assert world.raw(world.origin, "rev-parse", f"{sha}^").strip() == world.merge_sha  # on the latest base
    paths = changed(world)
    moved = "openspec/changes/archive/2026-10-05-add-x/"
    assert {p for p in paths if not p.startswith(moved) and not p.startswith("openspec/changes/add-x/")} == {
        "openspec/specs/cap-add-x/spec.md"
    }
    assert paths["openspec/specs/cap-add-x/spec.md"] == "A"
    assert all(s == "D" for p, s in paths.items() if p.startswith("openspec/changes/add-x/"))
    assert paths[f"{moved}tasks.md"] == "A" and paths[f"{moved}proposal.md"] == "A"


def test_commit_has_the_trailers_and_no_skip_ci(world):
    world.merged_mr()
    world.archiver().open_archive_pr(world.ref())
    message = world.raw(world.origin, "log", "-1", "--format=%B", ARCHIVE_BRANCH)
    assert message.splitlines()[0] == "chore(add-x): archive"
    assert "[skip ci]" not in message
    assert "\nL4-Run: r-20261005T1000Z-bbbb\n" in "\n" + message  # the `l4/**` rule `when: never` matches this
    assert "L4-Phase: archived" in message and "L4-Unit: openspec:add-x" in message


def test_the_mr_is_ready_with_the_archive_title_and_no_run_trailer_in_the_body(world, gitlab):
    world.merged_mr()
    result = world.archiver().open_archive_pr(world.ref())
    mr = gitlab.mrs[result.pr.number]
    assert mr["title"] == "[l4] archive add-x" and not mr["title"].lower().startswith("draft")
    assert mr["source_branch"] == ARCHIVE_BRANCH and mr["target_branch"] == "main"
    assert "L4-Run:" not in mr["description"]


def test_the_pending_ledger_is_folded_into_the_archived_ledger_and_the_lock_ref_stays(world):
    world.merged_mr()
    pending = world.raw(world.origin, "show", f"refs/l4/locks/openspec/add-x:ledger-pending/{RUN}.jsonl")
    on_main = world.raw(world.repo, "show", f"main:openspec/changes/add-x/.l4/ledger/{RUN}.jsonl")
    assert pending.startswith(on_main) and pending != on_main  # the tail after H is only in the lock ref
    world.archiver().open_archive_pr(world.ref())
    archived = world.raw(
        world.origin, "show", f"{ARCHIVE_BRANCH}:openspec/changes/archive/2026-10-05-add-x/.l4/ledger/{RUN}.jsonl"
    )
    assert archived == pending
    assert world.raw(world.origin, "for-each-ref", "refs/l4/locks/").strip()  # nothing is dropped here


def test_extra_path_aborts_archive_pr(world, gitlab):
    """SCN-ARC-28: an archive that touched a file outside the unit's paths builds no branch and no MR."""
    world.merged_mr()
    world.provider_options = {"stray": "src/pricing/cart.py"}
    result = world.archiver().open_archive_pr(world.ref())
    assert result.status == "failed" and "src/pricing/cart.py" in result.detail
    assert ARCHIVE_BRANCH not in world.remote_branches()
    assert len(gitlab.mrs) == 1  # the merged MR of the unit and nothing else


def test_a_refused_gate_builds_nothing(tmp_path, raw, git_environ, gitlab):
    world = MergedWorld(tmp_path, raw, git_environ, gitlab).build(tasks="- [x] 1.1 a\n- [ ] 1.2 b\n")
    world.merged_mr()
    result = world.archiver().open_archive_pr(world.ref())
    assert result.status == "failed" and "1.2" in result.detail
    assert ARCHIVE_BRANCH not in world.remote_branches()


def test_a_cli_error_is_a_failed_archive_naming_its_code(world):
    world.merged_mr()
    world.provider_options = {"refuse_with": ArchiveFailed("archive_target_exists", "Archive 'x' already exists.")}
    result = world.archiver().open_archive_pr(world.ref())
    assert result.status == "failed" and "archive_target_exists" in result.detail
    assert ARCHIVE_BRANCH not in world.remote_branches()


def test_second_unit_waits_for_first_archive_pr(world, gitlab):
    """SCN-ARC-20: no second archive MR while one is open; afterwards the next is built on the new base."""
    world.merged_mr()
    forge = world.forge()
    first = forge.create_pr("l4/archive/openspec/other", "main", "[l4] archive other", "b", draft=False)
    waiting = world.archiver().open_archive_pr(world.ref())
    assert waiting.status == "pending" and waiting.pr.number == first.number
    assert ARCHIVE_BRANCH not in world.remote_branches()
    gitlab.merge(first.number, None)  # the first archive MR merges and main moves
    head = world.advance_base()
    opened = world.archiver().open_archive_pr(world.ref())
    assert opened.status == "opened"
    (sha,) = world.archive_commits(ARCHIVE_BRANCH)
    assert world.raw(world.origin, "rev-parse", f"{sha}^").strip() == head


def test_an_open_archive_mr_of_the_unit_is_left_alone(world):
    world.merged_mr()
    first = world.archiver().open_archive_pr(world.ref())
    pushes = sum("push" in a for a in world.git.history)
    again = world.archiver().open_archive_pr(world.ref())
    assert again.status == "existing" and again.pr.number == first.pr.number
    assert sum("push" in a for a in world.git.history) == pushes


def test_a_pushed_branch_without_an_mr_gets_its_mr(world, gitlab):
    world.merged_mr()
    world.archiver().open_archive_pr(world.ref())
    del gitlab.mrs[2]  # the MR creation was lost after the push
    result = world.archiver().open_archive_pr(world.ref())
    assert result.status == "opened" and len(world.archive_commits(ARCHIVE_BRANCH)) == 1


def test_a_branch_whose_mr_a_human_closed_is_not_reopened(world, gitlab):
    world.merged_mr()
    world.archiver().open_archive_pr(world.ref())
    gitlab.mrs[2]["state"] = "closed"
    result = world.archiver().open_archive_pr(world.ref())
    assert result.status == "skipped" and len(gitlab.mrs) == 2


def test_a_unit_that_is_not_in_the_base_has_nothing_to_archive(tmp_path, raw, git_environ, gitlab):
    world = MergedWorld(tmp_path, raw, git_environ, gitlab).build(archive_in_merge=True)
    world.merged_mr()
    result = world.archiver().open_archive_pr(world.ref())
    assert result.status == "archived" and ARCHIVE_BRANCH not in world.remote_branches()


def test_a_branch_ledger_that_is_not_a_prefix_of_the_pending_one_stops_the_archive(world):
    world.merged_mr()
    ledger = world.repo / "openspec/changes/add-x/.l4/ledger" / f"{RUN}.jsonl"
    ledger.write_text(ledger.read_text().replace("verify_pass", "edited!!!"))
    world.raw(world.repo, "commit", "-q", "-am", "someone edits the ledger")
    world.raw(world.repo, "push", "-q", "origin", "main")
    result = world.archiver().open_archive_pr(world.ref())
    assert result.status == "failed" and ARCHIVE_BRANCH not in world.remote_branches()


def test_a_refused_push_is_an_explained_forge_error_and_no_mr(world, gitlab):
    world.merged_mr()
    hook = world.origin / "hooks" / "pre-receive"
    hook.write_text(
        "#!/bin/sh\necho 'GitLab: You are not allowed to push code to protected branches on this project' >&2\nexit 1\n"
    )
    hook.chmod(0o755)
    with pytest.raises(PushFailed) as caught:
        world.archiver().open_archive_pr(world.ref())
    assert caught.value.code is ExitCode.DOCTOR_FAILED and "protected branch or push rule" in str(caught.value)
    assert len(gitlab.mrs) == 1


def test_a_unit_already_archived_on_the_base_builds_no_worktree(world, monkeypatch):
    """squash-and-delete D8: once the archive branch is deleted, every sweep would build a worktree to find out that the
    unit's folder is gone; the folder is looked up on the base first."""
    world.merged_mr()
    world.archiver().open_archive_pr(world.ref())
    world.raw(world.origin, "update-ref", "refs/heads/main", f"refs/heads/{ARCHIVE_BRANCH}")  # the archive landed ...
    world.raw(world.origin, "update-ref", "-d", f"refs/heads/{ARCHIVE_BRANCH}")  # ... and its branch was deleted
    world.gitlab.mrs[2]["state"] = "merged"
    archiver = world.archiver()
    built = []
    monkeypatch.setattr(archiver._worktrees, "ensure_from_base", lambda *a, **k: built.append(a))
    result = archiver.open_archive_pr(world.ref())
    assert result.status == "archived" and built == []
    assert "no longer under" in result.detail
