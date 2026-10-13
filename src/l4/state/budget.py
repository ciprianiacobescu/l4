"""The fix-round and feedback-round budgets of a unit (SPEC L4-IMP-013, L4-FBK-006): the configured limit plus what a
member's resume extended it by."""

from l4.config.schema import L4Config
from l4.state.fold import UnitState

FEEDBACK_ROUNDS_EXHAUSTED = "feedback_rounds_exhausted"  # `phase.changed{to: escalated, reason}`
LABEL_FEEDBACK_ROUNDS = 1  # one `l4:resume` label event on a unit escalated for the feedback limit (L4-FBK-006)
LABEL_FIX_ROUNDS = 1  # one `l4:resume` label event on an escalated unit with its fix rounds used up (L4-CI-004)


def fix_round_limit(cfg: L4Config, state: UnitState) -> int:
    """`verifier.max_fix_rounds` and every `budget.extended{fix_rounds}` the fold has seen."""
    return cfg.verifier.max_fix_rounds + state.fix_rounds_extra


def fix_rounds_exhausted(cfg: L4Config, state: UnitState) -> bool:
    """The fix units spawned have reached the limit: a resume of an escalated unit then needs an extension. Feedback
    fix units are not counted (L4-FBK-006)."""
    return state.fix_rounds_counted >= fix_round_limit(cfg, state)


def feedback_round_limit(cfg: L4Config, state: UnitState) -> int:
    """`feedback.max_rounds` and every `budget.extended{feedback_rounds}` the fold has seen (design D8)."""
    return cfg.feedback.max_rounds + state.feedback_rounds_extra


def feedback_rounds_left(cfg: L4Config, state: UnitState) -> int:
    """Feedback fix units that may still be spawned: the limit less `feedback_rounds_used`, never below 0."""
    return max(feedback_round_limit(cfg, state) - state.feedback_rounds_used, 0)


def feedback_rounds_exhausted(state: UnitState) -> bool:
    """The unit is `escalated` for the feedback limit: its `phase.changed` reason is `feedback_rounds_exhausted`."""
    return state.phase == "escalated" and state.halt_reason == FEEDBACK_ROUNDS_EXHAUSTED
