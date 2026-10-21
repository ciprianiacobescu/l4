"""M1.12 lines 18, 19 and 22 (L4-CLI-001, SPEC 2.2): one list of the designed-stop codes, and a line that says so.

Diagnosis of K4 (line 17, `docs/plan/m112-progress.md`): the include already allowed 10-13; the job the operator read
as failed was an allowed failure, which GitLab shows as `failed` with the runner's own `ERROR: Job failed` line."""

import json
import re
from pathlib import Path

import pytest
import yaml

from l4 import exitcodes
from l4.ci.render import render_gitlab_ci
from l4.cli import main
from l4.exitcodes import CI_ALLOWED, SEVERITY_ORDER, ExitCode, map_exit, most_severe

TEMPLATES = Path(exitcodes.__file__).parent / "ci" / "templates"


def test_the_designed_stop_codes_are_one_list():
    assert CI_ALLOWED == (10, 11, 12, 13)
    assert not {1, 2, 3, 14, 15} & set(CI_ALLOWED)


def test_the_gitlab_template_allows_exactly_that_list():
    parsed = yaml.safe_load((TEMPLATES / "l4.gitlab-ci.yml").read_text())["l4"]["allow_failure"]["exit_codes"]
    assert tuple(parsed) == CI_ALLOWED
    assert tuple(yaml.safe_load(render_gitlab_ci())["l4"]["allow_failure"]["exit_codes"]) == CI_ALLOWED


def test_the_github_template_maps_every_step_and_map_exit_agrees_with_the_list():
    text = (TEMPLATES / "l4.github.yml").read_text()
    assert len(re.findall(r"\|\| \.l4/bin/l4 ci map-exit \$\?", text)) == 3  # doctor, plan --sweep, run
    for code in CI_ALLOWED:
        assert map_exit(code, "github")[1] == 0, code
    for code in (1, 2, 3, 14, 15, 127, 137):
        assert map_exit(code, "github")[1] == 1, code


def write_outcome(repo: Path, code: int, reason: str | None) -> None:
    (repo / ".l4-out").mkdir(exist_ok=True)
    unit = {"unit": "openspec:u", "phase_before": "verifying", "phase_after": "awaiting_human"}
    if reason:
        unit["exit_reason"] = reason
    doc = {"schema": "l4/outcome@1", "run_id": "r", "harness_version": "x", "exit_code": code, "units": [unit]}
    (repo / ".l4-out" / "outcome.json").write_text(json.dumps(doc))


@pytest.mark.parametrize("code", CI_ALLOWED)
def test_gitlab_says_a_designed_stop_is_not_a_failure_and_keeps_the_code(code, tmp_path, capsys):
    write_outcome(tmp_path, code, "awaiting_human: Q-001 needs an answer")
    assert main(["ci", "map-exit", str(code), "--repo", str(tmp_path)], environ={"GITLAB_CI": "true"}) == code
    out = capsys.readouterr().out.strip()
    assert out.startswith("designed stop, not a failure: ") and f"l4 exit {code} (" in out
    assert "Q-001 needs an answer" in out


@pytest.mark.parametrize("code", [1, 2, 3, 14, 137])
def test_a_failure_is_never_called_a_designed_stop(code, tmp_path, capsys):
    main(["ci", "map-exit", str(code), "--repo", str(tmp_path)], environ={"GITLAB_CI": "true"})
    assert "designed stop" not in capsys.readouterr().out


def test_without_a_reason_the_generic_meaning_stands_after_the_phrase(tmp_path, capsys):
    main(["ci", "map-exit", "11", "--repo", str(tmp_path)], environ={"GITLAB_CI": "true"})
    assert capsys.readouterr().out.strip() == (
        "designed stop, not a failure: l4 exit 11 (awaiting_human): blocked on questions or a human gate"
    )


def test_the_severity_order_is_unchanged_and_a_failure_outranks_a_designed_stop():
    """Pin (passes at once): 14 outranks 13, 11 and 14 together exit 14."""
    assert SEVERITY_ORDER == (1, 16, 2, 3, 14, 15, 13, 11, 12, 10, 0)
    assert most_severe([11, 14]) is ExitCode.REJECTED and most_severe([0, 10, 11]) is ExitCode.AWAITING_HUMAN


def test_the_note_of_a_unit_that_waits_for_a_person_is_headed_waiting_for_you_with_the_ids_and_the_way_to_answer():
    from l4.clarifier.notify import build_sticky_section

    class Q:  # a QuestionView stand-in: only what the section reads
        id, title = "Q-007", "Which error?"
        kind = None

    text = build_sticky_section([Q()], path="openspec/changes/u/questions.md", branch="l4/u", link=None)  # type: ignore[list-item]
    assert text.startswith("### Waiting for you") and "- Q-007 (unlabelled): Which error?" in text
    assert "`openspec/changes/u/questions.md`" in text and "set Status to `answered`" in text


def test_the_capacity_note_already_lists_the_profiles_and_the_return_time():
    """Pin (passes at once; the capacity section of M1.8 R3 is the base): `Waiting for capacity` names each unusable
    profile and the time capacity returns."""
    from datetime import UTC, datetime

    from l4.availability.errors import Unready, WaitingCapacity
    from l4.orchestrator import capacity_section

    when = datetime(2026, 10, 7, 12, 0, tzinfo=UTC)
    exc = WaitingCapacity(
        "judges", "x", when, (Unready("claude-opus", "claude-code", "subscription", "hello", "refused"),)
    )
    note = capacity_section(
        exc, base="main", now=datetime(2026, 10, 7, 11, 0, tzinfo=UTC), retry_after="2026-10-07T12:00:00Z"
    )
    assert "`claude-opus`" in note and "hello: refused" in note and "2026-10-07T12:00Z" in note


def test_capacity_note_speaks_github_on_github():
    """L4-GHP-009: the waiting-for-capacity note's login steps use the GitHub words on GitHub."""
    from datetime import UTC, datetime

    from l4.availability.errors import Unready, WaitingCapacity
    from l4.orchestrator import capacity_section

    exc = WaitingCapacity("judges", "x", None, (Unready("cc", "claude-code", "subscription", "auth", "not set"),))
    now = datetime(2026, 10, 7, 11, 0, tzinfo=UTC)
    note = capacity_section(exc, base="main", now=now, retry_after=None, platform="github", environment="l4")
    assert "a secret of the GitHub environment `l4`" in note and "masked CI variable" not in note
    gitlab = capacity_section(exc, base="main", now=now, retry_after=None)
    assert "masked CI variable" in gitlab
