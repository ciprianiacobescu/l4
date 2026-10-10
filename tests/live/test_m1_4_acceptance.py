"""The live exit protocol of M1.4 (docs/plan/m14-plan.md, "LIVE exit protocol on example-group/dummy-agentic through
l4-runner", gap M14-G7) as code: one test per step, reading pipelines, jobs, job artifacts, merge requests,
labels, branches, `git ls-remote` and file blobs through the read-only API.

It writes nothing to the repository. The operator runs it after each protocol step; a test whose step has not happened
yet SKIPS (the thing it looks for is not there), a test whose step happened and went wrong FAILS. Every id it meets goes
into the JSON file named by `L4_LIVE_RECORD` (default `/tmp/l4_m1_4_ids.json`), for `docs/live/README.md`.

    L4_LIVE=1 uv run pytest tests/live/test_m1_4_acceptance.py -m live -q -rs

Access is the one of `test_m1_1_acceptance.py` (`gitlab_client.py`): the Mintkey proxy, or `L4_LIVE_API_URL` +
`L4_LIVE_TOKEN`; the refs are read with `L4_FORGE_TOKEN`, `L4_LIVE_GIT_TOKEN_ENV`, or the operator's git credentials.
Steps 0 (local simulation) and 5/6 (optional, human, GitHub) are not live reads and have no test here.
"""

import json
import os
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from l4.vcs.errors import GitError

from .gitlab_client import LiveGitLab, LiveRemote, LiveUnavailable
from .protocol_m14 import command_output, created_before, plan_rows

pytestmark = pytest.mark.live

UNIT = "kiro:add-loyalty-points"
NAME = "add-loyalty-points"
BRANCH = f"l4/kiro/{NAME}"
PROBE_BRANCH = "probe/m14"
SPEC_DIR = f".kiro/specs/{NAME}"
C1_SUBJECT = "M1.4: upgrade the harness"
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
TOKEN_SHAPE = re.compile(r"glpat-|glptt-|gldt-|password=")
RECORD: dict[str, Any] = {}


def record(step: str, **ids: Any) -> None:
    RECORD.setdefault(step, {}).update(ids)


@pytest.fixture(scope="module", autouse=True)
def write_record() -> Iterator[None]:
    yield
    path = Path(os.environ.get("L4_LIVE_RECORD", "/tmp/l4_m1_4_ids.json"))
    path.write_text(json.dumps(RECORD, indent=2, sort_keys=True) + "\n", encoding="utf-8")


@pytest.fixture(scope="module")
def gl() -> LiveGitLab:
    try:
        return LiveGitLab()
    except LiveUnavailable as exc:
        pytest.skip(str(exc))


@pytest.fixture(scope="module")
def remote(gl: LiveGitLab) -> Iterator[LiveRemote]:
    found = LiveRemote(gl.repo_url())
    yield found
    found.close()


# --- reading helpers ----------------------------------------------------------------------------------------------


def finished_job(gl: LiveGitLab, sha: str, name: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """(pipeline, the one job called `name`) of the pipeline of `sha`; skips while there is none or it still runs."""
    pipeline = gl.pipeline_of(sha)
    if pipeline is None:
        pytest.skip(f"no pipeline for {sha[:12]} (yet)")
    if pipeline["status"] in ("created", "pending", "running", "waiting_for_resource", "preparing"):
        pytest.skip(f"pipeline {pipeline['id']} is still {pipeline['status']}")
    jobs = [j for j in gl.jobs(pipeline["id"]) if j["name"] == name]
    assert len(jobs) == 1, f"pipeline {pipeline['id']}: expected exactly one `{name}` job, found {len(jobs)}"
    return pipeline, jobs[0]


def trace(gl: LiveGitLab, job: dict[str, Any]) -> str:
    return ANSI.sub("", gl.trace(job["id"]))


def probe_artifacts(gl: LiveGitLab) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    """P1 (step 2): the pipeline and job `m14-probe` on the head of `probe/m14`, and `.l4-out/probe/*` by file name."""
    branch = gl.get(f"/repository/branches/{PROBE_BRANCH.replace('/', '%2F')}")
    if not branch:
        pytest.skip(f"{PROBE_BRANCH} does not exist (step 2 not done, or already deleted)")
    pipeline, job = finished_job(gl, branch["commit"]["id"], "m14-probe")
    files = {
        Path(path).name: text
        for path, text in gl.artifact_texts(job["id"]).items()
        if path.startswith(".l4-out/probe/")
    }
    assert files, f"job {job['id']} left no .l4-out/probe/ artifacts"
    record("2", branch_head=branch["commit"]["id"], pipeline=pipeline["id"], job=job["id"])
    return pipeline, job, files


def p2(gl: LiveGitLab) -> tuple[dict[str, Any], dict[str, Any], str]:
    """P2 (step 3): the `l4` job of the pipeline of C1 on `main`, and its log."""
    c1 = next((c for c in gl.commits("main", 200) if c["title"].startswith(C1_SUBJECT)), None)
    if c1 is None:
        pytest.skip("C1 is not on main yet (step 3)")
    pipeline, job = finished_job(gl, c1["id"], "l4")
    record("3", c1=c1["id"], pipeline=pipeline["id"], job=job["id"], duration=job.get("duration"))
    return pipeline, job, trace(gl, job)


def branch_events(gl: LiveGitLab, ref: str = BRANCH) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for path in gl.tree(f"{SPEC_DIR}/.l4/ledger", ref):
        if path.endswith(".jsonl"):
            events += [json.loads(line) for line in (gl.file(path, ref) or "").splitlines() if line.strip()]
    return sorted(events, key=lambda e: (e["ts"], e["run_id"], e["seq"]))


def pending_events(remote: LiveRemote) -> list[dict[str, Any]]:
    ref = f"refs/l4/locks/kiro/{NAME}"
    try:
        present = remote.refs(ref)
    except GitError as exc:
        first = (str(exc).splitlines() or ["git failed"])[0]
        pytest.skip(f"cannot read {ref} with git ({first}); set L4_FORGE_TOKEN or L4_LIVE_GIT_TOKEN_ENV")
    assert ref in present, f"{ref} does not exist on the remote"
    return remote.pending_events(ref)


def unit_commits(gl: LiveGitLab) -> list[dict[str, Any]]:
    """The unit branch's commits above `main`, oldest first, with their full messages."""
    on_main = {c["id"] for c in gl.commits("main", 200)}
    found = [c for c in gl.commits(BRANCH, 200) if c["id"] not in on_main]
    return [gl.commit(c["id"]) or c for c in reversed(found)]


def trailer(message: str, key: str) -> str | None:
    found = re.search(rf"^{re.escape(key)}: (.+)$", message, re.MULTILINE)
    return found.group(1).strip() if found else None


# --- step 2: P1, the probe branch ---------------------------------------------------------------------------------


def test_probe_pipeline_changes_nothing_and_provisions(gl):
    _, job, files = probe_artifacts(gl)
    assert job["status"] == "success", job["status"]
    summary = files["summary.txt"]
    for step in ("dryrun", "simulate", "doctor-unit", "fix1", "fix2"):
        assert f"{step} exit 0" in summary, summary
    assert "plan exit 10" in summary, summary  # --detailed-exitcode: something is actionable
    assert "refs unchanged" in summary and "REFS CHANGED" not in summary
    assert "sudo never called" in summary and "SUDO CALLED" not in summary
    assert all(not TOKEN_SHAPE.search(text) for text in files.values()), "a token shape was written under .l4-out/"

    plan = json.loads(files["plan.out"])
    row = next(u for u in plan["units"] if u["unit"] == UNIT)
    assert row["next_action"] == "implement" and row["tasks"] == {"done": 0, "total": 4}  # optional 1.2 not counted
    # a count: only the Kiro unit is actionable
    assert "L4_UNITS_ACTIONABLE=1" in files["plan.env"] and "L4_EXIT=10" in files["plan.env"]

    simulated = json.loads(files["simulate.out"])
    assert {s["name"]: s["status"] for s in simulated["scenarios"]} == {"happy-openspec": "pass", "happy-kiro": "pass"}

    assert json.loads(files["doctor-unit.out"])["ok"] is True

    first, second = json.loads(files["fix1.out"])["fixes"], json.loads(files["fix2.out"])["fixes"]
    openspec = [a for a in first if a["tool"].startswith("openspec")]
    assert openspec and all(a["status"] == "applied" and "1.14.0" in a["message"] for a in openspec), openspec
    present = {a["tool"] for a in first if a["status"] == "already present"}
    assert {"uv", "claude", "codex"} <= present, present
    assert second and all(a["status"] == "already present" for a in second), second  # no action, so no download
    record("2", plan_exit=10, fix1_applied=True, fix2_applied=False)


def test_probe_dry_run_prints_the_first_step_without_touching_anything(gl):
    _, job, files = probe_artifacts(gl)
    out = files["dryrun.out"]
    log = out + files.get("dryrun.err", "")  # the job trace holds no l4 output: the probe redirects every step
    assert out.rstrip().splitlines()[-1] == "would exit 0"
    found = re.search(rf"{re.escape(UNIT)}\s+phase=\S+\s+next=implement\s+task=2\.1 \(red\)", out)
    assert found, f"no decision for {UNIT} task 2.1 red in the dry run"
    assert "codex" in out and "unknown" in out  # implementer profile, availability not probed
    prompt = next((t for p, t in gl.artifact_texts(job["id"]).items() if p.endswith("2.1-red.prompt.md")), "")
    assert "Req 1.1" in prompt, "the red prompt does not carry the Kiro criteria"
    assert "agent.session" not in log and "availability.selected" not in log
    record("2", dry_run_decision=found.group(0))


def p2_started_at(gl: LiveGitLab) -> str | None:
    """When P2's `l4` job started, or None while it has not: from then on the unit's MR and refs are P2's own."""
    c1 = next((c for c in gl.commits("main", 200) if c["title"].startswith(C1_SUBJECT)), None)
    pipeline = gl.pipeline_of(c1["id"]) if c1 else None
    jobs = [j for j in gl.jobs(pipeline["id"]) if j["name"] == "l4"] if pipeline else []
    return jobs[0].get("started_at") if jobs else None


def test_probe_branch_left_no_mr_and_no_unit_branch(gl, remote):
    _, _, files = probe_artifacts(gl)  # skips until P1 has run
    anchor = p2_started_at(gl)
    mrs = created_before(gl.merge_requests(state="all", source_branch=BRANCH), anchor)
    assert not mrs, "P1 opened a merge request for the Kiro unit"
    if anchor is not None:  # P2 has pushed the unit's branch and lock ref since: read what P1 itself saw at its end
        left = [ln for ln in files["refs-after.txt"].splitlines() if "/kiro/" in ln]
        assert not left, f"P1 left refs behind: {left}"
        return
    try:
        refs = remote.refs("refs/heads/l4/kiro/*")
    except GitError:
        pytest.skip("cannot read the remote's refs with git")
    assert refs == {}, f"P1 left refs behind: {sorted(refs)}"


# --- step 3: P2, the real run on main -----------------------------------------------------------------------------


def test_p2_doctor_fix_finds_everything_present(gl):
    _, job, log = p2(gl)
    assert job["status"] == "success", job["status"]
    assert "doctor --ci --fix" in log
    assert "already present" in log and not re.search(r"(?i)downloading|curl |fetching http", log), log[:2000]
    assert "PRV-001" in log or "claude-code ready" in log or "codex ready" in log


def test_p2_plan_sweep_lists_the_kiro_unit_and_nothing_else(gl):
    _, _, log = p2(gl)
    rows = plan_rows(command_output(log, ".l4/bin/l4 plan --sweep"))  # GitLab prefixes each log line with a timestamp
    assert re.search(r"\bimplement\b", rows.get(UNIT, "")), f"plan --sweep: no `implement` row for {UNIT}"
    others = [row for unit, row in rows.items() if unit.startswith("openspec:")]
    assert others, "plan --sweep printed no OpenSpec unit (the M1.1 units are on main)"
    assert all(re.search(r"\bnone\b", row) for row in others), others


def test_kiro_unit_runs_waves_and_hands_off(gl, remote):
    pipeline, job, log = p2(gl)
    assert job["status"] == "success", job["status"]
    events = branch_events(gl)
    assert events, f"no ledger under {SPEC_DIR}/.l4/ledger on {BRANCH}"
    pend = pending_events(remote)
    started = [e["task"] for e in events if e["type"] == "task.started"]
    assert started.index("2.1") < started.index("1.1"), f"waves not honoured: {started}"
    assert "1.2" not in started, "the optional task 1.2 was started"

    commits = unit_commits(gl)
    steps = [(trailer(c["message"], "L4-Task"), trailer(c["message"], "L4-TDD")) for c in commits]
    work = [s for s in steps if s[0]]
    assert work[:4] == [("2.1", "red"), ("2.1", "green"), ("1.1", "red"), ("1.1", "green")], work
    assert all("[skip ci]" in c["message"] for c in commits if trailer(c["message"], "L4-TDD"))

    base = next(c for c in gl.commits("main", 200) if c["id"] == commits[0]["parent_ids"][0])["id"]
    before, after = gl.file(f"{SPEC_DIR}/tasks.md", base) or "", gl.file(f"{SPEC_DIR}/tasks.md", BRANCH) or ""
    changed = [i for i, (a, b) in enumerate(zip(before, after, strict=False)) if a != b]
    assert len(before) == len(after) and len(changed) == 4, f"tasks.md changed {len(changed)} bytes, expected 4"
    assert "- [ ]* 1.2" in after, "the optional 1.2 marker changed"
    assert "- [x] 1. " in after and "- [x] 2. " in after, "a parent was not ticked"

    every = events + pend
    for e in (x for x in every if x["type"] == "step.started"):
        key = (e["task"], e["phase"], e["attempt"])
        assert any((f["task"], f["phase"], f["attempt"]) == key for f in every if f["type"] == "step.finished"), key

    assert any(e["type"] == "verify.step" and e.get("step") == "0" for e in every)
    assert any(e["type"] == "verify.verdict" and e["verdict"] == "PASS" for e in every)
    assert gl.file(f"{SPEC_DIR}/verification.md", BRANCH), "verification.md was not committed"

    head = commits[-1]
    assert "[skip ci]" not in head["message"], "the hand-off commit is skippable"
    mrs = gl.merge_requests(state="opened", source_branch=BRANCH)
    assert len(mrs) == 1 and mrs[0]["title"].startswith("[l4]") and not mrs[0].get("draft")
    assert "l4:in_review" in mrs[0]["labels"] and mrs[0]["sha"] == head["id"]
    push = gl.pipeline_of(head["id"])
    assert push is not None and {j["name"] for j in gl.jobs(push["id"])} >= {"test"}
    assert "l4" not in {j["name"] for j in gl.jobs(push["id"])}

    env = next((t for p, t in gl.artifact_texts(job["id"]).items() if p.endswith("l4.env")), "")
    assert "L4_EXIT=0" in env and "in_review" in env
    logs = {p: t for p, t in gl.artifact_texts(job["id"]).items() if p.startswith(".l4-out/logs/")}
    assert logs and all(not TOKEN_SHAPE.search(t) for t in logs.values())
    record("3", started=started, mr=mrs[0]["iid"], head=head["id"], l4_pipeline=pipeline["id"])


# --- step 4: P1's prediction equals P2's first step ---------------------------------------------------------------


def test_dry_run_decision_matches_the_real_first_step(gl, remote):
    _, _, files = probe_artifacts(gl)
    p2(gl)
    events = branch_events(gl) + pending_events(remote)
    first = next(
        e for e in sorted(events, key=lambda e: (e["ts"], e["run_id"], e["seq"])) if e["type"] == "step.started"
    )
    found = re.search(rf"{re.escape(UNIT)}\s+phase=\S+\s+next=implement\s+task=(\S+) \((\w+)\)", files["dryrun.out"])
    assert found, "the dry run printed no decision for the Kiro unit"
    assert (found.group(1), found.group(2)) == (first["task"], first["phase"])
    record("4", predicted=found.group(0), real=[first["task"], first["phase"]])
