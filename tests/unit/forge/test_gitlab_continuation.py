"""L4-IMP-070: on GitLab the continuation is a pipeline on the base (`POST /pipeline`), and none is started while a
pipeline of the base waits (SCN-IMP-366)."""

import pytest

from ._gitlab_by_ref import RefAwareGitLab
from .conftest import PROJECT


@pytest.fixture
def gitlab() -> RefAwareGitLab:
    return RefAwareGitLab()


def test_no_waiting_pipeline_starts_one(gitlab, make_forge_client):
    assert make_forge_client().dispatch_continuation("main") == "dispatched"
    assert gitlab.writes() == [("POST", f"/projects/{PROJECT}/pipeline")]
    assert gitlab.requests[-1][3] == {"ref": "main"}
    listing = gitlab.requests[0]
    assert listing[:2] == ("GET", f"/projects/{PROJECT}/pipelines") and listing[2]["ref"] == "main"


@pytest.mark.parametrize("status", ["created", "waiting_for_resource", "preparing", "pending", "scheduled"])
def test_a_waiting_pipeline_starts_nothing(gitlab, make_forge_client, status):
    gitlab.add_ref_pipeline("main", status)
    assert make_forge_client().dispatch_continuation("main") == "already_queued"
    assert gitlab.writes() == []


def test_a_pipeline_of_another_ref_does_not_count(gitlab, make_forge_client):
    gitlab.add_ref_pipeline("feature", "pending")
    assert make_forge_client().dispatch_continuation("main") == "dispatched"


def test_a_running_pipeline_and_the_own_pipeline_do_not_count(gitlab, make_forge_client):
    """The dispatching job's pipeline is `running` (or, before it starts its job, `pending`): it must not block."""
    gitlab.add_ref_pipeline("main", "running")
    own = gitlab.add_ref_pipeline("main", "pending")
    assert make_forge_client(own_pipeline_id=str(own)).dispatch_continuation("main") == "dispatched"
    assert gitlab.writes() == [("POST", f"/projects/{PROJECT}/pipeline")]


@pytest.mark.parametrize("status", [403, 404])
def test_a_refused_start_is_unsupported_with_a_warning(gitlab, make_forge_client, status, monkeypatch):
    from l4.forge import gitlab as module

    said: list[str] = []
    monkeypatch.setattr(module.log, "warning", lambda text, *args: said.append(text % args))
    gitlab.pipeline_post_status = status
    assert make_forge_client().dispatch_continuation("main") == "unsupported"
    assert said and "continuation" in said[0] and "create pipelines" in said[0]


def test_a_failed_listing_is_an_error_not_a_dispatch(gitlab, make_forge_client):
    from l4.forge.base import ForgeError

    gitlab.fail_next = [__import__("httpx").Response(500, json={"message": "boom"})] * 6
    with pytest.raises(ForgeError):
        make_forge_client(sleeps=[]).dispatch_continuation("main")
    assert gitlab.writes() == []


# --- ci-start D1 (L4-OPS-024): `base_activity` reads the pipelines `base_runs` reads -----------------------


def test_base_activity_counts_unfinished_pipelines_of_the_ref_and_reads_the_newest_end(gitlab, make_forge_client):
    from datetime import UTC, datetime

    gitlab.add_ref_pipeline("main", "running")
    gitlab.add_ref_pipeline("main", "pending")
    gitlab.add_ref_pipeline("main", "success", finished_at="2026-10-30T10:05:00.000Z")
    gitlab.add_ref_pipeline("main", "failed", finished_at="2026-10-30T10:20:30.250Z")
    gitlab.add_ref_pipeline("main", "canceled", updated_at="2026-10-30T09:00:00.000Z")  # no finished_at: updated_at
    gitlab.add_ref_pipeline("feature", "running")
    gitlab.add_ref_pipeline("feature", "success", finished_at="2026-10-30T12:00:00.000Z")
    assert make_forge_client().base_activity("main") == (2, datetime(2026, 10, 30, 10, 20, 30, 250000, tzinfo=UTC))
    assert gitlab.writes() == []


def test_a_running_pipeline_alone_is_busy_and_no_pipeline_is_idle(gitlab, make_forge_client):
    assert make_forge_client().base_activity("main") == (0, None)
    gitlab.add_ref_pipeline("main", "running")
    assert make_forge_client().base_activity("main") == (1, None)


def test_base_activity_cannot_tell_from_a_failed_listing_or_an_unreadable_end(gitlab, make_forge_client):
    import httpx

    gitlab.fail_next = [httpx.Response(403, json={"message": "no"})]
    assert make_forge_client().base_activity("main") is None
    gitlab.add_ref_pipeline("main", "success")  # neither finished_at nor updated_at
    assert make_forge_client().base_activity("main") is None
