"""The harness that runs in CI is the pin of the base's workflow (adoption-lessons L4-ADO-005).

A scheduled run uses the default branch's copy of `.github/workflows/l4.yml`; a base that moved on leaves it on an old
harness. `pin_check` says whether the running harness is the base's pin (doctor's CFG-008 prints it), and
`stale_pin_stop` is what `l4 plan --sweep` and `l4 run` call first: on a mismatch they do no work, print a
`::warning::` annotation naming both commits and the fix, and exit 0, so a schedule neither acts with the old harness
nor turns red every time it fires."""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from l4.buildinfo import harness_commit
from l4.ci.github import WORKFLOW_RELPATH
from l4.config.schema import L4Config, effective_delivery
from l4.init.action import read_pin

FIX = (
    f"update {WORKFLOW_RELPATH} on the default branch to the base's copy (merge it, or `l4 upgrade` and copy the "
    "file there)"
)


@dataclass(frozen=True)
class PinCheck:
    status: Literal["skip", "pass", "mismatch"]
    reason: str  # why it was skipped, or what passed
    running: str | None = None
    pinned: str | None = None

    @property
    def problem(self) -> str:
        return (
            f"this job runs the harness {self.running} but {WORKFLOW_RELPATH} on the base pins {self.pinned}: the run "
            "is on a copy of the workflow that is not the base's (a scheduled run uses the default branch's copy)"
        )


def pin_check(cfg: L4Config, repo: Path, environ: Mapping[str, str], running: str | None) -> PinCheck:
    """`running`: the commit of the harness that is running (`harness_commit()`), None when unknown."""
    if environ.get("GITHUB_ACTIONS") != "true":
        return PinCheck("skip", "applies to CI jobs only")
    delivery = effective_delivery(cfg)
    if delivery != "action":
        return PinCheck("skip", f"harness.delivery is {delivery}, not action")
    if running is None:
        return PinCheck("skip", "the running harness has no known commit")
    try:
        found = read_pin((repo / WORKFLOW_RELPATH).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return PinCheck("skip", f"{WORKFLOW_RELPATH} cannot be read (CFG-006 says so)")
    pinned = found.effective if found is not None else None
    if pinned is None:
        return PinCheck("skip", f"{WORKFLOW_RELPATH} names no pin (CFG-006 says so)")
    if pinned == running:
        return PinCheck("pass", f"the running harness is the base's pin, {running[:12]}", running, pinned)
    return PinCheck("mismatch", "", running, pinned)


def stale_pin_stop(cfg: L4Config, repo: Path, environ: Mapping[str, str]) -> str | None:
    """The `::warning::` line when this run must do no work, else None."""
    check = pin_check(cfg, repo, environ, harness_commit())
    if check.status != "mismatch":
        return None
    return f"::warning::l4 does no work in this run: {check.problem}. To fix it, {FIX}."
