"""Kiro units get fix units (L4-FBK-008, L4-KSP-005; SCN-FBK-20): the family, the loop and the merge resolvers."""

import json
from pathlib import Path

import pytest

from l4.specs.base import Finding as SpecFinding
from l4.specs.base import FixUnitCapable, Framework, Marker, SpecError, UnitRef
from l4.specs.criteria import kiro_criteria
from l4.specs.fixmark import read_fix_marker, write_fix_marker
from l4.specs.harness_merge import harness_resolvers
from l4.specs.kiro import KiroProvider
from l4.verifier.fixloop import FamilyProvider, fix_units_of, is_fix_unit, without_fix_units

from ..orchestrator.test_kiro_unit import BRANCH as KIRO_BRANCH
from ..orchestrator.test_kiro_unit import (
    DISCOUNT_DONE,
    DISCOUNT_ID,
    REQUIREMENTS,
    SHOUT_ID,
    SPEC,
    TASKS,
    _events,
    _write_unit,
    script,
)
from ..specs.test_kiro_fix_unit import UUID
from .conftest import judge_reply


@pytest.fixture
def family(tmp_path: Path) -> tuple[Path, KiroProvider, UnitRef]:
    repo = tmp_path / "repo"
    spec = repo / SPEC
    spec.mkdir(parents=True)
    (spec / "requirements.md").write_text(REQUIREMENTS)
    (spec / "tasks.md").write_text(TASKS.replace("[ ]", "[x]"))
    provider = KiroProvider(repo, uuid_factory=lambda: UUID)
    return repo, provider, provider.list_units()[0]


def spawn(provider: KiroProvider, parent: UnitRef, criterion: str | None = SHOUT_ID, ordinal: int = 1) -> UnitRef:
    finding = SpecFinding(
        (f"F-0000000{ordinal}",), "Shout fails", "no capitals", "major", (criterion,) if criterion else ()
    )
    return provider.create_fix_unit(parent, ordinal, [finding], None)


def test_a_kiro_provider_is_fix_capable_so_the_family_can_fix(family):
    _, provider, parent = family
    wrapper = FamilyProvider(provider, parent)
    assert isinstance(provider, FixUnitCapable) and wrapper.can_fix
    assert wrapper.create_fix_unit(parent, 1, [SpecFinding(("F-00000001",), "x")], None).name == "discounts-fix-1"


def test_a_provider_without_fix_units_still_cannot_fix(family):
    _, provider, parent = family

    class Bare:
        framework = Framework.KIRO

    wrapper = FamilyProvider(Bare(), parent)  # type: ignore[arg-type]
    assert not wrapper.can_fix
    with pytest.raises(SpecError, match="has no fix units"):
        wrapper.create_fix_unit(parent, 1, [SpecFinding(("F-00000001",), "x")], None)


def test_the_family_lists_the_kiro_fix_units_the_parent_spawned_and_no_others(family):
    repo, provider, parent = family
    second, first = spawn(provider, parent, ordinal=2), spawn(provider, parent)
    assert [u.name for u in fix_units_of(provider, parent)] == ["discounts-fix-1", "discounts-fix-2"]
    assert is_fix_unit(first) and is_fix_unit(second) and not is_fix_unit(parent)
    other = UnitRef(Framework.KIRO, "discounts-fix-3", repo / SPEC.replace("discounts", "discounts-fix-3"))
    other.path.mkdir()
    (other.path / "bugfix.md").write_text("# Bugfix Requirements Document\n")
    write_fix_marker(other.path, read_fix_marker(first.path).__class__("kiro:somebody-else", 3, (), ()))
    assert [u.name for u in fix_units_of(provider, parent)] == ["discounts-fix-1", "discounts-fix-2"]
    assert without_fix_units([(provider, parent), (provider, first)], named=[]) == [(provider, parent)]


def test_a_restated_criterion_is_counted_once_in_the_family(family):
    """SCN-FBK-20: re-verification counts the parent's criterion once."""
    _, provider, parent = family
    fix = spawn(provider, parent, DISCOUNT_ID)  # `Req 1.1` of the parent, restated as `2.1`
    members = FamilyProvider(provider, parent)
    parents_own = kiro_criteria(parent.path)
    assert [c.id for c in members.criteria(parent)].count(DISCOUNT_ID) == 1
    assert [c.id for c in members.criteria(parent)][: len(parents_own)] == [c.id for c in parents_own]
    assert {c.id: c.alias for c in members.criteria(parent)}[DISCOUNT_ID] == "Req 1.1"  # the parent's own reading
    assert [c.alias for c in kiro_criteria(fix.path)] == ["Req 2.1"]  # the generic unchanged sentence is no criterion
    assert {c.id: c.alias for c in members.criteria(fix)}[DISCOUNT_ID] == "Req 2.1"  # what the fix task cites
    assert len(members.criteria(parent)) == len(parents_own)  # nothing of the fix unit's is new
    assert [c.id for c in members.criteria(parent)] == [c.id for c in members.criteria(fix)]  # one set, one order


def test_the_family_done_gate_and_markers_work_per_kiro_member(family):
    _, provider, parent = family
    fix = spawn(provider, parent)
    members = FamilyProvider(provider, parent)
    assert not members.done_gate(parent).passed and "discounts-fix-1" in members.done_gate(parent).reasons[0]
    members.set_marker(fix, "1.1", Marker.DONE)
    assert members.done_gate(parent).passed
    assert [t.done for t in members.tasks(parent)][-2:] == [True, True]  # the fix unit's parent task closed with it


def test_the_base_merge_resolvers_cover_kiro_fix_folders(family):
    rel = SPEC
    resolvers = harness_resolvers(rel, Framework.KIRO)
    tasks_matches, questions_matches = resolvers[1][0], resolvers[0][0]
    assert tasks_matches(f"{rel}/tasks.md") and tasks_matches(f"{rel}-fix-1/tasks.md")
    assert questions_matches(f"{rel}-fix-2/questions.md")
    assert not tasks_matches(f"{rel}-other/tasks.md") and not tasks_matches(f"{rel}-fix-1/sub/tasks.md")


# --- a failed round on a Kiro unit ends `fixing`, with the fix unit committed ---------------------------------------


def suppressed_script() -> list:
    """The unit's four steps, the last green step adding an undeclared `# noqa`: a deterministic FAIL."""
    steps = script()
    steps[-1].writes = {"src/pytdd/pricing.py": DISCOUNT_DONE + "\nUNUSED = 1  # noqa: E501\n"}
    return steps


def show(raw, tdd_repo, path: str) -> str:
    return raw(tdd_repo.origin, "show", f"{KIRO_BRANCH}:{path}")


def test_a_failed_kiro_round_spawns_a_bugfix_fix_unit_and_the_parent_is_fixing(run_l4, tdd_repo, raw):
    """SCN-FBK-20 (+): the unit is `fixing`, not `escalated`; the five files are on the branch."""
    _write_unit(tdd_repo, raw, TASKS)
    run = run_l4([*suppressed_script(), judge_step()], "--unit", "kiro:discounts", unit=False)
    assert run.code == 10, run.outcome
    assert run.outcome["units"][0]["phase_after"] == "fixing"
    events = _events(raw, tdd_repo)
    assert "escalated" not in [e["to"] for e in events if e["type"] == "phase.changed"]
    assert [e["verdict"] for e in events if e["type"] == "verify.verdict"] == ["FAIL"]
    [spawned] = [e for e in events if e["type"] == "fix.spawned"]
    assert (spawned["parent"], spawned["fix_unit"], spawned["round"]) == ("kiro:discounts", "discounts-fix-1", 1)
    assert "docs(discounts): fix unit 1 [skip ci]" in raw(tdd_repo.origin, "log", "--format=%s", f"main..{KIRO_BRANCH}")
    folder = f"{SPEC}-fix-1"
    files = raw(tdd_repo.origin, "ls-tree", "-r", "--name-only", KIRO_BRANCH, folder).split()
    assert sorted(f.removeprefix(f"{folder}/") for f in files) == [
        ".config.kiro", ".l4/fix.json", "bugfix.md", "design.md", "tasks.md",
    ]  # fmt: skip
    marker = json.loads(show(raw, tdd_repo, f"{folder}/.l4/fix.json"))
    assert marker["parent"] == "kiro:discounts" and marker["chores"] == spawned["findings"]
    tasks = show(raw, tdd_repo, f"{folder}/tasks.md")
    assert "[chore]" in tasks and "_Requirements" not in tasks  # a chore cites nothing: its tag exempts it
    assert "1.1 " in show(raw, tdd_repo, f"{folder}/bugfix.md")


def judge_step(failing: str | None = None):
    from l4.agents.fake import Step

    reply = judge_reply([DISCOUNT_ID, SHOUT_ID])
    for outcome in reply["criteria"]:
        if outcome["id"] == failing:
            outcome["verdict"] = "fail"
    return Step(structured=reply)


def answer_on_origin(tdd_repo, raw, qid: str, answer: str) -> None:
    """What a person does: clone the remote, answer a question of the Kiro unit's `questions.md`, push."""
    from l4.specs.questions import QuestionsFile, QuestionStatus

    clone = tdd_repo.repo.parent / "human"
    raw(tdd_repo.repo.parent, "clone", "-q", "--branch", KIRO_BRANCH, str(tdd_repo.origin), str(clone))
    path = clone / SPEC / "questions.md"
    file = QuestionsFile.load(path)
    assert file is not None
    file = file.set_status(qid, QuestionStatus("answered"))
    body = file.get(qid).answer.body  # type: ignore[union-attr]
    QuestionsFile.parse(file.data[: body.end] + answer.encode() + b"\n" + file.data[body.end :]).save(path)
    raw(clone, "add", "-A")
    raw(clone, "commit", "-q", "-m", f"answer {qid}")
    raw(clone, "push", "-q", "origin", KIRO_BRANCH)


def test_a_rejected_kiro_criterion_is_restated_with_its_id_next_to_the_scenario_the_person_wrote(run_l4, tdd_repo, raw):
    """SCN-FBK-20: `2.1` restates the criterion (same id) and `2.2` pins the scenario; the family counts the id once."""
    _write_unit(tdd_repo, raw, TASKS)
    first = run_l4([*script(), judge_step(SHOUT_ID)], "--unit", "kiro:discounts", unit=False)
    assert first.code == 11
    questions = show(raw, tdd_repo, f"{SPEC}/questions.md")
    assert "C-594c3674" in questions.split("## Q-002")[0]  # Q-001 asks about the failed criterion
    answer_on_origin(tdd_repo, raw, "Q-001", "reject: WHEN the name is empty THEN shout returns an empty string")
    run_l4([judge_step()], "--unit", "kiro:discounts", unit=False)
    folder = f"{SPEC}-fix-1"
    bugfix = show(raw, tdd_repo, f"{folder}/bugfix.md")
    assert "(parent Req 2.1, C-594c3674)" in bugfix
    assert "2.2 WHEN the name is empty THEN shout returns an empty string" in bugfix
    tasks = show(raw, tdd_repo, f"{folder}/tasks.md")
    assert "_Requirements: 2.1, 2.2_" in tasks
