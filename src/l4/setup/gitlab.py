"""`l4 setup gitlab` (M1.8 A10, L4-INS-006): the forge side of adoption, in the CLI instead of three scripts.

Reads the project, checks the runner the `l4` job would take, checks the include on the base branch, makes sure the
`l4-bot` access token and the masked CI/CD variable `L4_FORGE_TOKEN` (environment scope `l4`) exist, sets `--secret`
variables, makes sure the `l4 sweep` schedule exists and triggers one pipeline that runs the adoption check on the
runner. Idempotent: a second run with the same arguments sends only GETs (and the check pipeline). Every line it prints
names a thing and what happened to it, never a value; all output goes through a redactor that holds the maintainer's
credential, the bot token and every secret.
"""

import re
import shlex
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Literal
from urllib.parse import quote, unquote

import click
import httpx

from l4.ci.gitlab_jobs import GITLAB_CI_RELPATH, parse_gitlab_ci
from l4.ci.gitlab_rules import Pipeline, empty_pipeline_findings, jobs_on
from l4.ci.render import TEMPLATE_RELPATH
from l4.ci.watch import watch_pipeline
from l4.config.redaction import load_app_config
from l4.context import AppContext
from l4.exitcodes import ExitCode, L4Exit
from l4.forge.base import parse_remote_url
from l4.forge.gitlab_admin import AdminApi, AdminError, RefreshFailed
from l4.redact import Redactor
from l4.vcs.git import Git, GitError

BOT_NAME = "l4-bot"
BOT_SCOPES = ("api", "write_repository")
BOT_LEVEL = 30  # Developer
BOT_DAYS = 365
MAX_RUNNER_DETAILS = 5  # runners whose tags are read one by one; the others are counted
SCHEDULE_NAME = "l4 sweep"
HARNESS_JOB = "l4"
ADOPTION_VARIABLE = "L4_ADOPTION_CHECK"
READ_BY_L4 = (
    "CI_JOB_TOKEN",
    "CI_API_V4_URL",
    "CI_REPOSITORY_URL",
    "CI_JOB_ID",
    "CI_SERVER_URL",
)  # predefined, read by L4
ENV_SCOPE = "l4"  # the environment of the harness job in the CI template: the project's own jobs never see the token
_ID = re.compile(r"^\d+$")
_BAD_CHARS = re.compile(r"[?#\\%\s@:]")
Status = Literal["OK", "NEW", "SET", "KEPT", "WARN", "FAIL"]
_STATUSES: tuple[Status, ...] = ("OK", "NEW", "SET", "KEPT", "WARN", "FAIL")
TRANSPORT: httpx.BaseTransport | None = None  # tests put a fake server here when the command runs through the CLI


def project_path(given: str) -> str:
    """`--project` as the one path segment the API wants: a numeric id as it is, a path (`group/sub/name`) with its
    slashes encoded exactly once. A `%2F`-encoded path is decoded first; a result that still holds `%` was encoded
    twice and is refused, like every path a project cannot have."""
    text = given.strip()
    if _ID.match(text):
        return text
    text = unquote(text).strip().strip("/").removesuffix(".git")
    segments = text.split("/")
    if not text or not all(segments) or any(s in (".", "..") or _BAD_CHARS.search(s) for s in segments):
        raise L4Exit(
            ExitCode.USAGE_ERROR,
            f"--project: expected a numeric id or a path such as group/name, got {given!r}",
        )
    return "%2F".join(quote(s, safe="") for s in segments)


def derive_api_base(origin_url: str) -> str | None:
    """`https://<host>/api/v4` for the host of `origin` (https, ssh and scp-style URLs; userinfo is dropped)."""
    remote = parse_remote_url(origin_url)
    return f"https://{remote.host}/api/v4" if remote is not None else None


@dataclass(frozen=True)
class SetupOptions:
    pid: str  # `project_path` of --project
    token_env: str  # the variable that carries the bot token (`forge.token_env`)
    runner_tags: tuple[str, ...]
    rotate: bool = False
    revoke_old: bool = False
    secrets: tuple[tuple[str, str], ...] = ()  # (variable name, environment variable to read the value from)
    cron: str = "*/30 * * * *"
    schedule: bool = True
    pipeline: bool = True
    watch: bool = False
    dry_run: bool = False
    verify_base: str = ""
    base_branch: str | None = None  # `forge.base_branch` of the config; None: the project's default branch (L4-OPS-016)
    branch_prefix: str = "l4/"  # `forge.branch_prefix`: the push pipeline of a unit branch is checked too (L4-INS-008)


_MAX_NAMES = 8


def _names(names: Sequence[str]) -> str:
    """Job names, comma-separated: at most eight, then `(+k more)`; `none` when there are none."""
    if not names:
        return "none"
    shown = ", ".join(names[:_MAX_NAMES])
    return shown + (f" (+{len(names) - _MAX_NAMES} more)" if len(names) > _MAX_NAMES else "")


class Emitter:
    """The rows of the run. Every line goes through the redactor (which holds the maintainer's credential, the bot
    token and every secret) before it is printed."""

    def __init__(self, redactor: Redactor) -> None:
        self.redactor = redactor
        self.counts: dict[str, int] = dict.fromkeys(_STATUSES, 0)

    def row(self, status: Status, subject: str, detail: str = "") -> None:
        self.counts[status] += 1
        line = f"{status:<5} {subject}" + (f" {detail}" if detail else "")
        click.echo(self.redactor.redact_text(line))

    def raw(self, line: str) -> None:
        """A line that is not a row (the watcher's progress): redacted like the rows, not counted."""
        click.echo(self.redactor.redact_text(line))

    @property
    def failed(self) -> bool:
        return self.counts["FAIL"] > 0

    def summary(self, code: ExitCode) -> None:
        c = self.counts
        click.echo(
            f"summary: {c['OK']} ok, {c['NEW']} new, {c['SET']} set, {c['KEPT']} kept, {c['WARN']} warn, "
            f"{c['FAIL']} fail -> exit {int(code)}"
        )


_WHO_ELSE = {"public": "anyone", "internal": "every signed-in user of this GitLab"}


def _instance_runner_warning(visibility: str) -> str:
    article = "an" if visibility.startswith(tuple("aeiou")) else "a"
    text = (
        f"is an instance runner on {article} {visibility} project: any project of this GitLab whose jobs carry these "
        "tags can run on it, next to this project's checkout, the l4 job's token and the runner's agent logins"
    )
    if visibility in _WHO_ELSE:
        text += (
            f"; and the project is {visibility}: {_WHO_ELSE[visibility]} can read its code, its merge requests (the "
            "harness's notes too) and, with public pipelines on, its job logs. Prefer a project or group runner"
        )
    return text


def _scope_of(variable: Mapping[str, Any]) -> str:
    return str(variable.get("environment_scope", "*"))


class Setup:
    def __init__(
        self,
        api: AdminApi,
        options: SetupOptions,
        emit: Emitter,
        make_api: Callable[[str, str, str], AdminApi],
        learn: Callable[[str], None],
        secret_values: Mapping[str, str] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.sleep, self.clock = sleep, clock
        self.api, self.o, self.emit, self.make_api, self.learn = api, options, emit, make_api, learn
        self.values = dict(secret_values or {})  # variable name -> value read from the environment
        self.project: dict[str, Any] = {}
        self._variables: list[dict[str, Any]] | None = None
        self.include_found = False  # the base branch's .gitlab-ci.yml includes the harness template
        self.pipeline_id: int | None = None
        self.reactivated: object = None  # the id of the schedule this run switched on (see `watch`)

    @property
    def pid(self) -> str:
        return str(self.project["id"])

    def base_ref(self) -> str | None:
        """The branch the harness job runs on: `forge.base_branch` when the config names one, else the project's default
        branch. The include, the schedule and the check pipeline belong there: with a separate integration branch (a
        delivery plan's `staging`, L4-YOLO-007) the default branch has no harness job."""
        return self.o.base_branch or self.project.get("default_branch") or None

    # --- the project ------------------------------------------------------------------------------------------

    def read_project(self) -> None:
        self.project = self.api.get(f"projects/{self.o.pid}")
        p = self.project
        self.emit.row(
            "OK",
            f"project {p.get('path_with_namespace', self.o.pid)} (id {p['id']})",
            f"{p.get('visibility', '?')}, default branch {p.get('default_branch') or '(none yet)'}",
        )

    # --- the runner the `l4` job would take -------------------------------------------------------------------

    def runners(self) -> None:
        """Runners that carry the configured tags, with their type. The `l4` job stays pending without an online one;
        an instance (shared) runner is shared with every project of the GitLab, whatever this project's visibility, so
        each one the job can take is a WARN (L4-INS-006)."""
        emit, p = self.emit, self.project
        tags = ",".join(self.o.runner_tags)
        try:
            found = self.api.get_paged(f"projects/{self.pid}/runners", {"tag_list": tags} if tags else None)
        except AdminError as exc:
            if exc.status != 403:
                raise
            emit.row(
                "WARN",
                "runners",
                f"cannot list runners ({exc.status}: listing them needs the Maintainer role); check by hand that "
                f"one with the tags [{tags}] is online",
            )
            return
        usable = [r for r in found if r.get("active", True) and (r.get("online") or r.get("status") == "online")]
        label = f"[{tags}]"
        if not usable:
            emit.row(
                "FAIL",
                "runners",
                f"no online runner with the tags {label} is available to this project: the l4 job would stay pending",
            )
            return

        def kind(r: Mapping[str, Any]) -> str:
            return str(r.get("runner_type") or ("instance_type" if r.get("is_shared") else "project_type"))

        own = [r for r in usable if kind(r) != "instance_type"]
        shared = [r for r in usable if kind(r) == "instance_type"]
        shared_on = p.get("shared_runners_enabled", True)
        shown = (*own, *shared)[:MAX_RUNNER_DETAILS]
        tags_of = {r["id"]: self._runner_tags(r["id"]) for r in shown}  # the list endpoint omits `tag_list`

        def named(r: Mapping[str, Any]) -> str:
            return f"; tags: {tags_of[r['id']]}" if r["id"] in tags_of else ""

        for r in own:
            emit.row(
                "OK",
                f"runner #{r['id']} ({kind(r)}, online)",
                f"{r.get('description', '')} with the tags {label}{named(r)}",
            )
        if shared and not own and not shared_on:
            emit.row(
                "FAIL",
                "runners",
                f"only instance runners carry the tags {label}, and shared runners are off for this project: "
                "the l4 job cannot use them",
            )
            return
        for r in shared:
            subject = f"runner #{r['id']} ({kind(r)}, online)"
            if not shared_on:
                emit.row("OK", subject, f"not used: shared runners are off for this project{named(r)}")
                continue
            # the exposure is the runner's, whatever the project's visibility, and GitLab gives a project runner no
            # priority: the l4 job (and its token) can land on any instance runner that carries the tags
            emit.row("WARN", subject, _instance_runner_warning(str(p.get("visibility") or "private")) + named(r))
        if len(usable) > len(shown):
            emit.row("OK", "runners", f"and {len(usable) - len(shown)} more usable runner(s): their tags are not read")

    def _runner_tags(self, runner_id: object) -> str:
        """`tags: agentic, ai, opencode` from `GET runners/:id`; `not readable (<status>)` when the credential may not
        read it (403) or it is gone (404). Reading changes no verdict (M1.10 decision 13)."""
        try:
            detail = self.api.get(f"runners/{int(str(runner_id))}")
        except AdminError as exc:
            if exc.status in (403, 404):
                return f"not readable ({exc.status})"
            raise
        tags = [str(t) for t in detail.get("tag_list") or []]
        untagged = ", runs untagged jobs" if detail.get("run_untagged") else ""
        return (", ".join(tags) or "(none)") + untagged

    # --- the include on the base branch --------------------------------------------------------------------

    def include_check(self) -> None:
        branch = self.base_ref()
        emit = self.emit
        if not branch:
            emit.row("WARN", ".gitlab-ci.yml", "the project has no default branch yet: push your adoption commit first")
            return

        def load(path: str) -> str | None:
            try:
                return self.api.get_text(
                    f"projects/{self.pid}/repository/files/{quote(path, safe='')}/raw", {"ref": branch}
                )
            except AdminError as exc:
                if exc.status == 404:
                    return None
                raise

        text = load(GITLAB_CI_RELPATH)
        if text is None:
            emit.row("WARN", ".gitlab-ci.yml", f"no .gitlab-ci.yml on {branch}: push your adoption commit (git push)")
            return
        found = parse_gitlab_ci(text, load)
        mine = [j for j in found.jobs if j.name != HARNESS_JOB and not j.trigger]
        if TEMPLATE_RELPATH not in found.includes:
            emit.row(
                "WARN",
                f".gitlab-ci.yml on {branch}",
                f"does not include {TEMPLATE_RELPATH}: the l4 job does not exist there yet (push the adoption commit)",
            )
        else:
            self.include_found = True
            default = self.project.get("default_branch") or branch
            on = jobs_on(found, Pipeline("schedule", branch, default))
            unknown = f"; unknown: {_names(on.unknown)}" if on.unknown else ""
            emit.row(
                "OK",
                f".gitlab-ci.yml on {branch}",
                f"includes {TEMPLATE_RELPATH}; the project's own jobs on a scheduled pipeline of {branch}: "
                f"run: {_names(on.run)}; skip: {_names(on.skip)}{unknown}",
            )
        default = self.project.get("default_branch") or branch
        for finding in empty_pipeline_findings(found, branch, default, self.o.branch_prefix):
            emit.row("WARN", "workflow:rules" if finding.kind == "workflow" else "pipeline", finding.text)
        wanted = self.o.runner_tags
        missing = []
        for job in mine:
            tags = found.effective_tags(job)
            if wanted and not any(t.startswith("$") for t in tags) and not all(t in tags for t in wanted):
                missing.append(job.name)
        if missing:
            emit.row(
                "WARN",
                "jobs",
                f"{len(missing)} job(s) lack the runner tags [{','.join(wanted)}]: {', '.join(missing)}; they run on "
                "any runner of the instance (l4 doctor row CI-002)",
            )

    # --- the bot token and L4_FORGE_TOKEN -------------------------------------------------------------------

    def token_and_variable(self) -> None:
        o, emit, api = self.o, self.emit, self.api
        tokens = api.get_paged(f"projects/{self.pid}/access_tokens")
        active = [t for t in tokens if t.get("name") == BOT_NAME and t.get("active") and not t.get("revoked")]
        variables = self.variables()
        mine = next((v for v in variables if v.get("key") == o.token_env and _scope_of(v) == ENV_SCOPE), None)
        if active and mine is not None and not o.rotate:
            t = active[0]
            emit.row("KEPT", f"token {BOT_NAME} id={t['id']}", self._token_facts(t))
            emit.row("KEPT", f"variable {o.token_env}", f"(environment scope {ENV_SCOPE}, masked={mine.get('masked')})")
            self._twin_warning(variables)
            return
        why = "rotating" if o.rotate else ("no active token" if not active else f"{o.token_env} is not set")
        if o.dry_run:
            emit.row("NEW", f"token {BOT_NAME}", f"(dry run: would create it, {why})")
            emit.row("SET", f"variable {o.token_env}", f"(dry run: would set it, environment scope {ENV_SCOPE})")
            return
        created = api.post(
            f"projects/{self.pid}/access_tokens",
            {
                "name": BOT_NAME, "scopes": list(BOT_SCOPES), "access_level": BOT_LEVEL,
                "expires_at": (date.today() + timedelta(days=BOT_DAYS)).isoformat(),
            },
        )  # fmt: skip
        secret = created.pop("token")
        self.learn(secret)
        api.add_secret(secret)
        emit.row("NEW", f"token {BOT_NAME} id={created['id']}", self._token_facts(created))
        body = {
            "value": secret, "masked": True, "protected": False, "raw": True, "environment_scope": ENV_SCOPE,
            "description": f"L4 harness bot token ({BOT_NAME}), created {date.today().isoformat()}",
        }  # fmt: skip
        if mine is not None:
            api.put(self._variable_path(o.token_env), body)
        else:
            api.post(f"projects/{self.pid}/variables", {"key": o.token_env, **body})
        emit.row("SET", f"variable {o.token_env}", f"(environment scope {ENV_SCOPE}, masked, not protected, raw)")
        self._twin_warning(variables)
        verified = self._verify(secret)
        older = [t for t in active if t["id"] != created["id"]]
        if older and not o.rotate:  # the variable was missing: the old value cannot be read back, so it was replaced
            ids = ", ".join(str(t["id"]) for t in older)
            emit.row(
                "WARN",
                f"token {BOT_NAME} id={ids}",
                "an earlier token is still active (its value cannot be read back); revoke it, or use --rotate "
                "--revoke-old next time",
            )
        if o.rotate and not o.revoke_old and older:
            ids = ", ".join(str(t["id"]) for t in older)
            emit.row("WARN", f"token {BOT_NAME} id={ids}", "the older token is still active: --revoke-old revokes it")
        if o.rotate and o.revoke_old and older:
            if not verified:
                emit.row("WARN", f"token {BOT_NAME}", "the older tokens are not revoked: the new one did not verify")
                return
            for t in older:
                api.delete(f"projects/{self.pid}/access_tokens/{t['id']}")
                emit.row("OK", f"revoked token id={t['id']}", "(the older l4-bot token)")

    def variables(self) -> list[dict[str, Any]]:
        """The project's variables, read once. The list carries values: they are compared, never printed."""
        if self._variables is None:
            self._variables = self.api.get_paged(f"projects/{self.pid}/variables")
        return self._variables

    @staticmethod
    def _token_facts(t: Mapping[str, Any]) -> str:
        scopes = ",".join(t.get("scopes", []))
        return f"scopes={scopes} level={t.get('access_level')} expires={t.get('expires_at')}"

    def _variable_path(self, key: str, scope: str = ENV_SCOPE) -> str:
        """One variable of the project: the same key may exist once per environment scope, so the scope selects it."""
        return f"projects/{self.pid}/variables/{quote(key, safe='')}?filter[environment_scope]={quote(scope, safe='')}"

    def _twin_warning(self, variables: list[dict[str, Any]]) -> None:
        if any(v.get("key") == self.o.token_env and _scope_of(v) == "*" for v in variables):
            self.emit.row(
                "WARN",
                f"variable {self.o.token_env}",
                "an unscoped copy (scope *) still exists: every job of the project can read it; delete it once the "
                "scoped one works (not deleted here)",
            )

    def _verify(self, secret: str) -> bool:
        """The new token reads the project through the real API, as the bot user: a token that cannot is a FAIL."""
        verify = self.make_api(self.o.verify_base, secret, "private-token")
        try:
            project = verify.get(f"projects/{self.o.pid}")
        except AdminError as exc:
            self.emit.row("FAIL", "new token", f"cannot read the project as the bot user ({exc})")
            return False
        self.emit.row(
            "OK", "new token", f"can read project {project.get('path_with_namespace', self.o.pid)} as the bot user"
        )
        return True

    # --- --secret NAME=ENV ----------------------------------------------------------------------------------

    def secrets(self) -> None:
        """Each secret becomes a masked, raw, unprotected variable of the `l4` environment (never `*`: the project's own
        jobs run agent-written code). Compared in memory: equal is KEPT, different SET, missing NEW."""
        for name, source in self.o.secrets:
            value = self.values[name]
            self.api.add_secret(value)
            existing = next((v for v in self.variables() if v.get("key") == name and _scope_of(v) == ENV_SCOPE), None)
            wanted = {"masked": True, "protected": False, "raw": True}
            subject = f"variable {name}"
            if (
                existing is not None
                and existing.get("value") == value
                and all(existing.get(k) == v for k, v in wanted.items())
            ):
                self.emit.row("KEPT", subject, f"(from {source}; environment scope {ENV_SCOPE})")
                continue
            verb = "SET" if existing is not None else "NEW"
            if self.o.dry_run:
                self.emit.row(verb, subject, f"(dry run: would {'update' if existing else 'create'} it from {source})")
                continue
            body = {
                "value": value,
                **wanted,
                "environment_scope": ENV_SCOPE,
                "description": f"from {source} by l4 setup gitlab",
            }
            if existing is not None:
                self.api.put(self._variable_path(name), body)
                existing.update(body)
            else:
                self.api.post(f"projects/{self.pid}/variables", {"key": name, **body})
                self.variables().append({"key": name, **body})
            self.emit.row(verb, subject, f"(from {source}; masked, not protected, raw, environment scope {ENV_SCOPE})")

    # --- variables that override the predefined ones L4 reads ---------------------------------------------------

    def overriding_variables(self) -> None:
        """A CI/CD variable of the project, of an ancestor group or of the instance whose name is one of
        `READ_BY_L4` replaces GitLab's predefined variable in this project's jobs (a group variable named
        `CI_JOB_TOKEN` made every `l4 run` cancel itself). One row per such variable; names and scopes, never values."""
        emit = self.emit
        found: list[tuple[str, list[dict[str, Any]]]] = [("project", self.variables())]
        unreadable: list[str] = []
        namespace = self.project.get("namespace") or {}
        full = str(namespace.get("full_path") or str(self.project.get("path_with_namespace", "")).rpartition("/")[0])
        parts = [] if namespace.get("kind") == "user" else [p for p in full.split("/") if p]
        for depth in range(len(parts), 0, -1):  # the namespace first, then each parent
            path = "/".join(parts[:depth])
            try:
                found.append((f"group {path}", self.api.get_paged(f"groups/{quote(path, safe='')}/variables")))
            except AdminError as exc:
                if exc.status not in (401, 403, 404):
                    raise
                unreadable.append(path)
        try:
            found.append(("instance", self.api.get_paged("admin/ci/variables")))
        except AdminError as exc:
            if exc.status not in (401, 403, 404):
                raise
        names = ", ".join(READ_BY_L4)
        warned = False
        for where, variables in found:
            for v in variables:
                if v.get("key") in READ_BY_L4:
                    warned = True
                    scope = _scope_of(v)
                    emit.row(
                        "WARN",
                        "variables",
                        f"{where} defines {v['key']}{'' if scope == '*' else f' (scope {scope})'}: it overrides "
                        "GitLab's predefined variable in this project's jobs"
                        + (
                            " (L4 falls back to the token in CI_REPOSITORY_URL; the project's own jobs get the "
                            "variable's value)"
                            if v["key"] == "CI_JOB_TOKEN"
                            else ""
                        )
                        + "; rename it",
                    )
        if not warned:
            more = f"; not readable: group {', '.join(unreadable)}" if unreadable else ""
            emit.row(
                "OK", "variables", f"(none of {names} is defined by the project, its groups or the instance{more})"
            )

    # --- the sweep schedule ---------------------------------------------------------------------------------

    def sweep_schedule(self) -> None:
        """One schedule, `l4 sweep`, on the base branch (SPEC L4-CI-001, L4-CI-004): the sweeper resumes parked
        units and repairs mirrors on a clock, with no one to push. Created, kept, updated or reactivated; never
        duplicated (it is found by its description)."""
        o, emit = self.o, self.emit
        if not o.schedule:
            emit.row("OK", "schedule l4 sweep", "skipped (--no-schedule)")
            return
        ref = self.base_ref() or "main"
        found = [
            s
            for s in self.api.get_paged(f"projects/{self.pid}/pipeline_schedules")
            if s.get("description") == SCHEDULE_NAME
        ]
        subject = f"schedule {SCHEDULE_NAME}"
        wanted = {"description": SCHEDULE_NAME, "ref": ref, "cron": o.cron, "cron_timezone": "UTC", "active": True}
        if not found:
            if o.dry_run:
                emit.row("NEW", subject, f"(dry run: would create schedule {o.cron} on {ref})")
                return
            self.api.post(f"projects/{self.pid}/pipeline_schedules", wanted)
            emit.row("NEW", subject, f"({o.cron} UTC on {ref})")
            return
        entry = found[0]
        have_ref = str(entry.get("ref", "")).removeprefix("refs/heads/")
        changes = {}
        if entry.get("cron") != o.cron:
            changes["cron"] = o.cron
        if have_ref != ref:
            changes["ref"] = ref
        if not entry.get("active", True):
            changes["active"] = True
        if not changes:
            emit.row("KEPT", subject, f"({entry.get('cron')} on {have_ref}, active)")
            return
        said = []
        if "cron" in changes:
            said.append(f"cron {entry.get('cron')} -> {o.cron}")
        if "ref" in changes:
            said.append(f"ref {have_ref} -> {ref}")
        if "active" in changes:
            said.append("reactivated")
        if o.dry_run:
            emit.row("SET", subject, f"(dry run: would update: {'; '.join(said)})")
            return
        self.api.put(f"projects/{self.pid}/pipeline_schedules/{entry['id']}", changes)
        if "active" in changes:
            self.reactivated = entry["id"]
        emit.row("SET", subject, f"({'; '.join(said)})")

    # --- the adoption check -----------------------------------------------------------------------------------

    def check_pipeline(self) -> None:
        """One pipeline on the base branch with `L4_ADOPTION_CHECK=1`: the template's doctor line then adds
        `--adoption`, so GATE-001 runs the gates on the runner and its platform (a laptop cannot see a failure that is
        Linux-only). Triggered after the token exists (the first pipeline is not the red one of CI-001), and not when a
        row already failed or the include is not on the base branch (there is no `l4` job to check)."""
        o, emit = self.o, self.emit
        ref = self.base_ref()
        if not o.pipeline:
            emit.row("OK", "pipeline", "skipped (--no-pipeline)")
            return
        if o.dry_run:
            emit.row(
                "OK",
                "pipeline",
                f"(dry run: would trigger one on {ref or 'the base branch'} with {ADOPTION_VARIABLE}=1)",
            )
            return
        if emit.failed:
            emit.row("WARN", "pipeline", "not triggered: a row above failed")
            return
        if not ref or not self.include_found:
            emit.row(
                "WARN", "pipeline", "not triggered: the base branch has no .gitlab-ci.yml that includes the harness"
            )
            return
        created = self.api.post(
            f"projects/{self.pid}/pipeline",
            {"ref": ref, "variables": [{"key": ADOPTION_VARIABLE, "value": "1", "variable_type": "env_var"}]},
        )
        self.pipeline_id = int(created["id"])
        emit.row(
            "OK",
            f"pipeline #{created['id']}",
            f"triggered on {ref} with {ADOPTION_VARIABLE}=1: {created.get('web_url', '')}",
        )

    def watch(self) -> None:
        """`--watch`: follow the check pipeline (the last 60 lines of every failed job's trace) and make its end a row:
        a pipeline that did not succeed is a FAIL, so a red adoption check is exit 3."""
        if not (self.o.watch and self.pipeline_id is not None):
            return
        result = watch_pipeline(
            self.api, self.pid, self.pipeline_id, say=self.emit.raw, tail=60, sleep=self.sleep, clock=self.clock
        )
        if result.ok:
            self.emit.row("OK", f"pipeline #{self.pipeline_id}", f"{result.status}: the adoption check passed")
        else:
            paused = self._pause_again()
            self.emit.row(
                "FAIL", f"pipeline #{self.pipeline_id}",
                f"{result.status}: the adoption check did not pass (the job log above says why; fix it, then run "
                "`l4 ci watch` or setup again)" + (f"; {paused}" if paused else ""),
            )  # fmt: skip

    def _pause_again(self) -> str:
        """A schedule this run switched on is switched off again when the check it was switched on for fails: the
        owner paused it for a reason, and a sweep on a base that fails its check would only repeat the failure."""
        if self.reactivated is None:
            return ""
        try:
            self.api.put(f"projects/{self.pid}/pipeline_schedules/{self.reactivated}", {"active": False})
        except AdminError as exc:
            return f"the {SCHEDULE_NAME} schedule could not be paused again ({exc.status}): pause it by hand"
        return f"the {SCHEDULE_NAME} schedule is paused again until the check passes"

    # --- the whole run ----------------------------------------------------------------------------------------

    def run(self) -> None:
        self.read_project()
        self.runners()
        self.include_check()
        self.token_and_variable()
        self.secrets()
        self.overriding_variables()
        self.sweep_schedule()
        self.check_pipeline()
        self.watch()


_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
DEFAULT_CRON = "*/30 * * * *"  # SPEC L4-CI-001: the sweep


def _usage(message: str) -> L4Exit:
    return L4Exit(ExitCode.USAGE_ERROR, f"setup gitlab: {message}")


def _parse_secrets(
    pairs: tuple[str, ...], environ: Mapping[str, str]
) -> tuple[tuple[tuple[str, str], ...], dict[str, str]]:
    """`NAME=ENV` pairs and the values read from the environment, all checked before any request is sent."""
    parsed: list[tuple[str, str]] = []
    values: dict[str, str] = {}
    for item in pairs:
        name, sep, source = item.partition("=")
        if not sep or not _NAME.match(name) or not _NAME.match(source):
            raise _usage(f"--secret expects NAME=ENVVAR (two variable names), got {name or item!r}")
        if not environ.get(source):
            raise _usage(f"--secret {name}: the environment variable {source} is empty or not set")
        parsed.append((name, source))
        values[name] = environ[source]
    if len({n for n, _ in parsed}) != len(parsed):
        raise _usage("--secret names a variable twice")
    return tuple(parsed), values


def _origin_url(app: AppContext) -> str:
    try:
        done = Git(app.repo, environ=app.environ).run("remote", "get-url", "origin", check=False)
    except (L4Exit, GitError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def _hint(exc: AdminError) -> str:
    if exc.status == 401:
        return "the credential was refused (is it the token of a Maintainer of the project?)"
    if exc.status == 403:
        return "the credential may not do this: it needs the Maintainer role on the project (or Owner for some calls)"
    if exc.status == 404:
        return "not found: check --project, and that the credential can see the project"
    return ""


TOKEN_COMMAND_TIMEOUT_S = 30.0


def token_command_refresh(
    command: str, *, timeout: float = TOKEN_COMMAND_TIMEOUT_S, adopt: Callable[[str], None] | None = None
) -> Callable[[], str]:
    """`--token-command` (M1.10 decision 14): a callable that runs `command` (split with `shlex`, never through a
    shell, `timeout` seconds, stdout captured, stderr discarded) and returns its first non-empty stdout line as the new
    credential. `adopt` gets the value before it is returned, so every later line is redacted. A failure carries the
    exit status and nothing the command printed."""
    try:
        argv = shlex.split(command)
    except ValueError:
        argv = []

    def refresh() -> str:
        if not argv:
            raise RefreshFailed("token command failed (it cannot be parsed)")
        try:
            done = subprocess.run(  # noqa: S603 - the operator's own command, run without a shell
                argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, timeout=timeout,
                check=False, text=True,
            )  # fmt: skip
        except subprocess.TimeoutExpired:
            raise RefreshFailed("token command failed (timed out)") from None
        except OSError:
            raise RefreshFailed("token command failed (it could not start)") from None
        if done.returncode != 0:
            raise RefreshFailed(f"token command failed (exit {done.returncode})")
        value = next((line.strip() for line in done.stdout.splitlines() if line.strip()), "")
        if value and adopt is not None:
            adopt(value)
        return value

    return refresh


@dataclass
class Connection:
    app: AppContext
    cfg: Any
    api: AdminApi
    base: str
    verify: str  # where a new bot token is verified
    credential: str
    transport: httpx.BaseTransport | None


def connect_gitlab(
    app: AppContext,
    *,
    api_base: str | None,
    auth_env: str,
    auth_scheme: str,
    verify_base: str | None = None,
    transport: httpx.BaseTransport | None = None,
    token_command: str | None = None,
) -> Connection:
    """The maintainer's credential, the config, the API base and a client: the part `l4 setup gitlab` and
    `l4 ci watch` share. Every failure is a usage error (exit 2) raised before any request is sent."""
    if auth_scheme not in ("private-token", "bearer"):
        raise _usage("--auth-scheme is private-token or bearer")
    credential = app.environ.get(auth_env, "")
    if not credential:
        raise _usage(f"the environment variable {auth_env} is empty or not set: it holds the maintainer's credential")
    app, cfg = load_app_config(app)
    transport = transport or TRANSPORT
    origin = _origin_url(app)
    derived = derive_api_base(origin) if origin else None
    base = api_base or cfg.forge.gitlab.api_url or derived
    if not base:
        raise _usage("cannot tell the GitLab server: pass --api-base, set forge.gitlab.api_url, or add an `origin`")
    real = cfg.forge.gitlab.api_url or derived or ""
    verify = verify_base or (base if auth_scheme == "private-token" else real)
    if not verify:
        raise _usage("--verify-base is needed: the API base is a proxy and no GitLab server is known")
    refresh = None
    if token_command:
        issued: list[str] = []

        def adopt(value: str) -> None:  # a new credential is redacted from every line from then on
            issued.append(value)
            app.redactor.adopt(Redactor({f"setup:credential-{len(issued)}": value}))

        refresh = token_command_refresh(token_command, adopt=adopt)
    try:
        api = AdminApi(base, credential, scheme=auth_scheme, transport=transport, refresh=refresh)  # type: ignore[arg-type]
        AdminApi(verify, "x")  # the same checks for the verification base
    except ValueError as exc:
        raise _usage(str(exc)) from None
    return Connection(app, cfg, api, base, verify, credential, transport)


def run_setup_gitlab(
    app: AppContext,
    *,
    project: str,
    api_base: str | None = None,
    auth_env: str = "GITLAB_TOKEN",
    auth_scheme: str = "private-token",
    verify_base: str | None = None,
    rotate: bool = False,
    revoke_old: bool = False,
    secret: tuple[str, ...] = (),
    cron: str = DEFAULT_CRON,
    no_schedule: bool = False,
    no_pipeline: bool = False,
    watch: bool = False,
    dry_run: bool = False,
    token_command: str | None = None,
    transport: httpx.BaseTransport | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> ExitCode:
    """`l4 setup gitlab`. Exit 0; 3 when a row is FAIL (no usable runner, a token that does not verify, a failed check
    pipeline); 2 for usage (an empty credential, a bad project, an empty `--secret` source); 1 for an HTTP error
    (the rows printed before it say what was done)."""
    pid = project_path(project)
    if revoke_old and not rotate:
        raise _usage("--revoke-old only goes with --rotate")
    secrets, secret_values = _parse_secrets(tuple(secret), app.environ)
    if len(cron.split()) != 5:
        raise _usage("--cron expects five fields, such as '*/30 * * * *'")
    link = connect_gitlab(
        app, api_base=api_base, auth_env=auth_env, auth_scheme=auth_scheme, verify_base=verify_base,
        transport=transport, token_command=token_command,
    )  # fmt: skip
    app, cfg, api, verify, credential, transport = (
        link.app,
        link.cfg,
        link.api,
        link.verify,
        link.credential,
        link.transport,
    )
    config_file = app.config_path or app.repo / ".l4" / "config.yaml"
    options = SetupOptions(
        pid,
        cfg.forge.token_env,
        tuple(cfg.ci.runner_tags),
        rotate,
        revoke_old,
        secrets,
        cron,
        not no_schedule,
        not no_pipeline,
        watch,
        dry_run,
        verify,
        cfg.forge.base_branch if config_file.is_file() else None,
        cfg.forge.branch_prefix,
    )
    app.redactor.adopt(
        Redactor({"setup:credential": credential, **{f"setup:{n}": v for n, v in secret_values.items()}})
    )
    emit = Emitter(app.redactor)

    def learn(value: str) -> None:
        # the name is what a redaction marker prints (`[REDACTED:<name>]`): never a piece of the value
        app.redactor.adopt(Redactor({"setup:bot-token": value}))

    def make_api(url: str, token: str, scheme: str) -> AdminApi:
        return AdminApi(url, token, scheme=scheme, transport=transport)  # type: ignore[arg-type]

    if not config_file.is_file():
        emit.row(
            "OK",
            "config",
            f"no .l4/config.yaml: schema defaults (variable {options.token_env}, runner tags "
            f"[{', '.join(options.runner_tags)}])",
        )
    setup = Setup(api, options, emit, make_api, learn, secret_values, sleep, clock)
    try:
        setup.run()
    except AdminError as exc:
        click.echo(app.redactor.redact_text(f"ERROR {exc}" + (f"\n      {_hint(exc)}" if _hint(exc) else "")))
        emit.summary(ExitCode.INTERNAL_ERROR)
        return ExitCode.INTERNAL_ERROR
    code = ExitCode.DOCTOR_FAILED if emit.failed else ExitCode.OK
    emit.summary(code)
    return code
