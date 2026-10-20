"""GitLab REST v4 over httpx (forge-and-ci D5) and the per-command git credential helper (D6).

The token travels only in the `PRIVATE-TOKEN` header of requests to the configured API URL (https, or plain http
on a loopback address), redirects are not followed, and every message that leaves this module has the token cut out.
`Draft: ` in the title is how a merge request is a draft, so ready means dropping that prefix.
"""

import re
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import httpx

from l4 import cancel
from l4.config.schema import L4Config
from l4.forge.base import (
    AMBIGUOUS_ERRORS,
    GIT_USERNAMES,
    QUICK_TIMEOUT_S,
    STICKY_MARKER,
    UNFINISHED,
    AmbiguousWrite,
    CiRunState,
    Continuation,
    ForgeAuthError,
    ForgeError,
    ForgeNotFound,
    ForgeRateLimited,
    JobLog,
    JobResult,
    LabelEvent,
    MergeCall,
    PrState,
    PullRequest,
    Relay,
    StartRun,
    clip_log,
    forge_platform,
    post_once,
    strip_ansi,
)
from l4.forge.pushurl import push_url
from l4.vcs.git import Git

DRAFT_PREFIX = "Draft: "
LABEL_COLOR = "#6b7280"
MAX_RETRIES = 3
MAX_WAIT_S = 60.0
_JOB_URL = re.compile(r"/-/jobs/(?P<id>\d+)/?$")
_JOB_DONE = frozenset({"success", "failed", "canceled", "skipped", "manual"})
PIPELINE_UNFINISHED = frozenset({"created", "pending", "running", "waiting_for_resource", "preparing", "scheduled"})
MAX_PAGES = 100
PER_PAGE = 100
TIMEOUT_S = 30.0
_DRAFT = re.compile(r"^\s*(?:draft:|\[draft\]|\(draft\))\s*", re.IGNORECASE)
_LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1"})
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_GIT_USERNAME = re.compile(r"^[A-Za-z0-9_.-]+$")
_PROJECT_BOT = re.compile(r"^project_\d+_bot(?:_|$)")
_STATES = {"opened": "open", "merged": "merged", "closed": "closed", "locked": "open"}  # locked: being merged
_QUERY_STATES = {"open": "opened", "merged": "merged", "closed": "closed", "all": "all"}
# A job trace with runner timestamps: `<time>Z <stream id><O|E><' ' | '+' (the line continues the previous one)>`.
_RUNNER_PREFIX = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z [0-9a-f]{2}[OE][ +]?")
_SECTION = re.compile(r"section_(start|end):\d+:([A-Za-z0-9_.-]+)\r?")
# The runner's own closing sections: they come after the job's error and say nothing about it.
_RUNNER_SECTIONS = frozenset({
    "upload_artifacts_on_failure", "upload_artifacts_on_success", "cleanup_file_variables",
})  # fmt: skip
_STEP_SECTIONS = frozenset({"step_script", "build_script"})


def strip_draft(title: str) -> str:
    return _DRAFT.sub("", title, count=1)


def job_log_text(trace: str) -> str:
    return _read_trace(trace)[0]


def job_log_step(trace: str) -> str | None:
    return _read_trace(trace)[1]


def _read_trace(trace: str) -> tuple[str, str | None]:
    """A GitLab job trace as the job printed it: the runner's per-line timestamps, the section markers, lines that held
    only control sequences and the runner's closing sections (artifact upload, cleanup) removed, so the end of the text
    is the job's own end. M1.9 live check: a fix task keeps the end of the log, which held only the runner's lines.
    Also the last `$ ` echo inside the `step_script` (or legacy `build_script`) section, read before the markers go
    (M1.10 decision 1): None for a trace without such a section."""
    kept: list[str] = []
    skipping: str | None = None
    in_step = False
    step: str | None = None
    for raw in trace.replace("\r\n", "\n").split("\n"):
        unprefixed = _RUNNER_PREFIX.sub("", raw, count=1)
        line = strip_ansi(unprefixed)
        for marker in _SECTION.finditer(line):
            kind, name = marker.groups()
            if kind == "start" and name in _RUNNER_SECTIONS:
                skipping = name
            elif kind == "end" and name == skipping:
                skipping = None
            if name in _STEP_SECTIONS:
                in_step = kind == "start"
        line = _SECTION.sub("", line).replace("\r", "")
        if skipping is not None or (not line.strip() and line != unprefixed):
            continue  # the runner's own section, or a line of markers and control sequences only
        kept.append(line)
        if in_step and line.startswith("$ ") and line[2:].strip():
            step = line[2:].strip()
    return "\n".join(kept), step


def _checked_api_url(api_url: str) -> str:
    parts = urlsplit(api_url)
    loopback = parts.hostname in _LOOPBACK
    if parts.scheme != "https" and not (parts.scheme == "http" and loopback):
        raise ValueError("the GitLab API URL must be https (plain http only for localhost)")
    if not parts.hostname or "@" in parts.netloc:
        raise ValueError("the GitLab API URL needs a host and must not carry credentials")
    return api_url.rstrip("/")


class GitLabForge:
    """`api_url` is `.../api/v4`; `project` is the numeric id or `group/project`."""

    def __init__(
        self,
        api_url: str,
        project: str,
        token: str,
        *,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._api = _checked_api_url(api_url)
        self._project = quote(project, safe="")
        self._token = token
        self._transport = transport
        self._sleep = sleep
        self._bot_id: int | None = None
        self._bot_known = False

    # --- HTTP core --------------------------------------------------------------------------------------------

    def _scrub(self, text: str) -> str:
        return text.replace(self._token, "[REDACTED:token]") if self._token else text

    def _wait(self, response: httpx.Response | None, attempt: int) -> float:
        try:
            retry_after = float(response.headers["Retry-After"]) if response is not None else None
        except (KeyError, ValueError):
            retry_after = None
        wait = retry_after if retry_after is not None and retry_after >= 0 else float(2**attempt)
        return min(wait, MAX_WAIT_S)

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        absolute: bool = False,
        blind: bool | None = None,
        quick: bool = False,
    ) -> httpx.Response:
        """`path` is under the project, or under the API root when `absolute`. `blind`: whether a request whose
        response was lost may be sent again as it is; a POST is not blind unless the caller says it is idempotent
        (HB-12): it raises `AmbiguousWrite` instead, for the caller to read the effect back."""
        if method != "GET":
            cancel.check()  # W-D2: a cancelled run writes nothing to the forge
        blind = method != "POST" if blind is None else blind
        url = f"{self._api}{path}" if absolute else f"{self._api}/projects/{self._project}{path}"
        headers = {"PRIVATE-TOKEN": self._token, "Accept": "application/json"}
        label = f"GitLab {method} {path or '/'}"
        tries = 0 if quick else MAX_RETRIES  # `quick`: a best-effort read, `QUICK_TIMEOUT_S`, one try
        for attempt in range(tries + 1):
            last = attempt == tries
            try:
                timeout = QUICK_TIMEOUT_S if quick else TIMEOUT_S
                with httpx.Client(transport=self._transport, timeout=timeout, follow_redirects=False) as client:
                    response = client.request(method, url, params=params, json=json, headers=headers)
            except httpx.TransportError as exc:
                if not blind and isinstance(exc, AMBIGUOUS_ERRORS):
                    raise AmbiguousWrite(self._scrub(f"{label}: {type(exc).__name__}: {exc}")) from None
                if last:
                    raise ForgeError(self._scrub(f"{label}: {type(exc).__name__}: {exc}")) from None
                self._sleep(self._wait(None, attempt))
                continue
            if response.status_code >= 500 and not blind:
                raise AmbiguousWrite(self._scrub(f"{label}: HTTP {response.status_code}"), status=response.status_code)
            if (response.status_code == 429 or response.status_code >= 500) and not last:
                self._sleep(self._wait(response, attempt))
                continue
            if response.is_success:
                return response
            raise self._error(label, response)
        raise AssertionError("unreachable")  # pragma: no cover

    def _error(self, label: str, response: httpx.Response) -> ForgeError:
        status = response.status_code
        detail = ""
        try:
            body = response.json()
            text = body.get("message") or body.get("error") if isinstance(body, dict) else None
            detail = f": {' '.join(str(text).split())[:200]}" if text else ""
        except ValueError:
            pass
        message = self._scrub(f"{label}: HTTP {status}{detail}")
        if status in (401, 403):
            return ForgeAuthError(message, status=status)
        if status == 404:
            return ForgeNotFound(message, status=status)
        if status == 429:
            return ForgeRateLimited(message, status=status)
        return ForgeError(message, status=status)

    def _pages(self, path: str, params: dict[str, Any] | None = None) -> Iterator[Any]:
        page = 1
        for _ in range(MAX_PAGES):
            response = self._request("GET", path, params={**(params or {}), "per_page": PER_PAGE, "page": page})
            yield from response.json()
            following = response.headers.get("X-Next-Page", "")
            if not following.isdigit() or int(following) <= page:
                return
            page = int(following)

    # --- merge requests ---------------------------------------------------------------------------------------

    @staticmethod
    def _pr(data: dict[str, Any]) -> PullRequest:
        title = str(data["title"])
        return PullRequest(
            number=int(data["iid"]), url=str(data["web_url"]), head_branch=str(data["source_branch"]),
            base_branch=str(data["target_branch"]), title=strip_draft(title),
            draft=bool(data.get("draft", _DRAFT.match(title) is not None)),
            state=_STATES.get(str(data.get("state")), "open"), labels=tuple(str(x) for x in data.get("labels", ())),
            merge_commit_sha=(
                str(data.get("merge_commit_sha") or data.get("squash_commit_sha") or "") or None
            ),  # a squash merge leaves `merge_commit_sha` empty and fills `squash_commit_sha`
            head_sha=str(data["sha"]) if data.get("sha") else None,  # the MR's `sha` is its source branch head
            body=data.get("description") if isinstance(data.get("description"), str) else None,
        )  # fmt: skip

    @staticmethod
    def _ours(item: dict[str, Any]) -> bool:
        """Not an MR from a fork: a fork picks its own source branch name, which must not pass for a harness one."""
        return item.get("source_project_id") == item.get("target_project_id")

    def project_url(self) -> str:
        response = self._request("GET", "")
        return str(response.json()["web_url"]).rstrip("/")

    def get_pr(self, number: int) -> PullRequest:
        return self._pr(self._request("GET", f"/merge_requests/{number}").json())

    def find_pr(self, head_branch: str) -> PullRequest | None:
        found = self._request("GET", "/merge_requests", params={"source_branch": head_branch, "state": "opened"})
        items = [item for item in found.json() if self._ours(item)]
        return self._pr(items[0]) if items else None

    def list_prs(self, head_prefix: str, state: PrState = "all") -> list[PullRequest]:
        """GitLab has no prefix filter on the source branch, so every MR of the state is paged and filtered here."""
        params = {"state": _QUERY_STATES[state], "order_by": "updated_at", "sort": "desc"}
        return [self._pr(item) for item in self._pages("/merge_requests", params) if
                self._ours(item) and str(item["source_branch"]).startswith(head_prefix)]  # fmt: skip

    def create_pr(self, head: str, base: str, title: str, body: str, draft: bool = True) -> PullRequest:
        """The open MR of `head` when there is one, so a retry after a crash never opens a second."""
        existing = self.find_pr(head)
        if existing is not None:
            return existing
        full_title = f"{DRAFT_PREFIX}{strip_draft(title)}" if draft else strip_draft(title)
        payload = {"source_branch": head, "target_branch": base, "title": full_title, "description": body}
        return post_once(
            lambda: self._pr(self._request("POST", "/merge_requests", json=payload).json()),
            lambda: self.find_pr(head), self._pause,
        )  # fmt: skip

    def _pause(self) -> None:
        self._sleep(self._wait(None, 0))

    def update_pr(
        self, number: int, *, title: str | None = None, body: str | None = None, draft: bool | None = None
    ) -> PullRequest:
        current = self.get_pr(number)
        wanted_title = strip_draft(title) if title is not None else current.title
        wanted_draft = current.draft if draft is None else draft
        payload: dict[str, str] = {}
        if wanted_title != current.title or wanted_draft != current.draft:
            payload["title"] = f"{DRAFT_PREFIX}{wanted_title}" if wanted_draft else wanted_title
        if body is not None:
            payload["description"] = body
        if not payload:
            return current
        return self._pr(self._request("PUT", f"/merge_requests/{number}", json=payload).json())

    # --- the project's own CI --------------------------------------------------------------------------------

    def list_pipeline_jobs(self, sha: str, *, settled: bool = False) -> list[JobResult]:
        """`pipelines?sha=`, then `pipelines/:id/jobs` of each (a retried attempt is not listed unless asked for),
        newest pipeline first; the first job of a name is kept (`settled`: the first finished one, if any)."""
        pipelines = sorted(
            (p for p in self._pages("/pipelines", {"sha": sha}) if str(p.get("sha", sha)) == sha),
            key=lambda p: int(p["id"]), reverse=True,
        )  # fmt: skip
        found: dict[str, JobResult] = {}
        for pipeline in pipelines:
            names: set[str] = set()
            for job in self._pages(f"/pipelines/{int(pipeline['id'])}/jobs"):
                name = str(job["name"])
                names.add(name)
                status = str(job.get("status") or "")
                if name not in found or (settled and found[name].status in UNFINISHED and status not in UNFINISHED):
                    found[name] = JobResult(
                        name=name, stage=str(job.get("stage") or ""), status=status,
                        allow_failure=bool(job.get("allow_failure")), pipeline_id=int(pipeline["id"]),
                        job_id=int(job["id"]), web_url=str(job.get("web_url") or ""),
                    )  # fmt: skip
            if pipeline.get("status") in PIPELINE_UNFINISHED and not names - {"l4"}:
                # nothing but the harness's own job is listed: the pipeline is still being created (L4-CI-014)
                found[f"(pipeline {int(pipeline['id'])})"] = JobResult(
                    name=f"(pipeline {int(pipeline['id'])})", stage="", status="pending", allow_failure=False,
                    pipeline_id=int(pipeline["id"]), job_id=None, web_url=str(pipeline.get("web_url") or ""),
                )  # fmt: skip
        return list(found.values())

    def job_log_tail(self, job_id: int | str, max_lines: int = 40) -> str:
        return self.job_log(job_id, max_lines).tail

    def job_log(self, job_id: int | str, max_lines: int = 40) -> JobLog:
        try:
            text = self._request("GET", f"/jobs/{int(job_id)}/trace").text
        except ForgeNotFound:
            return JobLog()  # no log (erased, or never started): no evidence
        cleaned, step = _read_trace(text)
        return JobLog(clip_log(cleaned, max_lines), step)

    # --- who set a label (L4-SEC-004) -------------------------------------------------------------------------

    def label_events(self, number: int) -> list[LabelEvent]:
        """`resource_label_events`: `{id, action, user: {id}, label: {name} | null}` per event, oldest first."""
        events = []
        for item in self._pages(f"/merge_requests/{number}/resource_label_events"):
            try:
                user = item.get("user") or {}
                events.append(
                    LabelEvent(
                        id=int(item["id"]),
                        label=str((item.get("label") or {}).get("name") or ""),
                        action="remove" if item.get("action") == "remove" else "add",
                        user_id=int(user["id"]) if user.get("id") is not None else None,
                        created_at=str(item.get("created_at") or ""),
                    )  # fmt: skip
                )
            except (KeyError, ValueError, TypeError, AttributeError):
                continue  # an entry of an unknown shape is no evidence
        return sorted(events, key=lambda e: e.id)

    def member_access(self, user_id: int) -> int | None:
        """`members/all/:id` (direct and inherited members): the access level; None for a non-member (404), a user
        who is not active, or an answer without a level."""
        try:
            member = self._request("GET", f"/members/all/{int(user_id)}").json()
            level = int(member["access_level"])
        except ForgeNotFound:
            return None
        except (ValueError, KeyError, TypeError):
            return None
        return level if member.get("state", "active") == "active" else None

    def own_user_id(self) -> int | None:
        """The user the token acts as (`_author_id`)."""
        return self._author_id()

    def dispatch_continuation(self, ref: str) -> Continuation:
        """Not on GitLab yet (forge-and-ci 2.6, a trigger token): the next push or the schedule continues."""
        return "unsupported"

    def relay_run(self, ref: str, *, exclude_run_id: str | None) -> Relay:
        """No relay on GitLab: its schedule targets the base and the pin guard applies to GitHub only (L4-IMP-072)."""
        return "unsupported"

    def base_runs(self, ref: str, *, exclude_run_id: str | None = None) -> int | None:
        """The pipelines of `ref` from `created` to `running` (`UNFINISHED`), not counting pipeline `exclude_run_id`;
        the newest 20 are read. None when the forge cannot say."""
        try:
            pipelines = self._request("GET", "/pipelines", params={"ref": ref, "per_page": 20}).json()
        except ForgeError:
            return None
        if not isinstance(pipelines, list):
            return None
        return sum(
            1
            for item in pipelines
            if isinstance(item, dict) and str(item.get("id")) != exclude_run_id and item.get("status") in UNFINISHED
        )

    def ci_run_state(self, ci_url: str) -> CiRunState:
        """`GET /projects/:id/jobs/:job` of a job URL (`.../-/jobs/<id>`); a finished job is `completed`."""
        found = _JOB_URL.search(urlsplit(ci_url).path)
        if found is None:
            return "unknown", ""
        try:
            job = self._request("GET", f"/jobs/{found['id']}", quick=True).json()
        except ForgeError:
            return "unknown", ""
        status = job.get("status") if isinstance(job, dict) else None
        if status in _JOB_DONE:
            return "completed", str(status)
        if status in UNFINISHED:
            return "running", str(status)
        return "unknown", ""

    def start_run(self, ref: str) -> StartRun:
        """`POST /projects/:id/pipeline {ref}` (L4-OPS-002): 201 is `started`; a token that may not (401, 403) is
        `refused`; a ref or project that cannot run a pipeline (400, 404, 422) is `unsupported`. The `l4` job's rules
        accept the source `api`. Another failure raises."""
        try:
            self._request("POST", "/pipeline", json={"ref": ref})
        except ForgeAuthError:
            return "refused"
        except ForgeError as exc:
            if exc.status in (400, 404, 422):
                return "unsupported"
            raise
        return "started"

    # --- the sticky note --------------------------------------------------------------------------------------

    def _author_id(self) -> int | None:
        """The user whose notes are ours: the token's own user, else the project's single bot member (a project token
        may be unable to read `/user`). None when neither can be told; the answer is kept for the life of the client,
        so a forge that cannot say is asked once per run."""
        if not self._bot_known:
            self._bot_known = True
            self._bot_id = self._token_user() or self._project_bot()
        return self._bot_id

    def _token_user(self) -> int | None:
        try:
            return int(self._request("GET", "/user", absolute=True).json()["id"])
        except (ForgeError, ValueError, KeyError, TypeError):
            return None

    def _project_bot(self) -> int | None:
        try:
            members = self._request("GET", "/members/all", params={"query": "bot", "per_page": PER_PAGE}).json()
            bots = {int(m["id"]) for m in members if _PROJECT_BOT.match(str(m.get("username", "")))}
        except (ForgeError, ValueError, KeyError, TypeError, AttributeError):
            return None
        return bots.pop() if len(bots) == 1 else None

    def upsert_sticky_note(self, number: int, body: str) -> None:
        """Only a note by the token's own user whose text starts with the marker is ours: a marker quoted by a human
        or planted by someone else is never rewritten (it could not be, with a project token, and a 403 would read as
        a bad token)."""
        text = f"{STICKY_MARKER}\n{body}"
        me = self._author_id()
        if me is None:
            raise ForgeError("GitLab: cannot tell which user is the bot (GET /user failed, no single project bot)")
        path = f"/merge_requests/{number}/notes"

        def find() -> dict[str, Any] | None:
            return next(
                (
                    n for n in self._pages(path)
                    if not n.get("system") and n.get("author", {}).get("id") == me
                    and str(n.get("body", "")).startswith(STICKY_MARKER)
                ),
                None,
            )  # fmt: skip

        mine = find()
        if mine is None:  # a lost response is read back by the marker: never a second note
            mine = post_once(lambda: self._request("POST", path, json={"body": text}).json(), find, self._pause)
        if mine["body"] != text:
            self._request("PUT", f"{path}/{mine['id']}", json={"body": text})

    def close_pr(self, number: int, comment: str) -> PullRequest:
        """The note first (found again by its text after a lost response, never posted twice), then
        `PUT merge_requests/:iid {state_event: close}`. A merge request that is not open is returned as it is
        (L4-OPS-004)."""
        current = self.get_pr(number)
        if current.state != "open":
            return current
        path = f"/merge_requests/{number}/notes"

        def find() -> dict[str, Any] | None:
            return next(
                (n for n in self._pages(path) if not n.get("system") and str(n.get("body", "")) == comment), None
            )

        if find() is None:
            post_once(lambda: self._request("POST", path, json={"body": comment}).json(), find, self._pause)
        return self._pr(self._request("PUT", f"/merge_requests/{number}", json={"state_event": "close"}).json())

    def merge_pr(self, number: int, *, sha: str, title: str, message: str) -> MergeCall:
        """`PUT merge_requests/:iid/merge` with `squash: true`, pinned to `sha`: 200 merged, 409 the head is not `sha`,
        405, 406 and 422 (cannot be merged, squash not allowed) refused with GitLab's message. A refusal of a merge
        request that is merged by now (a lost answer, sent again) is the merge."""
        text = f"{title}\n\n{message}"
        payload = {
            "squash": True, "sha": sha, "squash_commit_message": text, "merge_commit_message": text,
            "should_remove_source_branch": False,
        }  # fmt: skip
        try:
            reply = self._request("PUT", f"/merge_requests/{number}/merge", json=payload).json()
        except ForgeError as exc:
            if exc.status == 409:
                return MergeCall("head_moved", None, str(exc))
            if exc.status in (405, 406, 422):
                now = self.get_pr(number)
                if now.state == "merged" and now.merge_commit_sha:
                    return MergeCall("merged", now.merge_commit_sha, "the merge request was merged already")
                return MergeCall("refused", None, str(exc))
            raise
        landed = self._pr(reply).merge_commit_sha
        if not landed:
            return MergeCall("refused", None, f"GitLab merged !{number} but names no commit")
        return MergeCall("merged", landed, f"squash-merged as {landed}")

    # --- labels -----------------------------------------------------------------------------------------------

    def label_names(self) -> list[str]:
        return [str(item["name"]) for item in self._pages("/labels")]

    def ensure_labels(self, names: Sequence[str]) -> None:
        existing = set(self.label_names())
        for name in names:
            if name in existing:
                continue
            try:
                self._create_label(name)
            except ForgeError as exc:
                if exc.status != 409:  # created meanwhile by another run
                    raise
            existing.add(name)

    def _create_label(self, name: str) -> None:
        def post() -> bool:
            self._request("POST", "/labels", json={"name": name, "color": LABEL_COLOR})
            return True

        post_once(post, lambda: True if name in self.label_names() else None, self._pause)

    def set_managed_labels(self, number: int, labels: Sequence[str], prefix: str) -> PullRequest:
        """Exactly `labels` among the labels that start with `prefix`; every other label stays. No call when
        nothing differs."""
        if any("," in name or not name.startswith(prefix) for name in labels):
            raise ValueError("a managed label starts with the prefix and has no comma")
        current = self.get_pr(number)
        have, want = set(current.labels), set(labels)
        add = sorted(want - have)
        remove = sorted(label for label in have - want if label.startswith(prefix))
        if not add and not remove:
            return current
        payload = {key: ",".join(names) for key, names in (("add_labels", add), ("remove_labels", remove)) if names}
        return self._pr(self._request("PUT", f"/merge_requests/{number}", json=payload).json())


# --- git credentials (D6) -------------------------------------------------------------------------------------


def git_auth_config(token_env: str, username: str = "oauth2") -> tuple[tuple[str, str], ...]:
    """`git -c` pairs for one command: the helper list is reset, then one helper that prints the password from the
    environment variable `token_env` when git asks (`get`). The variable's NAME is in argv, its value never is,
    and nothing is written to `.git/config`. `username`: `oauth2` for GitLab, `x-access-token` for GitHub."""
    if not _ENV_NAME.match(token_env):
        raise ValueError("token_env is not an environment variable name")
    if not _GIT_USERNAME.match(username):
        raise ValueError("the git username is spliced into a shell helper: letters, digits, '_', '.' and '-' only")
    helper = f'!f() {{ test "$1" = get || exit 0; echo username={username}; echo "password=${token_env}"; }}; f'
    return (("credential.helper", ""), ("credential.helper", helper))


def push_auth_config(
    cfg: L4Config, environ: Mapping[str, str], origin_url: str | None = None
) -> tuple[tuple[str, str], ...]:
    """The `git -c` pairs of every push: the credential helper, plus a credential-free push URL because a runner may
    rewrite the origin URL to carry its job token (`l4.forge.pushurl`). `origin_url` names the platform outside CI.
    Outside CI, with the `forge.token_env` variable empty, no helper: the person's own git credentials apply, as
    for the fetch (L4-ADO-003)."""
    platform = forge_platform(cfg, environ, origin_url)
    in_ci = environ.get("GITLAB_CI") == "true" or environ.get("GITHUB_ACTIONS") == "true"
    if in_ci or environ.get(cfg.forge.token_env):
        config = git_auth_config(cfg.forge.token_env, username=GIT_USERNAMES.get(platform, "oauth2"))
    else:
        config = ()
    url = push_url(cfg, environ) if platform == "gitlab" else None  # the runner workaround is GitLab's
    return (*config, ("remote.origin.pushurl", url)) if url else config


def strip_remote_credentials(git: Git, remote: str = "origin") -> bool:
    """A runner may write `https://gitlab-ci-token:<token>@host/...` into the shared `.git/config`, where agents and
    gates could read it (SPEC 16.3). Rewrite an https URL without its userinfo; ssh and credential-free URLs are left
    alone. True when the URL changed."""
    done = git.run("config", "--get", f"remote.{remote}.url", check=False)
    url = done.stdout.strip()
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or "@" not in parts.netloc:
        return False
    clean = urlunsplit(parts._replace(netloc=parts.netloc.rpartition("@")[2]))
    git.run("remote", "set-url", remote, clean)
    return True
