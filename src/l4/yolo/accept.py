"""`l4 yolo accept`: who is asking, what the target's configuration allows, and when an acceptance holds
(review-resolution design D7, section 8). Contract only: the bodies come in wave 1."""

from collections.abc import Mapping

from l4.config.schema import YoloReviewCfg
from l4.vcs.git import Git
from l4.yolo.model import PlanState


def actor(environ: Mapping[str, str], stdin_tty: bool) -> tuple[str, str | None]:
    """`("person", None)` or `("agent", <marker>)`."""
    raise NotImplementedError


def target_config(git: Git, ref: str) -> YoloReviewCfg:
    """`yolo.review` of `.l4/config.yaml` at `ref` (defaults when the file is absent or invalid)."""
    raise NotImplementedError


def holds(state: PlanState, latest_review: Mapping[str, object]) -> dict[str, bool]:
    """Per accepted subject: the latest review's entry has the same `material` and `findings_sha`."""
    raise NotImplementedError
