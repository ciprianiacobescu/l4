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
