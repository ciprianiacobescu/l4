"""Step 0 of the ladder (SPEC 10.2): the unit is complete, current and valid.

- The worktree has no change but the harness's own output (`Workbench.is_clean`): gates run in the unit worktree at
  the committed head (M1: verifier 1.5, a fresh detached verifier worktree). A dirty tree is a harness error (exit 1).
- The branch contains the base head. `l4.verifier.basemerge.bring_in_base` merged it in, at the start of `verify_hook`,
  before this step: a branch that still lacks it here is a harness bug, an error with exit 1 and no verdict.
- The project's own CI was red on the hand-off commit H (`phase.changed{trigger: repository_ci_failed}`, SCN-ARC-14):
  one blocker per red job, `repository CI failed: <job>`, in the first round after that edge only (no `verify.verdict`
  follows it yet). The detail carries the stage, H, the job's URL and the end of its log, so a fix unit's `[chore]` task
  (which keeps the first 600 characters of the detail) names the job and shows what failed.
- A person's `feedback.md` (L4-FBK-004): one blocker per takeable item (`verifier.feedback.scan_feedback`), source
  `"feedback"`, so the round fails here and the fix unit of L4-VER-006 takes the item. Not read when
  `feedback.max_rounds` is 0. The `feedback.changed|invalid|withdrawn` events of the scan are recorded by step 0.
- Every required task is done (a Kiro optional `[ ]*` leaf may stay open), and the provider's strict validation
  passes: either failure is a blocker, so a FAIL.
"""

import logging
from collections.abc import Mapping
from dataclasses import dataclass

from l4.ci.failing_step import CiStep, derive_step, named_step
from l4.ci.gitlab_jobs import GITLAB_CI_RELPATH, ScriptRefusal, job_script
from l4.evidence.collect import show_blob
from l4.exitcodes import ExitCode, L4Exit
from l4.implementer.tasks import required
from l4.implementer.workbench import Workbench
from l4.specs.base import SpecError
from l4.specs.feedback import FeedbackFile
from l4.state.budget import feedback_round_limit
from l4.state.fold import fold
from l4.state.ledger import LedgerEvent, read_ledger
from l4.vcs.authorship import commit_records, is_harness
from l4.vcs.git import Git
from l4.verifier.feedback import Event, feedback_findings, scan_feedback
from l4.verifier.fixloop import family_units
from l4.verifier.types import Finding, Severity

log = logging.getLogger(__name__)

MAX_NAMED = 5
MAX_ISSUE_CHARS = 200
CI_SUMMARY_TAIL_CHARS = 300  # the end of the log that opens the detail, within the first 600 characters of a task
CI_TASK_CHARS = 600  # what a fix task keeps of a detail (`specs.openspec.MAX_DETAIL_CHARS`)


@dataclass(frozen=True)
class Preconditions:
    head: str
    base_sha: str  # the merge base with the base branch: the start of `git diff <base>...<head>`
    findings: list[Finding]
    ci_steps: tuple["CiStepRecord", ...] = ()  # the `ci.step` events step 0 has not recorded yet
    feedback_events: tuple[Event, ...] = ()  # `feedback.changed|invalid|withdrawn` that step 0 has not recorded yet


@dataclass(frozen=True)
class CiStepRecord:
    """One `ci.step{derived|skipped}` for `(head, job)`: what step 0 decided about a red job's failing step."""

    job: str
    head: str
    step: str | None
    command: str | None
    reason: str | None
    source: str

    @property
    def status(self) -> str:
        return "derived" if self.command else "skipped"


def _blocker(title: str, detail: str) -> Finding:
    return Finding(Severity.BLOCKER, title, detail, "deterministic")


def ci_detail(job: str, stage: str, head: str, url: str, tail: str, command: str | None = None) -> str:
    """The detail of a `repository CI failed` blocker: the failing step first, when it was derived (M1.10 decision 3),
    where it failed and the end of the log flattened (what a task keeps), then the whole tail for the report. The end
    of the log shrinks so that a long step and the log both fit the first `CI_TASK_CHARS` characters."""
    where = f"job `{job}`" + (f" (stage {stage})" if stage else "") + f" failed on the hand-off commit {head[:10]}"
    where += f" ({url})" if url else ""
    if command:
        where = f"failing step: `{' '.join(command.split())}` (job `{job}` at {head[:10]}). {where}"
    flat = " ".join(tail.split())
    budget = max(80, min(CI_SUMMARY_TAIL_CHARS, CI_TASK_CHARS - len(where) - len(". Log ends: ...") - 4))
    last = flat[-budget:]
    summary = f"{where}. Log ends: {'...' if len(flat) > len(last) else ''}{last}." if last else f"{where}."
    return f"{summary}\n\n{tail.strip()}" if tail.strip() else summary


def ci_edge(events: list[LedgerEvent]) -> LedgerEvent | None:
    """The last `repository_ci_failed` edge that no `verify.verdict` follows."""
    edge: LedgerEvent | None = None
    for event in sorted(events, key=lambda e: (e.ts, e.run_id, e.seq)):
        if event.type == "phase.changed" and event.data.get("trigger") == "repository_ci_failed":
            edge = event
        elif event.type == "verify.verdict":
            edge = None
    return edge


def _edge_jobs(edge: LedgerEvent) -> list[dict]:
    return [j for j in edge.data.get("jobs") or [] if isinstance(j, dict) and j.get("name")]


def ci_blockers(events: list[LedgerEvent], steps: Mapping[str, CiStep] | None = None) -> list[Finding]:
    """One blocker per job of the last `repository_ci_failed` edge that no `verify.verdict` follows. A job whose
    failing step was derived (`steps`) names it first."""
    edge = ci_edge(events)
    if edge is None:
        return []
    head = str(edge.data.get("head") or "")
    return [
        _blocker(
            f"repository CI failed: {job['name']}",
            ci_detail(str(job["name"]), str(job.get("stage") or ""), head, str(job.get("url") or ""),
                      str(job.get("tail") or ""), (steps or {}).get(str(job["name"]), CiStep("", None)).command),
        )
        for job in _edge_jobs(edge)
    ]  # fmt: skip


def _harness_changed(git: Git, base_sha: str, head: str, paths: list[str]) -> str | None:
    """The first of `paths` that differs between the merge base and H and was touched by a harness commit in between
    (an agent's edit of the CI file: the file would vouch for its own commands). A person's change is allowed."""
    for path in paths:
        if show_blob(git, base_sha, path) == show_blob(git, head, path):
            continue
        if any(is_harness(r) for r in commit_records(git, f"{base_sha}..{head}", "--", path)):
            return path
    return None


def derive_ci_steps(wb: Workbench, edge: LedgerEvent, base_sha: str) -> dict[str, CiStepRecord]:
    """Decision 2: for each job of the edge, the failing step re-derived from the CI files at H (`show_blob`, never
    the worktree) and vetted; a skip carries its reason."""
    head = str(edge.data.get("head") or "")
    source = f"{GITLAB_CI_RELPATH}@{head[:10]}"
    read: list[str] = [GITLAB_CI_RELPATH]
    text = show_blob(wb.git, head, GITLAB_CI_RELPATH)

    def load(path: str) -> str | None:
        read.append(path)
        return show_blob(wb.git, head, path)

    refusal: str | None = None
    if text is None:
        refusal = f"{GITLAB_CI_RELPATH} cannot be read at {head[:10]}"
    jobs = _edge_jobs(edge)
    records: dict[str, CiStepRecord] = {}
    for job in jobs:
        name = str(job["name"])
        tail = str(job.get("tail") or "")
        named = named_step(job.get("step"), tail)
        script = job_script(text, load, name) if text is not None else ScriptRefusal(refusal or "")
        if text is not None and (changed := _harness_changed(wb.git, base_sha, head, sorted(set(read)))) is not None:
            script = ScriptRefusal(f"{changed} was changed by a harness commit on this branch: it vouches for itself")
        step = derive_step(name, named, tail, script)
        records[name] = CiStepRecord(name, head, named, step.command, step.reason, source)
    return records


def record_ci_steps(wb: Workbench, pre: "Preconditions") -> None:
    """Write the `ci.step` events of step 0 (the ladder's step 0 closure calls this)."""
    for record in pre.ci_steps:
        wb.emit(
            "ci.step", job=record.job, head=record.head, step=record.step, command=record.command,
            status=record.status, reason=record.reason, source=record.source,
        )  # fmt: skip


def record_feedback(wb: Workbench, pre: "Preconditions") -> None:
    """Write the `feedback.*` events that step 0 observed (an edit after a take, an invalid or withdrawn item)."""
    for kind, data in pre.feedback_events:
        wb.emit(kind, **data)


def check_preconditions(wb: Workbench) -> Preconditions:
    if not wb.is_clean():
        raise L4Exit(ExitCode.INTERNAL_ERROR, "the unit worktree has uncommitted changes: refusing to verify")
    head = wb.head()
    base_ref = f"refs/remotes/origin/{wb.cfg.forge.base_branch}"
    base_head = wb.git.rev_parse(base_ref)
    if base_head is None:
        raise L4Exit(ExitCode.INTERNAL_ERROR, f"the base branch {base_ref} is not in the checkout: fetch it first")
    if wb.git.run("merge-base", "--is-ancestor", base_head, head, check=False).returncode != 0:
        raise L4Exit(
            ExitCode.INTERNAL_ERROR,
            "bug: the base merge of step 0 did not run: the unit branch does not contain the base head "
            f"({wb.cfg.forge.base_branch})",
        )
    base_sha = wb.git.run("merge-base", base_head, head).stdout.strip()
    findings: list[Finding] = []
    pending = [t.key for t in required(wb.provider.tasks(wb.ref)) if not t.done]
    if pending:
        shown = ", ".join(pending[:MAX_NAMED]) + (
            f" (+{len(pending) - MAX_NAMED} more)" if len(pending) > MAX_NAMED else ""
        )
        findings.append(_blocker("tasks not done", f"these tasks are not ticked: {shown}"))
    events = read_ledger(wb.ref.path).events
    records: dict[str, CiStepRecord] = {}
    if (edge := ci_edge(events)) is not None:
        records = derive_ci_steps(wb, edge, base_sha)
    findings += ci_blockers(events, {n: CiStep(n, r.command, r.reason) for n, r in records.items()})
    feedback_events: tuple[Event, ...] = ()
    state = fold(events, wb.ref.id)
    if feedback_round_limit(wb.cfg, state) > 0:  # 0 turns taking off (D8)
        try:
            file = FeedbackFile.load(wb.ref.path)
        except SpecError as exc:  # an unreadable file is the person's to fix; it must not stop the round
            log.warning("%s: feedback.md is not read: %s", wb.ref.id, exc)
            file = None
        scan = scan_feedback(file, state)
        findings += feedback_findings(scan)
        feedback_events = scan.events
    recorded = {(str(e.data.get("head")), str(e.data.get("job"))) for e in events if e.type == "ci.step"}
    new = tuple(r for r in records.values() if (r.head, r.job) not in recorded)
    for unit in family_units(wb.provider, wb.ref):  # the unit and its fix units, each strictly valid
        report = wb.provider.validate(unit, strict=True)
        if not report.valid:
            errors = [i for i in report.issues if i.level == "ERROR"] or list(report.issues)
            shown = "; ".join(f"{i.path}: {i.message}"[:MAX_ISSUE_CHARS] for i in errors[:MAX_NAMED])
            where = "" if unit == wb.ref else f"{unit.name}: "
            detail = where + (shown or "no detail from openspec")
            findings.append(_blocker("the unit does not validate --strict", detail))
    return Preconditions(head, base_sha, findings, new, feedback_events)
