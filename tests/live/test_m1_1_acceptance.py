"""The live exit protocol of M1.1 (docs/plan/implementation-map.md, "Live exit protocol on example-group/dummy-agentic")
as code (gap G13): one test per step, reading pipelines, jobs, merge requests, labels, notes, branches, refs and files
through the read-only API and `git ls-remote`.

It writes nothing to the repository. The operator runs it after each protocol step; a test whose step has not happened
yet SKIPS (the thing it looks for is not there), a test whose step happened and went wrong FAILS. Every id it meets goes
into the JSON file named by `L4_LIVE_RECORD` (default `/tmp/l4_m1_1_ids.json`), for `docs/live/README.md`.

    L4_LIVE=1 uv run pytest tests/live/test_m1_1_acceptance.py -m live -q -rs

Access: `MINTKEY_AUTH` (or `~/.claude.json`) for the Mintkey proxy, or `L4_LIVE_API_URL` + `L4_LIVE_TOKEN`. The lock
refs (the `*_lock_ref_*` tests, which alone skip when git cannot read them) are read with `L4_FORGE_TOKEN`, with the
variable named by `L4_LIVE_GIT_TOKEN_ENV` (a `read_repository` token), or else with the git credentials of the
operator's machine (see `gitlab_client.py`).
"""

import json
import os
import re
from collections.abc import Iterator
from itertools import islice
from pathlib import Path
from typing import Any

import pytest
import yaml

from l4.vcs.errors import GitError

from .gitlab_client import LiveGitLab, LiveRemote, LiveUnavailable
from .protocol import happened_after, started_by_a_lock_ref_push

pytestmark = pytest.mark.live

DISCOUNT, AVERAGE, VAT = "add-discount-codes", "add-average-price", "add-vat"
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
RECORD: dict[str, Any] = {}


def record(step: str, **ids: Any) -> None:
    RECORD.setdefault(step, {}).update(ids)


@pytest.fixture(scope="module", autouse=True)
def write_record() -> Iterator[None]:
    yield
    path = Path(os.environ.get("L4_LIVE_RECORD", "/tmp/l4_m1_1_ids.json"))
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


def lock_ref(name: str) -> str:
    return f"refs/l4/locks/openspec/{name}"


def pending(remote: LiveRemote, name: str) -> list[dict[str, Any]]:
    """The pending ledger of a unit's lock ref. Skips when git cannot reach the repository (no credentials); fails when
    it can and the ref is not there."""
    ref = lock_ref(name)
    try:
        present = remote.refs(ref)
    except GitError as exc:
        first = (str(exc).splitlines() or ["git failed"])[0]
        pytest.skip(f"cannot read {ref} with git ({first}); set L4_FORGE_TOKEN or L4_LIVE_GIT_TOKEN_ENV, or log git in")
    assert ref in present, f"{ref} does not exist on the remote"
    return remote.pending_events(ref)


def unit_mr(gl: LiveGitLab, name: str) -> dict[str, Any] | None:
    found = [m for m in gl.merge_requests(state="all", source_branch=f"l4/openspec/{name}")]
    return max(found, key=lambda m: m["iid"]) if found else None


def archive_mrs(gl: LiveGitLab, name: str) -> list[dict[str, Any]]:
    return gl.merge_requests(state="all", source_branch=f"l4/archive/openspec/{name}")


def find_commit(gl: LiveGitLab, ref: str, subject_prefix: str) -> dict[str, Any] | None:
    return next((c for c in gl.commits(ref, 200) if c["title"].startswith(subject_prefix)), None)


def finished_pipeline(gl: LiveGitLab, sha: str) -> dict[str, Any]:
    pipeline = gl.pipeline_of(sha)
    if pipeline is None:
        pytest.skip(f"no pipeline for {sha[:12]} (yet)")
    if pipeline["status"] in ("created", "pending", "running", "waiting_for_resource", "preparing"):
        pytest.skip(f"pipeline {pipeline['id']} is still {pipeline['status']}")
    return pipeline


def l4_job(gl: LiveGitLab, pipeline: dict[str, Any]) -> dict[str, Any]:
    jobs = [j for j in gl.jobs(pipeline["id"]) if j["name"] == "l4"]
    assert len(jobs) == 1, f"pipeline {pipeline['id']}: expected exactly one `l4` job, found {len(jobs)}"
    return jobs[0]


def trace(gl: LiveGitLab, job: dict[str, Any]) -> str:
    return ANSI.sub("", gl.trace(job["id"]))


def plan_row(text: str, unit: str) -> list[str] | None:
    """The `l4 plan` table row of a unit in a job log: [unit, phase, tasks, next, reason]."""
    for line in text.splitlines():
        if re.match(rf"^\s*openspec:{re.escape(unit)}\s", line):
            return re.split(r"\s{2,}", line.strip(), maxsplit=4)
    return None


def branch_events(gl: LiveGitLab, name: str, ref: str) -> list[dict[str, Any]]:
    events = []
    for path in gl.tree(f"openspec/changes/{name}/.l4/ledger", ref):
        if path.endswith(".jsonl"):
            events += [json.loads(line) for line in (gl.file(path, ref) or "").splitlines() if line.strip()]
    return sorted(events, key=lambda e: (e["ts"], e["run_id"], e["seq"]))


def labels(mr: dict[str, Any]) -> set[str]:
    return set(mr.get("labels", []))


def sticky(gl: LiveGitLab, iid: int) -> str | None:
    notes = [n for n in gl.notes(iid) if not n.get("system") and n["body"].startswith("<!-- l4:sticky -->")]
    return notes[0]["body"] if notes else None


def commit_message(gl: LiveGitLab, sha: str) -> str:
    return (gl.commit(sha) or {}).get("message", "")


def answer_prompt_seen(gl: LiveGitLab, job: dict[str, Any], who: str, qid: str = "Q-001") -> bool:
    needle = f'<l4:data kind="answer" id="{qid}" by="{who}">'
    return any(needle in text for text in gl.artifact_texts(job["id"]).values())


# --- step 0 and 1: the upgrade, then the idle pipeline on main -----------------------------------------------------


def test_step0_main_carries_the_upgraded_harness_and_the_clarifier_roles(gl):
    template = gl.file(".l4/ci/l4.gitlab-ci.yml", "main")
    if template is None or "timeout: 180m" not in template:
        pytest.skip("the upgrade (steps 0 and 1) is not on main yet")
    assert "plan --sweep" in template and "L4_UNIT" not in template
    config = yaml.safe_load(gl.file(".l4/config.yaml", "main") or "")
    commit = config["harness"]["commit"]
    assert gl.file(".l4/vendor/src/l4/_commit.py", "main") == f'COMMIT = "{commit}"\n'
    assert config["roles"]["clarifier"] == ["claude-code"] and config["roles"]["s1_judge"] == ["claude-code"]
    assert config["clarifier"]["s1_standin"] == "llm_boolean"
    record("0", harness_commit=commit)


def test_step1_the_idle_pipeline_on_main_has_one_job_that_does_nothing(gl):
    upgrade = find_commit(gl, "main", "Upgrade the vendored L4 harness")
    if upgrade is None:
        pytest.skip("the upgrade commit is not on main yet")
    pipeline = finished_pipeline(gl, upgrade["id"])
    job = l4_job(gl, pipeline)
    log = trace(gl, job)
    record("1", commit=upgrade["id"], pipeline=pipeline["id"], job=job["id"], duration=job.get("duration"))
    assert job["status"] == "success" and "agentic" in job["tag_list"], job["status"]
    assert "nothing to do" in log
    assert "LIVE-001" not in log and "availability.selected" not in log
    mr1 = gl.get("/merge_requests/1") or {}
    merged_at = mr1.get("merged_at")
    if not merged_at or merged_at > pipeline["created_at"]:  # !1 was still in review when P1 ran
        discount, vat = plan_row(log, DISCOUNT), plan_row(log, VAT)
        assert discount and discount[1] == "in_review" and discount[3] == "none", discount
        assert vat and vat[1] == "awaiting_human" and vat[3] == "none", vat
    assert (job.get("duration") or 0) < 600, f"the idle job took {job.get('duration')} s"


# --- step 2: a human merges MR !1 -----------------------------------------------------------------------------------


def archive_mr_paths(gl: LiveGitLab) -> tuple[dict[str, Any], set[str], list[dict[str, Any]]]:
    mr = archive_mrs(gl, DISCOUNT)[0]
    changes = (gl.get(f"/merge_requests/{mr['iid']}/changes") or {})["changes"]
    return mr, {c["new_path"] for c in changes} | {c["old_path"] for c in changes}, changes


def test_step2_merging_mr1_opens_one_archive_mr_that_only_moves_the_folder(gl):
    mr1 = gl.get("/merge_requests/1") or {}
    if mr1.get("state") != "merged":
        pytest.skip("MR !1 is not merged yet (step 2)")
    merge_sha = mr1["merge_commit_sha"]
    pipeline = finished_pipeline(gl, merge_sha)
    job = l4_job(gl, pipeline)
    log = trace(gl, job)
    assert job["status"] == "success", job["status"]
    assert "nothing to do" in log
    assert "\nL4-Run: " not in "\n" + commit_message(gl, merge_sha)  # a human's merge commit starts the job

    archives = archive_mrs(gl, DISCOUNT)
    assert len(archives) == 1, f"expected exactly one archive MR for {DISCOUNT}, found {len(archives)}"
    mr = archives[0]
    assert mr["title"] == f"[l4] archive {DISCOUNT}" and not mr.get("draft") and mr["target_branch"] == "main"
    changes = (gl.get(f"/merge_requests/{mr['iid']}/changes") or {})["changes"]
    moved = re.compile(rf"^openspec/changes/archive/\d{{4}}-\d{{2}}-\d{{2}}-{DISCOUNT}/")
    paths = {c["new_path"] for c in changes} | {c["old_path"] for c in changes}
    allowed_spec = "openspec/specs/discounts/spec.md"
    own = f"openspec/changes/{DISCOUNT}/"
    stray = sorted(p for p in paths if not p.startswith(own) and not moved.match(p) and p != allowed_spec)
    assert stray == [], f"the archive MR changes paths outside the move: {stray}"
    assert any(c["new_path"] == "openspec/specs/discounts/spec.md" and c["new_file"] for c in changes)
    assert any(moved.match(p) and "/.l4/ledger/" in p for p in paths) and any(
        moved.match(p) and p.endswith("/verification.md") for p in paths
    )
    head = gl.commit(mr["sha"]) or {}
    assert head["title"] == f"chore({DISCOUNT}): archive" and "[skip ci]" not in head["message"]
    assert "\nL4-Run: " in "\n" + head["message"] and "L4-Phase: archived" in head["message"]
    push = gl.pipeline_of(mr["sha"])
    assert push is not None, "the archive push started no pipeline: the project's own `test` job should have run"
    names = {j["name"] for j in gl.jobs(push["id"])}
    assert "test" in names and "l4" not in names, names

    record("2", merge_commit=merge_sha, pipeline=pipeline["id"], job=job["id"], archive_mr=mr["iid"],
           archive_sha=mr["sha"], archive_pipeline=push["id"])  # fmt: skip


def test_step2_lock_ref_holds_the_merge_and_is_folded_into_the_archived_ledger(gl, remote):
    if (gl.get("/merge_requests/1") or {}).get("state") != "merged" or len(archive_mrs(gl, DISCOUNT)) != 1:
        pytest.skip("MR !1 is not merged, or has no archive MR yet (step 2)")
    mr, paths, _ = archive_mr_paths(gl)
    events = pending(remote, DISCOUNT)
    merged = [e for e in events if e["type"] == "phase.changed" and e.get("to") == "merged"]
    assert merged and merged[0]["from"] == "in_review" and any(e["type"] == "archive.opened" for e in events)
    moved = re.compile(rf"^openspec/changes/archive/\d{{4}}-\d{{2}}-\d{{2}}-{DISCOUNT}/")
    archived_dir = next(m.group(0) for p in sorted(paths) if (m := moved.match(p))).rstrip("/")
    files = {Path(p).stem for p in gl.tree(f"{archived_dir}/.l4/ledger", mr["source_branch"])}
    assert {e["run_id"] for e in events} <= files, "the pending ledger is not folded into the archived ledger"


def test_step3_mr2_was_closed(gl):
    mr2 = gl.get("/merge_requests/2") or {}
    if mr2.get("state") in (None, "opened"):
        pytest.skip("step 3 is not done: MR !2 is still open")
    assert mr2["state"] == "closed", mr2["state"]
    record("3", mr2_state=mr2.get("state"))


# --- step 4: the two new units ------------------------------------------------------------------------------------


def seed_pipeline(gl: LiveGitLab) -> tuple[dict[str, Any], dict[str, Any], str]:
    seed = find_commit(gl, "main", "Seed add-average-price")
    if seed is None:
        pytest.skip("the seed commit is not on main yet (step 4)")
    pipeline = finished_pipeline(gl, seed["id"])
    job = l4_job(gl, pipeline)
    return pipeline, job, trace(gl, job)


def test_step4_p3_sweeps_without_a_second_archive_mr_and_runs_both_units_to_exit_11(gl):
    pipeline, job, log = seed_pipeline(gl)
    record("4", pipeline=pipeline["id"], job=job["id"])
    assert job["allow_failure"] is True and job["status"] in ("success", "failed"), job["status"]
    assert "l4 exit 11 (awaiting_human)" in log, "the job did not end with exit 11 mapped through `l4 ci map-exit`"
    assert len(archive_mrs(gl, DISCOUNT)) == 1
    if archive_mrs(gl, DISCOUNT)[0]["state"] == "opened":
        assert re.search(rf"{DISCOUNT}: archive MR !\d+ is open", log), "the sweep did not report the open archive MR"
    # the plan table the job printed before it ran anything
    for name in (AVERAGE, VAT):
        row = plan_row(log, name)
        assert row and row[3] == "implement", (name, row)


def test_step4a_add_average_price_is_clarified_by_the_llm_and_handed_off(gl):
    mr = unit_mr(gl, AVERAGE)
    if mr is None:
        pytest.skip("add-average-price has no MR yet")
    branch = f"l4/openspec/{AVERAGE}"
    assert not mr.get("draft") and labels(mr) & {"l4:in_review"}, labels(mr)
    assert not any(label.startswith("l4:") and label != "l4:in_review" for label in labels(mr)), labels(mr)
    assert mr["title"] == f"[l4] {AVERAGE}: average unit price"
    head = gl.commit(mr["sha"]) or {}
    assert head["title"] == f"docs({AVERAGE}): hand off to review" and "[skip ci]" not in head["message"]
    assert "\nL4-Run: " in "\n" + head["message"]
    questions = gl.file(f"openspec/changes/{AVERAGE}/questions.md", branch) or ""
    assert "answered-by-clarifier" in questions and "confidence: high" in questions and "kind: technical" in questions
    assert re.search(r"S1 p=0\.\d\d", questions) and "Decimal" in questions, "the suggestion does not answer Decimal"
    events = branch_events(gl, AVERAGE, branch)
    results = [e for e in events if e["type"] == "clarifier.result"]
    assert results and results[0]["auto_accepted"] is True and results[0].get("citation_support") is not None, results
    assert any(e["type"] == "question.answered" and e.get("by") == "clarifier" for e in events)
    phases = [e["to"] for e in events if e["type"] == "phase.changed"]
    assert any(a == "clarifying" and b == "implementing" for a, b in zip(phases, phases[1:], strict=False)), phases
    assert "in_review" not in phases, "the branch carries a ledger line after the hand-off commit H"
    pipeline, job, log = seed_pipeline(gl)
    assert answer_prompt_seen(gl, job, "clarifier"), "no red prompt artefact carries the clarifier's answer"
    assert re.search(rf"openspec:{AVERAGE}\s+in_review", log), "the after_script `l4 status` does not say in_review"
    h_pipeline = gl.pipeline_of(mr["sha"])
    assert h_pipeline and {j["name"] for j in gl.jobs(h_pipeline["id"])} >= {"test"}
    assert "l4" not in {j["name"] for j in gl.jobs(h_pipeline["id"])}
    record("4a", mr=mr["iid"], head=mr["sha"], h_pipeline=h_pipeline["id"], lock_ref=lock_ref(AVERAGE))


def test_step4a_lock_ref_carries_the_hand_off_tail(gl, remote):
    mr = unit_mr(gl, AVERAGE)
    if mr is None:
        pytest.skip("add-average-price has no MR yet")
    head = gl.commit(mr["sha"]) or {}
    events = pending(remote, AVERAGE)
    tail = [e["type"] for e in events if e["run_id"] == head["message"].split("L4-Run: ")[1].split()[0]][-3:]
    assert tail == ["phase.changed", "lock.released", "run.finished"], tail
    assert "in_review" in [e["to"] for e in events if e["type"] == "phase.changed"]  # later steps add `merged`


def first_unit_commit(gl: LiveGitLab, branch: str) -> dict[str, Any]:
    compare = gl.get("/repository/compare", **{"from": "main", "to": branch}) or {}
    commits = compare.get("commits") or []
    ids = {c["id"] for c in commits}
    return next(c for c in commits if not set(c["parent_ids"]) & ids)


def test_step4b_add_vat_gets_the_lint_question_and_waits_for_a_human(gl):
    seed = find_commit(gl, "main", "Seed add-average-price")
    mr = unit_mr(gl, VAT)
    if seed is None or mr is None or mr["state"] == "closed":
        pytest.skip("the seed commit is not on main, or add-vat has no new MR yet (step 4)")
    if not happened_after(mr["created_at"], seed["created_at"]):
        pytest.skip(f"MR !{mr['iid']} of add-vat is older than the seed commit: it is M0's, not step 4's")
    branch = f"l4/openspec/{VAT}"
    first = first_unit_commit(gl, branch)
    assert first["title"].startswith(f"docs({VAT}): questions"), first["title"]
    questions = gl.file(f"openspec/changes/{VAT}/questions.md", first["id"]) or ""
    for needle in ("intake lint (L4-ODD-004)", "ambiguous", "Romanian customer", "119.00", "121.00", "1.1", "1.2"):
        assert needle in questions, needle
    files = sorted(gl.tree(f"openspec/changes/{VAT}/.l4/ledger", branch))
    earliest = [json.loads(line) for line in (gl.file(files[0], branch) or "").splitlines()]
    kinds = [e["type"] for e in earliest]
    assert "agent.session" not in kinds and "task.started" not in kinds, "an agent ran before the intake lint question"
    results = [e for e in earliest if e["type"] == "clarifier.result"]
    assert results and results[0]["auto_accepted"] is False and "ambiguous" in " ".join(results[0]["reasons"])
    phases = [e["to"] for e in earliest if e["type"] == "phase.changed"]
    assert "clarifying" in phases and phases[-1] == "awaiting_human", phases
    record("4b", mr=mr["iid"], first_commit=first["id"], ledger=files[0])
    if "l4:in_review" in labels(mr):
        pytest.skip("step 6 is done: the awaiting-human state of add-vat is gone (the history above was checked)")
    assert labels(mr) >= {"l4:awaiting_human", "l4:needs-answers"} and mr.get("draft"), labels(mr)
    note = sticky(gl, mr["iid"]) or ""
    assert "Q-001" in note and "questions.md" in note and f"l4/openspec/{VAT}" in note, note


# --- step 5: loop safety, read-only over the pipelines since step 4 -----------------------------------------------


def test_step5_no_pipeline_loops(gl):
    heads = []
    for ref in ("main", f"l4/openspec/{AVERAGE}", f"l4/openspec/{VAT}", f"l4/archive/openspec/{DISCOUNT}"):
        heads += [(ref, c) for c in gl.commits(ref, 60)]
    if not any(r.startswith("l4/") for r, _ in heads):
        pytest.skip("no unit branch yet")
    seen: set[str] = set()
    for ref, commit in heads:
        if commit["id"] in seen:
            continue
        seen.add(commit["id"])
        message = commit["message"]
        pipeline = gl.pipeline_of(commit["id"])
        if "[skip ci]" in message:
            assert pipeline is None or pipeline["status"] == "skipped", (ref, commit["id"][:12], pipeline)
        elif "\nL4-Run: " in "\n" + message and pipeline is not None:
            names = {j["name"] for j in gl.jobs(pipeline["id"])}
            assert "l4" not in names, f"an `l4` job ran on the harness' own commit {commit['id'][:12]} ({ref})"
    recent = list(islice(gl.pages("/pipelines", order_by="id", sort="desc"), 200))
    assert not any(started_by_a_lock_ref_push(p) for p in recent), "a lock-ref push started a pipeline"
    for p in recent:
        if p["source"] == "merge_request_event":  # a `[skip ci]` push to an MR branch makes a skipped one
            assert p["status"] == "skipped" or "l4" not in {j["name"] for j in gl.jobs(p["id"])}, (
                f"merge request pipeline {p['id']} ran an `l4` job"
            )
    for p in recent:  # no `l4` job on a commit that carries an L4-Run trailer (U-3, the rule that stops the loop)
        if "\nL4-Run: " in "\n" + commit_message(gl, p["sha"]) and p["source"] == "push":
            assert "l4" not in {j["name"] for j in gl.jobs(p["id"])}, f"pipeline {p['id']} ran `l4` on a harness commit"
    record("5", commits_checked=len(seen))


# --- step 6: the human answers add-vat -----------------------------------------------------------------------------


def test_step6_the_answer_resumes_add_vat_to_a_ready_mr(gl):
    branch = f"l4/openspec/{VAT}"
    answer = find_commit(gl, branch, "Answer Q-001")
    if answer is None:
        pytest.skip("the human answer is not on the add-vat branch yet (step 6)")
    pipeline = finished_pipeline(gl, answer["id"])
    job = l4_job(gl, pipeline)
    log = trace(gl, job)
    record("6", answer_commit=answer["id"], pipeline=pipeline["id"], job=job["id"])
    assert job["status"] == "success", job["status"]
    # the template prints this after the checkout; GitLab echoes the script line itself either way
    marker = re.findall(r"^l4: base checkout ([0-9a-f]{40})\s*$", log, re.MULTILINE)
    assert len(marker) == 1, "the default branch was not checked out before the shim ran"
    assert marker[0] != answer["id"], "the job ran the pushed branch's own head"
    assert marker[0] in {c["id"] for c in gl.commits("main", 60)}, "the checked-out commit is not on the default branch"
    row = plan_row(log, VAT)
    assert row and row[3] == "implement" and "answers submitted: Q-001" in row[4], row
    events = branch_events(gl, VAT, branch)
    assert any(e["type"] == "question.answered" and e.get("by") == "human" for e in events)
    resumed = [e for e in events if e["type"] == "phase.changed" and e["from"] == "awaiting_human"]
    assert any(e["to"] == "implementing" for e in resumed)
    assert answer_prompt_seen(gl, job, "human"), "no red prompt artefact carries the human's answer"
    mr = unit_mr(gl, VAT)
    assert mr is not None and mr["state"] == "opened" and not mr.get("draft")
    assert mr["title"] == f"[l4] {VAT}: VAT on the cart total"
    assert "l4:in_review" in labels(mr) and "l4:needs-answers" not in labels(mr), labels(mr)
    assert "Nothing is waiting for a human answer." in (sticky(gl, mr["iid"]) or "")
    head = gl.commit(mr["sha"]) or {}
    assert head["title"] == f"docs({VAT}): hand off to review" and "[skip ci]" not in head["message"]
    assert [e for e in events if e["type"] == "phase.changed"][-1]["to"] == "verified"  # the branch stops at H
    record("6", mr=mr["iid"], head=mr["sha"], lock_ref=lock_ref(VAT))


def test_step6_lock_ref_carries_in_review(gl, remote):
    if find_commit(gl, f"l4/openspec/{VAT}", "Answer Q-001") is None:
        pytest.skip("the human answer is not on the add-vat branch yet (step 6)")
    assert "in_review" in [e["to"] for e in pending(remote, VAT) if e["type"] == "phase.changed"]


# --- step 7: web and api pipelines on main -------------------------------------------------------------------------


@pytest.mark.parametrize("source", ["web", "api"])
def test_step7_a_manual_pipeline_is_idle_and_cheap(gl, source):
    seed = find_commit(gl, "main", "Seed add-average-price")
    if seed is None:
        pytest.skip("the seed commit is not on main yet: no pipeline of step 7 can exist")
    found = [  # M0's own manual pipelines on main are older than the seed
        p for p in gl.pages("/pipelines", ref="main", source=source, order_by="id", sort="desc")
        if happened_after(p["created_at"], seed["created_at"])
    ]  # fmt: skip
    if not found:
        pytest.skip(f"no `{source}` pipeline on main since the seed commit yet (step 7)")
    pipeline = found[0]
    if pipeline["status"] in ("created", "pending", "running", "waiting_for_resource", "preparing"):
        pytest.skip(f"pipeline {pipeline['id']} is still {pipeline['status']}")
    job = l4_job(gl, pipeline)
    log = trace(gl, job)
    record(f"7-{source}", pipeline=pipeline["id"], job=job["id"], duration=job.get("duration"))
    assert job["status"] == "success", job["status"]
    assert "nothing to do" in log and "availability.selected" not in log
    rows = [plan_row(log, n) for n in (DISCOUNT, AVERAGE, VAT)]
    assert all(r is None or r[3] == "none" for r in rows), rows
    assert len(archive_mrs(gl, DISCOUNT)) == 1, "a second archive MR was opened"
    assert (job.get("duration") or 0) < 300, f"the idle job took {job.get('duration')} s"


# --- step 8 (optional) ------------------------------------------------------------------------------------------


def test_step8_after_the_archive_mr_merges_the_unit_is_gone_from_the_plan(gl):
    archives = archive_mrs(gl, DISCOUNT)
    if not archives or archives[0]["state"] != "merged":
        pytest.skip("the archive MR is not merged (optional step 8)")
    merge_sha = archives[0]["merge_commit_sha"]
    pipeline = finished_pipeline(gl, merge_sha)
    job = l4_job(gl, pipeline)
    assert job["status"] == "success" and plan_row(trace(gl, job), DISCOUNT) is None
    assert gl.file(f"openspec/changes/{DISCOUNT}/proposal.md", "main") is None
    record("8", archive_merge_commit=merge_sha, pipeline=pipeline["id"])
