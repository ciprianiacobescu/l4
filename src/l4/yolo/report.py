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
from l4.yolo.model import Plan, PlanEvent, PlanState


def _last(events: Sequence[PlanEvent], kind: str, unit: str) -> dict[str, object]:
    found: dict[str, object] = {}
    for event in events:
        if event.type == kind and event.data.get("unit") == unit:
            found = event.data
    return found


def _usd(value: float) -> str:
    return f"${value:.2f}"


def promotion_sentence(plan: Plan) -> str:
    if plan.promotion is None:
        return "No promotion target is set. Promotion was not performed."
    return f"Promotion to {plan.promotion.target_branch} was not performed."


def render_report(
    *,
    repository: str,
    plan: Plan,
    state: PlanState,
    events: Sequence[PlanEvent],
    target_revision: str | None,
    units: Mapping[str, UnitState],
    generated_at: str,
) -> str:
    """The report of `plan` as `state` and `events` say it. `units` are the units' folded states (usage); a unit that
    is not there shows no usage."""
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
        if folded is not None:
            lines.append(
                f"- Usage: {_usd(folded.cost_usd)}, {folded.iteration} run(s), {folded.restarts + 1} attempt(s)"
            )
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
    lines.append(f"- Runs that dispatched a unit: {sum(1 for e in events if e.type == 'unit.dispatched')}")
    lines.append("")
    return "\n".join(lines)
