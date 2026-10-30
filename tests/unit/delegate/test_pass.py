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
    run = delegate_run([blocked("technical"), reply(**bad)], delegate={"max_attempts_per_question": 1})
    (result,) = results(run)
    assert result["status"] == "discarded"
    assert result["reason"] == "the reply was discarded: checked spec:proposal.md does not resolve"
    assert result["decision"] == "answer"  # what it would have decided (live test P1); never its text
    assert result["checked"] == [{"ref": "spec:proposal.md", "quote": "text that is not there"}]  # never the claim
    questions = run.pushed(QUESTIONS)
    assert "- **Escalated by:** the delegate" in questions and status_of(run) == "open"
    assert "the reply was discarded: checked spec:proposal.md does not resolve" in questions
    assert run.events("question.answered") == []


def test_a_reference_discard_is_asked_again_once(delegate_run, fake_clock, monkeypatch):  # SCN-DLG-118
    why = "checked spec:proposal.md does not resolve"
    bad = {"checked": [{"ref": "spec:proposal.md", "quote": "text that is not there", "claim": "c"}]}
    told = []
    real = pass_module.build_prompt

    def spy(question, material, **kwargs):
        told.append(material.previous)
        return real(question, material, **kwargs)

    monkeypatch.setattr(pass_module, "build_prompt", spy)
    first = delegate_run([blocked("technical"), reply(**bad)])
    (deferral,) = results(first)
    assert (deferral["status"], deferral["called"], deferral["discarded"]) == ("deferred", True, why)
    assert deferral["reason"].startswith(f"the reply was discarded: {why}")
    assert deferral["checked"] == [{"ref": "spec:proposal.md", "quote": "text that is not there"}]
    assert deferral["retry_after"] == "2026-01-01T00:05:00Z" and "text" not in deferral
    questions = first.pushed(QUESTIONS)
    assert "Escalated by" not in questions and status_of(first) == "open"
    assert first.events("question.answered") == [] and told == [""]  # the first ask has no previous reply
    fake_clock.advance(timedelta(minutes=10))
    second = delegate_run([reply(**bad)])
    assert told == ["", why]  # the second ask's prompt says why the first reply was discarded
    last = results(second)[-1]
    assert (last["status"], last["decision"], last["called"]) == ("discarded", "answer", True)
    assert last["reason"] == f"the reply was discarded: {why}"
    assert last["checked"] == [{"ref": "spec:proposal.md", "quote": "text that is not there"}]
    assert [e["status"] for e in results(second)] == ["deferred", "discarded"]
    escalated = second.pushed(QUESTIONS)
    assert f"- **Escalated by:** the delegate (delegate-model-1 via fake): the reply was discarded: {why}" in escalated
    assert status_of(second) == "open"


def test_a_second_ask_that_is_answered_is_written(delegate_run, fake_clock):  # SCN-DLG-118
    bad = {"checked": [{"ref": "spec:proposal.md", "quote": "text that is not there", "claim": "c"}]}
    first = delegate_run([blocked("technical"), reply(**bad)])
    assert [e["status"] for e in results(first)] == ["deferred"]
    fake_clock.advance(timedelta(minutes=10))
    second = delegate_run([reply()])
    assert [e["status"] for e in results(second)] == ["deferred", "answered"]
    assert status_of(second) == "answered" and "Escalated by" not in second.pushed(QUESTIONS)


def test_a_reply_that_is_not_a_reference_discard_escalates_at_once(delegate_run):
    run = delegate_run([blocked("technical"), reply(checked=[])])  # no checked entry: not asked again
    (result,) = results(run)
    assert result["status"] == "discarded" and result["reason"].endswith("has no checked entry")
    assert "retry_after" not in result and "Escalated by" in run.pushed(QUESTIONS)


def test_a_reply_citing_a_harness_file_is_discarded_with_that_reason(delegate_run):  # live test P1; SCN-DLG-119
    bad = {"checked": [{"ref": "spec:questions.md", "quote": "The test freezes a wrong value", "claim": "c"}]}
    run = delegate_run([blocked("technical"), reply(**bad)])
    (result,) = results(run)  # exactly one result, and it is the discard: no deferral, no second ask
    assert result["status"] == "discarded" and len(run.events("delegate.asked")) == 1
    assert result["status"] == "discarded" and result["decision"] == "answer" and "text" not in result
    assert result["reason"] == (
        "the reply was discarded: checked spec:questions.md cites a harness-written file "
        "(questions.md, verification.md, the harness's .l4/ files): not evidence"
    )
    assert status_of(run) == "open" and run.events("question.answered") == []


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


# -- 0.4.22: a deferral for lack of time is no attempt, and three in a row stop asking for runs ------------------------

NO_TIME = {"time_budget": "30m", "soft_deadline_margin": "20m"}  # 10 minutes left, delegate.timeout is 15m


def test_a_soft_deadline_deferral_is_no_attempt(delegate_run, outcomes):  # SCN-DLG-105
    for _ in range(2):
        run = delegate_run([blocked("technical")] if not outcomes else [], ci=NO_TIME)
    assert [r["reason"] for r in results(run)] == ["soft_deadline", "soft_deadline"]
    assert run.code == 11 and len(run.events("delegate.asked")) == 0
    last = delegate_run([reply()])  # a run with time left: max_attempts_per_question is 2, and 2 were deferred
    assert status_of(last) == "answered"
    assert len(last.events("delegate.asked")) == 1
    assert not [r for r in results(last) if "attempts used" in r.get("reason", "")]


def test_the_third_soft_deadline_deferral_in_a_row_requests_no_run(delegate_run, outcomes):  # SCN-DLG-113
    for _ in range(3):
        run = delegate_run([blocked("technical")] if not outcomes else [], ci=NO_TIME)
    assert [r["reason"] for r in results(run)] == ["soft_deadline"] * 3
    assert [o.start_run for o in outcomes] == [True, True, False]  # the third waits for a scheduled or pushed run
    assert [o.deferred for o in outcomes] == [("Q-001",)] * 3 and status_of(run) == "open"


def test_a_soft_deadline_streak_is_broken_by_a_call(delegate_run, outcomes):
    from l4.delegate.limits import soft_deferrals_in_a_row
    from l4.state.ledger import LedgerEvent

    def result(seq, status, reason):
        return LedgerEvent(
            "t", "r", "u", seq, "delegate.result", {"question": "Q-001", "status": status, "reason": reason}
        )

    raised = LedgerEvent("t", "r", "u", 0, "question.raised", {"id": "Q-001"})
    events = [raised, result(1, "deferred", "soft_deadline"), result(2, "deferred", "timeout"),
              result(3, "deferred", "soft_deadline"), result(4, "deferred", "soft_deadline")]  # fmt: skip
    assert soft_deferrals_in_a_row(events, "Q-001") == 2
    assert soft_deferrals_in_a_row([raised, *events[1:2]], "Q-001") == 1
    assert soft_deferrals_in_a_row([raised], "Q-001") == 0


# -- 0.4.22: what the pass hands the checks, and the questions it does not call for ------------------------------------


def test_an_old_chore_raise_is_found_by_its_note():
    import tempfile

    from l4.delegate.run import is_chore
    from l4.implementer.loop import chore_question_note
    from l4.redact import Redactor
    from l4.specs.questions import NewQuestion, QuestionKind, QuestionsFile, raise_questions

    def question(kind, context):
        folder = Path(tempfile.mkdtemp())
        new = NewQuestion("Which fixture?", kind, ("1.1",), context, "now", ())
        raise_questions(folder, "u", [new], redactor=Redactor({}))
        return QuestionsFile.load(folder / "questions.md").get("Q-001")

    note = chore_question_note("add-x-fix-1")
    noted = question(QuestionKind.TECHNICAL, f"the fixture must change\n\n{note}")
    plain = question(QuestionKind.TECHNICAL, "the fixture must change")
    old_raise = LedgerEvent("t", "r", "u", 1, "question.raised", {"id": "Q-001", "kind": "technical"})
    new_raise = LedgerEvent("t", "r", "u", 1, "question.raised", {"id": "Q-001", "kind": "technical", "chore": True})
    assert is_chore(new_raise, plain, "add-x-fix-1")  # the field
    assert is_chore(old_raise, noted, "add-x-fix-1")  # a raise from before the field: a fix unit's note
    assert not is_chore(old_raise, noted, None)  # the note counts only in a fix unit's question
    assert not is_chore(old_raise, plain, "add-x-fix-1") and not is_chore(None, plain, None)
    product = question(QuestionKind.PRODUCT, f"x\n\n{note}")
    assert not is_chore(old_raise, product, "add-x-fix-1")


def fake_pass(found):
    from types import SimpleNamespace

    return SimpleNamespace(_target=lambda target, question, raised: found, _hold_kind=pass_module._Pass._hold_kind)


def test_a_cap_only_question_with_no_report_file_escalates_without_a_call():  # SCN-DLG-109
    from l4.delegate.prompt import VerdictMaterial

    nameless = VerdictMaterial("C-2", "criterion", "C-2", "cap", "", cap_only=True, candidate="test_totals")
    reason = pass_module._Pass._without_a_call(fake_pass(nameless), None, None, None)
    assert reason and "names no file for the candidate test test_totals" in reason
    named = VerdictMaterial("C-2", "criterion", "C-2", "cap", "", cap_only=True, candidate="t", candidate_file="a.py")
    assert pass_module._Pass._without_a_call(fake_pass(named), None, None, None) is None


def test_a_judge_view_hold_that_names_no_file_escalates_without_a_call():  # SCN-DLG-107
    from l4.delegate.prompt import VerdictMaterial
    from l4.verifier.verdicts import LEGACY_LENGTH_HOLD

    legacy = VerdictMaterial("H-1", "hold", f"H-1 {LEGACY_LENGTH_HOLD}", "", "")
    reason = pass_module._Pass._without_a_call(fake_pass(legacy), None, None, None)
    assert reason and "names no file" in reason
    seen = VerdictMaterial("H-1", "hold", "H-1 judge view: `a.py`", "", "", files=("a.py",))
    assert pass_module._Pass._without_a_call(fake_pass(seen), None, None, None) is None
    scope = VerdictMaterial("H-2", "hold", "H-2 scope: `a.py` changes module `m`", "", "")
    assert pass_module._Pass._without_a_call(fake_pass(scope), None, None, None) is None
    assert pass_module._Pass._without_a_call(fake_pass(None), None, None, None) is None


def test_the_pass_hands_the_checks_the_globs_and_the_question_facts(delegate_run, monkeypatch):
    seen = {}
    real = pass_module.check_reply

    def spy(*args, **kwargs):
        seen.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(pass_module, "check_reply", spy)
    run = delegate_run([blocked("technical"), reply()])
    assert status_of(run) == "answered"
    assert seen["chore"] is False and seen["fix_task"] is False and seen["cap_only"] is False
    assert "**/conftest.py" in seen["support_globs"] and "**/tests/**" in seen["test_globs"]
    assert seen["judge_view_files"] == () and seen["cap_only_file"] is None


# -- 0.4.44: a run that only answers questions answers all that are due (L4-DLG-003, delegate-only-pass 1.1) ----------


def passes(run):
    return run.events("delegate.pass")


def test_a_delegate_only_run_answers_past_the_cap(delegate_run):  # SCN-DLG-123
    cap = {"max_questions_per_run": 1}
    first = delegate_run([blocked(*["technical"] * 3), reply("Q-001")], delegate=cap)  # the tail of a working run
    assert [e["question"] for e in first.events("delegate.asked")] == ["Q-001"]
    second = delegate_run(
        [reply("Q-002"), reply("Q-003")], delegate=cap
    )  # nothing of the unit runs: the cap does not bind
    assert [e["question"] for e in second.events("delegate.asked")] == ["Q-001", "Q-002", "Q-003"]
    assert [status_of(second, f"Q-00{n}") for n in range(1, 4)] == ["answered"] * 3
    assert [(p["bound"], p["delegate_only"]) for p in passes(second)] == [("cap", False), ("none_due", True)]


def test_the_tail_of_a_working_run_keeps_the_cap(delegate_run, outcomes):  # SCN-DLG-124
    two = {"max_questions_per_run": 2}
    run = delegate_run([blocked(*["technical"] * 3), reply("Q-001"), reply("Q-002")], delegate=two)
    assert [e["question"] for e in run.events("delegate.asked")] == ["Q-001", "Q-002"]
    assert [(p["bound"], p["delegate_only"]) for p in passes(run)] == [("cap", False)]
    assert [o.start_run for o in outcomes] == [True]  # the next run is asked for (L4-DLG-007)


def test_a_pass_that_asked_every_question_due_ends_on_none_due(delegate_run):
    run = delegate_run([blocked("technical"), reply()], delegate={"max_questions_per_run": 2})
    assert [(p["bound"], p["delegate_only"]) for p in passes(run)] == [("none_due", False)]


def test_the_soft_deadline_still_bounds_a_delegate_only_pass(delegate_run, monkeypatch):  # SCN-DLG-125
    cap = {"max_questions_per_run": 1}
    delegate_run([blocked(*["technical"] * 3), reply("Q-001")], delegate=cap)
    monkeypatch.setattr(pass_module._Pass, "_soft_deadline", lambda self: self.calls >= 1)  # one call, then no time
    run = delegate_run([reply("Q-002")], delegate=cap)
    assert [(r["question"], r["status"]) for r in results(run)[1:]] == [
        ("Q-002", "answered"), ("Q-003", "deferred"),
    ]  # fmt: skip
    assert results(run)[-1]["reason"] == "soft_deadline"  # a capped pass would have stopped before Q-003
    assert [(p["bound"], p["delegate_only"]) for p in passes(run)][-1] == ("deadline", True)


def test_the_cost_cap_still_bounds_a_delegate_only_pass(delegate_run):  # SCN-DLG-125
    cost = {"max_questions_per_run": 1, "max_cost_usd_per_answer": 0.5, "max_cost_usd_per_unit": 1.2}
    delegate_run([blocked(*["technical"] * 3), reply("Q-001", cost=0.5)], delegate=cost)
    run = delegate_run([reply("Q-002", cost=0.5)], delegate=cost)  # 1.0 of 1.2 is spent: a call needs 0.5 for Q-003
    last = results(run)[-1]
    assert last["status"] == "escalated" and "cost cap of the unit is used" in last["reason"]
    assert [e["question"] for e in run.events("delegate.asked")] == ["Q-001", "Q-002"]
    assert [(p["bound"], p["delegate_only"]) for p in passes(run)][-1] == ("cost", True)
