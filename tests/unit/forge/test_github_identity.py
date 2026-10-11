"""github-parity 1.1 (L4-GHP-001, SCN-GHP-01, SCN-GHP-02): who the GitHub token is, and the sticky note's author."""

import pytest

from l4.forge.base import STICKY_MARKER, ForgeError
from l4.forge.github import ACTIONS_BOT_ID, ACTIONS_BOT_LOGIN, GitHubForge

from ._github_helpers import API, LOGIN, REPO, TOKEN, USER_ID, FakeGitHub


def make(github: FakeGitHub, environ: dict[str, str] | None = None) -> GitHubForge:
    return GitHubForge(
        REPO, TOKEN, api_url=API, transport=github.transport(), sleep=lambda s: None, environ=environ or {}
    )


def test_own_user_id_is_the_id_of_get_user():
    assert make(FakeGitHub()).own_user_id() == USER_ID


def test_github_token_403_in_actions_is_the_actions_bot():
    github = FakeGitHub(user_status=403)
    forge = make(github, {"GITHUB_ACTIONS": "true"})
    assert forge.own_user_id() == ACTIONS_BOT_ID == 41898282
    assert forge._me() == ACTIONS_BOT_LOGIN == "github-actions[bot]"


def test_a_403_outside_actions_is_no_identity():
    forge = make(FakeGitHub(user_status=403), {})
    assert forge.own_user_id() is None
    with pytest.raises(ForgeError):
        forge._me()


def test_a_403_with_actions_not_true_is_no_identity():
    assert make(FakeGitHub(user_status=403), {"GITHUB_ACTIONS": "false"}).own_user_id() is None


def test_a_server_error_in_actions_is_not_the_bot():
    github = FakeGitHub(user_status=404)
    assert make(github, {"GITHUB_ACTIONS": "true"}).own_user_id() is None


def test_scn_ghp_01_the_actions_bot_note_is_found_and_updated():
    github = FakeGitHub(user_status=403)
    github.comments[1] = [
        {"id": 5, "body": f"{STICKY_MARKER}\nold", "user": {"login": ACTIONS_BOT_LOGIN, "id": ACTIONS_BOT_ID}}
    ]
    make(github, {"GITHUB_ACTIONS": "true"}).upsert_sticky_note(1, "new")
    assert len(github.comments[1]) == 1
    assert github.comments[1][0]["body"] == f"{STICKY_MARKER}\nnew"


def test_scn_ghp_02_a_persons_comment_with_the_marker_is_never_rewritten():
    github = FakeGitHub(user_status=403)
    github.comments[1] = [{"id": 5, "body": f"{STICKY_MARKER}\nquoted", "user": {"login": "mallory", "id": 9}}]
    make(github, {"GITHUB_ACTIONS": "true"}).upsert_sticky_note(1, "new")
    assert github.comments[1][0]["body"] == f"{STICKY_MARKER}\nquoted"
    assert len(github.comments[1]) == 2


def test_the_login_alone_is_not_the_author():
    """Marker, login and id together: a comment with our login but another id (a renamed account) is not ours."""
    github = FakeGitHub()
    github.comments[1] = [{"id": 5, "body": f"{STICKY_MARKER}\nx", "user": {"login": LOGIN, "id": USER_ID + 1}}]
    make(github).upsert_sticky_note(1, "new")
    assert github.comments[1][0]["body"] == f"{STICKY_MARKER}\nx"
    assert len(github.comments[1]) == 2
