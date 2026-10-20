"""`l4 yolo accept`: who is asking, what the target's configuration allows, and when an acceptance holds
(review-resolution design D7, section 8). Pure rules; the command (yolo/commands.py) records the events."""

import logging
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from l4.actor import AGENT_MARKERS, actor
from l4.config.loader import load_config
from l4.config.schema import L4Config, YoloReviewCfg
from l4.exitcodes import L4Exit
from l4.vcs.git import Git, GitError
from l4.yolo import findings as findings_mod
from l4.yolo.digest import MISSING
from l4.yolo.model import Plan, PlanEvent, PlanState

log = logging.getLogger("l4.yolo.accept")
__all__ = [
    "AGENT_MARKERS",
    "SKIPPED_WORDS",
    "Refusal",
    "actor",
    "check",
    "entry_of",
    "force_holds",
    "force_line",
    "force_subjects",
    "holds",
    "status_refusal",
    "target_config",
    "target_full_config",
    "why_not_holds",
    "whys",
]

_RESTARTABLE_STOPS = ("inputs_changed", "unit_rejected")  # the stopped plans a review can still be made on
_BEFORE_ACTIVATION = ("new", "refused", "admitted", "reviewed")
_HARNESS_CRITERIA = ("schema", "unit_missing", "completeness")
_CONFIG_PATH = ".l4/config.yaml"


@dataclass(frozen=True)
class Refusal:
    """Why `l4 yolo accept` refuses: the cause, and what clears it (the caller prefixes `accept: `)."""

    message: str
    fix: str


def target_full_config(git: Git, ref: str) -> L4Config | None:
    """The whole `.l4/config.yaml` at `ref`, or None when the file is absent, the ref is unknown or the file is not a
    valid config (the reason is logged). Never the working tree, and never the unit branch: a caller names the base."""
    try:
        shown = git.run("show", f"{ref}:{_CONFIG_PATH}", check=False)
    except GitError as exc:
        log.warning("accept: cannot read %s at %s (%s): the defaults apply", _CONFIG_PATH, ref, exc)
        return None
    if shown.returncode != 0:
        log.debug("accept: no %s at %s: the defaults apply", _CONFIG_PATH, ref)
        return None
    with tempfile.TemporaryDirectory(prefix="l4-accept-") as tmp:
        path = Path(tmp) / "config.yaml"
        path.write_text(shown.stdout, encoding="utf-8")
        try:
            return load_config(Path(tmp), config_path=path)
        except L4Exit as exc:  # ConfigSchemaError: the harness's own message names the position
            log.warning("accept: %s at %s is not a valid config (%s): the defaults apply", _CONFIG_PATH, ref, exc)
            return None


def target_config(git: Git, ref: str) -> YoloReviewCfg:
    """`yolo.review` of `.l4/config.yaml` at `ref` (defaults when the file is absent or invalid)."""
    full = target_full_config(git, ref)
    return full.yolo.review if full is not None else YoloReviewCfg()


def status_refusal(state: PlanState) -> Refusal | None:
    """The plan status rule of an acceptance (the first rule of `check`, shared with the force path): only before the
    activation, or stopped with `inputs_changed` or `unit_rejected`."""
    if state.status in _BEFORE_ACTIVATION or (state.status == "stopped" and state.stop_reason in _RESTARTABLE_STOPS):
        return None
    plan = state.plan_id
    why = f"{state.status} ({state.stop_reason})" if state.status == "stopped" and state.stop_reason else state.status
    return Refusal(
        f"{plan} is {why}: an acceptance is possible before activation, or when the plan is stopped with "
        "inputs_changed or unit_rejected",
        f"l4 yolo status {plan}",
    )


def check(
    state: PlanState,
    events: Sequence[PlanEvent],
    subject: str,
    latest_entry: Mapping[str, Any],
    cfg_target: YoloReviewCfg,
    actor: tuple[str, str | None] | str,
    *,
    withdraw: bool = False,
) -> Refusal | None:
    """The first rule `subject` breaks, in the order of design D7; None when it may be accepted. `events` are the plan's
    ledger: the rounds are counted by `findings.rounds_not_ready`, the number `plan.accepted` records. A withdrawal is
    never refused: it removes an override and only makes the activation stricter."""
    if withdraw:
        return None
    plan = state.plan_id
    kind = actor if isinstance(actor, str) else actor[0]
    found = latest_entry.get("findings") or []
    refusal = status_refusal(state)
    if refusal is not None:
        return refusal
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
    rounds, needed = findings_mod.rounds_not_ready(events, subject), cfg_target.accept_after_rounds
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


entry_of = _entry_of  # public: the commands read a review's entry with it


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


def _short(value: object) -> str:
    return str(value)[:8] if value else "none"


def _bound_digests(subject: str, entry: Mapping[str, Any]) -> dict[str, str]:
    """The unit digests an entry stands for: `{subject: digest}` for a unit, the entry's `digests` for a batch."""
    if subject.startswith("batch:"):
        raw = entry.get("digests")
        return {str(k): str(v) for k, v in raw.items()} if isinstance(raw, Mapping) else {}
    return {subject: str(entry["digest"])} if entry.get("digest") else {}


def why_not_holds(accepted: Mapping[str, Any], entry: Mapping[str, Any] | None, review_at: str | None) -> str:
    """One line that says why `accepted` (a `plan.accepted`'s data) does not hold on the latest review's `entry`
    (L4-YOLO-066, design D9.2). `review_at` is the `at` of the review that holds the entry."""
    subject = str(accepted.get("subject") or "this subject")
    if entry is None:
        return f"no entry: the latest review does not judge {subject}"
    old = _short(accepted.get("findings_sha") or findings_mod.findings_sha(accepted.get("findings") or []))
    sha = entry.get("findings_sha") or findings_mod.findings_sha(entry.get("findings") or [])
    when = f" judged {accepted['judged_at']}" if accepted.get("judged_at") else ""
    at = entry.get("reused_from") or review_at
    latest = f"judged {at} " if at else ""
    kind = "reused" if entry.get("reused_from") else "new"
    if accepted.get("material") == entry.get("material"):
        return (
            f"other findings of the same material: accepted findings {old}{when}; the latest review shows findings "
            f"{_short(sha)} {latest}({kind})"
        )
    text = (
        f"other material: accepted on material {_short(accepted.get('material'))} with findings {old}{when}; the "
        f"latest review shows material {_short(entry.get('material'))} with findings {_short(sha)} {latest}({kind})"
    )
    recorded = accepted.get("digests")
    if isinstance(recorded, Mapping) and recorded:
        if {str(k): str(v) for k, v in recorded.items()} != _bound_digests(subject, entry):
            return f"{text}; its own spec changed"
        return f"{text}; a prerequisite, its plan entry, its task marks or the review prompt changed"
    return text


def whys(state: PlanState, latest_review: Mapping[str, object], review_at: str | None) -> dict[str, str]:
    """`why_not_holds` for each accepted subject whose acceptance does not hold on `latest_review`."""
    held = holds(state, latest_review)
    return {
        s: why_not_holds(a, _entry_of(latest_review, s), review_at)
        for s, a in state.accepted.items()
        if not held.get(s)
    }


# --- the force acceptance (L4-YOLO-057, -060; design D4, D6) --------------------------------------------------------

SKIPPED_WORDS = {
    "no_review": "no review",
    "stale_review": "a review for other inputs",
    "blocked": "BLOCKED",
    "blocking": "a blocking finding",
    "material": "a material finding",
    "rounds": "fewer than yolo.review.accept_after_rounds judged versions",
    "not_ready": "NEEDS_REVISION",
}


def _skipped(
    entry: Mapping[str, Any] | None,
    stale: bool,
    events: Sequence[PlanEvent],
    subject: str,
    cfg_target: YoloReviewCfg,
) -> list[str]:
    """What an ordinary acceptance would have needed for `subject` (design D4), in the order of the design."""
    if entry is None:
        return ["no_review"]
    if stale:
        return ["stale_review"]
    verdict, found = entry.get("verdict"), entry.get("findings") or []
    if verdict == "READY":
        return []
    if verdict == "BLOCKED":
        return ["blocked"]
    skipped = []
    if any(x.get("severity") == "blocking" and x.get("criterion") != "material" for x in found):
        skipped.append("blocking")
    if any(x.get("criterion") == "material" for x in found):
        skipped.append("material")
    if findings_mod.rounds_not_ready(events, subject) < cfg_target.accept_after_rounds:
        skipped.append("rounds")
    return skipped or ["not_ready"]


def force_subjects(
    plan: Plan,
    plan_digest_now: str,
    now: Mapping[str, str],
    events: Sequence[PlanEvent],
    cfg_target: YoloReviewCfg,
    prompt_version: int,
) -> dict[str, dict[str, Any]]:
    """Every subject of `plan` (each unit; `batch:<id>` for a batch of more than one unit) as `plan.force_accepted`
    records it: its digest (a batch: its units' `digests`), what it `skipped`, and the latest review's `review_at`,
    `verdict` and `material` when that review has an entry for it. Pure: no model, no clock."""
    latest = next((e for e in reversed(events) if e.type == "plan.reviewed"), None)
    data: Mapping[str, Any] = latest.data if latest is not None else {}
    version = data.get("prompt_version")
    version = version if isinstance(version, int) and not isinstance(version, bool) else 1
    review_stale = latest is not None and (data.get("plan_digest") != plan_digest_now or version != prompt_version)
    out: dict[str, dict[str, Any]] = {}
    wanted: list[tuple[str, list[str]]] = [(u, [u]) for u in plan.unit_ids()]
    wanted += [(f"batch:{b.id}", [u.id for u in b.units]) for b in plan.batches if len(b.units) > 1]
    for subject, members in wanted:
        entry = _entry_of(data, subject) if latest is not None else None
        stale = review_stale
        if entry is not None and not stale:
            for unit in members:
                unit_entry = _entry_of(data, unit)
                stale = stale or unit_entry is None or unit_entry.get("digest") != now.get(unit, MISSING)
        row: dict[str, Any] = (
            {"digests": {u: now.get(u, MISSING) for u in members}}
            if subject.startswith("batch:")
            else {"digest": now.get(subject, MISSING)}
        )
        row["skipped"] = _skipped(entry, stale, events, subject, cfg_target)
        row["review_at"] = latest.at if entry is not None and latest is not None else None
        row["verdict"] = entry.get("verdict") if entry is not None else None
        row["material"] = entry.get("material") if entry is not None else None
        out[subject] = row
    return out


def force_holds(force: Mapping[str, Any] | None, plan_digest_now: str, now: Mapping[str, str]) -> dict[str, bool]:
    """Per subject a force acceptance names: it holds while the plan file and the subject's unit digest(s) are the ones
    recorded. A recorded or current `MISSING` never holds. No force acceptance: nothing."""
    if force is None:
        return {}
    plan_same = force.get("plan_digest") == plan_digest_now

    def same(unit: str, recorded: Any) -> bool:
        return recorded is not None and recorded != MISSING and now.get(unit) == recorded

    result: dict[str, bool] = {}
    for subject, row in (force.get("subjects") or {}).items():
        digests = row.get("digests") if isinstance(row, Mapping) else None
        if isinstance(digests, Mapping):
            ok = bool(digests) and all(same(str(u), d) for u, d in digests.items())
        else:
            ok = isinstance(row, Mapping) and same(str(subject), row.get("digest"))
        result[str(subject)] = plan_same and ok
    return result


def force_line(subject: str, by: str, reason: str, *, holds: bool = True) -> str:
    """The one text that status, findings, the report and the activation print for a force-accepted subject."""
    line = f"{subject}: force-accepted without review by {by} ({reason})"
    return line if holds else f"{line}; no longer holds: its spec or the plan file changed"
