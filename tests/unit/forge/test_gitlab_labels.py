import pytest

from .conftest import FakeGitLab

BRANCH = "l4/openspec/x"


def test_ensure_labels_creates_only_the_missing_ones(gitlab: FakeGitLab, make_forge_client):
    gitlab.labels = ["bug", "l4:ready"]
    make_forge_client().ensure_labels(["l4:ready", "l4:implementing"])
    assert gitlab.labels == ["bug", "l4:ready", "l4:implementing"]
    assert [(m, p) for m, p in gitlab.writes()] == [("POST", "/projects/118/labels")]


def test_ensure_labels_survives_a_label_created_meanwhile(gitlab: FakeGitLab, make_forge_client):
    forge = make_forge_client()
    real = gitlab.labels_route

    def racing(method, query, body):
        if method == "POST":
            gitlab.labels.append(body["name"])  # another run created it between our GET and POST
        return real(method, query, body)

    gitlab.labels_route = racing  # type: ignore[method-assign]
    forge.ensure_labels(["l4:ready"])
    assert gitlab.labels == ["l4:ready"]


def test_managed_labels_keep_foreign_labels_and_single_phase(gitlab: FakeGitLab, make_forge_client):
    forge = make_forge_client()
    forge.create_pr(BRANCH, "main", "t", "b")
    gitlab.mrs[1]["labels"] = ["bug", "l4:implementing", "l4:needs-answers", "team::core"]
    pr = forge.set_managed_labels(1, ["l4:verified"], "l4:")
    assert sorted(gitlab.mrs[1]["labels"]) == ["bug", "l4:verified", "team::core"]
    assert sorted(pr.labels) == ["bug", "l4:verified", "team::core"]
    forge.set_managed_labels(1, ["l4:in_review", "l4:needs-answers"], "l4:")
    assert sorted(gitlab.mrs[1]["labels"]) == ["bug", "l4:in_review", "l4:needs-answers", "team::core"]


def test_managed_labels_write_nothing_when_nothing_differs(gitlab: FakeGitLab, make_forge_client):
    forge = make_forge_client()
    forge.create_pr(BRANCH, "main", "t", "b")
    forge.set_managed_labels(1, ["l4:ready"], "l4:")
    gitlab.requests.clear()
    forge.set_managed_labels(1, ["l4:ready"], "l4:")
    assert gitlab.writes() == []


@pytest.mark.parametrize("bad", ["bug", "l4:a,b"])
def test_managed_labels_refuse_foreign_or_comma_names(bad: str, gitlab: FakeGitLab, make_forge_client):
    forge = make_forge_client()
    forge.create_pr(BRANCH, "main", "t", "b")
    with pytest.raises(ValueError):
        forge.set_managed_labels(1, [bad], "l4:")


def test_label_events_parse_the_probed_shape(gitlab: FakeGitLab, make_forge_client):
    """The answer of `resource_label_events` as probed on 2026-10-06 (ids and fields only, no project text)."""
    forge = make_forge_client()
    forge.create_pr(BRANCH, "main", "t", "b")
    gitlab.label_events[1] = [
        {"id": 1396, "action": "add", "created_at": "2026-10-06T12:33:07.000Z",
         "user": {"id": 62, "username": "project_119_bot_x", "name": "l4", "state": "active"},
         "label": {"id": 5, "name": "l4:halted", "color": "#6b7280"}},
        {"id": 1397, "action": "remove", "created_at": "2026-10-06T12:40:00.000Z",
         "user": {"id": 3, "username": "maintainer", "state": "active"}, "label": None},
    ]  # fmt: skip
    events = forge.label_events(1)
    assert [(e.id, e.label, e.action, e.user_id) for e in events] == [
        (1396, "l4:halted", "add", 62),
        (1397, "", "remove", 3),
    ]
    assert events[0].created_at == "2026-10-06T12:33:07.000Z"


def test_member_access_reads_access_level_and_a_404_is_none(gitlab: FakeGitLab, make_forge_client):
    gitlab.members = [{"id": 62, "username": "project_119_bot_x", "access_level": 30, "state": "active"}]
    forge = make_forge_client()
    assert forge.member_access(62) == 30
    assert forge.member_access(999) is None  # not a member: GitLab says 404


def test_own_user_id_reads_the_token_user(gitlab: FakeGitLab, make_forge_client):
    gitlab.bot_id = 62
    assert make_forge_client().own_user_id() == 62
