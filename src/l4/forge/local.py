"""The `Forge` Protocol in memory (simulation-harness 1.1, forge-and-ci 2.12): the fake forge of `l4 simulate`.

Optionally persisted as one JSON file under a directory, so a second process (a killed run and its successor) sees
the same pull requests. Every call is logged for tests ("zero forge writes in a dry run", "no merge under
`merge_policy: human`"). Nothing here touches the network.
"""

import json
import os
import subprocess
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from l4.forge.base import (
    UNFINISHED,
    Continuation,
    ForgeError,
    ForgeNotFound,
    JobLog,
    JobResult,
    LabelEvent,
    MergeCall,
    PrState,
    PullRequest,
    StartRun,
    clip_log,
)

STATE_FILENAME = "forge.json"
WRITE_CALLS = frozenset(
    {
        "ensure_labels",
        "create_pr",
        "update_pr",
        "set_managed_labels",
        "upsert_sticky_note",
        "merge",
        "close",
        "start_run",
        "close_pr",
    }
)


@dataclass(frozen=True)
class Call:
    name: str
    args: tuple[Any, ...]


class LocalForge:
    def __init__(
        self, directory: Path | None = None, *, url: str = "local://forge", origin: Path | None = None
    ) -> None:
        self._dir = directory
        self._origin = origin  # the repository whose branches `merge_pr` squashes into (a bare origin in tests)
        self._url = url.rstrip("/")
        self.calls: list[Call] = []
        self._prs: dict[int, dict[str, Any]] = {}
        self._labels: list[str] = []
        self._notes: dict[int, str] = {}
        self._comments: dict[int, list[str]] = {}  # MR number -> the comments of `close_pr`
        self._jobs: dict[str, list[dict[str, Any]]] = {}  # sha -> scripted CI jobs (JobResult fields)
        self._tails: dict[int, str] = {}  # job id -> its log
        self._steps: dict[int, str] = {}  # job id -> the command its step_script ran last (scripted)
        self._label_events: dict[int, list[dict[str, Any]]] = {}  # MR number -> scripted label events
        self._members: dict[int, int] = {}  # user id -> access level (scripted)
        self._own_id: int | None = None  # the user the harness's token acts as (scripted)
        self._start_result: StartRun = "unsupported"  # what `start_run` answers (scripted)
        if directory is not None and (directory / STATE_FILENAME).is_file():
            state = json.loads((directory / STATE_FILENAME).read_text(encoding="utf-8"))
            self._prs = {int(k): v for k, v in state["prs"].items()}
            self._labels, self._notes = state["labels"], {int(k): v for k, v in state["notes"].items()}
            self._jobs = state.get("jobs", {})
            self._tails = {int(k): v for k, v in state.get("tails", {}).items()}
            self._steps = {int(k): v for k, v in state.get("steps", {}).items()}
            self._label_events = {int(k): v for k, v in state.get("label_events", {}).items()}
            self._members = {int(k): int(v) for k, v in state.get("members", {}).items()}
            self._own_id = state.get("own_id")
            self._comments = {int(k): v for k, v in state.get("comments", {}).items()}

    # --- bookkeeping ---

    def _log(self, name: str, *args: Any) -> None:
        self.calls.append(Call(name, args))

    def writes(self) -> list[Call]:
        return [c for c in self.calls if c.name in WRITE_CALLS]

    def called(self, name: str) -> list[Call]:
        return [c for c in self.calls if c.name == name]

    def _save(self) -> None:
        if self._dir is None:
            return
        self._dir.mkdir(parents=True, exist_ok=True)
        state = {
            "prs": self._prs, "labels": self._labels, "notes": self._notes, "jobs": self._jobs, "tails": self._tails,
            "steps": self._steps, "label_events": self._label_events, "members": self._members,
            "own_id": self._own_id, "comments": self._comments,
        }  # fmt: skip
        fd, tmp = tempfile.mkstemp(dir=self._dir, prefix=".forge-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(state, handle, sort_keys=True, indent=2)
            os.replace(tmp, self._dir / STATE_FILENAME)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    def _view(self, number: int) -> PullRequest:
        raw = self._prs.get(number)
        if raw is None:
            raise ForgeNotFound(f"local forge: no pull request {number}", status=404)
        return PullRequest(
            number=number, url=f"{self._url}/pull/{number}", head_branch=raw["head"], base_branch=raw["base"],
            title=raw["title"], draft=raw["draft"], state=raw["state"], labels=tuple(raw["labels"]),
            merge_commit_sha=raw.get("merge_commit_sha"),
        )  # fmt: skip

    def note(self, number: int) -> str | None:
        """The sticky note's body as a human would read it (without the marker line)."""
        return self._notes.get(number)

    # --- the Forge Protocol ---

    def project_url(self) -> str:
        self._log("project_url")
        return self._url

    def ensure_labels(self, names: Sequence[str]) -> None:
        self._log("ensure_labels", tuple(names))
        changed = [n for n in names if n not in self._labels]
        if changed:
            self._labels.extend(changed)
            self._save()

    def find_pr(self, head_branch: str) -> PullRequest | None:
        self._log("find_pr", head_branch)
        found = [n for n, p in self._prs.items() if p["head"] == head_branch and p["state"] == "open"]
        return self._view(min(found)) if found else None

    def get_pr(self, number: int) -> PullRequest:
        self._log("get_pr", number)
        return self._view(number)

    def list_prs(self, head_prefix: str, state: PrState = "all") -> list[PullRequest]:
        self._log("list_prs", head_prefix, state)
        numbers = [
            n for n, p in self._prs.items()
            if p["head"].startswith(head_prefix) and state in ("all", p["state"])
        ]  # fmt: skip
        return [self._view(n) for n in sorted(numbers, reverse=True)]

    def create_pr(self, head: str, base: str, title: str, body: str, draft: bool = True) -> PullRequest:
        self._log("create_pr", head, base, title, body, draft)
        existing = next((n for n, p in self._prs.items() if p["head"] == head and p["state"] == "open"), None)
        if existing is not None:
            return self._view(existing)
        number = max(self._prs, default=0) + 1
        self._prs[number] = {
            "head": head, "base": base, "title": title, "body": body, "draft": draft, "state": "open", "labels": [],
        }  # fmt: skip
        self._save()
        return self._view(number)

    def update_pr(
        self, number: int, *, title: str | None = None, body: str | None = None, draft: bool | None = None
    ) -> PullRequest:
        self._log("update_pr", number, title, body, draft)
        raw = self._prs.get(number)
        if raw is None:
            raise ForgeNotFound(f"local forge: no pull request {number}", status=404)
        for key, value in (("title", title), ("body", body), ("draft", draft)):
            if value is not None:
                raw[key] = value
        self._save()
        return self._view(number)

    def set_managed_labels(self, number: int, labels: Sequence[str], prefix: str) -> PullRequest:
        self._log("set_managed_labels", number, tuple(labels), prefix)
        if any(not name.startswith(prefix) for name in labels):
            raise ValueError("a managed label starts with the prefix")
        raw = self._prs.get(number)
        if raw is None:
            raise ForgeNotFound(f"local forge: no pull request {number}", status=404)
        kept = [label for label in raw["labels"] if not label.startswith(prefix)]
        raw["labels"] = [*kept, *sorted(set(labels))]
        self._save()
        return self._view(number)

    def upsert_sticky_note(self, number: int, body: str) -> None:
        self._log("upsert_sticky_note", number, body)
        if number not in self._prs:
            raise ForgeNotFound(f"local forge: no pull request {number}", status=404)
        if self._notes.get(number) != body:
            self._notes[number] = body
            self._save()

    def list_pipeline_jobs(self, sha: str, *, settled: bool = False) -> list[JobResult]:
        """The scripted jobs; `settled`: one per name, the newest (last scripted) finished one, if any."""
        self._log("list_pipeline_jobs", sha, settled)
        jobs = [JobResult(**job) for job in self._jobs.get(sha, [])]
        if not settled:
            return jobs
        newest: dict[str, JobResult] = {}
        for job in reversed(jobs):
            kept = newest.get(job.name)
            if kept is None or (kept.status in UNFINISHED and job.status not in UNFINISHED):
                newest[job.name] = job
        return list(newest.values())

    def job_log_tail(self, job_id: int | str, max_lines: int = 40) -> str:
        self._log("job_log_tail", job_id, max_lines)
        return clip_log(self._tails.get(int(job_id), ""), max_lines) if int(job_id) in self._tails else ""

    def job_log(self, job_id: int | str, max_lines: int = 40) -> JobLog:
        return JobLog(self.job_log_tail(job_id, max_lines), self._steps.get(int(job_id)))

    def label_events(self, number: int) -> list[LabelEvent]:
        self._log("label_events", number)
        return [LabelEvent(**e) for e in self._label_events.get(number, [])]

    def member_access(self, user_id: int) -> int | None:
        self._log("member_access", user_id)
        return self._members.get(int(user_id))

    def own_user_id(self) -> int | None:
        self._log("own_user_id")
        return self._own_id

    def dispatch_continuation(self, ref: str) -> Continuation:
        self._log("dispatch_continuation", ref)
        return "unsupported"

    def start_run(self, ref: str) -> StartRun:
        self._log("start_run", ref)
        return self._start_result

    def script_start_run(self, result: StartRun) -> None:
        """What the next `start_run` answers (the default is `unsupported`, as for `dispatch_continuation`)."""
        self._start_result = result

    def close_pr(self, number: int, comment: str) -> PullRequest:
        self._log("close_pr", number, comment)
        raw = self._prs.get(number)
        if raw is None:
            raise ForgeNotFound(f"local forge: no pull request {number}", status=404)
        if raw["state"] == "open":
            self._comments.setdefault(number, []).append(comment)
            raw["state"] = "closed"
            self._save()
        return self._view(number)

    def comments(self, number: int) -> list[str]:
        """The comments the harness posted with `close_pr`, oldest first."""
        return list(self._comments.get(number, []))

    # --- what a human does (simulation only) ---

    def script_label_event(
        self, number: int, label: str, *, user_id: int | None, action: str = "add", created_at: str = ""
    ) -> int:
        """A person (or the bot) adds or removes a label on the pull request; the event id is returned."""
        events = self._label_events.setdefault(number, [])
        event_id = 1 + sum(len(v) for v in self._label_events.values())
        events.append({"id": event_id, "label": label, "action": action, "user_id": user_id, "created_at": created_at})
        raw = self._prs[number]
        if action == "add" and label not in raw["labels"]:
            raw["labels"] = [*raw["labels"], label]
        elif action == "remove" and label in raw["labels"]:
            raw["labels"] = [x for x in raw["labels"] if x != label]
        self._save()
        return event_id

    def script_member(self, user_id: int, access_level: int, *, own: bool = False) -> None:
        """The project's members: `own` marks the user the harness's token acts as."""
        self._members[int(user_id)] = int(access_level)
        if own:
            self._own_id = int(user_id)
        self._save()

    def script_jobs(
        self,
        sha: str,
        jobs: Sequence[tuple],
        *,
        tails: dict[str, str] | None = None,
        steps: dict[str, str] | None = None,
    ) -> None:
        """The project's CI for `sha`: `(name, status[, {stage, allow_failure}])` per job, and some logs by name."""
        listed = self._jobs.setdefault(sha, [])
        for spec in jobs:
            name, status, extra = (*spec, {})[:3]
            job_id = 1 + sum(len(v) for v in self._jobs.values())
            listed.append({
                "name": name, "stage": extra.get("stage", "test"), "status": status,
                "allow_failure": extra.get("allow_failure", False), "pipeline_id": 1, "job_id": job_id,
                "web_url": f"{self._url}/jobs/{job_id}",
            })  # fmt: skip
            if tails and name in tails:
                self._tails[job_id] = tails[name]
            if steps and name in steps:
                self._steps[job_id] = steps[name]
        self._save()

    def merge(self, number: int, merge_commit_sha: str | None = None) -> PullRequest:
        """A human merges the pull request; a real forge does this outside the harness."""
        self._log("merge", number)
        raw = self._prs[number]
        raw.update(state="merged", draft=False, merge_commit_sha=merge_commit_sha)
        self._save()
        return self._view(number)

    def merge_pr(self, number: int, *, sha: str, title: str, message: str) -> MergeCall:
        """The squash merge on the origin repository (squash-and-delete D2): one commit with the head's tree whose
        parent is the target tip, the target ref moved to it, the pull request merged with that commit. `head_moved`
        when `sha` is not the tip of the pull request's branch."""
        self._log("merge", number)
        raw = self._prs.get(number)
        if raw is None:
            raise ForgeNotFound(f"local forge: no pull request {number}", status=404)
        if self._origin is None:
            raise ForgeError("local forge: merge_pr needs an origin repository")
        branch, target = f"refs/heads/{raw['head']}", f"refs/heads/{raw['base']}"
        if self._git("rev-parse", "--verify", "-q", branch) != sha:
            return MergeCall("head_moved", None, f"{raw['head']} is not at {sha[:10]}")
        tip = self._git("rev-parse", "--verify", target)
        commit = self._git("commit-tree", f"{sha}^{{tree}}", "-p", tip, "-m", f"{title}\n\n{message}")
        self._git("update-ref", target, commit, tip)
        raw.update(state="merged", draft=False, merge_commit_sha=commit)
        self._save()
        return MergeCall("merged", commit, f"squash-merged as {commit}")

    def _git(self, *args: str) -> str:
        env = {
            **os.environ, "GIT_AUTHOR_NAME": "local forge", "GIT_AUTHOR_EMAIL": "forge@local.invalid",
            "GIT_COMMITTER_NAME": "local forge", "GIT_COMMITTER_EMAIL": "forge@local.invalid",
        }  # fmt: skip
        done = subprocess.run(
            ["git", "-C", str(self._origin), *args], env=env, capture_output=True, text=True, check=False
        )
        return done.stdout.strip() if done.returncode == 0 else ""

    def close(self, number: int) -> PullRequest:
        self._log("close", number)
        self._prs[number]["state"] = "closed"
        self._save()
        return self._view(number)
