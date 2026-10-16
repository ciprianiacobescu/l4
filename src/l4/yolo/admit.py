"""Admission and eligibility of delivery plans (yolo-mode design D2, requirements L4-YOLO-002 and L4-YOLO-010).

`admit` checks a plan against what the target head knows, without any model: unique ids, known units, resolvable
dependencies, no cycle, known acceptance profiles, profiles this runner can run (`unsupported_profile`: R7), the
target, the merge mode, open questions, intake, finished units, units another plan file already lists
(`held_by_other_plan`: R8) and external dependencies. A unit that the plan itself merged or integrated (its ledger
`state`) is done and has no unit-level finding. Every problem is a `Finding` with a code. The graph has one
node per unit and one per batch: a unit waits for the units it depends on and for the batch nodes its batch depends
on; a batch node waits for all of its units. The order is topological; among nodes ready together, batch position
decides, then unit position.

`next_eligible` is pure: from the plan, its folded state and the units' phases it names the one unit that may be
dispatched (the plan is serial) and the reason every other unit waits. `merged_not_integrated` names the units the
step must post-check before it dispatches anything (R10).
"""

import heapq
from collections.abc import Collection, Mapping

from l4.config.schema import L4Config
from l4.yolo.model import (
    PROFILE_ALL,
    PROFILE_NONE,
    Admission,
    Eligibility,
    Finding,
    Plan,
    PlanState,
    UnitInfo,
)

FINISHED_PHASES = frozenset({"merged", "archived"})
_SERVED = (
    "{who}: acceptance profile {name!r} lists e2e, but gates.e2e.serve is set and a profile run starts no app server "
    "(use all, which leaves e2e out, or a profile without e2e)"
)
_Node = tuple[str, str]  # ("u", unit id) or ("b", batch id)


def _label(node: _Node) -> str:
    return node[1]


def _duplicates(values: list[str]) -> list[str]:
    seen: set[str] = set()
    dup: list[str] = []
    for v in values:
        if v in seen and v not in dup:
            dup.append(v)
        seen.add(v)
    return dup


def _graph(plan: Plan) -> tuple[dict[_Node, list[_Node]], dict[_Node, tuple[int, int]]]:
    """Edges (node -> the nodes it waits for), without unknown or self references, and each node's tie key."""
    unit_ids = {u.id for u in plan.units()}
    batch_ids = {b.id for b in plan.batches}
    waits: dict[_Node, list[_Node]] = {}
    key: dict[_Node, tuple[int, int]] = {}
    for bi, batch in enumerate(plan.batches):
        for ui, unit in enumerate(batch.units):
            node: _Node = ("u", unit.id)
            deps: list[_Node] = [("u", d) for d in unit.depends_on if d in unit_ids and d != unit.id]
            deps += [("b", d) for d in batch.depends_on if d in batch_ids and d != batch.id]
            waits[node] = deps
            key[node] = (bi, ui)
        bnode: _Node = ("b", batch.id)
        waits[bnode] = [("u", u.id) for u in batch.units]
        key[bnode] = (bi, len(batch.units))
    return waits, key


def _find_cycle(waits: dict[_Node, list[_Node]], key: dict[_Node, tuple[int, int]]) -> list[_Node] | None:
    """The first cycle found, as the nodes in waiting order (the first one repeated at the end by the caller). Units
    are tried in file order before batches, so a cycle is named from its first unit."""
    starts = sorted(waits, key=lambda n: (n[0] == "b", key[n]))
    state: dict[_Node, int] = {}  # 1 on the path, 2 done
    path: list[_Node] = []

    def visit(node: _Node) -> list[_Node] | None:
        state[node] = 1
        path.append(node)
        for nxt in sorted(waits[node], key=lambda n: (n[0] == "b", key[n])):
            if state.get(nxt) == 1:
                return path[path.index(nxt) :]
            if nxt not in state and (found := visit(nxt)) is not None:
                return found
        path.pop()
        state[node] = 2
        return None

    for start in starts:
        if start not in state and (found := visit(start)) is not None:
            return found
    return None


def _topological(waits: dict[_Node, list[_Node]], key: dict[_Node, tuple[int, int]]) -> list[_Node]:
    left = {n: len(set(d)) for n, d in waits.items()}
    users: dict[_Node, list[_Node]] = {n: [] for n in waits}
    for n, deps in waits.items():
        for d in set(deps):
            users[d].append(n)
    ready = [(key[n], n) for n, c in left.items() if c == 0]
    heapq.heapify(ready)
    out: list[_Node] = []
    while ready:
        _, node = heapq.heappop(ready)
        out.append(node)
        for user in users[node]:
            left[user] -= 1
            if left[user] == 0:
                heapq.heappush(ready, (key[user], user))
    return out


def plan_order(plan: Plan) -> tuple[str, ...]:
    """The unit ids of an acyclic plan in admission order; units that sit on a cycle keep file order at the end."""
    waits, key = _graph(plan)
    done = [_label(n) for n in _topological(waits, key) if n[0] == "u"]
    return tuple(done + [u for u in plan.unit_ids() if u not in done])


def _needs_server(cfg: L4Config, profile: str) -> bool:
    """Whether the named profile lists `e2e` while the e2e gate needs an app server, which a profile run does not start
    (R7). `all` and `none` are never refused: `all` leaves the gate out."""
    if profile in (PROFILE_ALL, PROFILE_NONE) or not cfg.gates.e2e.serve.command.strip():
        return False
    return "e2e" in cfg.yolo.profiles.get(profile, ())


def done_units(plan: Plan, state: PlanState | None) -> frozenset[str]:
    """The units of `plan` that the plan itself already merged or integrated (its ledger state), in the plan now. The
    target holds their work: their spec may be finished, archived or gone, and that is no fault of the plan."""
    if state is None:
        return frozenset()
    return frozenset(u for u in plan.unit_ids() if u in state.integrated or u in state.merged)


def admit(
    plan: Plan,
    *,
    known_units: Mapping[str, UnitInfo],
    cfg: L4Config,
    held: Mapping[str, str] | None = None,
    state: PlanState | None = None,
    archived: Collection[str] = frozenset(),
) -> Admission:
    """Check `plan` at the target head (design D2). `known_units` holds what the spec providers found there. `held`
    maps a unit id to the id of the plan that holds it (`plans.held_by`: the activated plan, else the first file in
    path order): a unit of this plan that another plan holds is a `held_by_other_plan` finding (R8); entries naming
    this plan are no finding.

    `state` is the plan's own ledger state, when it has one. A planned unit that the plan merged or integrated is done
    (L4-YOLO-002): it is no `finished` unit, no `unknown_unit` (its change may be archived), and it has no open
    question or intake finding. It stays a unit of the graph. A plan with no state, or with nothing merged, gets no
    such leave. `archived` holds the ids of the changes archived at the target (`plans.archived_changes`): an excluded
    id that names one is known."""
    found: list[Finding] = []
    done = done_units(plan, state)

    def add(code: str, subject: str, text: str) -> None:
        found.append(Finding(code, subject, text))

    if plan.target != cfg.forge.base_branch:
        add("target_mismatch", plan.plan_id,
            f"the plan targets {plan.target}, the base branch is {cfg.forge.base_branch}")  # fmt: skip
    if plan.merge == "auto" and cfg.forge.merge_policy == "human":
        add("merge_policy", plan.plan_id, "merge: auto needs forge.merge_policy: auto in .l4/config.yaml")
    if plan.external_dependencies:
        add("external_dependencies", plan.plan_id, "external dependencies are not supported in this version")
    units = plan.units()
    if not units:
        add("empty_plan", plan.plan_id, "the plan has no unit")
    for dup in _duplicates([u.id for u in units]):
        add("duplicate_id", dup, f"unit {dup} appears more than once")
    for dup in _duplicates([b.id for b in plan.batches]):
        add("duplicate_id", dup, f"batch {dup} appears more than once")

    unit_ids = {u.id for u in units}
    batch_ids = {b.id for b in plan.batches}
    for dup in _duplicates([x.id for x in plan.exclude]):
        add("duplicate_id", dup, f"unit {dup} is excluded more than once")
    for excluded in dict.fromkeys(x.id for x in plan.exclude):
        if excluded in unit_ids:
            add("excluded_and_planned", excluded, f"unit {excluded} is both planned and excluded")
        if known_units.get(excluded) is None and excluded not in archived:
            add(
                "unknown_unit",
                excluded,
                f"excluded unit {excluded} was not found by a spec provider on the target head",
            )
    profiles = set(cfg.yolo.profiles)
    for batch in plan.batches:
        for dep in batch.depends_on:
            if dep == batch.id:
                add("self_dependency", batch.id, f"batch {batch.id} depends on itself")
            elif dep not in batch_ids:
                add(
                    "unknown_dependency",
                    batch.id,
                    f"batch {batch.id} depends on {dep}, which is not a batch of the plan",
                )
        if batch.acceptance_profile not in {PROFILE_ALL, PROFILE_NONE} | profiles:
            bad = batch.acceptance_profile
            add(
                "unknown_profile",
                batch.id,
                f"batch {batch.id}: acceptance profile {bad!r} is not all, none or in yolo.profiles",
            )
        elif _needs_server(cfg, batch.acceptance_profile):
            add("unsupported_profile", batch.id, _SERVED.format(who=f"batch {batch.id}", name=batch.acceptance_profile))
        for unit in batch.units:
            for dep in unit.depends_on:
                if dep == unit.id:
                    add("self_dependency", unit.id, f"unit {unit.id} depends on itself")
                elif dep not in unit_ids:
                    add(
                        "unknown_dependency",
                        unit.id,
                        f"unit {unit.id} depends on {dep}, which is not a unit of the plan",
                    )
            if unit.acceptance_profile not in {PROFILE_ALL} | profiles:
                bad = unit.acceptance_profile
                add(
                    "unknown_profile",
                    unit.id,
                    f"unit {unit.id}: acceptance profile {bad!r} is not all or in yolo.profiles",
                )
            elif _needs_server(cfg, unit.acceptance_profile):
                add("unsupported_profile", unit.id, _SERVED.format(who=f"unit {unit.id}", name=unit.acceptance_profile))
            if (other := (held or {}).get(unit.id)) is not None and other != plan.plan_id:
                add("held_by_other_plan", unit.id, f"unit {unit.id} is already listed in plan {other}")
            if unit.id in done:
                continue
            info = known_units.get(unit.id)
            if info is None:
                add("unknown_unit", unit.id, f"unit {unit.id} was not found by a spec provider on the target head")
                continue
            if info.open_questions:
                add("open_questions", unit.id, f"unit {unit.id} has {len(info.open_questions)} open question(s)")
            if not info.intake_ok:
                why = f": {info.intake_detail}" if info.intake_detail else ""
                add("intake", unit.id, f"unit {unit.id} fails the intake checks{why}")
            if info.phase in FINISHED_PHASES:
                add("finished", unit.id, f"unit {unit.id} is already {info.phase} and cannot be planned")

    waits, key = _graph(plan)
    cycle = _find_cycle(waits, key)
    if cycle is not None:
        names = [_label(n) for n in cycle]
        add("cycle", names[0], "dependency cycle: " + " -> ".join([*names, names[0]]))

    if found:
        return Admission(False, tuple(found), ())
    return Admission(True, (), tuple(_label(n) for n in _topological(waits, key) if n[0] == "u"))


def _unit_prereqs(plan: Plan) -> dict[str, tuple[list[str], list[str]]]:
    """unit -> (units it depends on directly, prerequisite batch ids)."""
    out: dict[str, tuple[list[str], list[str]]] = {}
    for batch in plan.batches:
        for unit in batch.units:
            out[unit.id] = (list(unit.depends_on), list(batch.depends_on))
    return out


def _order(plan: Plan, state: PlanState) -> list[str]:
    """The admission order recorded in the state when it covers the plan, else the order computed from the plan."""
    prereqs = {u.id for u in plan.units()}
    return [u for u in state.order if u in prereqs] if set(state.order) >= prereqs else list(plan_order(plan))


def merged_not_integrated(plan: Plan, state: PlanState, unit_phase: Mapping[str, str | None]) -> list[str]:
    """The units of the plan that are merged and not yet integrated, in admission order (R10): the ones the step merged
    (`state.merged`) and the ones a person merged, which show as a finished phase. The step post-checks each of them
    (D9) before it dispatches another unit, so a person's merge of a unit that was not current never stalls the
    plan (review #13)."""
    ids = {u.id for u in plan.units()}
    return [
        unit
        for unit in _order(plan, state)
        if unit in ids
        and unit not in state.integrated
        and (unit in state.merged or unit_phase.get(unit) in FINISHED_PHASES)
    ]


def unit_blocker(plan: Plan, state: PlanState, unit_id: str) -> str | None:
    """Why `unit_id` may not run or merge yet, or None: a unit it depends on, or a unit of a prerequisite batch, is not
    integrated, or a prerequisite batch is not accepted (a batch whose profile is `none` counts as accepted once its
    units are integrated). One rule for the dispatch, the activation and the merge guard."""
    integrated = state.integrated
    batches = {b.id: b for b in plan.batches}
    direct, prereq_batches = _unit_prereqs(plan).get(unit_id, ([], []))
    for dep in direct:
        if dep not in integrated:
            return f"waits for {dep} (not integrated)"
    for bid in prereq_batches:
        batch = batches.get(bid)
        if batch is None:
            continue
        for u in batch.units:
            if u.id not in integrated:
                return f"waits for {u.id} (not integrated)"
        accepted = bid in state.accepted_batches or (
            batch.acceptance_profile == PROFILE_NONE and all(u.id in integrated for u in batch.units)
        )
        if not accepted:
            return f"waits for batch {bid} (acceptance)"
    return None


def next_eligible(plan: Plan, state: PlanState, unit_phase: Mapping[str, str | None]) -> Eligibility:
    """The one unit to dispatch next and why each other unit waits (design D2, requirement L4-YOLO-010).

    A unit is eligible when it is not integrated, every unit it depends on is integrated, every unit of its prerequisite
    batches is integrated, and those batches are accepted (a batch whose profile is `none` counts as accepted once its
    units are integrated). The plan is serial: when `state.current` is set and not integrated it is the only candidate,
    and with no current unit the first eligible one in admission order is. A unit already merged (and not yet
    integrated) is never dispatched again; the plan step integrates it.
    """
    integrated = state.integrated

    def blocker(unit_id: str) -> str | None:
        return unit_blocker(plan, state, unit_id)

    prereqs = _unit_prereqs(plan)

    order = _order(plan, state)
    pending = [u for u in order if u not in integrated]
    waiting: dict[str, str] = {}
    chosen: str | None = None
    current = state.current if state.current in prereqs and state.current not in integrated else None
    if current is not None and (why := blocker(current)) is not None:
        waiting[current] = why  # a stale current unit never runs before its prerequisites (review z1, H2)
        current = None
    if current is not None:
        chosen = current
    for unit_id in pending:
        if unit_id == chosen:
            continue
        reason = blocker(unit_id)
        if reason is None and current is None and chosen is None:
            phase = unit_phase.get(unit_id)
            if phase in FINISHED_PHASES:
                reason = f"is {phase}, waits for its post-merge check"
            else:
                chosen = unit_id
                continue
        if reason is None:  # no prerequisite of its own left: only the serial order holds it (L4-YOLO-010)
            reason = f"waits for its turn: {chosen or current} runs first (one unit at a time)"
        waiting[unit_id] = reason
    return Eligibility(chosen, waiting)
