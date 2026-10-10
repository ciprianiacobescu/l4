#!/usr/bin/env python3
"""Is the l4 runner idle? The quiet-window check before a push that starts l4 jobs (M1.13, W-C6).

    l4_idle.py [--project ID ...] [--quiet-minutes N] [--retries N]

Exit 0: idle (no `l4` job running, pending or created in the projects, and the last commit of `main` of the first
project is older than the quiet window). Exit 1: busy. Exit 2: unknown, because the API did not answer: a 502 of the
Mintkey proxy ("vault error", intermittent) is retried with a backoff, and a 502 that lasts is *unknown*, never *busy*
(wave C: the owner's idle.py read every failed call as busy). Any other failure is unknown at once. GitLab is read only
through `scripts/dev/mk-gitlab-api.sh`, which also retries a 502 itself.
"""

import argparse
import json
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
MK_SCRIPT = str(HERE / "mk-gitlab-api.sh")
PROJECTS = (118, 119)  # the harness's own and the dummy project of the live runs
RETRIES = 3
WAIT_S = 2.0
QUIET_MINUTES = 15.0
BUSY_STATES = ("running", "pending", "created")


class ApiError(Exception):
    def __init__(self, status: int, path: str) -> None:
        super().__init__(f"HTTP {status} GET {path}")
        self.status, self.path = status, path


@dataclass(frozen=True)
class Verdict:
    state: str  # idle | busy | unknown
    text: str

    @property
    def code(self) -> int:
        return {"idle": 0, "busy": 1}.get(self.state, 2)


def mk_get(script: str | None = None) -> Callable[[str], Any]:
    """`get(path)` through the Mintkey wrapper: the parsed JSON, or an `ApiError` carrying the status the script said."""
    exe = script or MK_SCRIPT

    def get(path: str) -> Any:
        done = subprocess.run([exe, "GET", path], capture_output=True, text=True, check=False)
        if done.returncode != 0:
            status = 0
            for line in done.stderr.splitlines():
                parts = line.split()
                if len(parts) >= 2 and parts[0] == "HTTP" and parts[1].isdigit():
                    status = int(parts[1])
            raise ApiError(status, path)
        return json.loads(done.stdout)

    return get


def _retrying(get: Callable[[str], Any], path: str, retries: int, wait: float, sleep: Callable[[float], None]) -> Any:
    for attempt in range(retries + 1):
        try:
            return get(path)
        except ApiError as exc:
            if exc.status != 502 or attempt == retries:
                raise
            sleep(wait * (attempt + 1))
    raise AssertionError("unreachable")


def check(
    get: Callable[[str], Any],
    *,
    now: datetime,
    projects: tuple[int, ...] = PROJECTS,
    quiet_minutes: float = QUIET_MINUTES,
    retries: int = RETRIES,
    wait: float = WAIT_S,
    sleep: Callable[[float], None] = time.sleep,
) -> Verdict:
    def call(path: str) -> Any:
        return _retrying(get, path, retries, wait, sleep)

    try:
        busy = []
        for project in projects:
            for status in ("running", "pending"):
                for pipeline in call(f"projects/{project}/pipelines?status={status}&per_page=20"):
                    for job in call(f"projects/{project}/pipelines/{pipeline['id']}/jobs?per_page=50"):
                        if job["name"] == "l4" and job["status"] in BUSY_STATES:
                            busy.append(f"project {project} job {job['id']} {job['status']}")
        if busy:
            return Verdict("busy", "busy: " + "; ".join(busy))
        last = call(f"projects/{projects[0]}/repository/commits?ref_name=main&per_page=1")[0]
        age = (now - datetime.fromisoformat(last["created_at"])).total_seconds() / 60
        if age < quiet_minutes:
            return Verdict("busy", f"busy: the last commit of main ({last['short_id']}) is {age:.1f} min old")
        return Verdict("idle", f"idle: no l4 job, the last commit of main ({last['short_id']}) is {age:.1f} min old")
    except ApiError as exc:
        what = "the proxy kept answering 502" if exc.status == 502 else f"the API answered {exc.status or 'nothing'}"
        return Verdict("unknown", f"unknown: {what} ({exc.path}); not treated as busy")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--project", type=int, action="append", help="project id (default: 118 and 119)")
    parser.add_argument("--quiet-minutes", type=float, default=QUIET_MINUTES)
    parser.add_argument("--retries", type=int, default=RETRIES, help="more tries after a 502 (default 3)")
    args = parser.parse_args(argv)
    verdict = check(
        mk_get(), now=datetime.now(UTC), projects=tuple(args.project or PROJECTS),
        quiet_minutes=args.quiet_minutes, retries=args.retries, sleep=time.sleep,
    )  # fmt: skip
    print(verdict.text)
    return verdict.code


if __name__ == "__main__":
    sys.exit(main())
