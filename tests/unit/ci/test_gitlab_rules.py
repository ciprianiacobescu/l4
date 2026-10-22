"""Which project jobs run on a pipeline of a given source (gitlab-adoption 1.1, L4-INS-007)."""

import pytest

from l4.ci.gitlab_jobs import parse_gitlab_ci
from l4.ci.gitlab_rules import Pipeline, job_decision, jobs_on, workflow_decision

SCHEDULE = Pipeline("schedule", "master", "master")
PUSH = Pipeline("push", "feature", "master")


def rules(*items):
    return {"rules": list(items), "script": ["x"]}


def decide(job, pipeline=SCHEDULE):
    return job_decision(job, pipeline)[0]


@pytest.mark.parametrize(
    ("expr", "pipeline", "expected"),
    [
        ('$CI_PIPELINE_SOURCE == "schedule"', SCHEDULE, "run"),
        ('$CI_PIPELINE_SOURCE == "push"', SCHEDULE, "skip"),
        ("$CI_PIPELINE_SOURCE == 'schedule'", SCHEDULE, "run"),
        ('$CI_PIPELINE_SOURCE != "schedule"', SCHEDULE, "skip"),
        ('$CI_PIPELINE_SOURCE != "push"', SCHEDULE, "run"),
        ("$CI_PIPELINE_SOURCE =~ /^(schedule|api)$/", SCHEDULE, "run"),
        ("$CI_PIPELINE_SOURCE !~ /^(schedule|api)$/", SCHEDULE, "skip"),
        ("$CI_COMMIT_BRANCH =~ /^MASTER$/i", SCHEDULE, "run"),
        ("$CI_COMMIT_BRANCH =~ /^MASTER$/", SCHEDULE, "skip"),
        ("$CI_COMMIT_TAG", SCHEDULE, "skip"),
        ("$CI_COMMIT_BRANCH", SCHEDULE, "run"),
        ("$CI_COMMIT_TAG == null", SCHEDULE, "run"),
        ("$CI_COMMIT_BRANCH != null", SCHEDULE, "run"),
        ("$CI_MERGE_REQUEST_ID", SCHEDULE, "skip"),
        ("$CI_COMMIT_REF_NAME == $CI_DEFAULT_BRANCH", SCHEDULE, "run"),
        ('$CI_COMMIT_BRANCH == "master" && $CI_PIPELINE_SOURCE == "push"', SCHEDULE, "skip"),
        ('$CI_COMMIT_BRANCH == "master" || $CI_PIPELINE_SOURCE == "push"', SCHEDULE, "run"),
        # && binds tighter than ||: false && false || true is true
        ("$CI_COMMIT_TAG && $CI_COMMIT_TAG || $CI_COMMIT_BRANCH", SCHEDULE, "run"),
        ('$CI_COMMIT_BRANCH == "master" && ($CI_COMMIT_TAG || $CI_PIPELINE_SOURCE == "schedule")', SCHEDULE, "run"),
        ("$CI_COMMIT_TAG || ($CI_COMMIT_TAG && $CI_COMMIT_BRANCH)", SCHEDULE, "skip"),
        # unknown variables and three-valued logic
        ('$DEPLOY_ENV == "prod"', SCHEDULE, "unknown"),
        ("$DEPLOY_ENV", SCHEDULE, "unknown"),
        ('$DEPLOY_ENV == "prod" && $CI_COMMIT_TAG', SCHEDULE, "skip"),
        ('$DEPLOY_ENV == "prod" || $CI_COMMIT_BRANCH', SCHEDULE, "run"),
        ('$DEPLOY_ENV == "prod" && $CI_COMMIT_BRANCH', SCHEDULE, "unknown"),
        ('$DEPLOY_ENV == "prod" || $CI_COMMIT_TAG', SCHEDULE, "unknown"),
        # unreadable
        ("$CI_COMMIT_BRANCH ==", SCHEDULE, "unknown"),
        ('"a" == "a"', SCHEDULE, "run"),
        ('$CI_COMMIT_BRANCH == "master" )', SCHEDULE, "unknown"),
        ("$CI_COMMIT_BRANCH =~ /(/", SCHEDULE, "unknown"),
        ("$CI_COMMIT_BRANCH =~ /x/m", SCHEDULE, "unknown"),
        ("$CI_COMMIT_BRANCH @ 1", SCHEDULE, "unknown"),
        ('$CI_COMMIT_BRANCH == "feature"', PUSH, "run"),
    ],
)
def test_if_expressions(expr, pipeline, expected):
    assert decide(rules({"if": expr}), pipeline) == expected


def test_rules_in_order_first_true_item_decides():
    job = rules({"if": '$CI_PIPELINE_SOURCE == "schedule"', "when": "never"}, {"when": "always"})
    assert decide(job) == "skip"
    assert decide(job, PUSH) == "run"


@pytest.mark.parametrize("when", ["on_success", "manual", "delayed", "always"])
def test_any_other_when_is_run(when):
    assert decide(rules({"when": when})) == "run"


def test_no_rule_true_is_skip_and_an_empty_list_too():
    assert decide(rules({"if": "$CI_COMMIT_TAG"})) == "skip"
    assert decide({"rules": [], "script": ["x"]}) == "skip"


def test_changes_and_exists_are_unknown_when_they_would_decide():
    assert decide(rules({"changes": ["a/**"]})) == "unknown"
    assert decide(rules({"exists": ["Makefile"]})) == "unknown"
    assert decide(rules({"if": "$CI_COMMIT_BRANCH", "changes": ["a"]})) == "unknown"
    assert decide(rules({"if": "$CI_COMMIT_TAG", "changes": ["a"]}, {"when": "never"})) == "skip"


def test_an_unknown_if_before_a_true_one_makes_the_job_unknown():
    assert decide(rules({"if": "$X == 1"}, {"when": "always"})) == "unknown"
    assert decide(rules({"if": "$CI_COMMIT_BRANCH"}, {"if": "$X == 1", "when": "never"})) == "run"


def test_job_when_never_is_skip_and_manual_runs():
    assert decide({"when": "never", "script": ["x"]}) == "skip"
    assert decide({"when": "manual", "script": ["x"]}) == "run"
    assert decide({"when": "manual", "rules": [{"if": "$CI_COMMIT_BRANCH"}], "script": ["x"]}) == "run"
    assert decide({"when": "manual", "rules": [{"if": "$CI_COMMIT_BRANCH", "when": "never"}]}) == "skip"


def test_the_default_is_only_branches_and_tags():
    assert decide({"script": ["x"]}) == "run"
    assert decide({"script": ["x"]}, PUSH) == "run"


@pytest.mark.parametrize(
    ("keyword", "source", "expected"),
    [
        ("schedules", "schedule", "run"), ("schedules", "push", "skip"),
        ("api", "api", "run"), ("api", "schedule", "skip"),
        ("triggers", "trigger", "run"), ("triggers", "web", "skip"),
        ("web", "web", "run"), ("web", "push", "skip"),
        ("pushes", "push", "run"), ("pushes", "schedule", "skip"),
        ("branches", "schedule", "run"), ("tags", "schedule", "skip"),
        ("merge_requests", "push", "skip"), ("external", "push", "skip"),
        ("external_pull_requests", "push", "skip"), ("chat", "push", "skip"), ("pipelines", "push", "skip"),
    ],
)  # fmt: skip
def test_only_keywords(keyword, source, expected):
    assert decide({"only": [keyword], "script": ["x"]}, Pipeline(source, "master", "master")) == expected  # type: ignore[arg-type]
    assert decide({"only": keyword, "script": ["x"]}, Pipeline(source, "master", "master")) == expected  # type: ignore[arg-type]


def test_only_branch_name_and_regex_and_refs_mapping():
    assert decide({"only": ["master"], "script": ["x"]}) == "run"
    assert decide({"only": ["develop"], "script": ["x"]}) == "skip"
    assert decide({"only": ["/^mas/"], "script": ["x"]}) == "run"
    assert decide({"only": ["/^dev/"], "script": ["x"]}) == "skip"
    assert decide({"only": {"refs": ["schedules"]}, "script": ["x"]}) == "run"
    assert decide({"only": {"refs": ["schedules"], "variables": ["$A"]}, "script": ["x"]}) == "unknown"
    assert decide({"only": {"changes": ["a"]}, "script": ["x"]}) == "unknown"
    assert decide({"only": {"kubernetes": "active"}, "script": ["x"]}) == "unknown"


def test_except_removes_a_job_that_only_matches():
    assert decide({"except": ["schedules", "api", "triggers"], "script": ["x"]}) == "skip"
    assert decide({"except": ["schedules"], "script": ["x"]}, PUSH) == "run"
    assert decide({"only": ["branches"], "except": ["master"], "script": ["x"]}) == "skip"
    assert decide({"only": ["schedules"], "except": {"refs": ["develop"]}, "script": ["x"]}) == "run"
    assert decide({"except": {"variables": ["$A"]}, "script": ["x"]}) == "unknown"
    assert decide({"only": ["tags"], "except": {"variables": ["$A"]}, "script": ["x"]}) == "skip"


def test_workflow_rules():
    wf = {"rules": [{"if": '$CI_PIPELINE_SOURCE == "schedule"', "when": "never"}, {"when": "always"}]}
    assert workflow_decision(wf, SCHEDULE)[0] == "skip"
    assert workflow_decision(wf, PUSH)[0] == "run"
    assert workflow_decision(None, SCHEDULE)[0] == "run"
    assert workflow_decision({"name": "x"}, SCHEDULE)[0] == "run"
    assert workflow_decision({"rules": [{"if": "$X"}]}, SCHEDULE)[0] == "unknown"
    assert workflow_decision({"rules": [{"if": "$CI_COMMIT_TAG"}]}, SCHEDULE)[0] == "skip"
    assert workflow_decision("nonsense", SCHEDULE)[0] == "unknown"


def test_why_is_a_text():
    assert job_decision(rules({"if": "$CI_COMMIT_TAG"}), SCHEDULE)[1]


def read(text: str):
    return parse_gitlab_ci(text, lambda path: None)


SCENARIO = """
stages: [build, test]
unit_tests:
  stage: test
  except: [schedules, api, triggers]
  script: [x]
deploy_review:
  except: [schedules, api, triggers]
  script: [x]
lint:
  rules:
    - if: '$CI_PIPELINE_SOURCE == "push"'
  script: [x]
report:
  only: [schedules]
  script: [x]
"""


def test_jobs_on_sorts_run_skip_and_unknown():
    jobs = jobs_on(read(SCENARIO), SCHEDULE)
    assert jobs.workflow == "run"
    assert jobs.run == ("report",) and jobs.skip == ("deploy_review", "lint", "unit_tests") and jobs.unknown == ()
    assert jobs.normal_run == ("report",) and jobs.normal_unknown == ()


def test_jobs_on_unknown_jobs_and_normal_stage_filter():
    text = (
        "a:\n  rules: [{if: '$DEPLOY_ENV == \"p\"'}]\n  script: [x]\n"
        "b:\n  only: {variables: ['$A']}\n  stage: .post\n  script: [x]\n"
        "c:\n  stage: .pre\n  script: [x]\n"
        "d:\n  stage: build\n  script: [x]\n"
    )
    jobs = jobs_on(read(text), SCHEDULE)
    assert jobs.unknown == ("a", "b") and jobs.run == ("c", "d")
    assert jobs.normal_unknown == ("a",) and jobs.normal_run == ("d",)  # a job without stage is in test


def test_hidden_trigger_and_the_l4_job_are_left_out():
    text = (
        ".h:\n  script: [x]\nl4:\n  stage: .post\n  script: [x]\n"
        "down:\n  trigger: {project: g/p}\nreal:\n  script: [x]\n"
    )
    jobs = jobs_on(read(text), SCHEDULE)
    assert jobs.run == ("real",) and jobs.skip == jobs.unknown == ()


def test_extends_supplies_rules_and_stage():
    text = (
        ".base:\n  stage: build\n  rules: [{if: '$CI_PIPELINE_SOURCE == \"push\"'}]\n"
        "child:\n  extends: .base\n  script: [x]\n"
        "child2:\n  extends: .base\n  rules: [{when: always}]\n  script: [x]\n"
    )
    jobs = jobs_on(read(text), SCHEDULE)
    assert jobs.skip == ("child",) and jobs.run == ("child2",) and jobs.normal_run == ("child2",)


def test_workflow_comes_from_the_file():
    text = (
        "workflow:\n  rules:\n    - if: '$CI_PIPELINE_SOURCE == \"schedule\"'\n      when: never\n"
        "    - when: always\nj:\n  script: [x]\n"
    )
    assert jobs_on(read(text), SCHEDULE).workflow == "skip"
    assert jobs_on(read(text), PUSH).workflow == "run"


def test_deploys_reads_environment_and_stage():
    from l4.ci.gitlab_rules import deploys

    assert deploys({"environment": "production"})
    assert deploys({"environment": {"name": "staging"}})
    assert deploys({"environment": {"name": "staging", "action": "start"}})
    assert not deploys({"environment": {"name": "staging", "action": "stop"}})
    assert not deploys({"environment": {"name": "l4", "action": "prepare"}})
    assert deploys({"stage": "deploy"}) and deploys({"stage": "release"}) and deploys({"stage": "prod"})
    assert not deploys({"stage": "test"}) and not deploys({"stage": "products"})
