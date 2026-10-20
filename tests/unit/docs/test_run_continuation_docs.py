"""The docs of run-continuation: part A, the run deadline, the hand-back, the continuation and the halt (L4-IMP-066 to
L4-IMP-071 and L4-IMP-075, SCN-IMP-332 to SCN-IMP-349, SCN-IMP-360 to SCN-IMP-368, SCN-IMP-377 to SCN-IMP-379); part B,
the relay, the base's warning and `l4 yolo status` (L4-IMP-072 to L4-IMP-074)."""

import re
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


def flat(text: str) -> str:
    return " ".join(text.split())


def test_the_spec_has_the_relay_and_status_requirements() -> None:
    spec = read("docs", "SPEC.md")
    # the requirements of part A (L4-IMP-071 before, L4-IMP-075 after) are checked where they exist
    marks = [spec.find(f"**L4-IMP-0{n}** ") for n in range(71, 76)]
    found = [m for m in marks if m >= 0]
    assert found == sorted(found)
    assert 0 < marks[1] < marks[2] < marks[3]  # 072, 073, 074 in order
    assert spec.index("**L4-IMP-065** ") < marks[1]
    part2 = spec.split("# Part II", 1)[1]
    before = part2.index("### 23.8 ")
    last = -1
    for n in [*range(350, 360), *range(369, 377), *range(380, 385)]:
        at = part2.find(f"#### SCN-IMP-{n} ")
        assert 0 <= at < before, n
        assert at > last, n
        last = at
    ado = spec.split("**L4-ADO-005** ", 1)[1].split("\n**", 1)[0]
    assert "L4-IMP-072" in ado and "L4-IMP-074" in ado
    yolo = spec.split("**L4-YOLO-030** ", 1)[1].split("\n**", 1)[0]
    assert "ended without a record" in yolo and "nothing is running or queued" in yolo
    assert "| 56 | `run-continuation` |" in spec


def test_the_runbook_and_the_yolo_doc_say_what_needs_the_copy() -> None:
    runbook = flat(read("docs", "runbook.md"))
    assert "ended without a record" in runbook and "gh workflow run l4.yml --ref" in runbook
    assert "copy .github/workflows/l4.yml to the default branch once (or promote the base)" in runbook
    doc = flat(read("docs", "yolo-mode.md"))
    assert "relay" in doc and "copy .github/workflows/l4.yml to the default branch once" in doc


def test_the_skill_error_table_has_the_three_rows() -> None:
    table = read("plugins", "l4", "skills", "l4", "references", "operate.md")
    for needle in ("ended without a record", "nothing is running or queued", "deadline_repeated"):
        assert needle in table, needle


def test_the_changelog_names_the_relay_the_copy_and_the_status() -> None:
    changelog = read("CHANGELOG.md")
    assert re.search(r"^## 0\.4\.19 \(unreleased\)$", changelog, re.M)
    head = flat(changelog.split("## 0.4.19 (unreleased)", 1)[1].split("\n## ", 1)[0])
    for needle in (
        "relay", "before the configuration", "copy .github/workflows/l4.yml to the default branch once",
        "ended without a record",
    ):  # fmt: skip
        assert needle in head, needle
    assert changelog.index("## 0.4.19 (unreleased)") < changelog.index("## 0.4.18 (")
