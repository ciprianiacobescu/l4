"""Recorded reviews for the `l4 yolo findings|accept|activate|status` tests (review-resolution wave 2): a
`plan.reviewed` whose entries carry the material keys, built on the `yolo_cmd_world` repository."""

from collections.abc import Mapping, Sequence
from typing import Any

from l4.yolo.digest import plan_digest
from l4.yolo.model import PlanEvent
from l4.yolo.readiness import PROMPT_VERSION

from .yolo_cmd_world import A, B, CmdWorld

TESTABILITY = {"criterion": "testability", "severity": "major", "text": "no scenario gives an input and an output"}
OUTCOME = {"criterion": "outcome", "severity": "minor", "text": "the outcome could be clearer"}
FAILURES = {"criterion": "failure_cases", "severity": "major", "text": "bad input is not described"}
INTERFACES = {"criterion": "interfaces", "severity": "major", "text": "the signature of greet() is open"}
BLOCKING = {"criterion": "contradiction", "severity": "blocking", "text": "A contradicts B"}
MATERIAL = {"criterion": "material", "severity": "blocking", "text": "material_cut: design.md has 26000 characters"}


def entry(
    world: CmdWorld,
    unit: str,
    verdict: str,
    findings: Sequence[Mapping[str, Any]],
    material: str,
    digest: str | None = None,
) -> dict[str, Any]:
    return {
        "verdict": verdict,
        "digest": digest or world.digest(unit),
        "material": material,
        "findings": [dict(f) for f in findings],
    }


def review(
    world: CmdWorld, at: str, units: Mapping[str, dict[str, Any]], batches: Mapping[str, dict[str, Any]] | None = None
) -> PlanEvent:
    """A `plan.reviewed` for the pushed plan file; the units not given are READY."""
    rows = {u: entry(world, u, "READY", [], f"m-{u}") for u in (A, B)}
    rows.update(units)
    return PlanEvent(
        "plan.reviewed",
        at,
        {
            "plan_digest": plan_digest(world.plan_text),
            "prompt_version": PROMPT_VERSION,
            "units": rows,
            "batches": dict(batches or {"b1": {"verdict": "READY", "digest": None, "findings": []}}),
        },
    )


def two_rounds(
    world: CmdWorld, findings: Sequence[Mapping[str, Any]], *, unit: str = A, verdict: str = "NEEDS_REVISION"
) -> None:
    """The unit judged on two versions of its text (the first under a made-up digest), the latest on the real one."""
    for at, digest, material in (("2026-10-14T10:00:00Z", "old-digest", "m1"), ("2026-10-14T11:00:00Z", None, "m2")):
        world.seed("p1", review(world, at, {unit: entry(world, unit, verdict, findings, material, digest)}))
