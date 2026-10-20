"""The docs of run-continuation, part A: the run deadline, the hand-back, the continuation and the halt
(L4-IMP-066 to L4-IMP-071 and L4-IMP-075, SCN-IMP-332 to SCN-IMP-349, SCN-IMP-360 to SCN-IMP-368, SCN-IMP-377 to
SCN-IMP-379)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def _in_order(text: str, markers: list[str], after: str, before: str) -> None:
    positions = [text.index(marker) for marker in markers]
    assert positions == sorted(positions) and len(set(positions)) == len(positions)
    assert text.index(after) < positions[0] and positions[-1] < text.index(before)


def _scenarios(first: int, last: int) -> list[str]:
    return [f"#### SCN-IMP-{n} " for n in range(first, last + 1)]


def test_the_spec_has_the_deadline_requirements_and_scenarios_in_order() -> None:
    spec = read("docs", "SPEC.md")
    ids = [f"**L4-IMP-{n:03d}** " for n in (65, 66, 67, 68, 69, 70, 71, 75)]
    _in_order(spec, ids[1:], ids[0], "## 8. Agent and model factory")
    scenarios = [*_scenarios(332, 349), *_scenarios(360, 368), *_scenarios(377, 379)]
    _in_order(spec, scenarios, "#### SCN-IMP-331 ", "### 23.8 ")
    for n, requirement in ((332, 66), (339, 68), (345, 70), (348, 71), (377, 75)):
        title = spec.split(f"#### SCN-IMP-{n} ", 1)[1].split("\n", 1)[0]
        assert title.endswith(f"· L4-IMP-0{requirement}"), title
    block = spec.split("#### SCN-IMP-348 ", 1)[1].split("\n####", 1)[0]
    assert "- **Given**" in block and "- **When**" in block and "- **Then**" in block


def _paragraph(text: str, start: str) -> str:
    return text.split(start, 1)[1].split("\n\n", 1)[0]


def test_the_spec_amendments_are_made() -> None:
    spec = read("docs", "SPEC.md")
    imp012 = spec.split("**L4-IMP-012** ", 1)[1].split("\n---\n", 1)[0]
    for gone in ("the SIGINT of a running agent", "the estimate per phase", "the continuation dispatch"):
        assert gone not in imp012, gone
    assert "WIP" in imp012.split("*Still to do:*", 1)[1]
    for done in ("L4_JOB_STARTED_AT", "step.timed", "deadline.reached", "deadline_repeated"):
        assert done in imp012.split("*Implemented now:*", 1)[1].split("*Still to do:*", 1)[0], done
    scn19 = spec.split("#### SCN-IMP-19 ", 1)[1].split("\n####", 1)[0]
    then = scn19.split("**Then**", 1)[1]
    assert "the ledger and the unit branch are pushed" in then and "WIP snapshot stays local until M2" in then
    ci004 = _paragraph(spec, "**L4-CI-004** ")
    assert "10, 11, 12 or 13" in ci004 and "pipeline" in ci004 and "until forge-and-ci 2.6" not in ci004
    margin = next(line for line in spec.splitlines() if line.lstrip().startswith("soft_deadline_margin: 20m"))
    assert "longest call that cannot be stopped" in margin


def test_the_changelog_has_the_deadline_lines_under_0_4_19() -> None:
    changelog = read("CHANGELOG.md")
    head = changelog.split("## 0.4.19 (unreleased)", 1)[1].split("\n## ", 1)[0]
    assert changelog.index("## 0.4.19 (unreleased)") < changelog.index("## 0.4.18 (2026-10-20)")
    for needle in ("L4_JOB_STARTED_AT", "deadline.reached", "deadline_repeated", "soft deadline:", "limit_runs",
                   "count across runs"):  # fmt: skip
        assert needle in head, needle


def test_the_runbook_says_what_the_soft_deadline_does() -> None:
    section = read("docs", "runbook.md").split("- The soft deadline is `ci.time_budget`", 1)[1].split("\n## ", 1)[0]
    flat = " ".join(section.split())
    for needle in ("Before each step", "SIGINT", "does not count as an attempt", "deadline_repeated"):
        assert needle in flat, needle
    assert "only between units" not in section
