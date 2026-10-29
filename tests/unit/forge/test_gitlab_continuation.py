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


# --- ci-start D1 (L4-OPS-024): `base_activity` reads the pipelines of the job's resource group ---------------


def test_base_activity_counts_unfinished_pipelines_of_the_base_default_and_unit_refs(gitlab, make_forge_client):
    """The job's `resource_group: l4` is the project's: a run on the default branch or a unit branch makes a started
    run wait; a pipeline of an unrelated branch does not."""
    from datetime import UTC, datetime

    gitlab.add_ref_pipeline("staging", "running")  # the base
    gitlab.add_ref_pipeline("main", "pending")  # the default branch (a schedule's)
    gitlab.add_ref_pipeline("l4/openspec/a", "created")  # a unit branch
    gitlab.add_ref_pipeline("feature", "running")  # unrelated
    gitlab.add_ref_pipeline("staging", "success", updated_at="2026-10-30T10:05:00.000Z")
    gitlab.add_ref_pipeline("main", "failed", updated_at="2026-10-30T10:20:30.250Z")
    gitlab.add_ref_pipeline("feature", "success", updated_at="2026-10-30T12:00:00.000Z")  # unrelated: no end
    assert make_forge_client().base_activity("staging") == (
        3,
        datetime(2026, 10, 30, 10, 20, 30, 250000, tzinfo=UTC),
    )
    assert gitlab.writes() == []


@pytest.mark.parametrize("status", ["running", "pending", "created", "preparing", "waiting_for_resource"])
def test_every_unfinished_status_is_active(gitlab, make_forge_client, status):
    gitlab.add_ref_pipeline("l4/openspec/a", status)
    assert make_forge_client().base_activity("main") == (1, None)


@pytest.mark.parametrize("status", ["scheduled", "canceling"])
def test_scheduled_and_canceling_pipelines_are_active(gitlab, make_forge_client, status):
    gitlab.add_ref_pipeline("main", status)
    assert make_forge_client().base_activity("main") == (1, None)


def test_the_unit_branch_prefix_is_the_callers(gitlab, make_forge_client):
    gitlab.add_ref_pipeline("bot/openspec/a", "running")
    gitlab.add_ref_pipeline("l4/openspec/b", "running")
    assert make_forge_client().base_activity("main", branch_prefix="bot/") == (1, None)


def test_a_project_that_names_no_default_branch_still_counts_the_base_and_unit_refs(gitlab, make_forge_client):
    gitlab.default_branch = None
    gitlab.add_ref_pipeline("main", "running")
    gitlab.add_ref_pipeline("trunk", "running")
    assert make_forge_client().base_activity("main") == (1, None)


def test_a_running_pipeline_alone_is_busy_and_no_pipeline_is_idle(gitlab, make_forge_client):
    assert make_forge_client().base_activity("main") == (0, None)
    gitlab.add_ref_pipeline("main", "running")
    assert make_forge_client().base_activity("main") == (1, None)


def test_the_end_of_a_pipeline_is_its_updated_at_and_finished_at_is_the_fallback(gitlab, make_forge_client):
    from datetime import UTC, datetime

    gitlab.add_ref_pipeline("main", "success", finished_at="2026-10-30T09:00:00.000Z")  # no updated_at: the fallback
    assert make_forge_client().base_activity("main") == (0, datetime(2026, 10, 30, 9, 0, tzinfo=UTC))
    gitlab.add_ref_pipeline(
        "main", "failed", updated_at="2026-10-30T10:00:00.000Z", finished_at="2026-10-30T08:00:00.000Z"
    )
    assert make_forge_client().base_activity("main") == (0, datetime(2026, 10, 30, 10, 0, tzinfo=UTC))


def test_base_activity_cannot_tell_from_a_failed_listing_or_an_unreadable_end(gitlab, make_forge_client):
    import httpx

    gitlab.fail_next = [httpx.Response(403, json={"message": "no"})]
    assert make_forge_client().base_activity("main") is None
    gitlab.add_ref_pipeline("main", "success")  # neither updated_at nor finished_at
    assert make_forge_client().base_activity("main") is None


@pytest.mark.parametrize("failing_read", [0, 1])
def test_base_activity_is_none_for_a_200_that_is_not_json(gitlab, make_forge_client, failing_read):
    """An HTML page from a proxy, on the project read or on the listing: the forge cannot tell, it does not raise."""
    import httpx

    project = httpx.Response(200, json={"id": 118, "default_branch": "main"})
    html = httpx.Response(200, text="<html>sign in</html>")
    gitlab.fail_next = [html] if failing_read == 0 else [project, html]
    assert make_forge_client().base_activity("main") is None
