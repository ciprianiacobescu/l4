"""L4-YOLO-095, L4-YOLO-097, L4-YOLO-098: the configuration keys of the readiness judge chain."""

import pytest

from l4.config import roles
from l4.config.loader import ConfigSchemaError, load_config_text
from l4.config.schema import RolesCfg, YoloReviewCfg
from l4.yolo.readiness import Budgets


def load(text: str) -> str:
    with pytest.raises(ConfigSchemaError) as err:
        load_config_text(text)
    return str(err.value)


def test_plan_judges_defaults_to_empty_and_a_configuration_without_the_key_loads():
    assert RolesCfg().plan_judges == []
    cfg = load_config_text("profiles:\n  a: {adapter: claude-code}\nroles: {judges: [a]}\n")
    assert cfg.roles.plan_judges == []


def test_plan_judges_is_a_judge_role_right_after_judges():
    assert "plan_judges" in roles.JUDGE_ROLES
    assert roles.JUDGE_ROLES.index("plan_judges") == roles.JUDGE_ROLES.index("judges") + 1


def test_a_command_profile_in_plan_judges_fails_the_load_naming_the_role():  # SCN-YOLO-262
    message = load("profiles:\n  cmd: {adapter: command, options: {argv: [tool]}}\nroles: {plan_judges: [cmd]}\n")
    assert "profiles.cmd is in roles.plan_judges, but its adapter command cannot judge" in message
    assert "roles.judges, roles.plan_judges, roles.verifier_agent, roles.clarifier or roles.s1_judge" in message
    assert "remove cmd from roles.plan_judges" in message


def test_a_kiro_profile_loads_in_plan_judges():
    cfg = load_config_text("profiles:\n  k: {adapter: kiro-cli}\nroles: {plan_judges: [k]}\n")
    assert cfg.roles.plan_judges == ["k"]


def test_the_review_timeout_defaults_to_15m_and_has_a_floor():  # SCN-YOLO-270
    assert YoloReviewCfg().timeout == "15m"
    assert "yolo.review.timeout must be at least 1m" in load("yolo: {review: {timeout: 30s}}\n")
    assert load_config_text("yolo: {review: {timeout: 30m}}\n").yolo.review.timeout == "30m"
    assert load_config_text("yolo: {review: {timeout: 1m}}\n").yolo.review.timeout == "1m"


def test_max_batch_chars_defaults_and_bounds():
    assert YoloReviewCfg().max_batch_chars == 160_000
    assert load_config_text("yolo: {review: {max_batch_chars: 0}}\n").yolo.review.max_batch_chars == 0
    load("yolo: {review: {max_batch_chars: -1}}\n")


def test_budgets_carry_the_batch_bound():
    cfg = load_config_text("yolo: {review: {max_batch_chars: 1234}}\n")
    assert Budgets.of(cfg).batch == 1234
