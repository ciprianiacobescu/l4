"""squash-and-delete 2.1 (design D2, L4-YOLO-032): `Forge.merge_pr` pins the merge to the verified head. The request
shape and the answer mapping for GitHub and GitLab, and the squash commit of the local forge."""

import subprocess

import pytest

from l4.forge.base import MergeCall
from l4.forge.github import GitHubForge
from l4.forge.local import LocalForge

from ._github_helpers import API, REPO, TOKEN, FakeGitHub
from .conftest import PROJECT, FakeGitLab
from .conftest import TOKEN as GITLAB_TOKEN

BRANCH = "l4/openspec/add-discount-codes"
HEAD = "a" * 40
TITLE = "Add discount codes (#1)"
MESSAGE = "Squash of openspec:add-discount-codes: 3 commits, verified head " + HEAD + ".\n\nL4-Unit: openspec:x"


@pytest.fixture
def github() -> FakeGitHub:
    return FakeGitHub()


@pytest.fixture
def gh(github) -> GitHubForge:
    return GitHubForge(REPO, TOKEN, api_url=API, transport=github.transport(), sleep=lambda s: None)


def test_github_squash_request_shape_and_merged_answer(github, gh):
    github.add_pr(BRANCH)
    call = gh.merge_pr(1, sha=HEAD, title=TITLE, message=MESSAGE)
    assert call == MergeCall("merged", f"{1:040x}", call.detail) and gh.get_pr(1).state == "merged"
    assert github.writes() == [("PUT", f"/repos/{REPO}/pulls/1/merge")]
    assert [b for m, _, _, b in github.requests if m == "PUT"] == [
        {"merge_method": "squash", "sha": HEAD, "commit_title": TITLE, "commit_message": MESSAGE}
    ]


def test_github_409_is_head_moved(github, gh):
    github.add_pr(BRANCH)
    github.merge_status, github.merge_message = 409, "Head branch was modified. Review and try the merge again."
    call = gh.merge_pr(1, sha=HEAD, title=TITLE, message=MESSAGE)
    assert (call.status, call.sha) == ("head_moved", None) and "modified" in call.detail
    assert gh.get_pr(1).state == "open"


@pytest.mark.parametrize("status", [405, 422])
def test_github_405_and_422_are_refused_with_the_redacted_message(github, gh, status):
    github.add_pr(BRANCH)
    github.merge_status, github.merge_message = status, f"Squash merges are not allowed {TOKEN}"
    call = gh.merge_pr(1, sha=HEAD, title=TITLE, message=MESSAGE)
    assert (call.status, call.sha) == ("refused", None)
    assert "Squash merges are not allowed" in call.detail and TOKEN not in call.detail


def test_github_any_other_failure_raises(github, gh):
    from l4.forge.base import ForgeError

    github.add_pr(BRANCH)
    github.merge_status = 403
    with pytest.raises(ForgeError):
        gh.merge_pr(1, sha=HEAD, title=TITLE, message=MESSAGE)


def test_gitlab_squash_request_shape_and_merged_answer(gitlab: FakeGitLab, make_forge_client):
    forge = make_forge_client()
    forge.create_pr(BRANCH, "main", "t", "b")
    gitlab.requests.clear()
    call = forge.merge_pr(1, sha=HEAD, title=TITLE, message=MESSAGE)
    assert (call.status, call.sha) == ("merged", f"{1:040x}")  # squash_commit_sha: merge_commit_sha is empty
    base = f"/projects/{PROJECT}/merge_requests/1"
    assert gitlab.writes() == [("PUT", f"{base}/merge")]
    assert gitlab.requests[-1][3] == {
        "squash": True, "sha": HEAD, "squash_commit_message": f"{TITLE}\n\n{MESSAGE}",
        "merge_commit_message": f"{TITLE}\n\n{MESSAGE}", "should_remove_source_branch": False,
    }  # fmt: skip


def test_gitlab_reads_merge_commit_sha_when_that_is_the_one_filled(gitlab: FakeGitLab, make_forge_client):
    forge = make_forge_client()
    forge.create_pr(BRANCH, "main", "t", "b")
    gitlab.merge_sha_key = "merge_commit_sha"
    assert forge.merge_pr(1, sha=HEAD, title=TITLE, message=MESSAGE).sha == f"{1:040x}"


def test_gitlab_pr_falls_back_to_the_squash_commit_sha(gitlab: FakeGitLab, make_forge_client):
    forge = make_forge_client()
    forge.create_pr(BRANCH, "main", "t", "b")
    gitlab.mrs[1].update(state="merged", merge_commit_sha=None, squash_commit_sha="c" * 40)
    assert forge.get_pr(1).merge_commit_sha == "c" * 40


def test_gitlab_409_is_head_moved(gitlab: FakeGitLab, make_forge_client):
    forge = make_forge_client()
    forge.create_pr(BRANCH, "main", "t", "b")
    gitlab.merge_status, gitlab.merge_message = 409, "SHA does not match HEAD of source branch"
    call = forge.merge_pr(1, sha=HEAD, title=TITLE, message=MESSAGE)
    assert call.status == "head_moved" and call.sha is None and gitlab.mrs[1]["state"] == "opened"


@pytest.mark.parametrize("status", [405, 406, 422])
def test_gitlab_405_406_422_are_refused_with_the_message(gitlab: FakeGitLab, make_forge_client, status):
    forge = make_forge_client()
    forge.create_pr(BRANCH, "main", "t", "b")
    gitlab.merge_status, gitlab.merge_message = status, f"Squash is not allowed {GITLAB_TOKEN}"
    call = forge.merge_pr(1, sha=HEAD, title=TITLE, message=MESSAGE)
    assert call.status == "refused" and "Squash is not allowed" in call.detail and GITLAB_TOKEN not in call.detail


# --- the local forge -------------------------------------------------------------------------------------------------


def _git(cwd, *args) -> str:
    env = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null", "PATH": "/usr/bin:/bin:/usr/local/bin"}
    done = subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True)
    return done.stdout.strip()


@pytest.fixture
def origin(tmp_path):
    bare, work = tmp_path / "origin.git", tmp_path / "work"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    _git(tmp_path, "clone", "-q", str(bare), str(work))
    for key, value in (("user.name", "t"), ("user.email", "t@example.invalid"), ("commit.gpgsign", "false")):
        _git(work, "config", key, value)
    (work / "base.txt").write_text("base\n")
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "-m", "base")
    _git(work, "push", "-q", "origin", "main")
    _git(work, "checkout", "-q", "-b", BRANCH)
    for n in range(2):
        (work / f"u{n}.txt").write_text("unit\n")
        _git(work, "add", "-A")
        _git(work, "commit", "-q", "-m", f"step {n}")
    _git(work, "push", "-q", "origin", BRANCH)
    return bare, _git(work, "rev-parse", "HEAD")


def test_local_squash_commit_has_the_head_tree_on_the_target_tip(origin):
    bare, head = origin
    tip = _git(bare, "rev-parse", "refs/heads/main")
    forge = LocalForge(origin=bare)
    forge.create_pr(BRANCH, "main", "Add", "b")
    call = forge.merge_pr(1, sha=head, title=TITLE, message=MESSAGE)
    assert call.status == "merged" and call.sha == _git(bare, "rev-parse", "refs/heads/main") != head
    assert _git(bare, "rev-parse", f"{call.sha}^") == tip
    assert _git(bare, "rev-parse", f"{call.sha}^{{tree}}") == _git(bare, "rev-parse", f"{head}^{{tree}}")
    assert _git(bare, "log", "-1", "--format=%B", call.sha) == f"{TITLE}\n\n{MESSAGE}"
    view = forge.get_pr(1)
    assert (view.state, view.merge_commit_sha) == ("merged", call.sha)
    assert [c.name for c in forge.writes()] == ["create_pr", "merge"]


def test_local_a_head_that_is_not_the_pr_branch_tip_is_head_moved(origin):
    bare, head = origin
    forge = LocalForge(origin=bare)
    forge.create_pr(BRANCH, "main", "Add", "b")
    call = forge.merge_pr(1, sha=_git(bare, "rev-parse", "main"), title=TITLE, message=MESSAGE)
    assert call.status == "head_moved" and forge.get_pr(1).state == "open"
    assert _git(bare, "rev-parse", "refs/heads/main") != head
