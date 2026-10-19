# ruff: noqa: F401, F811  (the fixtures are imported by name)
"""`l4 plan` through the CLI names the action `delegate` (delegate-answers 9.3; L4-DLG-003; SCN-DLG-10, SCN-DLG-11):
the units come from `discover`, which sets what the delegate has still to decide for the units in its scope."""

import json
from datetime import UTC, datetime

from l4.availability.cooldown import AvailabilityStore, cooldown_key
from l4.cli import main
from l4.config.schema import Profile

from ..delegate.conftest import (
    blocked,
    delegate_run,
    escalation,
    fake_clock,
    no_clarifier,
    no_hooks_but_the_delegate,
    no_verifier,
    openspec_stand_in,
    publish_base,
    run_l4,
)


def plan_entry(tdd, raw, capsys) -> dict:
    raw(tdd.repo, "fetch", "-q", "origin")
    capsys.readouterr()
    main(["plan", "--json", "--repo", str(tdd.repo)], environ=tdd.environ)
    return json.loads(capsys.readouterr().out)["units"][0]


def test_a_deferred_question_is_the_delegate_action_once_its_time_has_passed(
    delegate_run, tdd_repo, raw, capsys, fake_clock
):
    profile = Profile(adapter="fake", model="delegate-model-1")
    until = datetime(2026, 1, 2, tzinfo=UTC)  # long ago on the real clock that `l4 plan` reads
    AvailabilityStore(tdd_repo.cache).cooldowns.record("dlg", cooldown_key("dlg", profile), until, "usage_limit", "t")
    run = delegate_run([blocked("technical")])
    assert [r["status"] for r in run.events("delegate.result")] == ["deferred"]
    entry = plan_entry(tdd_repo, raw, capsys)
    assert (entry["next_action"], entry["reason"]) == ("delegate", "delegate: Q-001 to ask")
    assert entry["actionable"] is True


def test_a_decided_question_is_no_action(delegate_run, tdd_repo, raw, capsys):
    delegate_run([blocked("technical"), escalation()])
    entry = plan_entry(tdd_repo, raw, capsys)
    assert entry["next_action"] == "none" and entry["reason"].startswith("awaiting_human")


def test_the_delegate_off_names_no_action(run_l4, tdd_repo, raw, capsys):
    run_l4([blocked("technical")])
    entry = plan_entry(tdd_repo, raw, capsys)
    assert entry["next_action"] == "none"
