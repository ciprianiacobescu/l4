"""`l4 run` tells the job log what happened: one `[l4] <unit> ...` line per ledger event, on stderr."""

import re

from ..verifier.conftest import valid_spec  # noqa: F401
from ..verifier.test_ladder import IMPLEMENT, judge_step
from .conftest import BRANCH, TOKEN, green_step, red_step  # noqa: F401

UNIT_ID = "openspec:add-discount-codes"
EXPECTED_IN_ORDER = [
    r"^\[l4\] \S+ run r-\S+ started \(iteration \d+, harness \S+\)$",
    r"phase none → intake \(unit_discovered_pending\)$",
    r"implementer: impl ok \(.*\) → selected$",
    r"task 1\.1 started: ",
    r"agent red task 1\.1 ok \(",
    r"red: 2 new tests fail, as intended$",  # the raw red gate line is at DEBUG (run-liveness D9)
    r"task 1\.1 red ok: \d+ new test\(s\) failing as expected$",
    r"MR \S+ \(draft\)$",
    r"agent green task 1\.1 ok \(",
    r"gate test pass \(exit 0, 4 tests: 4 passed, 0 failed\)$",
    r"task 1\.1 green ok: all tests passing$",
    r"verdict PASS \(round 1, \d+/\d+ criteria pass, 0 finding\(s\)\)$",
    r"MR \S+ marked ready for review$",
    r"run finished: exit 0 in [\d.]+s",
    r"^\[l4\] artefacts: /.+/\.l4-out/agent/r-\S+/, /.+/\.l4-out/gates/r-\S+/ \(CI: job artifacts\)$",
]


def trace(stderr: str) -> list[str]:
    return [line for line in stderr.splitlines() if line.startswith("[l4]")]


def test_the_run_prints_its_story_in_order(run_l4, forge_env, use_fake_gitlab, valid_spec, capsys):  # noqa: F811
    run = run_l4([*IMPLEMENT, judge_step()])
    assert run.code == 0
    lines = trace(capsys.readouterr().err)
    cursor = 0
    for pattern in EXPECTED_IN_ORDER:
        found = next((i for i in range(cursor, len(lines)) if re.search(pattern, lines[i])), None)
        assert found is not None, f"no line matching {pattern!r} after position {cursor} in:\n" + "\n".join(lines)
        cursor = found + 1
    print("\n".join(lines))  # shown with `pytest -s`


def test_quiet_silences_the_trace(run_l4, forge_env, use_fake_gitlab, valid_spec, capsys):  # noqa: F811
    run = run_l4([*IMPLEMENT, judge_step()], "-q")
    assert run.code == 0
    err = capsys.readouterr().err
    assert UNIT_ID not in err and "artefacts:" not in err  # only warnings (the sandbox notice) get through -q


def test_verbose_adds_the_detail_lines(run_l4, forge_env, use_fake_gitlab, valid_spec, capsys):  # noqa: F811
    run_l4([*IMPLEMENT, judge_step()], "-v")
    err = capsys.readouterr().err
    assert "agent red step started" in err and "verify round 1 step" in err and "lock acquired" in err


def test_every_commit_and_push_is_a_line_with_its_sha_and_the_summary_links_the_diff(
    run_l4,
    forge_env,
    use_fake_gitlab,
    valid_spec,  # noqa: F811
    capsys,
    raw,
    tdd_repo,
):
    forge_env["CI_PROJECT_URL"] = "https://gitlab.example.test/example-group/dummy-agentic"
    base = raw(tdd_repo.origin, "rev-parse", "main").strip()
    run = run_l4([*IMPLEMENT, judge_step()])
    assert run.code == 0
    lines = trace(capsys.readouterr().err)
    log = raw(tdd_repo.origin, "log", "--format=%H %s", "--reverse", f"main..{BRANCH}").splitlines()
    commits = {sha: subject for sha, subject in (entry.split(" ", 1) for entry in log)}
    for sha, subject in commits.items():
        if "[skip ci]" in subject or "hand off" in subject or subject.startswith(("test(", "feat(")):
            assert any(f" commit {sha[:10]} {subject[:90]}" in line for line in lines), (sha, subject)
    red = next(s for s, subject in commits.items() if subject.startswith("test("))
    green = next(s for s, subject in commits.items() if subject.startswith("feat("))
    assert any(f"commit {red[:10]} test(" in line for line in lines)
    assert any(f"commit {green[:10]} feat(" in line for line in lines)
    head = raw(tdd_repo.origin, "rev-parse", BRANCH).strip()
    project = "https://gitlab.example.test/example-group/dummy-agentic"
    pushes = [line for line in lines if " pushed " in line]
    assert (
        pushes
        and f"pushed {BRANCH} {base[:10]}..{red[:10]}" in pushes[0]
        and f"{project}/-/compare/{base}...{red}" in pushes[0]
    )
    summary = next(line for line in lines if " summary: " in line)
    assert f"head {head[:10]}" in summary and f"base {base[:10]}" in summary
    assert f"{project}/-/compare/{base}...{head}" in summary and "merge_requests/1" in summary
    print("\n".join(lines))  # shown with `pytest -s`


def test_a_resumed_run_prints_the_iteration_of_its_trailers(
    run_l4,
    install_hooks,
    forge_env,
    use_fake_gitlab,  # noqa: F811
    tdd_repo,
    raw,
    capsys,
):
    """P6: `run ... started (iteration N)` is the run's own iteration, the one its commits carry as `L4-Iteration`
    (it printed the count of the runs before it: 'iteration 1' on a second run)."""
    from l4.state.lifecycle import Trigger

    from ..orchestrator.test_review_reentry import human_commit

    install_hooks(verify=lambda ctx: Trigger.VERIFY_PASS)
    assert run_l4([*IMPLEMENT]).code == 0
    first = [line for line in trace(capsys.readouterr().err) if " started (iteration" in line]
    assert len(first) == 1 and "(iteration 1," in first[0]
    human_commit(tdd_repo, raw, {"notes.txt": "a person was here\n"})
    assert run_l4([]).code == 0
    second = [line for line in trace(capsys.readouterr().err) if " started (iteration" in line]
    assert len(second) == 1 and "(iteration 2," in second[0]
    trailer = raw(tdd_repo.origin, "log", "-1", "--format=%(trailers:key=L4-Iteration,valueonly)", BRANCH).strip()
    assert trailer == "2"
    (started,) = [e for e in run_started_events(raw, tdd_repo) if e["iteration"] == 2]
    assert started["run_id"] in second[0]


def run_started_events(raw, tdd_repo) -> list[dict]:
    import json

    from ..orchestrator.conftest import UNIT_DIR

    names = raw(tdd_repo.origin, "ls-tree", "--name-only", BRANCH, f"{UNIT_DIR}/.l4/ledger/").split()
    lines = [line for name in names for line in raw(tdd_repo.origin, "show", f"{BRANCH}:{name}").splitlines()]
    return [e for e in map(json.loads, lines) if e["type"] == "run.started"]
