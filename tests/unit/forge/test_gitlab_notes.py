import httpx
import pytest

from l4.forge.base import ForgeError

from .conftest import FakeGitLab

BRANCH = "l4/openspec/x"
MARKER = "<!-- l4:sticky -->"


def forge_with_mr(gitlab: FakeGitLab, make_forge_client):
    forge = make_forge_client()
    forge.create_pr(BRANCH, "main", "t", "b")
    return forge


def test_sticky_note_updated_in_place_and_noop_when_equal(gitlab: FakeGitLab, make_forge_client):
    forge = forge_with_mr(gitlab, make_forge_client)
    forge.upsert_sticky_note(1, "- Q-001: first")
    (note,) = gitlab.notes[1]
    assert note["body"] == f"{MARKER}\n- Q-001: first"
    forge.upsert_sticky_note(1, "- Q-001: first and second")
    assert [n["body"] for n in gitlab.notes[1]] == [f"{MARKER}\n- Q-001: first and second"]  # in place, no second note
    gitlab.requests.clear()
    forge.upsert_sticky_note(1, "- Q-001: first and second")
    assert gitlab.writes() == []  # unchanged: no write


def test_only_the_bots_own_note_with_the_marker_at_its_start_counts(gitlab: FakeGitLab, make_forge_client):
    forge = forge_with_mr(gitlab, make_forge_client)
    gitlab.notes[1] = [
        {"id": 1, "body": f"{MARKER}\nforged by someone else", "system": False, "author": {"id": 99}},
        {"id": 2, "body": f"a human quoting {MARKER} in a sentence", "system": False, "author": {"id": gitlab.bot_id}},
        {"id": 3, "body": f"{MARKER}\nsystem", "system": True, "author": {"id": gitlab.bot_id}},
    ]
    forge.upsert_sticky_note(1, "mine")
    assert [n["body"] for n in gitlab.notes[1][:3]] == [
        f"{MARKER}\nforged by someone else", f"a human quoting {MARKER} in a sentence", f"{MARKER}\nsystem"
    ]
    assert gitlab.notes[1][3]["body"] == f"{MARKER}\nmine"


def test_the_note_is_found_on_a_later_page(gitlab: FakeGitLab, make_forge_client):
    forge = forge_with_mr(gitlab, make_forge_client)
    gitlab.note_page_size = 2
    gitlab.notes[1] = [{"id": n, "body": f"note {n}", "system": False, "author": {"id": 5}} for n in range(1, 5)]
    gitlab.notes[1].append({"id": 5, "body": f"{MARKER}\nold", "system": False, "author": {"id": gitlab.bot_id}})
    forge.upsert_sticky_note(1, "new")
    assert gitlab.notes[1][4]["body"] == f"{MARKER}\nnew" and len(gitlab.notes[1]) == 5


@pytest.mark.parametrize("status", [401, 403, 404, 500])
def test_a_failing_get_user_falls_back_to_the_single_project_bot_member(gitlab: FakeGitLab, make_forge_client, status):
    forge = forge_with_mr(gitlab, make_forge_client)
    gitlab.user_status = status
    gitlab.members = [{"id": 3, "username": "alice"}, {"id": gitlab.bot_id, "username": "project_118_bot_ab12cd"}]
    gitlab.notes[1] = [
        {"id": 1, "body": f"{MARKER}\nforged", "system": False, "author": {"id": 99}},
        {"id": 2, "body": f"{MARKER}\nold", "system": False, "author": {"id": gitlab.bot_id}},
    ]
    forge.upsert_sticky_note(1, "new")
    assert [n["body"] for n in gitlab.notes[1]] == [f"{MARKER}\nforged", f"{MARKER}\nnew"]


@pytest.mark.parametrize(
    "members",
    [[], [{"id": 3, "username": "alice"}],
     [{"id": 4, "username": "project_118_bot_a"}, {"id": 5, "username": "project_118_bot_b"}]],
)
def test_a_note_is_not_written_when_the_bot_cannot_be_told(gitlab: FakeGitLab, make_forge_client, members):
    forge = forge_with_mr(gitlab, make_forge_client)
    gitlab.user_status, gitlab.members = 403, members
    gitlab.requests.clear()
    with pytest.raises(ForgeError, match="cannot tell which user is the bot"):
        forge.upsert_sticky_note(1, "new")
    assert gitlab.writes() == [] and gitlab.notes.get(1, []) == []
    gitlab.requests.clear()
    with pytest.raises(ForgeError):
        forge.upsert_sticky_note(1, "again")
    assert gitlab.requests == []  # the answer is kept: no more calls this run


def test_a_user_answer_without_an_id_is_a_failed_lookup(gitlab: FakeGitLab, make_forge_client):
    forge = forge_with_mr(gitlab, make_forge_client)
    gitlab.fail_next = [httpx.Response(200, json={"username": "l4-bot"})]
    gitlab.members = [{"id": gitlab.bot_id, "username": "project_118_bot_x"}]
    forge.upsert_sticky_note(1, "x")
    assert [n["body"] for n in gitlab.notes[1]] == [f"{MARKER}\nx"]
