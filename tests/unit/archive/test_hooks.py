import httpx

from l4.state.lifecycle import Trigger

from .conftest import BRANCH, TOKEN, UNIT_DIR, green_step, red_step

HANDOFF = "docs(add-discount-codes): hand off to review"
TITLE = (
    "[l4] add-discount-codes: Shoppers expect to enter a discount code at checkout, "
    "and today the pricing module cannot apply one."
)


def passing_verifier(install_hooks) -> None:
    install_hooks(verify=lambda ctx: Trigger.VERIFY_PASS)


def test_hooks_mirror_after_phase_change_and_handoff_marks_ready(
    run_l4, install_hooks, forge_env, use_fake_gitlab, push_configs, capsys, tdd_repo, raw
):
    gitlab = use_fake_gitlab
    passing_verifier(install_hooks)
    real_route = gitlab.route
    seen: dict[str, object] = {}

    def route(method, path, query, body):
        response = real_route(method, path, query, body)
        if method == "POST" and path.endswith("/merge_requests"):
            seen["pushed_before_mr"] = raw(tdd_repo.origin, "rev-parse", "--verify", "--quiet", BRANCH).strip() != ""
            gitlab.mrs[1]["labels"].append("bug")  # a label of the team's, which must survive
        return response

    gitlab.route = route  # type: ignore[method-assign]
    run = run_l4([red_step(), green_step()])
    assert run.code == 0
    # a draft MR after the first push, with the proposal's first Why line in the title
    assert seen["pushed_before_mr"] is True
    (mr,) = gitlab.mrs.values()
    assert mr["source_branch"] == BRANCH and mr["target_branch"] == "main"
    assert mr["title"] == TITLE  # ready: the Draft prefix is gone
    assert "verification.md" in mr["description"] and "Any merge method works" in mr["description"]
    # one l4:<phase> label, the team's label kept, no stale phase left
    assert sorted(mr["labels"]) == ["bug", "l4:in_review"]
    assert {"l4:implementing", "l4:verifying", "l4:verified", "l4:in_review"} <= set(gitlab.labels)
    # exactly one hand-off commit, without [skip ci], and it is the MR head: the rest of the run is in the lock ref
    subjects = run.subjects()
    assert subjects.count(HANDOFF) == 1
    assert subjects[-1] == HANDOFF and "[skip ci]" not in subjects[-1]
    assert len(run.pending_files()) == 1
    handoff_sha = raw(tdd_repo.origin, "log", "--format=%H", "--grep", HANDOFF, BRANCH).strip()
    files = raw(tdd_repo.origin, "show", "--name-only", "--format=", handoff_sha).split()
    assert any(f.startswith(f"{UNIT_DIR}/.l4/ledger/") for f in files)
    trailers = raw(tdd_repo.origin, "log", "-1", "--format=%(trailers:key=L4-Phase,valueonly)", handoff_sha).strip()
    assert trailers == "verified"
    # the MR is recorded in the ledger and in the outcome
    (event,) = run.events("pr.updated")
    assert event["url"] == mr_url(gitlab).replace("https://gitlab.example.test", "<forge>") and event["number"] == 1
    assert run.outcome["units"][0]["pr_url"] == mr_url(gitlab)
    assert run.outcome["units"][0]["phase_after"] == "in_review"
    # every push authenticated through the helper, and the token is nowhere
    assert push_configs and all(
        any(k == "credential.helper" and "L4_FORGE_TOKEN" in v and TOKEN not in v for k, v in cfg)
        for cfg in push_configs
    )
    assert TOKEN not in capsys.readouterr().err
    assert TOKEN not in (tdd_repo.repo / ".git" / "config").read_text()


def mr_url(gitlab) -> str:
    return gitlab.mr_json(next(iter(gitlab.mrs.values())))["web_url"]


def test_each_label_set_is_written_once(run_l4, install_hooks, forge_env, use_fake_gitlab):
    gitlab = use_fake_gitlab
    passing_verifier(install_hooks)
    run_l4([red_step(), green_step()])
    label_puts = [b for m, p, q, b in gitlab.requests if m == "PUT" and b and "add_labels" in b]
    added = [b["add_labels"] for b in label_puts]
    assert added == sorted(set(added), key=added.index)  # no label set is written twice
    assert added[-1] == "l4:in_review"


def test_a_forge_outage_while_mirroring_does_not_fail_the_run(
    run_l4, install_hooks, forge_env, use_fake_gitlab, capsys
):
    gitlab = use_fake_gitlab
    passing_verifier(install_hooks)
    real_route = gitlab.route

    def route(method, path, query, body):
        if method == "PUT" and body and ("add_labels" in body or "remove_labels" in body):
            return httpx.Response(500, json={"message": "boom"})
        return real_route(method, path, query, body)

    gitlab.route = route  # type: ignore[method-assign]
    run = run_l4([red_step(), green_step()])
    assert run.code == 0 and run.outcome["units"][0]["phase_after"] == "in_review"
    assert "HTTP 500" in capsys.readouterr().err
    assert gitlab.mrs[1]["labels"] == []


def test_no_token_outside_ci_skips_the_forge_hooks_and_stops_at_verified(run_l4, install_hooks, capsys):
    passing_verifier(install_hooks)
    run = run_l4([red_step(), green_step()])
    err = capsys.readouterr().err
    assert run.code == 0
    assert "L4_FORGE_TOKEN is not set" in err and "skipped" in err
    unit = run.outcome["units"][0]
    assert unit["phase_after"] == "verified" and unit["pr_url"] is None
    assert HANDOFF not in run.subjects()
    assert "hand_off_pushed" not in run.triggers()


def test_a_missing_token_in_ci_is_exit_3_before_any_agent_runs(run_l4, tdd_repo, monkeypatch, capsys):
    tdd_repo.environ.update(GITLAB_CI="true", CI_API_V4_URL="https://gitlab.example.test/api/v4", CI_PROJECT_ID="1")
    run = run_l4([red_step(), green_step()])
    assert run.code == 3
    assert run.adapter.requests == []
    assert "L4_FORGE_TOKEN is not set" in capsys.readouterr().err
    assert run.raw(tdd_repo.origin, "branch", "--list", BRANCH).strip() == ""  # nothing was pushed


def test_a_token_without_an_api_url_outside_ci_is_exit_2(run_l4, tdd_repo, capsys):
    tdd_repo.environ["L4_FORGE_TOKEN"] = TOKEN
    run = run_l4([red_step(), green_step()])
    assert run.code == 2
    assert "forge.gitlab.api_url" in capsys.readouterr().err and TOKEN not in capsys.readouterr().err


def test_a_failed_ready_call_leaves_the_unit_verified_and_a_rerun_adds_no_second_handoff_commit(
    run_l4, install_hooks, forge_env, use_fake_gitlab
):
    gitlab = use_fake_gitlab
    passing_verifier(install_hooks)
    real_route = gitlab.route
    broken = {"on": True}

    def route(method, path, query, body):
        if broken["on"] and method == "PUT" and body and "title" in body:
            return httpx.Response(500, json={"message": "boom"})
        return real_route(method, path, query, body)

    gitlab.route = route  # type: ignore[method-assign]
    first = run_l4([red_step(), green_step()])
    assert first.code == 1
    assert first.events("phase.changed")[-1]["to"] == "verified"
    assert gitlab.mrs[1]["title"].startswith("Draft: ")
    broken["on"] = False
    second = run_l4([])
    assert second.code == 0 and second.outcome["units"][0]["phase_after"] == "in_review"
    assert not gitlab.mrs[1]["title"].startswith("Draft: ")
    assert second.subjects().count(HANDOFF) == 1


def test_origin_credentials_written_by_the_runner_are_stripped_at_the_start_of_a_run(
    run_l4, install_hooks, forge_env, use_fake_gitlab, tdd_repo, raw, tmp_path
):
    job_token = "glpat-JOBTOKEN0123456789abcdef"
    passing_verifier(install_hooks)
    local = f"{tdd_repo.origin.parent}/"
    for prefix in (f"https://gitlab-ci-token:{job_token}@gitlab.example.test/", "https://gitlab.example.test/"):
        raw(tdd_repo.repo, "config", "--add", f"url.{local}.insteadOf", prefix)  # the network is the local bare repo
    raw(
        tdd_repo.repo,
        "remote",
        "set-url",
        "origin",
        f"https://gitlab-ci-token:{job_token}@gitlab.example.test/origin.git",
    )
    run = run_l4([red_step(), green_step()])
    assert run.code == 0
    assert job_token not in raw(tdd_repo.repo, "config", "--get", "remote.origin.url")
    assert (
        raw(tdd_repo.repo, "config", "--get", "remote.origin.url").strip() == "https://gitlab.example.test/origin.git"
    )


def test_a_hand_off_subject_in_the_history_of_main_does_not_count_for_this_unit(
    run_l4, install_hooks, forge_env, use_fake_gitlab, tdd_repo, raw
):
    passing_verifier(install_hooks)
    raw(tdd_repo.repo, "commit", "--allow-empty", "-q", "-m", HANDOFF)  # an older unit of the same name, merged
    raw(tdd_repo.repo, "push", "-q", "origin", "main")
    raw(tdd_repo.repo, "fetch", "-q", "origin")
    run = run_l4([red_step(), green_step()])
    assert run.code == 0 and run.subjects().count(HANDOFF) == 1


def test_a_rejected_token_is_exit_3_before_any_agent_runs(run_l4, install_hooks, forge_env, use_fake_gitlab):
    """Regression: a 401 used to be a warning until the hand-off, after every agent step had spent quota."""
    use_fake_gitlab.fail_next.append(httpx.Response(401, json={"message": "401 Unauthorized"}))
    passing_verifier(install_hooks)
    run = run_l4([red_step(), green_step()])
    assert run.code == 3
    assert run.adapter.requests == []


def halt_run(run_l4):
    from l4.agents.fake import Step

    from ..implementer.conftest import result

    run = run_l4([Step(structured=result("red"))], implementer={"max_task_attempts": 1})
    assert run.code == 13
    return run


def test_a_halted_unit_note_names_the_reason_and_the_label(run_l4, forge_env, use_fake_gitlab):
    """M1.11 W4: the halting run's last mirror sync writes why the unit halted and how to continue."""
    halt_run(run_l4)
    (note,) = use_fake_gitlab.notes[1]
    body = note["body"]
    assert "### Halted: task 1.1: max_task_attempts (1) reached in red; last failure: no tests added" in body
    assert "a member adds the label `l4:resume` to this merge request" in body
    assert "`l4 resume --unit openspec:add-discount-codes --reason TEXT`" in body
    assert use_fake_gitlab.mrs[1]["labels"] == ["l4:halted"]


def test_the_halted_note_is_redacted(run_l4, forge_env, use_fake_gitlab):
    """m1.11(fix): the halt reason quotes the first line of a test's error ("neither an assertion nor ..."), and the
    note goes to the forge as it is; the ledger and the console redact it, the note must too."""
    from l4.agents.fake import Step

    from ..implementer.conftest import HEADER, KNOWN, STUB, result

    raising = '    raise ValueError("glpat-" + "a1B2c3D4e5F6g7H8i9J0")\n'  # the token is made when the test runs
    leaky = HEADER + f'@pytest.mark.l4("{KNOWN}")\ndef test_known_code():\n' + raising
    red = Step(
        writes={"tests/test_discount.py": leaky, "src/pytdd/pricing.py": STUB},
        structured=result("red", tests_added=["tests/test_discount.py::test_known_code"], criteria_ids=[KNOWN]),
    )
    run = run_l4([red], implementer={"max_task_attempts": 1})
    assert run.code == 13
    (note,) = use_fake_gitlab.notes[1]
    assert "### Halted: task 1.1" in note["body"] and "ValueError" in note["body"]
    assert "a1B2c3D4e5F6g7H8i9J0" not in note["body"]
    assert "[REDACTED:gitlab-pat]" in note["body"]


def test_an_escalated_unit_note_says_how_a_resume_goes_on():
    from l4.ci.resume_label import halted_section

    text = halted_section("escalated", "verification failed and no fix round is left", "openspec:x", "l4:resume")
    assert text.startswith("### Escalated: verification failed and no fix round is left")
    assert "one more fix round per label event" in text and "--extend-fix-rounds N" in text


def test_the_section_goes_when_the_unit_resumes(run_l4, tdd_repo, forge_env, use_fake_gitlab):
    from l4.cli import main

    halt_run(run_l4)
    assert "Halted:" in use_fake_gitlab.notes[1][0]["body"]
    argv = ["resume", "--unit", "openspec:add-discount-codes", "--reason", "fixed", "--repo", str(tdd_repo.repo)]
    assert main(argv, environ=tdd_repo.environ) == 0
    assert use_fake_gitlab.notes[1][0]["body"].endswith("Nothing is waiting for a human answer.")
    assert use_fake_gitlab.mrs[1]["labels"] == ["l4:implementing"]
