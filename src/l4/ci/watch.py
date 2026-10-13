"""`l4 ci watch`: follow a GitLab pipeline, or a GitHub workflow run, to its end (M1.8 A13, github-parity 4.2).

One line per job status change (`job <id> <name> (<stage>) <status> — runner #<id> <description>`), a final table, and
an exit code a script can use: 0 for a successful pipeline (a job that failed with `allow_failure` is a success, and
says `failed (allowed)`), 1 for failed, canceled, skipped or timed out. `tail` prints the last lines of the trace of
every failed job (ANSI stripped). The credential never appears in a line: it is only in the client, which cuts it out
of its own errors. A transport error or a 5xx answer is retried at the next poll (a few times); anything else raises.
"""

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from l4.forge.gitlab_admin import AdminApi, AdminError

if TYPE_CHECKING:
    from l4.forge.github import GitHubForge
    from l4.setup.github import GhApi

TERMINAL = frozenset({"success", "failed", "canceled", "skipped"})
MAX_TRANSIENT = 5
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07")


@dataclass(frozen=True)
class WatchResult:
    status: str  # the pipeline's own, or `timeout`
    ok: bool
    exit_code: int
    pipeline: dict[str, Any] = field(default_factory=dict)
    jobs: tuple[dict[str, Any], ...] = ()


def _runner(job: dict[str, Any]) -> str:
    found = job.get("runner")
    if isinstance(found, dict) and found.get("id") is not None:
        return f"runner #{found['id']} {found.get('description', '')}".rstrip()
    return "no runner yet"


def _status_text(job: dict[str, Any]) -> str:
    return "failed (allowed)" if job.get("status") == "failed" and job.get("allow_failure") else str(job.get("status"))


def _job_line(job: dict[str, Any]) -> str:
    return f"job {job['id']} {job['name']} ({job.get('stage', '?')}) {_status_text(job)} — {_runner(job)}"


def watch_pipeline(
    api: AdminApi,
    project: str,
    pipeline_id: int,
    *,
    say: Callable[[str], None],
    interval: float = 15.0,
    timeout: float = 5400.0,
    tail: int = 0,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> WatchResult:
    base = f"projects/{project}/pipelines/{pipeline_id}"
    started = clock()
    seen: dict[int, str] = {}
    last_status = ""
    transient = 0
    while True:
        try:
            pipeline = api.get(base)
            jobs = api.get_paged(f"{base}/jobs")
        except AdminError as exc:
            if (exc.status == 0 or exc.status >= 500) and transient < MAX_TRANSIENT:
                transient += 1
                pipeline, jobs = None, []
            else:
                raise
        else:
            transient = 0
        if pipeline is not None:
            if pipeline["status"] != last_status:
                suffix = f": {pipeline.get('web_url')}" if not last_status and pipeline.get("web_url") else ""
                say(f"pipeline #{pipeline_id} {pipeline['status']}{suffix}")
                last_status = pipeline["status"]
            for job in jobs:
                text = _status_text(job)
                if seen.get(job["id"]) != text:
                    seen[job["id"]] = text
                    say(_job_line(job))
            if pipeline["status"] in TERMINAL:
                return _finish(api, project, pipeline, jobs, say, tail)
        remaining = timeout - (clock() - started)
        if remaining <= 0:
            say(f"timed out after {int(timeout)} s waiting for pipeline #{pipeline_id} (status {last_status or '?'})")
            return WatchResult("timeout", False, 1, pipeline or {}, tuple(jobs))
        sleep(min(interval, remaining))


def _finish(
    api: AdminApi,
    project: str,
    pipeline: dict[str, Any],
    jobs: list[dict[str, Any]],
    say: Callable[[str], None],
    tail: int,
) -> WatchResult:
    for job in jobs:
        say(f"  {job['name']:<24} {job.get('stage', ''):<8} {_status_text(job):<18} {_runner(job)}")
    if tail > 0:
        for job in (j for j in jobs if j.get("status") == "failed"):
            try:
                trace = api.get_text(f"projects/{project}/jobs/{job['id']}/trace")
            except AdminError as exc:
                say(f"  trace of job {job['id']} {job['name']}: not available ({exc.status})")
                continue
            lines = [_ANSI.sub("", line).rstrip("\r") for line in trace.splitlines()][-tail:]
            say(f"  trace of job {job['id']} {job['name']} (last {len(lines)} lines):")
            for line in lines:
                say(f"    | {line}")
    ok = pipeline["status"] == "success"
    code = 0 if ok else 1
    say(f"pipeline #{pipeline['id']} {pipeline['status']} -> exit {code}")
    return WatchResult(pipeline["status"], ok, code, pipeline, tuple(jobs))


@dataclass(frozen=True)
class GithubWatchResult:
    run_id: int
    status: str  # the run's own, or `timeout`
    conclusion: str
    exit_code: int


FAILED_CONCLUSIONS = frozenset({"failure", "timed_out", "startup_failure"})


def watch_github_run(
    api: "GhApi",
    forge: "GitHubForge",
    repo: str,
    ref: str,
    *,
    workflow: str = "l4.yml",
    after: int = 0,
    say: Callable[[str], None],
    interval: float = 15.0,
    timeout: float = 5400.0,
    tail: int = 0,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> GithubWatchResult:
    """Follow the newest run of `workflow` on `ref` (one whose id is above `after`: the run a dispatch just made) until
    it is completed. Prints the run's status changes, then each job's conclusion and, for a failed job, the last `tail`
    lines of its log (`Forge.job_log`). Exit 0 when the run's conclusion is `success`, else 1 (also on a timeout)."""
    from l4.setup.github import GhError

    runs = f"/repos/{repo}/actions/workflows/{workflow}/runs"
    started = clock()
    last = ""
    transient = 0
    while True:
        run: dict[str, Any] | None = None
        try:
            body = api.get(runs, {"branch": ref, "per_page": 1}) or {}
            found = body.get("workflow_runs") or []
            run = found[0] if found and int(found[0]["id"]) > after else None
            jobs = (
                (api.get(f"/repos/{repo}/actions/runs/{run['id']}/jobs", {"per_page": 100}) or {}).get("jobs", [])
                if run and run.get("status") == "completed"
                else []
            )
        except GhError as exc:
            if (exc.status == 0 or exc.status >= 500) and transient < MAX_TRANSIENT:
                transient += 1
                run = None
            else:
                raise
        else:
            transient = 0
        if run is not None:
            if run["status"] != last:
                suffix = f": {run['html_url']}" if not last and run.get("html_url") else ""
                say(f"run #{run['id']} {run['status']}{suffix}")
                last = run["status"]
            if run["status"] == "completed":
                return _finish_github(forge, run, jobs, say, tail)
        remaining = timeout - (clock() - started)
        if remaining <= 0:
            what = f"run #{run['id']} (status {last})" if run else f"a run of {workflow} on {ref}"
            say(f"timed out after {int(timeout)} s waiting for {what}")
            return GithubWatchResult(int(run["id"]) if run else 0, "timeout", "", 1)
        sleep(min(interval, remaining))


def _finish_github(
    forge: "GitHubForge",
    run: dict[str, Any],
    jobs: list[dict[str, Any]],
    say: Callable[[str], None],
    tail: int,
) -> GithubWatchResult:
    for job in jobs:
        say(f"  {job['name']:<24} {job.get('conclusion') or job.get('status')}")
    if tail > 0:
        for job in (j for j in jobs if j.get("conclusion") in FAILED_CONCLUSIONS):
            text = forge.job_log(int(job["id"]), tail).tail
            lines = [_ANSI.sub("", line).rstrip("\r") for line in text.splitlines()][-tail:]
            if not lines:
                say(f"  log of job {job['id']} {job['name']}: not available")
                continue
            say(f"  log of job {job['id']} {job['name']} (last {len(lines)} lines):")
            for line in lines:
                say(f"    | {line}")
    conclusion = str(run.get("conclusion") or "")
    code = 0 if conclusion == "success" else 1
    say(f"run #{run['id']} completed ({conclusion or 'no conclusion'}) -> exit {code}")
    return GithubWatchResult(int(run["id"]), "completed", conclusion, code)


def run_ci_watch(
    app: Any,
    *,
    project: str | None = None,
    pipeline: int | None = None,
    ref: str | None = None,
    api_base: str | None = None,
    auth_env: str | None = None,
    repo: str | None = None,
    api_url: str | None = None,
    auth_scheme: str = "private-token",
    interval: str = "15s",
    timeout: str = "90m",
    tail: int = 0,
    token_command: str | None = None,
    transport: Any = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> Any:
    """`l4 ci watch --project P [--pipeline ID | --ref REF]`: exit 0 for a successful pipeline, 1 for failed, canceled,
    skipped, timed out or an HTTP error; 2 for usage. Without `--pipeline` it takes the latest pipeline of `--ref`
    (the default branch when neither is given). With `--repo owner/name` (or, without `--project`, an `origin` on
    GitHub) it follows the newest run of `l4.yml` on `--ref` instead (L4-GHP-012)."""
    from l4.config.schema import duration_seconds
    from l4.exitcodes import ExitCode, L4Exit
    from l4.setup.gitlab import _hint, connect_gitlab, project_path

    if repo is not None or (project is None and _origin_is_github(app)):
        return _run_github_watch(
            app, repo=repo, ref=ref, api_url=api_url, token_env=auth_env or "GH_TOKEN", interval=interval,
            timeout=timeout, tail=tail, transport=transport, sleep=sleep, clock=clock,
        )  # fmt: skip
    if project is None:
        raise L4Exit(ExitCode.USAGE_ERROR, "ci watch: pass --project (GitLab) or --repo owner/name (GitHub)")
    auth_env = auth_env or "GITLAB_TOKEN"
    pid = project_path(project)
    try:
        seconds = (duration_seconds(interval), duration_seconds(timeout))
    except ValueError:
        raise L4Exit(
            ExitCode.USAGE_ERROR, "ci watch: --interval and --timeout are durations such as 15s or 90m"
        ) from None
    if tail < 0:
        raise L4Exit(ExitCode.USAGE_ERROR, "ci watch: --tail is a number of lines")
    link = connect_gitlab(
        app, api_base=api_base, auth_env=auth_env, auth_scheme=auth_scheme, transport=transport,
        token_command=token_command,
    )  # fmt: skip
    app = link.app
    import click

    from l4.redact import Redactor

    app.redactor.adopt(Redactor({"watch:credential": link.credential}))

    def say(line: str) -> None:
        click.echo(app.redactor.redact_text(line))

    try:
        if pipeline is None:
            wanted = ref or link.api.get(f"projects/{pid}").get("default_branch")
            found = link.api.get(f"projects/{pid}/pipelines", {"ref": wanted, "per_page": 1}) if wanted else []
            if not found:
                say(f"ERROR no pipeline found on {wanted or 'the project'}: pass --pipeline ID or --ref REF")
                return ExitCode.INTERNAL_ERROR
            pipeline = int(found[0]["id"])
        result = watch_pipeline(
            link.api,
            pid,
            pipeline,
            say=say,
            interval=seconds[0],
            timeout=seconds[1],
            tail=tail,
            sleep=sleep,
            clock=clock,
        )
    except AdminError as exc:
        say(f"ERROR {exc}" + (f"\n      {_hint(exc)}" if _hint(exc) else ""))
        return ExitCode.INTERNAL_ERROR
    return ExitCode(result.exit_code)


def _origin_is_github(app: Any) -> bool:
    from l4.forge.base import GITHUB_HOSTS, parse_remote_url
    from l4.forge.urls import origin_url

    remote = parse_remote_url(origin_url(app.repo, app.environ) or "")
    return remote is not None and remote.host in GITHUB_HOSTS


def _run_github_watch(
    app: Any,
    *,
    repo: str | None,
    ref: str | None,
    api_url: str | None,
    token_env: str,
    interval: str,
    timeout: str,
    tail: int,
    transport: Any,
    sleep: Callable[[float], None],
    clock: Callable[[], float],
) -> Any:
    import click

    from l4.config.redaction import load_app_config
    from l4.config.schema import duration_seconds
    from l4.exitcodes import ExitCode, L4Exit
    from l4.forge.github import DEFAULT_API, GitHubForge
    from l4.redact import Redactor
    from l4.setup.github import GhApi, GhError, resolve_target

    try:
        seconds = (duration_seconds(interval), duration_seconds(timeout))
    except ValueError:
        raise L4Exit(
            ExitCode.USAGE_ERROR, "ci watch: --interval and --timeout are durations such as 15s or 90m"
        ) from None
    if tail < 0:
        raise L4Exit(ExitCode.USAGE_ERROR, "ci watch: --tail is a number of lines")
    token = app.environ.get(token_env, "")
    if not token:
        raise L4Exit(ExitCode.USAGE_ERROR, f"ci watch: the environment variable {token_env} is empty or not set")
    app, cfg = load_app_config(app)
    name, base_url = resolve_target(app, repo, api_url)
    app.redactor.adopt(Redactor({"watch:token": token}))

    def say(line: str) -> None:
        click.echo(app.redactor.redact_text(line))

    api = GhApi(base_url or DEFAULT_API, token, transport)
    forge = GitHubForge(name, token, api_url=base_url or DEFAULT_API, transport=transport)
    try:
        result = watch_github_run(
            api, forge, name, ref or cfg.forge.base_branch, say=say, interval=seconds[0], timeout=seconds[1],
            tail=tail, sleep=sleep, clock=clock,
        )  # fmt: skip
    except GhError as exc:
        say(f"ERROR {exc}")
        return ExitCode.INTERNAL_ERROR
    return ExitCode(result.exit_code)
