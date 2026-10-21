"""Which kinds of question a delegate profile may answer (delegate-answers 22.2; L4-DLG-019, design A5).

The delegate's `verdict` answers overturn the judge (and under `merge: auto` an accept merges), its `product` and
`ambiguous` answers decide what the specification leaves open, and nothing after them checks the answer against the
person's intent; a `technical` answer is implemented test-first and verified, and a `harness` accept reaches the judge
labelled `delegate_override`. So a weak model answers only the last two:

- `profiles.<p>.options.delegate_kinds` narrows what a profile answers (never widens `delegate.kinds`);
- a free-tier model (an OpenCode Zen id `opencode/...`, or an id ending `:free`, read as configured) answers only
  `technical` and `harness`, whatever its options say;
- the restriction is a factory veto per question, so a fallback never reaches a weak profile for a verdict."""

from collections.abc import Collection

from l4.availability.fallback import Constraint
from l4.config.schema import DELEGATE_KINDS, DelegateCfg, Profile

FREE_ZEN_PREFIX = "opencode/"
FREE_TAG = ":free"
FREE_TIER_KINDS = ("technical", "harness")  # what a free-tier model may answer
OPTION = "delegate_kinds"
KINDS_STEP = "kinds"  # the prefix of the reason of this veto: `kinds: <p> answers <kinds> questions`


def is_free_tier(model: str | None) -> bool:
    """An OpenCode Zen id or an id ending `:free`, as configured (before the model identity cut of L4-DLG-018)."""
    name = (model or "").strip().lower()
    return name.startswith(FREE_ZEN_PREFIX) or name.endswith(FREE_TAG)


def unknown_kinds(profile: Profile) -> list[str]:
    """The entries of `options.delegate_kinds` that are no question kind (DLG-001 fails on them; the pass skips the
    profile). A value that is not a list is itself unknown."""
    value = profile.options.get(OPTION)
    if value is None:
        return []
    if not isinstance(value, list):
        return [str(value)]
    return [str(k) for k in value if k not in DELEGATE_KINDS]


def allowed_kinds(profile: Profile, cfg: DelegateCfg) -> frozenset[str]:
    """The kinds this profile may answer: those of `delegate.kinds`, narrowed by `options.delegate_kinds` (an unknown
    entry is ignored, a value that is no list names nothing) and by the free-tier rule. Options narrow, never widen."""
    kinds = set(cfg.kinds)
    value = profile.options.get(OPTION)
    if value is not None:
        kinds &= {k for k in value if isinstance(k, str)} if isinstance(value, list) else set()
    if is_free_tier(profile.model):
        kinds &= set(FREE_TIER_KINDS)
    return frozenset(kinds)


def join_kinds(kinds: Collection[str]) -> str:
    """`technical`, `technical and harness`, `product, ambiguous and verdict`; `no` for none, in the canonical order."""
    ordered = [k for k in DELEGATE_KINDS if k in set(kinds)]
    if not ordered:
        return "no"
    return ordered[0] if len(ordered) == 1 else f"{', '.join(ordered[:-1])} and {ordered[-1]}"


def kinds_constraint(kind: str, cfg: DelegateCfg) -> Constraint:
    """The veto of one question (a `Constraint` of the factory): why a profile may not answer `kind`, else None."""

    def check(name: str, profile: Profile) -> str | None:
        if bad := unknown_kinds(profile):
            return f"{KINDS_STEP}: {name} names an unknown kind in options.{OPTION} ({', '.join(bad)})"
        if kind in allowed_kinds(profile, cfg):
            return None
        return f"{KINDS_STEP}: {name} answers {join_kinds(allowed_kinds(profile, cfg))} questions"

    return check
