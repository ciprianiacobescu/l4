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
    # a review timeout of 1m keeps these tests about the step floor: the review warning has its own tests below
    return L4Config.model_validate(
        {"ci": {"time_budget": budget, "soft_deadline_margin": margin}, "yolo": {"review": {"timeout": "1m"}}}
    )


def outcome(ctx):
    (found,) = run_checks(ctx, scopes=CONFIG_SCOPES, only={"CFG-012"})
    return found


def test_a_budget_below_one_step_is_an_error(make_ctx):
    ctx, _ = make_ctx(cfg=cfg("21m"))
    result = cc._cfg_012(ctx)
    # a room of 1 min is also below the review timeout (1m is not less than 1m): the warning is added (L4-YOLO-097)
    assert result.status == "fail" and result.message.startswith(ERROR + "; yolo.review.timeout (1m)")
    assert result.fix_hint.startswith(
        "set ci.time_budget: auto (the job timeout), or a duration at least soft_deadline_margin plus 10m"
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


def review_cfg(timeout: str, budget: str = "20m", margin: str = "10m") -> L4Config:
    return L4Config.model_validate(
        {"ci": {"time_budget": budget, "soft_deadline_margin": margin}, "yolo": {"review": {"timeout": timeout}}}
    )


def test_a_review_timeout_not_below_the_budget_minus_the_margin_warns(make_ctx):  # SCN-YOLO-272
    ctx, _ = make_ctx(cfg=review_cfg("15m"))
    result = cc._cfg_012(ctx)
    assert result.status == "fail" and result.severity == "warn"
    assert (
        "yolo.review.timeout (15m) is not less than ci.time_budget (20m) minus ci.soft_deadline_margin (10m): "
        "no readiness call can start in a CI job"
    ) in result.message
    assert "lower yolo.review.timeout" in (result.fix_hint or "")
    found = outcome(ctx)
    assert found.severity == "warn" and exit_code([found]) == 0


def test_a_shorter_review_timeout_and_an_auto_budget_pass(make_ctx):
    ctx, _ = make_ctx(cfg=review_cfg("5m"))
    assert cc._cfg_012(ctx).status == "pass"
    ctx, _ = make_ctx(cfg=review_cfg("15m", budget="auto"))
    assert cc._cfg_012(ctx).status == "pass"


def test_a_failing_cfg_012_keeps_failing_with_the_review_warning_added(make_ctx):
    ctx, _ = make_ctx(cfg=review_cfg("15m", budget="21m", margin="20m"))
    result = cc._cfg_012(ctx)
    assert result.status == "fail" and result.severity != "warn"
    assert ERROR in result.message and "yolo.review.timeout (15m) is not less than" in result.message


def test_an_auto_budget_is_the_job_timeout_and_a_review_timeout_that_does_not_fit_it_warns(make_ctx):
    ctx, _ = make_ctx(cfg=review_cfg("15m", budget="auto", margin="20m"), L4_JOB_TIMEOUT_MINUTES="30")
    result = cc._cfg_012(ctx)
    assert result.status == "fail" and result.severity == "warn"
    assert (
        "yolo.review.timeout (15m) is not less than the job's timeout (30 min, L4_JOB_TIMEOUT_MINUTES) minus "
        "ci.soft_deadline_margin (20m): no readiness call can start in a CI job"
    ) in result.message
    assert "lower yolo.review.timeout" in (result.fix_hint or "")
    assert exit_code([outcome(ctx)]) == 0


def test_the_auto_budget_review_warning_is_exact_at_the_edge_and_silent_without_a_job_timeout(make_ctx):
    ctx, _ = make_ctx(cfg=review_cfg("15m", budget="auto", margin="20m"), L4_JOB_TIMEOUT_MINUTES="35")
    assert cc._cfg_012(ctx).status == "fail"  # 35 - 20 = 15: the timeout is not less than the room
    ctx, _ = make_ctx(cfg=review_cfg("15m", budget="auto", margin="20m"), L4_JOB_TIMEOUT_MINUTES="36")
    assert cc._cfg_012(ctx).status == "pass"
    ctx, _ = make_ctx(cfg=review_cfg("15m", budget="auto", margin="20m"))
    assert cc._cfg_012(ctx).status == "pass"  # the job's timeout is unknown: nothing is said


def test_a_set_budget_is_still_the_budget_whatever_the_job_timeout(make_ctx):
    ctx, _ = make_ctx(cfg=review_cfg("5m", budget="60m", margin="20m"), L4_JOB_TIMEOUT_MINUTES="30")
    assert "yolo.review.timeout" not in cc._cfg_012(ctx).message
