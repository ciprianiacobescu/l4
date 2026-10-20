"""The docs of run-continuation, part B: the relay, the base's warning and `l4 yolo status` (L4-IMP-072 to L4-IMP-074).
Part A (the deadline, L4-IMP-066 to L4-IMP-071 and L4-IMP-075) adds its own tests to this file."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


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
