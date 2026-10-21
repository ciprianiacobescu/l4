"""The delegate is never the mind that asked or judged the question (L4-DLG-002, D3).

`askers` reads who is behind a question from the unit's ledger, `delegate_constraint` turns them into the veto that
`Factory.for_role("delegate", ..., constraints=[...])` applies to each profile of `roles.delegate`, and
`independence_escalation` says when a chain with no profile left is an escalation for that reason."""

import re
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from l4.availability.errors import RoleUnavailable
from l4.availability.fallback import Constraint
from l4.availability.vendor import normalise_model
from l4.config.schema import Profile
from l4.delegate.kinds import KINDS_STEP
from l4.state.fold import question_key
from l4.state.ledger import LedgerEvent

# The adapters whose read-only tool mode L4 defines (L4-DLG-015): Claude Code in plan mode, Codex read-only, and an
# `opencode` / `kiro-cli` run from an allow-list of read tools. A `command` or backend profile does not serve. `fake`
# is the scripted adapter of the tests.
DELEGATE_SERVES = ("claude-code", "codex", "opencode", "kiro-cli", "fake")
IMPLEMENTER_PHASES = ("red", "green", "single")  # the `phase` of an implementer step's `agent.finished`
INTAKE_SOURCES = ("intake_lint", "intake_open_questions")  # raised with no agent step behind them
NO_INDEPENDENT_DELEGATE = "no independent delegate"
NO_PROFILE_ANSWERS = "no delegate profile answers this kind of question"
_VETOES_BY_INDEPENDENCE = {"constraint", "serves"}


_BRACKET = re.compile(r"\[[^\]]*\]$")
_VERTEX_DATE = re.compile(r"@[^@]*$")
_TAG = re.compile(r":[^:]*$")  # `:free`, `:thinking`, a Bedrock `:0`
_BEDROCK_PREFIX = re.compile(r"^(?:[a-z][a-z0-9-]*\.)?anthropic\.")  # the shape of `MODEL_FAMILIES`' Bedrock pattern
_BEDROCK_VERSION = re.compile(r"-v\d+(?::\d+)?$")
AUTO = "auto"


def model_key(model: str | None) -> str | None:
    """One id for one model, whichever adapter names it (L4-DLG-018): lowercased and cut after its last `/`, then
    stripped, in this order, of a `[...]` context marker, a trailing `@...` (a Vertex date), a trailing `:...`, a
    leading `(<region>.)?anthropic.` and a trailing `-v<n>(:<n>)?` (Bedrock), then of a date suffix, and a `.` between
    digits folded to `-`. None for no model and for `auto` (a router: no known model)."""
    name = (model or "").strip().lower().rsplit("/", 1)[-1].strip()
    if not name or name == AUTO:
        return None
    for pattern in (_BRACKET, _VERTEX_DATE, _TAG):
        name = pattern.sub("", name)
    name = _BEDROCK_VERSION.sub("", _BEDROCK_PREFIX.sub("", name))
    key = normalise_model(name)
    return key if key and key != AUTO else None


def same_mind(a: str, b: str) -> bool:
    """Two model keys are one mind when they are equal or one is the other followed by `-` and more
    (`gpt-6.1` and `gpt-6.1-sol`; fail safe: a false veto escalates, a false pass lets a model overturn its family)."""
    return a == b or a.startswith(f"{b}-") or b.startswith(f"{a}-")


@dataclass(frozen=True)
class Asker:
    """A mind behind a question. `model` None: not recorded (a raise from before this change), so a caller that has the
    configuration resolves it from the profile. `role`: `asked` (an implementer step) or `judged` (a round's judge)."""

    profile: str | None
    model: str | None
    role: Literal["asked", "judged"] = "asked"


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _implementers(events: Sequence[LedgerEvent], configured: Iterable[str] = ()) -> list[Asker]:
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
    found = [Asker(profile, None, "asked") for profile in seen]
    # D3: an asker's model is the model the step reported, else the profile's: a profile on an alias (`opus`) is served
    # as a full id the configuration never names, so every model an implementer step reported is an asker's too
    reported: list[str] = []
    for e in events:
        if e.type == "agent.finished" and e.data.get("phase") in IMPLEMENTER_PHASES:
            model = _text(e.data.get("model"))
            if model and model not in reported:
                reported.append(model)
    return [*found, *(Asker(None, model, "asked") for model in reported)]


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
        mine = model_key(profile.model)
        if mine is None:  # the CLI would run its default or routed model, which can be an asker's: fail safe (D3)
            if profile.model or profile.adapter == "kiro-cli":  # `auto`, or no model on kiro-cli, which runs `auto`
                return f"independence: model: delegate profile {name} is routed (auto)"
            return f"independence: model: delegate profile {name} has no known model"
        for asker in minds:
            theirs = model_of(asker)
            their_key = model_key(theirs)
            if their_key is None:
                return f"independence: model: {asker.role} profile {asker.profile or 'unknown'} has no known model"
            if same_mind(mine, their_key):
                return f"independence: model {theirs} {asker.role} the question"
        return None

    return check


def independence_escalation(exc: RoleUnavailable, kind: str | None = None) -> str | None:
    """Why a chain with no profile left is an escalation for the veto it ran into, else None: an empty chain, a
    binary, a login or a cool-down is another cause. `no independent delegate` when any profile was out for
    independence (or an adapter that cannot serve) with the kinds veto beside it or not; `no delegate profile answers
    <kind> questions` when the chain is out only because no profile may answer the question's kind (L4-DLG-019)."""
    steps = set(exc.steps)
    if "constraint" not in steps or not steps <= _VETOES_BY_INDEPENDENCE:
        return None
    if len(exc.reasons) != len(exc.steps):  # a raise that carries no reasons: the independence veto, as before
        return NO_INDEPENDENT_DELEGATE
    vetoes = [why for step, why in zip(exc.steps, exc.reasons, strict=True) if step == "constraint"]
    if all(why.startswith(f"{KINDS_STEP}:") for why in vetoes):
        return f"no delegate profile answers {kind} questions" if kind else NO_PROFILE_ANSWERS
    return NO_INDEPENDENT_DELEGATE
