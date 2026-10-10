"""A unit that waits for verdicts re-enters through `l4 run` without `--unit` and through `l4 verify`; an answer that
cannot be read gets the sticky note's request for a fix (simulation-harness 1.13 delta, verifier 5.8)."""

import shutil
import sys
import types

from l4 import services
from l4.agents.fake import Step
from l4.specs.questions import QuestionsFile, QuestionStatus

from ..implementer.conftest import green_step, red_step
from ..orchestrator.conftest import BRANCH, UNIT_DIR, edit_questions_on_origin, new_origin_main
from .test_ladder_depth import JUDGE, red_known_only


def test_run_without_unit_picks_a_unit_whose_verdicts_are_answered(run_l4, valid_spec, tdd_repo, raw):
    assert run_l4([red_known_only(), green_step(), JUDGE]).code == 11
    assert run_l4([], unit=False).adapter.requests == []  # nothing answered yet: the plan says none, nothing runs
    edit_questions_on_origin(tdd_repo, raw, status="answered", answer="Accept: it is covered elsewhere")
    raw(tdd_repo.repo, "fetch", "-q", "origin")
    resumed = run_l4([], unit=False)
    assert resumed.code == 0 and resumed.adapter.requests == []
    assert resumed.triggers()[-2:] == ["verdicts_answered", "verify_pass"]
    assert resumed.outcome["units"][0]["verdict"] == "PASS"


def test_l4_verify_takes_a_unit_whose_verdicts_are_answered(run_l4, run_verify, valid_spec, tdd_repo, raw):
    assert run_l4([red_known_only(), green_step(), JUDGE]).code == 11
    edit_questions_on_origin(tdd_repo, raw, status="answered", answer="accept")
    raw(tdd_repo.repo, "fetch", "-q", "origin")
    verified = run_verify([])
    assert verified.code == 0 and verified.adapter.requests == []
    assert verified.outcome["units"][0]["phase_after"] == "verified"


def test_l4_verify_still_refuses_a_unit_that_waits_for_an_answer(run_l4, run_verify, valid_spec):
    assert run_l4([red_known_only(), green_step(), JUDGE]).code == 11
    assert run_verify([]).code == 2


def test_an_unreadable_answer_gets_a_sticky_note_that_asks_for_a_fix(run_l4, valid_spec, tdd_repo, raw, monkeypatch):
    assert run_l4([red_known_only(), green_step(), JUDGE]).code == 11
    edit_questions_on_origin(tdd_repo, raw, status="answered", answer="yes")
    raw(tdd_repo.repo, "fetch", "-q", "origin")
    notes: list[tuple[str, ...] | None] = []

    class Mirror:
        def sync(self, phase, *, notes=None):
            seen.append(notes)

    seen = notes
    module = types.ModuleType("l4_test_mirror")
    module.mirror = lambda ctx: Mirror()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "l4_test_mirror", module)
    monkeypatch.setitem(services.HOOKS, "mirror", "l4_test_mirror:mirror")
    again = run_l4([])
    assert again.code == 11 and again.events("human.verdict") == [] and again.adapter.requests == []
    asked = [n[0] for n in notes if n]
    assert asked and all("Q-001" in n and "does not start with `accept` or `reject`" in n for n in asked)
    assert "Start each answer with `accept` or `reject`" in asked[-1]


def answer_all(tdd_repo, raw, text: str) -> None:
    clone = tdd_repo.repo.parent / "human-all"
    raw(tdd_repo.repo.parent, "clone", "-q", "--branch", BRANCH, str(tdd_repo.origin), str(clone))
    path = clone / UNIT_DIR / "questions.md"
    file = QuestionsFile.load(path)
    assert file is not None
    for question in list(file.questions):
        file = file.set_status(question.id, QuestionStatus.ANSWERED)
        body = file.get(question.id).answer.body  # type: ignore[union-attr]
        file = QuestionsFile.parse(file.data[: body.end] + text.encode() + b"\n" + file.data[body.end :])
    file.save(path)
    raw(clone, "add", "-A")
    raw(clone, "commit", "-q", "-m", "answer everything")
    raw(clone, "push", "-q", "origin", BRANCH)


def test_a_hold_is_asked_about_and_an_accept_lets_the_unit_pass(run_l4, valid_spec, tdd_repo, raw):
    broken = Step(structured={"verdicts": "not the schema"})
    first = run_l4([red_known_only(), green_step(), broken, broken])
    assert first.code == 11
    asked = first.events("question.raised")
    assert len(asked) == 3 and sum(e["target"].startswith("H-") for e in asked) == 1
    answer_all(tdd_repo, raw, "accept: checked by hand")
    raw(tdd_repo.repo, "fetch", "-q", "origin")
    second = run_l4([], unit=False)
    assert second.code == 0 and second.adapter.requests == []
    assert second.outcome["units"][0]["verdict"] == "PASS"


def test_an_answered_hold_is_not_asked_again_whichever_way_it_was_answered():  # m1.x F1: was "a rejected one stays"
    from l4.verifier.types import HumanVerdict
    from l4.verifier.verdicts import hold_id, unresolved_holds

    a, b, c = "the diff was cut", "the judge reply was discarded", "no scenarios"
    effective = {
        hold_id(a): HumanVerdict("Q-001", hold_id(a), "accept", "human", "", ""),
        hold_id(b): HumanVerdict("Q-002", hold_id(b), "reject", "human", "no", ""),
    }
    assert unresolved_holds([a, b, c], effective) == [c]  # a reject is a decision: `settle_holds` makes it a finding


# --- step 0 merges the base (M1.7) -----------------------------------------------------------------------------------

QUESTIONS = f"{UNIT_DIR}/questions.md"


def first_parent_chain(raw, tdd_repo) -> list[str]:
    return raw(tdd_repo.origin, "rev-list", "--first-parent", BRANCH).split()


def test_answer_on_a_branch_behind_base_merges_then_hands_off(
    run_l4, valid_spec, tdd_repo, raw, forge_env, use_fake_gitlab
):
    assert run_l4([red_known_only(), green_step(), JUDGE]).code == 11
    new_origin_main(tdd_repo, raw, {"NEWS.md": "main moved\n"})
    edit_questions_on_origin(tdd_repo, raw, status="answered", answer="accept: it is covered elsewhere")
    raw(tdd_repo.repo, "fetch", "-q", "origin")
    before = raw(tdd_repo.origin, "rev-parse", BRANCH).strip()
    base = raw(tdd_repo.origin, "rev-parse", "main").strip()
    second = run_l4([JUDGE])
    assert second.code == 0, second.outcome
    [merged] = second.events("base.merged")
    assert merged["base_sha"] == base and merged["behind"] == 1 and merged["resolved"] == []
    merge = merged["merge_sha"]
    # a real merge commit: the branch's old head first, then the base; pushed, not rewritten
    parents = raw(tdd_repo.origin, "rev-list", "--parents", "-n1", merge).split()[1:]
    assert parents[1] == base and raw(tdd_repo.origin, "merge-base", "--is-ancestor", before, parents[0]) == ""
    trailers = raw(tdd_repo.origin, "log", "-1", "--format=%(trailers:key=L4-Phase,valueonly)", merge).strip()
    assert trailers == "verifying" and "[skip ci]" in raw(tdd_repo.origin, "log", "-1", "--format=%s", merge)
    # the round was judged afresh on the merged tree, then the unit was handed off: H sits on top of the merge
    steps = [e for e in second.events("verify.step") if e["round"] == 2]
    assert steps and all(e["status"] != "reused" for e in steps) and second.adapter.requests
    assert second.outcome["units"][0]["phase_after"] == "in_review"
    chain = first_parent_chain(raw, tdd_repo)
    assert merge in chain and chain.index(merge) > 0
    assert (
        raw(tdd_repo.origin, "log", "-1", "--format=%s", BRANCH).strip()
        == "docs(add-discount-codes): hand off to review"
    )
    assert second.pushed("NEWS.md") == "main moved\n"  # H's tree holds the base's change
    # the human's accept carried over to the fresh round (SCN-VER-48)
    assert second.outcome["units"][0]["verdict"] == "PASS"


def test_conflict_exits_1_with_note_and_pushes_no_merge(run_l4, valid_spec, tdd_repo, raw, forge_env, use_fake_gitlab):
    assert run_l4([red_known_only(), green_step(), JUDGE]).code == 11
    pricing = (tdd_repo.repo / "src/pytdd/pricing.py").read_text()
    new_origin_main(
        tdd_repo, raw, {"src/pytdd/pricing.py": pricing + "\n\ndef shout(name):\n    return name.upper()\n"}
    )
    edit_questions_on_origin(tdd_repo, raw, status="answered", answer="accept: it is covered elsewhere")
    raw(tdd_repo.repo, "fetch", "-q", "origin")
    base = raw(tdd_repo.origin, "rev-parse", "main").strip()
    second = run_l4([JUDGE])
    assert second.code == 1
    assert second.adapter.requests == []  # no judge: the ladder never started
    [conflict] = second.events("base.conflict")
    assert conflict["files"] == ["src/pytdd/pricing.py"] and conflict["base_sha"] == base
    [step] = [e for e in second.events("verify.step") if e["round"] == 2]
    assert (step["step"], step["status"], step["reason"]) == ("0", "error", "base-merge-conflict")
    assert len(second.events("verify.verdict")) == 1  # round 1's only
    assert second.events("base.merged") == []
    assert raw(tdd_repo.origin, "rev-list", "--merges", f"main..{BRANCH}").strip() == ""  # no merge commit anywhere
    ancestor = subprocess_ok(tdd_repo.origin, raw, "merge-base", "--is-ancestor", base, BRANCH)
    assert not ancestor  # the base is still not part of the branch
    (mr,) = use_fake_gitlab.mrs.values()
    notes = [n["body"] for n in use_fake_gitlab.notes[mr["iid"]]]
    assert any("Base merge needed" in body and "src/pytdd/pricing.py" in body for body in notes)
    assert second.triggers()[-1] == "verdicts_answered"  # the phase stays `verifying`


def subprocess_ok(cwd, raw, *args) -> bool:
    import subprocess

    try:
        raw(cwd, *args)
    except subprocess.CalledProcessError:
        return False
    return True


def test_questions_md_on_both_sides_is_resolved_by_the_harness(run_l4, valid_spec, tdd_repo, raw):
    assert run_l4([red_known_only(), green_step(), JUDGE]).code == 11
    on_branch = raw(tdd_repo.origin, "show", f"{BRANCH}:{QUESTIONS}")
    older = QuestionsFile.parse(on_branch).set_status("Q-001", QuestionStatus.ANSWERED)
    body = older.get("Q-001").answer.body  # type: ignore[union-attr]
    older = QuestionsFile.parse(older.data[: body.end] + b"accept: main copy, older\n" + older.data[body.end :])
    new_origin_main(tdd_repo, raw, {QUESTIONS: older.data.decode()})
    edit_questions_on_origin(tdd_repo, raw, status="answered", answer="accept: branch answer, newer")
    raw(tdd_repo.repo, "fetch", "-q", "origin")
    branch_file = raw(tdd_repo.origin, "show", f"{BRANCH}:{QUESTIONS}")
    assert branch_file != older.data.decode()
    second = run_l4([JUDGE])
    assert second.code in (0, 11)
    [merged] = second.events("base.merged")
    assert merged["resolved"] == [QUESTIONS] and merged["behind"] == 1
    # the branch answer is the newer one: its file stands, byte for byte, in the merge commit
    assert raw(tdd_repo.origin, "show", f"{merged['merge_sha']}:{QUESTIONS}") == branch_file
    assert (
        raw(tdd_repo.origin, "rev-list", "--parents", "-n1", merged["merge_sha"]).split()[2]
        == raw(tdd_repo.origin, "rev-parse", "main").strip()
    )
    assert second.events("base.conflict") == []


def test_a_base_conflict_ends_its_unit_with_exit_1_and_the_units_after_it_still_run(run_l4, valid_spec, tdd_repo, raw):
    """SPEC 2: with several units in one run the exit code is the most severe one, so one unit's conflict (which
    repeats on every run until a human merges the base) must not stop the units sorted after it."""
    assert run_l4([red_known_only(), green_step(), JUDGE]).code == 11
    pricing = (tdd_repo.repo / "src/pytdd/pricing.py").read_text()
    shutil.copytree(tdd_repo.repo / UNIT_DIR, tdd_repo.repo / "openspec/changes/add-zzz")  # sorts after the unit
    new_origin_main(
        tdd_repo, raw, {"src/pytdd/pricing.py": pricing + "\n\ndef shout(name):\n    return name.upper()\n"}
    )
    edit_questions_on_origin(tdd_repo, raw, status="answered", answer="accept: it is covered elsewhere")
    raw(tdd_repo.repo, "fetch", "-q", "origin")
    every = run_l4([red_step(), green_step(), JUDGE], unit=False)  # the CI job on a push to main: every unit
    assert every.code == 1  # the conflicting unit's exit 1 is the most severe
    assert every.events("base.conflict") and every.adapter.requests  # the second unit's agent ran
    assert raw(tdd_repo.origin, "rev-parse", "--verify", "-q", "refs/heads/l4/openspec/add-zzz").strip()
    units = {u["unit"]: u for u in every.outcome["units"]}
    assert set(units) == {"openspec:add-discount-codes", "openspec:add-zzz"}
    assert units["openspec:add-discount-codes"]["phase_after"] == "verifying"
    assert units["openspec:add-zzz"]["phase_after"] != "none"
