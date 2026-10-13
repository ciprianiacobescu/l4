"""A required role that is unavailable with no reset in sight still parks with a `retry_after` (L4-AVL-007)."""

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from l4.agents.base import LimitSignal, RunResult
from l4.availability.errors import RoleUnavailable
from l4.config.schema import AvailabilityCfg, CiCfg, ForgeCfg
from l4.exitcodes import ExitCode
from l4.implementer.tdd import RoleLimit
from l4.orchestrator import Orchestrator


def _stub(tmp_path: Path, seen: dict[str, object], recorded: list | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        cfg=SimpleNamespace(
            availability=AvailabilityCfg(default_cooldown="30m"), forge=ForgeCfg(base_branch="main"), ci=CiCfg()
        ),
        services=SimpleNamespace(
            ref=SimpleNamespace(id="u"),
            factory=SimpleNamespace(now=lambda: datetime(2026, 10, 4, 12, 0, tzinfo=UTC)),
            app=SimpleNamespace(redactor=SimpleNamespace(redact_text=lambda text: text), environ={}, repo=tmp_path),
        ),
        _record_limit=lambda exc: None,
        _go=lambda trigger, **context: seen.update(context) or SimpleNamespace(exit_code=None),
    )


def test_a_plain_role_unavailable_is_parked_after_the_default_cooldown(tmp_path: Path):
    seen: dict[str, object] = {}
    stub = SimpleNamespace(
        cfg=SimpleNamespace(
            availability=AvailabilityCfg(default_cooldown="30m"), forge=ForgeCfg(base_branch="main"), ci=CiCfg()
        ),
        services=SimpleNamespace(
            ref=SimpleNamespace(id="u"),
            factory=SimpleNamespace(now=lambda: datetime(2026, 10, 4, 12, 0, tzinfo=UTC)),
            app=SimpleNamespace(  # the note words the login steps for the origin's forge (L4-GHP-009)
                redactor=SimpleNamespace(redact_text=lambda text: text), environ={}, repo=tmp_path
            ),
        ),
        _record_limit=lambda exc: None,
        _go=lambda trigger, **context: seen.update(context) or SimpleNamespace(exit_code=None),
    )
    assert Orchestrator._park(stub, RoleUnavailable("judges", "cannot answer")) is ExitCode.WAITING_CAPACITY  # type: ignore[arg-type]
    assert seen["retry_after"] == "2026-10-04T12:30:00Z"


def test_a_role_limit_with_no_reset_time_is_parked_with_the_default_cooldown_too(tmp_path: Path):
    """L4-OPS-009, SCN-OPS-02: a park without `retry_after` could not be left by the planner, whatever the cause."""
    seen: dict[str, object] = {}
    no_reset = RunResult(status="quota", raw_events_path=tmp_path / "e.jsonl", detail="You have hit your usage limit")
    assert Orchestrator._park(_stub(tmp_path, seen), RoleLimit(no_reset)) is ExitCode.WAITING_CAPACITY  # type: ignore[arg-type]
    assert seen["retry_after"] == "2026-10-04T12:30:00Z"


def test_a_reported_reset_time_still_wins_over_the_default(tmp_path: Path):
    seen: dict[str, object] = {}
    limit = LimitSignal("codex", None, "usage_limit", datetime(2026, 10, 4, 15, 0, tzinfo=UTC), "text", "limit")
    result = RunResult(status="quota", raw_events_path=tmp_path / "e.jsonl", limit=limit)
    Orchestrator._park(_stub(tmp_path, seen), RoleLimit(result))  # type: ignore[arg-type]
    assert seen["retry_after"] == "2026-10-04T15:00:00Z"
