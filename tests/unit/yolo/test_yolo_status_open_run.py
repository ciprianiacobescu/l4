"""run-continuation 7.2 (L4-IMP-073): `l4 yolo status` names an open run that ended without a record, and an active
plan that nothing will advance, and gives the command that starts a run on the base."""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from l4.config.schema import L4Config
from l4.forge.base import ForgeUnavailable
from l4.forge.urls import ForgeUrls
from l4.state.status import Activity, OpenRun
from l4.yolo import commands as cmd
from l4.yolo.model import PlanEvent, PlanState
from l4.yolo.store import PlanRead

NOW = datetime(2026, 10, 16, 12, 0, 0, tzinfo=UTC)
LINK = "https://github.com/owner/repo/actions/runs/123"
RERUN = "https://github.com/owner/repo/actions/runs/77/attempts/2"
UNIT = "openspec:add-x"
RUN = "r-20261016T1139Z-1a2b"
START = "gh workflow run l4.yml --ref staging"
TODAY = "nothing: CI advances the plan"
WHY_AGE = "older than its job timeout (180 min): likely the CI timeout"


def _at(minutes: int) -> str:
    return datetime.fromtimestamp(NOW.timestamp() - minutes * 60, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class FakeForge:
    def __init__(self, *, state: tuple[str, str] = ("unknown", ""), runs: int | None = 0, fail: bool = False) -> None:
        self.state, self.runs, self.fail = state, runs, fail
        self.state_calls: list[str] = []
        self.run_calls: list[str] = []

    def ci_run_state(self, ci_url: str) -> tuple[str, str]:
        assert not self.fail, "the forge must not be asked"
        self.state_calls.append(ci_url)
        return self.state  # type: ignore[return-value]

    def base_runs(self, ref: str, *, exclude_run_id: str | None = None) -> int | None:
        assert not self.fail, "the forge must not be asked"
        self.run_calls.append(ref)
        return self.runs


@pytest.fixture(autouse=True)
def _clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cmd, "_now", lambda: NOW)
    monkeypatch.setattr(cmd, "_default_copy_problem", lambda ctx: None)


@pytest.fixture
def forge(monkeypatch: pytest.MonkeyPatch) -> FakeForge:
    fake = FakeForge()
    monkeypatch.setattr(cmd, "make_forge", lambda cfg, environ, **kwargs: fake)
    return fake


def _ctx(tmp_path: Path, *, schedule: str | None = "*/30 * * * *", environ: dict[str, str] | None = None, **ci: Any):
    cfg = L4Config.model_validate({"forge": {"base_branch": "staging"}, "ci": {"schedule": schedule, **ci}})
    env = {"GITHUB_ACTIONS": "true", "PATH": "/usr/bin:/bin", **(environ or {})}
    app = SimpleNamespace(environ=env, repo=tmp_path)
    return SimpleNamespace(target="staging", app=app, cfg=cfg)


def _describe(
    monkeypatch: pytest.MonkeyPatch, ctx: Any, status: str, events: list[PlanEvent], run: OpenRun | None,
    activity: Activity | None = None,
) -> dict[str, Any]:  # fmt: skip
    state = PlanState(plan_id="p1", status=status, current=UNIT)  # type: ignore[arg-type]
    monkeypatch.setattr(cmd, "fold_plan", lambda pid, evs: state)
    units = cmd._Units(activity={UNIT: (activity, run)})
    return cmd._describe(ctx, None, None, PlanRead(head="x", events=events), "p1", units)


def _run(minutes: int, link: str | None = LINK, timeout: int | None = 10800) -> OpenRun:
    return OpenRun(run_id=RUN, started=_at(minutes), ci_url=link, job_timeout_s=timeout)


def _event(minutes: int) -> list[PlanEvent]:
    return [PlanEvent(type="plan.activated", at=_at(minutes))]


def test_an_open_run_older_than_its_timeout_ended_without_a_record(monkeypatch, tmp_path, forge):  # SCN-IMP-357
    forge.fail = True  # the age decides: the forge is not asked
    d = _describe(monkeypatch, _ctx(tmp_path), "active", _event(215), _run(210))
    lines = cmd._render(d).splitlines()
    assert (
        f"  open run: {RUN} started 3h 30m ago, no end recorded: it ended without a record ({WHY_AGE}): {LINK}" in lines
    )
    expected = (
        f"the run {RUN} of {UNIT} ended without a record ({WHY_AGE}); the unit continues from its last pushed step: "
        f"start a run on staging: {START}"
    )
    assert lines[-1] == f"Next: {expected}" and d["next"] == expected
    assert d["open_run"]["ended_without_record"] is True and d["open_run"]["why"] == WHY_AGE
    assert forge.run_calls == [] and forge.state_calls == []


def test_an_older_run_started_without_the_timeout_assumes_180_minutes(monkeypatch, tmp_path, forge):  # SCN-IMP-357
    d = _describe(monkeypatch, _ctx(tmp_path), "active", _event(215), _run(210, timeout=None))
    assert d["open_run"]["why"] == "older than its job timeout (180 min, assumed): likely the CI timeout"
    d = _describe(monkeypatch, _ctx(tmp_path, time_budget="2h"), "active", _event(215), _run(130, timeout=None))
    assert d["open_run"]["why"] == "older than its job timeout (120 min): likely the CI timeout"  # a set budget
    d = _describe(monkeypatch, _ctx(tmp_path), "active", _event(215), _run(183))
    assert d["open_run"]["ended_without_record"] is False  # the 5 minutes allow for clock skew


def test_the_ci_says_completed(monkeypatch, tmp_path, forge):  # SCN-IMP-358
    forge.state = ("completed", "cancelled")
    d = _describe(monkeypatch, _ctx(tmp_path), "active", _event(30), _run(20))
    assert d["open_run"]["ended_without_record"] is True
    assert d["open_run"]["why"] == "its CI run is completed (cancelled)"
    assert d["next"].startswith(f"the run {RUN} of {UNIT} ended without a record (its CI run is completed (cancelled))")
    assert d["next"].endswith(f"start a run on staging: {START}")
    assert forge.state_calls == [LINK]


def test_a_young_run_without_an_answer_is_unchanged(monkeypatch, tmp_path):  # SCN-IMP-359
    def no_token(cfg, environ, **kwargs):
        raise ForgeUnavailable("L4_FORGE_TOKEN is not set")

    monkeypatch.setattr(cmd, "make_forge", no_token)
    d = _describe(monkeypatch, _ctx(tmp_path), "active", _event(30), _run(20))
    assert d["open_run"]["ended_without_record"] is False and "why" not in d["open_run"]
    assert f"  open run: {RUN} started 20m ago, no end recorded: {LINK}" in cmd._render(d).splitlines()
    assert d["next"].startswith(TODAY)


def test_the_forge_is_asked_only_when_the_age_does_not_decide(monkeypatch, tmp_path, forge):  # SCN-IMP-372
    forge.fail = True
    _describe(monkeypatch, _ctx(tmp_path), "active", _event(250), _run(240))  # old: no call (the forge would fail)
    forge.fail = False
    _describe(monkeypatch, _ctx(tmp_path), "active", _event(30), _run(20, link=RERUN))
    assert forge.state_calls == [RERUN]  # the attempt of the URL is the one asked about
    forge.fail = True
    d = _describe(monkeypatch, _ctx(tmp_path), "active", _event(300), _run(240, link=None))
    assert d["open_run"]["ended_without_record"] is False  # no ci_url: no age rule, and nothing to ask about


@pytest.mark.parametrize("status", ["stopped", "waiting"])
def test_a_stopped_plan_keeps_its_next(monkeypatch, tmp_path, forge, status):  # SCN-IMP-373
    young = _describe(monkeypatch, _ctx(tmp_path), status, _event(215), _run(20))
    old = _describe(monkeypatch, _ctx(tmp_path), status, _event(215), _run(210))
    assert old["open_run"]["ended_without_record"] is True
    assert " ended without a record (" in cmd._render(old).split("Next:")[0]
    assert old["next"] == young["next"] and "ended without a record" not in old["next"]


test_a_waiting_plan_keeps_its_next = test_a_stopped_plan_keeps_its_next  # the one test, both plan states


def test_an_active_plan_idle_for_two_periods_names_the_command(monkeypatch, tmp_path, forge):  # SCN-IMP-374
    d = _describe(monkeypatch, _ctx(tmp_path), "active", _event(70), None)
    assert d["next"] == (
        f"nothing is running or queued on staging and the plan has been idle for 1h10m: start a run on staging: {START}"
    )
    assert forge.run_calls == ["staging"]
    forge.runs = 1
    assert _describe(monkeypatch, _ctx(tmp_path), "active", _event(70), None)["next"].startswith(TODAY)
    forge.runs = None  # the forge cannot say
    assert _describe(monkeypatch, _ctx(tmp_path), "active", _event(70), None)["next"].startswith(TODAY)


def test_between_two_ticks_the_schedule_is_trusted(monkeypatch, tmp_path, forge):  # SCN-IMP-380
    forge.fail = True  # not idle long enough: the forge is not asked either
    assert _describe(monkeypatch, _ctx(tmp_path), "active", _event(20), None)["next"].startswith(TODAY)
    assert _describe(monkeypatch, _ctx(tmp_path), "active", _event(20), _run(10))["next"].startswith(TODAY)


def test_no_schedule_names_the_command(monkeypatch, tmp_path, forge):  # SCN-IMP-380
    d = _describe(monkeypatch, _ctx(tmp_path, schedule=None), "active", _event(20), None)
    assert d["next"] == (
        "nothing is running or queued on staging, and no schedule starts runs there (ci.schedule is null): "
        f"start a run on staging: {START}"
    )
    monkeypatch.setattr(
        cmd, "_default_copy_problem", lambda ctx: "main's copy of .github/workflows/l4.yml pins aaaaaaa"
    )
    d = _describe(monkeypatch, _ctx(tmp_path), "active", _event(20), None)
    assert "no schedule starts runs there (main's copy of .github/workflows/l4.yml pins aaaaaaa)" in d["next"]
    forge.runs = 2
    assert _describe(monkeypatch, _ctx(tmp_path), "active", _event(20), None)["next"].startswith(TODAY)


def test_cron_period_s():
    assert cmd.cron_period_s("*/30 * * * *") == 1800
    assert cmd.cron_period_s("15 * * * *") == 3600
    assert cmd.cron_period_s("0 6 * * *") == 86400
    assert cmd.cron_period_s("0 6 * * 1") == 3600
    assert cmd.cron_period_s("1,31 * * * *") == 3600
    assert cmd.cron_period_s(None) is None


def test_gitlab_names_the_new_pipeline_page(monkeypatch, tmp_path, forge):
    env = {"GITLAB_CI": "true", "CI_PROJECT_URL": "https://gitlab.example.test/group/project"}
    ctx = _ctx(tmp_path, environ={"GITHUB_ACTIONS": "", **env})
    d = _describe(
        monkeypatch, ctx, "active", _event(215), OpenRun(RUN, _at(210), "<forge>/group/project/-/jobs/9", 10800)
    )
    assert d["next"].endswith(
        "start a run on staging: https://gitlab.example.test/group/project/-/pipelines/new?ref=staging"
    )


def test_a_pre_existing_context_without_an_app_asks_nothing(monkeypatch):
    """The older tests build a context with a target only: no forge, no start command, today's behaviour."""
    ctx: Any = SimpleNamespace(target="main")
    d = _describe(monkeypatch, ctx, "active", _event(30), _run(20))
    assert d["open_run"]["ended_without_record"] is False and d["next"].startswith(TODAY)


STORED = "<forge>/owner/repo/actions/runs/123"  # what the ledger holds (observability.redact_forge_urls)


def test_the_stored_forge_form_of_the_ci_url_is_expanded_before_the_forge_is_asked(monkeypatch, tmp_path, forge):
    """B-M1, SCN-IMP-358: the ledger writer scrubs the host, so status expands it once and the forge, the text and
    the JSON all carry the real address."""
    forge.state = ("completed", "cancelled")
    ctx = _ctx(tmp_path)
    ctx.app.redactor = SimpleNamespace(forge_urls=ForgeUrls(frozenset({"https://github.com"}), "https://github.com"))
    d = _describe(monkeypatch, ctx, "active", _event(30), _run(20, link=STORED))
    assert forge.state_calls == [LINK]
    assert d["open_run"]["ci_url"] == LINK
    assert d["open_run"]["why"] == "its CI run is completed (cancelled)"
    assert f"{RUN} started 20m ago, no end recorded: it ended without a record" in cmd._render(d)
    assert cmd._render(d).splitlines()[-2].endswith(LINK)


def test_a_ci_run_held_for_approval_is_not_ended(monkeypatch, tmp_path, forge):
    """B-m3, SCN-IMP-358: a run held for approval waits; status names the run's page as the step to take, and never
    says to start a run on the base."""
    forge.state = ("running", "waiting for approval")
    d = _describe(monkeypatch, _ctx(tmp_path), "active", _event(30), _run(20))
    assert d["open_run"]["ended_without_record"] is False and d["open_run"]["waiting_for_approval"] is True
    assert d["next"] == f"the CI run {LINK} of {UNIT} waits for approval: open it and approve the run"
    assert START not in d["next"]
    assert f"no end recorded: the CI run waits for approval: {LINK}" in cmd._render(d).splitlines()[-2]
    assert forge.run_calls == []  # the base is not asked: a person's click advances it
