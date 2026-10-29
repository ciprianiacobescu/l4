"""Whether the process runs in a CI job (L4-CLI-004): `in_ci_job` is the one rule for every decision; `ci_like` also
counts `CI=true` alone, only where that is a deliberate opt-in."""

from collections.abc import Mapping


def in_ci_job(environ: Mapping[str, str]) -> bool:
    """True inside a GitLab CI or GitHub Actions job (`GITLAB_CI` or `GITHUB_ACTIONS` is `true`); `CI=true` on a
    person's machine is not a job."""
    return environ.get("GITLAB_CI") == "true" or environ.get("GITHUB_ACTIONS") == "true"


def ci_like(environ: Mapping[str, str]) -> bool:
    """A job, or `CI=true` alone: the opt-in reading of the gate environment (L4-SEC-040), the judges' fail-closed
    sandbox fallbacks and the doctor's tool severity."""
    return in_ci_job(environ) or environ.get("CI") == "true"
