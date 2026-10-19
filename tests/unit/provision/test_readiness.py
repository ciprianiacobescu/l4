from pathlib import Path

from l4.agents.base import ProbeCtx, ProbeResult
from l4.agents.factory import Factory
from l4.config.schema import L4Config, Profile
from l4.provision.readiness import AdapterState, adapter_readiness, sanitize_status


class Scripted:
    name = "scripted"

    def __init__(self, binary_ok: bool, auth: ProbeResult | None) -> None:
        self.binary_ok, self.auth, self.steps = binary_ok, auth, []

    def probe(self, profile, step, ctx):
        self.steps.append(step)
        if step == "binary":
            return ProbeResult(step, self.binary_ok, reason=None if self.binary_ok else "not found")
        assert self.auth is not None
        return self.auth


def check(adapter: Scripted, auth_mode="subscription"):
    profile = Profile(adapter="codex", auth=auth_mode)
    factory = Factory(L4Config(), ProbeCtx({}, Path("."), lambda *a: None), adapters={"codex": adapter})
    return adapter_readiness("codex-main", profile, factory, ProbeCtx({}, Path("."), lambda *a: None))


def test_three_states_and_email_never_printed():
    leak = {"logged_in": True, "auth_method": "chatgpt", "plan": "pro", "email": "me@example.com", "token": "sk-xyz"}
    ready = check(Scripted(True, ProbeResult("auth", True, leak)))
    assert ready.state is AdapterState.READY and ready.steps == ()
    assert ready.status == {"logged_in": True, "auth_method": "chatgpt", "plan": "pro"}
    assert "me@example.com" not in repr(ready) and "sk-xyz" not in repr(ready)
    out = check(Scripted(True, ProbeResult("auth", False, reason="codex is not logged in")))
    assert out.state is AdapterState.INSTALLED_NOT_AUTHENTICATED
    assert "codex login --device-auth" in out.steps[0]
    missing = check(Scripted(False, None))
    assert missing.state is AdapterState.MISSING and missing.steps == ()
    assert ready.line() == "codex-main codex ready"


def test_auth_is_read_through_the_adapters_own_probe():
    adapter = Scripted(True, ProbeResult("auth", True, {"logged_in": True}))
    check(adapter)
    assert adapter.steps == ["binary", "auth"]  # no login, no hello (they cost tokens or authenticate)


def test_an_adapter_this_build_does_not_know_is_missing():
    factory = Factory(L4Config(), ProbeCtx({}, Path("."), lambda *a: None))
    result = adapter_readiness("k", Profile(adapter="kiro-cli"), factory, ProbeCtx({}, Path("."), lambda *a: None))
    assert result.state is AdapterState.MISSING and result.adapter == "kiro-cli"


def test_sanitize_status_keeps_three_fields_and_word_values_only():
    raw = {"loggedIn": True, "authMethod": "claude.ai", "subscriptionType": "max", "email": "a@b.c"}
    assert sanitize_status(raw) == {"logged_in": True, "auth_method": "claude.ai", "plan": "max"}
    assert sanitize_status({"logged_in": "yes", "auth_method": "a@b.c", "plan": "x" * 80}) == {
        "logged_in": False, "auth_method": None, "plan": None,
    }  # fmt: skip
    assert sanitize_status({}) == {"logged_in": False, "auth_method": None, "plan": None}


def _timed_out(step: str) -> Scripted:
    from l4.availability.probes import StepTimedOut, timeout_reason

    class Slow(Scripted):
        def probe(self, profile, name, ctx):
            self.steps.append(name)
            if name == step:
                raise StepTimedOut(timeout_reason("codex", 20, name))
            return ProbeResult(name, True)

    return Slow(True, None)


def test_a_binary_step_that_times_out_is_missing_with_the_reason():
    out = check(_timed_out("binary"))
    assert out.state is AdapterState.MISSING
    assert out.detail == (
        "codex did not answer within 20 s (binary step); a login prompt or a helper process that keeps the output "
        "open can cause this: run l4 doctor"
    )


def test_an_auth_step_that_times_out_is_not_authenticated_with_the_reason():
    out = check(_timed_out("auth"))
    assert out.state is AdapterState.INSTALLED_NOT_AUTHENTICATED
    assert out.detail is not None and out.detail.startswith("codex did not answer within 20 s (auth step)")
