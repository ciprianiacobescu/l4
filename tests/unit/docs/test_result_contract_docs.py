"""The result contract is documented where a person looks for it (L4-IMP-020, L4-IMP-021, L4-FAC-011)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _runbook() -> str:
    return (ROOT / "docs" / "runbook.md").read_text(encoding="utf-8")


def test_the_log_lines_and_the_ledger_event_are_in_the_runbook() -> None:  # SCN-IMP-188, SCN-FAC-18
    runbook = _runbook()
    lines = runbook[runbook.index("### 4.2 ") : runbook.index("### 4.3 ")]
    for needle in (
        "task <k> <phase> attempt <n>: L4 repaired the result (<fix>; <fix>)",
        "status set to done, was red",
        "`result.normalized`",
        "still judge the work",
        "context peak <n>k tokens",
        "<p>%",
    ):
        assert needle in lines, needle
    ledger = runbook[runbook.index("### 4.5 ") : runbook.index("## 5. ")]
    for needle in ("result.normalized{task, phase, attempt, source, fixes}", "context_peak_tokens"):
        assert needle in ledger, needle


def test_the_halted_section_says_when_a_result_fails_an_attempt() -> None:  # SCN-IMP-195, SCN-IMP-196
    runbook = _runbook()
    halted = runbook[runbook.index("### 7.2 `halted`") : runbook.index("### 7.3 ")]
    for needle in (
        "no longer fails an attempt",
        "only when the agent delivered no result object",
        "no result was delivered",
        "A `blocked` result with no question is not a failed",
        "one question made from its summary",
    ):
        assert needle in " ".join(halted.split()), needle


def test_the_limits_say_that_no_code_reads_the_repair_key() -> None:
    runbook = _runbook()
    limits = runbook[runbook.index("## 11. ") : runbook.index("## 12. ")]
    assert "`implementer.result_repair_attempts` is in the config, and no code reads it" in " ".join(limits.split())


def test_the_changelog_names_the_result_contract() -> None:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    section = changelog[changelog.index("## 0.4.4 (unreleased)") : changelog.index("## 0.4.3 ")]
    for needle in ("result.normalized", "output@1", "context_peak_tokens", "context_peak_percent", "no result object"):
        assert needle in section, needle
