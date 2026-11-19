"""The documentation of the readiness judge chain (L4-YOLO-100, SCN-YOLO-282)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
REFERENCES = ("plugins", "l4", "skills", "l4", "references")


def read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def section(text: str, start: str, end: str) -> str:
    return text.split(start, 1)[1].split(end, 1)[0]


def test_the_runbook_names_the_chain_the_keys_the_event_and_the_three_reasons() -> None:
    runbook = read("docs", "runbook.md")
    review = section(runbook, "### 12.2 ", "### 12.2a ")
    for needle in (
        "roles.plan_judges",
        "yolo.review.timeout",
        "yolo.review.max_batch_chars",
        "plan.review_incomplete",
        "no_judge",
        "timeout",
        "job_time",
        "incomplete",
        "judged in <n> parts",
        "answered and kept",
    ):
        assert needle in review, needle
    assert "The harness then records no review" not in review
    capacity = runbook.split("Every judge was discarded in step 9", 1)[1].split("**What you see:**", 1)[0]
    assert "roles.plan_judges" in capacity and "plan review" in capacity


def test_yolo_mode_no_longer_says_that_no_review_is_recorded() -> None:
    text = read("docs", "yolo-mode.md")
    assert "L4 records no review" not in text
    assert "plan.review_incomplete" in text and "roles.plan_judges" in text


def test_the_skill_names_the_chain_and_the_incomplete_review() -> None:
    assert "roles.plan_judges" in read(*REFERENCES, "adopt.md")
    for name in ("operate.md", "plan.md"):
        assert "the review is incomplete" in read(*REFERENCES, name), name
    assert "the review is incomplete" in read(*REFERENCES, "plan.md").split("When no judge can run", 1)[1]


def test_the_changelog_names_the_keys_in_the_0459_section() -> None:
    head = read("CHANGELOG.md").split("## 0.4.59 (", 1)[1].split("\n## ", 1)[0]
    for needle in ("roles.plan_judges", "yolo.review.timeout", "yolo.review.max_batch_chars", "plan.review_incomplete"):
        assert needle in head, needle


def test_the_runbook_says_the_size_bound_is_off_by_default_and_names_the_note_on_a_batch_in_parts() -> None:
    review = " ".join(section(read("docs", "runbook.md"), "### 12.2 ", "### 12.2a ").split())
    assert "default `0`" in review and "160,000" not in review and "turns it off" not in review
    assert "no judge saw two units' full text together" in review
    assert "a review has finished" in review  # a part of a finished review does not split the batch again


def test_the_runbook_counts_the_five_judge_roles() -> None:
    runbook = read("docs", "runbook.md")
    assert "judge adapter in all five roles" in " ".join(runbook.split())
    assert "in all four" not in runbook


def test_the_operate_row_gives_the_message_a_dry_run_prints() -> None:
    row = next(
        line for line in read(*REFERENCES, "operate.md").splitlines() if "the review is incomplete (<reason>)" in line
    )
    assert "answered and kept in the local cache" in row and "answered and kept, <l> left" in row


def test_the_changelog_lists_the_changed_behaviour_of_the_review() -> None:
    head = read("CHANGELOG.md").split("## 0.4.59 (", 1)[1].split("\n## ", 1)[0]
    assert "160,000" not in head
    changed = head.split("### Changed", 1)[1].split("\n### ", 1)[0]
    for needle in (
        "plan.review_incomplete",
        "job_time",
        "plan.admitted",
        "usage limit",
        "CFG-012",
        "yolo.review.max_batch_chars",
        "reviewed in parts",
    ):
        assert needle in changed, needle
