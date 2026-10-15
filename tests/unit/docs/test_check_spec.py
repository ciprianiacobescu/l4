"""scripts/check_spec.py counts every scenario heading of docs/SPEC.md, a lettered id (SCN-ADO-29a) included."""

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_a_scenario_id_with_a_letter_suffix_is_counted() -> None:  # SCN-ADO-29a
    spec = ROOT / "docs" / "SPEC.md"
    headings = re.findall(r"^#### SCN-[A-Z]+-\d+[a-z]? \(", spec.read_text(encoding="utf-8"), re.M)
    assert any(re.match(r"#### SCN-[A-Z]+-\d+[a-z] ", h) for h in headings)  # the spec has lettered ids
    run = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_spec.py"), str(spec)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert run.returncode == 0, run.stdout
    assert f"scenarios: {len(headings)} |" in run.stdout
