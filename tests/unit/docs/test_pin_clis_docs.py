"""The docs of pin-clis: the pinned agent CLIs (L4-PRV-042 to L4-PRV-046, L4-OCG-005, SCN-PRV-113 to SCN-PRV-128)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def test_the_spec_has_the_requirements_and_scenarios() -> None:
    spec = read("docs", "SPEC.md")
    ids = [spec.index(f"**L4-PRV-0{n} ") for n in range(42, 47)]
    assert ids == sorted(ids)
    assert ids[-1] < spec.index("| ENV-015 |")
    assert spec.index("**L4-OCG-004 ") < spec.index("**L4-OCG-005 ")
    prv = [spec.index(f"#### SCN-PRV-{n} ") for n in range(113, 129)]
    ocg = [spec.index(f"#### SCN-OCG-{n} ") for n in range(11, 15)]
    assert prv == sorted(prv) and ocg == sorted(ocg)
    config = spec.split("### 3.2 ", 1)[1].split("\n### 3.3 ", 1)[0]
    assert "cli_versions: {}" in config
    assert "| ENV-015 |" in spec
    assert "| 57 | `pin-clis` |" in spec


def test_the_runbook_has_the_kiro_gate_and_the_versions_section() -> None:
    runbook = read("docs", "runbook.md")
    s74 = runbook.split("### 7.4 ", 1)[1].split("### 7.5 ", 1)[0]
    assert "is Kiro CLI 3; L4 runs Kiro CLI 2" in s74
    s107 = runbook.split("### 10.7 ", 1)[1].split("\n## ", 1)[0]
    for needle in ("ci.cli_versions", "ENV-015", "l4 doctor --ci --fix", "l4 doctor --fix", "min_version"):
        assert needle in s107, needle
    assert "replaces only a CLI below its `min_version`" in s107
    assert "harness.delivery: action" in s107


def test_the_runner_readme_has_prq12_and_prq21() -> None:
    readme = read("docs", "runner", "README.md")
    row12 = next(line for line in readme.splitlines() if line.startswith("| PRQ-12 |"))
    assert "sha256sum" in row12 and "versioned" in row12 and "cli.kiro.dev/install" not in row12
    row21 = next(line for line in readme.splitlines() if line.startswith("| PRQ-21 |"))
    assert "DISABLE_AUTOUPDATER" in row21 and "app.disableAutoupdates" in row21
    assert "PRQ-20" in readme and "reserved" in readme


def test_the_skill_names_the_pins() -> None:
    base = ("plugins", "l4", "skills", "l4", "references")
    adopt = read(*base, "adopt.md")
    assert "ci.cli_versions" in adopt and "move the pin before" in adopt.lower()
    section = adopt.split("## 4d. ", 1)[1].split("\n## ", 1)[0]
    assert "2.32.0 or newer" not in section and "a Kiro CLI 3 is refused" in section
    operate = read(*base, "operate.md")
    assert "is Kiro CLI 3; L4 runs Kiro CLI 2" in operate
    assert "pinned" in operate and "ENV-015" in operate
    assert "ci.cli_versions:" in operate and "does not match the published" in operate


def test_the_changelog_names_the_pins() -> None:
    changelog = read("CHANGELOG.md")
    assert changelog.index("## 0.4.20 (unreleased)") < changelog.index("## 0.4.19 (")
    head = changelog.split("## 0.4.20 (unreleased)", 1)[1].split("\n## ", 1)[0]
    for needle in ("2.32.0", "ci.cli_versions", "DISABLE_AUTOUPDATER", "Kiro CLI 3", "ENV-015", "kiro-cli update"):
        assert needle in head, needle


def test_the_runner_prerequisites_are_one_table() -> None:  # R5
    lines = read("docs", "runner", "README.md").splitlines()
    first = next(i for i, ln in enumerate(lines) if ln.startswith("| PRQ-01 |"))
    start = first
    while lines[start - 1].startswith("|"):
        start -= 1
    end = first
    while lines[end].startswith("|"):
        end += 1
    table = lines[start:end]
    assert all(ln.startswith("| PRQ-") for ln in table[2:]) and len(table) > 20
    assert {"PRQ-12", "PRQ-17", "PRQ-21"} <= {ln.split(" | ")[0].strip("| ") for ln in table}
    assert not any(ln.startswith("| PRQ-") for ln in lines[end:])  # no row after the table is broken off
    assert lines[end] == "" and lines[end + 1].startswith("PRQ-20 is reserved")


def test_the_skill_names_the_release_that_brings_the_pin() -> None:  # R6
    adopt = read("plugins", "l4", "skills", "l4", "references", "adopt.md")
    section = adopt.split("## 4d. ", 1)[1].split("\n## ", 1)[0]
    assert "harness 0.4.20, kiro-cli 2.32.0" in section and "harness 0.4.19, kiro-cli" not in section


def test_the_docs_name_the_kiro_digest_and_the_refused_download() -> None:  # R8, R9
    operate = read("plugins", "l4", "skills", "l4", "references", "operate.md")
    runbook = read("docs", "runbook.md")
    for text in (operate, runbook):
        assert "does not match the harness's digest" in text and "that version may no longer be served" in text
        assert "ci.cli_versions" in text.split("that version may no longer be served", 1)[1][:400]
