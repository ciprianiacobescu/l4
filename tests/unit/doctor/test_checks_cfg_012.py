"""CFG-012: the soft deadline leaves room for a step (budget-guard D4; L4-IMP-076, L4-IMP-077)."""

from l4.config.schema import L4Config
from l4.doctor import checks_config as cc
from l4.doctor.registry import CONFIG_SCOPES, REGISTRY, doctor_scopes, exit_code, run_checks

ERROR = (
    "ci.time_budget 21m minus soft_deadline_margin 20m leaves 1 min, less than one step (10 min): "
    "set ci.time_budget: auto (the job timeout) or raise it"
)
JOB_180 = {"L4_JOB_TIMEOUT_MINUTES": "180"}


def cfg(budget: str, margin: str = "20m") -> L4Config:
    return L4Config.model_validate({"ci": {"time_budget": budget, "soft_deadline_margin": margin}})


def outcome(ctx):
    (found,) = run_checks(ctx, scopes=CONFIG_SCOPES, only={"CFG-012"})
    return found


def test_a_budget_below_one_step_is_an_error(make_ctx):
    ctx, _ = make_ctx(cfg=cfg("21m"))
    result = cc._cfg_012(ctx)
    assert result.status == "fail" and result.message == ERROR
    assert (
        result.fix_hint
        == "set ci.time_budget: auto (the job timeout), or a duration at least soft_deadline_margin plus 10m"
    )
    found = outcome(ctx)
    assert found.status == "fail" and found.severity == "error"


def test_a_budget_at_the_floor_and_auto_pass(make_ctx):
    ctx, _ = make_ctx(cfg=cfg("30m"))
    result = cc._cfg_012(ctx)
    assert result.status == "pass" and "leaves 10 min after soft_deadline_margin 20m" in result.message
    ctx, _ = make_ctx(cfg=cfg("auto"))
    result = cc._cfg_012(ctx)
    assert result.status == "pass" and "the job's timeout is the budget" in result.message
    ctx, _ = make_ctx(cfg=cfg("15m"))
    result = cc._cfg_012(ctx)
    assert result.status == "fail" and "leaves no time" in result.message


def test_a_budget_that_shortens_the_job_warns(make_ctx):
    ctx, _ = make_ctx(cfg=cfg("60m"), **JOB_180)
    result = cc._cfg_012(ctx)
    assert result.status == "fail" and result.severity == "warn"
    assert "the soft deadline comes at minute 40, not at minute 160" in result.message
    found = outcome(ctx)
    assert found.severity == "warn"
    assert exit_code([found]) == 0


def test_the_job_timeout_comes_from_the_workflow_file(make_ctx):
    ctx, _ = make_ctx(cfg=cfg("60m"))
    assert cc._cfg_012(ctx).status == "pass"  # no variable, no file: nothing is said
    workflow = ctx.repo / ".github" / "workflows" / "l4.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("jobs:\n  l4:\n    timeout-minutes: 180\n")
    result = cc._cfg_012(ctx)
    assert result.status == "fail" and result.severity == "warn"
    assert ".github/workflows/l4.yml timeout-minutes" in result.message
    ctx, _ = make_ctx(cfg=cfg("60m"), CI_JOB_TIMEOUT="3600")
    assert cc._cfg_012(ctx).status == "pass"
    ctx, _ = make_ctx(cfg=cfg("170m"), **JOB_180)
    assert cc._cfg_012(ctx).status == "pass"


def test_both_texts_make_one_error(make_ctx):
    ctx, _ = make_ctx(cfg=cfg("21m"), **JOB_180)
    result = cc._cfg_012(ctx)
    assert result.status == "fail" and result.severity is None
    error, warning = result.message.split("; ", 1)
    assert error == ERROR
    assert warning.startswith("ci.time_budget 21m is shorter than the job's timeout")
    assert "comes at minute 1, not at minute 160" in warning
    assert outcome(ctx).severity == "error"


def test_cfg_012_runs_in_every_config_scope(make_ctx):
    check = {c.id: c for c in REGISTRY.checks()}["CFG-012"]
    assert check.severity == "error" and check.scopes >= CONFIG_SCOPES
    assert check.title == "The soft deadline leaves room for a step"
    ctx, _ = make_ctx(cfg=cfg("21m"))
    scopes = doctor_scopes(ci=False, adoption=True, no_gates=True)
    assert [o.id for o in run_checks(ctx, scopes=scopes, only={"CFG-012"})] == ["CFG-012"]
