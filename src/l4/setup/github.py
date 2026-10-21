"""`l4 setup github` (github-parity 4.1, L4-GHP-011): the forge side of adopting a repository on GitHub, in one command.

Checks the token has admin on the repository, sets the workflow permissions, creates the environment
`ci.github_environment` with its deployment branch policies, seals each `--secret` with the environment's public key,
sets the repository variable `L4_SELF_PROVISION`, creates the labels, and dispatches the `l4` workflow. Idempotent: a
second run without `--secret` sends only reads (and the dispatch). Every row names a thing and what happened to it,
never a value; all output goes through a redactor that holds the token and every secret. Only first pages of the (small)
listings are read and no `Link` header is followed: behind a credential broker those point at another host.
"""

import base64
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import quote

import click
import httpx
from nacl import public

from l4.ci.github import WORKFLOW_RELPATH
from l4.config.redaction import load_app_config
from l4.context import AppContext
from l4.exitcodes import ExitCode, L4Exit
from l4.forge.base import GITHUB_HOSTS, ForgeError, parse_remote_url
from l4.forge.github import API_VERSION, DEFAULT_API, TIMEOUT_S, GitHubForge, _checked_api_url
from l4.init.action import read_pin
from l4.redact import Redactor
from l4.state.lifecycle import Phase
from l4.vcs.git import Git, GitError

SELF_PROVISION = "L4_SELF_PROVISION"
WORKFLOW_FILE = WORKFLOW_RELPATH.rsplit("/", 1)[-1]
WANTED_PERMISSIONS = {"default_workflow_permissions": "write", "can_approve_pull_request_reviews": True}
WANTED_POLICY = {"protected_branches": False, "custom_branch_policies": True}
Status = Literal["KEPT", "SET", "CREATED", "FAILED"]
_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_REPO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9._-]+$")


class GhError(Exception):
    """An HTTP failure; the message never holds the token."""

    def __init__(self, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.status = status


class GhApi:
    """A small GitHub REST client: the token travels only in the header of requests to the configured base (https, or
    http on loopback), redirects are not followed and every message has the token cut out."""

    def __init__(self, api_url: str, token: str, transport: httpx.BaseTransport | None = None) -> None:
        self.base = _checked_api_url(api_url)
        self._token = token
        self._transport = transport

    def scrub(self, text: str) -> str:
        return text.replace(self._token, "[REDACTED:token]") if self._token else text

    def request(
        self, method: str, path: str, *, json: Any = None, params: dict[str, Any] | None = None
    ) -> httpx.Response:
        """The response of a 2xx answer; a 404 comes back as a response too (callers ask `status_code`)."""
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
        }
        label = f"GitHub {method} {path}"
        try:
            with httpx.Client(transport=self._transport, timeout=TIMEOUT_S, follow_redirects=False) as client:
                response = client.request(method, f"{self.base}{path}", params=params, json=json, headers=headers)
        except httpx.TransportError as exc:
            raise GhError(self.scrub(f"{label}: {type(exc).__name__}: {exc}")) from None
        if response.is_success or (response.status_code == 404 and method == "GET"):
            return response
        detail = ""
        try:
            body = response.json()
            text = body.get("message") if isinstance(body, dict) else None
            detail = f": {' '.join(str(text).split())[:200]}" if text else ""
        except ValueError:
            pass
        raise GhError(self.scrub(f"{label}: HTTP {response.status_code}{detail}"), response.status_code)

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any | None:
        """The JSON body, or None for a 404."""
        response = self.request("GET", path, params=params)
        return None if response.status_code == 404 else response.json()


def resolve_target(app: AppContext, repo: str | None, api_url: str | None) -> tuple[str, str]:
    """`owner/name` and the API base: the arguments, then the `origin` URL (an Enterprise host gets /api/v3)."""
    remote = None
    if repo is None or api_url is None:
        try:
            done = Git(app.repo, environ=app.environ).run("remote", "get-url", "origin", check=False)
            remote = parse_remote_url(done.stdout.strip()) if done.returncode == 0 else None
        except (L4Exit, GitError):
            remote = None
    repo = repo or (remote.path if remote else "")
    if not _REPO.match(repo):
        raise _usage("cannot tell the repository: pass --repo owner/name or add an `origin` on GitHub")
    if api_url is None:
        api_url = app.environ.get("GITHUB_API_URL") or (
            f"https://{remote.host}/api/v3" if remote and remote.host not in GITHUB_HOSTS else DEFAULT_API
        )
    try:
        _checked_api_url(api_url)
    except ValueError as exc:
        raise _usage(f"--api-url: {exc}") from None
    return repo, api_url


def _usage(message: str) -> L4Exit:
    return L4Exit(ExitCode.USAGE_ERROR, f"setup github: {message}")


def parse_secrets(pairs: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    parsed: list[tuple[str, str]] = []
    for item in pairs:
        name, sep, source = item.partition("=")
        if not sep or not _NAME.match(name) or not _NAME.match(source):
            raise _usage(f"--secret expects NAME=ENVVAR (two variable names), got {name or item!r}")
        parsed.append((name, source))
    if len({n for n, _ in parsed}) != len(parsed):
        raise _usage("--secret names a secret twice")
    return tuple(parsed)


class Emitter:
    def __init__(self, redactor: Redactor, dry_run: bool) -> None:
        self.redactor, self.dry_run = redactor, dry_run
        self.counts: dict[str, int] = dict.fromkeys(("KEPT", "SET", "CREATED", "FAILED"), 0)

    def row(self, status: Status, subject: str, detail: str = "") -> None:
        self.counts[status] += 1
        if self.dry_run and status in ("SET", "CREATED"):
            detail = f"{detail} (dry-run: would be written)".strip()
        self.raw(f"{status:<7} {subject}" + (f" {detail}" if detail else ""))

    def raw(self, line: str) -> None:
        click.echo(self.redactor.redact_text(line))

    @property
    def failed(self) -> bool:
        return self.counts["FAILED"] > 0

    def summary(self, code: ExitCode) -> None:
        c = self.counts
        done = f"{c['CREATED']} created, {c['SET']} set, {c['KEPT']} kept, {c['FAILED']} failed"
        click.echo(f"summary: {done} -> exit {int(code)}")


@dataclass(frozen=True)
class Options:
    repo: str
    environment: str | None
    base: str
    prefix: str
    labels: tuple[str, ...]
    self_provision: bool
    secrets: tuple[tuple[str, str], ...]
    dry_run: bool


def managed_labels(prefix: str) -> tuple[str, ...]:
    """Every label the harness sets on a pull request: one per phase, `needs-answers`, `needs-person` (the delegate
    escalated a question, L4-CLR-004), and the operator signals `resume`, `retry` and `restart` (L4-OPS-003)."""
    signals = (f"{prefix}{name}" for name in ("resume", "retry", "restart"))
    phases = (f"{prefix}{phase.value}" for phase in Phase)
    return (*phases, f"{prefix}needs-answers", f"{prefix}needs-person", *signals)


def seal(public_key: str, value: str) -> str:
    box = public.SealedBox(public.PublicKey(base64.b64decode(public_key)))
    return base64.b64encode(box.encrypt(value.encode("utf-8"))).decode("ascii")


class Setup:
    def __init__(
        self, api: GhApi, forge: GitHubForge, options: Options, emit: Emitter, environ: Mapping[str, str]
    ) -> None:
        self.api, self.forge, self.o, self.emit, self.environ = api, forge, options, emit, environ
        self.root = f"/repos/{options.repo}"
        self.env_exists = False
        self.default_branch = options.base  # read from the repository in `admin()`

    def write(self, method: str, path: str, body: Any) -> None:
        if not self.o.dry_run:
            self.api.request(method, f"{self.root}{path}", json=body)

    def admin(self) -> bool:
        repo = self.api.get(self.root)
        if repo is None:
            self.emit.row("FAILED", f"repository {self.o.repo}", "not found, or the token cannot see it")
            return False
        if not (repo.get("permissions") or {}).get("admin"):
            self.emit.row(
                "FAILED", f"repository {self.o.repo}",
                "the token has no admin permission on it: use a token of an administrator (repo scope or "
                "Administration: write, Environments: write, Variables and Secrets: write)",
            )  # fmt: skip
            return False
        self.default_branch = str(repo.get("default_branch") or self.o.base)
        self.emit.raw(f"OK      repository {self.o.repo} the token has admin permission")  # a check, not a state row
        return True

    def workflow_permissions(self) -> None:
        path = "/actions/permissions/workflow"
        have = self.api.get(f"{self.root}{path}") or {}
        if all(have.get(k) == v for k, v in WANTED_PERMISSIONS.items()):
            self.emit.row("KEPT", "workflow permissions", "write, pull requests may be created")
            return
        self.write("PUT", path, WANTED_PERMISSIONS)
        self.emit.row("SET", "workflow permissions", "write, pull requests may be created")

    def environment(self) -> None:
        env = self.o.environment
        if env is None:
            self.emit.row("KEPT", "environment", "ci.github_environment is null: the workflow runs in none")
            return
        path = f"/environments/{quote(env, safe='')}"
        have = self.api.get(f"{self.root}{path}")
        self.env_exists = have is not None
        if have is None:
            self.write("PUT", path, {"deployment_branch_policy": WANTED_POLICY})
            self.emit.row("CREATED", f"environment {env}", "with custom deployment branch policies")
        elif have.get("deployment_branch_policy") != WANTED_POLICY:
            self.write("PUT", path, {"deployment_branch_policy": WANTED_POLICY})
            self.emit.row("SET", f"environment {env}", "custom deployment branch policies")
        else:
            self.emit.row("KEPT", f"environment {env}")
        found = self.api.get(f"{self.root}{path}/deployment-branch-policies", {"per_page": 100}) if have else None
        names = {str(p.get("name")) for p in (found or {}).get("branch_policies", [])}
        # the default branch too when it is not the base: schedule and dispatch run from it (L4-ADO-002)
        wanted = (self.o.base, f"{self.o.prefix}*", f"{self.o.prefix}**/*", self.default_branch)
        for pattern in dict.fromkeys(wanted):
            if pattern in names:
                self.emit.row("KEPT", f"branch policy {pattern}", f"of environment {env}")
                continue
            self.write("POST", f"{path}/deployment-branch-policies", {"name": pattern, "type": "branch"})
            self.emit.row("CREATED", f"branch policy {pattern}", f"of environment {env}")

    def workflow_text(self, ref: str) -> str | None:
        """The text of `.github/workflows/l4.yml` on `ref` (the contents API), or None when the file is not there."""
        found = self.api.get(f"{self.root}/contents/{WORKFLOW_RELPATH}", {"ref": ref})  # a 403: see the caller
        if not isinstance(found, dict) or found.get("encoding") != "base64":
            return None
        return base64.b64decode(str(found.get("content", ""))).decode("utf-8", errors="replace")

    def default_branch_workflow(self) -> None:
        """GitHub runs schedule and dispatch only from the default branch: when it is not the base, its copy of the
        workflow must exist (L4-ADO-002, design D2). Nothing is read when the base is the default branch."""
        default = self.default_branch
        if default == self.o.base:
            return
        try:
            text = self.workflow_text(default)
        except GhError as exc:
            if exc.status != 403:
                raise
            self.emit.row(
                "FAILED", f"workflow {WORKFLOW_RELPATH} on {default}",
                "the token cannot read the repository's contents (Contents: read)",
            )  # fmt: skip
            return
        if text is None:
            self.emit.row(
                "FAILED", f"workflow {WORKFLOW_RELPATH} on {default}",
                f"{default} has no {WORKFLOW_RELPATH}: GitHub runs schedule and dispatch only from the default "
                "branch; merge a pull request that adds it",
            )  # fmt: skip
            return
        base_text = self.workflow_text(self.o.base)
        pin_there, pin_base = read_pin(text), read_pin(base_text or "")
        have = pin_there.effective if pin_there else None
        want = pin_base.effective if pin_base else None
        if want and have != want:
            self.emit.row(
                "FAILED", f"workflow {WORKFLOW_RELPATH} on {default}",
                f"pins {have or 'no commit'} but {self.o.base} pins {want}: a schedule runs {default}'s copy; "
                f"copy {self.o.base}'s file to {default}",
            )  # fmt: skip
            return
        self.emit.row("KEPT", f"workflow {WORKFLOW_RELPATH} on {default}", "present")

    def secrets(self) -> None:
        env = self.o.environment
        for name, source in self.o.secrets:
            value = self.environ.get(source, "")
            if env is None:
                self.emit.row(
                    "FAILED", f"secret {name}", "ci.github_environment is null: there is no environment for it"
                )
                continue
            if not value:
                self.emit.row("FAILED", f"secret {name}", f"the environment variable {source} is empty or not set")
                continue
            path = f"/environments/{quote(env, safe='')}/secrets"
            if self.o.dry_run and not self.env_exists:
                self.emit.row("SET", f"secret {name}", f"of environment {env}")
                continue
            key = self.api.get(f"{self.root}{path}/public-key")
            if not isinstance(key, dict) or "key" not in key or "key_id" not in key:
                self.emit.row("FAILED", f"secret {name}", f"environment {env} has no public key")
                continue
            self.write(
                "PUT", f"{path}/{name}", {"encrypted_value": seal(str(key["key"]), value), "key_id": key["key_id"]}
            )
            self.emit.row("SET", f"secret {name}", f"of environment {env}, sealed with its public key")

    def self_provision(self) -> None:
        if not self.o.self_provision:
            return
        have = self.api.get(f"{self.root}/actions/variables/{SELF_PROVISION}")
        if have is None:
            self.write("POST", "/actions/variables", {"name": SELF_PROVISION, "value": "true"})
            self.emit.row("CREATED", f"variable {SELF_PROVISION}", "true (ci.runner_tags is empty)")
        elif have.get("value") != "true":
            self.write("PATCH", f"/actions/variables/{SELF_PROVISION}", {"name": SELF_PROVISION, "value": "true"})
            self.emit.row("SET", f"variable {SELF_PROVISION}", "true (ci.runner_tags is empty)")
        else:
            self.emit.row("KEPT", f"variable {SELF_PROVISION}", "true")

    def labels(self) -> None:
        found = self.api.get(f"{self.root}/labels", {"per_page": 100}) or []
        have = {str(item.get("name")) for item in found}
        missing = [name for name in self.o.labels if name not in have]
        if not missing:
            self.emit.row("KEPT", "labels", f"{len(self.o.labels)} present")
            return
        if not self.o.dry_run:
            self.forge.ensure_labels(missing)
        self.emit.row("CREATED", "labels", ", ".join(missing))

    def newest_run(self) -> int:
        body = self.api.get(
            f"{self.root}/actions/workflows/{WORKFLOW_FILE}/runs", {"branch": self.o.base, "per_page": 1}
        )
        runs = (body or {}).get("workflow_runs") or []
        return int(runs[0]["id"]) if runs else 0

    def dispatch(self) -> int:
        """The id of the newest run before the dispatch (0: none): the run to follow is the first one after it."""
        before = self.newest_run()
        self.api.request("POST", f"{self.root}/actions/workflows/{WORKFLOW_FILE}/dispatches", json={"ref": self.o.base})
        self.emit.raw(f"DISPATCHED {WORKFLOW_FILE} on {self.o.base}")
        return before

    def run_steps(self) -> int | None:
        """Runs the steps; the newest run id before the dispatch, or None when nothing was dispatched."""
        if not self.admin():
            return None
        self.workflow_permissions()
        self.environment()
        self.default_branch_workflow()
        self.secrets()
        self.self_provision()
        self.labels()
        return None if self.o.dry_run or self.emit.failed else self.dispatch()


def run_setup_github(
    app: AppContext,
    *,
    repo: str | None = None,
    api_url: str | None = None,
    token_env: str = "GH_TOKEN",
    secret: tuple[str, ...] = (),
    watch: bool = False,
    dry_run: bool = False,
    tail: int = 60,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> ExitCode:
    """`l4 setup github`. Exit 0; 3 when a row is FAILED (no admin, a secret that cannot be read or written); 2 for
    usage (no token, a bad repository or URL); 1 for an HTTP error (the rows printed before it say what was done)."""
    secrets = parse_secrets(tuple(secret))
    token = app.environ.get(token_env, "")
    if not token:
        raise _usage(f"the environment variable {token_env} is empty or not set: it holds a token with admin rights")
    app, cfg = load_app_config(app)
    name, base_url = resolve_target(app, repo, api_url)
    app.redactor.adopt(
        Redactor({"setup:token": token, **{f"setup:{n}": app.environ[s] for n, s in secrets if app.environ.get(s)}})
    )
    options = Options(
        name, cfg.ci.github_environment, cfg.forge.base_branch, cfg.forge.branch_prefix,
        managed_labels(cfg.forge.labels_prefix), not cfg.ci.runner_tags, secrets, dry_run,
    )  # fmt: skip
    emit = Emitter(app.redactor, dry_run)
    api = GhApi(base_url, token, transport)
    forge = GitHubForge(name, token, api_url=base_url, transport=transport)
    setup = Setup(api, forge, options, emit, app.environ)
    try:
        before = setup.run_steps()
        if before is not None and watch:
            from l4.ci.watch import watch_github_run

            result = watch_github_run(
                api, forge, name, options.base, after=before, say=emit.raw, tail=tail, sleep=sleep, clock=clock
            )
            if result.exit_code:
                emit.row("FAILED", f"workflow run {result.run_id}", result.conclusion)
    except (GhError, ForgeError) as exc:
        click.echo(app.redactor.redact_text(f"ERROR {exc}"))
        emit.summary(ExitCode.INTERNAL_ERROR)
        return ExitCode.INTERNAL_ERROR
    code = ExitCode.DOCTOR_FAILED if emit.failed else ExitCode.OK
    emit.summary(code)
    return code
