"""The delegate pass through the real orchestrator: `FakeAdapter` is every role's agent and its script is consumed in
call order (the implementer's blocked step, then one delegate call for each question the pass asks)."""

from collections.abc import Callable
from typing import Any

import pytest

from l4 import services
from l4.agents.base import LimitSignal
from l4.agents.fake import Step

from ..orchestrator.conftest import (  # noqa: F401  (the fixtures `run_l4` needs)
    BRANCH,
    UNIT_DIR,
    fake_clock,
    install_hooks,
    no_clarifier,
    no_verifier,
    openspec_stand_in,
    run_l4,
)

QUOTE = "Unknown codes are rejected with `ValueError`."  # proposal.md of the fixture unit
DELEGATE = {"enabled": True, "scope": "all"}
CHAIN = {"delegate": ["dlg"]}
PROFILES = {"dlg": {"adapter": "fake", "vendor": "dlgco", "model": "delegate-model-1"}}


def blocked(*kinds: str) -> Step:
    """The implementer's red step blocks on one question of each kind given (all hold task 1.1)."""
    from ..implementer.conftest import result

    questions = [
        {"title": f"Which error {n}?", "context": "what does an unknown code raise", "kind": kind, "options": []}
        for n, kind in enumerate(kinds, 1)
    ]
    return Step(structured=result("red", status="blocked", questions=questions))


def reply(question: str = "Q-001", decision: str = "answer", **over: Any) -> Step:
    """The delegate's document for a technical question, with a claim that resolves in the unit folder."""
    cost = over.pop("cost", 0.2)
    base = {
        "question": question, "decision": decision, "text": "Raise ValueError.",
        "reason": "proposal.md names the exception",
        "checked": [{"ref": "spec:proposal.md", "quote": QUOTE, "claim": "unknown codes raise ValueError"}],
    }  # fmt: skip
    return Step(structured={**base, **over}, cost_usd=cost)


def escalation(question: str = "Q-001", why: str = "no project document decides this") -> Step:
    return reply(question, "escalate", text="", reason=why, checked=[])


def limit_step() -> Step:
    return Step(status="quota", limit=LimitSignal("fake", None, "usage_limit", None, "test", "limit reached"))


@pytest.fixture(autouse=True)
def no_hooks_but_the_delegate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(services.HOOKS, "delegate", "l4.delegate.run:delegate_hook")


@pytest.fixture
def publish_base(tdd_repo, raw) -> Callable[..., None]:
    """`publish(**config)`: this `.l4/config.yaml` on the base branch, where the pass reads the delegate's section."""

    def publish(**config: Any) -> None:
        tdd_repo.write_config(**config)
        raw(tdd_repo.repo, "add", ".l4/config.yaml")
        raw(tdd_repo.repo, "commit", "-q", "--allow-empty", "-m", "the delegate on the base branch")
        raw(tdd_repo.repo, "push", "-q", "origin", "main")
        raw(tdd_repo.repo, "fetch", "-q", "origin")

    return publish


def with_delegate(config: dict[str, Any]) -> dict[str, Any]:
    """The defaults of the delegate's tests under `config`: `delegate=`, `roles=` and `profiles=` replace key by key."""
    config["delegate"] = {**DELEGATE, **config.get("delegate", {})}
    config["roles"] = {**CHAIN, **config.get("roles", {})}
    config["profiles"] = {**PROFILES, **config.get("profiles", {})}
    return config


@pytest.fixture
def delegate_run(run_l4, publish_base) -> Callable[..., Any]:  # noqa: F811
    """`run(script, **config)`: the delegate is on for scope `all` with the one fake profile `dlg`, on the base branch
    (the pass reads it there) and in the checkout; `delegate=` and `roles=` replace the defaults key by key."""

    def run(script: list[Step], *flags: str, **config: Any):
        config = with_delegate(config)
        publish_base(**config)
        return run_l4(script, *flags, **config)

    return run
