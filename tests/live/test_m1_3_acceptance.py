"""The live exit protocol of M1.3 (docs/plan/m13-plan.md, "Live exit protocol on example-group/dummy-agentic through
l4-runner") as code (gap M13-G6): one test per step, reading pipelines, jobs, merge requests, labels, notes,
branches, commit trailers, `verification.md` and the ledger through the read-only API.

It writes nothing to the repository. The operator runs it after each protocol step; a test whose step has not happened
yet SKIPS (the thing it looks for is not there), a test whose step happened and went wrong FAILS. Every id it meets
goes into the JSON file named by `L4_LIVE_RECORD` (default `/tmp/l4_m1_3_ids.json`), for `docs/live/README.md`.

    L4_LIVE=1 uv run pytest tests/live/test_m1_3_acceptance.py -m live -q -rs

Access as in `test_m1_1_acceptance.py`: `MINTKEY_AUTH` (or `~/.claude.json`), or `L4_LIVE_API_URL` + `L4_LIVE_TOKEN`.
The two branches of step 1 (1A: a PASS with a convertible minor; 1B: NEEDS_HUMAN) are told apart by the ledger: the
tests of the branch that did not happen skip.
"""

import json
import os
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from .gitlab_client import LiveGitLab, LiveUnavailable
from .protocol_m13 import (
    branch_of_step_1,
    handed_off,
    of_type,
    parent_events,
    tdd_of,
    trailers,
    unit_checkpoints,
)

pytestmark = pytest.mark.live

UNIT = "add-shipping-fee"
FIX = f"{UNIT}-fix-1"
BRANCH = f"l4/openspec/{UNIT}"
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
EM_DASH = "\N{EM DASH}"
RECORD: dict[str, Any] = {}


def record(step: str, **ids: Any) -> None:
    RECORD.setdefault(step, {}).update(ids)


@pytest.fixture(scope="module", autouse=True)
def write_record() -> Iterator[None]:
    yield
    path = Path(os.environ.get("L4_LIVE_RECORD", "/tmp/l4_m1_3_ids.json"))
    path.write_text(json.dumps(RECORD, indent=2, sort_keys=True) + "\n", encoding="utf-8")


@pytest.fixture(scope="module")
def gl() -> LiveGitLab:
    try:
        return LiveGitLab()
    except LiveUnavailable as exc:
        pytest.skip(str(exc))


# --- reading helpers ----------------------------------------------------------------------------------------------


def unit_mr(gl: LiveGitLab) -> dict[str, Any] | None:
    found = gl.merge_requests(state="all", source_branch=BRANCH)
    return max(found, key=lambda m: m["iid"]) if found else None


def ledger(gl: LiveGitLab, ref: str = BRANCH) -> list[dict[str, Any]]:
    events = []
    for path in gl.tree(f"openspec/changes/{UNIT}/.l4/ledger", ref):
        if path.endswith(".jsonl"):
            events += [json.loads(line) for line in (gl.file(path, ref) or "").splitlines() if line.strip()]
    return sorted(events, key=lambda e: (e["ts"], e["run_id"], e["seq"]))


def need_ledger(gl: LiveGitLab) -> list[dict[str, Any]]:
    events = ledger(gl)
    if not events:
        pytest.skip(f"{BRANCH} has no ledger yet (step 1)")
    return events


def commits(gl: LiveGitLab) -> list[dict[str, Any]]:
    return gl.commits(BRANCH, 200)


def sticky(gl: LiveGitLab, iid: int) -> str:
    notes = [n for n in gl.notes(iid) if not n.get("system") and n["body"].startswith("<!-- l4:sticky -->")]
    return notes[0]["body"] if notes else ""


def verification(gl: LiveGitLab, ref: str = BRANCH) -> str:
    return gl.file(f"openspec/changes/{UNIT}/verification.md", ref) or ""


def round_verdicts(events: list[dict[str, Any]]) -> list[tuple[int, str]]:
    return [(e["round"], e["verdict"]) for e in of_type(events, "verify.verdict")]


# --- step 0: the upgrade and the levers -------------------------------------------------------------------------------


def test_step0_main_carries_the_m13_levers_and_the_seed(gl):
    config = gl.file(".l4/config.yaml", "main")
    if config is None or "verifier_agent" not in config:
        pytest.skip("the M1.3 levers are not on main yet (step 0)")
    assert (
        "fix_minor_findings: true" in config and "max_fix_rounds: 1" in config and "audit_sample_ratio: 0.1" in config
    )
    if gl.file(f"openspec/changes/{UNIT}/tasks.md", "main") is None:
        pytest.skip("the seed is not on main yet (step 1)")
    record("0", seeded=True)


# --- step 1: task 1.1 and round 1 ------------------------------------------------------------------------------------


def test_step1_task_1_1_goes_red_with_zero_value_proofs_then_green(gl):
    events = parent_events(need_ledger(gl))  # a fix unit's task 1.1 writes into this ledger too
    purity = of_type(events, "stub.purity", task="1.1")
    red = of_type(events, "task.red_ok", task="1.1")
    assert purity and red, "task 1.1 has no stub.purity or task.red_ok event"
    criteria = red[-1]["criteria"]
    assert len(criteria) == 2 and {c["proof"] for c in criteria.values()} == {"zero_value"}, criteria
    assert of_type(events, "task.done", task="1.1")
    tdd = tdd_of(commits(gl), f"openspec:{UNIT}", "1.1")  # the branch lists main's history (other units' 1.1) too
    assert tdd.count("red") == 1 and tdd.count("green") == 1, tdd
    committed = of_type(events, "task.red_committed", task="1.1")  # C22: the sha travels in its own event
    record("1", criteria=sorted(criteria), red_sha=(committed or red)[-1].get("sha"))


def test_step1_round_1_ran_the_full_ladder_with_the_matrix_and_one_audit_test(gl):
    events = need_ledger(gl)
    if not round_verdicts(events):
        pytest.skip("round 1 has not ended yet")
    text = gl.file(f"openspec/changes/{UNIT}/.l4/evidence/round-1/verification.md", BRANCH) or ""
    for row in ("| 0 | preconditions", "| 1 | integrity", "| 2 | build", "| 3 | tests", "| 4 | traceability"):
        assert row in text, row
    assert "| 4a | audit sampling" in text and "| 9 | judge" in text and "| 10 | aggregation" in text
    assert "## Traceability" in text and "zero_value" in text and "2/2 criteria covered" in text
    audit = of_type(events, "verify.audit", status="accepted")
    if audit:
        round_commit = [c for c in commits(gl) if c["title"] == f"test({UNIT}): verifier round 1 [skip ci]"]
        assert len(round_commit) == 1 and trailers(round_commit[0]["message"]).get("L4-Phase") == "verifying"
        assert re.fullmatch(r"tests/test_l4_audit_c_[0-9a-f]{8}_r1\.py", audit[0]["path"]), audit[0]["path"]
        assert "@pytest.mark.l4" in (gl.file(audit[0]["path"], BRANCH) or "")
    record("1", round_1=round_verdicts(events)[0][1], audit=[a["status"] for a in of_type(events, "verify.audit")])


def test_step1a_a_convertible_minor_becomes_fix_unit_1_before_the_hand_off(gl):
    events = need_ledger(gl)
    spawned = of_type(events, "fix.spawned", fix_unit=FIX)
    if branch_of_step_1(events) != "1A" or not spawned:  # in 1B, step 2's answers spawn a fix unit too
        pytest.skip("branch 1A did not happen (round 1 did not PASS with a fix unit)")
    assert spawned[0]["round"] == 1 and spawned[0]["parent"] == f"openspec:{UNIT}"
    phases = [(e["from"], e["to"]) for e in of_type(events, "phase.changed")]
    assert ("verifying", "verified") in phases and ("verified", "fixing") in phases
    fix_commit = next((c for c in commits(gl) if c["title"] == f"docs({UNIT}): fix unit 1 [skip ci]"), None)
    assert fix_commit is not None and trailers(fix_commit["message"]).get("L4-Phase") == "verifying"
    marker = json.loads(gl.file(f"openspec/changes/{FIX}/.l4/fix.json", BRANCH) or "{}")
    assert marker["schema"] == "l4/fix-unit@1" and marker["parent"] == f"openspec:{UNIT}"
    tasks = gl.file(f"openspec/changes/{FIX}/tasks.md", BRANCH) or ""
    assert re.search(r"^- \[x\] 1\.1 .*\(F-[0-9a-f]{8}", tasks, re.M), tasks
    assert "proposal.md" in " ".join(gl.tree(f"openspec/changes/{FIX}", BRANCH))
    spec = gl.file(f"openspec/changes/{FIX}/specs/shipping/spec.md", BRANCH) or ""
    if spec:
        assert f"### Requirement: Shipping fee {EM_DASH} regression 1" in spec and "## ADDED Requirements" in spec
        assert "MODIFIED" not in spec and "REMOVED" not in spec and "RENAMED" not in spec
    else:
        assert "skip_specs: true" in (gl.file(f"openspec/changes/{FIX}/.openspec.yaml", BRANCH) or "")
    by_unit = [
        trailers(c["message"]) for c in commits(gl) if trailers(c["message"]).get("L4-Unit") == f"openspec:{FIX}"
    ]
    assert by_unit and {t.get("L4-TDD") for t in by_unit} <= {"red", "green", "already-satisfied", "exempt"}
    assert of_type(events, "fix.done", fix_unit=FIX)
    verdicts = round_verdicts(events)
    assert verdicts[-1][1] == "PASS" and verdicts[-1][0] >= 2, verdicts
    record("1A", fix_unit=FIX, fix_commit=fix_commit["id"], verdicts=verdicts)


def test_step1b_needs_human_asks_one_verdict_question_per_criterion_and_judge_finding(gl):
    events = need_ledger(gl)
    asked = of_type(events, "question.raised", kind="verdict")
    if branch_of_step_1(events) != "1B" or not asked:
        pytest.skip("branch 1B did not happen (round 1 did not end NEEDS_HUMAN with verdict questions)")
    questions = gl.file(f"openspec/changes/{UNIT}/questions.md", BRANCH) or ""
    assert questions.count("- **Kind:** verdict") >= len(asked) and "**Blocking tasks:** none" in questions
    mr = unit_mr(gl)
    assert mr is not None
    if not of_type(events, "phase.changed", trigger="verdicts_answered"):  # the labels and the note are of that moment
        assert {"l4:awaiting_human", "l4:needs-answers"} <= set(mr.get("labels", []))
        assert "Waiting for you: a human answer" in sticky(gl, mr["iid"])
    record("1B", questions=[q["id"] for q in asked], mr=mr["iid"])


def test_step2_answers_resume_at_aggregation_and_a_reject_spawns_the_fix_unit(gl):
    events = need_ledger(gl)
    verdicts = of_type(events, "human.verdict")
    if not verdicts:
        pytest.skip("no verdict answer has been consumed yet (step 2)")
    steps_round_2 = {e["step"]: e["status"] for e in of_type(events, "verify.step", round=2)}
    assert all(steps_round_2.get(s) == "reused" for s in ("0", "1", "2", "3", "4", "9")), steps_round_2
    assert not [e for e in of_type(events, "verify.judge") if e["round"] == 2], "round 2 called the judge"
    assert {v["decision"] for v in verdicts} <= {"accept", "reject"}
    if any(v["decision"] == "reject" for v in verdicts):
        spawned = of_type(events, "fix.spawned", fix_unit=FIX)
        assert spawned and set(spawned[0]["consumed"]) >= {v["question"] for v in verdicts if v["decision"] == "reject"}
    record("2", verdicts=[(v["target"], v["decision"]) for v in verdicts])


# --- step 3: loop safety ---------------------------------------------------------------------------------------------


def test_step3_no_checkpoint_commit_started_an_l4_job(gl):
    events = need_ledger(gl)
    if not round_verdicts(events):
        pytest.skip("no round has ended yet")
    checkpoints = unit_checkpoints(commits(gl), f"openspec:{UNIT}")  # not an operator's `[skip ci]` commit on main
    assert checkpoints, "the unit branch has no checkpoint commit"
    for commit in checkpoints:
        pipeline = gl.pipeline_of(commit["id"])
        if pipeline is not None:
            jobs = {j["name"] for j in gl.jobs(pipeline["id"])}
            assert "l4" not in jobs, f"{commit['title']!r} started an l4 job in pipeline {pipeline['id']}"
    record("3", checkpoints=len(checkpoints))


# --- step 4: the hand-off and what a reader sees ---------------------------------------------------------------------


def test_step4_the_merge_request_is_in_review_with_the_fix_unit_in_its_diff(gl):
    events = need_ledger(gl)
    if not handed_off(events, commits(gl), UNIT):  # a `pr.updated` (labels on the draft) is no hand-off
        pytest.skip("the unit has not been handed off yet")
    mr = unit_mr(gl)
    assert mr is not None and not mr.get("draft") and "l4:in_review" in mr.get("labels", [])
    assert not [label for label in mr["labels"] if label.startswith("l4:") and label != "l4:in_review"], mr["labels"]
    assert "Waiting for you: a human answer" not in sticky(gl, mr["iid"])
    changes = (gl.get(f"/merge_requests/{mr['iid']}/changes") or {}).get("changes", [])
    if of_type(events, "fix.spawned", fix_unit=FIX):
        assert any(c["new_path"].startswith(f"openspec/changes/{FIX}/") for c in changes)
    head = gl.commit(mr["sha"]) or {}
    assert head.get("title") == f"docs({UNIT}): hand off to review"
    record("4", mr=mr["iid"], head=mr["sha"])


# --- step 5: the archive MR moves the parent and then the fix unit ----------------------------------------------------


def test_step5_the_archive_mr_moves_the_parent_and_its_fix_units_in_one_commit(gl):
    archives = gl.merge_requests(state="all", source_branch=f"l4/archive/openspec/{UNIT}")
    if not archives:
        pytest.skip("the unit is not merged yet (optional step 5)")
    mr = archives[0]
    changes = (gl.get(f"/merge_requests/{mr['iid']}/changes") or {})["changes"]
    paths = {c["new_path"] for c in changes}
    archive = re.compile(r"^openspec/changes/archive/\d{4}-\d{2}-\d{2}-")
    assert any(archive.match(p) and f"-{UNIT}/" in p for p in paths)
    if of_type(ledger(gl, "main") or ledger(gl), "fix.spawned", fix_unit=FIX):
        assert any(archive.match(p) and f"-{FIX}/" in p for p in paths), "the fix unit was not archived with its parent"
    spec = gl.file("openspec/specs/shipping/spec.md", mr["source_branch"]) or ""
    assert "Shipping fee" in spec
    record("5", archive_mr=mr["iid"])
