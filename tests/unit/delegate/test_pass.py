"""The delegate pass (delegate-answers 8.1; L4-DLG-003, 005, 006, 008, 013; SCN-DLG-11, 12, 12a, 20, 21, 22, 25, 35,
36, 36a, 37): the real orchestrator parks a unit on the implementer's questions and the fake adapter plays the
delegate."""

import difflib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from l4.agents.base import ProbeResult
from l4.agents.factory import ADAPTERS, Factory
from l4.agents.fake import FakeAdapter, Step
from l4.availability.cooldown import AvailabilityStore, cooldown_key
from l4.config.schema import DelegateCfg, L4Config, Profile, RolesCfg
from l4.delegate import run as pass_module
from l4.delegate.run import select_delegate
from l4.sandbox.none import NoSandbox
from l4.specs.questions import QuestionsFile
from l4.specs.questions_cli import Refusal
from l4.state.ledger import LedgerEvent

from .conftest import BRANCH, UNIT_DIR, blocked, escalation, limit_step, reply, with_delegate

DELEGATE_ON = {"enabled": True, "scope": "all"}
QUESTIONS = f"{UNIT_DIR}/questions.md"


@pytest.fixture
def outcomes(monkeypatch):
    """The `DelegateOutcome` of every pass of the test."""
    seen = []
    real = pass_module.delegate_hook

    def recording(ctx):
        seen.append(real(ctx))
        return seen[-1]

    monkeypatch.setattr(pass_module, "delegate_hook", recording)
    return seen


def results(run):
    return run.events("delegate.result")


def status_of(run, qid="Q-001"):
    return QuestionsFile.parse(run.pushed(QUESTIONS).encode()).get(qid).status.value


# -- how many calls, and for which question --------------------------------------------------------------------


def test_one_call_per_question_oldest_first_capped(delegate_run):  # SCN-DLG-12a
    run = delegate_run(
        [blocked(*["technical"] * 3), reply("Q-001"), reply("Q-002")], delegate={"max_questions_per_run": 2}
    )
    assert run.code == 11
    assert [e["question"] for e in run.events("delegate.asked")] == ["Q-001", "Q-002"]
    assert len(run.adapter.requests) == 3  # the implementer's step, then one call for each of the two oldest
    assert [status_of(run, f"Q-00{n}") for n in range(1, 4)] == ["answered", "answered", "open"]


def test_each_question_has_its_own_constraint(tmp_path):  # SCN-DLG-06, D6: the askers differ per question
    profiles = {
        "claude-opus": Profile(adapter="claude-code", model="claude-opus-5-5", vendor="anthropic"),
        "codex-sol": Profile(adapter="codex", model="gpt-6.1-sol", vendor="openai"),
        "delegate-opus": Profile(adapter="claude-code", model="claude-opus-5-5", vendor="anthropic"),
        "delegate-sol": Profile(adapter="codex", model="gpt-6.1-sol", vendor="openai"),
    }
    cfg = L4Config(profiles=profiles, roles=RolesCfg(delegate=["delegate-opus", "delegate-sol"]))
    from l4.agents.base import ProbeCtx

    ctx = ProbeCtx(environ={"PATH": "/usr/bin"}, cwd=tmp_path, run=lambda *a: None)
    factory = Factory(cfg, ctx, adapters={n: FakeAdapter([]) for n in ("claude-code", "codex")})
    stamp = "2026-10-18T10:00:00Z"

    def raised(seq: int, qid: str, profile: str, model: str) -> LedgerEvent:
        data = {"id": qid, "profile": profile, "model": model}
        return LedgerEvent(stamp, "r-1", "u", seq, "question.raised", data)

    events = [raised(1, "Q-001", "claude-opus", "claude-opus-5-5"), raised(2, "Q-002", "codex-sol", "gpt-6.1-sol")]
    one = select_delegate(factory, "u", events, "Q-001", DelegateCfg(), profiles)
    two = select_delegate(factory, "u", events, "Q-002", DelegateCfg(), profiles)
    assert (one.profile_name, two.profile_name) == ("delegate-sol", "delegate-opus")


# -- a kept answer -------------------------------------------------------------------------------------------------


def changed_lines(before: str, after: str) -> list[str]:
    diff = difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=0)
    return [line for line in diff if line[:1] in "+-" and not line.startswith(("+++", "---"))]


def test_a_kept_answer_is_written_committed_and_recorded(delegate_run, raw, outcomes):  # SCN-DLG-20, SCN-DLG-21
    text = "Raise ValueError: proposal.md names it."
    run = delegate_run([blocked("technical"), reply(text=text)])
    assert run.code == 11
    # the file: only Q-001's Status, Answer body, index row and the Answered by line differ from the raised version
    touching = raw(run.tdd.origin, "log", "--format=%H", BRANCH, "--", QUESTIONS).split()
    after, before = (raw(run.tdd.origin, "show", f"{sha}:{QUESTIONS}") for sha in touching[:2])
    changed = changed_lines(before, after)
    assert any("Answered by:** the delegate (delegate-model-1 via fake)" in line for line in changed)
    assert all(
        any(mark in line for mark in ("Status:", "Answered by", text, "| Q-001 |", "Answer")) for line in changed
    ), changed
    assert status_of(run) == "answered"
    # the commit: the subject and body of `l4 questions`, and the run's trailers
    subject = "answer Q-001 (add-discount-codes): Which error 1?"
    assert subject in run.subjects()
    body = raw(run.tdd.origin, "log", "-1", "--format=%B", touching[0])
    for line in (
        "Status: answered", "By: delegate (delegate-model-1 via fake; profile dlg)", "Via: l4 delegate", "[skip ci]",
        "L4-Unit: openspec:add-discount-codes",
    ):  # fmt: skip
        assert line in body, line
    # the ledger
    (asked,) = run.events("delegate.asked")
    assert (asked["question"], asked["profile"], asked["model"]) == ("Q-001", "dlg", "delegate-model-1")
    assert len(asked["prompt_sha256"]) == 64
    (cost,) = [e for e in run.events("budget.cost") if e.get("role") == "delegate"]
    assert (cost["usd"], cost["profile"], cost["question"]) == (0.2, "dlg", "Q-001")
    (result,) = results(run)
    assert (result["status"], result["decision"], result["called"], result["cost_usd"]) == (
        "answered",
        "answer",
        True,
        0.2,
    )
    assert result["tasks"] == ["1.1"] and result["checked"][0]["ref"] == "spec:proposal.md"
    (answered,) = run.events("question.answered")
    assert (answered["id"], answered["by"], answered["profile"], answered["model"]) == (
        "Q-001", "delegate", "dlg", "delegate-model-1",
    )  # fmt: skip
    assert answered["answer_sha256"] == result["answer_sha256"]
    assert [(o.answered, o.start_run) for o in outcomes] == [(("Q-001",), True)]


def test_an_escalation_writes_its_line(delegate_run, outcomes):  # SCN-DLG-25
    run = delegate_run([blocked("product"), escalation()])
    assert run.code == 11
    questions = run.pushed(QUESTIONS)
    assert "- **Escalated by:** the delegate (delegate-model-1 via fake): no project document decides this" in questions
    assert status_of(run) == "open" and "Answered by" not in questions
    (result,) = results(run)
    assert (result["status"], result["decision"], result["reason"]) == (
        "escalated", "escalate", "no project document decides this",
    )  # fmt: skip
    assert run.events("question.answered") == []
    assert [(o.escalated, o.start_run) for o in outcomes] == [(("Q-001",), False)]


def test_a_discarded_reply_escalates(delegate_run):
    bad = {"checked": [{"ref": "spec:proposal.md", "quote": "text that is not there", "claim": "c"}]}
    run = delegate_run([blocked("technical"), reply(**bad)])
    (result,) = results(run)
    assert result["status"] == "discarded"
    assert result["reason"] == "checked spec:proposal.md does not resolve"
    questions = run.pushed(QUESTIONS)
    assert "- **Escalated by:** the delegate" in questions and status_of(run) == "open"
    assert run.events("question.answered") == []


def test_an_edit_refusal_escalates(delegate_run, monkeypatch):  # a draft or a moved file: the edit core refuses
    def refuse(*args, **kwargs):
        raise Refusal("Q-001 has a draft answer", "set its Status").exit()

    monkeypatch.setattr(pass_module, "build_edit", refuse)
    run = delegate_run([blocked("technical"), reply()])
    assert run.code == 11
    (result,) = results(run)
    assert result["status"] == "escalated" and result["reason"].startswith("the answer could not be written")
    assert status_of(run) == "open" and run.events("question.answered") == []


# -- the chain is not usable ---------------------------------------------------------------------------------------


def test_cooling_defers(delegate_run, tdd_repo, fake_clock):  # SCN-DLG-35
    until = datetime(2026, 1, 2, tzinfo=UTC)
    profile = Profile(adapter="fake", model="delegate-model-1")
    AvailabilityStore(tdd_repo.cache).cooldowns.record("dlg", cooldown_key("dlg", profile), until, "usage_limit", "t")
    run = delegate_run([blocked("technical")])
    assert run.code == 11 and len(run.adapter.requests) == 1  # no delegate call
    (result,) = results(run)
    assert (result["status"], result["reason"], result["retry_after"]) == (
        "deferred",
        "cooling",
        "2026-01-02T00:00:00Z",
    )
    assert result["called"] is False
    assert "Escalated by" not in run.pushed(QUESTIONS) and status_of(run) == "open"


def test_a_limit_in_the_call_cools_the_profile_and_defers(delegate_run, fake_clock):
    run = delegate_run([blocked("technical", "technical"), limit_step()])
    assert run.code == 11
    assert [(r["question"], r["status"], r["reason"]) for r in results(run)] == [
        ("Q-001", "deferred", "cooling"),
        ("Q-002", "deferred", "cooling"),
    ]  # the second finds the chain cooling at selection
    assert len(run.adapter.requests) == 2


def test_a_fix_only_cause_escalates(delegate_run, monkeypatch):  # SCN-DLG-36
    no_binary = ProbeResult("binary", False, reason="claude is not installed")
    no_login = ProbeResult("auth", False, reason="codex is not logged in")
    monkeypatch.setitem(ADAPTERS, "claude-code", lambda: FakeAdapter([], probes={"binary": no_binary}))
    monkeypatch.setitem(ADAPTERS, "codex", lambda: FakeAdapter([], probes={"auth": no_login}))
    profiles = {
        "dlg-claude": {"adapter": "claude-code", "model": "claude-opus-5-5", "vendor": "anthropic"},
        "dlg-codex": {"adapter": "codex", "model": "gpt-6.1-sol", "vendor": "openai"},
    }
    run = delegate_run([blocked("technical")], roles={"delegate": ["dlg-claude", "dlg-codex"]}, profiles=profiles)
    assert run.code == 11
    (result,) = results(run)
    assert result["status"] == "escalated" and result["called"] is False
    assert "claude is not installed" in result["reason"] and "codex is not logged in" in result["reason"]
    assert len(run.adapter.requests) == 1


def test_an_empty_chain_escalates(delegate_run):  # SCN-DLG-37
    run = delegate_run([blocked("technical")], roles={"delegate": []})
    assert run.code == 11  # not 12: the delegate is an optional role
    (result,) = results(run)
    assert result["status"] == "escalated" and "no profile is configured for it under roles" in result["reason"]


def test_a_timeout_defers_then_escalates_at_the_limit(delegate_run, fake_clock):  # SCN-DLG-36a
    first = delegate_run([blocked("technical"), Step(status="timeout")])
    (deferral,) = results(first)
    assert (deferral["status"], deferral["reason"], deferral["called"]) == ("deferred", "timeout", True)
    assert deferral["retry_after"] == "2026-01-01T00:05:00Z"
    fake_clock.advance(timedelta(minutes=10))
    second = delegate_run([Step(status="timeout")])
    last = results(second)[-1]
    assert (last["status"], last["reason"]) == ("escalated", "delegate attempts used (2)")
    assert "Escalated by:** the delegate" in second.pushed(QUESTIONS)


def test_no_time_left_defers_and_asks_for_a_run(delegate_run, outcomes):  # SCN-DLG-12
    ci = {"time_budget": "30m", "soft_deadline_margin": "20m"}  # 10 minutes left, delegate.timeout is 15m
    run = delegate_run([blocked("technical")], ci=ci)
    assert run.code == 11 and len(run.adapter.requests) == 1
    (result,) = results(run)
    assert (result["status"], result["reason"], result["called"]) == ("deferred", "soft_deadline", False)
    assert [o.start_run for o in outcomes] == [True]


# -- consent, idempotence, the worktree ----------------------------------------------------------------------------


def test_no_consent_for_agents_is_needed(delegate_run):  # SCN-DLG-22
    run = delegate_run([blocked("technical"), reply()], clarifier={"answer_by_agents": False})
    assert status_of(run) == "answered" and run.events("question.answered")[0]["by"] == "delegate"


def test_a_decided_question_is_not_asked_again(delegate_run):  # SCN-DLG-11
    first = delegate_run([blocked("technical"), escalation()])
    assert len(first.events("delegate.asked")) == 1
    second = delegate_run([])  # a call would find the script exhausted
    assert len(second.events("delegate.asked")) == 1 and len(second.adapter.requests) == 0
    assert second.code == 11


def test_the_worktree_is_detached_read_only_and_removed(delegate_run, raw, monkeypatch):
    seen = {}
    real = FakeAdapter.run

    def spy(self, req):
        if req.role == "delegate":
            cwd = Path(req.cwd)
            seen["head"] = raw(cwd, "rev-parse", "HEAD").strip()
            seen["detached"] = raw(cwd, "branch", "--show-current").strip() == ""
            seen["origin"] = raw(Path(req.cwd), "rev-parse", f"refs/remotes/origin/{BRANCH}").strip()
            seen["policy"] = req.permission_policy.mode
            seen["cwd"] = cwd
        return real(self, req)

    monkeypatch.setattr(FakeAdapter, "run", spy)
    specs = []
    wrap = NoSandbox.wrap
    monkeypatch.setattr(
        NoSandbox,
        "wrap",
        lambda self, argv, spec, env, cwd=None: specs.append(spec) or wrap(self, argv, spec, env, cwd),
    )
    run = delegate_run([blocked("technical"), reply()])
    assert seen["detached"] and seen["policy"] == "read_only"
    assert seen["head"] == seen["origin"]  # the head the delegate reads is the one on origin
    assert not seen["cwd"].exists()  # removed after the pass
    request = next(r for r in run.adapter.requests if r.role == "delegate")
    request.wrap(["true"], {})
    assert specs and specs[-1].worktree_read_only is True and specs[-1].worktree == seen["cwd"]


def test_the_chain_and_its_profiles_are_the_base_branchs(run_l4, publish_base):  # L4-DLG-001
    """The checkout of a run can differ from the base (a laptop, a branch): the delegate's chain and the profiles it
    names are read from the base, like the section's switches."""
    publish_base(**with_delegate({}))
    here = {"delegate": DELEGATE_ON, "roles": {"delegate": ["nobody"]}, "profiles": {"nobody": {"adapter": "fake"}}}
    run = run_l4([blocked("technical"), reply()], **here)
    assert run.code == 11 and status_of(run) == "answered"
    assert run.events("delegate.asked")[0]["profile"] == "dlg"  # the base's profile, not the checkout's `nobody`
