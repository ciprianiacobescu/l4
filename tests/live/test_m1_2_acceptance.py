"""The live exit protocol of M1.2 (docs/plan/m12-plan.md, "Live exit protocol on example-group/dummy-agentic through
l4-runner") as code (gap G20): one test per step, reading pipelines, jobs, merge requests, branches, commits and
files through the read-only API, matching the console lines of the job logs by pattern, and reading the `outcome.json`
artefacts.

It writes nothing to the repository. The operator runs it after each protocol step; a test whose step has not happened
yet SKIPS (the thing it looks for is not there), a test whose step happened and went wrong FAILS. Every id it meets goes
into the JSON file named by `L4_LIVE_RECORD` (default `/tmp/l4_m1_2_ids.json`), for `docs/live/README.md`.

    L4_LIVE=1 uv run pytest tests/live/test_m1_2_acceptance.py -m live -q -rs

The steps are told apart by the title of the commit the operator pushes (the plan names the first two):
- step 1: `M1.2: harness <sha>, fallback profiles, seed add-money-format`
- step 3: `M1.2: reserve on codex, Kiro in the chain, Q9 judges; seed add-split-amount`
- step 5 (optional): `M1.2: exit 12, seed add-percent-of`
- step 6: `M1.2: cleanup`
Steps 2, 4 and 6 also run `l4 probe --json` on the runner as `gitlab-runner` (through `scripts/runner/mk-ssh.sh`); the
API cannot see that, so the operator saves each output and names the file: `L4_LIVE_PROBE_2`, `L4_LIVE_PROBE_4`,
`L4_LIVE_PROBE_6` (the `--no-cache codex` run, then `L4_LIVE_PROBE_6B` for the final `l4 probe --json`).

Access: `MINTKEY_AUTH` (or `~/.claude.json`) for the Mintkey proxy, or `L4_LIVE_API_URL` + `L4_LIVE_TOKEN`.
"""

import json
import os
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from .gitlab_client import LiveGitLab, LiveUnavailable
from .protocol_m12 import (
    fallback_number,
    independence_line,
    selected_line,
    selections,
    skipped_line,
    trailer_values,
    unit_implementer_commits,
)

pytestmark = pytest.mark.live

MONEY, SPLIT, PERCENT = "add-money-format", "add-split-amount", "add-percent-of"
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
RECORD: dict[str, Any] = {}
STEP1, STEP3, STEP5, STEP6 = "M1.2: harness", "M1.2: reserve on codex", "M1.2: exit 12", "M1.2: cleanup"


def record(step: str, **ids: Any) -> None:
    RECORD.setdefault(step, {}).update(ids)


@pytest.fixture(scope="module", autouse=True)
def write_record() -> Iterator[None]:
    yield
    path = Path(os.environ.get("L4_LIVE_RECORD", "/tmp/l4_m1_2_ids.json"))
    path.write_text(json.dumps(RECORD, indent=2, sort_keys=True) + "\n", encoding="utf-8")


@pytest.fixture(scope="module")
def gl() -> LiveGitLab:
    try:
        return LiveGitLab()
    except LiveUnavailable as exc:
        pytest.skip(str(exc))


# --- reading helpers ----------------------------------------------------------------------------------------------


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


def step_run(gl: LiveGitLab, title: str) -> tuple[dict[str, Any], dict[str, Any], str, dict[str, Any]]:
    """(commit, pipeline, trace, job) of the pipeline a protocol step started; skips when it has not run yet."""
    commit = find_commit(gl, "main", title)
    if commit is None:
        pytest.skip(f"the commit `{title} …` is not on main yet")
    pipeline = finished_pipeline(gl, commit["id"])
    job = l4_job(gl, pipeline)
    return commit, pipeline, ANSI.sub("", gl.trace(job["id"])), job


def unit_mr(gl: LiveGitLab, name: str) -> dict[str, Any] | None:
    found = gl.merge_requests(state="all", source_branch=f"l4/openspec/{name}")
    return max(found, key=lambda m: m["iid"]) if found else None


def branch_events(gl: LiveGitLab, name: str, ref: str) -> list[dict[str, Any]]:
    events = []
    for path in gl.tree(f"openspec/changes/{name}/.l4/ledger", ref):
        if path.endswith(".jsonl"):
            events += [json.loads(line) for line in (gl.file(path, ref) or "").splitlines() if line.strip()]
    return sorted(events, key=lambda e: (e["ts"], e["run_id"], e["seq"]))


def implementer_commits(gl: LiveGitLab, name: str) -> list[dict[str, Any]]:
    """The red and green commits of the unit itself (the harness' checkpoints carry `L4-Task` and `L4-Unit`)."""
    return unit_implementer_commits(gl.commits(f"l4/openspec/{name}", 100), f"openspec:{name}")


def outcome_unit(gl: LiveGitLab, job: dict[str, Any], name: str) -> dict[str, Any]:
    texts = gl.artifact_texts(job["id"])
    key = next((k for k in texts if k.endswith("outcome.json")), None)
    assert key is not None, f"job {job['id']} has no outcome.json artefact"
    units = [u for u in json.loads(texts[key])["units"] if u["unit"] == f"openspec:{name}"]
    assert units, f"outcome.json names no unit openspec:{name}"
    return units[0]


def operator_probe(variable: str) -> dict[str, Any]:
    path = os.environ.get(variable)
    if not path or not Path(path).is_file():
        pytest.skip(f"set {variable} to the saved `l4 probe --json` output of this step")
    return json.loads(Path(path).read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def probe_row(doc: dict[str, Any], profile: str) -> dict[str, Any]:
    rows = [r for r in doc.get("profiles", []) if r.get("profile") == profile]
    assert rows, f"`l4 probe --json` lists no profile {profile}"
    return rows[0]


def ready_mr(gl: LiveGitLab, name: str) -> dict[str, Any]:
    mr = unit_mr(gl, name)
    assert mr is not None, f"{name} has no merge request"
    assert mr["title"].startswith(f"[l4] {name}") and not mr.get("draft"), mr["title"]
    assert "l4:in_review" in set(mr.get("labels", [])), mr.get("labels")
    return mr


# --- step 1: P1, codex implements and the judge falls back ---------------------------------------------------------


def test_step1_codex_implements_and_the_judge_falls_back_to_the_declared_opencode_profile(gl):
    commit, pipeline, log, job = step_run(gl, STEP1)
    record("1", commit=commit["id"], pipeline=pipeline["id"], job=job["id"])
    assert job["status"] == "success", job["status"]
    # implementer: codex, no fallback
    line = selected_line(log, "implementer", "codex")
    assert line is not None and fallback_number(line) is None, line
    # judges: claude-judge (auth: api_key) skipped at the auth step (no ANTHROPIC_API_KEY on the runner, L4-PRV-024),
    # opencode-free is fallback #1
    skipped = skipped_line(log, "judges", "claude-judge")
    assert skipped is not None and re.search(r"auth: ANTHROPIC_API_KEY is not set", skipped), skipped
    assert "auth: auth:" not in skipped, skipped
    judge = selected_line(log, "judges", "opencode-free")
    assert judge is not None and fallback_number(judge) == 1, judge
    branch = f"l4/openspec/{MONEY}"
    events = branch_events(gl, MONEY, branch)
    (implementer,) = selections(events, "implementer")
    assert implementer["selected"] == "codex" and "fallback_from" not in implementer
    (chosen,) = selections(events, "judges")
    assert (chosen["selected"], chosen["fallback_index"], chosen["fallback_from"]) == (
        "opencode-free",
        1,
        "claude-judge",
    )
    assert any(e["type"] == "availability.model_unverified" and e["profile"] == "opencode-free" for e in events)
    assert not [e for e in events if e["type"] == "availability.cooldown"]
    commits = implementer_commits(gl, MONEY)
    assert commits, "the unit branch has no red or green commit"
    for c in commits:
        assert trailer_values(c["message"], "L4-Agent")[0].startswith("codex"), c["message"]
        assert trailer_values(c["message"], "L4-Fallback-From") == [], c["message"]
    verification = gl.file(f"openspec/changes/{MONEY}/verification.md", branch) or ""
    assert "PASS" in verification.splitlines()[0] and "- Judge: opencode-free" in verification
    line = independence_line(verification) or ""
    assert line.startswith("independence: declared (unverified)"), line
    assert "opencode-free zhipu (declared)" in line and "codex openai (tool)" in line, line
    mr = ready_mr(gl, MONEY)
    record("1", mr=mr["iid"])


# --- step 2: a read-only probe of claude-code, by the operator ------------------------------------------------------


def test_step2_probing_claude_code_shows_windows_and_leaves_no_cooldown():
    doc = operator_probe("L4_LIVE_PROBE_2")
    row = probe_row(doc, "claude-code")
    assert row["status"] == "ok", row
    assert not doc.get("cooldowns"), doc.get("cooldowns")
    quota = next(step for step in row["steps"] if step["step"] == "quota")
    assert quota["skipped"] or quota["detail"].get("windows"), quota
    for window in quota["detail"].get("windows", []):
        assert float(window["used_percent"]) <= 90, f"claude-code has < 10% left in {window['name']}: wait (step 2)"


# --- step 3: P2, codex is forced exhausted and the implementer falls back --------------------------------------------


def test_step3_the_implementer_falls_back_past_codex_and_kiro_to_opencode_free(gl, capsys):
    commit, pipeline, log, job = step_run(gl, STEP3)
    record("3", commit=commit["id"], pipeline=pipeline["id"], job=job["id"])
    assert job["status"] == "success", job["status"]
    codex = skipped_line(log, "implementer", "codex") or ""
    assert re.search(r"quota: \S+ window \d+(\.\d+)?% used, \d+(\.\d+)?% remaining", codex), codex
    assert "< 100%" in codex and "(profile reserve)" in codex and "cool-down recorded" in codex, codex
    kiro = skipped_line(log, "implementer", "kiro") or ""
    assert kiro.endswith("auth: kiro-cli installed, not authenticated"), kiro
    chosen_line = selected_line(log, "implementer", "opencode-free")
    assert chosen_line is not None and fallback_number(chosen_line) == 2, chosen_line
    judge = selected_line(log, "judges", "claude-code")
    assert judge is not None and fallback_number(judge) is None, judge
    branch = f"l4/openspec/{SPLIT}"
    events = branch_events(gl, SPLIT, branch)
    (implementer,) = selections(events, "implementer")
    assert (implementer["selected"], implementer["fallback_index"], implementer["fallback_from"]) == (
        "opencode-free",
        2,
        "codex",
    )
    assert {(s["profile"], s["step"]) for s in implementer["skipped"]} == {("codex", "quota"), ("kiro", "auth")}
    cooldowns = [e for e in events if e["type"] == "availability.cooldown" and e["profile"] == "codex"]
    assert cooldowns and cooldowns[0]["kind"] == "usage_limit" and cooldowns[0]["source"] == "codex.rateLimits"
    started = [e for e in events if e["type"] == "step.started"]
    assert started and all(e["agent"] == "opencode-free" for e in started), "codex ran an agent step in P2"
    commits = implementer_commits(gl, SPLIT)
    assert commits
    for c in commits:
        assert trailer_values(c["message"], "L4-Agent")[0] == "opencode-free/opencode/big-pickle", c["message"]
        assert trailer_values(c["message"], "L4-Fallback-From") == ["codex"], c["message"]
    verification = gl.file(f"openspec/changes/{SPLIT}/verification.md", branch) or ""
    line = independence_line(verification) or ""
    assert line.startswith("independence: declared (unverified)"), line
    assert "opencode-free zhipu (declared)" in line and re.search(r"claude-code anthropic \(served claude-", line), line
    mr = ready_mr(gl, SPLIT)
    unit = outcome_unit(gl, job, SPLIT)
    assert unit["profiles"]["implementer"] == "opencode-free" and unit["profiles"]["fallback_from"] == "codex", unit
    record("3", mr=mr["iid"])


# --- step 4: probing again, by the operator ------------------------------------------------------------------------


def test_step4_the_probe_after_p2_shows_codex_cooling_and_kiro_logged_out():
    doc = operator_probe("L4_LIVE_PROBE_4")
    codex = probe_row(doc, "codex")
    assert codex["status"] == "cooling" and codex["cooling_until"], codex
    assert any(c["profile"] == "codex" and c["kind"] == "usage_limit" for c in doc["cooldowns"]), doc["cooldowns"]
    kiro = probe_row(doc, "kiro")
    assert kiro["status"] == "failed" and "not authenticated" in (kiro["reason"] or ""), kiro
    assert probe_row(doc, "claude-judge")["status"] == "failed", "claude-judge must stop at the binary step"
    for name in ("opencode-free", "claude-code"):
        assert probe_row(doc, name)["status"] == "ok", name


# --- step 5 (optional): exit 12 ------------------------------------------------------------------------------------


def test_step5_with_every_profile_cooling_the_job_exits_12_and_nothing_is_pushed(gl):
    commit, pipeline, log, job = step_run(gl, STEP5)
    record("5", commit=commit["id"], pipeline=pipeline["id"], job=job["id"])
    assert job["allow_failure"] is True, job
    skipped = skipped_line(log, "implementer", "codex") or ""
    assert "cooling until" in skipped and "(usage_limit); no probe sent" in skipped, skipped
    unit = outcome_unit(gl, job, PERCENT)
    assert unit["phase_after"] == "waiting_capacity" and unit["retry_after"], unit
    assert gl.get(f"/repository/branches/{'l4%2Fopenspec%2F' + PERCENT}") is None, "a branch was pushed"
    assert unit_mr(gl, PERCENT) is None, "a merge request was opened"


# --- step 6: cleanup, then the re-probe that clears the cool-down ---------------------------------------------------


def test_step6_after_the_cleanup_the_plan_is_empty(gl):
    commit, pipeline, log, job = step_run(gl, STEP6)
    record("6", commit=commit["id"], pipeline=pipeline["id"], job=job["id"])
    assert job["status"] == "success", job["status"]
    assert "nothing to do" in log, "the cleanup pipeline still has an actionable unit"


def test_step6_probing_codex_without_the_cache_clears_its_cooldown():
    again = probe_row(operator_probe("L4_LIVE_PROBE_6"), "codex")
    assert again["status"] == "ok" and again["cooldown_cleared"] is True, again
    final = operator_probe("L4_LIVE_PROBE_6B")
    assert not final.get("cooldowns"), final.get("cooldowns")
