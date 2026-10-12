"""github-parity 1.3 (L4-GHP-007): who set a label and what access they have, read from GitHub."""

import pytest

from l4.forge.base import LabelEvent
from l4.forge.github import GitHubForge

from ._github_helpers import API, REPO, TOKEN, FakeGitHub


@pytest.fixture
def github() -> FakeGitHub:
    return FakeGitHub()


@pytest.fixture
def forge(github) -> GitHubForge:
    return GitHubForge(REPO, TOKEN, api_url=API, transport=github.transport(), sleep=lambda s: None)


def event(id_: int, kind: str, label: str | None, actor: int | None, at: str = "2026-10-11T10:00:00Z") -> dict:
    return {
        "id": id_, "event": kind, "created_at": at, "actor": {"id": actor} if actor is not None else None,
        "label": {"name": label} if label else None,
    }  # fmt: skip


def test_label_events_keep_labeled_and_unlabeled_oldest_first(github, forge):
    github.issue_events[3] = [
        event(30, "unlabeled", "l4:resume", 5, "2026-10-11T12:00:00Z"),
        event(10, "labeled", "l4:halted", 7),
        event(20, "labeled", "l4:resume", 5, "2026-10-11T11:00:00Z"),
        {"id": 25, "event": "assigned", "actor": {"id": 5}, "created_at": "x"},
        {"id": 26, "event": "commented", "actor": {"id": 5}, "created_at": "x"},
    ]
    assert forge.label_events(3) == [
        LabelEvent(10, "l4:halted", "add", 7, "2026-10-11T10:00:00Z"),
        LabelEvent(20, "l4:resume", "add", 5, "2026-10-11T11:00:00Z"),
        LabelEvent(30, "l4:resume", "remove", 5, "2026-10-11T12:00:00Z"),
    ]


def test_label_events_page_and_tolerate_an_unknown_actor(github, forge):
    github.page_size = 2
    github.issue_events[3] = [event(i, "labeled", "l4:resume", i if i != 4 else None) for i in range(1, 6)]
    events = forge.label_events(3)
    assert [e.id for e in events] == [1, 2, 3, 4, 5]
    assert events[3].user_id is None
    assert github.requests[-1][1] == f"/repos/{REPO}/issues/3/events"


def test_label_events_without_any_is_empty(forge):
    assert forge.label_events(9) == []


@pytest.mark.parametrize(
    ("body", "level"),
    [
        ({"role_name": "admin", "permission": "admin"}, 50),
        ({"role_name": "maintain", "permission": "write"}, 40),
        ({"role_name": "write", "permission": "write"}, 30),
        ({"role_name": "triage", "permission": "read"}, 20),
        ({"role_name": "read", "permission": "read"}, 10),
        ({"permission": "write"}, 30),  # no role_name: the legacy field
        ({"role_name": "custom-role", "permission": "write"}, None),  # unknown role: no level
        ({"role_name": "none", "permission": "none"}, None),
        ({}, None),
    ],
)
def test_member_access_maps_the_role_to_a_level(github, forge, body, level):
    github.users[5] = "alice"
    github.permissions["alice"] = body
    assert forge.member_access(5) == level
    paths = [p for m, p, _, _ in github.requests]
    assert paths == ["/user/5", f"/repos/{REPO}/collaborators/alice/permission"]


def test_member_access_is_none_for_a_non_collaborator_or_unknown_user(github, forge):
    github.users[5] = "alice"  # no permission entry: 404
    assert forge.member_access(5) is None
    assert forge.member_access(99) is None  # no such user: 404
