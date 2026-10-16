"""SCN-YOLO-72: `l4 yolo status` shows when a plan's current unit last moved (L4-YOLO-030, design D8)."""

from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from l4.state.status import Activity, OpenRun
from l4.yolo import commands as cmd
from l4.yolo.model import PlanEvent, PlanState
from l4.yolo.store import PlanRead

NOW = datetime(2026, 10, 16, 12, 0, 0, tzinfo=UTC)
LINK = "https://github.com/owner/repo/actions/runs/123"
UNIT = "openspec:add-x"
RUN = "r-20261016T1139Z-1a2b"


def _at(minutes: int) -> str:
    return datetime.fromtimestamp(NOW.timestamp() - minutes * 60, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture(autouse=True)
def _clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cmd, "_now", lambda: NOW)


def _describe(
    monkeypatch: pytest.MonkeyPatch, status: str, events: list[PlanEvent], units: cmd._Units
) -> dict[str, Any]:
    state = PlanState(plan_id="p1", status=status, current=UNIT)  # type: ignore[arg-type]
    monkeypatch.setattr(cmd, "fold_plan", lambda pid, evs: state)
    ctx: Any = SimpleNamespace(target="main")
    return cmd._describe(ctx, None, None, PlanRead(head="x", events=events), "p1", units)


def _units(activity: Activity | None, run: OpenRun | None) -> cmd._Units:
    return cmd._Units(activity={UNIT: (activity, run)})


ACTIVITY = Activity(ts=_at(6), type="task.red_ok", task="2.1", run_id=RUN)
RUNNING = OpenRun(run_id=RUN, started=_at(21), ci_url=LINK)
OLD_EVENT = PlanEvent(type="plan.activated", at=_at(40))


def test_active_plan_shows_unit_activity_and_open_run(monkeypatch: pytest.MonkeyPatch) -> None:
    d = _describe(monkeypatch, "active", [OLD_EVENT], _units(ACTIVITY, RUNNING))
    text = cmd._render(d)
    assert f"  last activity: 6m ago (task.red_ok, task 2.1, unit {UNIT})" in text.splitlines()
    assert f"  open run: {RUN} started 21m ago, no end recorded: {LINK}" in text.splitlines()
    assert d["last_activity"] == {"ts": _at(6), "type": "task.red_ok", "task": "2.1", "run_id": RUN, "unit": UNIT}
    assert d["open_run"] == {"run_id": RUN, "started": _at(21), "ci_url": LINK, "unit": UNIT}


def test_completed_plan_has_neither_line_and_null_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    d = _describe(monkeypatch, "completed", [OLD_EVENT], _units(ACTIVITY, RUNNING))
    text = cmd._render(d)
    assert "last activity" not in text and "open run" not in text
    assert d["last_activity"] is None and d["open_run"] is None


def test_newer_plan_event_wins_and_shows_its_type(monkeypatch: pytest.MonkeyPatch) -> None:
    newer = PlanEvent(type="plan.unit_started", at=_at(2))
    d = _describe(monkeypatch, "waiting", [OLD_EVENT, newer], _units(ACTIVITY, None))
    text = cmd._render(d)
    assert "  last activity: 2m ago (plan.unit_started)" in text.splitlines()
    assert "open run" not in text
    assert d["last_activity"] == {"ts": _at(2), "type": "plan.unit_started"}
    assert d["open_run"] is None


def test_plan_event_only_and_no_link(monkeypatch: pytest.MonkeyPatch) -> None:
    d = _describe(monkeypatch, "stopped", [OLD_EVENT], _units(None, OpenRun(RUN, _at(21), None)))
    lines = cmd._render(d).splitlines()
    assert "  last activity: 40m ago (plan.activated)" in lines
    assert f"  open run: {RUN} started 21m ago, no end recorded" in lines
    assert "ci_url" not in d["open_run"]


def test_read_units_collects_activity_from_snapshots(monkeypatch: pytest.MonkeyPatch) -> None:
    snap = SimpleNamespace(
        ref=SimpleNamespace(id=UNIT), state=SimpleNamespace(phase="red", cost_usd=0.0),
        last_activity=ACTIVITY, open_run=RUNNING,
    )  # fmt: skip

    @contextmanager
    def workspace(ctx: Any, rev: str) -> Any:
        yield None, None

    monkeypatch.setattr(cmd, "_workspace", workspace)
    monkeypatch.setattr(cmd, "discover", lambda *a, **k: [(None, snap)])
    monkeypatch.setattr(cmd, "unit_infos", lambda *a, **k: {})
    monkeypatch.setattr(cmd, "providers_for", lambda *a, **k: None)
    ctx: Any = SimpleNamespace(cfg=None, app=SimpleNamespace(environ={}), target="main")
    units = cmd._read_units(ctx, "abc", [UNIT], intake=False)
    assert units.activity == {UNIT: (ACTIVITY, RUNNING)}
