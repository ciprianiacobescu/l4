"""The plan report (openspec/changes/yolo-mode, design D12, requirement L4-YOLO-015, scenario SCN-YOLO-28).

`render_report` turns a plan, its folded state, its ledger and the units' folded states into the text of `report.md`.
The plan step writes it on completion and on every stop, into the plan ref and into `.l4-out/yolo/<plan>.md`. It states
the repository, the target and its revision, each unit with its pull request, merge commit, post-merge result and
usage, each batch result, the stop reason, and the sentence `Promotion to <target_branch> was not performed`: the
harness never promotes the integration branch (D14). A plan with no promotion target says so in the same words.
The text depends only on its arguments, so the same ledger gives the same report.
"""

from collections.abc import Mapping, Sequence

from l4.state.fold import UnitState
from l4.state.ledger import LedgerEvent
from l4.yolo.accept import force_line
from l4.yolo.findings import finding_id
from l4.yolo.model import Plan, PlanEvent, PlanState


def _last(events: Sequence[PlanEvent], kind: str, unit: str) -> dict[str, object]:
    found: dict[str, object] = {}
    for event in events:
        if event.type == kind and event.data.get("unit") == unit:
            found = event.data
    return found


def _usd(value: float) -> str:
    return f"${value:.2f}"


def _charged(events: Sequence[PlanEvent], unit: str) -> tuple[float, int, int] | None:
    """(cost, runs, attempts) a unit was charged over all its attempts (R1): the maximum per attempt, summed, and the
    highest attempt; None when the plan never charged it. A charge without an attempt counts as attempt 1."""
    cost: dict[int, float] = {}
    runs: dict[int, int] = {}
    for event in events:
        if event.type != "plan.charged" or event.data.get("unit") != unit:
            continue
        attempt = int(event.data.get("attempt", 1) or 0)
        cost[attempt] = max(cost.get(attempt, 0.0), float(event.data.get("cost_usd") or 0))
        runs[attempt] = max(runs.get(attempt, 0), int(event.data.get("runs") or 0))
    if not cost:
        return None
    return sum(cost.values()), sum(runs.values()), max(cost)


def _accepted_lines(plan: Plan, state: PlanState, unit_id: str, batch_id: str, folded: UnitState | None) -> list[str]:
    """The findings a person accepted for the unit (its own subject and its batch's), who accepted them, and the
    verifier's answers: `addressed by the verifier`, `waived by <by> (<actor>): <reason>` (L4-YOLO-031),
    `not addressed: <evidence>`, or `no answer recorded` (L4-YOLO-028)."""
    lines: list[str] = []
    for subject in (unit_id, f"batch:{batch_id}"):
        data = state.activated_accepted.get(subject)
        if data and data.get("force"):  # L4-YOLO-062: no findings, the person's reason
            lines.append(f"- {force_line(subject, str(data.get('by', '?')), str(data.get('reason', '')))}")
            continue
        if not data or not data.get("findings"):
            continue
        lines.append(
            f"- Accepted review findings ({'' if subject == unit_id else subject + ', '}accepted by "
            f"{data.get('by', '?')} ({data.get('actor', '?')}): {data.get('reason', '')}):"
        )
        for f in data["findings"]:
            fid = finding_id(subject, f)
            if folded is not None and fid in folded.accepted_addressed:
                answer = "addressed by the verifier"
            elif (waiver := state.waived.get(fid)) is not None:
                answer = f"waived by {waiver.get('by', '?')} ({waiver.get('actor', '?')}): {waiver.get('reason', '')}"
            elif folded is not None and fid in folded.accepted_evidence:
                answer = f"not addressed: {folded.accepted_evidence[fid]}"
            else:
                answer = "no answer recorded"
            lines.append(f"  - {fid} [{f.get('criterion', '')}/{f.get('severity', '')}] {f.get('text', '')}: {answer}")
    return lines


def promotion_sentence(plan: Plan) -> str:
    if plan.promotion is None:
        return "No promotion target is set. Promotion was not performed."
    return f"Promotion to {plan.promotion.target_branch} was not performed."


def _delegate_lines(results: Sequence[LedgerEvent]) -> list[str]:
    """The delegate's decisions on the unit's questions: kind, decision, who (the model via the CLI) and cost; an
    escalation with its reason (L4-DLG-010)."""
    if not results:
        return []
    lines = ["- Delegate decisions:"]
    for r in results:
        d = r.data
        who = f" by the delegate ({d['model']} via {d['cli']})" if d.get("model") and d.get("cli") else ""
        cost = f", {_usd(float(d['cost_usd']))}" if isinstance(d.get("cost_usd"), int | float) else ""
        kind = f" ({_flat(d['kind'])})" if d.get("kind") else ""
        head = f"  - {_flat(str(d.get('question') or d.get('id') or '?'))}{kind}: "
        if d.get("status") == "answered":
            lines.append(f"{head}{_flat(str(d.get('decision') or 'answer'))}{who}{cost}")
        else:
            what = "escalated" if d.get("status") == "escalated" else "reply discarded, escalated"
            reason = f": {_flat(str(d['reason']), 300)}" if d.get("reason") else ""
            lines.append(f"{head}{what}{who}{cost}{reason}")
    return lines


def _flat(text: str, limit: int = 120) -> str:
    return " ".join(text.split())[:limit]


def render_report(
    *,
    repository: str,
    plan: Plan,
    state: PlanState,
    events: Sequence[PlanEvent],
    target_revision: str | None,
    units: Mapping[str, UnitState],
    generated_at: str,
    delegate: Mapping[str, Sequence[LedgerEvent]] | None = None,
) -> str:
    """The report of `plan` as `state` and `events` say it. `units` are the units' folded states (usage); a unit that
    is not there shows no usage. `delegate`: per unit, its final `delegate.result` events (L4-DLG-010)."""
    lines = [
        f"# Delivery plan {plan.plan_id}",
        "",
        f"- Status: {state.status}",
        f"- Repository: {repository}",
        f"- Target: {plan.target} at {target_revision or 'an unknown revision'}",
        f"- Merge: {plan.merge}",
        f"- {promotion_sentence(plan)}",
        f"- Written: {generated_at}",
    ]
    if state.completed_revision:
        lines.append(f"- Completed at: {state.completed_revision}")
    if state.stop_reason:
        where = f" ({state.stop_unit})" if state.stop_unit else ""
        detail = f": {state.stop_detail}" if state.stop_detail else ""
        lines.append(f"- Stopped: {state.stop_reason}{where}{detail}")
    if state.wait_reason:
        lines.append(f"- Waiting: {state.wait_reason}")
    lines += ["", "## Units", ""]
    batch_of = {u.id: b.id for b in plan.batches for u in b.units}
    for unit in plan.units():
        merged = _last(events, "unit.merged", unit.id)
        post = _last(events, "unit.postcheck", unit.id)
        folded = units.get(unit.id)
        integrated = state.integrated.get(unit.id)
        status = "integrated" if integrated else "merged" if unit.id in state.merged else "not integrated"
        lines.append(f"### {unit.id}")
        lines.append(f"- Result: {status}" + (f" at {integrated}" if integrated else ""))
        lines.append(f"- Pull request: {merged.get('pr') or (folded.pr if folded else None) or 'none'}")
        lines.append(f"- Merge commit: {merged.get('merge_commit') or state.merged.get(unit.id) or 'none'}")
        if post:
            detail = f" ({post['detail']})" if post.get("detail") else ""
            lines.append(f"- Post-merge check: {post.get('status')} with profile {post.get('profile')}{detail}")
        else:
            lines.append("- Post-merge check: not run")
        charged = _charged(events, unit.id)
        if charged is not None:  # the plan's own figures: they survive a restart of the unit (R1)
            lines.append(f"- Usage: {_usd(charged[0])}, {charged[1]} run(s), {charged[2]} attempt(s)")
        elif folded is not None:
            lines.append(
                f"- Usage: {_usd(folded.cost_usd)}, {folded.iteration} run(s), {folded.restarts + 1} attempt(s)"
            )
        lines += _accepted_lines(plan, state, unit.id, batch_of.get(unit.id, ""), folded)
        lines += _delegate_lines((delegate or {}).get(unit.id, ()))
        lines.append("")
    lines += ["## Batches", ""]
    for batch in plan.batches:
        if batch.id in state.accepted_batches:
            result = f"accepted at {state.accepted_batches[batch.id]}"
        elif batch.id in state.failed_batches:
            result = f"failed: {state.failed_batches[batch.id]}"
        else:
            result = "not checked"
        lines.append(f"- {batch.id} (profile {batch.acceptance_profile}): {result}")
    lines += ["", "## Usage", ""]
    lines.append(f"- Cost: {_usd(state.used.cost_usd)}")
    review = _charged(events, "plan:review")
    if review is not None:
        lines.append(f"- Of which the readiness review: {_usd(review[0])}")
    lines.append(f"- Runs that dispatched a unit: {sum(1 for e in events if e.type == 'unit.dispatched')}")
    lines.append("")
    return "\n".join(lines)
