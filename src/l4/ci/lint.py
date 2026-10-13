"""Checks on a rendered GitHub workflow (forge-and-ci 2.17, L4-CI-001..003): what must never be true of an l4 job.

Structural only, from the parsed YAML. `actionlint` is the syntax and expression linter; this is the harness's own
policy, so a hand edit or a future template change cannot reopen a hole.
"""

from typing import Any

import yaml

UNTRUSTED_TRIGGERS = ("pull_request", "pull_request_target", "issue_comment", "issues", "workflow_run")


def _triggers(document: dict[Any, Any]) -> set[str]:
    on = document.get("on", document.get(True))  # YAML 1.1 reads the key `on` as the boolean True
    if isinstance(on, str):
        return {on}
    if isinstance(on, list):
        return {str(item) for item in on}
    return {str(key) for key in on} if isinstance(on, dict) else set()


def lint_github_yaml(text: str) -> list[str]:
    """Problems found, empty when the workflow is acceptable."""
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError:
        return ["the workflow is not valid YAML"]
    if not isinstance(document, dict) or not isinstance(document.get("jobs"), dict):
        return ["the workflow has no jobs"]
    problems = [
        f"trigger {name} lets untrusted events run the harness (L4-CI-003)"
        for name in sorted(_triggers(document) & set(UNTRUSTED_TRIGGERS))
    ]
    if "permissions" not in document:
        problems.append("the workflow sets no permissions")
    for job_id, job in document["jobs"].items():
        if not isinstance(job, dict):
            problems.append(f"job {job_id} is not a mapping")
            continue
        concurrency = job.get("concurrency", document.get("concurrency"))
        if concurrency is None:
            problems.append(f"job {job_id} has no concurrency group")
        elif isinstance(concurrency, dict) and concurrency.get("cancel-in-progress") not in (False, None):
            problems.append(f"job {job_id} cancels runs in progress: a cancelled push would lose work")
        if "timeout-minutes" not in job:
            problems.append(f"job {job_id} has no timeout-minutes")
        for step in job.get("steps") or []:
            uses = str(step.get("uses", "")) if isinstance(step, dict) else ""
            if uses.startswith("actions/checkout") and (step.get("with") or {}).get("persist-credentials") is not False:
                problems.append(f"job {job_id}: checkout must set persist-credentials: false")
    return problems
