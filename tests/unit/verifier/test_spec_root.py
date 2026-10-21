"""HB-3 (docs/research/08): an agent that copies its delta into the archived specs is reverted, and the verifier's
pass-to-pass baseline comes from the base commit."""

import json

from l4.agents.fake import Step

from ..conftest import FIXTURE
from ..implementer.conftest import IMPL, green_step, red_step, result
from .conftest import judge_reply
from .test_ladder import CRITERIA

DELTA = (FIXTURE / "openspec/changes/add-discount-codes/specs/pricing/spec.md").read_text()
MAIN_SPEC = "openspec/specs/pricing/spec.md"
SIBLING = "openspec/changes/add-vat/proposal.md"


def test_a_delta_copied_into_the_main_specs_is_reverted_and_never_reaches_the_branch(run_l4, valid_spec):
    planted = Step(
        writes={
            "src/pytdd/pricing.py": IMPL,
            MAIN_SPEC: DELTA.replace("## ADDED Requirements", "## Requirements"),
            SIBLING: "# a sibling change the agent invented\n",
        },
        structured=result("green"),
    )
    run = run_l4([red_step(), planted, Step(structured=judge_reply(CRITERIA))])
    assert run.code == 0
    violations = {(e["path"], e["action"]) for e in run.events("guard.violation")}
    assert {(MAIN_SPEC, "removed"), (SIBLING, "removed")} <= violations
    files = run.raw(run.tdd.origin, "ls-tree", "--name-only", "-r", "l4/openspec/add-discount-codes").split()
    assert MAIN_SPEC not in files and SIBLING not in files


def test_the_verifier_reads_its_baseline_from_the_base_commit(run_l4, valid_spec, monkeypatch):
    from l4.specs import criteria as criteria_module
    from l4.verifier import ladder

    seen: list[str] = []
    real = criteria_module.base_criteria_at

    def spy(git, rev):
        seen.append(rev)
        return real(git, rev)

    monkeypatch.setattr(ladder, "base_criteria_at", spy)
    run = run_l4([red_step(), green_step(), Step(structured=judge_reply(CRITERIA))])
    assert run.code == 0
    verdict = json.loads(run.pushed("openspec/changes/add-discount-codes/.l4/evidence/round-1/verdict.json"))
    assert seen == [verdict["base_sha"]]  # the merge base, not the head the worktree is at
