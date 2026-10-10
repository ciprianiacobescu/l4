"""clarification-loop 3.2 under M1.2 (Q9): the clarifier chain falls back at selection; a limit inside a batch keeps
the M1.1 rule (the question is unavailable and a human answers)."""

from datetime import UTC, datetime

import pytest

from l4 import services
from l4.agents.base import LimitSignal
from l4.agents.fake import Step
from l4.availability.cooldown import AvailabilityStore, cooldown_key
from l4.config.schema import Profile

from ..implementer.conftest import green_step, red_step
from .test_hook import blocked, clarifier_reply, s1

CHAIN = {
    "roles": {"clarifier": ["first", "second"], "s1_judge": ["second"]},
    "clarifier": {"s1_standin": "llm_boolean"},
    "profiles": {"first": {"adapter": "fake", "vendor": "alpha"}, "second": {"adapter": "fake", "vendor": "beta"}},
}


@pytest.fixture(autouse=True)
def only_the_implementer_and_the_clarifier(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(services.HOOKS, "verify", "l4_test_no_verifier:verify_hook")
    monkeypatch.setitem(services.HOOKS, "clarify", "l4.clarifier.clarifier:clarify_hook")


def test_a_cooling_first_clarifier_is_skipped_at_selection_and_the_next_one_answers(run_l4, tdd_repo, fake_clock):
    store = AvailabilityStore(tdd_repo.cache)
    until = datetime(2026, 1, 2, tzinfo=UTC)
    store.cooldowns.record("first", cooldown_key("first", Profile(adapter="fake")), until, "usage_limit", "test")
    run = run_l4([blocked("technical"), clarifier_reply(), s1(False), s1(True), red_step(), green_step()], **CHAIN)
    assert run.code == 0
    selected = [e for e in run.events("availability.selected") if e["role"] == "clarifier"]
    assert [(e["selected"], e["fallback_index"], e["fallback_from"]) for e in selected] == [("second", 1, "first")]
    assert selected[0]["skipped"][0]["profile"] == "first"
    (looked,) = run.events("clarifier.result")
    assert looked["profile"] == "second" and looked["status"] == "ok"


def test_a_limit_inside_a_batch_is_not_retried_on_the_next_profile(run_l4, fake_clock):
    limit = LimitSignal("fake", None, "usage_limit", None, "test", "limit reached")
    run = run_l4([blocked("technical"), Step(status="quota", limit=limit)], **CHAIN)
    assert run.code == 11  # a human answers, not exit 12
    assert len(run.adapter.requests) == 2  # the second clarifier profile was never asked
    last = run.events("phase.changed")[-1]
    assert last["trigger"] == "clarifier_needs_human" and last["reason"].startswith("clarifier unavailable")
    (looked,) = run.events("clarifier.result")
    assert looked["status"] == "unavailable"
