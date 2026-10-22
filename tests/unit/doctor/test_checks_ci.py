from l4.doctor import checks_ci as ci

from ..forge.test_pushurl import JOB_TOKEN, _runner_conf


def test_skipped_outside_gitlab_ci(make_ctx):
    ctx, _ = make_ctx()
    assert ci.CI_001.run(ctx).status == "skip"


def test_no_runner_rule_passes(make_ctx, tmp_path):
    ctx, _ = make_ctx(GITLAB_CI="true", CI_PROJECT_DIR=str(tmp_path / "nothing"))
    assert ci.CI_001.run(ctx).status == "pass"


def test_the_runner_rule_without_the_forge_token_fails_and_explains_the_403(make_ctx, tmp_path):
    ctx, _ = make_ctx(**_runner_conf(tmp_path))
    result = ci.CI_001.run(ctx)
    assert result.status == "fail" and "L4_FORGE_TOKEN" in result.message and "403" in result.message
    assert result.fix_hint and "write_repository" in result.fix_hint
    assert JOB_TOKEN not in result.message + result.fix_hint


def test_the_runner_rule_with_the_token_passes_when_the_push_url_is_known(make_ctx, tmp_path):
    env = {**_runner_conf(tmp_path), "L4_FORGE_TOKEN": "x"}
    ctx, _ = make_ctx(**env, CI_SERVER_URL="https://gl.example", CI_PROJECT_PATH="g/p")
    assert ci.CI_001.run(ctx).status == "pass"
    ctx, _ = make_ctx(**env)
    assert ci.CI_001.run(ctx).status == "fail"  # no way to build the oauth2 URL


# --- CI-002: the runner tags (M1.8 A11, forge-and-ci 2.19, SCN-CI-06) -------------------------------------------------

from pathlib import Path  # noqa: E402

from l4.ci.render import TEMPLATE_RELPATH, render_gitlab_ci  # noqa: E402
from l4.config.schema import L4Config  # noqa: E402

INCLUDE = f"include:\n  - local: {TEMPLATE_RELPATH}\n"
TEST_JOB = "test:\n  stage: test\n  script:\n    - pytest\n"


def put(repo: Path, relpath: str, text: str) -> None:
    path = repo / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def adopted(repo: Path, *, template: str | None = None, main: str = INCLUDE + TEST_JOB) -> None:
    put(repo, ".l4/ci/l4.gitlab-ci.yml", render_gitlab_ci() if template is None else template)
    put(repo, ".gitlab-ci.yml", main)


def test_ci002_shipped_template_passes(make_ctx):
    ctx, _ = make_ctx()
    adopted(ctx.repo, main=INCLUDE + TEST_JOB.replace("stage: test", "stage: test\n  tags: [agentic]"))
    result = ci.CI_002.run(ctx)
    assert result.status == "pass", result.message
    assert result.severity is None


def test_ci002_fails_for_an_untagged_l4_job(make_ctx):
    """SCN-CI-06: the harness job without the runner tags would stay pending (or run on any runner of the instance)."""
    ctx, _ = make_ctx()
    untagged = render_gitlab_ci().replace("  tags: [agentic]\n", "")
    adopted(ctx.repo, template=untagged)
    result = ci.CI_002.run(ctx)
    assert result.status == "fail" and result.severity == "error"
    assert "job l4" in result.message and "agentic" in result.message


def test_ci002_warns_for_an_untagged_repo_job_and_names_it(make_ctx):
    ctx, _ = make_ctx()
    adopted(ctx.repo)  # `test` has no tags: sample-consumer's shape (owner decision O8)
    result = ci.CI_002.run(ctx)
    assert result.status == "fail" and result.severity == "warn"
    assert "test" in result.message and "any runner of the instance" in result.message
    assert "job l4" not in result.message


def test_ci002_default_tags_satisfy_it(make_ctx):
    ctx, _ = make_ctx()
    adopted(ctx.repo, main="default:\n  tags: [agentic]\n" + INCLUDE + TEST_JOB)
    assert ci.CI_002.run(ctx).status == "pass"


def test_ci002_template_tags_differing_from_runner_tags_is_an_error(make_ctx):
    ctx, _ = make_ctx(cfg=L4Config.model_validate({"ci": {"runner_tags": ["agentic", "big"]}}))
    adopted(ctx.repo, main=INCLUDE)
    result = ci.CI_002.run(ctx)
    assert result.status == "fail" and result.severity == "error" and "big" in result.message


def test_ci002_variable_tags_are_not_checked_and_trigger_jobs_need_none(make_ctx):
    ctx, _ = make_ctx()
    main = INCLUDE + "build:\n  tags: [$RUNNER]\n  script: [make]\ndownstream:\n  trigger:\n    include: child.yml\n"
    adopted(ctx.repo, main=main)
    result = ci.CI_002.run(ctx)
    assert result.status == "pass" and "not checked" in result.message


def test_ci002_extends_and_hidden_jobs(make_ctx):
    ctx, _ = make_ctx()
    main = INCLUDE + ".base:\n  tags: [agentic]\ntest:\n  extends: .base\n  script: [x]\n"
    adopted(ctx.repo, main=main)
    assert ci.CI_002.run(ctx).status == "pass"  # `.base` is not a job; `test` inherits its tags


def test_ci002_skips_without_a_gitlab_file_and_off_gitlab(make_ctx):
    ctx, _ = make_ctx()
    assert ci.CI_002.run(ctx).status == "skip"
    adopted(ctx.repo)
    off, _ = make_ctx(cfg=L4Config.model_validate({"ci": {"platform": "github"}}))
    assert ci.CI_002.run(off).status == "skip"


def test_ci002_remote_includes_are_listed_as_not_checked(make_ctx):
    ctx, _ = make_ctx()
    adopted(ctx.repo, main=INCLUDE.replace("include:\n", "include:\n  - remote: https://example.test/x.yml\n"))
    result = ci.CI_002.run(ctx)
    assert result.status == "pass" and "https://example.test/x.yml" in result.message


def test_ci002_is_in_the_config_scope():
    from l4.doctor.registry import REGISTRY

    assert {"ci", "local", "config"} <= ci.CI_002.scopes and ci.CI_002 in REGISTRY.checks()


# --- CI-003: repository CI jobs the gates do not mirror (adoption-lessons 6.1, 6.2; SCN-ADO-17..19) -------------------


from l4.doctor.registry import REGISTRY, load_check_modules  # noqa: E402

WORKFLOW = """\
on:
  push:
jobs:
  test:
    steps:
      - run: uv run pytest
  conformance:
    services:
      postgres:
        image: postgres:16
    steps:
      - run: uv run pytest -m postgres
"""


def gated(**extra) -> L4Config:
    return L4Config.model_validate(
        {"gates": {"test": {"command": ".venv/bin/pytest --junitxml=.l4-out/j.xml"}}, **extra}
    )


def test_ci_003_is_a_config_scope_warning():
    load_check_modules()
    check = next(c for c in REGISTRY.checks() if c.id == "CI-003")
    assert check.severity == "warn" and "config" in check.scopes


def test_ci_003_lists_the_unmirrored_job_with_its_services(make_ctx):
    ctx, _ = make_ctx(cfg=gated())
    put(ctx.repo, ".github/workflows/ci.yml", WORKFLOW)
    result = ci.CI_003.run(ctx)
    assert result.status == "fail"
    assert "ci.yml: conformance (services: postgres)" in result.message and "pytest -m postgres" in result.message
    assert "ci.yml: test" not in result.message
    assert "L4_FORGE_TOKEN" not in result.message  # no token sentence without GITHUB_TOKEN and auto


def test_ci_003_passes_when_every_job_is_mirrored(make_ctx):
    ctx, _ = make_ctx(cfg=gated())
    put(ctx.repo, ".github/workflows/ci.yml", WORKFLOW.split("  conformance:")[0])
    assert ci.CI_003.run(ctx).status == "pass"


def test_ci_003_names_a_uses_only_job_as_not_mirrored(make_ctx):
    ctx, _ = make_ctx(cfg=gated())
    put(
        ctx.repo,
        ".github/workflows/ci.yml",
        "on: push\njobs:\n  docker:\n    steps:\n      - uses: docker/build-push-action@v6\n",
    )
    result = ci.CI_003.run(ctx)
    assert result.status == "fail"
    assert "ci.yml: docker not mirrored (uses actions/services the gates do not run)" in result.message


def test_ci_003_is_skipped_without_a_ci_file(make_ctx):
    ctx, _ = make_ctx(cfg=gated())
    put(ctx.repo, ".github/workflows/l4.yml", "on: push\njobs: {}\n")
    result = ci.CI_003.run(ctx)
    assert result.status == "skip" and "no CI file" in result.message


def test_ci_003_names_a_file_that_does_not_parse(make_ctx):
    ctx, _ = make_ctx(cfg=gated())
    put(ctx.repo, ".github/workflows/bad.yml", "on: [push\njobs: {")
    result = ci.CI_003.run(ctx)
    assert result.status == "fail" and "bad.yml" in result.message


import pytest  # noqa: E402


def test_ci_003_says_the_workflow_token_starts_no_ci(make_ctx):
    config = gated(forge={"token_env": "GITHUB_TOKEN", "merge_policy": "auto"})
    ctx, _ = make_ctx(cfg=config)
    put(ctx.repo, ".github/workflows/ci.yml", WORKFLOW)
    result = ci.CI_003.run(ctx)
    assert result.status == "fail" and "start no CI" in result.message and "merges on the gates alone" in result.message
    for name in ("L4_FORGE_TOKEN", "forge.token_env", "l4 upgrade", "l4 setup github --secret"):
        assert name in (result.fix_hint or ""), name


@pytest.mark.parametrize(
    "forge",
    [{"token_env": "GITHUB_TOKEN", "merge_policy": "human"}, {"token_env": "L4_FORGE_TOKEN", "merge_policy": "auto"}],
)
def test_ci_003_has_no_token_sentence_otherwise(make_ctx, forge):
    ctx, _ = make_ctx(cfg=gated(forge=forge))
    put(ctx.repo, ".github/workflows/ci.yml", WORKFLOW)
    assert "start no CI" not in ci.CI_003.run(ctx).message


def test_ci_003_token_sentence_stands_without_a_ci_file(make_ctx):
    ctx, _ = make_ctx(cfg=gated(forge={"token_env": "GITHUB_TOKEN", "merge_policy": "auto"}))
    result = ci.CI_003.run(ctx)
    assert result.status == "fail" and "start no CI" in result.message


# --- CI-005: the job token is this job's (hotfix 0.4.24); CI-006: the rendered job's base branch ----------------------

URL_TOKEN_ENV = {"CI_REPOSITORY_URL": "https://gitlab-ci-token:job-tok@forge.test/grp/proj.git"}


def test_ci005_skips_outside_gitlab_ci_and_without_a_url_token(make_ctx):
    ctx, _ = make_ctx(CI_JOB_TOKEN="group-var", **URL_TOKEN_ENV)
    assert ci.CI_005.run(ctx).status == "skip"
    ctx, _ = make_ctx(GITLAB_CI="true", CI_JOB_TOKEN="group-var", CI_REPOSITORY_URL="https://forge.test/grp/p.git")
    assert ci.CI_005.run(ctx).status == "skip"


def test_ci005_passes_when_the_tokens_are_equal(make_ctx):
    ctx, _ = make_ctx(GITLAB_CI="true", CI_JOB_TOKEN="job-tok", **URL_TOKEN_ENV)
    assert ci.CI_005.run(ctx).status == "pass"


def test_ci005_warns_when_the_variable_overrides_the_job_token_and_prints_no_value(make_ctx):
    ctx, _ = make_ctx(GITLAB_CI="true", CI_JOB_TOKEN="group-var", **URL_TOKEN_ENV)
    result = ci.CI_005.run(ctx)
    assert result.status == "fail" and result.severity == "warn"
    text = result.message + (result.fix_hint or "")
    assert "CI_JOB_TOKEN is overridden by a CI/CD variable (project, group or instance)" in text
    assert "rename that variable (Settings > CI/CD > Variables)" in text
    assert "group-var" not in text and "job-tok" not in text
    assert ci.CI_005.title == "The job token is this job's" and ci.CI_005.severity == "warn"


def _rendered(ctx, base: str) -> None:
    from l4.config.schema import L4Config as Cfg

    cfg = Cfg.model_validate({"version": 1, "forge": {"base_branch": base}})
    put(ctx.repo, ".l4/ci/l4.gitlab-ci.yml", render_gitlab_ci(cfg))


def test_ci006_skips_without_the_rendered_job(make_ctx):
    ctx, _ = make_ctx()
    assert ci.CI_006.run(ctx).status == "skip"


def test_ci006_passes_when_the_rendered_base_branch_matches(make_ctx):
    ctx, _ = make_ctx()
    _rendered(ctx, "amaster")
    ctx = ctx.__class__(
        **{**ctx.__dict__, "cfg": L4Config.model_validate({"version": 1, "forge": {"base_branch": "amaster"}})}
    )
    assert ci.CI_006.run(ctx).status == "pass"


def test_ci006_warns_when_the_rendered_base_branch_differs(make_ctx):
    ctx, _ = make_ctx()
    _rendered(ctx, "main")
    ctx = ctx.__class__(
        **{**ctx.__dict__, "cfg": L4Config.model_validate({"version": 1, "forge": {"base_branch": "amaster"}})}
    )
    result = ci.CI_006.run(ctx)
    assert result.status == "fail" and result.severity == "warn"
    assert "the rendered L4 job names base branch main, forge.base_branch is amaster" in result.message
    assert "l4 upgrade" in result.message and "re-renders it" in result.message


# --- CI-007: the harness's pipelines are not empty (gitlab-adoption 2.2; L4-INS-008) ----------------------------------

NO_SCHEDULE_JOBS = (
    "stages: [test]\n"
    "unit_tests:\n  stage: test\n  except: [schedules, api, triggers]\n  script: [x]\n"
    "deploy_review:\n  except: [schedules, api, triggers]\n  script: [x]\n"
    "lint:\n  rules:\n    - if: '$CI_PIPELINE_SOURCE == \"push\"'\n  script: [x]\n"
)
ANCHOR = (
    "l4-pipeline-anchor:\n  stage: test\n  script: [echo]\n  rules:\n"
    "    - if: '$CI_PIPELINE_SOURCE =~ /^(schedule|api|trigger|web)$/'\n"
    "    - if: '$CI_PIPELINE_SOURCE == \"push\" && $CI_COMMIT_BRANCH =~ /^l4\\/unit/'\n"
)


def _ci007_ctx(make_ctx, main: str, base: str = "master"):
    cfg = L4Config.model_validate({"version": 1, "ci": {"platform": "gitlab"}, "forge": {"base_branch": base}})
    ctx, _ = make_ctx(cfg=cfg)
    adopted(ctx.repo, main=INCLUDE + main)
    return ctx


def test_ci007_is_registered_as_a_warn_check_over_the_config_scopes():
    from l4.doctor.registry import CONFIG_SCOPES

    assert ci.CI_007.id == "CI-007" and ci.CI_007.severity == "warn" and ci.CI_007.scopes == CONFIG_SCOPES
    assert ci.CI_007.title == "The harness's pipelines are not empty"


def test_ci007_skips_without_gitlab_or_without_the_file(make_ctx):
    cfg = L4Config.model_validate({"version": 1, "ci": {"platform": "github"}})
    ctx, _ = make_ctx(cfg=cfg)
    adopted(ctx.repo, main=INCLUDE + NO_SCHEDULE_JOBS)
    assert ci.CI_007.run(ctx).status == "skip"
    (ctx.repo / ".gitlab-ci.yml").unlink()
    cfg = L4Config.model_validate({"version": 1, "ci": {"platform": "gitlab"}})
    ctx, _ = make_ctx(cfg=cfg)
    assert ci.CI_007.run(ctx).status == "skip"


def test_ci007_passes_when_a_normal_job_runs(make_ctx):
    result = ci.CI_007.run(_ci007_ctx(make_ctx, TEST_JOB))
    assert result.status == "pass"
    assert result.message == "a project job in a normal stage runs on the harness's pipelines"


def test_scn_ins_20_ci007_warns_that_only_the_l4_job_would_run(make_ctx):
    result = ci.CI_007.run(_ci007_ctx(make_ctx, NO_SCHEDULE_JOBS))
    assert result.status == "fail" and result.severity == "warn"
    for article, source in (("a", "schedule"), ("an", "api")):
        assert (
            f"on {article} {source} pipeline of master only the l4 job (stage .post) would be created, and GitLab "
            'refuses a pipeline whose jobs are all in .pre or .post ("pipeline would have been empty")'
        ) in result.message
    assert "add a job in a normal stage that runs on schedule, api, trigger and web pipelines" in result.message
    assert "(l4 init --ci gitlab adds l4-pipeline-anchor)" in result.message


def test_scn_ins_21_an_anchor_job_or_an_unknown_job_is_enough(make_ctx):
    assert ci.CI_007.run(_ci007_ctx(make_ctx, NO_SCHEDULE_JOBS + ANCHOR)).status == "pass"
    unknown = "env_job:\n  rules:\n    - if: '$DEPLOY_ENV == \"prod\"'\n  script: [x]\n"
    assert ci.CI_007.run(_ci007_ctx(make_ctx, NO_SCHEDULE_JOBS + unknown)).status == "pass"


def test_scn_ins_29_a_pre_job_does_not_make_the_pipeline_acceptable(make_ctx):
    result = ci.CI_007.run(_ci007_ctx(make_ctx, NO_SCHEDULE_JOBS + "notify:\n  stage: .pre\n  script: [x]\n"))
    assert result.status == "fail" and "schedule pipeline of master" in result.message
    assert "api pipeline of master" in result.message


def test_scn_ins_22_ci007_warns_when_workflow_rules_exclude_schedules(make_ctx):
    workflow = (
        "workflow:\n  rules:\n    - if: '$CI_PIPELINE_SOURCE == \"schedule\"'\n      when: never\n    - when: always\n"
    )
    result = ci.CI_007.run(_ci007_ctx(make_ctx, TEST_JOB + workflow))
    assert result.status == "fail" and result.severity == "warn"
    assert (
        ".gitlab-ci.yml's workflow:rules create no schedule pipeline on master: the l4 job never runs on one"
        in result.message
    )
    assert "api pipeline" not in result.message


def test_ci007_checks_the_push_pipeline_of_a_unit_branch(make_ctx):
    job = "job:\n  only: [schedules, api]\n  script: [x]\n"
    result = ci.CI_007.run(_ci007_ctx(make_ctx, job))
    assert result.status == "fail"
    assert "on a push pipeline of l4/* only the l4 job" in result.message
    assert "on pushes to l4/ branches" in result.message


def test_ci007_does_not_judge_a_file_it_cannot_read_in_full(make_ctx):
    ctx = _ci007_ctx(make_ctx, "")
    put(ctx.repo, ".gitlab-ci.yml", INCLUDE + "  - remote: https://x.test/a.yml\n" + NO_SCHEDULE_JOBS)
    assert ci.CI_007.run(ctx).status == "pass"


# --- CI-008 (L4-INS-011): a project job that deploys on the harness's own pipelines -----------------------------

DEPLOY_ON_MASTER = "deploy_staging:\n  stage: deploy\n  only: [master]\n  script: [x]\n"


def test_ci008_is_registered():
    from l4.doctor.registry import CONFIG_SCOPES

    assert ci.CI_008.id == "CI-008" and ci.CI_008.severity == "warn" and ci.CI_008.scopes == CONFIG_SCOPES
    assert ci.CI_008.title == "The harness's pipelines deploy nothing"


def test_scn_ins_30_a_deploy_job_on_the_base_branch_runs_on_every_harness_run(make_ctx):
    result = ci.CI_008.run(_ci007_ctx(make_ctx, TEST_JOB + DEPLOY_ON_MASTER))
    assert result.status == "fail" and result.severity == "warn"
    assert (
        "on a schedule pipeline of master the project's jobs deploy_staging deploy (an environment or a deploy stage) "
        "and would run on every harness run: exclude them from schedule, api, trigger and web pipelines"
    ) in result.message
    assert "on an api pipeline of master the project's jobs deploy_staging" in result.message


def test_scn_ins_31_excluded_manual_or_unknown_deploy_jobs_are_not_named(make_ctx):
    excluded = (
        "deploy_staging:\n  stage: deploy\n  only: [master]\n  except: [schedules, api, triggers]\n  script: [x]\n"
    )
    manual = "deploy_staging:\n  stage: deploy\n  only: [master]\n  when: manual\n  script: [x]\n"
    rule_manual = (
        "ship:\n  environment: production\n  rules:\n    - if: '$CI_COMMIT_BRANCH == \"master\"'\n"
        "      when: manual\n  script: [x]\n"
    )
    unknown = "ship:\n  environment: production\n  rules:\n    - if: '$DEPLOY == \"1\"'\n  script: [x]\n"
    for text in (excluded, manual, rule_manual, unknown):
        result = ci.CI_008.run(_ci007_ctx(make_ctx, TEST_JOB + text))
        assert result.status == "pass", text
        assert result.message == "no project job deploys on the harness's pipelines"


def test_ci008_names_a_job_with_an_environment_in_any_stage(make_ctx):
    job = "review:\n  environment:\n    name: staging\n  only: [master]\n  script: [x]\n"
    stop = "teardown:\n  environment:\n    name: staging\n    action: stop\n  only: [master]\n  script: [x]\n"
    assert "the project's jobs review deploy" in ci.CI_008.run(_ci007_ctx(make_ctx, TEST_JOB + job)).message
    assert ci.CI_008.run(_ci007_ctx(make_ctx, TEST_JOB + stop)).status == "pass"


def test_ci008_skips_without_gitlab(make_ctx):
    cfg = L4Config.model_validate({"version": 1, "ci": {"platform": "github"}})
    ctx, _ = make_ctx(cfg=cfg)
    assert ci.CI_008.run(ctx).status == "skip"
