"""CI-001: the runner's `insteadOf` rule (see l4.forge.pushurl). CI-002: the runner tags of the pipeline's jobs (M1.8).
Registered at import (via l4.doctor.run)."""

from l4.ci.gitlab_jobs import gitlab_jobs
from l4.ci.render import TEMPLATE_RELPATH
from l4.doctor.context import DoctorContext
from l4.doctor.registry import CONFIG_SCOPES, Check, CheckResult, register
from l4.forge.base import forge_wanted
from l4.forge.pushurl import push_url, runner_rewrites_urls


def _ci_001(ctx: DoctorContext) -> CheckResult:
    if ctx.env.get("GITLAB_CI") != "true":
        return CheckResult("skip", "not a GitLab CI job")
    if not runner_rewrites_urls(ctx.env):
        return CheckResult("pass", "the runner does not rewrite the origin URL")
    token_env = ctx.cfg.forge.token_env
    if not forge_wanted(ctx.cfg):
        return CheckResult("pass", "the runner rewrites the origin URL; the forge is not GitLab, no push is made")
    if not ctx.env.get(token_env):
        return CheckResult(
            "fail",
            "the runner rewrites https URLs of this server to carry the CI job token (insteadOf in its "
            f"include file), and {token_env} is not set: every push would use the job token, which cannot push "
            '(GitLab answers 403 "You are not allowed to push code to this project")',
            f"define {token_env} as a masked CI/CD variable (a project access token with write_repository and api "
            "scopes, Developer role or higher)",
        )
    if push_url(ctx.cfg, ctx.env) is None:
        return CheckResult(
            "fail",
            "the runner rewrites the origin URL and the push URL cannot be built: CI_SERVER_URL and "
            "CI_PROJECT_PATH are missing",
            "run inside a GitLab CI job, or set forge.gitlab.api_url and forge.gitlab.project",
        )
    return CheckResult("pass", f"the runner rewrites the origin URL; pushes go to oauth2@ with {token_env} instead")


CI_001 = register(Check("CI-001", "Runner URL rewriting cannot hijack pushes", "error", _ci_001))


HARNESS_JOB = "l4"


def _ci_002(ctx: DoctorContext) -> CheckResult:
    """Every job must carry every tag of `ci.runner_tags`. The harness job `l4` missing one is an error (it would stay
    pending, or run on an instance runner next to other projects' code); a repository job missing one is a warning,
    because it may be untagged on purpose (sample-consumer's `test` job, owner decision O8)."""
    wanted = tuple(ctx.cfg.ci.runner_tags)
    if ctx.cfg.ci.platform in ("github", "local"):
        return CheckResult("skip", f"ci.platform is {ctx.cfg.ci.platform}")
    found = gitlab_jobs(ctx.repo)
    if not found.present:
        return CheckResult("skip", "no .gitlab-ci.yml")
    if not wanted:
        return CheckResult("pass", "ci.runner_tags is empty: no tag is required")
    errors: list[str] = []
    repo_jobs: list[str] = []
    variables: list[str] = []
    for job in found.jobs:
        if job.trigger:
            continue  # a bridge job runs on no runner
        tags = found.effective_tags(job)
        if any(t.startswith("$") for t in tags):
            variables.append(job.name)
            continue
        missing = [t for t in wanted if t not in tags]
        if job.name == HARNESS_JOB:
            shipped = job.source == TEMPLATE_RELPATH and not job.overridden
            if missing:
                errors.append(
                    f"job {job.name} ({job.source}) has tags [{', '.join(tags)}] and lacks [{', '.join(missing)}]: "
                    "it would stay pending, or run on an instance runner"
                )
            elif shipped and set(tags) != set(wanted):
                errors.append(
                    f"the template {TEMPLATE_RELPATH} tags job {job.name} [{', '.join(tags)}] but ci.runner_tags is "
                    f"[{', '.join(wanted)}]: the template is static; set ci.runner_tags to its tags or edit it"
                )
        elif missing:
            repo_jobs.append(job.name)
    unchecked = [*found.not_checked, *found.problems]
    notes = []
    if variables:
        notes.append(f"tags of {', '.join(variables)} use a variable (not checked)")
    if unchecked:
        notes.append("not checked: " + "; ".join(unchecked))
    tail = f" ({'; '.join(notes)})" if notes else ""
    if errors:
        return CheckResult(
            "fail", "; ".join(errors) + tail,
            f"give the job the tags [{', '.join(wanted)}] (or change ci.runner_tags to the tags the runner has)",
            severity="error",
        )  # fmt: skip
    if repo_jobs:
        return CheckResult(
            "fail",
            f"{len(repo_jobs)} repository job(s) lack the tags [{', '.join(wanted)}]: {', '.join(repo_jobs)}; they run "
            "on any runner of the instance, so your code leaves the tagged runner" + tail,
            "tag them, or ignore this if they are meant to run elsewhere",
            severity="warn",
        )
    return CheckResult("pass", f"every job carries [{', '.join(wanted)}]{tail}")


CI_002 = register(Check("CI-002", "Jobs carry the runner tags", "error", _ci_002, CONFIG_SCOPES))
