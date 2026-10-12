import json
from pathlib import Path

import pytest

from l4.agents.fake import Step
from l4.security.protected import ProtectedSet
from l4.specs.base import Finding, Framework, Marker, SpecError, UnitRef
from l4.specs.fixmark import FixMarker, chore_findings, read_fix_marker, write_fix_marker
from l4.specs.openspec import OpenSpecProvider
from l4.verifier.fixloop import (
    FamilyProvider,
    family_tasks,
    family_units,
    fix_units_of,
    is_fix_unit,
    without_fix_units,
)

from ..implementer.conftest import IMPL, red_step, result
from ..orchestrator.conftest import BRANCH, UNIT_DIR
from ..specs.conftest import GREETING_DELTA
from ..specs.fixcli import FixCli
from .conftest import judge_reply
from .test_ladder_fix import CRITERIA, FIX_DIR, FIX_UNIT, chore_fix, judge, noqa_green


@pytest.fixture(autouse=True)
def no_fix_loop() -> None:
    """The fix loop is on, as in `test_ladder_fix`."""


@pytest.fixture
def family(tmp_path: Path) -> tuple[Path, OpenSpecProvider, UnitRef]:
    repo = tmp_path / "repo"
    change = repo / "openspec" / "changes" / "add-greeting"
    (change / "specs" / "greeting").mkdir(parents=True)
    (change / "tasks.md").write_text("# Tasks\n\n- [x] 1.1 greet\n")
    (change / "specs" / "greeting" / "spec.md").write_text(GREETING_DELTA)
    provider = OpenSpecProvider(repo, {}, cli=FixCli(repo))  # type: ignore[arg-type]
    return repo, provider, provider.list_units()[0]


def spawn(provider: OpenSpecProvider, parent: UnitRef, ordinal: int, *, chore: bool = False) -> UnitRef:
    return provider.create_fix_unit(
        parent, ordinal, [Finding((f"F-0000000{ordinal}",), f"fix {ordinal}", chore=chore)], None
    )


def test_fix_units_of_lists_the_parents_fix_units_in_the_order_they_were_spawned(family):
    repo, provider, parent = family
    second, first = spawn(provider, parent, 2), spawn(provider, parent, 1)
    assert [u.name for u in fix_units_of(provider, parent)] == ["add-greeting-fix-1", "add-greeting-fix-2"]
    assert is_fix_unit(first) and is_fix_unit(second) and not is_fix_unit(parent)
    other = UnitRef(Framework.OPENSPEC, "add-greeting-fix-3", repo / "openspec" / "changes" / "add-greeting-fix-3")
    other.path.mkdir()
    write_fix_marker(other.path, FixMarker("openspec:somebody-else", 3, (), ()))
    assert [u.name for u in fix_units_of(provider, parent)] == ["add-greeting-fix-1", "add-greeting-fix-2"]


def test_the_family_provider_reads_the_whole_family_and_writes_per_unit(family):
    _, provider, parent = family
    fix = spawn(provider, parent, 1)
    family_provider = FamilyProvider(provider, parent)
    assert [t.done for t in family_provider.tasks(parent)] == [True, False]  # the parent's list is the family's
    assert [t.key for t in family_provider.tasks(fix)] == ["1.1"] and not family_provider.tasks(fix)[0].done
    assert [t.done for _, t in family_tasks(family_provider, parent)] == [True, False]
    assert [u.name for u in family_units(family_provider, parent)] == ["add-greeting", "add-greeting-fix-1"]
    assert family_units(provider, parent) == [parent]  # an ordinary provider has just the unit
    assert not family_provider.done_gate(parent).passed and "fix-1" in family_provider.done_gate(parent).reasons[0]
    family_provider.set_marker(fix, "1.1", Marker.DONE)
    assert family_provider.done_gate(parent).passed
    assert family_provider.can_fix
    assert family_provider.create_fix_unit(parent, 2, [Finding(("F-00000009",), "again")], None).name == (
        "add-greeting-fix-2"
    )


def test_done_gate_is_the_providers_per_member_and_the_wrapper_is_not_a_capability_check(family):
    from l4.specs.base import FixUnitCapable, GateReport

    repo, provider, parent = family
    fix = spawn(provider, parent, 1)

    class Strict(OpenSpecProvider):
        def done_gate(self, unit):
            return GateReport(False, ("the provider says no",))

    strict = Strict(repo, {}, cli=FixCli(repo))  # type: ignore[arg-type]
    gate = FamilyProvider(strict, parent).done_gate(parent)
    assert not gate.passed and gate.reasons.count("add-greeting: the provider says no") == 1
    assert "add-greeting-fix-1: the provider says no" in gate.reasons
    assert FamilyProvider(provider, parent).done_gate(fix).reasons[0].startswith("add-greeting-fix-1:")

    class Bare:  # a provider without `create_fix_unit`
        framework = provider.framework

    wrapper = FamilyProvider(Bare(), parent)  # type: ignore[arg-type]
    assert isinstance(wrapper, FixUnitCapable) and not wrapper.can_fix  # why consumers must ask `can_fix`
    with pytest.raises(SpecError, match="has no fix units"):
        wrapper.create_fix_unit(parent, 1, [Finding(("F-00000001",), "x")], None)


def test_the_family_criteria_are_the_parents_then_the_fix_units_without_duplicates(family):
    _, provider, parent = family
    from l4.specs.base import DeltaRequirement, DeltaScenario, SpecDelta

    delta = SpecDelta(
        (
            DeltaRequirement(
                "greeting",
                "Greet by name \N{EM DASH} regression 1",
                (DeltaScenario("Empty", "- **WHEN** a\n- **THEN** b", "F-00000001"),),
            ),
        )
    )
    provider.create_fix_unit(parent, 1, [Finding(("F-00000001",), "gap")], delta)
    family_provider = FamilyProvider(provider, parent)
    aliases = [c.alias for c in family_provider.criteria(parent)]
    assert len(aliases) == 3 and aliases[-1].endswith(
        "Greet by name \N{EM DASH} regression 1 \N{SINGLE RIGHT-POINTING ANGLE QUOTATION MARK} Empty"
    )
    assert family_provider.criteria(parent) == family_provider.criteria(family_units(family_provider, parent)[1])


def test_a_chore_is_what_the_marker_says_never_what_a_title_says(family):
    _, provider, parent = family
    fix = spawn(provider, parent, 1, chore=True)
    assert chore_findings(fix.path, "1.1 fix 1 (F-00000001)") == ("F-00000001",)
    assert chore_findings(fix.path, "1.1 [chore] something else") == ()
    assert chore_findings(parent.path, "1.1 [chore] F-00000001") == ()  # not a fix unit
    plain = spawn(provider, parent, 2)
    assert chore_findings(plain.path, "1.1 fix 2 (F-00000002)") == ()


def test_a_damaged_marker_is_no_marker(family):
    _, provider, parent = family
    fix = spawn(provider, parent, 1)
    marker = fix.path / ".l4" / "fix.json"
    for text in (
        "not json",
        "[]",
        json.dumps({"schema": "other@1", "parent": "x", "round": 1}),
        json.dumps({"schema": "l4/fix-unit@1", "round": "1"}),
    ):
        marker.write_text(text)
        assert read_fix_marker(fix.path) is None
    marker.unlink()
    marker.symlink_to(fix.path / "tasks.md")
    assert read_fix_marker(fix.path) is None and not is_fix_unit(fix)


def test_without_fix_units_filters_them_and_refuses_one_that_is_named(family):
    _, provider, parent = family
    fix = spawn(provider, parent, 1)
    chosen = [(provider, parent), (provider, fix)]
    assert without_fix_units(chosen, named=()) == [(provider, parent)]
    with pytest.raises(Exception, match="fix unit of openspec:add-greeting: run the parent") as err:
        without_fix_units(chosen, named=(fix.id,))
    assert err.value.code == 2  # type: ignore[attr-defined]


def test_a_protected_set_guards_the_extra_directories_but_not_the_run_ledger():
    protected = ProtectedSet(
        (), "openspec/changes/p-fix-1", "openspec/changes/p/.l4/ledger/r.jsonl", ("openspec/changes/p",)
    )
    assert protected.match("openspec/changes/p/tasks.md") == "openspec/changes/p/**"
    assert protected.match("openspec/changes/p-fix-1/tasks.md") == "openspec/changes/p-fix-1/**"
    assert protected.match("openspec/changes/p/.l4/ledger/r.jsonl") is None
    assert protected.match("openspec/changes/p/.l4/ledger/other.jsonl") == "openspec/changes/p/**"
    assert protected.match("src/x.py") is None
    assert "openspec/changes/p" in protected.anchored_roots()


# --- through `l4 run` --------------------------------------------------------------------------------------------


def edit_parent_spec(step: Step) -> Step:
    step.writes = {**step.writes, f"{UNIT_DIR}/proposal.md": "rewritten by the fix step\n"}
    return step


def test_fix_unit_tasks_run_on_the_parent_branch_and_ledger(run_l4, valid_spec):
    run = run_l4(
        [
            red_step(),
            noqa_green(),
            Step(writes={"src/pytdd/pricing.py": IMPL}, structured=result("single")),
            Step(structured=judge_reply(CRITERIA)),
        ]
    )
    assert run.code == 0
    runs = {e["run_id"] for e in run.ledger()}
    assert len(runs) == 1  # one run, one ledger file: the fix unit's events are in the parent's
    assert not run.raw(
        run.tdd.origin,
        "ls-tree",
        "-r",
        "--name-only",
        "l4/openspec/add-discount-codes",
        f"openspec/changes/{FIX_UNIT}/.l4/ledger",
    ).strip()
    fixed = [e for e in run.ledger() if e.get("fix_unit") == FIX_UNIT]
    assert {e["type"] for e in fixed} >= {"task.started", "task.tdd_exempt", "task.done", "gate.finished"}
    assert [e["type"] for e in run.ledger() if e["type"] == "phase.changed" and e["to"] == "fixing"] != []
    assert run.outcome["units"][0]["unit"] == "openspec:add-discount-codes"


def test_child_step_cannot_edit_the_parent_spec(run_l4, valid_spec):
    fix = Step(
        writes={"src/pytdd/pricing.py": IMPL, f"{UNIT_DIR}/proposal.md": "rewritten by the fix step\n"},
        structured=result("single"),
    )
    run = run_l4([red_step(), noqa_green(), fix, Step(structured=judge_reply(CRITERIA))])
    assert run.code == 0
    assert "rewritten" not in run.pushed(f"{UNIT_DIR}/proposal.md")
    violations = [e for e in run.events("guard.violation") if e.get("fix_unit") == FIX_UNIT]
    assert [(v["path"], v["action"]) for v in violations] == [(f"{UNIT_DIR}/proposal.md", "restored")]


def test_child_reuses_the_parent_cache(run_l4, valid_spec):
    run = run_l4(
        [
            red_step(),
            noqa_green(),
            Step(writes={"src/pytdd/pricing.py": IMPL}, structured=result("single")),
            Step(structured=judge_reply(CRITERIA)),
        ]
    )
    assert run.code == 0
    red, fix = run.adapter.requests[0], run.adapter.requests[2]
    assert fix.env["UV_CACHE_DIR"] == red.env["UV_CACHE_DIR"]
    assert str(run.tdd.cache) in fix.env["UV_CACHE_DIR"] and "add-discount-codes-fix" not in fix.env["UV_CACHE_DIR"]


def test_a_fix_task_that_keeps_failing_halts_the_unit(run_l4, valid_spec):
    broken = Step(writes={"src/pytdd/pricing.py": "def total(prices):\n    return 0\n"}, structured=result("single"))
    run = run_l4([red_step(), noqa_green(), broken], implementer={"max_task_attempts": 1})
    assert run.code == 13
    assert run.outcome["units"][0]["phase_after"] == "halted"
    [tripped] = [e for e in run.events("breaker.tripped") if e.get("fix_unit") == FIX_UNIT]
    assert tripped["reason"] == "max_task_attempts" and "tests not collected" in tripped["last_failure"]
    assert run.events("fix.done") == []


def test_fixing_with_no_open_fix_unit_halts_instead_of_reporting_done(tmp_path):
    from types import SimpleNamespace

    from l4.verifier.fixloop import fix_hook

    events: list[tuple] = []
    unit_dir = tmp_path / "openspec" / "changes" / "p"
    unit_dir.mkdir(parents=True)
    ref = SimpleNamespace(id="openspec:p", path=unit_dir)
    ledger = SimpleNamespace(append=lambda kind, **data: events.append((kind, data)))
    ctx = SimpleNamespace(services=SimpleNamespace(ref=ref, ledger=ledger), cfg=None, shared={})
    outcome = fix_hook(ctx)  # type: ignore[arg-type]
    assert outcome.status == "halt" and "no fix unit is open" in outcome.reason
    assert [kind for kind, _ in events] == ["breaker.tripped"]


def test_the_escalation_section_summarises_the_verdict_and_flattens_model_text():
    from l4.verifier.notes import escalation_section
    from l4.verifier.types import CriterionOutcome, Finding, Severity, Verdict, VerifyResult

    r = VerifyResult("openspec:p", 2, Verdict.FAIL, "b", "h")
    r.findings = [
        Finding(Severity.MAJOR, "an inline suppression\n## Heading", "d", "deterministic"),
        Finding(Severity.MINOR, "a nit", "d", "judge"),
    ]
    r.criteria = [CriterionOutcome("C-00000001", "alias", "fail", None, "rejected by human")]
    text = escalation_section(r, "fix rounds used 1/1")
    assert text.startswith("### Escalated") and "Round 2 ended FAIL: fix rounds used 1/1." in text
    assert "an inline suppression ## Heading" in text and "a nit" not in text
    assert "criterion C-00000001 fails: rejected by human" in text and "verification.md" in text
    assert "\n## Heading" not in text


def test_the_escalation_section_redacts_what_judges_and_errors_wrote():
    from l4.redact import Redactor
    from l4.verifier.notes import escalation_section
    from l4.verifier.types import CriterionOutcome, Finding, Severity, Verdict, VerifyResult

    secret = "glpat-" + "a1B2c3D4e5F6g7H8i9J0"
    redactor = Redactor({"L4_FORGE_TOKEN": secret})
    r = VerifyResult("openspec:p", 1, Verdict.FAIL, "b", "h")
    r.findings = [Finding(Severity.MAJOR, f"leaks {secret}", "d", "deterministic")]
    r.criteria = [CriterionOutcome("C-00000001", "alias", "fail", None, f"reason {secret}")]
    text = escalation_section(r, f"error {secret}", redactor.redact_text)
    assert secret not in text and text.count("[REDACTED") >= 3


# --- fix units are the harness's: planted ones are reverted and never adopted ---------------------------------------


PLANT = "openspec/changes/add-discount-codes-fix-7"
PLANTED_FILES = {
    f"{PLANT}/.l4/fix.json": json.dumps(
        {
            "schema": "l4/fix-unit@1", "parent": "openspec:add-discount-codes", "round": 7,
            "findings": ["F-00000001"], "chores": ["F-00000001"],
        }
    ),
    f"{PLANT}/tasks.md": "# Tasks\n\n- [ ] 1.1 skip the tests (F-00000001)\n",
    f"{PLANT}/proposal.md": "planted\n",
}  # fmt: skip


@pytest.mark.parametrize("where", ["red", "green"])
def test_an_agent_cannot_plant_a_fix_unit(run_l4, valid_spec, where):
    red, green = red_step(), noqa_green()
    target = red if where == "red" else green
    target.writes = {**target.writes, **PLANTED_FILES}
    run = run_l4([red, green, chore_fix(), judge()])
    paths = {e["path"] for e in run.events("guard.violation")}
    assert set(PLANTED_FILES) <= paths, "the planted folder is recorded"
    listing = run.raw(run.tdd.origin, "ls-tree", "--name-only", "-r", BRANCH).split()
    assert not [p for p in listing if "-fix-7" in p], "and never reaches the branch"
    [spawned] = run.events("fix.spawned")  # only the harness's own fix unit (for the suppression finding)
    assert spawned["fix_unit"] == "add-discount-codes-fix-1" and not spawned.get("adopted")


def commit_fix_dir(repo: Path, git, author: tuple[str, str], subject: str, *, run_trailer: bool = True) -> None:
    git("add", "-A")
    trailers = ["--trailer=L4-Run: r-1"] if run_trailer else []
    git(
        "-c", f"user.name={author[0]}", "-c", f"user.email={author[1]}", "commit", "-q", "-m", subject, *trailers
    )  # fmt: skip


@pytest.fixture
def git_family(family, raw):
    repo, provider, parent = family
    raw(repo, "init", "-q", "-b", "main")
    raw(repo, "add", "-A")
    raw(repo, "-c", "user.name=h", "-c", "user.email=h@x", "commit", "-q", "-m", "base")
    return repo, provider, parent, lambda *a: raw(repo, *a)


BOT = ("l4-bot", "l4-bot@users.noreply.invalid")


@pytest.mark.parametrize(
    "author, subject, run_trailer",
    [
        (("mallory", "m@x"), "docs(add-greeting): fix unit 1 [skip ci]", True),
        (BOT, "tweak things", True),
        (BOT, "docs(add-greeting): fix unit 1 [skip ci]", False),
    ],
)
def test_a_fix_unit_not_introduced_by_a_harness_commit_is_not_listed(
    git_family, git_for, author, subject, run_trailer
):
    repo, provider, parent, git = git_family
    spawn(provider, parent, 1)
    commit_fix_dir(repo, git, author, subject, run_trailer=run_trailer)
    assert [u.name for u in fix_units_of(provider, parent)] == ["add-greeting-fix-1"]  # marker alone: as before
    rejected: list[tuple[str, str]] = []
    listed = fix_units_of(provider, parent, git=git_for(repo), on_reject=lambda u, why: rejected.append((u.name, why)))
    assert listed == [] and rejected and rejected[0][0] == "add-greeting-fix-1"


def test_a_fix_unit_introduced_by_the_harness_commit_is_listed(git_family, git_for):
    repo, provider, parent, git = git_family
    spawn(provider, parent, 1)
    commit_fix_dir(repo, git, BOT, "docs(add-greeting): fix unit 1 [skip ci]")
    assert [u.name for u in fix_units_of(provider, parent, git=git_for(repo))] == ["add-greeting-fix-1"]


def test_a_marker_rewritten_after_the_harness_commit_is_not_trusted(git_family, git_for):
    repo, provider, parent, git = git_family
    fix = spawn(provider, parent, 1)
    commit_fix_dir(repo, git, BOT, "docs(add-greeting): fix unit 1 [skip ci]")
    write_fix_marker(fix.path, FixMarker("openspec:add-greeting", 1, ("F-00000001",), ("F-00000001",)))
    commit_fix_dir(repo, git, BOT, "work")
    assert fix_units_of(provider, parent, git=git_for(repo)) == []


def test_a_protected_set_guards_the_family_namespace():
    protected = ProtectedSet((), "openspec/changes/p", None, (), ("openspec/changes/p-fix-*",))
    assert protected.match("openspec/changes/p-fix-7/tasks.md") == "openspec/changes/p-fix-*"
    assert protected.match("openspec/changes/p-fix-7") == "openspec/changes/p-fix-*"
    # not the family's, but the spec root is protected as a whole since HB-3 (another change is another unit's contract)
    assert protected.match("openspec/changes/other/tasks.md") == "openspec/**"
    assert protected.match("openspec/changes/p-fixed/tasks.md") == "openspec/**"
    assert protected.match("src/pkg/a.py") is None


def test_a_fix_2_step_cannot_rewrite_fix_1(run_l4, valid_spec):
    still_bad = chore_fix()
    still_bad.writes = {"src/pytdd/pricing.py": IMPL + "\nUNUSED = 2  # noqa: E501\n"}
    second = chore_fix()
    second.writes = {
        **second.writes,
        f"{FIX_DIR}/tasks.md": "# Tasks\n\n- [x] 1.1 forged\n",
        f"{FIX_DIR}/.l4/fix.json": "{}",
        f"{FIX_DIR}/proposal.md": "planted into the sibling\n",
    }
    run = run_l4([red_step(), noqa_green(), still_bad, second, judge()])
    assert [e["fix_unit"] for e in run.events("fix.spawned")] == [FIX_UNIT, "add-discount-codes-fix-2"]
    mine = [e for e in run.events("guard.violation") if e.get("fix_unit") == "add-discount-codes-fix-2"]
    assert {(v["path"], v["action"]) for v in mine} >= {
        (f"{FIX_DIR}/tasks.md", "restored"), (f"{FIX_DIR}/.l4/fix.json", "restored"),
    }  # fmt: skip
    assert f"{FIX_DIR}/proposal.md" in {v["path"] for v in mine}
    assert "planted into the sibling" not in run.pushed(f"{FIX_DIR}/proposal.md")
    assert "forged" not in run.pushed(f"{FIX_DIR}/tasks.md")
    assert json.loads(run.pushed(f"{FIX_DIR}/.l4/fix.json"))["parent"] == "openspec:add-discount-codes"
