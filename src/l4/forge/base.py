"""The forge port, reduced to what M0 calls (forge-and-ci 1.1/1.2, D4): a merge request, its labels, its draft flag.

M1: forge-and-ci 1.1 adds the rest of the `Forge` Protocol (sticky note, commit status, jobs, approvals,
continuation) and 1.2 `make_forge` choosing by the origin URL; GitHub is forge-and-ci 2.x.
"""

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol, TypeVar
from urllib.parse import urlsplit

import httpx

from l4.config.schema import L4Config
from l4.exitcodes import ExitCode, L4Exit

T = TypeVar("T")


class ForgeError(L4Exit):
    """A forge call failed. The message never carries the token (`status` is the HTTP status, when there was one)."""

    def __init__(self, message: str, *, status: int | None = None, code: ExitCode = ExitCode.INTERNAL_ERROR) -> None:
        super().__init__(code, message)
        self.status = status


class ForgeAuthError(ForgeError):
    """401 or 403: the token is wrong, expired or lacks a scope. An environment problem, so exit 3."""

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message, status=status, code=ExitCode.DOCTOR_FAILED)


class ForgeNotFound(ForgeError):
    pass


class ForgeRateLimited(ForgeError):
    pass


class AmbiguousWrite(ForgeError):
    """A POST that may or may not have landed: the response was lost (a read timeout, a dropped connection) or the
    server answered 5xx after it may have acted. Only the caller knows how to read the effect back (HB-12)."""


# a lost response: the request was sent, so the effect may exist. A connect error or a 429 provably did nothing.
AMBIGUOUS_ERRORS = (
    httpx.ReadTimeout, httpx.ReadError, httpx.WriteTimeout, httpx.WriteError, httpx.RemoteProtocolError,
    httpx.CloseError,
)  # fmt: skip


def post_once(post: Callable[[], T], find: Callable[[], T | None], pause: Callable[[], None]) -> T:
    """A POST that creates something, retried the safe way: blindly only when it cannot have landed (the caller's
    `_request` does that for a connect error or a 429); after a lost response `find` reads the effect back first, and
    only a clean read that finds nothing allows a second POST. A second lost response is an error, after one more
    read."""
    try:
        return post()
    except AmbiguousWrite:
        if (found := find()) is not None:
            return found
    pause()
    try:
        return post()
    except AmbiguousWrite as exc:
        if (found := find()) is not None:
            return found
        raise ForgeError(str(exc), status=exc.status) from None


class ForgeUnavailable(Exception):
    """No forge can be used for this run (no token, a forge other than GitLab, `forge.type: local`). The hooks
    skip with a warning instead of failing: the unit branch and its ledger are the truth, the MR is a mirror."""


@dataclass(frozen=True)
class PullRequest:
    number: int
    url: str
    head_branch: str
    base_branch: str
    title: str  # without the `Draft: ` prefix
    draft: bool
    state: Literal["open", "merged", "closed"]
    labels: tuple[str, ...]
    merge_commit_sha: str | None = None  # of a merged MR, when the merge method made a commit
    head_sha: str | None = None  # the head commit of the source branch as the forge shows it (None: not reported)
    body: str | None = None  # the description as the forge holds it (None: not reported)


PrState = Literal["open", "merged", "closed", "all"]


@dataclass(frozen=True)
class MergeCall:
    """The answer of `Forge.merge_pr` (squash-and-delete D2): `merged` (`sha` is the commit on the target), `head_moved`
    (the pull request head is no longer the `sha` the call pinned: nothing merged) or `refused` (the forge will not
    squash-merge it: `detail` carries its message, redacted). Any other failure raises `ForgeError`."""

    status: Literal["merged", "head_moved", "refused"]
    sha: str | None = None
    detail: str = ""


@dataclass(frozen=True)
class LabelEvent:
    """One entry of a merge request's label history, attributed by the forge itself (L4-SEC-004, M1.11): `user_id` is
    who added or removed the label, as the forge records it (not a text anyone can write into a commit)."""

    id: int
    label: str
    action: Literal["add", "remove"]
    user_id: int | None
    created_at: str = ""


# What a CI job's status is called here: GitLab's own words. GitHub's check runs are mapped onto them (`github.py`).
UNFINISHED = frozenset({"created", "waiting_for_resource", "preparing", "pending", "running", "scheduled"})
MAX_TAIL_LINES = 40
MAX_TAIL_CHARS = 3000
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")


@dataclass(frozen=True)
class JobResult:
    """One CI job of the project's own pipelines (forge-and-ci 1.1, M1.9 decision 8)."""

    name: str
    stage: str
    status: str  # a GitLab job status: success, failed, running, pending, canceled, skipped, manual, ...
    allow_failure: bool
    pipeline_id: int | str | None
    job_id: int | str | None
    web_url: str


@dataclass(frozen=True)
class JobLog:
    """The end of a job's log, and the command the job's `step_script` ran last (M1.10 decision 1): `step` is None when
    the forge cannot say (a trace without sections, GitHub, no log)."""

    tail: str = ""
    step: str | None = None


def strip_ansi(text: str) -> str:
    """`text` without ANSI escape sequences."""
    return _ANSI.sub("", text)


def clip_log(text: str, max_lines: int = MAX_TAIL_LINES, max_chars: int = MAX_TAIL_CHARS) -> str:
    """The end of a job log as plain text: ANSI escapes and carriage returns gone, the last `max_lines` lines, and no
    more than `max_chars` characters (the end is kept: the failing assertion is there)."""
    plain = _ANSI.sub("", text).replace("\r\n", "\n").replace("\r", "\n")
    lines = plain.rstrip("\n").split("\n")[-max(max_lines, 1) :]
    clipped = "\n".join(lines)
    return clipped[-max_chars:] if len(clipped) > max_chars else clipped


STICKY_MARKER = "<!-- l4:sticky -->"


class Forge(Protocol):
    def project_url(self) -> str: ...

    def ensure_labels(self, names: Sequence[str]) -> None: ...

    def find_pr(self, head_branch: str) -> PullRequest | None: ...

    def get_pr(self, number: int) -> PullRequest: ...

    def list_prs(self, head_prefix: str, state: PrState = "all") -> list[PullRequest]:
        """The MRs whose source branch starts with `head_prefix`, of the given state, newest first."""

    def create_pr(self, head: str, base: str, title: str, body: str, draft: bool = True) -> PullRequest: ...

    def update_pr(
        self, number: int, *, title: str | None = None, body: str | None = None, draft: bool | None = None
    ) -> PullRequest: ...

    def set_managed_labels(self, number: int, labels: Sequence[str], prefix: str) -> PullRequest: ...

    def upsert_sticky_note(self, number: int, body: str) -> None:
        """The one note of this harness on the merge request, found by `STICKY_MARKER`: created, or rewritten in
        place; no write when it already says `body`."""

    def list_pipeline_jobs(self, sha: str, *, settled: bool = False) -> list[JobResult]:
        """The jobs of every pipeline of the project that ran for `sha`, newest pipeline first, one job per name (the
        newest pipeline's, so a rerun replaces the attempt it retried). `settled`: the newest *finished* attempt of a
        name instead, and its newest unfinished one only when none finished (the base head's comparison: a pipeline
        still running there, such as the one the sweep runs in, does not hide an earlier result). Reads only."""

    def job_log_tail(self, job_id: int | str, max_lines: int = MAX_TAIL_LINES) -> str:
        """The end of a job's log (`clip_log`): plain text, at most `max_lines` lines. '' when it cannot be read."""

    def job_log(self, job_id: int | str, max_lines: int = MAX_TAIL_LINES) -> JobLog:
        """`job_log_tail` and the last `$ ` command of the job's `step_script`, from one read of the log."""

    def label_events(self, number: int) -> list[LabelEvent]:
        """The label history of a merge request, oldest first; `[]` when the forge cannot say (fail closed: the
        `l4:resume` label is then never honoured)."""

    def member_access(self, user_id: int) -> int | None:
        """The project access level of a user (GitLab's scale: 30 Developer, 40 Maintainer, 50 Owner); None for a
        user who is not a member or when the forge cannot say."""

    def own_user_id(self) -> int | None:
        """The user the token acts as (the harness's own bot), None when the forge cannot say."""

    def dispatch_continuation(self, ref: str) -> "Continuation":
        """Start one more run of the harness's CI on `ref` for units a run left at its soft deadline (github-parity
        L4-GHP-004): `dispatched`, `already_queued` (one is waiting: nothing sent) or `unsupported`."""

    def start_run(self, ref: str) -> "StartRun":
        """Start the harness's CI on `ref` for an operator command (L4-OPS-002): `started`, `already_queued` (a run
        waits: nothing sent), `refused` (the token may not start one: 401 or 403) or `unsupported` (the forge or the
        project cannot). A refusal is an answer, never an exception; any other failure raises `ForgeError`."""

    def close_pr(self, number: int, comment: str) -> PullRequest:
        """Post `comment` on the pull request, then close it without a merge (L4-OPS-004 step 6). One that is no
        longer open is left as it is: no comment, no write. Returns the pull request as the forge now has it; its
        `state` (`open`, `closed` or `merged`) is also what `get_pr` says, so there is no separate state call."""

    def merge_pr(self, number: int, *, sha: str, title: str, message: str) -> MergeCall:
        """Squash-merge the pull request through the forge's own merge call, pinned to the head `sha` (L4-YOLO-032): the
        forge refuses with `head_moved` when the head is not `sha`. `title` and `message` are the squash commit's. The
        call has no guard on the target tip; the caller compares the landed commit with what it read."""


Platform = Literal["gitlab", "github", "local"]
Continuation = Literal["dispatched", "already_queued", "unsupported"]
StartRun = Literal["started", "already_queued", "refused", "unsupported"]
GITHUB_HOSTS = frozenset({"github.com", "www.github.com"})
GIT_USERNAMES = {"gitlab": "oauth2", "github": "x-access-token"}  # what git sends with the token as the password
_SCP_URL = re.compile(r"^(?:[^@/\s]+@)?(?P<host>[A-Za-z0-9.-]+):(?P<path>[^/\s][^\s]*)$")


@dataclass(frozen=True)
class RemoteUrl:
    host: str
    path: str  # `owner/name`, or `group/sub/project`: without a trailing `.git` or slash


def parse_remote_url(url: str) -> RemoteUrl | None:
    """The host and project path of an https, ssh or scp-style (`git@host:owner/name.git`) remote URL; None for a
    local path or anything without both. Userinfo is dropped, so a token embedded in the URL goes no further."""
    text = url.strip()
    parts = urlsplit(text)
    if parts.scheme in ("http", "https", "ssh", "git"):
        host, path = parts.hostname or "", parts.path
    elif "://" not in text and (match := _SCP_URL.match(text)):
        host, path = match.group("host"), match.group("path")
    else:
        return None
    path = path.strip("/").removesuffix(".git").strip("/")
    return RemoteUrl(host.lower(), path) if host and "/" in path else None


def forge_platform(cfg: L4Config, environ: Mapping[str, str], origin_url: str | None = None) -> Platform:
    """`forge.type`, then `ci.platform`, then the CI variables, then the host of `origin`; GitLab when nothing says
    (the M0 behaviour). `ci.platform: local` is a development setting for the checks, not a forge: only an explicit
    `forge.type: local` selects the in-memory forge."""
    if cfg.forge.type != "auto":
        return cfg.forge.type
    if cfg.ci.platform not in ("auto", "local"):
        return cfg.ci.platform
    if environ.get("GITLAB_CI") == "true":
        return "gitlab"
    if environ.get("GITHUB_ACTIONS") == "true":
        return "github"
    remote = parse_remote_url(origin_url or "")
    return "github" if remote is not None and remote.host in GITHUB_HOSTS else "gitlab"


def forge_wanted(cfg: L4Config, environ: Mapping[str, str] | None = None) -> bool:
    """True when this run's forge is GitLab (the GitLab-only checks and workarounds ask this)."""
    return forge_platform(cfg, environ or {}) == "gitlab"


def _in_ci(platform: Platform, environ: Mapping[str, str]) -> bool:
    variable = {"gitlab": "GITLAB_CI", "github": "GITHUB_ACTIONS"}.get(platform)
    return variable is not None and environ.get(variable) == "true"


def require_token_in_ci(cfg: L4Config, environ: Mapping[str, str]) -> None:
    """A job without the forge token cannot push or open its pull request: exit 3 before the lease, a worktree or any
    agent. Outside CI the same gap only skips the forge hooks (`l4.archive.forge_hook`)."""
    platform = forge_platform(cfg, environ)
    if not _in_ci(platform, environ) or environ.get(cfg.forge.token_env):
        return
    if platform == "github":
        raise L4Exit(
            ExitCode.DOCTOR_FAILED,
            f"{cfg.forge.token_env} is not set: a GitHub job needs a token that can push and open pull requests "
            "(contents: write, pull-requests: write); map a repository secret to it in the workflow's `env`",
        )
    from l4.forge.pushurl import runner_rewrites_urls

    why = (
        "; without it every push carries the job token the runner writes into the checkout (an insteadOf rule), "
        'and GitLab answers 403 "You are not allowed to push code to this project"'
        if runner_rewrites_urls(environ)
        else ""
    )
    raise L4Exit(
        ExitCode.DOCTOR_FAILED,
        f"{cfg.forge.token_env} is not set: a GitLab job needs the project access token "
        f"(api and write_repository scopes) as a masked CI/CD variable{why}",
    )


def fetch_auth_config(
    cfg: L4Config, environ: Mapping[str, str], origin_url: str | None = None
) -> tuple[tuple[str, str], ...]:
    """The credential helper for `git fetch` of the origin; none without a forge token (a public or ssh remote) and
    none for a local forge. `origin_url` names the platform outside CI (L4-OPS-011)."""
    platform = forge_platform(cfg, environ, origin_url)
    if platform not in GIT_USERNAMES or not environ.get(cfg.forge.token_env):
        return ()
    from l4.forge.gitlab import git_auth_config

    return git_auth_config(cfg.forge.token_env, username=GIT_USERNAMES[platform])


def _gitlab_target(cfg: L4Config, environ: Mapping[str, str], origin_url: str | None = None) -> tuple[str, str]:
    """API URL and project: the CI variables inside CI, `forge.gitlab` otherwise, and each one still missing from the
    `origin` remote (`https://<host>/api/v4`, the path without `.git`: L4-OPS-011); a gap is a config error (exit 2)."""
    in_ci = environ.get("GITLAB_CI") == "true"
    remote = parse_remote_url(origin_url or "")
    api_url = (environ.get("CI_API_V4_URL") if in_ci else None) or cfg.forge.gitlab.api_url
    project = (environ.get("CI_PROJECT_ID") if in_ci else None) or cfg.forge.gitlab.project
    if remote is not None:
        api_url = api_url or f"https://{remote.host}/api/v4"
        project = project or remote.path
    if not api_url or not project:
        raise L4Exit(
            ExitCode.USAGE_ERROR,
            "forge.gitlab.api_url and forge.gitlab.project must be set for a run outside GitLab CI "
            "(or the origin remote must name the project)",
        )
    return api_url, project


def _github_target(environ: Mapping[str, str], origin_url: str | None) -> tuple[str, str | None]:
    """`owner/name` and the API URL (None: github.com). Actions sets both variables; elsewhere `GITHUB_REPOSITORY`
    or the `origin` URL names the repository, and an Enterprise host gets `https://<host>/api/v3`."""
    remote = parse_remote_url(origin_url or "")
    repo = environ.get("GITHUB_REPOSITORY") or (remote.path if remote else "")
    if not repo:
        raise L4Exit(
            ExitCode.USAGE_ERROR,
            "the GitHub repository is unknown: outside Actions set GITHUB_REPOSITORY=owner/name (Actions sets it)",
        )
    api = environ.get("GITHUB_API_URL")
    if not api and remote is not None and remote.host not in GITHUB_HOSTS:
        api = f"https://{remote.host}/api/v3"
    return repo, api


def require_forge_target(cfg: L4Config, environ: Mapping[str, str], origin_url: str | None = None) -> None:
    """With a token set, the forge needs a target: say so before the lease, a worktree or the sandbox self-test. The
    `origin` remote counts as a target (L4-OPS-011, SCN-OPS-18)."""
    platform = forge_platform(cfg, environ, origin_url)
    if not environ.get(cfg.forge.token_env):
        return
    if platform == "gitlab":
        _gitlab_target(cfg, environ, origin_url)
    elif platform == "github":
        _github_target(environ, origin_url)


def make_forge(
    cfg: L4Config,
    environ: Mapping[str, str],
    *,
    transport: httpx.BaseTransport | None = None,
    origin_url: str | None = None,
    repo: Path | None = None,
) -> Forge:
    """The forge of this run (`forge_platform`); `ForgeUnavailable` when a real forge has no token. `repo`: where to
    read the `origin` remote from when the caller has not read it (L4-OPS-011); `origin_url` wins."""
    if origin_url is None and repo is not None:
        from l4.forge.urls import origin_url as read_origin_url

        origin_url = read_origin_url(repo, environ)
    platform = forge_platform(cfg, environ, origin_url)
    if platform == "local":
        from l4.forge.local import LocalForge

        return LocalForge()
    token = environ.get(cfg.forge.token_env)
    if not token:
        raise ForgeUnavailable(f"{cfg.forge.token_env} is not set")
    try:
        if platform == "github":
            from l4.forge.github import DEFAULT_API, GitHubForge

            slug, api = _github_target(environ, origin_url)
            return GitHubForge(slug, token, api_url=api or DEFAULT_API, transport=transport)
        from l4.forge.gitlab import GitLabForge

        api_url, project = _gitlab_target(cfg, environ, origin_url)
        return GitLabForge(api_url, project, token, transport=transport)
    except ValueError as exc:
        raise L4Exit(ExitCode.USAGE_ERROR, str(exc)) from None


__all__ = [
    "MAX_TAIL_CHARS", "MAX_TAIL_LINES", "STICKY_MARKER", "UNFINISHED", "Forge", "ForgeAuthError", "ForgeError",
    "ForgeNotFound", "ForgeRateLimited", "ForgeUnavailable", "JobResult", "LabelEvent", "Platform", "PrState",
    "PullRequest", "RemoteUrl", "StartRun", "clip_log", "fetch_auth_config", "forge_platform", "forge_wanted",
    "make_forge", "parse_remote_url", "require_forge_target", "require_token_in_ci",
]  # fmt: skip
