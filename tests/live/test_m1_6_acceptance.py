"""The live exit protocol of M1.6 (docs/plan/m16-plan.md, "Live exit protocol on example-group/dummy-agentic through
l4-runner", gap M16-G22, line 40) as code: one test per step that can be read, reading pipelines, jobs, job
artifacts, merge requests, branches and file blobs through the read-only API.

It writes nothing to the repository and prints no token: job logs are searched for token shapes, never echoed. The
operator runs it after each protocol step; a test whose step has not happened yet SKIPS (the thing it looks for is not
there), a test whose step happened and went wrong FAILS. Every id it meets goes into the JSON file named by
`L4_LIVE_RECORD` (default `/tmp/l4_m1_6_ids.json`), for `docs/live/README.md`.

    L4_LIVE=1 uv run pytest tests/live/test_m1_6_acceptance.py -m live -q -rs

Access is the one of `test_m1_1_acceptance.py` (`gitlab_client.py`): the Mintkey proxy, or `L4_LIVE_API_URL` +
`L4_LIVE_TOKEN`. Not live reads, so without a test: step 1's push and step 2's human push (the operator makes them),
step 3's answers (the operator writes them), step 4 (Mac: canary, export, audit, tuning, score, report) and step 5
(deploy of the checkpoint). Step 6 (P4) is found by the maintainer's commit title containing `laya-tuned`; its tests
skip until that commit and its pipeline exist. Step 7's `pgrep` on the runner is not readable here: the job logs are
checked for the start and the stop of `laya-serve` instead.
"""

import json
import os
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from .gitlab_client import LiveGitLab, LiveUnavailable

pytestmark = pytest.mark.live

UNIT = "add-bulk-discount"
BRANCH = f"l4/openspec/{UNIT}"
SPEC_DIR = f"openspec/changes/{UNIT}"
P4_UNIT = "add-free-shipping-flag"
P4_BRANCH = f"l4/openspec/{P4_UNIT}"
P4_DIR = f"openspec/changes/{P4_UNIT}"
P1_TITLE = "Seed inventory module, coverage, bulk discount unit"
P4_MARK = "laya-tuned"
STOCK = "src/inventory/stock.py"
RECEIPT = "src/pricing/receipt.py"
RECEIPT_FUNCTIONS = ("format_receipt", "format_line", "format_total")
MIN_PERCENT = 80
RUNNING = ("created", "pending", "running", "waiting_for_resource", "preparing")
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
TOKEN_SHAPE = re.compile(r"glpat-|glptt-|gldt-|glcbt-|password=|sk-ant-|mk_agent_")
RECORD: dict[str, Any] = {}


def record(step: str, **ids: Any) -> None:
    RECORD.setdefault(step, {}).update(ids)


@pytest.fixture(scope="module", autouse=True)
def write_record() -> Iterator[None]:
    yield
    path = Path(os.environ.get("L4_LIVE_RECORD", "/tmp/l4_m1_6_ids.json"))
    path.write_text(json.dumps(RECORD, indent=2, sort_keys=True) + "\n", encoding="utf-8")


@pytest.fixture(scope="module")
def gl() -> LiveGitLab:
    try:
        return LiveGitLab()
    except LiveUnavailable as exc:
        pytest.skip(str(exc))


# --- reading helpers ----------------------------------------------------------------------------------------------


def finished_job(gl: LiveGitLab, sha: str, name: str = "l4") -> tuple[dict[str, Any], dict[str, Any]]:
    """(pipeline, the one job called `name`) of the pipeline of `sha`; skips while there is none or it still runs."""
    pipeline = gl.pipeline_of(sha)
    if pipeline is None:
        pytest.skip(f"no pipeline for {sha[:12]} (yet)")
    if pipeline["status"] in RUNNING:
        pytest.skip(f"pipeline {pipeline['id']} is still {pipeline['status']}")
    jobs = [j for j in gl.jobs(pipeline["id"]) if j["name"] == name]
    assert len(jobs) == 1, f"pipeline {pipeline['id']}: expected exactly one `{name}` job, found {len(jobs)}"
    return pipeline, jobs[0]


def trace(gl: LiveGitLab, job: dict[str, Any]) -> str:
    return ANSI.sub("", gl.trace(job["id"]))


def ledger(gl: LiveGitLab, spec_dir: str, ref: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for path in gl.tree(f"{spec_dir}/.l4/ledger", ref):
        if path.endswith(".jsonl"):
            events += [json.loads(line) for line in (gl.file(path, ref) or "").splitlines() if line.strip()]
    if not events:
        pytest.skip(f"no ledger under {spec_dir}/.l4/ledger on {ref} (yet)")
    return sorted(events, key=lambda e: (e["ts"], e["run_id"], e["seq"]))


def of_type(events: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [e for e in events if e["type"] == kind]


def on_main(gl: LiveGitLab, needle: str) -> dict[str, Any]:
    found = next((c for c in gl.commits("main", 200) if needle in c["title"]), None)
    if found is None:
        pytest.skip(f"no commit on main with {needle!r} in its title yet")
    return found


def unit_commits(gl: LiveGitLab, branch: str) -> list[dict[str, Any]]:
    """The unit branch's commits above `main`, oldest first, with their full messages."""
    main = {c["id"] for c in gl.commits("main", 200)}
    found = [c for c in gl.commits(branch, 200) if c["id"] not in main]
    if not found:
        pytest.skip(f"{branch} has no commit above main (yet)")
    return [gl.commit(c["id"]) or c for c in reversed(found)]


def verdict_round(events: list[dict[str, Any]], verdict: str) -> int:
    """The last round that ended with `verdict`; skips while there is none."""
    rounds = [e["round"] for e in of_type(events, "verify.verdict") if e["verdict"] == verdict]
    if not rounds:
        pytest.skip(f"no round ended {verdict} yet")
    return rounds[-1]


def evidence_of(gl: LiveGitLab, spec_dir: str, ref: str, round_no: int) -> dict[str, Any]:
    text = gl.file(f"{spec_dir}/.l4/evidence/round-{round_no}/evidence.json", ref)
    if text is None:
        pytest.skip(f"no evidence.json for round {round_no} on {ref} (yet)")
    return json.loads(text)


def s1_rows(gl: LiveGitLab, job: dict[str, Any]) -> list[dict[str, Any]]:
    files = {p: t for p, t in gl.artifact_texts(job["id"]).items() if p.startswith(".l4-out/s1/")}
    assert files, f"job {job['id']} left no .l4-out/s1/ artefact"
    return [json.loads(line) for text in files.values() for line in text.splitlines() if line.strip()]


def kind_rows(rows: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [r for r in rows if r.get("kind") == kind]


def p1(gl: LiveGitLab) -> tuple[dict[str, Any], dict[str, Any]]:
    pipeline, job = finished_job(gl, on_main(gl, P1_TITLE)["id"])
    record("1", pipeline=pipeline["id"], job=job["id"], status=job["status"])
    return pipeline, job


def p2(gl: LiveGitLab) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], int]:
    """(pipeline, job, ledger, round) of the run after the human push of step 2: the last round that ended
    NEEDS_HUMAN with the holds; the job is the one whose log names the answers submitted."""
    events = ledger(gl, SPEC_DIR, BRANCH)
    round_no = verdict_round(events, "NEEDS_HUMAN")
    evidence = evidence_of(gl, SPEC_DIR, BRANCH, round_no)
    if not evidence["holds"]:
        pytest.skip("the last NEEDS_HUMAN round has no hold (step 2 has not happened yet)")
    commits = unit_commits(gl, BRANCH)
    for c in reversed(commits):
        pipeline = gl.pipeline_of(c["id"])
        if pipeline is None or pipeline["status"] in RUNNING:
            continue
        jobs = [j for j in gl.jobs(pipeline["id"]) if j["name"] == "l4"]
        if jobs and any(r.get("kind") == "item" for r in s1_rows_or_empty(gl, jobs[0])):
            record("2", pipeline=pipeline["id"], job=jobs[0]["id"], round=round_no)
            return pipeline, jobs[0], events, round_no
    pytest.skip("no finished l4 job left a .l4-out/s1/ artefact with items yet")


def s1_rows_or_empty(gl: LiveGitLab, job: dict[str, Any]) -> list[dict[str, Any]]:
    try:
        return s1_rows(gl, job)
    except AssertionError:
        return []


# --- step 1: P1, intake raises Q-001 and the unit waits for a human ----------------------------------------------


def test_p1_intake_raises_q001_and_the_unit_waits_for_a_human(gl):
    _, job = p1(gl)
    log = trace(gl, job)
    assert not TOKEN_SHAPE.search(log), "a token shape is in the job log"
    env = next((t for p, t in gl.artifact_texts(job["id"]).items() if p.endswith("l4.env")), "")
    assert "L4_EXIT=11" in env, env
    events = ledger(gl, SPEC_DIR, BRANCH)
    raised = [e for e in of_type(events, "question.raised") if e.get("id") == "Q-001"]
    assert raised, "intake raised no Q-001"
    assert any(e.get("to") == "awaiting_human" for e in of_type(events, "phase.changed")) or "awaiting_human" in log
    mrs = gl.merge_requests(state="opened", source_branch=BRANCH)
    assert mrs and mrs[0].get("draft"), "no draft merge request for the waiting unit"
    record("1", mr=mrs[0]["iid"])


# --- step 2: P2, the human push and the evidence --------------------------------------------------------------------


def test_p2_human_edits_survive_every_guard(gl):
    _, _, events, _ = p2(gl)
    stock = gl.file(STOCK, BRANCH) or ""
    assert "LOW_STOCK_THRESHOLD = 3" in stock, "the human's edit of src/inventory/stock.py was reverted"
    receipt = gl.file(RECEIPT, BRANCH) or ""
    assert all(f"def {name}" in receipt for name in RECEIPT_FUNCTIONS), "src/pricing/receipt.py was reverted"
    touched = {e.get("path") for e in of_type(events, "guard.violation")}
    assert STOCK not in touched and RECEIPT not in touched, sorted(p for p in touched if p)
    record("2", guard_violation_paths=sorted(str(p) for p in touched if p))


def test_p2_the_scope_hold_and_the_coverage_hold_are_in_the_evidence(gl):
    _, _, _, round_no = p2(gl)
    evidence = evidence_of(gl, SPEC_DIR, BRANCH, round_no)
    holds = {h["kind"]: h for h in evidence["holds"]}
    assert "scope" in holds and holds["scope"]["subjects"] == [STOCK], evidence["holds"]
    assert "coverage" in holds, evidence["holds"]
    covered = {s.split("::")[-1] for s in holds["coverage"]["subjects"]}
    assert covered >= set(RECEIPT_FUNCTIONS), (
        f"the coverage hold names {sorted(covered)}: receipt functions are covered? (retry rule: repeat steps 1-2 "
        "with src/pricing/receipt_debug.py, 60 executable lines)"
    )
    coverage = evidence["diff_coverage"]
    assert coverage["status"] == "ok" and coverage["percent"] < MIN_PERCENT, coverage
    assert evidence["tests_ran"]["tests_ok"] is True, evidence["tests_ran"]
    files = {f["path"]: f["label"] for f in evidence["scope"]["files"]}
    assert files[STOCK] == "out_of_scope"
    record("2", coverage_percent=coverage["percent"], holds=[h["id"] for h in evidence["holds"]])


def test_p2_verdict_report_and_questions(gl):
    _, job, events, round_no = p2(gl)
    verdicts = [e for e in of_type(events, "verify.verdict") if e["round"] == round_no]
    assert verdicts and verdicts[-1]["verdict"] == "NEEDS_HUMAN", verdicts
    text = gl.file(f"{SPEC_DIR}/verification.md", BRANCH) or ""
    assert "NEEDS_HUMAN" in text[:600], text[:600]
    assert "## Evidence" in text and STOCK in text and "src/pricing/receipt.py::" in text
    questions = gl.file(f"{SPEC_DIR}/questions.md", BRANCH) or ""
    for hold in evidence_of(gl, SPEC_DIR, BRANCH, round_no)["holds"]:
        assert hold["id"] in questions, f"no verdict question for {hold['id']}"
    env = next((t for p, t in gl.artifact_texts(job["id"]).items() if p.endswith("l4.env")), "")
    assert "L4_EXIT=11" in env, env


def test_p2_items_and_answers_from_both_engines_and_laya_serve_inside_step_8(gl):
    _, job, _, round_no = p2(gl)
    rows = s1_rows(gl, job)
    items = kind_rows(rows, "item")
    answers = kind_rows(rows, "answer")
    subjects = [i["subject"] for i in items]
    files = {s for s in subjects if "::" not in s and s.endswith(".py") and not s.startswith("C-")}
    functions = [s for s in subjects if "::" in s]
    assert len(files) >= 3, f"item records for {len(files)} changed code file(s), at least 3 wanted: {sorted(files)}"
    assert len(functions) >= 2, f"item records for {len(functions)} function(s), at least 2 wanted"
    assert any(i["question_set"].startswith("l4/tests-ok") for i in items), "no tests-ok item"
    by_item: dict[str, set[str]] = {}
    for a in answers:
        by_item.setdefault(a["item_key"], set()).add(a["profile"])
    engines = {a["engine"] for a in answers}
    assert {"laya-local", "jev"} <= engines, f"answers came from {sorted(engines)}"
    for i in items:
        assert i["item_key"] in by_item, f"item {i['subject']} has no answer or error record"
    log = trace(gl, job)
    start = re.search(r"laya-serve started: pid \d+", log)
    stop = re.search(r"laya-serve stopped: pid \d+", log)
    assert start and stop and start.start() < stop.start(), "laya-serve start/stop is not in the job log"
    keys = evidence_of(gl, SPEC_DIR, BRANCH, round_no)["items"]
    assert keys and set(keys.values()) <= {i["item_key"] for i in items}, "evidence.json names an unknown item key"
    record("2", items=len(items), answers=len(answers), engines=sorted(engines))


# --- step 3: the human verdicts become labels -----------------------------------------------------------------------


def test_p3_the_scope_reject_is_a_label_and_the_coverage_accept_is_not(gl):
    events = ledger(gl, SPEC_DIR, BRANCH)
    human = of_type(events, "human.verdict")
    if len(human) < 2:
        pytest.skip(f"{len(human)} human.verdict event(s) so far; step 3 wants 2")
    by_target = {e["target"]: e["decision"] for e in human}
    holds = {}
    for n in sorted({e["round"] for e in of_type(events, "verify.verdict")}):
        holds |= {h["kind"]: h["id"] for h in evidence_of(gl, SPEC_DIR, BRANCH, n)["holds"] if h["id"] in by_target}
    assert by_target.get(holds["scope"]) == "reject" and by_target.get(holds["coverage"]) == "accept", by_target
    # the job that consumed the answers carries the label in its artefact
    for c in reversed(unit_commits(gl, BRANCH)):
        pipeline = gl.pipeline_of(c["id"])
        if pipeline is None or pipeline["status"] in RUNNING:
            continue
        jobs = [j for j in gl.jobs(pipeline["id"]) if j["name"] == "l4"]
        labels = [r for j in jobs for r in kind_rows(s1_rows_or_empty(gl, j), "label")]
        if labels:
            break
    else:
        pytest.skip("no finished l4 job left a label record yet")
    assert [(r["label"], r["source"]) for r in labels] == [("out_of_scope", "human:verdict")], labels
    stock_items = {  # the question was raised in an earlier round than the last NEEDS_HUMAN one, perhaps
        evidence_of(gl, SPEC_DIR, BRANCH, n)["items"].get(f"l4/file-relevant@1|{STOCK}")
        for n in sorted({e["round"] for e in of_type(events, "verify.verdict")})
    }
    assert labels[0]["item_key"] in stock_items, "the label is not about the stock item"
    assert labels[0]["truth"] == {"relevant": False}
    record("3", label_item=labels[0]["item_key"], verdicts=sorted(by_target.values()))


# --- step 6: P4, the tuned checkpoint (only when the gate passed) ----------------------------------------------------


def p4(gl: LiveGitLab) -> tuple[dict[str, Any], dict[str, Any]]:
    pipeline, job = finished_job(gl, on_main(gl, P4_MARK)["id"])
    record("6", pipeline=pipeline["id"], job=job["id"], status=job["status"])
    return pipeline, job


def test_p4_doctor_s1_002_is_ok_and_the_tuned_profile_is_selected(gl):
    _, job = p4(gl)
    log = trace(gl, job)
    assert not TOKEN_SHAPE.search(log), "a token shape is in the job log"
    assert "S1-002" in log and not re.search(r"S1-002\W+(fail|warn|error)", log, re.I), "doctor S1-002 is not ok"
    events = ledger(gl, P4_DIR, P4_BRANCH)
    selected = [e for e in of_type(events, "availability.selected") if e.get("role") == "s1_judge"]
    assert selected and selected[-1]["selected"] == "laya-tuned", selected


def test_p4_verdict_pass_and_three_engines_answered_every_item(gl):
    _, job = p4(gl)
    events = ledger(gl, P4_DIR, P4_BRANCH)
    verdicts = of_type(events, "verify.verdict")
    assert verdicts and verdicts[-1]["verdict"] == "PASS", verdicts
    rows = s1_rows(gl, job)
    items, answers = kind_rows(rows, "item"), kind_rows(rows, "answer")
    seen: dict[str, set[str]] = {}
    for a in answers:
        seen.setdefault(a["item_key"], set()).add(a["profile"])
    missing = [i["subject"] for i in items if not {"laya-tuned", "laya", "jev"} <= seen.get(i["item_key"], set())]
    assert items and not missing, f"items without all of laya-tuned, laya and jev: {missing}"
    mrs = gl.merge_requests(state="opened", source_branch=P4_BRANCH)
    assert mrs and not mrs[0].get("draft"), "the P4 merge request is not ready"
    record("6", items=len(items), mr=mrs[0]["iid"])


# --- step 7: read-only checks ---------------------------------------------------------------------------------------


def test_skip_ci_commits_have_no_l4_job(gl):
    commits = unit_commits(gl, BRANCH)
    harness = [c for c in commits if "[skip ci]" in c["message"]]
    assert harness, "the unit branch has no [skip ci] commit"
    for c in harness:
        pipeline = gl.pipeline_of(c["id"])
        if pipeline is not None:
            assert "l4" not in {j["name"] for j in gl.jobs(pipeline["id"])}, f"an l4 job ran on {c['title']!r}"
    record("7", skip_ci_commits=len(harness))


def test_job_logs_hold_no_token_shape_and_record_the_peak_memory(gl):
    _, job, _, _ = p2(gl)
    log = trace(gl, job)
    assert not TOKEN_SHAPE.search(log), "a token shape is in the job log"
    logs = {p: t for p, t in gl.artifact_texts(job["id"]).items() if p.startswith(".l4-out/logs/")}
    assert all(not TOKEN_SHAPE.search(t) for t in logs.values()), "a token shape in .l4-out/logs/"
    memory = [ln.strip() for ln in log.splitlines() if re.search(r"(?i)max(imum)? resident|peak (rss|memory)", ln)]
    record("7", p2_peak_memory_lines=memory[:3])  # for the operator's README: the lines, never an assertion
