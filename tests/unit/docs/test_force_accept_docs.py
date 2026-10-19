"""The docs of force-accept: a person's force acceptance, a person's --yes with prompts on stderr, and the acceptance
binding (L4-YOLO-057 to L4-YOLO-067)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def test_the_spec_has_the_eleven_requirements_and_their_scenarios_in_order() -> None:
    spec = read("docs", "SPEC.md")
    for n in range(57, 68):
        assert f"**L4-YOLO-0{n} " in spec, n
    assert spec.index("**L4-YOLO-056 ") < spec.index("**L4-YOLO-057 ") < spec.index("**L4-YOLO-067 ")
    for n in range(150, 177):
        assert f"#### SCN-YOLO-{n} " in spec, n
    first, last = spec.index("#### SCN-YOLO-150 "), spec.index("#### SCN-YOLO-176 ")
    assert spec.index("#### SCN-YOLO-149 ") < first < last < spec.index("### 23.21 ")
    assert "| 53 | `force-accept` |" in spec
    row = next(line for line in spec.splitlines() if line.startswith("| `l4 yolo accept "))
    assert "--all --force" in row


def test_the_yolo_doc_has_the_section_with_the_risk_and_the_alternative() -> None:
    yolo = read("docs", "yolo-mode.md")
    assert "When the reviewer is unavailable" in yolo
    section = yolo.split("When the reviewer is unavailable", 1)[1].split("\n## ", 1)[0]
    for needle in ("l4 yolo accept <plan> --all --force", "l4 yolo review <plan>", "no model reviewed", "--yes"):
        assert needle in section, needle


def test_the_runbook_has_the_procedure() -> None:
    runbook = read("docs", "runbook.md")
    section = runbook.split("### 12.2a ", 1)[1].split("### 12.2b ", 1)[0]
    for needle in ("When the judge cannot run", "--all --force", "--yes", "plan.force_accepted"):
        assert needle in section, needle


def test_the_skill_keeps_agents_off_the_force_path() -> None:
    for name in ("plan.md", "operate.md"):
        text = read("plugins", "l4", "skills", "l4", "references", name)
        assert "--force" in text and "never" in text.lower(), name
        assert 'l4 yolo accept <id> --all --force --reason "' in text, name


def test_the_changelog_names_the_three_fixes() -> None:
    head = read("CHANGELOG.md").split("## 0.4.18 (unreleased)", 1)[1].split("\n## ", 1)[0]
    for needle in ("plan.force_accepted", "--yes", "stderr", "reused"):
        assert needle in head, needle
