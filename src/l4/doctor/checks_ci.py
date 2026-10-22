"""CI-001: the runner's `insteadOf` rule (see l4.forge.pushurl). CI-002: the runner tags of the pipeline's jobs (M1.8).
CI-003: the repository's own CI jobs that the gates do not mirror (adoption-lessons L4-ADO-006).
CI-005: `CI_JOB_TOKEN` is the job's own token (a CI/CD variable of that name overrides it). CI-006: the rendered
GitLab job names the configured base branch. CI-007: the harness's own pipelines are not empty (L4-INS-008).
CI-008: no project job deploys on the harness's own pipelines (L4-INS-011).
Registered at import (via l4.doctor.run)."""

import re

from l4.ci.gitlab_jobs import gitlab_jobs
from l4.ci.gitlab_rules import deploying_findings, empty_pipeline_findings
from l4.ci.render import TEMPLATE_RELPATH
from l4.ci.repo_jobs import RepoJob, open_commands, repo_ci_jobs, unmirrored
from l4.doctor.context import DoctorContext
from l4.doctor.registry import CONFIG_SCOPES, Check, CheckResult, register
from l4.forge.base import forge_wanted
from l4.forge.pushurl import push_url, runner_rewrites_urls
from l4.redact import url_job_token


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


MAX_JOB_COMMANDS = 3
OPAQUE_REASON = "uses actions/services the gates do not run"


def _job_line(job: RepoJob, wanted: list[str]) -> str:
    where = f"{job.file}: {job.name}"
    extras = []
    if job.services:
        extras.append(f"services: {', '.join(job.services)}")
    if job.container:
        extras.append("container")
    if not wanted:
        return f"{where}{' (' + '; '.join(extras) + ')' if extras else ''} not mirrored ({OPAQUE_REASON})"
    shown = ", ".join(f"`{c}`" for c in wanted[:MAX_JOB_COMMANDS])
    more = f" (+{len(wanted) - MAX_JOB_COMMANDS} more)" if len(wanted) > MAX_JOB_COMMANDS else ""
    tail = f" ({'; '.join(extras)})" if extras else ""
    return f"{where}{tail} runs {shown}{more}"


TOKEN_SENTENCE = (
    "forge.token_env is GITHUB_TOKEN and forge.merge_policy is auto: a push made with the workflow's GITHUB_TOKEN "
    "starts no workflow run, so L4's pushes start no CI and a `merge: auto` plan merges on the gates alone"
)
TOKEN_HINT = (
    "set a personal or app token as the repository secret L4_FORGE_TOKEN (`l4 setup github --secret`), set "
    "forge.token_env to L4_FORGE_TOKEN, then run `l4 upgrade` so that the workflow passes it"
)


def _workflow_token_starts_no_ci(ctx: DoctorContext) -> bool:
    forge = ctx.cfg.forge
    return forge.token_env == "GITHUB_TOKEN" and forge.merge_policy == "auto"  # noqa: S105  (a name, not a secret)


def _ci_003(ctx: DoctorContext) -> CheckResult:
    """The warning of `l4 doctor --adoption`: a job of the repository's own CI that no gate mirrors is not run by L4,
    so a unit can hand off green on the gates and red on that job. Heuristic (design D6): it never fails a run."""
    found = repo_ci_jobs(ctx.repo)
    token = _workflow_token_starts_no_ci(ctx)
    if not found.present and not token:
        return CheckResult("skip", "no CI file besides l4.yml and no .gitlab-ci.yml")
    open_jobs = unmirrored(found.jobs, ctx.cfg)
    parts = []
    if open_jobs:
        lines = "; ".join(_job_line(j, open_commands(j, ctx.cfg)) for j in open_jobs)
        parts.append(
            f"{len(open_jobs)} job(s) of the repository's own CI have a command that no gate runs, so L4 does not "
            f"run it: {lines}"
        )
    if found.problems:
        parts.append("not compared: " + "; ".join(found.problems))
    if token:
        parts.append(TOKEN_SENTENCE)
    if not parts:
        return CheckResult("pass", f"{len(found.jobs)} CI job(s), each mirrored by a gate")
    hints = []
    if open_jobs or found.problems:
        hints.append(
            "add the command to a gate (gates.setup, lint, test, e2e), or accept that no unit is checked by it"
        )
    if token:
        hints.append(TOKEN_HINT)
    return CheckResult("fail", "; ".join(parts), "; ".join(hints), severity="warn")


CI_003 = register(Check("CI-003", "The repository's CI jobs are mirrored by the gates", "warn", _ci_003, CONFIG_SCOPES))


def _ci_005(ctx: DoctorContext) -> CheckResult:
    """A CI/CD variable named `CI_JOB_TOKEN` (project, group or instance) overrides the predefined one: L4 then uses the
    job token in `CI_REPOSITORY_URL`, but the project's own jobs get the variable's value. No value is printed."""
    if ctx.env.get("GITLAB_CI") != "true":
        return CheckResult("skip", "not inside GitLab CI")
    from_url = url_job_token(ctx.env)
    if not from_url:
        return CheckResult("skip", "no job token in CI_REPOSITORY_URL")
    if from_url == (ctx.env.get("CI_JOB_TOKEN") or ""):
        return CheckResult("pass", "CI_JOB_TOKEN is the job token in CI_REPOSITORY_URL")
    return CheckResult(
        "fail",
        "CI_JOB_TOKEN is overridden by a CI/CD variable (project, group or instance): L4 uses the job token in "
        "CI_REPOSITORY_URL, but the project's own jobs get the variable's value; rename that variable "
        "(Settings > CI/CD > Variables)",
        severity="warn",
    )


CI_005 = register(Check("CI-005", "The job token is this job's", "warn", _ci_005))

_RENDERED_BASE = re.compile(r'^\s*L4_BASE_BRANCH:\s*"([^"]*)"', re.M)


def _ci_006(ctx: DoctorContext) -> CheckResult:
    """The rendered job's `L4_BASE_BRANCH` is what its base-branch rules and base checkout read: a value other than
    `forge.base_branch` (a re-init, or a config change without `l4 upgrade`) leaves them never firing on a merge."""
    path = ctx.repo / TEMPLATE_RELPATH
    if not path.is_file():
        return CheckResult("skip", f"no {TEMPLATE_RELPATH}")
    found = _RENDERED_BASE.search(path.read_text(encoding="utf-8", errors="replace"))
    if found is None:
        return CheckResult("skip", f"no L4_BASE_BRANCH in {TEMPLATE_RELPATH}")
    want = ctx.cfg.forge.base_branch
    if found.group(1) == want:
        return CheckResult("pass", f"the rendered L4 job names base branch {want}")
    return CheckResult(
        "fail",
        f"the rendered L4 job names base branch {found.group(1)}, forge.base_branch is {want}: its base-branch rules "
        "never fire on a merge; run l4 upgrade, which re-renders it",
        severity="warn",
    )


CI_006 = register(Check("CI-006", "The rendered L4 job names the base branch", "warn", _ci_006, CONFIG_SCOPES))


def _ci_007(ctx: DoctorContext) -> CheckResult:
    """On a schedule or api pipeline of the base branch and the push pipeline of a unit branch, some project job in a
    normal stage must run (or be unknown): GitLab refuses a pipeline whose jobs are all in `.pre` or `.post`, and the
    `l4` job is in `.post`. Also: `workflow: rules` must create those pipelines at all."""
    if ctx.cfg.ci.platform in ("github", "local"):
        return CheckResult("skip", f"ci.platform is {ctx.cfg.ci.platform}")
    found = gitlab_jobs(ctx.repo)
    if not found.present:
        return CheckResult("skip", "no .gitlab-ci.yml")
    base = ctx.cfg.forge.base_branch or "main"
    findings = empty_pipeline_findings(found, base, base, ctx.cfg.forge.branch_prefix)
    if not findings:
        return CheckResult("pass", "a project job in a normal stage runs on the harness's pipelines")
    return CheckResult("fail", "; ".join(f.text for f in findings), severity="warn")


CI_007 = register(Check("CI-007", "The harness's pipelines are not empty", "warn", _ci_007, CONFIG_SCOPES))


def _ci_008(ctx: DoctorContext) -> CheckResult:
    """No project job that deploys (an environment, a deploy stage) starts by itself on a schedule or api pipeline of
    the base branch: every harness run would deploy (L4-INS-011)."""
    if ctx.cfg.ci.platform in ("github", "local"):
        return CheckResult("skip", f"ci.platform is {ctx.cfg.ci.platform}")
    found = gitlab_jobs(ctx.repo)
    if not found.present:
        return CheckResult("skip", "no .gitlab-ci.yml")
    base = ctx.cfg.forge.base_branch or "main"
    findings = deploying_findings(found, base, base, ctx.cfg.forge.branch_prefix)
    if not findings:
        return CheckResult("pass", "no project job deploys on the harness's pipelines")
    return CheckResult("fail", "; ".join(f.text for f in findings), severity="warn")


CI_008 = register(Check("CI-008", "The harness's pipelines deploy nothing", "warn", _ci_008, CONFIG_SCOPES))
