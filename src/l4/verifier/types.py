"""What the ladder produces: findings, per-criterion outcomes, step records and the result of one round."""

import hashlib
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from l4.security.protected import HumanChange
    from l4.verifier.selection import Independence


class Severity(StrEnum):
    BLOCKER = "blocker"
    MAJOR = "major"
    MINOR = "minor"


class Verdict(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NEEDS_HUMAN = "NEEDS_HUMAN"


# "human": a judge finding the human rejected (L4-VER-013); "feedback": a person's item of feedback.md (L4-FBK-004)
Source = Literal["deterministic", "judge", "human", "feedback"]
StepStatus = Literal["ok", "failed", "not_run", "reused", "unavailable"]
CounterexampleStatus = Literal["reproduced", "not_reproduced", "unexecuted"]
CriterionResult = Literal["pass", "needs_human", "fail", "disputed"]


def finding_id(title: str, criterion: str | None = None) -> str:
    """`F-` and 8 hex digits of the title and criterion (a reworded detail keeps its id)."""
    digest = hashlib.sha256(f"{title}\x00{criterion or ''}".encode()).hexdigest()
    return f"F-{digest[:8]}"


@dataclass(frozen=True)
class FeedbackRef:
    """What the fix planner needs of one item of `feedback.md` (L4-FBK-004, L4-FBK-005): the item as step 0 read it.
    `sha256` is `specs.feedback.content_sha256` of that reading, which `feedback.taken` records."""

    id: str
    kind: str
    title: str
    text: str  # the person's request, whitespace as written
    by: str
    places: tuple[str, ...] = ()  # `path[:start[-end]]`
    env: str | None = None
    when: str | None = None
    then: str | None = None
    code: str = ""
    sha256: str = ""
    retake: bool = False  # the item had a `feedback.taken` before this fix unit: its chore may find nothing to change


@dataclass(frozen=True)
class FeedbackOutcome:
    """The judge check of one item in one round (L4-FBK-007): addressed or not, and the evidence either way."""

    id: str
    addressed: bool
    evidence: str


@dataclass(frozen=True)
class Finding:
    severity: Severity
    title: str
    detail: str
    source: Source
    criterion: str | None = None
    log: str | None = None  # path of the gate log, relative to the repository root
    spec_gap: bool = False
    suggested_fix: str = ""
    id: str = ""  # `F-` and 8 hex digits of the title and criterion; set here, so a reworded detail keeps its id
    feedback: FeedbackRef | None = None  # source "feedback" only; not stored in verdict.json (the item is in the file)

    def __post_init__(self) -> None:
        if not self.id:
            object.__setattr__(self, "id", finding_id(self.title, self.criterion))

    @property
    def blocking(self) -> bool:
        return self.severity in (Severity.BLOCKER, Severity.MAJOR)


@dataclass(frozen=True)
class CounterexampleRun:
    status: CounterexampleStatus
    note: str = ""


@dataclass(frozen=True)
class CriterionOutcome:
    id: str
    alias: str
    result: CriterionResult
    judge: str | None  # the judge's verdict word, None when there was none
    reason: str
    counterexample: CounterexampleRun | None = None
    tests: tuple[str, ...] = ()  # ids of the tests that count as evidence for it
    s1_p: float | None = None  # step 8's `p`: recorded, never used to decide


@dataclass(frozen=True)
class StepRecord:
    step: str
    name: str
    status: StepStatus
    seconds: float = 0.0
    note: str = ""


@dataclass(frozen=True)
class IntegrityCheck:
    """One sub-check of step 1: `skipped` when it had nothing to look at."""

    name: str
    status: Literal["ok", "failed", "skipped"]
    note: str = ""


@dataclass
class IntegrityReport:
    checks: list[IntegrityCheck] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    declared: list[str] = field(default_factory=list)  # declared suppressions found in the diff, one line each
    # protected paths that only people's commits changed (allowed, listed: L4-SEC-004): {path, commits: [{sha, author}]}
    human_protected: list["HumanChange"] = field(default_factory=list)
    human_tests: list[str] = field(default_factory=list)  # test deletions and skip markers only people's commits made
    unfrozen: list[str] = field(default_factory=list)  # frozen tests a human answer unfroze for green (M1.10)
    human_suppressions: list[str] = field(default_factory=list)  # inline suppressions a person's commit wrote (W-D6)
    human_scan: list[str] = field(default_factory=list)  # content-scan hits only people's commits introduced (W-D6)
    human_config: list[str] = field(default_factory=list)  # gate and runner configuration only people's commits changed
    allowed_tests: list[str] = field(default_factory=list)  # pre-existing test changes an allowance covers (L4-VER-031)
    mocked_support: list[str] = field(
        default_factory=list
    )  # fixtures a test requests that patch the unit's code (listed)
    base_tests: dict[str, Any] | None = None  # the ids that passed at the base (L4-VER-038), for the next round
    test_awareness: list[str] = field(default_factory=list)  # signs of a test run in production code (judge, listed)

    @property
    def blocked(self) -> bool:
        return any(f.blocking for f in self.findings)


@dataclass(frozen=True)
class TracingTest:
    """A test that traces a criterion. `proof` is why it counts: `zero_value`, `pre_satisfied` or `red_assertion`
    (the implementer's red phase), `pass_to_pass` (the criterion text is unchanged from the base specs), `audit`
    or `generated` (a verifier-written test), `human` or `chore` (a test people or a test chore wrote, which the
    verifier saw fail against the zero values or on the base's code). `adequate` is False once the judge called it
    inadequate."""

    id: str
    status: str
    proof: str
    adequate: bool = True
    note: str = ""  # why a proof that no run showed counts: `not applicable: ...` or `accepted by Q-NNN: ...`
    over_cap: int = 0  # a test over the cap (L4-VER-054, a candidate or one the judge named): criteria it traces


@dataclass(frozen=True)
class CriterionEvidence:
    criterion: str
    alias: str
    state: Literal["covered", "uncovered", "fail"]
    tests: tuple[TracingTest, ...] = ()
    ignored: tuple[tuple[str, str], ...] = ()  # (test id, why it is not evidence)
    held: str = ""  # a reason a human must decide although tests cover the criterion (a failed audit test)
    capped: tuple[TracingTest, ...] = ()  # proved, passing tests over the per-test cap: candidates of L4-VER-054


@dataclass(frozen=True)
class AuditRecord:
    """Step 4a for one criterion. `status`: accepted, rejected (passes against zero values, or cannot be collected),
    inconclusive (the zero-value run could not run the test: no finding, L4-VER-050), failed (fails at head),
    not_testable, invalid, timeout or skipped (cap)."""

    criterion: str
    status: str
    test_path: str = ""
    tests: tuple[str, ...] = ()
    reason: str = ""
    support: str = ""  # how it ran: base (support files at the base), head (with them) or unchanged (L4-VER-036)
    support_files: tuple[str, ...] = ()  # the support files reverted for a `base` run, the unit's for a `head` run


GenStatus = Literal[
    "accepted", "not_testable", "non_discriminating", "fails_at_head", "uncollectable", "base_error", "base_unservable",
    "lint_failed", "writer_failed", "waived",
]  # fmt: skip
RunOutcome = Literal["pass", "fail", "error"]  # the new test at the merge base / at the head


@dataclass(frozen=True)
class GeneratedOutcome:
    """Step 5 for one UI criterion (`generate.py`)."""

    criterion: str
    status: GenStatus
    path: str | None = None  # repository-relative; set for every status that wrote a file
    attempts: int = 0
    reason: str = ""
    code: str = ""  # the last test written: the evidence for a test that fails at the head
    artifacts: tuple[str, ...] = ()  # traces and screenshots of the head run that failed
    cost_usd: float = 0.0
    model: str | None = None
    prompt_sha256: str = ""
    base: RunOutcome | None = None  # None: the run did not happen or did not run the test
    head: RunOutcome | None = None
    tests: tuple[str, ...] = ()  # accepted: the ids of the new file's tests in the head report (the evidence)
    sha256: str = ""  # accepted: of the file as written, so that a later round can tell it is still ours
    support: str = ""  # the head run: base (the unit's support files at the base), head (with them) or unchanged
    by: str = ""  # waived: the answered question that waived the criterion (L4-VER-067); no writer ran

    @property
    def accepted(self) -> bool:
        return self.status == "accepted"


@dataclass(frozen=True)
class S1Record:
    """Step 8 for one criterion: `p` of "does this evidence show that the criterion is satisfied?"."""

    criterion: str
    status: Literal["ok", "unavailable"]
    p: float | None = None
    model: str = ""  # as the server's reply says it
    engine: str = ""
    reason: str = ""
    truncated: bool = False
    evidence: dict[str, float] | None = None  # the 4-way choice's probabilities


@dataclass(frozen=True)
class HumanVerdict:
    """`human.verdict` as the next round reads it. `text_sha256`: the criterion text (or the finding's title) the human
    judged, so an `accept` of text that has changed since is void."""

    question: str
    target: str
    decision: Literal["accept", "reject"]
    by: str
    reason: str
    text_sha256: str
    marker: str = ""  # an agent: the marker of its environment
    model: str = ""  # the delegate: the model and the CLI that answered
    cli: str = ""

    @property
    def label(self) -> str:
        """Who decided, as `verification.md` and the notes of the round say it (L4-DLG-010, L4-VER-051): a person is
        `human`, an agent `agent (<marker>)`, the delegate `the delegate (<model> via <cli>)`."""
        if self.by == "agent":
            return f"agent ({self.marker})" if self.marker else "agent"
        if self.by == "delegate":
            return f"the delegate ({self.model} via {self.cli})" if self.model and self.cli else "the delegate"
        return self.by


@dataclass(frozen=True)
class GateLine:
    name: str
    command: str
    status: Literal["pass", "fail"]
    reason: str
    log: str | None
    digest: str | None = None  # a failed gate's last error lines, normalised (`gates.log_digest`): `same_failure` (M5)


@dataclass
class FixDecision:
    """What the round's verdict means for fix units (L4-VER-006, L4-VER-007), decided before the evidence is written so
    that the report can list it: `spawn` a fix unit, `escalate` (the rounds are used up, or nothing can be fixed), or
    `none`. `plan` is the `fixloop.FixPlan` to execute; it is not serialised."""

    action: Literal["spawn", "escalate", "none"]
    ordinal: int = 0  # of the fix unit `<parent>-fix-<ordinal>`
    tasks: list[str] = field(default_factory=list)
    not_converted: list[str] = field(default_factory=list)
    reason: str = ""
    plan: Any = None
    code: str = ""  # an `escalate` with a machine-readable reason, the edge's `reason` (`feedback_rounds_exhausted`)


REPLY_OUTCOMES = ("valid", "repaired", "retried", "discarded")  # how a judge's reply fared, counted per profile


@dataclass
class VerifyResult:
    unit: str
    round: int
    verdict: Verdict
    base_sha: str
    head_sha: str
    steps: list[StepRecord] = field(default_factory=list)
    gates: list[GateLine] = field(default_factory=list)
    criteria: list[CriterionOutcome] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    holds: list[str] = field(default_factory=list)  # why a human has to look, beyond criteria and findings
    judge_profile: str = ""
    implementer_profiles: list[str] = field(default_factory=list)
    judge_model: str | None = None
    independence: "Independence | None" = None
    judge_calls: int = 0
    judge_reply: str = ""  # how the judge's reply fared this round (`judge.REPLY_OUTCOMES`); empty when not reached
    judge_replies: dict[str, int] = field(default_factory=dict)  # the judge profile's counts over the unit's ledger
    prompt_sha256: str = ""
    prompt_template: str = ""  # `judge@<version>` of the prompt the judge was sent
    # a diff judged in parts (L4-VER-041): per part `{part, files, chars, profile, calls, reply, prompt_sha256}`
    judge_parts: list[dict[str, Any]] = field(default_factory=list)
    # the follow-up calls for criteria the parts split (L4-VER-057): per call `{followup, criteria, parts, files,
    # chars, not_shown, profile, calls, reply, status, prompt_sha256}`; `judge_split`: the record of each split
    # criterion (L4-VER-058)
    judge_followups: list[dict[str, Any]] = field(default_factory=list)
    judge_split: dict[str, dict[str, Any]] = field(default_factory=dict)
    judge_files: list[list[Any]] = field(
        default_factory=list
    )  # `[part, path, characters]` of every file (0: not judged)
    hold_views: dict[str, dict[str, Any]] = field(default_factory=dict)  # `judge view:` hold -> {sha, paths} (M1)
    cost_usd: float | None = None
    tests: dict[str, str] = field(default_factory=dict)  # test id -> status, from the step 3 report
    failures: dict[str, dict[str, str]] = field(
        default_factory=dict
    )  # failing test id -> {gate, kind, message} (VER-069)
    red_green: dict[str, str] = field(default_factory=dict)  # new test id -> task whose `task.red_ok` named it
    guards: list[str] = field(default_factory=list)  # `guard.*` ledger events of the unit, one line each
    feedback: list[str] = field(default_factory=list)  # items taken or judged in this round, one line each (D12)
    feedback_outcomes: list[FeedbackOutcome] = field(default_factory=list)  # the judge check of L4-FBK-007; not stored
    integrity: IntegrityReport | None = None
    trace: list[CriterionEvidence] = field(default_factory=list)
    audit: list[AuditRecord] = field(default_factory=list)
    human: list[HumanVerdict] = field(default_factory=list)  # the verdicts that applied to this round's aggregation
    judge_verdict: dict[str, Any] | None = None  # the `l4/judge-verdict@1` object; a resumed round re-aggregates it
    cx_runs: dict[str, CounterexampleRun] = field(default_factory=dict)
    subject_sha: str = ""  # the last commit not made by the harness's evidence steps (resume at aggregation, D4)
    reused_from: int | None = None  # the round whose steps 0-9 this round reused
    fix: FixDecision | None = None
    generated: list[GeneratedOutcome] = field(default_factory=list)  # step 5: one per UI criterion it tried
    s1: list[S1Record] = field(default_factory=list)  # step 8
    evidence: dict[str, Any] | None = None  # M1.6 Stage A: `l4/evidence@1` (scope, diff coverage, tests ran, holds)
