"""github-parity 1.4 (L4-GHP-004): the GitHub forge continues a run with workflow_dispatch, once."""

import httpx
import pytest

from l4.ci.github import WORKFLOW_RELPATH
from l4.forge.base import ForgeAuthError
from l4.forge.github import WORKFLOW_FILE, GitHubForge

from ._github_helpers import API, REPO, TOKEN, FakeGitHub


@pytest.fixture
def github() -> FakeGitHub:
    return FakeGitHub()


@pytest.fixture
def forge(github) -> GitHubForge:
    return GitHubForge(REPO, TOKEN, api_url=API, transport=github.transport(), sleep=lambda s: None)


def test_the_workflow_file_is_the_one_the_template_writes():
    assert WORKFLOW_FILE == WORKFLOW_RELPATH.rsplit("/", 1)[-1] == "l4.yml"


def test_no_queued_run_dispatches_the_ref(github, forge):
    assert forge.dispatch_continuation("main") == "dispatched"
    runs = {"branch": "main", "per_page": "20"}  # C-m6: the listing is not filtered to `queued` (was status=queued)
    assert github.requests == [
        ("GET", f"/repos/{REPO}/actions/workflows/l4.yml/runs", runs, None),
        ("POST", f"/repos/{REPO}/actions/workflows/l4.yml/dispatches", {}, {"ref": "main"}),
    ]


def test_a_queued_run_sends_nothing(github, forge):
    github.queued_runs = 1
    assert forge.dispatch_continuation("main") == "already_queued"
    assert github.writes() == []


def test_a_refused_dispatch_raises_the_forges_error(github):
    original = github.handle

    def refuse(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(403, json={"message": "Resource not accessible by integration"})
        return original(request)

    forge = GitHubForge(REPO, TOKEN, api_url=API, transport=httpx.MockTransport(refuse), sleep=lambda s: None)
    with pytest.raises(ForgeAuthError):
        forge.dispatch_continuation("main")


def test_the_dispatching_runs_own_progress_does_not_block(github, forge):
    """SCN-IMP-365: the run that dispatches is itself `in_progress` on the base and must not count; only a run that
    waits does. The count leaves `in_progress` out (C-m6: the listing is no longer filtered to `queued`)."""
    assert forge.dispatch_continuation("main") == "dispatched"  # no waiting run: sent, though this run is in progress
    [listing, _post] = github.requests
    assert "status" not in listing[2]
    github.queued_runs = 1
    assert forge.dispatch_continuation("main") == "already_queued"


@pytest.mark.parametrize("status", ["queued", "pending", "waiting", "requested"])
def test_a_run_that_waits_in_any_state_blocks_a_second_dispatch(status):
    """C-m6: GitHub's waiting states are queued, pending, waiting and requested; `in_progress` is the run itself."""
    from ._runs_helpers import RunsGitHub

    github = RunsGitHub()
    forge = GitHubForge(REPO, TOKEN, api_url=API, transport=github.transport(), sleep=lambda s: None)
    github.l4_runs = [{"id": 5, "status": status, "conclusion": None, "head_branch": "main"}]
    assert forge.dispatch_continuation("main") == "already_queued"
    assert forge.start_run("main") == "already_queued"
    assert github.writes() == []
    github.l4_runs = [{"id": 5, "status": "in_progress", "conclusion": None, "head_branch": "main"}]
    assert forge.dispatch_continuation("main") == "dispatched"


# --- ci-start D1 (L4-OPS-024): `base_activity` reads the same listing as `base_runs` ------------------------


def _row(run_id: int, status: str, *, updated_at: str | None = None, branch: str = "main") -> dict:
    row = {"id": run_id, "status": status, "conclusion": None, "head_branch": branch}
    return {**row, "updated_at": updated_at} if updated_at else row


def test_base_activity_counts_active_runs_of_any_branch_and_reads_when_the_newest_completed_one_ended():
    """The job holds one concurrency group for the repository: a run on another branch makes a dispatched run wait."""
    from datetime import UTC, datetime

    from ._runs_helpers import RunsGitHub

    github = RunsGitHub()
    forge = GitHubForge(REPO, TOKEN, api_url=API, transport=github.transport(), sleep=lambda s: None)
    github.l4_runs = [
        _row(1, "queued"),
        _row(2, "in_progress"),
        _row(3, "completed", updated_at="2026-10-30T10:05:00Z"),
        _row(4, "completed", updated_at="2026-10-30T10:20:30Z"),
        _row(5, "completed", updated_at="2026-10-30T09:00:00Z"),
        _row(6, "completed", updated_at="2026-10-30T11:00:00Z", branch="other"),
        _row(7, "in_progress", branch="l4/openspec/a"),
    ]
    assert forge.base_activity("main") == (3, datetime(2026, 10, 30, 11, 0, 0, tzinfo=UTC))
    assert github.writes() == []
    [listing] = github.requests
    assert "branch" not in listing[2] and listing[2]["per_page"] == "100"


@pytest.mark.parametrize("branch", ["develop", "l4/openspec/a"])
def test_a_run_going_on_another_branch_blocks_the_base(branch):
    """A scheduled run on a default branch that is not the base, or a push run on a unit branch."""
    from ._runs_helpers import RunsGitHub

    github = RunsGitHub()
    forge = GitHubForge(REPO, TOKEN, api_url=API, transport=github.transport(), sleep=lambda s: None)
    github.l4_runs = [_row(1, "in_progress", branch=branch)]
    assert forge.base_activity("main") == (1, None)
    assert forge.base_runs("main") == 0  # the base-only count the continuation wants is unchanged


def test_a_run_held_for_approval_is_active_not_ended():
    """`ci_run_state` calls a completed run with the conclusion `action_required` still running; so does this."""
    from datetime import UTC, datetime

    from ._runs_helpers import RunsGitHub

    github = RunsGitHub()
    forge = GitHubForge(REPO, TOKEN, api_url=API, transport=github.transport(), sleep=lambda s: None)
    held = {**_row(1, "completed", updated_at="2026-10-30T11:50:00Z"), "conclusion": "action_required"}
    github.l4_runs = [held, _row(2, "completed", updated_at="2026-10-30T10:00:00Z")]
    assert forge.base_activity("main") == (1, datetime(2026, 10, 30, 10, 0, 0, tzinfo=UTC))


def test_base_activity_is_none_for_a_200_that_is_not_json():
    """An HTML page from a proxy is not a listing: the forge cannot tell, it does not raise."""
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text="<html>sign in</html>"))
    forge = GitHubForge(REPO, TOKEN, api_url=API, transport=transport, sleep=lambda s: None)
    assert forge.base_activity("main") is None


def test_base_activity_of_an_empty_listing_is_idle_and_never_ended():
    from ._runs_helpers import RunsGitHub

    github = RunsGitHub()
    forge = GitHubForge(REPO, TOKEN, api_url=API, transport=github.transport(), sleep=lambda s: None)
    assert forge.base_activity("main") == (0, None)


@pytest.mark.parametrize("stamp", [None, "yesterday"])
def test_base_activity_cannot_tell_when_a_completed_run_has_no_readable_end(stamp):
    """A run that ended at a time nobody can read would let `--if-idle` start too soon: it cannot tell."""
    from ._runs_helpers import RunsGitHub

    github = RunsGitHub()
    forge = GitHubForge(REPO, TOKEN, api_url=API, transport=github.transport(), sleep=lambda s: None)
    github.l4_runs = [_row(3, "completed", updated_at=stamp)]
    assert forge.base_activity("main") is None


def test_base_activity_is_none_when_the_listing_fails_and_is_a_quick_read():
    from ._runs_helpers import RunsGitHub

    github = RunsGitHub()
    forge = GitHubForge(REPO, TOKEN, api_url=API, transport=github.transport(), sleep=lambda s: None)
    github.listing_status = 502
    assert forge.base_activity("main") is None
    assert [r[0] for r in github.requests] == ["GET"]  # one try
    assert 0 < github.timeouts[-1]["read"] <= 10
