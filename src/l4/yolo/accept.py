"""`l4 yolo accept`: who is asking, what the target's configuration allows, and when an acceptance holds
(review-resolution design D7, section 8). Pure rules; the command (yolo/commands.py) records the events."""

import json
import logging
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from l4.config.loader import load_config
from l4.config.schema import YoloReviewCfg
from l4.exitcodes import L4Exit
from l4.vcs.git import Git, GitError
from l4.yolo import findings as findings_mod
from l4.yolo.model import PlanState

log = logging.getLogger("l4.yolo.accept")

# The first one found is named. The harness cannot know who types a command: these keep honest agents from deciding
# for a person; they are not a security boundary (design D7.2).
AGENT_MARKERS = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "AI_AGENT", "CODEX_SANDBOX", "L4_RESULT_PATH")
_RESTARTABLE_STOPS = ("inputs_changed", "unit_rejected")  # the stopped plans a review can still be made on
_BEFORE_ACTIVATION = ("new", "refused", "admitted", "reviewed")
_HARNESS_CRITERIA = ("schema", "unit_missing", "completeness")
_CONFIG_PATH = ".l4/config.yaml"


@dataclass(frozen=True)
class Refusal:
    """Why `l4 yolo accept` refuses: the cause, and what clears it (the caller prefixes `accept: `)."""

    message: str
    fix: str


def actor(environ: Mapping[str, str], stdin_tty: bool) -> tuple[str, str | None]:
    """`("person", None)` or `("agent", <marker>)`: a person is a terminal on stdin and no marker; stdout is not
    looked at, so `l4 yolo accept ... | tee log` stays a person's command."""
    for marker in AGENT_MARKERS:
        if environ.get(marker):
            return "agent", marker
    return ("person", None) if stdin_tty else ("agent", None)


def target_config(git: Git, ref: str) -> YoloReviewCfg:
    """`yolo.review` of `.l4/config.yaml` at `ref` (defaults when the file is absent or invalid)."""
    try:
        shown = git.run("show", f"{ref}:{_CONFIG_PATH}", check=False)
    except GitError as exc:
        log.warning("accept: cannot read %s at %s (%s): the default yolo.review applies", _CONFIG_PATH, ref, exc)
        return YoloReviewCfg()
    if shown.returncode != 0:
        log.debug("accept: no %s at %s: the default yolo.review applies", _CONFIG_PATH, ref)
        return YoloReviewCfg()
    with tempfile.TemporaryDirectory(prefix="l4-accept-") as tmp:
        path = Path(tmp) / "config.yaml"
        path.write_text(shown.stdout, encoding="utf-8")
        try:
            return load_config(Path(tmp), config_path=path).yolo.review
        except L4Exit as exc:  # ConfigSchemaError: the harness's own message names the position
            log.warning(
                "accept: %s at %s is not a valid config (%s): the default yolo.review applies", _CONFIG_PATH, ref, exc
            )
            return YoloReviewCfg()


def _version(entry: Mapping[str, Any]) -> str | None:
    """The version of a subject's own text an entry judged: a unit's digest, a batch's list of its units' digests."""
    if entry.get("digest") is not None:
        return f"digest:{entry['digest']}"
    digests = entry.get("digests")
    if isinstance(digests, Mapping) and digests:
        return "digests:" + json.dumps(sorted(digests.items()), default=str)
    if isinstance(digests, Sequence) and not isinstance(digests, str) and digests:
        return "digests:" + json.dumps(list(digests), default=str)
    return f"material:{entry['material']}" if entry.get("material") is not None else None


def _rounds(judged_history: Sequence[Mapping[str, Any]]) -> int:
    """Distinct versions of the subject's own text judged not READY (a reused or re-judged one is the same)."""
    versions: set[str] = set()
    for index, entry in enumerate(judged_history):
        if entry.get("verdict") != "READY":
            versions.add(_version(entry) or f"entry:{index}")
    return len(versions)


def check(
    state: PlanState,
    judged_history: Sequence[Mapping[str, Any]],
    subject: str,
    latest_entry: Mapping[str, Any],
    cfg_target: YoloReviewCfg,
    actor: tuple[str, str | None] | str,
    *,
    withdraw: bool = False,
) -> Refusal | None:
    """The first rule `subject` breaks, in the order of design D7; None when it may be accepted. A withdrawal is
    never refused: it removes an override and only makes the activation stricter."""
    if withdraw:
        return None
    plan = state.plan_id
    kind = actor if isinstance(actor, str) else actor[0]
    found = latest_entry.get("findings") or []
    if not (
        state.status in _BEFORE_ACTIVATION or (state.status == "stopped" and state.stop_reason in _RESTARTABLE_STOPS)
    ):
        why = (
            f"{state.status} ({state.stop_reason})" if state.status == "stopped" and state.stop_reason else state.status
        )
        return Refusal(
            f"{plan} is {why}: an acceptance is possible before activation, or when the plan is stopped with "
            "inputs_changed or unit_rejected",
            f"l4 yolo status {plan}",
        )
    if latest_entry.get("verdict") == "BLOCKED":
        harness = [x for x in found if x.get("criterion") in _HARNESS_CRITERIA]
        if harness:
            return Refusal(
                f"{subject} is BLOCKED ({harness[0]['criterion']}): no review happened, so there is nothing to accept",
                f"run l4 yolo review {plan} again; if {subject} is missing, push its folder or remove it from the plan",
            )
        return Refusal(
            f"{subject} is BLOCKED: the judge could not judge it or says it cannot be built",
            f"fix the spec, push it and run l4 yolo review {plan}",
        )
    blocking = [x for x in found if x.get("severity") == "blocking" and x.get("criterion") != "material"]
    if blocking:
        return Refusal(
            f"{subject} has a blocking finding ({blocking[0].get('criterion')}): the implementer would build the "
            "wrong thing, so it cannot be accepted",
            f"fix the spec, push it and run l4 yolo review {plan}",
        )
    if any(x.get("criterion") == "material" for x in found):
        return Refusal(
            f"{subject} has a material finding: part of its text was left out of the review, so the activation "
            "would freeze text no one reviewed",
            "shorten the file or raise yolo.review.max_file_chars (or max_folder_chars) in .l4/config.yaml on the "
            "base branch",
        )
    if latest_entry.get("verdict") == "READY":
        return Refusal(f"{subject} is READY: nothing to accept", f"l4 yolo activate {plan} --reason TEXT")
    rounds, needed = _rounds(judged_history), cfg_target.accept_after_rounds
    if rounds < needed:
        return Refusal(
            f"{subject} was judged not READY on {rounds} version{'' if rounds == 1 else 's'}; {needed} are needed "
            "(yolo.review.accept_after_rounds)",
            f"change the spec and review again (l4 yolo review {plan}), or set yolo.review.accept_after_rounds in "
            ".l4/config.yaml on the base branch",
        )
    if kind == "agent" and not cfg_target.accept_by_agents:
        return Refusal(
            "acceptance is a person's decision",
            f'a person runs: l4 yolo accept {plan} {subject} --reason "..."; or set yolo.review.accept_by_agents: '
            "true in .l4/config.yaml on the base branch (a pushed change a person can see)",
        )
    return None


def _entry_of(latest_review: Mapping[str, Any], subject: str) -> Mapping[str, Any] | None:
    """The subject's entry in a `plan.reviewed` event's data (`units`, `batches`) or in a flat subject mapping."""
    if subject.startswith("batch:"):
        batches = latest_review.get("batches")
        entry = batches.get(subject[len("batch:") :]) if isinstance(batches, Mapping) else None
    else:
        units = latest_review.get("units")
        entry = units.get(subject) if isinstance(units, Mapping) else None
    if entry is None:
        entry = latest_review.get(subject)
    return entry if isinstance(entry, Mapping) else None


def holds(state: PlanState, latest_review: Mapping[str, object]) -> dict[str, bool]:
    """Per accepted subject: the latest review's entry has the same `material` and `findings_sha`."""
    result: dict[str, bool] = {}
    for subject, accepted in state.accepted.items():
        entry = _entry_of(latest_review, subject)
        if entry is None or entry.get("material") is None or accepted.get("material") != entry.get("material"):
            result[subject] = False
            continue
        sha = entry.get("findings_sha")
        if sha is None:
            sha = findings_mod.findings_sha(entry.get("findings") or [])
        result[subject] = accepted.get("findings_sha") == sha
    return result
