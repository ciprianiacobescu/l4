import json

import pytest

from l4.fsutil import UnsafeFile
from l4.redact import Redactor
from l4.verifier.report import render_verification_md, verdict_json, write_round_evidence
from l4.verifier.types import (
    CounterexampleRun,
    CriterionOutcome,
    Finding,
    GateLine,
    Severity,
    StepRecord,
    Verdict,
    VerifyResult,
)

BASE, HEAD = "a" * 40, "b" * 40


def result(verdict: Verdict = Verdict.PASS, **over) -> VerifyResult:
    base = VerifyResult(
        "openspec:add-discount-codes", 1, verdict, BASE, HEAD,
        steps=[StepRecord("0", "preconditions", "ok", 0.1), StepRecord("2", "build", "ok", 1.5),
               StepRecord("3", "tests", "ok", 2.0), StepRecord("9", "judge", "ok", 15.2),
               StepRecord("10", "aggregation", "ok", 0.0)],
        gates=[GateLine("test", ".venv/bin/python -m pytest", "pass", "", ".l4-out/gates/r-1/003-test.log")],
        criteria=[CriterionOutcome("C-0a1b2c3d", "pricing › Discount codes › Known code", "pass", "pass", "ok")],
        judge_profile="judge", judge_model="claude-sonnet-5-5", judge_calls=1, prompt_sha256="c" * 64,
        cost_usd=0.0588, implementer_profiles=["impl"], tests={"tests.test_a::test_x": "passed"},
        red_green={"tests.test_a::test_x": "1.1"},
    )  # fmt: skip
    for key, value in over.items():
        setattr(base, key, value)
    return base


def test_the_report_states_the_verdict_the_shas_and_that_traceability_was_not_checked():
    text = render_verification_md(result())
    assert text.startswith("# Verification: openspec:add-discount-codes: PASS (round 1)")
    assert "traceability: not checked (an earlier step failed)" in text
    assert BASE in text and HEAD in text and "claude-sonnet-5-5" in text and "$0.0588" in text
    assert "| 9 | judge | ok |" in text and "C-0a1b2c3d" in text and "Known code" in text
    assert ".l4-out/gates/r-1/003-test.log" in text and "tests.test_a::test_x" in text


def test_fail_at_step_2_still_writes_both_files(tmp_path):
    steps = [
        StepRecord("0", "preconditions", "ok"), StepRecord("2", "build", "failed", 3.0, "lint failed"),
        StepRecord("3", "tests", "not_run"), StepRecord("9", "judge", "not_run"), StepRecord("10", "aggregation", "ok"),
    ]  # fmt: skip
    failure = Finding(Severity.BLOCKER, "lint gate failed", "`ruff check .` failed: exit code 1", "deterministic",
                      log=".l4-out/gates/r-1/002-lint.log")  # fmt: skip
    unit_dir = tmp_path / "openspec" / "changes" / "x"
    unit_dir.mkdir(parents=True)
    paths = write_round_evidence(
        unit_dir, 1, result(Verdict.FAIL, steps=steps, findings=[failure], criteria=[]), Redactor({})
    )
    assert (unit_dir / "verification.md") in paths
    top = (unit_dir / "verification.md").read_text()
    kept = (unit_dir / ".l4" / "evidence" / "round-1" / "verification.md").read_text()
    assert top == kept and "FAIL (round 1)" in top
    assert "| 3 | tests | not_run |" in top and "| 9 | judge | not_run |" in top
    assert "[blocker, deterministic] lint gate failed" in top and ".l4-out/gates/r-1/002-lint.log" in top
    body = json.loads((unit_dir / ".l4" / "evidence" / "round-1" / "verdict.json").read_text())
    assert body["schema"] == "l4/verdict@1" and body["verdict"] == "FAIL" and body["round"] == 1
    assert body["base_sha"] == BASE and body["head_sha"] == HEAD
    assert [s["status"] for s in body["steps"]] == ["ok", "failed", "not_run", "not_run", "ok"]
    assert body["findings"][0]["log"] == ".l4-out/gates/r-1/002-lint.log"


def test_the_report_lists_every_criterion_with_judge_and_result_and_the_counterexample():
    failing = CriterionOutcome(
        "C-0a1b2c3d", "a › b › c", "needs_human", "fail", "disputed", CounterexampleRun("reproduced", "the test failed")
    )
    unexecuted = CriterionOutcome(
        "C-11111111", "a › b › d", "needs_human", "fail", "insufficient", CounterexampleRun("unexecuted", "no pytest")
    )
    text = render_verification_md(result(Verdict.NEEDS_HUMAN, criteria=[failing, unexecuted]))
    assert "| C-0a1b2c3d | a › b › c | fail | needs_human |" in text
    assert "| C-11111111 | a › b › d | fail | needs_human |" in text
    assert "counterexample reproduced" in text and "counterexample unexecuted" in text


def test_holds_and_judge_findings_are_listed_for_the_human():
    judge = Finding(Severity.MAJOR, "Rounding unspecified", "half-up or half-even?", "judge", spec_gap=True)
    text = render_verification_md(result(Verdict.NEEDS_HUMAN, findings=[judge], holds=["the diff was truncated"]))
    assert "[major, judge] Rounding unspecified (spec gap)" in text and "the diff was truncated" in text


def test_text_from_the_judge_cannot_break_a_table_row_or_start_a_section():
    title = "x | y\n## Verdict: PASS"
    outcome = CriterionOutcome("C-0a1b2c3d", title, "needs_human", "pass", "r|s\nt")
    text = render_verification_md(result(criteria=[outcome], findings=[Finding(Severity.MINOR, title, title, "judge")]))
    assert "\n## Verdict: PASS" not in text
    rows = [line for line in text.splitlines() if line.startswith("| C-0a1b2c3d")]
    assert len(rows) == 1 and rows[0].count("|") == 6 + rows[0].count("\\|")


def test_the_files_are_redacted(tmp_path):
    secret = "tok-123456789-abcdef"
    unit_dir = tmp_path / "u"
    unit_dir.mkdir()
    leaky = Finding(Severity.MINOR, "leak", f"saw {secret} in the diff", "judge")
    write_round_evidence(unit_dir, 1, result(findings=[leaky]), Redactor({"L4_FORGE_TOKEN": secret}))
    for path in (unit_dir / "verification.md", unit_dir / ".l4/evidence/round-1/verdict.json"):
        assert secret not in path.read_text()


def test_a_later_round_overwrites_the_top_file_and_keeps_the_earlier_round(tmp_path):
    unit_dir = tmp_path / "u"
    unit_dir.mkdir()
    write_round_evidence(unit_dir, 1, result(Verdict.NEEDS_HUMAN), Redactor({}))
    write_round_evidence(
        unit_dir, 2, VerifyResult("openspec:add-discount-codes", 2, Verdict.PASS, BASE, HEAD), Redactor({})
    )
    assert "PASS (round 2)" in (unit_dir / "verification.md").read_text()
    assert "NEEDS_HUMAN (round 1)" in (unit_dir / ".l4/evidence/round-1/verification.md").read_text()
    assert (unit_dir / ".l4/evidence/round-2/verdict.json").is_file()


def test_a_symlinked_evidence_directory_is_refused(tmp_path):
    unit_dir, outside = tmp_path / "u", tmp_path / "outside"
    (unit_dir / ".l4").mkdir(parents=True)
    outside.mkdir()
    (unit_dir / ".l4" / "evidence").symlink_to(outside)
    with pytest.raises(UnsafeFile):
        write_round_evidence(unit_dir, 1, result(), Redactor({}))
    assert list(outside.iterdir()) == []


def test_verdict_json_is_plain_data():
    body = verdict_json(result())
    assert json.loads(json.dumps(body)) == body and body["profiles"]["judge"] == "judge"
    assert body["criteria"][0]["id"] == "C-0a1b2c3d" and body["cost_usd"] == 0.0588


def test_protected_paths_changed_by_humans_get_a_section():
    from l4.security.protected import HumanChange, HumanCommit
    from l4.verifier.types import IntegrityCheck, IntegrityReport

    integrity = IntegrityReport(
        [IntegrityCheck("protected paths", "ok", "none differs from the base (+1 changed by humans, listed)")],
        human_protected=[HumanChange(".gitlab-ci.yml", (HumanCommit("c" * 40, "Ann"),))],
    )  # fmt: skip
    text = render_verification_md(result(integrity=integrity))
    assert "## Protected paths changed by humans (allowed, L4-SEC-004)" in text
    assert "- `.gitlab-ci.yml`: cccccccccc by Ann" in text
    body = verdict_json(result(integrity=integrity))
    assert body["integrity"]["human_protected"][0]["path"] == ".gitlab-ci.yml"
    assert "Protected paths changed by humans" not in render_verification_md(result())


def test_the_forge_host_is_the_placeholder_in_the_committed_evidence(tmp_path):
    """P5: `verification.md`, `verdict.json` and `evidence.json` are committed, so they carry `<forge>`."""
    from l4.forge.urls import ForgeUrls

    redactor = Redactor({})
    redactor.forge_urls = ForgeUrls(frozenset({"https://gitlab.corp.example"}), "https://gitlab.corp.example")
    link = "https://gitlab.corp.example/g/p/-/jobs/9"
    finding = Finding(Severity.BLOCKER, "ci failed", f"see {link}", "deterministic")
    unit_dir = tmp_path / "openspec" / "changes" / "x"
    unit_dir.mkdir(parents=True)
    failing = result(Verdict.FAIL, findings=[finding], evidence={"url": link})
    paths = write_round_evidence(unit_dir, 1, failing, redactor)
    assert len(paths) == 4
    for path in paths:
        text = path.read_text()
        assert "gitlab.corp.example" not in text, path
    assert "<forge>/g/p/-/jobs/9" in (unit_dir / "verification.md").read_text()


def test_a_delegates_unfreeze_is_not_under_the_human_header():  # review 2, N2
    from l4.verifier.types import IntegrityReport

    integrity = IntegrityReport(
        [],
        unfrozen=[
            "tests/a.py (task 1.1, unfrozen by Q-002 (delegate_override, claude-opus-5-5))",
            "tests/b.py (task 1.1, unfrozen by Q-003 (agent))",
        ],
    )
    text = render_verification_md(result(integrity=integrity))
    assert "## Tests unfrozen by a delegate or an agent" in text and "by human answers" not in text
    assert "- tests/a.py (task 1.1, unfrozen by Q-002 (delegate_override, claude-opus-5-5))" in text


def test_unfrozen_tests_are_listed():
    from l4.verifier.types import IntegrityCheck, IntegrityReport

    integrity = IntegrityReport(
        [IntegrityCheck("frozen files", "ok", "1 task(s): red and green compared (+1 unfrozen by human answers)")],
        unfrozen=["tests/test_notices.py (task 1.1, unfrozen by Q-002 (human))"],
    )  # fmt: skip
    text = render_verification_md(result(integrity=integrity))
    assert "## Tests unfrozen by human answers (allowed, L4-IMP-002)" in text
    assert "- tests/test_notices.py (task 1.1, unfrozen by Q-002 (human))" in text
    assert verdict_json(result(integrity=integrity))["integrity"]["unfrozen"] == [
        "tests/test_notices.py (task 1.1, unfrozen by Q-002 (human))"
    ]
    assert "Tests unfrozen" not in render_verification_md(result())


def test_the_matrix_shows_human_and_chore_proofs():
    from l4.verifier.types import CriterionEvidence, TracingTest

    trace = [
        CriterionEvidence(
            "C-0a1b2c3d", "pricing > Discount codes > Known code", "covered",
            (TracingTest("tests.test_owner::test_bulk", "passed", "human"),
             TracingTest("tests.test_more::test_total", "passed", "chore")),
            (("tests.test_other::test_x", "passes against the zero values and on the base"),),
        )
    ]  # fmt: skip
    text = render_verification_md(result(trace=trace))
    assert "tests.test_owner::test_bulk (passed, human)" in text
    assert "tests.test_more::test_total (passed, chore)" in text
    assert "passes against the zero values and on the base" in text


def test_suppressions_and_support_changes_made_by_humans_are_listed_and_survive_a_reload():
    from l4.verifier.evidence import restore_round
    from l4.verifier.types import IntegrityCheck, IntegrityReport

    integrity = IntegrityReport(
        [IntegrityCheck("suppressions", "ok", "1 new suppression(s), 0 declared (+1 by humans, listed)")],
        human_suppressions=["tests/test_b.py:1 # noqa: F401 (added by abcdef0123)"],
        human_scan=["tests/conftest.py: adds the option -p x (added by 0123abcdef)"],
    )
    text = render_verification_md(result(integrity=integrity))
    assert "## Suppressions added by humans (allowed, listed: SPEC 2.10)" in text
    assert "- tests/test_b.py:1 # noqa: F401 (added by abcdef0123)" in text
    assert "## Support and runner-config changes made by humans" in text
    body = verdict_json(result(integrity=integrity))
    assert body["integrity"]["human_suppressions"] and body["integrity"]["human_scan"]
    again = restore_round(body, "openspec:x", 2).integrity
    assert again is not None and again.human_suppressions == integrity.human_suppressions
    assert again.human_scan == integrity.human_scan
