"""A reviewed plan with a judge's blocking finding on `batch:b1`, for the overrule tests: the shapes of
`yolo_review_events`, with the batch entry carrying a `material` and the unit digests it judged."""

from l4.yolo.digest import plan_digest
from l4.yolo.findings import finding_id
from l4.yolo.model import PlanEvent

from .yolo_cmd_world import A, B, CmdWorld, ev

BATCH = "batch:b1"
FALSE_BLOCKING = {
    "criterion": "missing_dependency",
    "severity": "blocking",
    "text": "two units list themselves in depends_on",
}
MAJOR = {"criterion": "testability", "severity": "major", "text": "no scenario gives an output"}
MINOR = {"criterion": "outcome", "severity": "minor", "text": "the outcome could be clearer"}
SCHEMA_BLOCK = {"criterion": "schema", "severity": "blocking", "text": "schema_invalid: the judge's answer"}
REASON = "no unit lists itself; checked the plan file"


def batch_entry(world: CmdWorld, findings, verdict="NEEDS_REVISION", material="m-b1") -> dict:
    return {
        "verdict": verdict,
        "digest": None,
        "digests": {A: world.digest(A), B: world.digest(B)},
        "material": material,
        "findings": [dict(f) for f in findings],
    }


def reviewed_with(world: CmdWorld, findings=(FALSE_BLOCKING,), verdict="NEEDS_REVISION", material="m-b1") -> PlanEvent:
    """The plan pushed, admitted and reviewed: A and B READY, `batch:b1` judged `verdict` with `findings`."""
    world.push_plan()
    review = world.reviewed()
    review.data["batches"]["b1"] = batch_entry(world, findings, verdict, material)
    for unit in (A, B):
        review.data["units"][unit]["material"] = f"m-{unit}"
    world.seed("p1", ev("plan.admitted", plan_digest=plan_digest(world.plan_text), order=[A, B]), review)
    return review


def fid(finding=FALSE_BLOCKING, subject=BATCH) -> str:
    return finding_id(subject, finding)


def overruled_event(finding=FALSE_BLOCKING, subject=BATCH, material="m-b1", by="alex@example.com", actor="person"):
    return ev(
        "plan.finding_overruled", finding=fid(finding, subject), subject=subject, criterion=finding["criterion"],
        severity=finding["severity"], text=finding["text"], material=material, reason=REASON, by=by, actor=actor,
        marker=None, confirmed="typed",
    )  # fmt: skip
