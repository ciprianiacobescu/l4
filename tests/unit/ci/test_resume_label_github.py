"""github-parity 1.3 (SCN-GHP-09, SCN-GHP-10): `resume_signal` fed by the GitHub forge's events and levels."""

import pytest
from tests.unit.forge._github_helpers import API, REPO, TOKEN, USER_ID, FakeGitHub

from l4.ci.resume_label import Refusal, ResumeSignal, resume_signal
from l4.forge.github import GitHubForge

LABEL = "l4:resume"
WRITER, READER = 11, 12


@pytest.fixture
def github() -> FakeGitHub:
    fake = FakeGitHub()
    fake.users = {WRITER: "wanda", READER: "rory"}
    fake.permissions = {"wanda": {"role_name": "write"}, "rory": {"role_name": "read"}}
    return fake


def decide(github: FakeGitHub, actor: int):
    github.issue_events[4] = [
        {"id": 90, "event": "labeled", "label": {"name": LABEL}, "actor": {"id": actor}, "created_at": "t"}
    ]
    forge = GitHubForge(REPO, TOKEN, api_url=API, transport=github.transport(), sleep=lambda s: None)
    return resume_signal(
        [LABEL], forge.label_events(4), label=LABEL, own_id=forge.own_user_id(), access=forge.member_access,
        consumed=frozenset(),
    )  # fmt: skip


def test_a_write_users_label_passes(github):
    assert decide(github, WRITER) == ResumeSignal(event_id=90, signal="label:90", user_id=WRITER, access_level=30)


def test_a_read_users_label_is_refused(github):
    got = decide(github, READER)
    assert isinstance(got, Refusal) and "below Developer access (level 10)" in got.why


def test_the_tokens_own_label_is_refused(github):
    github.users[USER_ID] = "l4-bot"
    github.permissions["l4-bot"] = {"role_name": "write"}
    got = decide(github, USER_ID)
    assert isinstance(got, Refusal) and "own user" in got.why
