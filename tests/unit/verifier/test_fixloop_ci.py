"""A CI failure that no fix touched escalates instead of getting another fix unit (ci-evidence D12; L4-OPS-023,
SCN-OPS-40 to SCN-OPS-44): `decide_fix` on a real repository, a real ledger, and a parent with a fix unit."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from l4.config.schema import L4Config
from l4.redact import Redactor
from l4.specs.base import Finding as SpecFinding
from l4.specs.openspec import OpenSpecProvider
from l4.state.ledger import LedgerWriter, read_ledger
from l4.vcs.git import Git
from l4.verifier.fixloop import CI_NOT_FIXED, FamilyProvider, ci_not_fixed_detail, decide_fix, unfixed_ci_jobs
from l4.verifier.types import Finding, HumanVerdict, Severity, Verdict, VerifyResult

from ..specs.conftest import GREETING_DELTA
from ..specs.fixcli import FixCli

JOB = "ci.yml / tests"
TITLE = f"repository CI failed: {JOB}"
UNIT_ID = "openspec:add-greeting"
UNIT_REL = "openspec/changes/add-greeting"
TAIL = "Run uv run pytest -q\nFAILED tests/test_cli.py::test_help - AssertionError\n1 failed, 2277 passed in 3s"


class World:
    def __init__(self, tmp_path: Path, raw) -> None:
        self.repo = tmp_path / "repo"
        change = self.repo / UNIT_REL
        (change / "specs" / "greeting").mkdir(parents=True)
        (change / "tasks.md").write_text("# Tasks\n\n- [x] 1.1 greet\n")
        (change / "specs" / "greeting" / "spec.md").write_text(GREETING_DELTA)
        (self.repo / "src").mkdir()
        (self.repo / "src" / "greet.py").write_text("v1\n")
        self.raw = raw
        raw(self.repo, "init", "-q", "-b", "main")
        raw(self.repo, "add", "-A")
        raw(self.repo, "commit", "-q", "-m", "unit")
        self.git = Git(self.repo)
        self.provider = OpenSpecProvider(self.repo, {}, cli=FixCli(self.repo))  # type: ignore[arg-type]
        self.parent = self.provider.list_units()[0]
        self.writer = LedgerWriter.open(self.parent.path, UNIT_ID, "r-20261020T1000Z-aaaa", redactor=Redactor({}))
        self.n = 0

    def commit(self, files: dict[str, str]) -> str:
        for name, text in files.items():
            (self.repo / name).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / name).write_text(text)
        self.raw(self.repo, "add", "-f", *files)  # the ledger stays untracked: it must survive a checkout
        self.raw(self.repo, "commit", "-q", "-m", "c")
        return self.raw(self.repo, "rev-parse", "HEAD").strip()

    def head(self) -> str:
        return self.raw(self.repo, "rev-parse", "HEAD").strip()

    def edge(self, head: str) -> None:
        job = {"name": JOB, "stage": "", "url": "", "tail": TAIL, "failed_step": "tests", "workflow": "ci.yml"}
        self.writer.append(
            "phase.changed", **{"from": "in_review", "to": "verifying"}, trigger="repository_ci_failed", head=head,
            pipeline=5, jobs=[job], preexisting=[],
        )  # fmt: skip

    def decide(self, rejected: str = "") -> VerifyResult:
        """`rejected`: a person's reject of a human finding, its reason a WHEN ... THEN ...: it converts to a task."""
        blocker = Finding(Severity.BLOCKER, TITLE, "detail", "deterministic")
        result = VerifyResult(UNIT_ID, 2, Verdict.FAIL, "b" * 40, self.head())
        result.findings = [blocker]
        if rejected:
            held = Finding(Severity.MAJOR, "the greeting is wrong", "a person rejected it", "human")
            result.findings.append(held)
            result.human = [HumanVerdict("Q-001", held.id, "reject", "alex", rejected, "x")]
        family = FamilyProvider(self.provider, self.parent)
        services = SimpleNamespace(ref=self.parent, git=self.git, worktree=self.repo, ledger=self.writer)
        ctx = SimpleNamespace(cfg=L4Config(), services=services, shared={})
        wb = SimpleNamespace(provider=family, ref=self.parent, git=self.git, unit_rel=UNIT_REL, worktree=self.repo)
        decide_fix(ctx, wb, result)  # type: ignore[arg-type]
        return result


@pytest.fixture
def world(tmp_path, raw) -> World:
    return World(tmp_path, raw)


def two_hand_offs(world: World, between: dict[str, str]) -> str:
    h1 = world.head()
    world.edge(h1)
    world.writer.append("verify.verdict", round=1, verdict="FAIL", findings=1)
    h2 = world.commit(between)
    world.edge(h2)
    return h1


def test_an_unfixed_ci_job_escalates_with_ci_not_fixed(world):
    """SCN-OPS-40: the fix touched only its own folder; rounds are left; no fix unit, `same_failure` not reached."""
    h1 = two_hand_offs(world, {f"{UNIT_REL}-fix-1/tasks.md": "- [x] 1.1\n"})
    fix = world.decide().fix
    assert fix is not None and fix.action == "escalate" and fix.code == CI_NOT_FIXED == "ci_not_fixed"
    assert fix.plan is None and fix.tasks == []
    assert fix.reason.startswith(f"the repository CI job `{JOB}` failed in step `tests`: FAILED tests/test_cli.py")
    assert fix.reason.endswith(
        f". It failed again on the hand-off commit {world.head()[:10]}, as on {h1[:10]}, "
        "and no commit between changed a project file: the gates here do not reproduce this CI failure, so handing "
        "off again would fail the same way"
    )
    assert "FAILED tests/test_cli.py::test_help - AssertionError | 1 failed, 2277 passed in 3s" in fix.reason


def test_a_hand_off_as_it_was_that_fails_again_escalates(world):
    """SCN-OPS-41: a retry between the two edges changes nothing."""
    h1 = world.head()
    world.edge(h1)
    world.writer.append("verify.verdict", round=1, verdict="FAIL", findings=1)
    world.writer.append("unit.retried", reason="a person retried", by="alex")
    world.edge(h1)  # handed off as it was: the same head
    fix = world.decide().fix
    assert fix is not None and fix.code == CI_NOT_FIXED
    assert f"on the hand-off commit {h1[:10]}, as on {h1[:10]}" in fix.reason


def test_a_project_change_makes_a_fix_unit(world):
    """SCN-OPS-42: a project file changed between the two hand-offs: a fix unit, as today."""
    two_hand_offs(world, {"src/greet.py": "v2\n"})
    fix = world.decide().fix
    assert fix is not None and fix.action == "spawn" and fix.code == ""


def test_a_persons_commit_to_a_test_file_makes_a_fix_unit(world):
    two_hand_offs(world, {"tests/test_greet.py": "def test_x(): ...\n"})
    fix = world.decide().fix
    assert fix is not None and fix.action == "spawn"


def test_a_base_merge_is_not_a_fix(world):
    """SCN-OPS-44: only a merge of the base lies between the hand-offs."""
    h1 = world.head()
    world.edge(h1)
    world.writer.append("verify.verdict", round=1, verdict="FAIL", findings=1)
    world.raw(world.repo, "checkout", "-q", "-b", "side")
    world.commit({"src/other.py": "base\n"})
    world.raw(world.repo, "checkout", "-q", "main")
    world.raw(world.repo, "merge", "-q", "--no-ff", "-m", "merge the base", "side")
    world.edge(world.head())
    fix = world.decide().fix
    assert fix is not None and fix.code == CI_NOT_FIXED


def test_a_first_failure_is_not_escalated(world):
    world.edge(world.head())
    fix = world.decide().fix
    assert fix is not None and fix.action == "spawn"


def test_a_round_without_the_jobs_blocker_is_not_escalated_for_it(world):
    """The job is unfixed, but this round failed on something else: the escalation is for the round with the blocker."""
    two_hand_offs(world, {f"{UNIT_REL}/notes.md": "x\n"})
    events = read_ledger(world.parent.path).events
    other = [Finding(Severity.BLOCKER, "something else", "x", "deterministic")]
    assert unfixed_ci_jobs(events, world.git, UNIT_REL, L4Config(), other) == []
    mine = [Finding(Severity.BLOCKER, TITLE, "x", "deterministic")]
    assert [h.job for h in unfixed_ci_jobs(events, world.git, UNIT_REL, L4Config(), mine)] == [JOB]


def test_an_unfinished_fix_unit_is_taken_up_first(world):
    """The fix unit that is open and has a task left is run, not replaced by an escalation."""
    two_hand_offs(world, {f"{UNIT_REL}/notes.md": "x\n"})
    fix_unit = world.provider.create_fix_unit(world.parent, 1, [SpecFinding(("F-00000001",), "fix it")], None)
    world.writer.append("fix.spawned", parent=UNIT_ID, fix_unit=fix_unit.name, round=1, verify_round=1, findings=[])
    decision = world.decide().fix
    assert decision is not None and decision.action == "spawn" and decision.code == ""


def test_a_persons_reject_that_converts_into_a_task_makes_a_fix_unit(world):
    """Review MINOR-4 (D12): the escalation is for a round no person has said anything about; a person's reject that
    becomes a task is new input, so the fix unit is made (and answers it) although the CI job is still unfixed."""
    two_hand_offs(world, {f"{UNIT_REL}-fix-1/tasks.md": "- [x] 1.1\n"})
    fix = world.decide(rejected="WHEN a name is empty THEN greet the world").fix
    assert fix is not None and fix.action == "spawn" and fix.code == "" and fix.plan is not None
    assert fix.plan.consumed == ["Q-001"]


def test_no_person_input_still_escalates_the_unfixed_job(world):
    two_hand_offs(world, {f"{UNIT_REL}-fix-1/tasks.md": "- [x] 1.1\n"})
    fix = world.decide().fix
    assert fix is not None and fix.code == CI_NOT_FIXED


def test_a_resumed_round_decides_the_same(world):
    """The decision comes from the ledger and git alone: a second call gives the same answer."""
    two_hand_offs(world, {f"{UNIT_REL}-fix-1/tasks.md": "- [x] 1.1\n"})
    first, second = world.decide().fix, world.decide().fix
    assert first is not None and second is not None and (first.code, first.reason) == (second.code, second.reason)


def test_the_detail_names_every_job_and_leaves_out_what_is_not_recorded():
    from l4.ci.unfixed import CiHistory

    base = dict(head="a" * 40, again_head="b" * 40, again_changed=0, unfixed=True, put_back=(), notes=None)
    one = CiHistory(job="j1", failed_step=None, failing="", **base)  # type: ignore[arg-type]
    two = CiHistory(job="j2", failed_step="tests", failing="FAILED t::x", **base)  # type: ignore[arg-type]
    assert ci_not_fixed_detail([one]).endswith("so handing off again would fail the same way")
    text = ci_not_fixed_detail([two, one])
    assert text.startswith("the repository CI job `j2` failed in step `tests`: FAILED t::x. It failed again")
    assert text.endswith("(also: j1)")
