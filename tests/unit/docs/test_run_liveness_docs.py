"""A person can tell a working run from a stuck one (L4-OPS-021, SCN-OPS-37)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _flat(text: str) -> str:
    return " ".join(text.split())


def _runbook() -> str:
    return (ROOT / "docs" / "runbook.md").read_text(encoding="utf-8")


def test_section_2_leads_to_the_stuck_job_procedure() -> None:  # SCN-OPS-37
    runbook = _runbook()
    table = runbook[runbook.index("## 2. ") : runbook.index("## 3. ")]
    assert "The job runs, and its log has no new line for a long time" in table
    assert "(#46-is-the-job-stuck)" in table


def test_procedure_4_6_has_the_needles() -> None:  # SCN-OPS-37
    runbook = _runbook()
    proc = _flat(runbook[runbook.index("### 4.6 Is the job stuck?") : runbook.index("## 5. ")])
    for needle in (
        "working <elapsed>, <c> tool calls, last activity <t> ago",
        "tool call open for <t>",
        "implementer.idle_timeout",
        "30 minutes",
        "no activity from",
        "Last activity:",
        "Open run:",
        "gh run list --workflow l4.yml --status in_progress",
        "red: <n> new tests fail, as intended",
        "implementer.heartbeat",
    ):
        assert needle in proc, needle


def test_sections_4_2_4_4_4_5_and_11_have_their_rows() -> None:  # SCN-OPS-37
    runbook = _runbook()
    logs = _flat(runbook[runbook.index("### 4.2 ") : runbook.index("### 4.3 ")])
    for needle in (
        "last activity <t> ago",
        "no activity from <profile> for <t>",
        "red: <n> new tests fail, as intended",
    ):
        assert needle in logs, needle
    status = _flat(runbook[runbook.index("### 4.4 ") : runbook.index("### 4.5 ")])
    for needle in ("`LAST`", "Last activity:", "Open run:", "open_run", "last_activity"):
        assert needle in status, needle
    ledger = _flat(runbook[runbook.index("### 4.5 ") : runbook.index("### 4.6 ")])
    for needle in ("agent.idle{task, phase, attempt, profile, silent_s, tool_calls}", "run.started.ci_url"):
        assert needle in ledger, needle
    limits = _flat(runbook[runbook.index("## 11. ") : runbook.index("## 12. ")])
    assert "longer than `implementer.idle_timeout`" in limits
    assert "one step old" in limits


def test_operate_names_the_last_activity() -> None:  # SCN-OPS-37
    text = _flat((ROOT / "plugins" / "l4" / "skills" / "l4" / "references" / "operate.md").read_text(encoding="utf-8"))
    assert "last activity" in text and "open run" in text and "CI link" in text


def test_changelog_names_run_liveness_in_0_4_5() -> None:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    section = changelog[changelog.index("## 0.4.5 (") : changelog.index("## 0.4.4 (")]
    for needle in (
        "implementer.idle_timeout",
        "implementer.heartbeat",
        "agent.idle",
        "Open run:",
        "run.started.ci_url",
    ):
        assert needle in section, needle
    old = changelog[changelog.index("## 0.4.4 (") : changelog.index("## 0.4.3 ")]
    assert "agent.idle" not in old
