"""The hint that names the delegate where an agent is stuck (L4-DLG-021, design B1).

One pure function, `delegate_hint`, gives the sentence or None; every surface that shows it (`l4 questions`,
`l4 status --unit`, `l4 yolo status`, the sticky note's waiting section) calls it, so the four say the same thing in the
same cases: the delegate is off on the base branch **and that configuration was read**, the unit waits on questions
(`awaiting_human`, or `fixing` with a waiting fix unit), one open question is of a kind the delegate answers, and the
unit would be in scope were the delegate on."""

from collections.abc import Iterable

from l4.config.schema import L4Config
from l4.delegate.scope import PlansView, in_scope, plans_view
from l4.delegate.settings import REMOTE_REF, DelegateSettings
from l4.vcs.git import Git
from l4.yolo.accept import target_full_config

WAITING_PHASES = ("awaiting_human", "fixing")
HINT_TEMPLATE = (
    "Hint: the delegate can answer these questions in CI: set delegate.enabled: true and roles.delegate in "
    ".l4/config.yaml on {base} (docs/runbook.md 7.1, the delegate)."
)


def hint_text(base: str) -> str:
    return HINT_TEMPLATE.format(base=base)


def delegate_hint(
    settings: DelegateSettings | None,
    unit: str,
    view: PlansView,
    phase: str | None,
    open_kinds: Iterable[str],
    *,
    fix_of: str | None = None,
) -> str | None:
    """`settings` is None when the base configuration could not be read (`delegate_settings` would then fall back to
    its defaults, and a default `enabled: false` says nothing about the base): no hint."""
    if settings is None or settings.delegate.enabled or phase not in WAITING_PHASES:
        return None
    if not set(open_kinds) & set(settings.delegate.kinds):
        return None
    on = settings.delegate.model_copy(update={"enabled": True})  # `in_scope` is False for a section that is off
    if not in_scope(unit, view, on, phase=phase, fix_of=fix_of):
        return None
    return hint_text(view.target)


def readable_base_settings(git: Git, base: str) -> DelegateSettings | None:
    """The delegate's settings at `origin/<base>`, or None when its configuration is absent or invalid."""
    full = target_full_config(git, f"{REMOTE_REF}{base}")
    if full is None:
        return None
    return DelegateSettings(full.delegate, list(full.roles.delegate), dict(full.profiles))


class HintReader:
    """The base settings and the plans view of one command, each read once and only when a unit needs them."""

    def __init__(self, git: Git, cfg: L4Config) -> None:
        self.git, self.cfg = git, cfg
        self._settings: tuple[DelegateSettings | None] | None = None
        self._view: PlansView | None = None

    def hint(self, unit: str, phase: str | None, open_kinds: Iterable[str], *, fix_of: str | None = None) -> str | None:
        kinds = list(open_kinds)
        if phase not in WAITING_PHASES or not kinds:
            return None  # the cheap exits first: no read of the base for a unit that waits on nothing
        if self._settings is None:
            self._settings = (readable_base_settings(self.git, self.cfg.forge.base_branch),)
        settings = self._settings[0]
        if settings is None or settings.delegate.enabled:
            return None
        if self._view is None:
            self._view = plans_view(self.git.repo, self.cfg, self.git)
        return delegate_hint(settings, unit, self._view, phase, kinds, fix_of=fix_of)
