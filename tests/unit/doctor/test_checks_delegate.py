"""DLG-001 and DLG-002 (delegate-answers 15.1; L4-DLG-012; SCN-DLG-33, SCN-DLG-34, SCN-DLG-34a) and the delegate in the
`--live` hello (LIVE-001)."""

import pytest

from l4.agents import factory as factory_module
from l4.agents.base import ProbeResult
from l4.agents.fake import FakeAdapter
from l4.config.schema import L4Config, Profile
from l4.doctor import checks_delegate as c
from l4.doctor.registry import REGISTRY, load_check_modules, run_checks

PROFILES = {
    "claude-opus": Profile(adapter="claude-code", model="claude-opus-5-5", vendor="anthropic"),
    "judge-opus": Profile(adapter="claude-code", model="claude-opus-5-5", vendor="anthropic"),
    "codex-sol": Profile(adapter="codex", model="gpt-6.1-sol", vendor="openai"),
    "delegate-opus": Profile(adapter="claude-code", model="claude-opus-5-5", vendor="anthropic"),
    "delegate-sol": Profile(adapter="codex", model="gpt-6.1-sol", vendor="openai"),
    "zen": Profile(adapter="opencode", model="deepseek-v4.1-flash", vendor="deepseek"),
    "api": Profile(backend="openai-chat", model="x"),
}


def config(*, enabled: bool = True, delegate: list[str] | None = None, implementer=("codex-sol",),
           judges=("judge-opus",), profiles=None, **settings) -> L4Config:  # fmt: skip
    return L4Config.model_validate(
        {
            "profiles": {**PROFILES, **(profiles or {})},
            "roles": {"implementer": list(implementer), "judges": list(judges), "delegate": delegate or []},
            "delegate": {"enabled": enabled, **settings},
        }
    )


def test_the_checks_are_registered_with_their_weights():
    load_check_modules()
    found = {x.id: x for x in REGISTRY.checks() if x.id.startswith("DLG-")}
    assert {i: x.severity for i, x in found.items()} == {"DLG-001": "error", "DLG-002": "warn"}


def test_off_passes_silently(make_ctx):
    """SCN-DLG-34a: nothing is configured and nothing is reported."""
    ctx, _ = make_ctx(cfg=L4Config())
    for check in (c._dlg_001, c._dlg_002):
        result = check(ctx)
        assert result.status == "pass" and result.fix_hint is None
    ctx, _ = make_ctx(cfg=config(enabled=False, delegate=["zen"]))  # a bad chain is nobody's business while it is off
    assert c._dlg_001(ctx).status == "pass" and c._dlg_002(ctx).status == "pass"


def test_an_empty_chain(make_ctx):
    ctx, _ = make_ctx(cfg=config(delegate=[]))
    result = c._dlg_001(ctx)
    assert result.status == "fail" and "roles.delegate is empty" in result.message and result.fix_hint
    assert c._dlg_002(ctx).status == "fail"


def test_an_opencode_profile_is_refused(make_ctx):
    ctx, _ = make_ctx(cfg=config(delegate=["zen", "api", "delegate-sol"]))
    result = c._dlg_001(ctx)
    assert result.status == "fail"
    assert "profile zen is a opencode profile; only claude-code and codex profiles serve the delegate" in result.message
    assert "profile api is a backend profile" in result.message


def test_an_unknown_profile(make_ctx):
    ctx, _ = make_ctx(cfg=config(delegate=["delegate-sol", "delegate-ghost"]))
    result = c._dlg_001(ctx)
    assert result.status == "fail" and "delegate-ghost, which is not defined under profiles" in result.message


def test_a_delegate_that_is_the_judges_model(make_ctx):
    """SCN-DLG-33."""
    ctx, _ = make_ctx(cfg=config(delegate=["delegate-opus"]))
    result = c._dlg_001(ctx)
    assert result.status == "fail"
    assert (
        "no delegate profile is independent of judge profile judge-opus (claude-opus-5-5): "
        "its verdict questions would escalate"
    ) in result.message


def test_an_implementer_nobody_can_be_independent_of(make_ctx):
    ctx, _ = make_ctx(cfg=config(delegate=["delegate-sol"], implementer=["codex-sol", "claude-opus"]))
    result = c._dlg_001(ctx)
    assert result.status == "fail" and "judge profile" not in result.message
    assert "implementer profile codex-sol (gpt-6.1-sol)" in result.message
    assert "implementer profile claude-opus" not in result.message  # delegate-sol is independent of it


def test_profile_mode_only_asks_for_another_name(make_ctx):
    ctx, _ = make_ctx(cfg=config(delegate=["delegate-opus"], independence="profile"))
    assert c._dlg_001(ctx).status == "pass"  # the owner's literal rule: another name is enough


def test_a_usable_chain_passes(make_ctx, monkeypatch):
    """SCN-DLG-34: the default implementer and judge chains of the reference, both CLIs logged in."""
    adapter = FakeAdapter([])
    monkeypatch.setitem(factory_module.ADAPTERS, "claude-code", lambda: adapter)
    monkeypatch.setitem(factory_module.ADAPTERS, "codex", lambda: adapter)
    ctx, _ = make_ctx(cfg=config(delegate=["delegate-opus", "delegate-sol"]))
    one, two = c._dlg_001(ctx), c._dlg_002(ctx)
    assert one.status == "pass" and "delegate-opus, delegate-sol" in one.message
    assert two.status == "pass" and "delegate-opus is usable" in two.message


class Probing(FakeAdapter):
    """Probe results by profile model; records the (model, step) pairs that ran."""

    def __init__(self, failing: dict[str, tuple[str, str]], log: list) -> None:
        super().__init__([])
        self.failing, self.log = failing, log

    def probe(self, profile, step, ctx):
        self.log.append((profile.model, step))
        bad = self.failing.get(profile.model or "")
        if bad and bad[0] == step:
            return ProbeResult(step, False, reason=bad[1])
        return ProbeResult(step, True, {"ms": 7} if step == "hello" else {})


@pytest.fixture
def probing(monkeypatch):
    def install(failing=None):
        log: list = []
        adapter = Probing(failing or {}, log)
        for name in ("claude-code", "codex"):
            monkeypatch.setitem(factory_module.ADAPTERS, name, lambda adapter=adapter: adapter)
        return log

    return install


def test_the_availability_check_spends_no_hello(make_ctx, probing):
    log = probing()
    ctx, _ = make_ctx(cfg=config(delegate=["delegate-opus"]))
    assert c._dlg_002(ctx).status == "pass"
    assert log == [("claude-opus-5-5", "binary"), ("claude-opus-5-5", "auth"), ("claude-opus-5-5", "quota")]


def test_no_usable_profile_warns_with_the_fix(make_ctx, probing):
    probing({"claude-opus-5-5": ("auth", "logged out"), "gpt-6.1-sol": ("binary", "codex is not installed")})
    ctx, _ = make_ctx(cfg=config(delegate=["delegate-opus", "delegate-sol"]))
    result = c._dlg_002(ctx)
    assert result.status == "fail" and "logged out" in result.message and "codex is not installed" in result.message
    assert result.fix_hint and "log in" in result.fix_hint
    [row] = [o for o in run_checks(ctx, registry=REGISTRY) if o.id == "DLG-002"]
    assert row.severity == "warn"  # never an error: the delegate escalates to a person


def test_the_second_profile_is_enough(make_ctx, probing):
    probing({"claude-opus-5-5": ("auth", "logged out")})
    ctx, _ = make_ctx(cfg=config(delegate=["delegate-opus", "delegate-sol"]))
    result = c._dlg_002(ctx)
    assert result.status == "pass" and "delegate-sol" in result.message


def test_live_hello_includes_the_delegate_chain(make_ctx, probing):
    """LIVE-001 with `--live` spends the hello of the delegate chain too, as a warning when only it fails."""
    log = probing()
    ctx, _ = make_ctx(cfg=config(delegate=["delegate-sol"]))
    [live] = [o for o in run_checks(ctx, live=True) if o.id == "LIVE-001"]
    assert live.status == "pass" and "delegate: delegate-sol ok" in live.message
    assert ("gpt-6.1-sol", "hello") in log
    only = {"delegate-only": Profile(adapter="codex", model="gpt-6.1-only", vendor="openai")}
    ctx, _ = make_ctx(cfg=config(delegate=["delegate-only"], profiles=only))
    probing({"gpt-6.1-only": ("hello", "no answer")})
    [failed] = [o for o in run_checks(ctx, live=True) if o.id == "LIVE-001"]
    assert failed.status == "fail" and failed.severity == "warn" and "no answer" in failed.message


def test_the_live_hello_ignores_the_delegate_while_it_is_off(make_ctx, probing):
    probing()
    ctx, _ = make_ctx(cfg=config(enabled=False, delegate=["delegate-sol"]))
    [live] = [o for o in run_checks(ctx, live=True) if o.id == "LIVE-001"]
    assert "delegate" not in live.message


# -- review fixes (F1, F2) -----------------------------------------------------------------------------------------


def test_a_delegate_timeout_that_never_fits_the_budget_is_an_error(make_ctx):  # review F1
    cfg = config(delegate=["delegate-sol"], implementer=["claude-opus"]).model_copy(
        update={"ci": L4Config().ci.model_copy(update={"time_budget": "30m", "soft_deadline_margin": "20m"})}
    )
    ctx, _ = make_ctx(cfg=cfg)  # 10 minutes left, delegate.timeout defaults to 15m
    result = c._dlg_001(ctx)
    assert result.status == "fail" and "delegate.timeout (15m)" in result.message and "soft deadline" in result.message
    ok = config(delegate=["delegate-sol"], implementer=["claude-opus"]).model_copy(
        update={"ci": L4Config().ci.model_copy(update={"time_budget": "60m", "soft_deadline_margin": "20m"})}
    )
    assert c._dlg_001(make_ctx(cfg=ok)[0]).status == "pass"
    assert (
        c._dlg_001(make_ctx(cfg=config(delegate=["delegate-sol"], implementer=["claude-opus"]))[0]).status == "pass"
    )  # auto: not known here


def test_a_delegate_profile_with_no_model_fails_under_model_independence(make_ctx):  # review F2
    profiles = {"dlg-nomodel": Profile(adapter="claude-code", vendor="anthropic")}
    ctx, _ = make_ctx(
        cfg=config(delegate=["delegate-sol", "dlg-nomodel"], implementer=["claude-opus"], profiles=profiles)
    )
    result = c._dlg_001(ctx)
    assert result.status == "fail" and "profile dlg-nomodel has no model" in result.message
    ctx, _ = make_ctx(
        cfg=config(
            delegate=["delegate-sol", "dlg-nomodel"],
            implementer=["claude-opus"],
            profiles=profiles,
            independence="profile",
        )
    )
    assert c._dlg_001(ctx).status == "pass"


def test_an_implementer_with_no_model_cannot_be_shown_independent(make_ctx):  # review F2
    profiles = {"impl-nomodel": Profile(adapter="claude-code", vendor="anthropic")}
    ctx, _ = make_ctx(cfg=config(delegate=["delegate-sol"], implementer=["impl-nomodel"], profiles=profiles))
    result = c._dlg_001(ctx)
    assert result.status == "fail" and "implementer profile impl-nomodel has no model" in result.message
