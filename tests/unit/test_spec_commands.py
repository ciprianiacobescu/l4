"""Every command in the dispatch table has a row in SPEC 2.1 (M1.14 line 43: `eval` was the one that did not)."""

import re
from pathlib import Path

from l4.commands import HANDLERS

SPEC = (Path(__file__).resolve().parents[2] / "docs" / "SPEC.md").read_text(encoding="utf-8")


def section_2_1() -> str:
    return SPEC.split("### 2.1 Commands", 1)[1].split("### 2.2", 1)[0]


def test_every_handler_has_a_row_in_section_2_1() -> None:
    rows = [line for line in section_2_1().splitlines() if line.startswith("| `l4 ")]
    for name in HANDLERS:
        assert any(re.match(rf"\| `l4 {re.escape(name)}[ `]", row) for row in rows), f"no row for `l4 {name}`"


def test_eval_has_its_row_and_exit_15_its_line() -> None:
    assert "| `l4 eval " in section_2_1()
    assert "| 15 | `regression` |" in SPEC


def test_the_template_lock_item_points_at_the_eval() -> None:
    assert "run `l4 eval --compare`" in SPEC.split("## 20. Testing strategy", 1)[1].split("## 21.", 1)[0]
