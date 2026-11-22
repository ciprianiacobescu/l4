"""CFG-013 (L4-YOLO-103, SCN-YOLO-293, SCN-YOLO-294): a judge chain of one has no fallback judge."""

from l4.config.schema import L4Config
from l4.doctor import checks_config as cc
from l4.doctor.registry import CONFIG_SCOPES, REGISTRY, exit_code, run_checks

PROFILES = {name: {"adapter": "fake", "vendor": f"v-{name}"} for name in ("impl", "j1", "j2", "j3")}
ONE = "roles.judges has one profile (j1): unit verification has no fallback judge when it fails"
ONE_REVIEW = (
    ", and a judge for plan readiness reviews only belongs in roles.plan_judges, which unit verification never "
    "reads: do not cut roles.judges for a review"
)
PLAN_ONE = (
    "roles.plan_judges has one profile (j3): the plan review has no fallback judge (it does not fall back to "
    "roles.judges)"
)


def cfg(judges, plan_judges=()) -> L4Config:
    roles = {"implementer": ["impl"], "judges": list(judges), "plan_judges": list(plan_judges)}
    return L4Config.model_validate({"profiles": PROFILES, "roles": roles})


def outcome(ctx):
    (found,) = run_checks(ctx, scopes=CONFIG_SCOPES, only={"CFG-013"})
    return found


def test_the_check_is_registered_as_a_warning_for_every_configuration_scope():
    check = next(c for c in REGISTRY.checks() if c.id == "CFG-013")
    assert check.severity == "warn" and check.scopes == CONFIG_SCOPES


def test_scn_yolo_293_one_judge_warns_and_says_where_a_review_only_judge_goes(make_ctx):
    ctx, _ = make_ctx(cfg=cfg(["j1"]))
    result = cc._cfg_013(ctx)
    assert result.status == "fail" and result.message == ONE + ONE_REVIEW
    assert "second judge profile" in result.fix_hint and "roles.plan_judges" in result.fix_hint
    found = outcome(ctx)
    assert found.status == "fail" and found.severity == "warn"
    assert exit_code([found]) == 0  # a warning never changes doctor's exit code


def test_scn_yolo_294_a_review_chain_changes_what_it_says(make_ctx):
    ctx, _ = make_ctx(cfg=cfg(["j1"], ["j2", "j3"]))
    assert cc._cfg_013(ctx).message == ONE  # the plan reviews have their own chain: no second sentence
    ctx, _ = make_ctx(cfg=cfg(["j1", "j2"]))
    result = cc._cfg_013(ctx)
    assert result.status == "pass" and result.message == "roles.judges has 2 profiles"
    ctx, _ = make_ctx(cfg=cfg(["j1", "j2"], ["j3"]))
    result = cc._cfg_013(ctx)
    assert result.status == "fail" and result.message == PLAN_ONE


def test_both_chains_of_one_join_the_texts_with_a_semicolon(make_ctx):
    ctx, _ = make_ctx(cfg=cfg(["j1"], ["j3"]))
    assert cc._cfg_013(ctx).message == f"{ONE}; {PLAN_ONE}"


def test_a_profile_named_twice_counts_once(make_ctx):
    ctx, _ = make_ctx(cfg=cfg(["j1", "j1"]))
    assert cc._cfg_013(ctx).message == ONE + ONE_REVIEW


def test_two_chains_of_two_pass_naming_both(make_ctx):
    ctx, _ = make_ctx(cfg=cfg(["j1", "j2"], ["j2", "j3"]))
    result = cc._cfg_013(ctx)
    assert result.status == "pass" and result.message == "roles.judges has 2 profiles; roles.plan_judges has 2"


def test_no_judge_is_skipped_because_cfg_002_says_so(make_ctx):
    ctx, _ = make_ctx(cfg=cfg([]))
    result = cc._cfg_013(ctx)
    assert result.status == "skip" and "CFG-002" in result.message
