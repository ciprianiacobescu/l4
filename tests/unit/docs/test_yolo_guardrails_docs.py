"""The docs of yolo-guardrails, part A: the probe bounds (L4-AVL-012, SCN-AVL-21 to SCN-AVL-25)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def test_the_spec_has_the_probe_requirement_and_its_scenarios() -> None:
    spec = read("docs", "SPEC.md")
    assert spec.index("**L4-AVL-011** ") < spec.index("**L4-AVL-012** ")
    positions = [spec.index(f"#### SCN-AVL-{n} ") for n in range(20, 26)]
    assert positions == sorted(positions)
    config = spec.split("availability:\n", 1)[1].split("\n\n", 1)[0]
    assert "probe_step_timeout: 20s" in config
    table = spec.split("**L4-AVL-001** ", 1)[1].split("**L4-AVL-002**", 1)[0]
    assert table.count("probe_step_timeout") >= 3  # the binary, auth and quota rows


def test_the_changelog_has_the_gate_and_the_probe_fix_under_0_4_18() -> None:
    changelog = read("CHANGELOG.md")
    assert "## 0.4.20 (unreleased)" not in changelog
    head = changelog.split("## 0.4.18 (unreleased)", 1)[1].split("\n## ", 1)[0]
    for needle in ("probe_step_timeout", "did not answer within", "OpenCode v2", "unsupported_version"):
        assert needle in head, needle


def test_the_runbook_names_the_probe_timeout() -> None:
    section = read("docs", "runbook.md").split("### 7.4 ", 1)[1].split("### 7.5 ", 1)[0]
    assert "did not answer within" in section and "l4 doctor" in section
