"""The live exit protocol of M1.5 (docs/plan/m15-plan.md, "Live exit protocol on example-group/dummy-agentic through
l4-runner", gap M15-G8) as code: one test per step, reading pipelines, jobs, job artifacts, merge requests,
labels, branches and file blobs through the read-only API.

It writes nothing to the repository and prints no token: job logs are searched for token shapes, never echoed. The
operator runs it after each protocol step; a test whose step has not happened yet SKIPS (the thing it looks for is not
there), a test whose step happened and went wrong FAILS. Every id it meets goes into the JSON file named by
`L4_LIVE_RECORD` (default `/tmp/l4_m1_5_ids.json`), for `docs/live/README.md`.

    L4_LIVE=1 uv run pytest tests/live/test_m1_5_acceptance.py -m live -q -rs

Access is the one of `test_m1_1_acceptance.py` (`gitlab_client.py`): the Mintkey proxy, or `L4_LIVE_API_URL` +
`L4_LIVE_TOKEN`. Step 0 (operator, runner) and step 1 (operator, local) are not live reads and have no test; step 6
(Jev) is not run, by decision.
"""

import json
import os
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from .gitlab_client import LiveGitLab, LiveUnavailable
from .protocol_m15 import commits_above, s1_lines

pytestmark = pytest.mark.live

FIRST, SECOND = "show-item-count", "show-subtotal"
BRANCH = f"l4/openspec/{FIRST}"
SECOND_BRANCH = f"l4/openspec/{SECOND}"
SPEC_DIR = f"openspec/changes/{FIRST}"
SECOND_DIR = f"openspec/changes/{SECOND}"
CRITERION = "C-de7f2d3f"
OTHER_CRITERION = "C-68f2e098"
LESSON = "L-09421538"
LESSONS_FILE = ".serena/memories/harness/lessons.md"
GENERATED_TEST = "e2e/test_l4_c_de7f2d3f.py"
P1_TITLE = "Seed the cart web page"
P3_TITLE = "Seed show-subtotal"
RUNNING = ("created", "pending", "running", "waiting_for_resource", "preparing")
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
TOKEN_SHAPE = re.compile(r"glpat-|glptt-|gldt-|glcbt-|password=|sk-ant-|mk_agent_")
RECORD: dict[str, Any] = {}


def record(step: str, **ids: Any) -> None:
    RECORD.setdefault(step, {}).update(ids)


@pytest.fixture(scope="module", autouse=True)
def write_record() -> Iterator[None]:
    yield
    path = Path(os.environ.get("L4_LIVE_RECORD", "/tmp/l4_m1_5_ids.json"))
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


def seed_commit(gl: LiveGitLab, title: str) -> dict[str, Any]:
    found = next((c for c in gl.commits("main", 200) if c["title"].startswith(title)), None)
    if found is None:
        pytest.skip(f"no commit on main titled {title!r} yet")
    return found


def p1(gl: LiveGitLab) -> tuple[dict[str, Any], dict[str, Any]]:
    pipeline, job = finished_job(gl, seed_commit(gl, P1_TITLE)["id"])
    record("2", pipeline=pipeline["id"], job=job["id"], status=job["status"])
    return pipeline, job


def p3(gl: LiveGitLab) -> tuple[dict[str, Any], dict[str, Any]]:
    pipeline, job = finished_job(gl, seed_commit(gl, P3_TITLE)["id"])
    record("4", pipeline=pipeline["id"], job=job["id"], status=job["status"])
    return pipeline, job


def ledger(gl: LiveGitLab, spec_dir: str, ref: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for path in gl.tree(f"{spec_dir}/.l4/ledger", ref):
        if path.endswith(".jsonl"):
            events += [json.loads(line) for line in (gl.file(path, ref) or "").splitlines() if line.strip()]
    if not events:
        pytest.skip(f"no ledger under {spec_dir}/.l4/ledger on {ref} (yet)")
    return sorted(events, key=lambda e: (e["ts"], e["run_id"], e["seq"]))


def unit_commits(gl: LiveGitLab, branch: str, seed_title: str = P1_TITLE) -> list[dict[str, Any]]:
    """The unit branch's commits above its seed commit, oldest first, with their full messages. Not "above `main`":
    after the human merge (step 3) every one of them is on `main` too, and the step-2 checks would skip."""
    found = commits_above(gl.commits(branch, 200), seed_commit(gl, seed_title)["id"])
    if not found:
        pytest.skip(f"{branch} has no commit above its seed commit (yet)")
    return [gl.commit(c["id"]) or c for c in found]


def trailer(message: str, key: str) -> str | None:
    found = re.search(rf"^{re.escape(key)}: (.+)$", message, re.MULTILINE)
    return found.group(1).strip() if found else None


def artifacts(gl: LiveGitLab, job: dict[str, Any], prefix: str) -> dict[str, str]:
    return {p: t for p, t in gl.artifact_texts(job["id"]).items() if p.startswith(prefix)}


def of_type(events: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [e for e in events if e["type"] == kind]


# --- step 2: P1, the first unit on main ---------------------------------------------------------------------------


def test_p1_doctor_plan_and_exit(gl):
    _, job = p1(gl)
    log = trace(gl, job)
    assert job["status"] == "success", job["status"]
    assert "MEM-001" in log and not re.search(r"MEM-001\W+(fail|error)", log, re.I), "doctor MEM-001 is not ok"
    assert re.search(rf"{FIRST}\b.*\bimplement\b", log), f"plan: no `implement` row for {FIRST}"
    assert not TOKEN_SHAPE.search(log), "a token shape is in the job log"
    env = next((t for p, t in gl.artifact_texts(job["id"]).items() if p.endswith("l4.env")), "")
    assert "L4_EXIT=0" in env, env


def test_p1_implementer_serena_ok_and_no_lessons_yet(gl):
    p1(gl)
    events = ledger(gl, SPEC_DIR, BRANCH)
    serena = of_type(events, "memory.serena")
    assert serena, "no memory.serena event: the Serena check did not run"
    assert all(e["status"] == "ok" for e in serena), [e.get("reason") for e in serena if e["status"] != "ok"]
    first_step = next(i for i, e in enumerate(events) if e["type"] == "agent.session")
    assert events.index(serena[0]) < first_step, "memory.serena came after the first agent step"
    assert not of_type(events, "lessons.injected"), "lessons were injected into the very first unit"
    assert not [e for e in of_type(events, "guard.violation") if e.get("path", "").startswith(".serena/")], (
        "a .serena path was a guard violation"
    )
    record("2", serena_startup_ms=[e.get("startup_ms") for e in serena])


def test_p1_verifier_steps_in_ledger_order(gl):
    p1(gl)
    events = ledger(gl, SPEC_DIR, BRANCH)
    steps = [(e["step"], e.get("status")) for e in of_type(events, "verify.step")]
    names = [s for s, _ in steps]
    for wanted in ("3", "4", "5", "8", "9"):
        assert wanted in names, f"verify.step {wanted} missing: {names}"
    assert names.index("3") < names.index("4") < names.index("5") < names.index("8") < names.index("9"), names
    assert dict(steps)["8"] == "ok", "step 8 (S1) was not ok"

    generated = [e for e in of_type(events, "verify.generated") if e.get("criterion") == CRITERION]
    assert generated, f"no verify.generated for {CRITERION}"
    accepted = generated[-1]
    assert accepted["test"].endswith("e2e/test_l4_c_de7f2d3f.py") or GENERATED_TEST in accepted["test"], accepted
    assert accepted["base"] == "fail" and accepted["head"] == "pass" and accepted["status"] == "accepted", accepted
    assert accepted.get("attempts") in (1, 2), accepted

    s1 = [e for e in of_type(events, "verify.s1") if e.get("criterion") == CRITERION]
    assert s1 and s1[-1]["status"] == "ok" and isinstance(s1[-1]["p"], float), s1
    assert s1[-1].get("model"), "verify.s1 records no served model"
    assert s1[-1].get("checkpoint"), "verify.s1 records no checkpoint"
    verdicts = of_type(events, "verify.verdict")
    assert verdicts and verdicts[-1]["verdict"] == "PASS", verdicts
    record("2", generated=accepted["test"], s1_p=s1[-1]["p"], s1_model=s1[-1]["model"], checkpoint=s1[-1]["checkpoint"])


def test_p1_s1_artefact_has_one_line_and_laya_serve_ran_inside_step_8(gl):
    _, job = p1(gl)
    lines = artifacts(gl, job, ".l4-out/s1/")
    assert lines, "the job left no .l4-out/s1/ artefact"
    found = s1_lines(lines)  # step 8's rows; M1.6's shadow records share the file
    rows = found.criteria
    assert [r["criterion"] for r in rows].count(CRITERION) == 1, [r["criterion"] for r in rows]
    row = next(r for r in rows if r["criterion"] == CRITERION)
    assert 0.0 <= row["p"] <= 1.0 and len(row["state_sha256"]) == 64
    assert row["served_model"] and row["model"] and row["question_set"] and row["engine"], row
    assert row["judge"] == "pass", f"the judge column holds {row['judge']!r}"
    log = trace(gl, job)
    laya_answered = any(not a.get("error") for a in found.by_engine().get("laya-local", []))
    if row["engine"] == "laya-local" or laya_answered:  # laya-local in step 8 itself or in its shadow half
        assert re.search(r"laya-serve started: pid \d+", log), "laya-serve start is not in the job log"
        assert re.search(r"laya-serve stopped: pid \d+", log), "laya-serve stop is not in the job log"
    shadow = {engine: sum(not a.get("error") for a in answers) for engine, answers in found.by_engine().items()}
    record("2", s1_row_engine=row["engine"], s1_question_set=row["question_set"], shadow_answered=shadow)


def test_p1_verification_md_passes_and_lists_the_generated_test(gl):
    p1(gl)
    text = gl.file(f"{SPEC_DIR}/verification.md", BRANCH)
    if text is None:
        pytest.skip("verification.md is not on the unit branch (yet)")
    assert "PASS" in text.splitlines()[0] or "PASS" in text[:400], text[:400]
    row = next((ln for ln in text.splitlines() if CRITERION in ln and ln.lstrip().startswith("|")), "")
    assert row, f"no matrix row for {CRITERION}"
    assert "generated, base fail, head pass" in row, row
    assert "S1" in text and re.search(r"\b0\.\d+|\b1\.0\b", row), "the S1 p is not in the matrix row"


def test_p1_branch_commits_come_in_the_planned_order_and_the_mr_is_ready(gl):
    p1(gl)
    commits = unit_commits(gl, BRANCH)
    titles = [c["title"] for c in commits]
    work = [i for i, c in enumerate(commits) if trailer(c["message"], "L4-TDD")]
    test_i = next((i for i, t in enumerate(titles) if t.startswith(f"test({FIRST}): verifier round 1")), None)
    docs_i = next((i for i, t in enumerate(titles) if t.startswith(f"docs({FIRST}): verification round 1")), None)
    memory_i = next((i for i, t in enumerate(titles) if t.startswith("chore(memory): lesson")), None)
    assert work and test_i is not None and docs_i is not None and memory_i is not None, titles
    assert max(work) < test_i < docs_i < memory_i < len(commits) - 1, titles
    for i in (test_i, docs_i, memory_i):
        assert "[skip ci]" in commits[i]["message"], titles[i]
    assert trailer(commits[memory_i]["message"], "L4-Phase") == "lessons"
    head = commits[-1]
    assert "[skip ci]" not in head["message"], "the hand-off commit is skippable"
    mrs = gl.merge_requests(state="all", source_branch=BRANCH)
    assert mrs, f"no merge request for {BRANCH}"
    mr = max(mrs, key=lambda m: m["iid"])
    if mr["state"] == "opened":
        assert not mr.get("draft") and "l4:in_review" in mr["labels"] and mr["sha"] == head["id"], mr["labels"]
    test_pipeline = gl.pipeline_of(head["id"])
    assert test_pipeline is not None and "test" in {j["name"] for j in gl.jobs(test_pipeline["id"])}
    assert "l4" not in {j["name"] for j in gl.jobs(test_pipeline["id"])}, "an l4 job ran on the hand-off commit"
    record("2", mr=mr["iid"], head=head["id"], memory_commit=commits[memory_i]["id"])


def test_p1_lesson_is_curated_on_the_branch(gl):
    p1(gl)
    events = ledger(gl, SPEC_DIR, BRANCH)
    created = [e for e in of_type(events, "lessons.curated") if e.get("action") == "created"]
    assert [e["id"] for e in created] == [LESSON], of_type(events, "lessons.curated")
    text = gl.file(LESSONS_FILE, BRANCH) or ""
    assert f"## {LESSON}" in text and "ui-criterion-without-e2e-test" in text, text[:500]
    assert "src/pricing/web/**" in text, "the lesson scope is not the web directory"


# --- step 3: the human merge --------------------------------------------------------------------------------------


def test_after_the_merge_main_holds_the_lesson_and_the_generated_test_and_an_archive_mr_exists(gl):
    mrs = gl.merge_requests(state="merged", source_branch=BRANCH)
    if not mrs:
        pytest.skip(f"the MR of {BRANCH} is not merged yet (step 3)")
    lessons = gl.file(LESSONS_FILE, "main") or ""
    assert f"## {LESSON}" in lessons, "main has no lesson after the merge"
    assert gl.file(GENERATED_TEST, "main"), f"main has no {GENERATED_TEST} after the merge"
    archive = gl.merge_requests(state="all", source_branch=f"l4/archive/openspec/{FIRST}")
    assert archive, "no archive MR was opened after the merge"
    record("3", merged_mr=mrs[0]["iid"], archive_mr=archive[0]["iid"])


# --- step 4: P3, the second unit sees the lesson ------------------------------------------------------------------


def test_p3_red_prompt_carries_the_lesson_and_the_ledger_says_so_before_the_first_session(gl):
    _, job = p3(gl)
    events = ledger(gl, SECOND_DIR, SECOND_BRANCH)
    red_prompts = [t for p, t in gl.artifact_texts(job["id"]).items() if re.search(r"-red-\d+\.prompt\.md$", p)]
    assert red_prompts, "the job left no red prompt artefact"
    assert any(f'<l4:data kind="lessons" ids="{LESSON}">' in t for t in red_prompts), "the red prompt has no lesson"
    injected = of_type(events, "lessons.injected")
    assert injected and injected[0]["ids"] == [LESSON] and injected[0]["channel"] == "prompt_section", injected
    first_session = next(i for i, e in enumerate(events) if e["type"] == "agent.session")
    assert events.index(injected[0]) < first_session, "lessons.injected came after the first agent.session"
    rendered = [e for e in of_type(events, "prompt.rendered") if e.get("role") == "red"]
    assert rendered and rendered[0]["lessons"] == [LESSON], rendered[:1]
    record("4", injected=injected[0]["ids"])


def test_p3_verdict_and_the_informational_branch_of_step_5(gl):
    _, job = p3(gl)
    events = ledger(gl, SECOND_DIR, SECOND_BRANCH)
    assert job["status"] == "success", job["status"]
    verdicts = of_type(events, "verify.verdict")
    assert verdicts and verdicts[-1]["verdict"] == "PASS", verdicts
    generated = [e for e in of_type(events, "verify.generated") if e.get("criterion") == OTHER_CRITERION]
    reinforced = [e for e in of_type(events, "lessons.curated") if e.get("action") == "reinforced"]
    # informational (plan step 4): either Codex wrote the e2e test itself (no generation), or a second generated
    # test was accepted and the lesson was reinforced
    if generated and generated[-1].get("status") == "accepted":
        assert [e["id"] for e in reinforced] == [LESSON], reinforced
    record("4", generated=bool(generated), reinforced=[e["id"] for e in reinforced])


# --- step 5: read-only checks ---------------------------------------------------------------------------------------


def test_s1_artefacts_have_one_line_per_criterion_with_model_p_and_state_hash(gl):
    pairs = []
    for getter in (p1, p3):
        _, job = getter(gl)
        files = artifacts(gl, job, ".l4-out/s1/")
        assert files, f"job {job['id']} left no .l4-out/s1/ artefact"
        rows = s1_lines(files).criteria  # step 8's rows; M1.6's shadow records share the file
        ids = [r["criterion"] for r in rows]
        assert ids and len(ids) == len(set(ids)), f"job {job['id']}: a criterion has two rows: {ids}"
        for r in rows:
            assert r["served_model"] and isinstance(r["p"], float) and len(r["state_sha256"]) == 64, r
        pairs.append((job["id"], len(rows)))
    record("5", s1_rows=pairs)


def test_skip_ci_commits_have_no_l4_job_and_no_l4_job_ran_on_a_harness_commit(gl):
    p1(gl)
    commits = unit_commits(gl, BRANCH)
    harness = [c for c in commits if "[skip ci]" in c["message"]]
    assert harness, "the unit branch has no [skip ci] commit"
    checked = 0
    for c in harness:
        pipeline = gl.pipeline_of(c["id"])
        if pipeline is None:
            continue  # [skip ci] creates none: the expected case
        assert "l4" not in {j["name"] for j in gl.jobs(pipeline["id"])}, f"an l4 job ran on {c['title']!r}"
        checked += 1
    head = commits[-1]
    pipeline = gl.pipeline_of(head["id"])
    if pipeline is not None:
        assert "l4" not in {j["name"] for j in gl.jobs(pipeline["id"])}, "an l4 job ran on the hand-off commit"
    record("5", skip_ci_commits=len(harness), with_pipeline=checked)


def test_the_job_logs_hold_no_token_shape_and_record_the_peak_memory(gl):
    peaks = {}
    for name, getter in (("p1", p1), ("p3", p3)):
        _, job = getter(gl)
        log = trace(gl, job)
        assert not TOKEN_SHAPE.search(log), f"{name}: a token shape is in the job log"
        logs = artifacts(gl, job, ".l4-out/logs/")
        assert all(not TOKEN_SHAPE.search(t) for t in logs.values()), f"{name}: a token shape in .l4-out/logs/"
        memory = [ln.strip() for ln in log.splitlines() if re.search(r"(?i)max(imum)? resident|peak (rss|memory)", ln)]
        peaks[name] = memory[:3]
    record("5", peak_memory_lines=peaks)  # for the operator's README: the lines, never an assertion on their size
