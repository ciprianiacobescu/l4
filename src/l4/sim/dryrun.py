"""`l4 run --dry-run [--probe]` (SPEC L4-SIM-001, simulation-harness 2.5, 2.6, 2.8 reduced): what a run would do,
with no lease, worktree, agent process, push or forge write.

It plans the way `l4 run` does (same snapshots, same `next_action`), renders the next step's prompt of each unit that
would implement into `.l4-out/dry-run/<run-id>/<unit>/<task>-<phase>.prompt.md`, and prints the implementer command
(`build_command` with placeholders for the paths a run creates), the gate commands, the names (never the values) of the
environment variables the agent would get, a decision table, and `would exit N` as its last line. The command itself
exits 0. Only git reads happen; in CI the ref refresh (a fetch) is a read of the remote.
The prompt is rendered from the unit snapshot, not by `tdd._prompt` (that one needs a worktree, git and the ledger), so
a block that another increment adds to `_prompt` reaches the dry run only when it is added here too: the
previous-attempt block never (a dry run has no attempt), the lessons block by M1.5 at its merge (parallel-ownership
C14). The unit's context (sources, conventions, the task's block, the budget) comes from `prompt_inputs`, the builder
of the run itself, so it cannot drift; the console shows its budget, steering decisions and cuts (L4-IMP-054).
M1: `verify --dry-run` and `init --dry-run`, prompts for later steps of the same unit.
"""

import re
import shlex
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

import click

from l4.agents.base import PermissionPolicy, RunRequest
from l4.agents.claude_code import ClaudeCodeAdapter
from l4.agents.codex import CodexAdapter
from l4.clarifier.inject import render_answer_blocks
from l4.config.preflight import preflight_run_config
from l4.config.redaction import load_app_config
from l4.config.schema import L4Config, Profile
from l4.context import AppContext
from l4.exitcodes import ExitCode, most_severe
from l4.fsutil import atomic_write_bytes
from l4.implementer.prompt import PromptContext, render_prompt
from l4.implementer.result import RESULT_SCHEMA
from l4.implementer.tasks import select_next_step, task_scope
from l4.implementer.unit_context import Cut, cut_summary, prompt_inputs, safe_label
from l4.memory.inject import branch_changed_files, inject_for_task, task_paths
from l4.orchestrator import ACTIONABLE
from l4.outcome import CommandResult, TaskCounts, UnitOutcome
from l4.planner import PlanEntry, compute_plan, facts_of, with_plan_holds
from l4.sandbox.base import SandboxSpec
from l4.sandbox.env import build_agent_env
from l4.sim.availability import AvailabilityView, NullAvailability, ProbingAvailability, roles_needed
from l4.specs.base import SpecProvider, UnitRef
from l4.specs.detect import require_framework
from l4.specs.providers import providers_for
from l4.specs.questions import blocked_tasks
from l4.state.ledger import ledger_path
from l4.state.status import UnitSnapshot, load_snapshot, refresh_refs, select_units
from l4.vcs.git import Git
from l4.vcs.merge import base_moved
from l4.vcs.names import unit_branch

DRY_DIR = "dry-run"
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")
# what `run_command` does with a unit that is named with `--unit` but has no next action (orchestrator `_drive`)
_EXIT_OF_PHASE = {
    "awaiting_human": ExitCode.AWAITING_HUMAN,
    "halted": ExitCode.HALTED,
    "escalated": ExitCode.HALTED,
    "fixing": ExitCode.HALTED,
    "rejected": ExitCode.REJECTED,
}


@dataclass(frozen=True)
class Step:
    """What one unit would do first."""

    unit: str
    phase: str
    action: str
    task: str | None  # the task an `implement` would start
    step: str | None  # `red` for an implement that has a task
    availability: str  # of the role the action needs: unknown / usable / unavailable
    expected_exit: ExitCode
    prompt: Path | None = None
    command: str | None = None
    base_moved: str | None = None  # step 0 would merge the base: what and where it can conflict
    held: str | None = None  # a delivery plan holds the unit: why (a named run of it exits 13)
    context: "ContextReport | None" = None  # the budget, the steering decisions and the cuts of the prompt (L4-IMP-054)


@dataclass(frozen=True)
class ContextReport:
    """What a person needs to see of the prompt's context before a run: the budget and its key, every steering decision,
    and every source that is cut or not read."""

    budget_tokens: int
    budget_source: str  # `implementer` or `profile:<name>`
    steering: tuple[dict[str, object], ...]
    cuts: tuple[Cut, ...]

    def lines(self) -> list[str]:
        if self.budget_source == "implementer":
            key = "implementer.context_budget_tokens"
        elif self.budget_source == "model_window":
            key = "capped at 60% of the model's context window"
        else:
            key = f"profiles.{safe_label(self.budget_source.removeprefix('profile:'))}.context_budget_tokens"
        head = f"context: budget {self.budget_tokens} tokens ({key})" + ("" if self.cuts else ", nothing cut")
        steering = [
            f"steering: {safe_label(str(d['path']))} included ({d['why']})"
            if d["included"]
            else f"steering: {safe_label(str(d['path']))} left out ({d['why']})"
            for d in self.steering
        ]
        return [head, *steering, *(f"cut: {cut_summary(c)}" for c in self.cuts)]


def _safe(text: str) -> str:
    return _UNSAFE.sub("-", text)


def _head(cfg: L4Config, role: str) -> tuple[str, Profile] | None:
    chain: list[str] = getattr(cfg.roles, role)
    return (chain[0], cfg.profiles[chain[0]]) if chain and chain[0] in cfg.profiles else None


def _implementer_command(cfg: L4Config, profile: Profile) -> str | None:
    """The argv a run would start for the implementer, with placeholders for the paths a run creates. None for an
    adapter that has no command (the fake one)."""
    request = RunRequest(
        profile=profile, role="implementer", cwd=Path("<worktree>"), prompt="",
        result_path=Path("<agent-tmp>/result.json"), raw_events_path=Path("<agent-raw>/events.jsonl"), env={},
        result_schema=RESULT_SCHEMA,
        permission_policy=PermissionPolicy("implement", gate_prefix=cfg.gates.test.command),
    )  # fmt: skip
    if profile.adapter == "claude-code":
        return shlex.join(ClaudeCodeAdapter().build_command(request, exe="claude"))
    if profile.adapter == "codex":
        return shlex.join(CodexAdapter().build_command(request, exe="codex", schema_path=Path("<output-schema>")))
    return None


def _env_names(app: AppContext) -> list[str]:
    spec = SandboxSpec(
        "agent", Path("<worktree>"), Path("<git-common-dir>/.git"), Path("<agent-tmp>"), Path("<home>"),
        adapter="dry-run", cache_root=Path("<cache>"), tool_paths=(),
    )  # fmt: skip
    return sorted(build_agent_env(app.environ, spec))


def _gates(cfg: L4Config) -> list[str]:
    gates = cfg.gates
    parts = [
        ("setup", gates.setup),
        ("test", [gates.test.command]),
        ("lint", gates.lint),
        ("typecheck", gates.typecheck),
    ]
    return [f"{name}: {' ; '.join(commands)}" for name, commands in parts if any(commands)]


def _prompt(
    app: AppContext, cfg: L4Config, provider: SpecProvider, ref: UnitRef, snapshot: UnitSnapshot, task_key: str,
    title: str, profile_name: str, profile: Profile,
) -> tuple[str, ContextReport]:  # fmt: skip
    answers = ""
    if snapshot.questions is not None:
        scope = task_scope(snapshot.tasks, task_key)
        answers = render_answer_blocks(snapshot.questions.questions, app.redactor.redact_text, tasks=scope).text
    # the files an earlier task already pushed to the unit branch scope the lessons as in the real run; the lessons are
    # read from the main checkout, not from a unit worktree that a dry run does not have
    branch = unit_branch(ref.id, cfg.forge.branch_prefix)
    base, head = (f"refs/remotes/origin/{name}" for name in (cfg.forge.base_branch, branch))
    pushed = branch_changed_files(Git(app.repo, environ=app.environ), base, head)
    lessons = inject_for_task(app.repo, cfg.memory, task_paths(title, pushed), redact=app.redactor.redact_text).block
    task = next(t for t in snapshot.tasks if t.key == task_key)
    inputs = prompt_inputs(  # the one builder of the run: the dry run cannot drift on the context
        root=app.repo, provider=provider, ref=ref, task=task, tasks=snapshot.tasks, changed=pushed, cfg=cfg,
        profile_name=profile_name, profile=profile,
    )  # fmt: skip
    ctx = PromptContext(
        unit_id=ref.id, adapter=profile.adapter or "", task_key=task_key, task_title=title,
        task_links=task.links,  # a Kiro leaf's refs (K20)
        source_files=inputs.source_files, conventions=inputs.conventions, task_block=inputs.task_block,
        unit_rel=inputs.unit_rel, budget_source=inputs.budget_source, window_tokens=inputs.window_tokens,
        criteria=inputs.criteria,
        own_criteria=inputs.own_criteria,
        gate_command=cfg.gates.test.command, context_budget_tokens=inputs.budget_tokens,
        static_gate_commands=(*cfg.gates.lint, *cfg.gates.typecheck),
        data_blocks=(
            *((("answered questions", answers),) if answers else ()),
            *((("lessons", lessons),) if lessons else ()),
        ),
        run_ledger=ledger_path(provider.unit_dir(ref), app.run_id).resolve().relative_to(app.repo.resolve()).as_posix(),
    )  # fmt: skip
    rendered = render_prompt("red", ctx)
    report = ContextReport(rendered.budget_tokens, rendered.budget_source, tuple(inputs.steering), rendered.cuts)
    return app.redactor.redact_text(rendered.text), report


def _step(
    app: AppContext, cfg: L4Config, view: AvailabilityView, provider: SpecProvider, ref: UnitRef,
    snapshot: UnitSnapshot, entry: PlanEntry, held: str | None = None,
) -> Step:  # fmt: skip
    phase = entry.phase or "none"
    roles = roles_needed({entry.next_action})
    status = view.head(roles[0]).status if roles else "unknown"
    base = Step(ref.id, phase, entry.next_action, None, None, status, _EXIT_OF_PHASE.get(phase, ExitCode.OK))
    if held is not None:  # a plan holds it: the real run refuses it by name and starts nothing otherwise
        return replace(base, held=held, expected_exit=ExitCode.HALTED, availability="unknown")
    if entry.next_action != "implement":
        return base
    head = _head(cfg, "implementer")
    expected = ExitCode.WAITING_CAPACITY if status == "unavailable" else ExitCode.OK
    file = snapshot.questions
    pending = [t.key for t in snapshot.tasks if not t.done and not t.optional]
    blocked = blocked_tasks(file.questions, pending, file.unreadable_ids) if file else frozenset()
    task = select_next_step(snapshot.tasks, blocked)
    if task is None or head is None:  # nothing eligible: the real run parks the unit or waits for a person
        return Step(ref.id, phase, entry.next_action, None, None, status, expected)
    text, context = _prompt(app, cfg, provider, ref, snapshot, task.key, task.title, head[0], head[1])
    target = app.out_dir / DRY_DIR / app.run_id / _safe(ref.id) / f"{_safe(task.key)}-red.prompt.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(target, text.encode("utf-8"))
    return Step(
        ref.id, phase, entry.next_action, task.key, "red", status, expected, target,
        _implementer_command(cfg, head[1]), context=context,
    )  # fmt: skip


def _base_moved(cfg: L4Config, git: Git, unit_id: str) -> str | None:
    """`base moved: ...` when the unit's remote branch lacks the base head (the next run's step 0 merges it)."""
    branch = unit_branch(unit_id, cfg.forge.branch_prefix)
    moved = base_moved(git, f"refs/remotes/origin/{cfg.forge.base_branch}", f"refs/remotes/origin/{branch}")
    if moved is None:
        return None
    both = ", ".join(moved.both) or "none"
    return (
        f"base moved: step 0 merges {cfg.forge.base_branch}@{moved.base_sha[:12]} "
        f"({moved.behind} commit{'' if moved.behind == 1 else 's'} behind; changed on both sides: {both})"
    )


def _render(app: AppContext, cfg: L4Config, steps: Sequence[Step], exit_code: ExitCode) -> str:
    out = ["l4 run --dry-run: no lease, worktree, agent, push or forge write"]
    for s in steps:
        out.append(f"\n{s.unit}  phase={s.phase}  next={s.action}" + (f"  task={s.task} ({s.step})" if s.task else ""))
        if s.held is not None:
            out.append(f"  held: {s.held}")
        if s.base_moved is not None:
            out.append(f"  {s.base_moved}")
        if s.prompt is not None:
            out.append(f"  prompt:  {s.prompt.relative_to(app.repo).as_posix()}")
        if s.context is not None:
            out.extend(f"  {line}" for line in s.context.lines())
        if s.command is not None:
            out.append(f"  command: {s.command}")
            out.append(f"  env:     {' '.join(_env_names(app))}  (names only)")
        if s.action == "implement":
            out.extend(f"  gate {line}" for line in _gates(cfg))
    header = ("UNIT", "PHASE", "ACTION", "TASK", "AVAILABILITY", "EXIT")
    rows = [(s.unit, s.phase, s.action, s.task or "-", s.availability, str(int(s.expected_exit))) for s in steps]
    widths = [max(len(r[i]) for r in [header, *rows]) for i in range(len(header))]
    table = [
        "  ".join(c.ljust(w) for c, w in zip(r, widths, strict=True)).rstrip()
        for r in ([header, *rows] if rows else [header])
    ]
    return "\n".join([*out, "", *table, "", f"would exit {int(exit_code)}"])


def run_dry(app: AppContext, *, units: tuple[str, ...] = (), probe: bool = False) -> CommandResult:
    app, cfg = load_app_config(app)
    preflight_run_config(app, cfg)
    require_framework(cfg, app.repo)
    git = Git(app.repo, environ=app.environ)
    refresh_refs(app, cfg, git)
    pairs = select_units(providers_for(cfg, app.repo, app.environ), units)
    snapshots = {ref.id: load_snapshot(p, git, ref, branch_prefix=cfg.forge.branch_prefix) for p, ref in pairs}
    planned = compute_plan([facts_of(s) for s in snapshots.values()])
    shown = with_plan_holds(
        app, cfg, list(snapshots.values()), planned
    )  # delivery plans hold their units (L4-YOLO-010)
    held = {a.unit: a.reason for a, b in zip(shown, planned, strict=True) if a is not b}
    entries = {e.unit: e for e in shown}
    chosen = [(p, ref) for p, ref in pairs if units or entries[ref.id].next_action in ACTIONABLE]
    view: AvailabilityView = (
        ProbingAvailability(cfg, app.environ, app.repo) if probe else NullAvailability(cfg)
    )  # no probe unless asked (SCN-DRY-02)
    steps = [_step(app, cfg, view, p, ref, snapshots[ref.id], entries[ref.id], held.get(ref.id)) for p, ref in chosen]
    steps = [replace(s, base_moved=_base_moved(cfg, git, s.unit)) for s in steps]
    would = most_severe(s.expected_exit for s in steps) if steps else ExitCode.OK
    click.echo(app.redactor.redact_text(_render(app, cfg, steps, would)))
    outcomes = [_outcome(snapshots[s.unit]) for s in steps]
    return CommandResult(ExitCode.OK, outcomes, tuple(s.unit for s in steps))


def _outcome(snapshot: UnitSnapshot) -> UnitOutcome:
    phase = snapshot.state.phase or "none"
    return UnitOutcome(
        unit=snapshot.ref.id, phase_before=phase, phase_after=phase,  # a dry run changes nothing
        tasks=TaskCounts(done=snapshot.tasks_done, total=snapshot.tasks_total),
        open_questions=list(snapshot.state.questions.open), iteration=snapshot.state.iteration,
    )  # fmt: skip
