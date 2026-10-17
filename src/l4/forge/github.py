"""GitHub REST v3 over httpx (forge-and-ci 2.8, 2.9 reduced): pull requests, labels, the sticky comment.

The token travels only in the `Authorization` header of requests to the configured API host (https, or plain http on a
loopback address): a `Link: rel="next"` that points anywhere else ends the listing, redirects are not followed, and
every message that leaves this module has the token cut out. A pull request becomes ready for review through the
GraphQL mutation `markPullRequestReadyForReview`; REST has no endpoint for it.
M1: forge-and-ci 2.9 rest (statuses, check runs, approvals, collaborator permission), 2.10 (workflow_dispatch).
"""

import os
import re
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from typing import Any
from urllib.parse import quote, urlsplit

import httpx

from l4 import cancel
from l4.ci.github import WORKFLOW_RELPATH
from l4.forge.base import (
    AMBIGUOUS_ERRORS,
    STICKY_MARKER,
    UNFINISHED,
    AmbiguousWrite,
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
    StartRun,
    clip_log,
    post_once,
)

DEFAULT_API = "https://api.github.com"
API_VERSION = "2022-11-28"
LABEL_COLOR = "6b7280"
WORKFLOW_FILE = WORKFLOW_RELPATH.rsplit("/", 1)[-1]  # `l4.yml`: the one name the template and the dispatch share
ACTIONS_BOT_LOGIN = "github-actions[bot]"  # who a job's GITHUB_TOKEN is; GET /user answers 403 for it
ACTIONS_BOT_ID = 41898282  # GET /users/github-actions[bot], verified 2026-10-11
MAX_RETRIES = 3
MAX_WAIT_S = 60.0
MAX_PAGES = 100
PER_PAGE = 100
TIMEOUT_S = 30.0
_LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1"})
_REPO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9._-]+$")
_NEXT = re.compile(r'<([^>]+)>\s*;\s*rel="next"')
_READY = "mutation($id: ID!) { markPullRequestReadyForReview(input: {pullRequestId: $id}) { pullRequest { id } } }"
_DRAFT = "mutation($id: ID!) { convertPullRequestToDraft(input: {pullRequestId: $id}) { pullRequest { id } } }"


_ROLE_LEVELS = {"admin": 50, "maintain": 40, "write": 30, "triage": 20, "read": 10}  # GitLab access levels
_PR_REFUSED = (
    "GitHub refused to create the pull request (403). Allow GitHub Actions to create and approve pull requests "
    "(Settings > Actions > General > Workflow permissions), or run `l4 setup github`"
)
_CHECK_CONCLUSIONS = {
    "success": "success", "failure": "failed", "timed_out": "failed", "startup_failure": "failed",
    "cancelled": "canceled", "skipped": "skipped", "neutral": "skipped", "stale": "skipped",
    "action_required": "manual",
}  # fmt: skip


def _check_status(status: object, conclusion: object) -> str:
    """GitHub's `status` and `conclusion` in the words of a GitLab job status (`l4.forge.base.JobResult`)."""
    if status == "completed":
        return _CHECK_CONCLUSIONS.get(str(conclusion), "failed")  # a conclusion it does not know is not green
    return {"in_progress": "running", "queued": "pending", "waiting": "pending", "pending": "pending"}.get(
        str(status), "pending"
    )


def _checked_api_url(api_url: str) -> str:
    parts = urlsplit(api_url)
    if parts.scheme != "https" and not (parts.scheme == "http" and parts.hostname in _LOOPBACK):
        raise ValueError("the GitHub API URL must be https (plain http only for localhost)")
    if not parts.hostname or "@" in parts.netloc:
        raise ValueError("the GitHub API URL needs a host and must not carry credentials")
    return api_url.rstrip("/")


class GitHubForge:
    """`api_url` is `https://api.github.com` or a GitHub Enterprise `https://host/api/v3`; `repo` is `owner/name`."""

    def __init__(
        self,
        repo: str,
        token: str,
        *,
        api_url: str = DEFAULT_API,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], float] = time.time,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        if not _REPO.match(repo):
            raise ValueError("the GitHub repository must be written owner/name")
        self._api = _checked_api_url(api_url)
        self._repo = repo
        self._owner = repo.partition("/")[0]
        self._token = token
        self._transport = transport
        self._sleep = sleep
        self._now = now
        self._environ = os.environ if environ is None else environ
        self._who: tuple[str, int] | None = None

    # --- HTTP core ----------------------------------------------------------------------------------------------

    def _scrub(self, text: str) -> str:
        return text.replace(self._token, "[REDACTED:token]") if self._token else text

    def _wait(self, response: httpx.Response | None, attempt: int) -> float:
        """Retry-After wins; for an exhausted primary limit, until `x-ratelimit-reset`; else exponential."""
        if response is not None:
            try:
                return min(max(float(response.headers["Retry-After"]), 0.0), MAX_WAIT_S)
            except (KeyError, ValueError):
                pass
            if response.headers.get("x-ratelimit-remaining") == "0":
                try:
                    return min(max(float(response.headers["x-ratelimit-reset"]) - self._now(), 0.0), MAX_WAIT_S)
                except (KeyError, ValueError):
                    pass
        return min(float(2**attempt), MAX_WAIT_S)

    @staticmethod
    def _rate_limited(response: httpx.Response) -> bool:
        """429, or a 403 that says it is a rate limit (primary: `x-ratelimit-remaining: 0`; secondary: its message or a
        `Retry-After`). Any other 403 is a missing scope."""
        if response.status_code == 429:
            return True
        if response.status_code != 403:
            return False
        if response.headers.get("x-ratelimit-remaining") == "0" or "Retry-After" in response.headers:
            return True
        try:
            body = response.json()
        except ValueError:
            return False
        return isinstance(body, dict) and "rate limit" in str(body.get("message", "")).lower()

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        blind: bool | None = None,
    ) -> httpx.Response:
        """`path` is relative to the API root, or an absolute URL on the same host (the next page of a listing).
        `blind`: whether a request whose response was lost may be sent again as it is; a POST is not blind unless the
        caller says it is idempotent (HB-12): it raises `AmbiguousWrite` for the caller to read the effect back."""
        if method != "GET":
            cancel.check()  # W-D2: a cancelled run writes nothing to the forge
        blind = method != "POST" if blind is None else blind
        url = path if path.startswith("http") else f"{self._api}{path}"
        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
        }
        label = f"GitHub {method} {urlsplit(url).path.removeprefix(urlsplit(self._api).path) or '/'}"
        for attempt in range(MAX_RETRIES + 1):
            last = attempt == MAX_RETRIES
            try:
                with httpx.Client(transport=self._transport, timeout=TIMEOUT_S, follow_redirects=False) as client:
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
            if (self._rate_limited(response) or response.status_code >= 500) and not last:
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
            text = body.get("message") if isinstance(body, dict) else None
            detail = f": {' '.join(str(text).split())[:200]}" if text else ""
        except ValueError:
            pass
        message = self._scrub(f"{label}: HTTP {status}{detail}")
        if self._rate_limited(response):
            return ForgeRateLimited(message, status=status)
        if status in (401, 403):
            return ForgeAuthError(message, status=status)
        if status == 404:
            return ForgeNotFound(message, status=status)
        return ForgeError(message, status=status)

    def _pages(self, path: str, params: dict[str, Any] | None = None, *, key: str | None = None) -> Iterator[Any]:
        """The items of a listing, page after page; `key` names the list inside an object body (`check_runs`)."""
        url: str | None = path
        query: dict[str, Any] | None = {**(params or {}), "per_page": PER_PAGE}
        for _ in range(MAX_PAGES):
            response = self._request("GET", url or path, params=query)
            body = response.json()
            yield from (body.get(key, []) if key and isinstance(body, dict) else body)
            match = _NEXT.search(response.headers.get("Link", ""))
            following = match.group(1) if match else None
            if following is None or urlsplit(following)[:2] != urlsplit(self._api)[:2]:
                return  # another scheme or host: the token must not follow
            url, query = following, None

    def _graphql(self, query: str, **variables: Any) -> None:
        root = self._api.removesuffix("/api/v3") + "/api" if self._api.endswith("/api/v3") else self._api
        reply = self._request(
            "POST", f"{root}/graphql", json={"query": query, "variables": variables}, blind=True
        ).json()  # draft and ready are idempotent mutations
        if isinstance(reply, dict) and reply.get("errors"):
            first = reply["errors"][0]
            raise ForgeError(self._scrub(f"GitHub GraphQL: {str(first.get('message', 'error'))[:200]}"))

    # --- pull requests ------------------------------------------------------------------------------------------

    @staticmethod
    def _pr(data: dict[str, Any]) -> PullRequest:
        merged = bool(data.get("merged") or data.get("merged_at"))
        return PullRequest(
            number=int(data["number"]), url=str(data["html_url"]), head_branch=str(data["head"]["ref"]),
            base_branch=str(data["base"]["ref"]), title=str(data["title"]), draft=bool(data.get("draft", False)),
            state="merged" if merged else ("open" if data.get("state") == "open" else "closed"),
            labels=tuple(str(x["name"]) for x in data.get("labels", ())),
            merge_commit_sha=str(data["merge_commit_sha"]) if merged and data.get("merge_commit_sha") else None,
            head_sha=str(data["head"]["sha"]) if data["head"].get("sha") else None,
        )  # fmt: skip

    def project_url(self) -> str:
        return str(self._request("GET", f"/repos/{self._repo}").json()["html_url"]).rstrip("/")

    def _get_raw(self, number: int) -> dict[str, Any]:
        return self._request("GET", f"/repos/{self._repo}/pulls/{number}").json()

    def get_pr(self, number: int) -> PullRequest:
        return self._pr(self._get_raw(number))

    def find_pr(self, head_branch: str) -> PullRequest | None:
        found = self._request(
            "GET", f"/repos/{self._repo}/pulls", params={"head": f"{self._owner}:{head_branch}", "state": "open"}
        ).json()
        return self._pr(found[0]) if found else None

    def list_prs(self, head_prefix: str, state: PrState = "all") -> list[PullRequest]:
        """GitHub has no prefix filter on the head branch, so every pull request of the state is paged and filtered
        here. A pull request from a fork is never ours, whatever its branch is called."""
        params = {"state": "open" if state == "open" else "all", "sort": "updated", "direction": "desc"}
        found = []
        for item in self._pages(f"/repos/{self._repo}/pulls", params):
            head = item["head"]
            if not str(head["ref"]).startswith(head_prefix) or (head.get("repo") or {}).get("full_name") != self._repo:
                continue
            pr = self._pr(item)
            if state in ("all", "open") or pr.state == state:
                found.append(pr)
        return found

    def create_pr(self, head: str, base: str, title: str, body: str, draft: bool = True) -> PullRequest:
        """The open pull request of `head` when there is one, so a retry after a crash never opens a second."""
        existing = self.find_pr(head)
        if existing is not None:
            return existing
        payload = {"head": head, "base": base, "title": title, "body": body, "draft": draft}

        def post() -> PullRequest:
            try:
                return self._pr(self._request("POST", f"/repos/{self._repo}/pulls", json=payload).json())
            except ForgeAuthError as exc:
                if exc.status != 403:
                    raise
                raise ForgeAuthError(self._scrub(f"{_PR_REFUSED} [{exc}]"), status=403) from None

        return post_once(post, lambda: self.find_pr(head), self._pause)

    def _pause(self) -> None:
        self._sleep(self._wait(None, 0))

    def update_pr(
        self, number: int, *, title: str | None = None, body: str | None = None, draft: bool | None = None
    ) -> PullRequest:
        raw = self._get_raw(number)
        current = self._pr(raw)
        payload = {
            key: value
            for key, value, now in (("title", title, current.title), ("body", body, raw.get("body") or ""))
            if value is not None and value != now
        }
        if payload:
            self._request("PATCH", f"/repos/{self._repo}/pulls/{number}", json=payload)
        if draft is not None and draft != current.draft:
            self._graphql(_DRAFT if draft else _READY, id=raw["node_id"])
        return self.get_pr(number) if payload or (draft is not None and draft != current.draft) else current

    def close_pr(self, number: int, comment: str) -> PullRequest:
        """The comment first (an issue comment, found again by its text after a lost response, never posted twice),
        then `PATCH pulls/:n {state: closed}`. A pull request that is not open is returned as it is (L4-OPS-004)."""
        current = self.get_pr(number)
        if current.state != "open":
            return current
        path = f"/repos/{self._repo}/issues/{number}/comments"

        def find() -> dict[str, Any] | None:
            return next((c for c in self._pages(path) if str(c.get("body", "")) == comment), None)

        if find() is None:
            post_once(lambda: self._request("POST", path, json={"body": comment}).json(), find, self._pause)
        self._request("PATCH", f"/repos/{self._repo}/pulls/{number}", json={"state": "closed"})
        return self.get_pr(number)

    def merge_pr(self, number: int, *, sha: str, title: str, message: str) -> MergeCall:
        """`PUT pulls/:n/merge` with the squash method, pinned to `sha`: 200 merged, 409 the head is not `sha`, 405 and
        422 (not mergeable, squash not allowed, a rule) refused with GitHub's message. A refusal of a pull request that
        is merged by now (a lost answer, sent again) is the merge."""
        payload = {"merge_method": "squash", "sha": sha, "commit_title": title, "commit_message": message}
        try:
            reply = self._request("PUT", f"/repos/{self._repo}/pulls/{number}/merge", json=payload).json()
        except ForgeError as exc:
            if exc.status == 409:
                return MergeCall("head_moved", None, str(exc))
            if exc.status in (405, 422):
                now = self.get_pr(number)
                if now.state == "merged" and now.merge_commit_sha:
                    return MergeCall("merged", now.merge_commit_sha, "the pull request was merged already")
                return MergeCall("refused", None, str(exc))
            raise
        landed = reply.get("sha") if isinstance(reply, dict) and reply.get("merged") else None
        if not landed:
            return MergeCall("refused", None, self._scrub(f"GitHub did not merge pull request {number}: {reply}"[:200]))
        return MergeCall("merged", str(landed), f"squash-merged as {landed}")

    # --- labels -------------------------------------------------------------------------------------------------

    def ensure_labels(self, names: Sequence[str]) -> None:
        existing = {str(item["name"]) for item in self._pages(f"/repos/{self._repo}/labels")}
        for name in names:
            if name in existing:
                continue
            try:
                self._create_label(name)
            except ForgeError as exc:
                if exc.status != 422:  # `already_exists`: created meanwhile by another run
                    raise
            existing.add(name)

    def _create_label(self, name: str) -> None:
        def post() -> bool:
            self._request("POST", f"/repos/{self._repo}/labels", json={"name": name, "color": LABEL_COLOR})
            return True

        def exists() -> bool | None:
            return True if any(item["name"] == name for item in self._pages(f"/repos/{self._repo}/labels")) else None

        post_once(post, exists, self._pause)

    def set_managed_labels(self, number: int, labels: Sequence[str], prefix: str) -> PullRequest:
        """Exactly `labels` among the labels that start with `prefix`; every other label stays. No call when
        nothing differs."""
        if any(not name.startswith(prefix) for name in labels):
            raise ValueError("a managed label starts with the prefix")
        current = self.get_pr(number)
        have, want = set(current.labels), set(labels)
        add = sorted(want - have)
        remove = sorted(label for label in have - want if label.startswith(prefix))
        if not add and not remove:
            return current
        base = f"/repos/{self._repo}/issues/{number}/labels"
        if add:
            self._request("POST", base, json={"labels": add}, blind=True)  # adding a label twice is a no-op
        for name in remove:
            self._request("DELETE", f"{base}/{quote(name, safe='')}")
        return self.get_pr(number)

    # --- the project's own CI: check runs ------------------------------------------------------------------------

    def list_pipeline_jobs(self, sha: str, *, settled: bool = False) -> list[JobResult]:
        """The check runs of the commit, one per name (the newest), as `JobResult`s. The `l4` workflow's own run is
        listed like any other; the caller ignores it. `settled` reads every run (`filter=all`, not only the latest of
        each check suite) and keeps a name's newest finished one when it has one."""
        newest: dict[str, JobResult] = {}
        path = f"/repos/{self._repo}/commits/{quote(sha, safe='')}/check-runs"
        runs = sorted(
            self._pages(path, {"filter": "all"} if settled else None, key="check_runs"),
            key=lambda run: int(run["id"]), reverse=True,
        )  # fmt: skip
        for run in runs:
            job, name = self._job(run), str(run["name"])
            if name not in newest or (settled and newest[name].status in UNFINISHED and job.status not in UNFINISHED):
                newest[name] = job
        return list(newest.values())

    @staticmethod
    def _job(run: dict[str, Any]) -> JobResult:
        suite = (run.get("check_suite") or {}).get("id")
        return JobResult(
            name=str(run["name"]), stage="", status=_check_status(run.get("status"), run.get("conclusion")),
            allow_failure=False, pipeline_id=suite, job_id=int(run["id"]), web_url=str(run.get("html_url") or ""),
        )  # fmt: skip

    def job_log(self, job_id: int | str, max_lines: int = 40) -> JobLog:
        """An Actions log has no `$` echo of the job's commands: `step` is None (the job is skipped with a reason)."""
        return JobLog(self.job_log_tail(job_id, max_lines), None)

    def label_events(self, number: int) -> list[LabelEvent]:
        """`issues/:n/events`, the `labeled` and `unlabeled` ones as `LabelEvent`s, oldest first (a pull request is an
        issue here). An entry of an unknown shape is no evidence."""
        events = []
        for item in self._pages(f"/repos/{self._repo}/issues/{number}/events"):
            try:
                if item.get("event") not in ("labeled", "unlabeled"):
                    continue
                actor = item.get("actor") or {}
                events.append(
                    LabelEvent(
                        id=int(item["id"]),
                        label=str((item.get("label") or {}).get("name") or ""),
                        action="remove" if item["event"] == "unlabeled" else "add",
                        user_id=int(actor["id"]) if actor.get("id") is not None else None,
                        created_at=str(item.get("created_at") or ""),
                    )  # fmt: skip
                )
            except (KeyError, ValueError, TypeError, AttributeError):
                continue
        return sorted(events, key=lambda e: e.id)

    def member_access(self, user_id: int) -> int | None:
        """The user's repository role as GitLab's access level (`_ROLE_LEVELS`): `GET /user/:id` for the login, then
        the collaborator permission. None for a user who is no collaborator (404) or a role this does not know."""
        try:
            login = str(self._request("GET", f"/user/{int(user_id)}").json()["login"])
            permission = self._request(
                "GET", f"/repos/{self._repo}/collaborators/{quote(login, safe='')}/permission"
            ).json()
        except ForgeNotFound:
            return None
        except (ValueError, KeyError, TypeError):
            return None
        role = permission.get("role_name") or permission.get("permission") if isinstance(permission, dict) else None
        return _ROLE_LEVELS.get(str(role))

    def own_user_id(self) -> int | None:
        """The user the token acts as; None when it cannot be told (`resume_label` then honours no label)."""
        try:
            return self._identity()[1]
        except ForgeError:
            return None

    def dispatch_continuation(self, ref: str) -> Continuation:
        """One more run of the `l4` workflow on `ref`, unless one is already waiting (L4-GHP-004). The dispatch event
        starts a run even when the GITHUB_TOKEN sends it (the only event type besides repository_dispatch that does)."""
        base = f"/repos/{self._repo}/actions/workflows/{WORKFLOW_FILE}"
        queued = self._request("GET", f"{base}/runs", params={"branch": ref, "status": "queued", "per_page": 1}).json()
        if isinstance(queued, dict) and int(queued.get("total_count") or 0) > 0:
            return "already_queued"
        self._request("POST", f"{base}/dispatches", json={"ref": ref})
        return "dispatched"

    def start_run(self, ref: str) -> StartRun:
        """The dispatch of `dispatch_continuation` in the words of L4-OPS-002: `dispatched` is `started`; a token that
        may not dispatch (401, 403) is `refused`; no `l4.yml` on the ref (404) is `unsupported`."""
        try:
            answer = self.dispatch_continuation(ref)
        except ForgeAuthError:
            return "refused"
        except ForgeNotFound:
            return "unsupported"
        return "started" if answer == "dispatched" else answer

    def job_log_tail(self, job_id: int | str, max_lines: int = 40) -> str:
        """`actions/jobs/:id/logs` answers with a redirect to a pre-signed URL; it is followed without the token
        (another host, and the URL is the credential). '' when there is no log: a check run of another app is no
        Actions job, and logs expire."""
        url = f"{self._api}/repos/{self._repo}/actions/jobs/{int(job_id)}/logs"
        headers = {"Authorization": f"Bearer {self._token}", "Accept": "application/vnd.github+json",
                   "X-GitHub-Api-Version": API_VERSION}  # fmt: skip
        try:
            with httpx.Client(transport=self._transport, timeout=TIMEOUT_S, follow_redirects=False) as client:
                first = client.get(url, headers=headers)
                if first.status_code == 200:
                    return clip_log(first.text, max_lines)
                location = first.headers.get("Location", "")
                if first.status_code not in (301, 302, 303, 307, 308) or urlsplit(location).scheme != "https":
                    return ""  # nothing to read, or a downgrade the token must not follow
                second = client.get(location)  # no Authorization header: a fresh request on a pre-signed URL
        except httpx.TransportError:
            return ""
        return clip_log(second.text, max_lines) if second.status_code == 200 else ""

    # --- the sticky comment -------------------------------------------------------------------------------------

    def _identity(self) -> tuple[str, int]:
        """(login, id) of the token's user: `GET /user`; for a job's GITHUB_TOKEN, which that answers with 403, the
        Actions bot (L4-GHP-001). Anything else is an error: the sticky note is never matched without an author."""
        if self._who is None:
            try:
                user = self._request("GET", "/user").json()
                self._who = (str(user["login"]), int(user["id"]))
            except ForgeAuthError as exc:
                if exc.status == 403 and self._environ.get("GITHUB_ACTIONS") == "true":
                    self._who = (ACTIONS_BOT_LOGIN, ACTIONS_BOT_ID)
                else:
                    raise ForgeError("GitHub: cannot tell which user the token belongs to (GET /user failed)") from None
            except (ForgeError, KeyError, TypeError, ValueError):
                raise ForgeError("GitHub: cannot tell which user the token belongs to (GET /user failed)") from None
        return self._who

    def _me(self) -> str:
        return self._identity()[0]

    def upsert_sticky_note(self, number: int, body: str) -> None:
        """An issue comment by the token's own user (login and id together) that starts with the marker: a marker quoted
        or planted by someone else is never rewritten."""
        text = f"{STICKY_MARKER}\n{body}"
        me, my_id = self._identity()
        path = f"/repos/{self._repo}/issues/{number}/comments"

        def find() -> dict[str, Any] | None:
            return next(
                (
                    c for c in self._pages(path)
                    if (c.get("user") or {}).get("login") == me and (c.get("user") or {}).get("id") == my_id
                    and str(c.get("body", "")).startswith(STICKY_MARKER)
                ),
                None,
            )  # fmt: skip

        mine = find()
        if mine is None:  # a lost response is read back by the marker: never a second comment
            mine = post_once(lambda: self._request("POST", path, json={"body": text}).json(), find, self._pause)
        if mine["body"] != text:
            self._request("PATCH", f"/repos/{self._repo}/issues/comments/{mine['id']}", json={"body": text})
