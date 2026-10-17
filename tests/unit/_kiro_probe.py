"""The probe of kiro-prompt-context as a test fixture: a Kiro spec `.kiro/specs/tip-calc/` and its steering, byte for
byte the repository on which harness 0.4.14 was seen to drop a Kiro unit's criteria text behind a long design."""

import shutil
from pathlib import Path

PROBE = Path(__file__).resolve().parents[1] / "fixtures" / "kiro_probe"
UNIT_REL = ".kiro/specs/tip-calc"
LONG_DESIGN_CHARS = 125_492
PROBE_IDS = {"1.1": "C-1a9abc58", "1.2": "C-41bc8f70"}  # the ids 0.4.14 rendered for the probe


def long_design() -> str:
    """The short design's two lines, a blank line, then 1,100 `## Component N` sections: 125,492 characters."""
    short = (PROBE / UNIT_REL / "design.md").read_text(encoding="utf-8").splitlines()
    sections = "".join(
        f"## Component {i}\nThis section describes component {i} in detail with interfaces, data models and error "
        "handling. \n"
        for i in range(1100)
    )
    text = ("\n".join(short[:2]) + "\n\n" + sections)[:-1]
    assert len(text) == LONG_DESIGN_CHARS
    return text


def probe_tree(tmp_path: Path, *, long: bool = False) -> Path:
    """Copy the fixture into `tmp_path` and return it; `long` writes the 125,492-character design."""
    shutil.copytree(PROBE / ".kiro", tmp_path / ".kiro", dirs_exist_ok=True)
    if long:
        (tmp_path / UNIT_REL / "design.md").write_text(long_design(), encoding="utf-8")
    return tmp_path
