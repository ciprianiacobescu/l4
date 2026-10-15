"""Whether the process runs in a CI job: one rule for the doctor and the readiness judge's sandbox choice."""

from collections.abc import Mapping


def in_ci(environ: Mapping[str, str]) -> bool:
    return environ.get("GITLAB_CI") == "true" or environ.get("GITHUB_ACTIONS") == "true" or environ.get("CI") == "true"
