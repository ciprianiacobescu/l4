"""The shared types of delivery plans (openspec/changes/yolo-mode, design D1, D2, D4, D5, D8, D9, D10).

This module is the contract between the plan's parts: the plan file and its loader (D1), admission and eligibility
(D2, `admit.py`), the plan ledger and its fold (D4, `store.py`, `state.py`), the readiness review (D5,
`readiness.py`), the guarded merge (D8, `merge.py`), the post-merge profile (D9, `postcheck.py`) and the plan step
(D10, `cycle.py`). It holds data only, and `load_plan`.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

SCHEMA = "l4/delivery-plan@1"
PLANS_DIR = ".l4/plans"
PLAN_REF_PREFIX = "refs/l4/plans/"
PLAN_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
PROFILE_ALL = "all"  # every configured gate
PROFILE_NONE = "none"  # no check: valid for a batch only

MergeMode = Literal["human", "auto"]
VerdictValue = Literal["READY", "NEEDS_REVISION", "BLOCKED"]
PlanStatus = Literal["new", "refused", "admitted", "reviewed", "active", "waiting", "stopped", "cancelled", "completed"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)


# --- D1: the plan file ---------------------------------------------------------------------------------------------


class PlanUnit(_Strict):
    id: str  # a namespaced unit id: `openspec:<change>` or `kiro:<spec>`
    depends_on: list[str] = Field(default_factory=list)  # unit ids
    acceptance_profile: str = PROFILE_ALL


class PlanBatch(_Strict):
    id: str
    depends_on: list[str] = Field(default_factory=list)  # batch ids
    acceptance_profile: str = PROFILE_NONE
    units: list[PlanUnit]


class PlanExclusion(_Strict):
    """A unit this plan deliberately does not deliver (D15, L4-YOLO-017): it is held only while a plan is active on the
    target; before and after that it runs as without a plan."""

    id: str
    reason: str = Field(min_length=1, max_length=200)


class PlanLimits(_Strict):
    """The plan's limits (D11). R12: at least one attempt and one run, a cost of zero or more, a deadline with a time
    zone (a naive one cannot be compared with the clock)."""

    max_cost_usd: float | None = Field(default=None, ge=0)
    max_unit_attempts: int = Field(default=2, ge=1)
    max_runs: int | None = Field(default=None, ge=1)
    deadline: datetime | None = None

    @field_validator("deadline")
    @classmethod
    def _deadline_has_a_zone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.utcoffset() is None:
            raise ValueError("the deadline must carry a time zone (for example 2026-12-31T18:00:00Z)")
        return value


class Promotion(_Strict):
    mode: Literal["manual"]
    target_branch: str


class Plan(_Strict):
    schema_id: Literal["l4/delivery-plan@1"] = Field(alias="schema")
    plan_id: str
    target: str
    merge: MergeMode
    promotion: Promotion | None = None
    limits: PlanLimits = Field(default_factory=PlanLimits)
    external_dependencies: list[dict[str, Any]] = Field(default_factory=list)
    batches: list[PlanBatch]
    exclude: list[PlanExclusion] = Field(default_factory=list)

    def units(self) -> list[PlanUnit]:
        """Every unit, in file order (batch position, then unit position)."""
        return [u for b in self.batches for u in b.units]

    def unit_ids(self) -> list[str]:
        return [u.id for u in self.units()]

    def known_ids(self) -> list[str]:
        """The unit ids admission must look up: the planned units and the excluded ones (D15), each once."""
        return list(dict.fromkeys([*self.unit_ids(), *(x.id for x in self.exclude)]))

    def batch_of(self, unit_id: str) -> PlanBatch | None:
        return next((b for b in self.batches if any(u.id == unit_id for u in b.units)), None)


@dataclass(frozen=True)
class PlanInvalid:
    """The file is not a plan: the messages say why, one per problem (`<plan>: …`)."""

    errors: tuple[str, ...]


def load_plan(text: str, *, file_name: str | None = None) -> Plan | PlanInvalid:
    """Parse and validate a plan file (D1). The `plan_id` must match `PLAN_ID` and, when `file_name` is given, the file
    name `<plan_id>.json`. A non-empty `external_dependencies` is refused (not supported in this version)."""
    label = PurePosixPath(file_name).stem if file_name else "plan"
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        return PlanInvalid((f"{label}: not JSON: {exc.msg} at line {exc.lineno}",))
    if not isinstance(raw, dict):
        return PlanInvalid((f"{label}: not a JSON object",))
    try:
        plan = Plan.model_validate_json(text)
    except ValidationError as exc:
        errors = []
        for err in exc.errors():
            where = ".".join(str(p) for p in err["loc"]) or "plan"
            if err["type"] == "extra_forbidden":
                errors.append(f"{label}: unknown field {where}")
            else:
                errors.append(f"{label}: {where}: {err['msg']}")
        return PlanInvalid(tuple(errors))
    errors = []
    if not PLAN_ID.match(plan.plan_id):
        errors.append(f"{label}: plan_id {plan.plan_id!r} must match {PLAN_ID.pattern}")
    if file_name is not None and PurePosixPath(file_name).name != f"{plan.plan_id}.json":
        errors.append(f"{label}: the file name must be {plan.plan_id}.json")
    if plan.external_dependencies:
        errors.append(f"{label}: external dependencies are not supported in this version")
    return PlanInvalid(tuple(errors)) if errors else plan


# --- D2: admission and eligibility ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    """One admission problem. `code` is one of design D2's codes; `subject` is the unit, batch or plan id."""

    code: str
    subject: str
    text: str


@dataclass(frozen=True)
class Admission:
    ok: bool
    findings: tuple[Finding, ...]
    order: tuple[str, ...]  # unit ids, topological; empty when not ok


@dataclass(frozen=True)
class UnitInfo:
    """What admission needs to know of one unit, read at the target head (or its branch)."""

    id: str
    folder: str  # repository-relative unit folder
    open_questions: tuple[str, ...] = ()
    phase: str | None = None
    intake_ok: bool = True
    intake_detail: str = ""


@dataclass(frozen=True)
class Eligibility:
    unit: str | None  # the one unit that may be dispatched now, if any
    waiting: dict[str, str] = field(default_factory=dict)  # unit id -> "waits for openspec:a (not integrated)"


# --- D4: the plan ledger -------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PlanEvent:
    type: str  # one of design D4's event types, e.g. "plan.activated"
    at: str  # ISO-8601 UTC
    data: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps({"type": self.type, "at": self.at, **self.data}, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def from_json(line: str) -> "PlanEvent":
        raw = json.loads(line)
        return PlanEvent(type=str(raw.pop("type")), at=str(raw.pop("at")), data=raw)


class PlanMoved(Exception):
    """The plan ref moved since it was read (a lost lease): read again and decide again, never overwrite."""


class Usage(BaseModel):
    cost_usd: float = 0.0
    runs: int = 0
    attempts: dict[str, int] = Field(default_factory=dict)  # unit id -> highest attempt charged (R1)


class PlanState(BaseModel):
    plan_id: str
    status: PlanStatus = "new"
    plan_digest: str | None = None  # the plan file's digest: the latest admitted one, the activated one once active
    activated_digest: str | None = None  # R2: frozen by `plan.activated`; a plan file that differs stops the plan
    merge: MergeMode | None = None
    order: list[str] = Field(default_factory=list)
    findings: list[dict[str, str]] = Field(default_factory=list)  # of the latest `plan.refused`
    review_plan_digest: str | None = None  # the plan digest the latest review was for
    review_prompt_version: int = 1  # the readiness prompt version of the latest review (no key in the event: 1)
    review_digests: dict[str, str] = Field(default_factory=dict)  # unit -> digest the latest review was for
    review: dict[str, str] = Field(default_factory=dict)  # unit or `batch:<id>` -> verdict
    digests: dict[str, str] = Field(default_factory=dict)  # frozen at activation: unit -> digest
    limits: dict[str, Any] = Field(default_factory=dict)  # frozen at activation (PlanLimits as a dict)
    attempt_base: dict[str, int] = Field(default_factory=dict)  # R13: unit -> its attempt refs when the plan began
    current: str | None = None  # the unit dispatched and not yet integrated
    merged: dict[str, str] = Field(default_factory=dict)  # unit -> merge commit (head)
    integrated: dict[str, str] = Field(default_factory=dict)  # unit -> target revision
    accepted_batches: dict[str, str] = Field(default_factory=dict)  # batch -> revision
    failed_batches: dict[str, str] = Field(default_factory=dict)  # batch -> detail
    stale_merges: dict[str, int] = Field(default_factory=dict)  # unit -> `stale` refusals in the current attempt
    stop_reason: str | None = None
    stop_detail: str | None = None
    stop_unit: str | None = None
    wait_reason: str | None = None
    used: Usage = Field(default_factory=Usage)
    extended: Usage = Field(default_factory=Usage)
    extended_deadline: datetime | None = None  # R3: the latest deadline a `l4 yolo resume --extend-deadline` set (UTC)
    activated_by: str | None = None
    completed_revision: str | None = None


# --- D5: readiness review ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Verdict:
    verdict: VerdictValue
    findings: tuple[dict[str, str], ...] = ()  # {criterion, severity, text}
    assumptions: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    digest: str | None = None  # the unit digest (units) the review was for


@dataclass(frozen=True)
class ReviewResult:
    units: dict[str, Verdict]
    batches: dict[str, Verdict]  # batch id -> verdict, only batches with more than one unit


# --- D8, D9: merge and post-merge ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class MergeOutcome:
    status: Literal["merged", "stale", "refused", "not_ready"]
    head: str | None = None
    target_before: str | None = None
    pr: int | None = None
    detail: str = ""


@dataclass(frozen=True)
class ProfileResult:
    status: Literal["pass", "fail", "error"]
    revision: str
    profile: str
    gates: tuple[Any, ...] = ()  # l4.gates.runner.GateResult
    detail: str = ""


# --- D10: the plan step --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class YoloStep:
    allow: frozenset[str] | None  # None: no active plan, nothing changes; else the unit ids `l4 run` may dispatch
    actions: tuple[str, ...] = ()  # one line per thing the step did, for the log and outcome.json
    start_next_run: bool = False
    plan_id: str | None = None
