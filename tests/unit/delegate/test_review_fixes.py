"""Fixes from the independent review of delegate-answers (F1 to F12): each test was written first, from the reviewer's
reproduction, and failed before the fix."""

import dataclasses
from datetime import timedelta

from l4.agents.fake import FakeAdapter, Step
from l4.delegate import run as pass_module

from .conftest import blocked, reply
from .test_pass import QUESTIONS, outcomes, results  # noqa: F401  (outcomes is a fixture)

SOFT = {"time_budget": "30m", "soft_deadline_margin": "20m"}  # 10 minutes left every run, delegate.timeout is 15m


def test_f1_soft_deadline_deferrals_are_bounded(delegate_run, outcomes, fake_clock):  # noqa: F811
    """L4-DLG-013 / L4-DLG-026 (0.4.22, C4): a deferral for lack of time is no attempt, so it never escalates the
    question; the chain of free runs ends because the third deferral in a row asks for no further run."""
    delegate_run([blocked("technical")], ci=SOFT)
    for _ in range(5):
        fake_clock.advance(timedelta(minutes=1))
        last = delegate_run([], ci=SOFT)
    rs = results(last)
    assert [r["status"] for r in rs] == ["deferred"] * 6  # none escalated as `delegate attempts used`
    assert len(last.events("delegate.asked")) == 0
    assert [o.start_run for o in outcomes] == [True, True, False, False, False, False]


# -- F2: an unknown model vetoes (D3: fail safe) ----------------------------------------------------


def _independence():
    from l4.config.schema import Profile
    from l4.delegate.independence import Asker, delegate_constraint

    return Profile, Asker, delegate_constraint


def test_f2_a_delegate_profile_with_no_model_is_vetoed_under_model_independence():
    Profile, Asker, delegate_constraint = _independence()
    check = delegate_constraint([Asker("impl", "claude-opus-5-5")], "model")
    reason = check("dlg", Profile(adapter="claude-code"))
    assert reason is not None and "no known model" in reason
    assert (
        delegate_constraint([Asker("impl", "claude-opus-5-5")], "profile")("dlg", Profile(adapter="claude-code"))
        is None
    )


def test_f2_an_asker_with_no_resolvable_model_vetoes_every_candidate():
    Profile, Asker, delegate_constraint = _independence()
    dlg = Profile(adapter="codex", model="gpt-6.1-sol")
    unknown = delegate_constraint([Asker("impl", None)], "model", profiles={"impl": Profile(adapter="codex")})
    reason = unknown("dlg", dlg)
    assert reason is not None and "impl" in reason and "no known model" in reason
    unlisted = delegate_constraint([Asker("impl", None)], "model")  # no configuration to resolve it from
    assert unlisted("dlg", dlg) is not None
    known = delegate_constraint(
        [Asker("impl", None)], "model", profiles={"impl": Profile(adapter="codex", model="a-1")}
    )
    assert known("dlg", dlg) is None
    assert delegate_constraint([Asker("impl", None)], "profile")("dlg", dlg) is None  # profile mode: the name rules
    assert delegate_constraint([], "model")("dlg", dlg) is None  # an intake question has no asker


# -- F3: the model that served the call is checked against the askers -------------------------------


def test_f3_the_served_model_of_the_call_is_checked_against_the_askers(delegate_run, monkeypatch):
    monkeypatch.setattr(FakeAdapter.__init__, "__kwdefaults__", {"probes": None, "served_model": True})
    asker_step = dataclasses.replace(blocked("technical"), model="shared-model-9")
    answer = dataclasses.replace(reply(), model="shared-model-9")  # the delegate's CLI served the asker's model
    run = delegate_run([asker_step, answer])
    (res,) = run.events("delegate.result")
    assert res["status"] == "discarded" and "independence: model shared-model-9 asked the question" in res["reason"]
    assert res["called"] is True and res["model"] == "shared-model-9"
    assert run.events("question.answered") == []
    line = next(x for x in run.pushed(QUESTIONS).splitlines() if "Escalated by" in x)
    assert "shared-model-9" in line


def test_f3_another_served_model_still_answers(delegate_run, monkeypatch):
    monkeypatch.setattr(FakeAdapter.__init__, "__kwdefaults__", {"probes": None, "served_model": True})
    asker_step = dataclasses.replace(blocked("technical"), model="shared-model-9")
    answer = dataclasses.replace(reply(), model="delegate-model-1")
    run = delegate_run([asker_step, answer])
    assert [r["status"] for r in run.events("delegate.result")] == ["answered"]


# -- F10: the Escalated by line neutralises HTML comments -------------------------------------------


def test_f10_escalated_by_line_neutralises_html_comments(delegate_run):
    from .conftest import escalation

    run = delegate_run([blocked("product"), escalation(why="cannot check <!-- hidden from the reader --> this")])
    line = next(x for x in run.pushed(QUESTIONS).splitlines() if "Escalated by" in x)
    assert "<!--" not in line and "-->" not in line and "cannot check" in line


# -- F11: the cost of a call that hit a limit is recorded -------------------------------------------


def _limited(cost):
    from l4.agents.base import LimitSignal

    return Step(
        status="quota", cost_usd=cost, limit=LimitSignal("fake", None, "usage_limit", None, "test", "limit reached")
    )


def test_f11_the_cost_of_a_limited_call_is_recorded(delegate_run):
    profiles = {"dlg2": {"adapter": "fake", "vendor": "dlgco2", "model": "delegate-model-2"}}
    run = delegate_run(
        [blocked("technical"), _limited(1.10), reply(cost=0.30)], roles={"delegate": ["dlg", "dlg2"]}, profiles=profiles
    )
    assert [e["profile"] for e in run.events("delegate.asked")] == ["dlg", "dlg2"]
    costs = [e["usd"] for e in run.events("budget.cost") if e.get("role") == "delegate"]
    assert costs == [1.10, 0.30]
    assert [r["status"] for r in run.events("delegate.result")] == ["answered"]


def test_f11_an_unpriced_limited_call_counts_at_the_cap():
    from l4.delegate.limits import delegate_cost
    from l4.state.ledger import LedgerEvent

    def result(**data):
        return LedgerEvent("2026-10-18T10:00:00Z", "r-1", "u", 1, "delegate.result", {"called": True, **data})

    assert delegate_cost([result(question="Q-001", cost_usd=None)], 2.0) == 2.0
    assert delegate_cost([result(question="Q-001", cost_usd=None, unpriced_calls=1)], 2.0) == 4.0
    assert delegate_cost([result(question="Q-001", cost_usd=0.3, unpriced_calls=1)], 2.0) == 2.0


# -- F12: a worktree that is missing but still registered does not stop the next pass ----------------------------------


def test_f12_a_missing_but_registered_worktree_is_pruned(tmp_path, make_repo, raw, git_for):
    import shutil
    from types import SimpleNamespace

    repo = make_repo("head")
    (repo / "a.txt").write_text("one\n")
    raw(repo, "add", "-A")
    raw(repo, "commit", "-q", "-m", "files")
    git = git_for(repo)
    fake = SimpleNamespace(
        tree=None,
        head=git.rev_parse("HEAD"),
        benches=[SimpleNamespace(unit_cache=tmp_path)],
        s=SimpleNamespace(git=git),
    )
    first = pass_module._Pass._detached(fake)
    shutil.rmtree(first)  # the pass was killed mid-call: the folder is gone, git still lists the worktree
    fake.tree = None
    again = pass_module._Pass._detached(fake)  # a fresh pass in a persistent checkout
    assert (again / "a.txt").read_text() == "one\n"


def test_f12_a_git_failure_of_the_pass_keeps_the_parked_exit_code(delegate_run, monkeypatch):
    from l4.vcs.errors import GitError

    def broken(self):
        raise GitError(["git", "worktree", "add"], 128, "fatal: could not create the worktree")

    monkeypatch.setattr(pass_module._Pass, "_detached", broken)
    run = delegate_run([blocked("technical")])
    assert run.code == 11 and run.events("question.answered") == []


def test_f11_a_limited_call_that_ends_the_chain_is_the_results_own_call(delegate_run):
    run = delegate_run([blocked("technical"), _limited(None)])
    (result,) = run.events("delegate.result")
    assert result["called"] is True and result["cost_usd"] is None and "unpriced_calls" not in result, result


def test_f11_an_unpriced_call_that_moved_on_is_one_unpriced_call(delegate_run):
    profiles = {"dlg2": {"adapter": "fake", "vendor": "dlgco2", "model": "delegate-model-2"}}
    run = delegate_run(
        [blocked("technical"), _limited(None), reply(cost=None)], roles={"delegate": ["dlg", "dlg2"]}, profiles=profiles
    )
    (answered,) = run.events("delegate.result")
    assert answered["status"] == "answered" and answered.get("unpriced_calls") == 1
