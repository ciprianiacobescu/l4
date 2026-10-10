"""The fix-round budget of a unit (SPEC L4-IMP-013): the configured limit plus what a member's resume extended it by."""

from l4.config.schema import L4Config
from l4.state.fold import UnitState

LABEL_FIX_ROUNDS = 1  # one `l4:resume` label event on an escalated unit with its fix rounds used up (L4-CI-004)


def fix_round_limit(cfg: L4Config, state: UnitState) -> int:
    """`verifier.max_fix_rounds` and every `budget.extended{fix_rounds}` the fold has seen."""
    return cfg.verifier.max_fix_rounds + state.fix_rounds_extra


def fix_rounds_exhausted(cfg: L4Config, state: UnitState) -> bool:
    """The fix units spawned have reached the limit: a resume of an escalated unit then needs an extension."""
    return state.fix_round >= fix_round_limit(cfg, state)
