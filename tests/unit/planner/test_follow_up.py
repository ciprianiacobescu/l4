"""human-feedback 5.2: the planner action `follow_up` for a merged unit whose `feedback.md` has takeable items and no
open follow-up (L4-FBK-010; SCN-FBK-23, SCN-FBK-24)."""

import json
from pathlib import Path

import pytest

from l4.cli import main
from l4.orchestrator import ACTIONABLE
from l4.planner import UnitFacts, facts_of, next_action
from l4.specs.base import Framework, UnitRef
from l4.specs.feedback import FeedbackFile
from l4.state.fold import UnitState
from l4.state.followups import FollowUpOffer
from l4.state.status import UnitSnapshot

UNIT = "add-reorder-quantity"
SPEC = f".kiro/specs/{UNIT}"
ITEM = """# Feedback

## FB-001: dedupe the rounding

- **Status:** submitted
- **Kind:** duplication
- **Where:** `src/inventory/reorder.py:4-9`
- **By:** Ada, 2026-10-12T10:00:00Z

### Feedback
The rounding is written twice.
"""


def facts(**over) -> UnitFacts:
    base = {"unit": f"kiro:{UNIT}", "framework": "kiro", "phase": "merged", "tasks_done": 3, "tasks_total": 3}
    return UnitFacts(**{**base, **over})


def test_a_merged_unit_with_takeable_items_plans_follow_up():
    action, reason = next_action(facts(follow_up_items=("FB-001", "FB-002")))
    assert action == "follow_up" and "FB-001, FB-002" in reason and "follow-up" in reason
    assert "follow_up" not in ACTIONABLE  # `l4 run` performs it before it selects units; the dry run never runs it


def test_a_merged_unit_with_an_open_follow_up_plans_nothing():
    """SCN-FBK-24: one follow-up at a time."""
    action, reason = next_action(facts(follow_up_items=("FB-002",), follow_up_open=f"{UNIT}-followup-1"))
    assert action == "none" and f"{UNIT}-followup-1" in reason and "FB-002" in reason


def test_a_merged_unit_without_items_stays_merged():
    assert next_action(facts()) == ("none", "merged")


@pytest.mark.parametrize("phase", ["in_review", "abandoned", "verified"])
def test_other_phases_never_plan_a_follow_up(phase: str):
    assert next_action(facts(phase=phase, follow_up_items=("FB-001",)))[0] != "follow_up"


def test_facts_read_the_offer_of_the_snapshot(tmp_path: Path):
    file = FeedbackFile.parse(ITEM)
    offer = FollowUpOffer(items=tuple(file.items), open=None, n=1)
    ref = UnitRef(Framework.KIRO, UNIT, tmp_path / UNIT)
    snap = UnitSnapshot(ref, UnitState(unit=ref.id, phase="merged"), [], "worktree", follow_up=offer)
    found = facts_of(snap)
    assert found.follow_up_items == ("FB-001",) and found.follow_up_open is None
    assert next_action(found)[0] == "follow_up"
    waiting = FollowUpOffer(offer.items, f"{UNIT}-followup-1", 2)
    opened = UnitSnapshot(ref, snap.state, [], "worktree", follow_up=waiting)
    assert facts_of(opened).follow_up_open == f"{UNIT}-followup-1"


# --- a real repository: the merged Kiro unit of SCN-FBK-23 -----------------------------------------------------


@pytest.fixture
def project(make_repo, git_environ, raw, tmp_path: Path):
    """`origin/main` holds the merged Kiro unit with a submitted duplication item; its lock ref holds `merged`."""
    from l4.redact import Redactor
    from l4.state.ledger import LedgerWriter
    from l4.state.pending import PendingLedger
    from l4.vcs.git import Git

    repo = make_repo(remote=True)
    spec = repo / SPEC
    spec.mkdir(parents=True)
    (spec / "requirements.md").write_text("# Requirements\n")
    (spec / "tasks.md").write_text("# Plan\n\n- [x] 1. Reorder\n  - [x] 1.1 Add it\n")
    (repo / ".l4").mkdir()
    (repo / ".l4" / "config.yaml").write_text("version: 1\n")
    LedgerWriter.open(spec, f"kiro:{UNIT}", "r-20261003T1312Z-7f3a", redactor=Redactor({})).finish(0)
    (spec / "feedback.md").write_text(ITEM)
    raw(repo, "add", "-A")
    raw(repo, "commit", "-q", "-m", "merged unit")
    raw(repo, "push", "-q", "origin", "main")
    scratch = tmp_path / "scratch" / UNIT
    writer = LedgerWriter.open(scratch, f"kiro:{UNIT}", "r-20261003T1320Z-aaaa", redactor=Redactor({}))
    writer.append("phase.changed", **{"from": "in_review", "to": "merged", "trigger": "pr_merged"})
    writer.finish(0)
    git = Git(repo, environ=git_environ)
    ref = f"refs/l4/locks/kiro/{UNIT}"
    pending = PendingLedger(git, lock_ref=ref, unit=f"kiro:{UNIT}", run_id="r-20261003T1320Z-aaaa")
    built = pending.build(next((scratch / ".l4" / "ledger").glob("*.jsonl")))
    pending.push(built)
    environ = {**git_environ, "L4_CACHE": str(tmp_path / "cache")}
    return repo, environ


def plan(project, capsys) -> dict:
    repo, environ = project
    assert main(["plan", "--json", "--repo", str(repo)], environ=environ) == 0
    return {u["unit"]: u for u in json.loads(capsys.readouterr().out)["units"]}


def test_plan_shows_follow_up_for_the_merged_kiro_unit(project, capsys):
    """SCN-FBK-23: the next base run plans the follow-up."""
    entry = plan(project, capsys)[f"kiro:{UNIT}"]
    assert entry["phase"] == "merged" and entry["next_action"] == "follow_up" and entry["actionable"] is True
    assert "FB-001" in entry["reason"]


def test_plan_reads_the_file_from_the_base_branch(project, capsys, raw):
    """The item the person committed to the base counts, not the copy on the unit's old branch or an unpushed edit."""
    repo, _ = project
    path = repo / SPEC / "feedback.md"
    path.write_text(path.read_text().replace("submitted", "withdrawn"))  # an unpushed edit: not the base's file
    assert plan(project, capsys)[f"kiro:{UNIT}"]["next_action"] == "follow_up"
