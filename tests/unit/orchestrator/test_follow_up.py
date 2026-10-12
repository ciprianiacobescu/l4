# ruff: noqa: F811
"""human-feedback 5.2 end to end (L4-FBK-010; SCN-FBK-23, SCN-FBK-24): `l4 run` with a scripted fake agent, a fake
GitLab and a bare origin. A merged unit whose `feedback.md` on the base holds a submitted item gets a unit of its own on
its own branch; the base is never pushed to; one follow-up is open at a time."""

import json
from pathlib import Path

import pytest

from l4.agents.fake import Step
from l4.cli import main
from l4.redact import Redactor
from l4.specs.criteria import kiro_criteria
from l4.specs.feedback import FeedbackKind, NewFeedback, Place, append_item
from l4.state.ledger import LedgerWriter
from l4.state.pending import PendingLedger
from l4.vcs.git import Git

from ..archive.conftest import forge_env, gitlab, use_fake_gitlab  # noqa: F401  (a fake GitLab for the draft MR)
from ..implementer.conftest import IMPL, result
from .conftest import new_origin_main

PARENT = "add-reorder-quantity"
FOLLOW = f"{PARENT}-followup-1"
BRANCH = f"l4/kiro/{FOLLOW}"
SPEC = f".kiro/specs/{PARENT}"
FOLLOW_DIR = f".kiro/specs/{FOLLOW}"
REQUIREMENTS = """# Requirements Document

## Requirements

### Requirement 1: Reorder

**User Story:** As a buyer, I want a reorder quantity, so that I order enough.

#### Acceptance Criteria

1. WHEN total is called, THE Shop SHALL return the rounded sum.
"""
TASKS = "# Implementation Plan\n\n- [x] 1. Reorder\n  - [x] 1.1 Add `total`\n    - _Requirements: 1.1_\n"
CHORE = Step(
    writes={"src/pytdd/pricing.py": IMPL + "\n# the rounding is its own function\n"}, structured=result("single")
)
RUN_ID = "r-20261003T1320Z-aaaa"


def feedback_text(tmp: Path, *items: dict) -> str:
    """The `feedback.md` a person would commit: the command's own writer, so the grammar is the real one."""
    folder = tmp / f"fb-{len(list(tmp.glob('fb-*')))}"
    folder.mkdir()
    for body in items:
        spec = {
            "kind": FeedbackKind.DUPLICATION, "title": "Dedupe the rounding", "text": "The rounding is written twice.",
            "by": "Ana, 2026-10-12T15:04:00Z", "places": (Place("src/pytdd/pricing.py", 1, 2),),
        }  # fmt: skip
        append_item(folder, PARENT, NewFeedback(**{**spec, **body}), redactor=Redactor({}))
    return (folder / "feedback.md").read_text()


def ledger_files(folder: Path, unit: str, run_id: str, *phases: tuple[str, str]) -> None:
    writer = LedgerWriter.open(folder, unit, run_id, redactor=Redactor({}))
    for before, after in phases:
        writer.append("phase.changed", **{"from": before, "to": after, "trigger": "test"})
    writer.finish(0)


@pytest.fixture
def merged_kiro(tdd_repo, raw, tmp_path, forge_env, use_fake_gitlab):
    """`main` holds only the merged Kiro unit with a submitted duplication item; its lock ref says merged."""
    repo = tdd_repo.repo
    raw(repo, "rm", "-rq", "openspec")
    spec = repo / SPEC
    spec.mkdir(parents=True)
    (spec / "requirements.md").write_text(REQUIREMENTS)
    (spec / "tasks.md").write_text(TASKS)
    (repo / "tests" / "test_total.py").write_text(  # the merged unit's own test, traced to its criterion
        f'import pytest\n\nfrom pytdd.pricing import total\n\n\n@pytest.mark.l4("{kiro_criteria(spec)[0].id}")\n'
        "def test_total():\n    assert total([1.005, 2.0]) == 3.0\n"
    )
    ledger_files(spec, f"kiro:{PARENT}", "r-20261003T1312Z-7f3a", ("none", "in_review"))  # the folder reads in_review
    (spec / "feedback.md").write_text(feedback_text(tmp_path, {}))
    tdd_repo.write_config()
    new_origin_main(tdd_repo, raw, {})
    scratch = tmp_path / "scratch"
    ledger_files(scratch / SPEC, f"kiro:{PARENT}", RUN_ID, ("in_review", "merged"))
    git = Git(repo, environ=tdd_repo.environ)
    pending = PendingLedger(git, lock_ref=f"refs/l4/locks/kiro/{PARENT}", unit=f"kiro:{PARENT}", run_id=RUN_ID)
    pending.push(pending.build(next((scratch / SPEC / ".l4" / "ledger").glob("*.jsonl"))))
    return tdd_repo


def events(tdd, raw, branch: str, folder: str) -> list[dict]:
    listing = raw(tdd.origin, "ls-tree", "--name-only", branch, f"{folder}/.l4/ledger/").split()
    return [json.loads(line) for p in listing for line in raw(tdd.origin, "show", f"{branch}:{p}").splitlines()]


def test_feedback_on_a_merged_kiro_unit_becomes_a_follow_up_unit(merged_kiro, run_l4, raw, use_fake_gitlab):
    """SCN-FBK-23: the follow-up exists on its own branch with one chore task, and its PR opens as draft."""
    tdd = merged_kiro
    main_before = raw(tdd.origin, "rev-parse", "main").strip()
    run = run_l4([CHORE], unit=False)

    assert run.code == 0, run.adapter.requests[-1].prompt[-500:] if run.adapter.requests else run.outcome
    assert raw(tdd.origin, "rev-parse", "main").strip() == main_before  # the base is never pushed to
    tasks = raw(tdd.origin, "show", f"{BRANCH}:{FOLLOW_DIR}/tasks.md")
    leaves = [line for line in tasks.splitlines() if line.strip().startswith("- [")]
    assert len(leaves) == 2 and "[chore]" in leaves[1], tasks  # the group line and one chore task
    marker = json.loads(raw(tdd.origin, "show", f"{BRANCH}:{FOLLOW_DIR}/.l4/followup.json"))
    assert marker["schema"] == "l4/followup@1" and marker["parent"] == f"kiro:{PARENT}"
    assert [i["id"] for i in marker["items"]] == ["FB-001"] and len(marker["items"][0]["sha256"]) == 64
    assert marker["refactors"] == marker["chores"] and len(marker["chores"]) == 1
    assert "Requested by Ana" in raw(tdd.origin, "show", f"{BRANCH}:{FOLLOW_DIR}/bugfix.md")
    # the follow-up's own branch holds the parent's file with the item taken
    fb = raw(tdd.origin, "show", f"{BRANCH}:{SPEC}/feedback.md")
    assert "**Status:** taken" in fb and f"Taken into {FOLLOW}" in fb
    taken = [e for e in events(tdd, raw, BRANCH, FOLLOW_DIR) if e["type"] == "feedback.taken"]
    assert [(e["id"], e["kind"], e["round"], e["fix_unit"]) for e in taken] == [("FB-001", "duplication", 0, FOLLOW)]
    # it ran as an ordinary unit: the chore is done, and its draft MR is open
    assert "- [x] 1.1" in tasks
    assert use_fake_gitlab.mrs[1]["source_branch"] == BRANCH
    assert use_fake_gitlab.mrs[1]["title"].lower().startswith("draft")
    assert raw(tdd.origin, "show", f"main:{SPEC}/feedback.md").count("**Status:** submitted") == 1
    assert f"kiro:{PARENT}" in {u["unit"] for u in run.outcome["units"]}


def second_item_on_main(tdd, raw, tmp_path: Path) -> None:
    """A person's second submitted item on the parent, committed to the base."""
    second = {"title": "Add tests for the rounding", "kind": FeedbackKind.TESTS}
    new_origin_main(tdd, raw, {f"{SPEC}/feedback.md": feedback_text(tmp_path, {}, second)})


def test_one_follow_up_at_a_time_and_the_newer_item_waits(
    merged_kiro, run_l4, raw, use_fake_gitlab, tmp_path, monkeypatch, capsys
):
    """SCN-FBK-24: an open follow-up, a new item on the parent: no second follow-up, the item reads waiting."""
    from l4.ci import sweeper
    from l4.forge.gitlab import GitLabForge

    from ..forge.conftest import API, PROJECT, TOKEN

    tdd = merged_kiro
    assert run_l4([CHORE], unit=False).code == 0  # follow-up 1 is open: it ran to `implemented`

    def fake_forge(cfg, environ, **kw):
        return GitLabForge(API, PROJECT, TOKEN, transport=use_fake_gitlab.transport(), sleep=lambda s: None)

    monkeypatch.setattr(sweeper, "make_forge", fake_forge)
    second_item_on_main(tdd, raw, tmp_path)

    def plan(*words: str) -> dict:
        code = main(["plan", "--json", *words, "--repo", str(tdd.repo)], environ=tdd.environ)
        assert code == 0
        return {u["unit"]: u for u in json.loads(capsys.readouterr().out)["units"]}

    entry = plan()[f"kiro:{PARENT}"]
    assert entry["next_action"] == "none" and "FB-002" in entry["reason"] and FOLLOW in entry["reason"]
    assert "FB-001" not in entry["reason"]  # the open follow-up has taken it: same id, same content
    plan("--sweep")  # records the wait once
    plan("--sweep")
    pending = raw(tdd.origin, "ls-tree", "--name-only", f"refs/l4/locks/kiro/{PARENT}", "ledger-pending/").split()
    lines = [
        json.loads(line)
        for name in pending
        for line in raw(tdd.origin, "show", f"refs/l4/locks/kiro/{PARENT}:{name}").splitlines()
    ]
    waiting = [e for e in lines if e["type"] == "feedback.waiting"]
    assert [(e["ids"], e["reason"]) for e in waiting] == [(["FB-002"], "follow_up_open")]
    assert run_l4([], unit=False).code == 0
    assert raw(tdd.origin, "for-each-ref", f"refs/heads/l4/kiro/{PARENT}-followup-2").strip() == ""
    assert main(["status", "--json", "--repo", str(tdd.repo)], environ=tdd.environ) == 0
    status = {u["unit"]: u for u in json.loads(capsys.readouterr().out)["units"]}
    assert status[f"kiro:{PARENT}"]["feedback_counts"].get("waiting") == 1


def test_feedback_on_an_archived_openspec_change_becomes_a_follow_up_change(
    tdd_repo, run_l4, raw, tmp_path, forge_env, use_fake_gitlab, monkeypatch
):
    """The OpenSpec variant: the parent is only an archive folder on the base (no change folder, no lock ref)."""
    from ..specs.fixcli import patch_openspec

    patch_openspec(monkeypatch)
    repo, name = tdd_repo.repo, "add-discount-codes"
    archive = repo / "openspec" / "changes" / "archive" / f"2026-10-01-{name}"
    archive.parent.mkdir(parents=True)
    raw(repo, "mv", f"openspec/changes/{name}", str(archive.relative_to(repo)))
    (archive / "tasks.md").write_text("# Tasks\n\n- [x] 1.1 Parse codes\n")
    ledger_files(archive, f"openspec:{name}", "r-20261003T1312Z-7f3a", ("none", "in_review"), ("in_review", "merged"))
    items = (
        {"title": "Dedupe the rounding"},
        {
            "kind": FeedbackKind.BEHAVIOUR, "title": "Round half up", "text": "Round half up at the till.",
            "when": "the total is 0.005", "then": "the total is 0.01", "places": (),
        },
    )  # fmt: skip
    (archive / "feedback.md").write_text(feedback_text(tmp_path, *items).replace(PARENT, name))
    tdd_repo.write_config()
    new_origin_main(tdd_repo, raw, {})
    main_before = raw(tdd_repo.origin, "rev-parse", "main").strip()

    run = run_l4([], "--unit", f"openspec:{name}", unit=False)

    assert run.code == 0, run.outcome
    branch, folder = f"l4/openspec/{name}-followup-1", f"openspec/changes/{name}-followup-1"
    assert raw(tdd_repo.origin, "rev-parse", "main").strip() == main_before
    shown = lambda path: raw(tdd_repo.origin, "show", f"{branch}:{path}")  # noqa: E731
    marker = json.loads(shown(f"{folder}/.l4/followup.json"))
    assert marker["parent"] == f"openspec:{name}" and [i["id"] for i in marker["items"]] == ["FB-001", "FB-002"]
    assert "Requested by Ana" in shown(f"{folder}/proposal.md")
    assert "skip_specs" not in shown(f"{folder}/.openspec.yaml")  # the behaviour item has a delta
    delta = shown(f"{folder}/specs/pricing/spec.md")  # the first capability of the parent's archived specs
    assert "## ADDED Requirements" in delta and "feedback FB-002" in delta and "the total is 0.01" in delta
    tasks = shown(f"{folder}/tasks.md")
    assert tasks.count("- [ ] 1.") == 2
    archived = shown(f"openspec/changes/archive/2026-10-01-{name}/feedback.md")
    assert archived.count("**Status:** taken") == 2 and f"Taken into {name}-followup-1" in archived
    ledger = events(tdd_repo, raw, branch, folder)
    assert [e["id"] for e in ledger if e["type"] == "feedback.taken"] == ["FB-001", "FB-002"]
    on_main = raw(tdd_repo.origin, "show", f"main:openspec/changes/archive/2026-10-01-{name}/feedback.md")
    assert "**Status:** taken" not in on_main  # only the follow-up's branch says taken


def test_a_follow_up_that_cannot_be_made_fails_the_run_and_nothing_is_left_half_done(
    merged_kiro, run_l4, raw, monkeypatch
):
    """A push that fails leaves no branch and no state: the exit code says so and the next run tries again."""
    from l4.forge.pushfail import PushFailed
    from l4.vcs.git import Git

    real = Git.push

    def refuse(self, remote, refspecs, *, config=()):
        if any(f"refs/heads/l4/kiro/{FOLLOW}" in r for r in refspecs):
            raise PushFailed(1, "push refused by the server")
        return real(self, remote, refspecs, config=config)

    monkeypatch.setattr(Git, "push", refuse)
    run = run_l4([], unit=False)
    assert run.code != 0
    assert raw(merged_kiro.origin, "for-each-ref", f"refs/heads/{BRANCH}").strip() == ""
    monkeypatch.setattr(Git, "push", real)
    assert run_l4([CHORE], unit=False).code == 0  # the next run makes it
    assert raw(merged_kiro.origin, "for-each-ref", f"refs/heads/{BRANCH}").strip() != ""


def test_the_archived_parent_is_found_by_its_exact_dated_name(tmp_path):
    """review #13: `*-x` also matched `2026-05-01-other-x`; the parent `x` is only `<date>-x`."""
    from types import SimpleNamespace

    from l4.config.schema import L4Config
    from l4.follow_up import _parent_in
    from l4.specs.base import Framework, UnitRef

    archive = tmp_path / "openspec" / "changes" / "archive"
    for name in ("2026-04-01-x", "2026-05-01-other-x", "2026-06-01-x2"):
        (archive / name).mkdir(parents=True)
    snapshot = SimpleNamespace(ref=UnitRef(Framework.OPENSPEC, "x", tmp_path / "openspec" / "changes" / "x"))
    found = _parent_in(tmp_path, L4Config(), snapshot)
    assert found is not None and found.path.name == "2026-04-01-x"
    (archive / "2026-04-01-x").rmdir()
    assert _parent_in(tmp_path, L4Config(), snapshot) is None
