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


def test_an_item_a_merged_follow_up_took_is_not_taken_again(project, capsys, raw):
    """After the follow-up merged, its marker is on the base: the same item (same hash) is not offered again, and a
    new item gets the next ordinal."""
    from l4.specs.feedback import content_sha256

    repo, _ = project
    sha = content_sha256(FeedbackFile.parse(ITEM).get("FB-001"))
    follow = repo / ".kiro" / "specs" / f"{UNIT}-followup-1"
    (follow / ".l4").mkdir(parents=True)
    (follow / "tasks.md").write_text("- [x] 1. Done\n")
    marker = {"schema": "l4/followup@1", "parent": f"kiro:{UNIT}", "items": [{"id": "FB-001", "sha256": sha}]}
    (follow / ".l4" / "followup.json").write_text(json.dumps(marker))
    raw(repo, "add", "-A")
    raw(repo, "commit", "-q", "-m", "the follow-up merged")
    raw(repo, "push", "-q", "origin", "main")
    assert plan(project, capsys)[f"kiro:{UNIT}"]["next_action"] != "follow_up"
    assert main(["status", "--json", "--repo", str(repo)], environ=project[1]) == 0
    status = {u["unit"]: u for u in json.loads(capsys.readouterr().out)["units"]}
    assert status[f"kiro:{UNIT}"]["feedback_counts"] == {"taken": 1}  # the parent reads the take from the marker
    second = ITEM.replace("FB-001", "FB-002").replace("dedupe the rounding", "dedupe it again").split("\n", 2)[2]
    (repo / SPEC / "feedback.md").write_text(ITEM + "\n" + second)
    raw(repo, "add", "-A")
    raw(repo, "commit", "-q", "-m", "a second item")
    raw(repo, "push", "-q", "origin", "main")
    entry = plan(project, capsys)[f"kiro:{UNIT}"]
    assert entry["next_action"] == "follow_up" and "FB-002" in entry["reason"] and "FB-001" not in entry["reason"]
    from l4.config.schema import L4Config  # noqa: F401
    from l4.state.followups import known_follow_ups, next_ordinal
    from l4.vcs.git import Git

    cfg = L4Config.model_validate({"version": 1})
    found = known_follow_ups(Git(repo, environ=project[1]), cfg)
    assert [(k.name, k.on_base) for k in found] == [(f"{UNIT}-followup-1", True)] and next_ordinal(found) == 2


def test_a_forged_marker_is_not_a_follow_up(project, capsys, raw):
    """The folder name and the parent in the marker must agree."""
    repo, _ = project
    follow = repo / ".kiro" / "specs" / f"{UNIT}-followup-1"
    (follow / ".l4").mkdir(parents=True)
    (follow / "tasks.md").write_text("- [x] 1. Done\n")
    marker = {"schema": "l4/followup@1", "parent": "kiro:someone-else", "items": [{"id": "FB-001", "sha256": "0" * 64}]}
    (follow / ".l4" / "followup.json").write_text(json.dumps(marker))
    raw(repo, "add", "-A")
    raw(repo, "commit", "-q", "-m", "forged")
    raw(repo, "push", "-q", "origin", "main")
    assert plan(project, capsys)[f"kiro:{UNIT}"]["next_action"] == "follow_up"


def test_an_archived_openspec_change_with_feedback_plans_a_follow_up(make_repo, git_environ, raw, tmp_path, capsys):
    from l4.redact import Redactor
    from l4.state.ledger import LedgerWriter

    repo = make_repo(remote=True)
    archive = repo / "openspec" / "changes" / "archive" / "2026-10-01-add-x"
    archive.mkdir(parents=True)
    (archive / "tasks.md").write_text("# Tasks\n\n- [x] 1.1 done\n")
    (archive / "feedback.md").write_text(ITEM)
    writer = LedgerWriter.open(archive, "openspec:add-x", "r-20261003T1312Z-7f3a", redactor=Redactor({}))
    writer.append("phase.changed", **{"from": "in_review", "to": "merged", "trigger": "pr_merged"})
    writer.finish(0)
    older = repo / "openspec" / "changes" / "archive" / "2026-09-01-add-y"  # archived, no feedback: not a unit
    older.mkdir(parents=True)
    (older / "tasks.md").write_text("# Tasks\n\n- [x] 1.1 done\n")
    (repo / "openspec" / "changes" / "live").mkdir(parents=True)
    (repo / "openspec" / "changes" / "live" / "tasks.md").write_text("# Tasks\n\n- [ ] 1.1 todo\n")
    (repo / ".l4").mkdir()
    (repo / ".l4" / "config.yaml").write_text("version: 1\n")
    raw(repo, "add", "-A")
    raw(repo, "commit", "-q", "-m", "archived")
    raw(repo, "push", "-q", "origin", "main")
    project = (repo, {**git_environ, "L4_CACHE": str(tmp_path / "cache")})
    units = plan(project, capsys)
    assert units["openspec:add-x"]["phase"] == "merged" and units["openspec:add-x"]["next_action"] == "follow_up"
    assert "openspec:add-y" not in units and units["openspec:live"]["next_action"] == "implement"


def test_an_abandoned_follow_up_releases_its_items(project, capsys, raw):
    """A follow-up on a branch whose unit was abandoned keeps its number but no longer holds what it took."""
    from l4.redact import Redactor
    from l4.specs.feedback import content_sha256
    from l4.state.ledger import LedgerWriter

    repo, _ = project
    sha = content_sha256(FeedbackFile.parse(ITEM).get("FB-001"))
    name = f"{UNIT}-followup-1"
    raw(repo, "checkout", "-q", "-b", f"l4/kiro/{name}")
    follow = repo / ".kiro" / "specs" / name
    (follow / ".l4").mkdir(parents=True)
    (follow / "tasks.md").write_text("- [ ] 1. Todo\n")
    marker = {"schema": "l4/followup@1", "parent": f"kiro:{UNIT}", "items": [{"id": "FB-001", "sha256": sha}]}
    (follow / ".l4" / "followup.json").write_text(json.dumps(marker))
    writer = LedgerWriter.open(follow, f"kiro:{name}", "r-20261004T0900Z-bbbb", redactor=Redactor({}))
    writer.append("phase.changed", **{"from": "implementing", "to": "abandoned", "trigger": "test"})
    writer.finish(0)
    raw(repo, "add", "-A")
    raw(repo, "commit", "-q", "-m", "an abandoned follow-up")
    raw(repo, "push", "-q", "origin", f"l4/kiro/{name}")
    raw(repo, "checkout", "-q", "main")
    units = plan(project, capsys)
    assert units[f"kiro:{UNIT}"]["next_action"] == "follow_up"  # the item is offered again, as follow-up 2
    assert units[f"kiro:{name}"]["phase"] == "abandoned"
