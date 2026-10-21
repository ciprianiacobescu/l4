"""scripts/dev/release_notes.py prints one version's CHANGELOG section (L4-ACT-006, SCN-ACT-11, SCN-ACT-14)."""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "dev" / "release_notes.py"
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"

CHANGELOG = """# Changelog

## 0.4.19 (2026-10-21)

### Added
- nineteen

## 0.4.1 (2026-10-01)

### Fixed
- one

## 0.4.0 (2026-09-30)

- zero
"""


def run(tmp_path: Path, version: str, text: str | None = CHANGELOG):
    path = tmp_path / "CHANGELOG.md"
    if text is not None:
        path.write_text(text, encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--version", version, "--changelog", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_middle_section(tmp_path: Path) -> None:
    done = run(tmp_path, "0.4.1")
    assert done.returncode == 0, done.stderr
    assert done.stdout == "### Fixed\n- one\n"


def test_last_section_to_eof(tmp_path: Path) -> None:
    done = run(tmp_path, "0.4.0")
    assert done.returncode == 0, done.stderr
    assert done.stdout == "- zero\n"


def test_exact_version_match(tmp_path: Path) -> None:
    assert "nineteen" in run(tmp_path, "0.4.19").stdout
    assert "nineteen" not in run(tmp_path, "0.4.1").stdout
    done = run(tmp_path, "0.4")
    assert done.returncode == 1


def test_unreleased_refused(tmp_path: Path) -> None:
    done = run(tmp_path, "0.4.19", "## 0.4.19 (unreleased)\n\n- x\n")
    assert done.returncode == 1
    assert done.stdout == ""
    assert done.stderr.startswith("error:") and len(done.stderr.strip().splitlines()) == 1
    assert "date the section: `## 0.4.19 (YYYY-MM-DD)`" in done.stderr


def test_missing_heading_refused(tmp_path: Path) -> None:
    done = run(tmp_path, "0.9.9")
    assert done.returncode == 1
    assert done.stderr.startswith("error:") and len(done.stderr.strip().splitlines()) == 1
    assert "## 0.9.9 (YYYY-MM-DD)" in done.stderr and "tag again" in done.stderr


def test_empty_body_refused(tmp_path: Path) -> None:
    done = run(tmp_path, "0.4.19", "## 0.4.19 (2026-10-21)\n\n\n## 0.4.18 (2026-10-20)\n\n- x\n")
    assert done.returncode == 1
    assert done.stderr.startswith("error:") and "empty" in done.stderr


def test_missing_file_refused(tmp_path: Path) -> None:
    done = run(tmp_path, "0.4.19", None)
    assert done.returncode == 1
    assert done.stderr.startswith("error:") and "CHANGELOG.md" in done.stderr


def test_real_changelog_0_4_18() -> None:
    done = subprocess.run(
        [sys.executable, str(SCRIPT), "--version", "0.4.18", "--changelog", str(ROOT / "CHANGELOG.md")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.startswith("### Added")


def test_workflow_order_and_notes() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    version = text.index("- name: Version from the tag")
    notes = text.index("- name: Release notes from CHANGELOG.md")
    build = text.index("- name: Build the release commit")
    refuse = text.index("- name: Refuse a source commit with a failed check")
    assert version < notes < refuse < build
    assert "::error::" in text[notes:refuse]
    release = text[text.index("- name: GitHub release") :]
    start = release.index("{\n") + 2
    first = release[start:].lstrip().splitlines()[0]
    assert "changelog-section.md" in first and first.lstrip().startswith("cat ")
    assert re.search(r"echo '---'|echo \"---\"", release)
