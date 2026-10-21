"""What `Orchestrator` works with for one unit, and the hooks later changes plug in (implementer-tdd-loop D8).

`Services` is built after the unit is leased, its worktree exists and its ledger is open. The hooks are resolved
lazily with the rule `l4.commands.dispatch` uses for handlers: a hook whose module does not exist is absent, any
other import problem is an error. `forge`, `verify`, `mirror`, `handoff` and `clarify` are resolved; `lessons` is absent
(M1: memory-lessons).
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from l4.agents.base import AgentAdapter, ProbeCtx
from l4.agents.factory import Factory
from l4.availability.cooldown import AvailabilityStore, SystemClock
from l4.commands import import_optional
from l4.config.defaults import cache_root
from l4.config.schema import L4Config
from l4.context import AppContext
from l4.proc import run_process
from l4.sandbox.base import Sandbox
from l4.sandbox.none import AbsentSandbox
from l4.sandbox.select import select_sandbox
from l4.specs.base import SpecProvider, UnitRef, UnknownUnit
from l4.specs.providers import provider_for_unit, providers_for
from l4.state.ledger import LedgerWriter
from l4.state.lifecycle import Trigger
from l4.vcs.git import Git
from l4.vcs.names import UnitNames

if TYPE_CHECKING:
    from l4.clarifier.ports import ClarifyOutcome
    from l4.delegate.run import DelegateOutcome
    from l4.verifier.fixloop import FixOutcome

# hook name -> "module:function". Each function takes a `HookContext`.
HOOKS: dict[str, str] = {
    "forge": "l4.archive:forge_hook",
    "verify": "l4.verifier.ladder:verify_hook",
    "mirror": "l4.archive:mirror_hook",
    "handoff": "l4.archive:handoff_hook",
    "clarify": "l4.clarifier.clarifier:clarify_hook",
    "fix": "l4.verifier.fixloop:fix_hook",
    "delegate": "l4.delegate.run:delegate_hook",
}


class ForgeHook(Protocol):
    """Returned by `forge_hook(ctx)`: how this unit's pushes authenticate, and what follows each one (the draft
    MR after the first push)."""

    push_config: Sequence[tuple[str, str]]  # `git -c key=value` pairs, passed to every push

    def after_push(self, phase: str | None) -> None: ...


class MirrorHook(Protocol):
    """Returned by `mirror_hook(ctx)`: keeps the MR's labels and sticky note in step; called after every push and
    phase change. `notes` are the sticky note's sections: None leaves the note alone, an empty sequence clears it."""

    def sync(self, phase: str | None, notes: Sequence[str] | None = None) -> None: ...


@dataclass(frozen=True)
class Hooks:
    """`forge` and `mirror` may return None: nothing to do for this run (no forge credential). `handoff` returns
    False when it handed nothing off (the unit stays `verified`, exit 0); None or True: the unit is in review."""

    forge: Callable[["HookContext"], ForgeHook | None] | None = None
    verify: Callable[["HookContext"], Trigger] | None = None  # runs the ladder, returns the lifecycle trigger
    mirror: Callable[["HookContext"], MirrorHook | None] | None = None
    handoff: Callable[["HookContext"], bool | None] | None = (
        None  # hand-off commit, push, MR ready; then HAND_OFF_PUSHED
    )
    clarify: Callable[["HookContext"], "ClarifyOutcome"] | None = None  # the clarifier on the unit's open questions;
    # the outcome names the phase that follows (`implementing`, or `awaiting_human` with a sticky section)
    fix: Callable[["HookContext"], "FixOutcome"] | None = None  # the open fix unit's tasks: done, blocked or halt
    delegate: Callable[["HookContext"], "DelegateOutcome"] | None = None  # the delegate pass (L4-DLG-003)


@dataclass
class Services:
    app: AppContext
    ref: UnitRef  # the unit inside the worktree
    provider: SpecProvider  # bound to the worktree
    names: UnitNames
    worktree: Path
    git: Git  # runs in the worktree
    ledger: LedgerWriter
    sandbox: Sandbox
    factory: Factory
    hooks: Hooks = field(default_factory=Hooks)


H_PUSHED = "h_pushed"  # key in `HookContext.shared`: the hand-off commit is on the remote


@dataclass(frozen=True)
class HookContext:
    cfg: L4Config
    services: Services
    push: Callable[[], None]  # push the unit branch (never forced) and run the forge and mirror hooks
    shared: dict[str, Any] = field(default_factory=dict)  # what the hooks of one run keep in common (the forge client)


def load_hooks(registry: Mapping[str, str] | None = None) -> Hooks:
    found: dict[str, Callable] = {}
    for name, target in (HOOKS if registry is None else registry).items():
        module_name, _, function = target.partition(":")
        module = import_optional(module_name)
        if module is not None:
            found[name] = getattr(module, function)
    return Hooks(**found)


def build_services(
    app: AppContext,
    cfg: L4Config,
    *,
    git: Git,
    names: UnitNames,
    worktree: Path,
    ledger: LedgerWriter,
    adapters: Mapping[str, AgentAdapter] | None = None,
    hooks: Hooks | None = None,
    sandbox: bool = True,
) -> Services:
    """Fails closed: no usable sandbox is `SandboxUnavailable` (exit 3) before anything else exists. `sandbox=False`
    is for `l4 resume`, which runs no agent and no gate: the unit gets a sandbox that refuses every use."""
    chosen = (
        select_sandbox(cfg.sandbox, app.environ, repo=app.repo, events=ledger)
        if sandbox
        else AbsentSandbox("resume runs no agent or gate")
    )
    provider = provider_for_unit(providers_for(cfg, worktree, app.environ), names.unit_id)
    ref = next((r for r in provider.list_units() if r.id == names.unit_id), None)
    if ref is None:
        raise UnknownUnit(f"{names.unit_id} is not in the worktree {worktree}")
    probe = ProbeCtx(app.environ, cache_root(app.environ, repo=app.repo), run_process, forbid=(app.repo, worktree))
    return Services(
        app=app, ref=ref, provider=provider, names=names, worktree=worktree, git=git.at(worktree), ledger=ledger,
        sandbox=chosen, factory=Factory(
            cfg, probe, events=ledger, adapters=adapters, clock=SystemClock(),
            availability=AvailabilityStore(cache_root(app.environ, repo=app.repo)),
        ),
        hooks=load_hooks() if hooks is None else hooks,
    )  # fmt: skip
