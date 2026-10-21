"""M1.2 line 2: the shared types later parts build on (agent-factory 1.1, delta)."""

from datetime import UTC, datetime

from l4.agents.base import AgentCaps, LimitSignal, ProbeCtx
from l4.agents.factory import REQUIRED_ROLES, RoleUnavailable, Selected, WaitingCapacity
from l4.agents.fake import FakeAdapter
from l4.config.schema import Profile
from l4.exitcodes import ExitCode


def test_limit_signal_gains_window_fields_without_breaking_positional_use():
    old = LimitSignal("codex", None, "usage_limit", None, "text", "x")
    assert old.window_minutes is None and old.used_percent is None
    new = LimitSignal("codex", "m", "usage_limit", None, "s", "", 300, 100.0)
    assert (new.window_minutes, new.used_percent) == (300, 100.0)


def test_agent_caps_served_model_defaults_to_false():
    assert AgentCaps("native", True, True, True, True, True, True, True).served_model is False
    assert AgentCaps("native", True, True, True, True, True, True, True, served_model=True).served_model


def test_waiting_capacity_is_a_role_unavailable_with_exit_12_and_a_retry_time():
    when = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
    err = WaitingCapacity("implementer", "every profile is cooling", when)
    assert isinstance(err, RoleUnavailable) and err.retry_after == when
    assert err.code == ExitCode.WAITING_CAPACITY and "implementer" in str(err)


def test_required_roles_are_the_three_that_wait():
    assert set(REQUIRED_ROLES) == {"implementer", "verifier_agent", "judges"}


def test_selected_carries_vendor_and_provenance_with_safe_defaults():
    picked = Selected("p", Profile(adapter="fake"), FakeAdapter([]))
    assert picked.vendor is None and picked.provenance == "unknown" and picked.fallback_from is None


def test_probe_ctx_defaults_keep_existing_callers_working(tmp_path):
    ctx = ProbeCtx(environ={}, cwd=tmp_path, run=lambda *a: None)
    assert ctx.min_remaining_percent == 10 and ctx.min_remaining_usd == 0.50 and ctx.rpc is None
