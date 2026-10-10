"""A required role that is unavailable with no reset in sight still parks with a `retry_after` (L4-AVL-007)."""

from datetime import UTC, datetime
from types import SimpleNamespace

from l4.availability.errors import RoleUnavailable
from l4.config.schema import AvailabilityCfg
from l4.exitcodes import ExitCode
from l4.orchestrator import Orchestrator


def test_a_plain_role_unavailable_is_parked_after_the_default_cooldown():
    seen: dict[str, object] = {}
    stub = SimpleNamespace(
        cfg=SimpleNamespace(
            availability=AvailabilityCfg(default_cooldown="30m"), forge=SimpleNamespace(base_branch="main")
        ),
        services=SimpleNamespace(
            ref=SimpleNamespace(id="u"),
            factory=SimpleNamespace(now=lambda: datetime(2026, 10, 4, 12, 0, tzinfo=UTC)),
            app=SimpleNamespace(redactor=SimpleNamespace(redact_text=lambda text: text)),
        ),
        _record_limit=lambda exc: None,
        _go=lambda trigger, **context: seen.update(context) or SimpleNamespace(exit_code=None),
    )
    assert Orchestrator._park(stub, RoleUnavailable("judges", "cannot answer")) is ExitCode.WAITING_CAPACITY  # type: ignore[arg-type]
    assert seen["retry_after"] == "2026-10-04T12:30:00Z"
