"""The delegate is never the mind that asked or judged the question (L4-DLG-002, D3).

`askers` reads who is behind a question from the unit's ledger, `delegate_constraint` turns them into the veto that
`Factory.for_role("delegate", ..., constraints=[...])` applies to each profile of `roles.delegate`, and
`independence_escalation` says when a chain with no profile left is an escalation for that reason."""

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from typing import Literal

from l4.availability.errors import RoleUnavailable
from l4.availability.fallback import Constraint
from l4.config.schema import Profile
from l4.state.fold import question_key
from l4.state.ledger import LedgerEvent
from l4.verifier.selection import same_model

# The adapters whose read-only tool mode L4 defines (D2): an `opencode` profile has none, and a `kiro-cli` read mode is
# unverified. `fake` is the scripted adapter of the tests.
DELEGATE_SERVES = ("claude-code", "codex", "fake")
INTAKE_SOURCES = ("intake_lint", "intake_open_questions")  # raised with no agent step behind them
NO_INDEPENDENT_DELEGATE = "no independent delegate"
_VETOES_BY_INDEPENDENCE = {"constraint", "serves"}


@dataclass(frozen=True)
class Asker:
    """A mind behind a question. `model` None: not recorded (a raise from before this change), so a caller that has the
    configuration resolves it from the profile. `role`: `asked` (an implementer step) or `judged` (a round's judge)."""

    profile: str | None
    model: str | None
    role: Literal["asked", "judged"] = "asked"


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _implementers(events: Iterable[LedgerEvent], configured: Iterable[str] = ()) -> list[Asker]:
    """Every implementer profile that ran a step of the unit (its ledger); the configured `roles.implementer` chain when
    the ledger names none."""
    seen: list[str] = []
    for e in events:
        if e.type == "availability.selected" and e.data.get("role") == "implementer":
            profile = _text(e.data.get("selected")) or _text(e.data.get("profile"))
            if profile and profile not in seen:
                seen.append(profile)
    if not seen:
        seen = list(dict.fromkeys(configured))
    return [Asker(profile, None, "asked") for profile in seen]


def _judges(events: Iterable[LedgerEvent]) -> list[Asker]:
    out: list[Asker] = []
    for e in events:
        if e.type == "verify.judge" and (profile := _text(e.data.get("profile"))):
            asker = Asker(profile, _text(e.data.get("model")), "judged")
            if asker not in out:
                out.append(asker)
    return out


def askers(events: Iterable[LedgerEvent], question: str, configured: Iterable[str] = ()) -> tuple[Asker, ...]:
    """Who asked `question` (`Q-001`, or `<fix unit>/Q-001`), from the unit's ledger events.

    - an intake raise (`source: intake_lint`, `intake_open_questions`) has no agent step behind it: nobody;
    - a raise that names its asker: that profile and model (`profile`, `model`), or for a verdict question the
      `judges` of its round AND every implementer profile of the unit (owner decision F9: the model that wrote the
      code never overturns the judge's dispute of it); `configured` is the `roles.implementer` chain, used when the
      ledger names no implementer step;
    - any other raise (written before this change), and a question with no raise event at all: fail safe, every
      implementer profile of the unit, and for a verdict question (or no kind) every judge profile of its rounds."""
    events = list(events)
    raise_event = next(
        (e for e in reversed(events) if e.type == "question.raised" and question_key(e) == question), None
    )
    if raise_event is None:
        return (*_implementers(events, configured), *_judges(events))
    data = raise_event.data
    if data.get("source") in INTAKE_SOURCES:
        return ()
    if data.get("kind") == "verdict":
        judges = data.get("judges")
        if isinstance(judges, list):
            named = [
                Asker(profile, _text(j.get("model")), "judged")
                for j in judges
                if isinstance(j, dict) and (profile := _text(j.get("profile")))
            ]
        else:
            named = _judges(events)
        return (*named, *_implementers(events, configured))
    if profile := _text(data.get("profile")):
        return (Asker(profile, _text(data.get("model")), "asked"),)
    return tuple(_implementers(events, configured))


def delegate_constraint(
    found: Collection[Asker], mode: Literal["model", "profile"], *, profiles: Mapping[str, Profile] | None = None
) -> Constraint:
    """The veto for each delegate profile (`Constraint` of the factory): the reason it is not independent, else None.
    `profile` vetoes a profile that is an asker's by name; `model` also one that serves an asker's model. An asker that
    recorded no model takes the configured model of its profile when `profiles` is given; a delegate profile with no
    model, or an asker whose model cannot be resolved, is a veto under `model` (the verifier's rule: fail safe)."""
    minds = tuple(found)

    def model_of(asker: Asker) -> str | None:
        if asker.model:
            return asker.model
        configured = (profiles or {}).get(asker.profile or "")
        return configured.model if configured else None

    def check(name: str, profile: Profile) -> str | None:
        for asker in minds:
            if asker.profile == name:
                subject = (model_of(asker) or name) if mode == "model" else name
                return f"independence: {mode} {subject} {asker.role} the question"
        if mode != "model":
            return None
        if not profile.model:  # the CLI would run its default model, which can be an asker's: fail safe (D3)
            return f"independence: model: delegate profile {name} has no known model"
        for asker in minds:
            theirs = model_of(asker)
            if not theirs:
                return f"independence: model: {asker.role} profile {asker.profile or 'unknown'} has no known model"
            if same_model(profile.model, theirs):
                return f"independence: model {theirs} {asker.role} the question"
        return None

    return check


def independence_escalation(exc: RoleUnavailable) -> str | None:
    """`no independent delegate` when the chain is out only because of independence (a profile an asker's, or an adapter
    that cannot serve the role), else None: an empty chain, a binary, a login or a cool-down is another cause."""
    steps = set(exc.steps)
    if "constraint" in steps and steps <= _VETOES_BY_INDEPENDENCE:
        return NO_INDEPENDENT_DELEGATE
    return None
