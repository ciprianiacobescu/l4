import pytest

from l4.cli import main
from l4.exitcodes import ExitCode, map_exit


def test_github_downgrades_semantic_codes_gitlab_preserves():
    annotation, code = map_exit(11, "github")
    assert annotation is not None and annotation.startswith("::warning::") and code == 0
    assert map_exit(12, "github")[0].startswith("::warning::") and map_exit(12, "github")[1] == 0
    assert map_exit(10, "github")[0].startswith("::notice::") and map_exit(10, "github")[1] == 0
    assert map_exit(0, "github") == (None, 0)
    for failure in (1, 2, 3, 14, 15):
        annotation, code = map_exit(failure, "github")
        assert annotation.startswith("::error::") and code == 1, failure
    for any_code in (0, 1, 2, 3, 10, 11, 12, 13, 14, 15):
        annotation, code = map_exit(any_code, "gitlab")
        assert code == any_code
        assert (annotation is None) == (any_code == 0)
        assert annotation is None or not annotation.startswith("::")


def test_github_renders_13_as_a_warning_and_14_as_an_error():
    """M1.11 W4: a halt is unit state the forge already mirrors (label, note, exit_reason), not a failed job."""
    annotation, code = map_exit(13, "github", "task 1.1: max_task_attempts (3) reached")
    assert annotation == "::warning::l4 exit 13 (halted): task 1.1: max_task_attempts (3) reached" and code == 0
    annotation, code = map_exit(14, "github")
    assert annotation is not None and annotation.startswith("::error::l4 exit 14 (rejected)") and code == 1
    assert map_exit(13, "gitlab")[1] == 13  # GitLab keeps the code; `allow_failure: exit_codes` decides


def test_unknown_platform_raises():
    with pytest.raises(ValueError):
        map_exit(11, "bitbucket")


def test_a_code_outside_the_table_is_a_failure_that_keeps_its_number():
    annotation, code = map_exit(137, "gitlab")
    assert annotation == "l4 exited with unexpected code 137" and code == 137
    assert map_exit(127, "gitlab")[1] == 127
    assert map_exit(300, "gitlab")[1] == 1 and map_exit(-1, "gitlab")[1] == 1  # cannot be a process exit status
    annotation, code = map_exit(137, "github")
    assert annotation == "::error::l4 exited with unexpected code 137" and code == 1


def test_failures_are_never_downgraded_by_the_command(capsys):
    assert main(["ci", "map-exit", "14"], environ={"GITHUB_ACTIONS": "true"}) == 1
    assert main(["ci", "map-exit", "13"], environ={"GITHUB_ACTIONS": "true"}) == 0  # a halt is a warning (M1.11)
    assert main(["ci", "map-exit", "13"], environ={"GITLAB_CI": "true"}) == 13
    assert main(["ci", "map-exit", "11"], environ={"GITLAB_CI": "true"}) == 11


def test_command_on_github_prints_annotation_and_exits_0(capsys):
    assert main(["ci", "map-exit", "11"], environ={"GITHUB_ACTIONS": "true"}) == 0
    assert "::warning::" in capsys.readouterr().out


def test_no_ci_environment_preserves_the_code(capsys):
    assert main(["ci", "map-exit", "11"], environ={}) == ExitCode.AWAITING_HUMAN
    assert main(["ci", "map-exit", "0"], environ={}) == 0
    assert capsys.readouterr().out.count("\n") == 1  # only the code 11 line; 0 prints nothing


def test_unknown_code_is_reported_not_called_a_usage_error(capsys):
    assert main(["ci", "map-exit", "137"], environ={"GITLAB_CI": "true"}) == 137
    assert "unexpected code 137" in capsys.readouterr().out
    assert main(["ci", "map-exit", "137"], environ={"GITHUB_ACTIONS": "true"}) == 1
    assert main(["ci", "map-exit", "--", "-1"], environ={}) == 1
    assert main(["ci", "map-exit", "abc"], environ={}) == 2  # a non-integer argument is the only usage error


def test_map_exit_works_with_a_broken_config(tmp_path, capsys):
    (tmp_path / ".l4").mkdir()
    (tmp_path / ".l4" / "config.yaml").write_text("verifer: {}\n", encoding="utf-8")
    assert main(["ci", "map-exit", "11", "--repo", str(tmp_path)], environ={}) == 11


REASON = "base merge conflict: merge main into l4/openspec/add-cart-clear by hand and push"


def write_outcome(repo, code, reason):
    import json

    (repo / ".l4-out").mkdir(parents=True, exist_ok=True)
    unit = {"unit": "openspec:add-cart-clear", "phase_before": "verifying", "phase_after": "verifying"}
    if reason:
        unit["exit_reason"] = reason
    doc = {"schema": "l4/outcome@1", "run_id": "r", "harness_version": "x", "exit_code": code, "units": [unit]}
    (repo / ".l4-out" / "outcome.json").write_text(json.dumps(doc))


def test_a_base_merge_conflict_has_its_own_line_and_the_same_exit_code(tmp_path, capsys):
    write_outcome(tmp_path, 1, REASON)
    assert main(["ci", "map-exit", "1", "--repo", str(tmp_path)], environ={"GITLAB_CI": "true"}) == 1
    assert capsys.readouterr().out.strip() == f"l4 exit 1 (internal_error): {REASON}"
    assert main(["ci", "map-exit", "1", "--repo", str(tmp_path)], environ={"GITHUB_ACTIONS": "true"}) == 1
    assert capsys.readouterr().out.strip() == f"::error::l4 exit 1 (internal_error): {REASON}"


def test_without_a_reason_or_for_another_code_the_generic_line_stays(tmp_path, capsys):
    generic = "l4 exit 1 (internal_error): harness bug or infrastructure failure"
    assert main(["ci", "map-exit", "1", "--repo", str(tmp_path)], environ={"GITLAB_CI": "true"}) == 1  # no outcome
    assert capsys.readouterr().out.strip() == generic
    write_outcome(tmp_path, 1, None)
    main(["ci", "map-exit", "1", "--repo", str(tmp_path)], environ={"GITLAB_CI": "true"})
    assert capsys.readouterr().out.strip() == generic
    write_outcome(tmp_path, 13, REASON)  # the outcome belongs to a run that ended otherwise
    main(["ci", "map-exit", "1", "--repo", str(tmp_path)], environ={"GITLAB_CI": "true"})
    assert capsys.readouterr().out.strip() == generic
    (tmp_path / ".l4-out" / "outcome.json").write_text("{not json")
    main(["ci", "map-exit", "1", "--repo", str(tmp_path)], environ={"GITLAB_CI": "true"})
    assert capsys.readouterr().out.strip() == generic


def test_a_regression_maps_to_itself_on_gitlab_and_to_an_error_on_github():
    """M1.14 D7: 15 is not in CI_ALLOWED, so GitLab shows the job red and GitHub exits 1."""
    annotation, code = map_exit(15, "gitlab")
    assert code == 15 and annotation == "l4 exit 15 (regression): eval scorecard regressed against the baseline"
    annotation, code = map_exit(15, "github", "profile p1 dropped")
    assert annotation == "::error::l4 exit 15 (regression): profile p1 dropped" and code == 1
