"""`l4 yolo review --worktree`: review the working tree before the push (review-resolution design D5, tasks 2.4 and
2.5).

The dry run reads the plan file and the unit folders through a snapshot commit of the working tree (`worktree.snapshot`:
`HEAD`, the index and every ref stay), asks the judge only about the subjects whose material was not judged before (the
plan's recorded reviews and a local cache), prints what it found and records nothing on origin. `--record`, on a clean
tree only, records the events `--local` would, so that the pushed commit finds its review current in CI."""

import json
import logging
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from l4.availability.errors import RoleUnavailable
from l4.ci.detect import in_ci
from l4.config.defaults import cache_root
from l4.context import AppContext
from l4.exitcodes import ExitCode, L4Exit
from l4.implementer.tdd import RoleLimit
from l4.sandbox.base import Sandbox
from l4.specs.providers import providers_for
from l4.state.status import discover
from l4.vcs.names import unit_branch
from l4.yolo import accept, findings, judge_sandbox, worktree
from l4.yolo.admit import admit, done_units
from l4.yolo.commands import (
    _append,
    _event,
    _findings_text,
    _held,
    _money,
    _open,
    _plan_id,
    _print_findings,
    _stamp,
    _sync,
    _valid,
    _verdict_json,
)
from l4.yolo.cycle import REVIEW_KEY, review_batches
from l4.yolo.digest import RevisionMissing, plan_digest
from l4.yolo.model import Plan, PlanEvent, ReviewResult, Verdict
from l4.yolo.plans import archived_at, plan_files, unit_infos
from l4.yolo.readiness import PROMPT_VERSION, delivered_on_target, review_plan_costed
from l4.yolo.state import fold_plan

log = logging.getLogger("l4.yolo.review_worktree")

CACHE_FILE = "verdicts.jsonl"
_BLOCKED_STATES = ("active", "waiting", "cancelled", "completed")


# --- the local cache ----------------------------------------------------------------------------------------------


def cache_path(app: AppContext, plan_id: str) -> Path:
    return cache_root(app.environ, repo=app.repo) / "yolo" / plan_id / "review" / CACHE_FILE


def read_cache(path: Path) -> dict[str, dict[str, Any]]:
    """Material key -> the cached line (newest wins) of the current prompt version; a line that cannot be read is
    skipped, since a cache is only ever a shortcut."""
    found: dict[str, dict[str, Any]] = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return found
    for raw in text.splitlines():
        try:
            line = json.loads(raw)
        except ValueError:
            continue
        entry = line.get("entry") if isinstance(line, dict) else None
        key = line.get("material") if isinstance(line, dict) else None
        if not isinstance(entry, dict) or not key or line.get("prompt_version") != PROMPT_VERSION:
            continue
        if entry.get("verdict") is None:
            continue
        found[str(key)] = line
    return found


def append_cache(path: Path, lines: Sequence[Mapping[str, Any]]) -> None:
    if not lines:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            for line in lines:
                handle.write(json.dumps(dict(line), sort_keys=True) + "\n")
    except OSError as exc:  # the cache is the person's convenience: a full disk must not lose the review
        log.warning("the review cache could not be written: %s", exc)


# --- the run ------------------------------------------------------------------------------------------------------


class _Sandboxes:
    """`sandbox_for` for `review_plan_costed`: `judge_sandbox.choose`, remembering the label and the profile that the
    recorded event carries, and saying so when the judge runs without bwrap."""

    def __init__(self, ctx: Any, say: Any) -> None:
        self.ctx, self.say = ctx, say
        self.label: str | None = None
        self.profile: str | None = None

    def __call__(self, adapter: str, profile: str) -> Sandbox:
        app, cfg = self.ctx.app, self.ctx.cfg
        sandbox, label = judge_sandbox.choose(cfg, app.environ, app.repo, adapter=adapter, in_ci=in_ci(app.environ))
        self.label, self.profile = label, profile
        if label == "none" and cfg.sandbox.mode == "auto":
            why = judge_sandbox.unsandboxed_reason(app.environ, app.repo)
            if why:
                self.say(f"judge unsandboxed ({why}): it has no tools and runs in an empty folder")
        return sandbox


def _subject_names(plan: Plan) -> set[str]:
    return {*plan.unit_ids(), *(f"batch:{b.id}" for b in plan.batches if len(b.units) > 1)}


def _unit_infos_for_render(plan: Plan, infos: Mapping[str, Any]) -> dict[str, findings.UnitInfo]:
    out: dict[str, findings.UnitInfo] = {}
    for batch in plan.batches:
        for unit in batch.units:
            info = infos.get(unit.id)
            out[unit.id] = findings.UnitInfo(
                folder=info.folder if info else None, batch=batch.id, depends_on=tuple(unit.depends_on)
            )
        out[f"batch:{batch.id}"] = findings.UnitInfo(batch=batch.id)
    return out


def _review_total(events: Sequence[PlanEvent]) -> float:
    return max(
        (
            float(e.data.get("cost_usd") or 0)
            for e in events
            if e.type == "plan.charged" and e.data.get("unit") == REVIEW_KEY
        ),
        default=0.0,
    )


def _uncommitted(git: Any, paths: Sequence[str]) -> list[str]:
    done = git.run("status", "--porcelain=v1", "--untracked-files=all", "--", *paths)
    return [line[3:].strip() for line in done.stdout.splitlines() if line.strip()]


def run_review_worktree(app: AppContext, *, plan: str, fresh: Sequence[str], record: bool, no_run: bool) -> ExitCode:
    """Review the working tree for `plan`. Exit 0 when every subject is READY or holds an acceptance, else 2. `no_run`
    is accepted for symmetry with `l4 yolo review`: this command starts no run."""
    plan_id = _plan_id(plan)
    ctx = _open(app)
    rev = _sync(ctx, who="review")
    file = next((f for f in plan_files(ctx.app.repo) if f.plan_id == plan_id), None)
    if file is None:
        raise L4Exit(ExitCode.USAGE_ERROR, f"review: no plan file .l4/plans/{plan_id}.json in the working tree")
    parsed = _valid(ctx, file, "review")
    store = ctx.store(plan_id)
    read = store.read()
    state = fold_plan(plan_id, read.events)
    if state.status in _BLOCKED_STATES:
        raise L4Exit(
            ExitCode.USAGE_ERROR, f"review: {plan_id} is {state.status}: a plan is reviewed before it is activated"
        )
    unknown = sorted(set(fresh) - _subject_names(parsed))
    if unknown:
        raise L4Exit(
            ExitCode.USAGE_ERROR,
            f"review: --fresh names {', '.join(unknown)}, which is not a unit or a batch (batch:<id>) of {plan_id}",
        )
    found = discover(ctx.cfg, ctx.git, providers_for(ctx.cfg, ctx.app.repo, ctx.app.environ))
    infos = unit_infos(ctx.app.repo, found, parsed.known_ids(), check_intake=True)
    phases = {snapshot.ref.id: snapshot.state.phase for _, snapshot in found}
    archived = archived_at(ctx.git, rev, ctx.cfg)
    admission = admit(
        parsed,
        known_units=infos,
        cfg=ctx.cfg,
        held=_held(ctx, plan_id, state),
        state=state,
        archived=archived,
    )
    if not admission.ok:
        ctx.say(f"{plan_id}: not admitted, nothing to review (run l4 yolo check {plan_id})")
        _print_findings(ctx, _findings_text(admission, plan_id))
        return ExitCode.USAGE_ERROR
    paths = [file.path, *dict.fromkeys(infos[u].folder for u in parsed.unit_ids() if u in infos)]
    if record:
        dirty = _uncommitted(ctx.git, paths)
        if dirty:
            listed = "\n".join(f"  {p}" for p in dirty)
            raise L4Exit(
                ExitCode.USAGE_ERROR,
                f"review: --record needs the plan file and the unit folders committed:\n{listed}\n"
                f"Commit them, or run l4 yolo review {plan_id} --worktree without --record.",
            )
        assert worktree.clean(ctx.git, paths)
    snap = worktree.snapshot(ctx.git, paths)
    for unit in parsed.unit_ids():
        branch = unit_branch(unit, ctx.cfg.forge.branch_prefix)
        if unit in infos and ctx.git.rev_parse(f"refs/remotes/origin/{branch}") is not None:
            ctx.say(f"CI reads {unit} on its branch {branch}; this review read the working tree")
    ledger = findings.prior_entries(read.events, PROMPT_VERSION)
    cache_file = cache_path(ctx.app, plan_id)
    cached = read_cache(cache_file)
    prior: dict[str, dict[str, Any]] = {
        **{k: {**line["entry"], "at": line.get("at")} for k, line in cached.items()},
        **ledger,
    }  # the ledger wins: it is the shared record
    sandboxes = _Sandboxes(ctx, ctx.say)
    ctx.say(f"plan {plan_id} at the working tree: plan digest {plan_digest(file.text)}")
    try:
        result, cost = review_plan_costed(
            ctx.app,
            ctx.cfg,
            parsed,
            infos,
            git=ctx.git,
            rev=snap,
            done=done_units(parsed, state),
            delivered=delivered_on_target(archived, phases),
            prior=prior,
            fresh=tuple(fresh),
            revs=dict.fromkeys(infos, snap),
            sandbox_for=sandboxes,
        )
    except RoleLimit as exc:
        raise L4Exit(ExitCode.WAITING_CAPACITY, f"review: the judge hit a usage limit: {exc}") from None
    except RoleUnavailable as exc:
        raise L4Exit(ExitCode.WAITING_CAPACITY, f"review: no judge could answer, nothing was recorded: {exc}") from None
    except RevisionMissing as exc:
        raise L4Exit(ExitCode.USAGE_ERROR, f"review: {exc}") from None
    batches = review_batches(parsed, result)
    subjects: dict[str, tuple[str, Verdict]] = {
        **{u: ("unit", v) for u, v in result.units.items()},
        **{f"batch:{b}": ("batch", v) for b, v in batches.items()},
    }
    judged_now = {s: v for s, (_, v) in subjects.items() if v.material and not v.reused_from}
    reused = {s: v for s, (_, v) in subjects.items() if v.reused_from}
    from_cache = {s: v for s, v in reused.items() if v.material not in ledger and v.material in cached}
    stamp = _stamp()
    append_cache(
        cache_file,
        [
            {
                "material": v.material,
                "prompt_version": PROMPT_VERSION,
                "judge": sandboxes.profile,
                "sandbox": sandboxes.label,
                "kind": subjects[s][0],
                "subject": s,
                "entry": _entry(v),
                "at": stamp,
            }
            for s, v in judged_now.items()
            if not _no_review(v)
        ],
    )
    _show(ctx, parsed, state, read.events, infos, result, batches, subjects, reused)
    shown = parsed.limits.max_cost_usd
    recorded = _review_total(read.events)
    limit = f"${shown:.2f}" if shown is not None else "no limit"
    if record:
        ctx.say(f"cost: ${cost:.2f} ({len(judged_now)} judged, {len(reused)} reused)")
        labels = [sandboxes.label] if sandboxes.label else []
        labels += [str(cached[v.material]["sandbox"]) for v in from_cache.values() if cached[v.material].get("sandbox")]
        judges = [sandboxes.profile] if sandboxes.profile else []
        judges += [str(cached[v.material]["judge"]) for v in from_cache.values() if cached[v.material].get("judge")]
        digest = plan_digest(file.text)
        reviewed: dict[str, Any] = {
            "plan_digest": digest,
            "prompt_version": PROMPT_VERSION,
            "source": "worktree",
            "cost_usd": cost,
            "by": ctx.who(),
            "units": {u: _recorded(v, ledger) for u, v in result.units.items()},
            "batches": {b: _recorded(v, ledger) for b, v in batches.items()},
        }
        if labels:
            reviewed["sandbox"] = "none" if "none" in labels else labels[0]
        if judges:
            reviewed["judge"] = judges[0]
        events = [
            _event("plan.admitted", plan_digest=digest, order=list(admission.order), merge=parsed.merge),
            _event("plan.reviewed", **reviewed),
        ]
        if cost > 0:
            events.append(
                _event("plan.charged", unit=REVIEW_KEY, attempt=0, cost_usd=round(recorded + cost, 6), runs=0)
            )
        _append(store, events, read.head)
        ctx.say(f"recorded review cost of the plan: {_money(recorded + cost)} of {limit}")
    else:
        budget = f" of {limit}" if shown is not None else ""
        ctx.say(f"cost: ${cost:.2f} in judge calls (a dry run is not charged to the plan's budget{budget})")
    ok = _all_clear(state, result, batches)
    if record:
        ctx.say("Next: git push; CI finds this review current and does not review again")
    elif ok:
        ctx.say(
            f"Next: commit the plan file and the unit folders, then l4 yolo review {plan_id} --worktree --record, "
            "then git push"
        )
    else:
        ctx.say(f"Next: change the specification as the Resolve lines say, then l4 yolo review {plan_id} --worktree")
    return ExitCode.OK if ok else ExitCode.USAGE_ERROR


def _no_review(verdict: Verdict) -> bool:
    return any(f.get("criterion") in findings.HARNESS_CRITERIA for f in verdict.findings)


def _entry(verdict: Verdict) -> dict[str, Any]:
    entry = _verdict_json(verdict)
    if verdict.material:
        entry["material"] = verdict.material
    return entry


def _recorded(verdict: Verdict, ledger: Mapping[str, Any]) -> dict[str, Any]:
    """The ledger entry of a verdict: a reuse of a recorded entry keeps `reused_from`; one taken from the local cache
    has no earlier judgement in the ledger to point at, so it is recorded as the judgement it is."""
    entry = _entry(verdict)
    if not (verdict.reused_from and verdict.material in ledger):
        entry.pop("reused_from", None)  # `_verdict_json` carries it; `findings.judged()` would drop this round
    return entry


def _review_data(result: ReviewResult, batches: Mapping[str, Verdict]) -> dict[str, Any]:
    return {
        "units": {u: _entry(v) for u, v in result.units.items()},
        "batches": {b: _entry(v) for b, v in batches.items()},
    }


def _all_clear(state: Any, result: ReviewResult, batches: Mapping[str, Verdict]) -> bool:
    holds = accept.holds(state, _review_data(result, batches))
    subjects = {**result.units, **{f"batch:{b}": v for b, v in batches.items()}}
    return all(v.verdict == "READY" or holds.get(s, False) for s, v in subjects.items())


def _show(
    ctx: Any,
    parsed: Plan,
    state: Any,
    events: Sequence[PlanEvent],
    infos: Mapping[str, Any],
    result: ReviewResult,
    batches: Mapping[str, Verdict],
    subjects: Mapping[str, tuple[str, Verdict]],
    reused: Mapping[str, Verdict],
) -> None:
    for name, (kind, verdict) in subjects.items():
        mark = " (reused)" if name in reused else ""
        if kind == "unit":
            ctx.say(
                f"  {name}: digest {verdict.digest or 'none'}, material {verdict.material or 'none'}: "
                f"{verdict.verdict}{mark}"
            )
        else:
            ctx.say(f"  {name}: material {verdict.material or 'none'}: {verdict.verdict}{mark}")
    review = _review_data(result, batches)
    plan_id = parsed.plan_id
    lines = findings.render(
        plan_id,
        ctx.target,
        review,
        lambda subject: findings.history(events, subject, PROMPT_VERSION),
        units=_unit_infos_for_render(parsed, infos),
        accepted=state.accepted,
        holds=accept.holds(state, review),
    )
    for line in lines:
        ctx.say(line)
