"""The red guard and `if TYPE_CHECKING:` import blocks (SPEC L4-IMP-002 (iii): imports for a stub are admissible).

Live finding, job 5537 (M1.6 live exit, `add-bulk-discount`): Codex stubbed `bulk_discount(cart: Cart)` in
`src/pricing/discounts.py` and imported `Cart` under `if TYPE_CHECKING:` (a plain import would be circular: `cart.py`
imports `discounts.py`). The guard kept `from typing import TYPE_CHECKING` and the stub but dropped the block, so the
rebuilt file failed the lint gate (F401 `TYPE_CHECKING` unused, F821 `Cart` undefined) on all three red attempts.
"""

import ast
import shutil
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest

from l4.implementer.stubs import classify_red_changes

HEAD = dedent(
    """\
    from __future__ import annotations

    from dataclasses import dataclass
    from decimal import Decimal


    @dataclass(frozen=True)
    class PercentOff:
        percent: Decimal
    """
)

AGENT = dedent(
    """\
    from __future__ import annotations

    from dataclasses import dataclass
    from decimal import Decimal
    from typing import TYPE_CHECKING

    if TYPE_CHECKING:
        from pricing.cart import Cart


    @dataclass(frozen=True)
    class PercentOff:
        percent: Decimal


    def bulk_discount(cart: Cart) -> Decimal:
        raise NotImplementedError
    """
)


def _ruff() -> list[str] | None:
    exe = shutil.which("ruff") or str(Path(sys.executable).with_name("ruff"))
    return [exe] if Path(exe).exists() else None


def test_the_live_case_keeps_the_type_checking_block_and_the_file_stays_lint_clean(tmp_path: Path):
    out = classify_red_changes(HEAD, AGENT)
    ast.parse(out.source)
    assert out.restored == (), out.restored
    assert out.stubs == ("bulk_discount",)
    assert "if TYPE_CHECKING:\n    from pricing.cart import Cart\n" in out.source
    assert out.source == AGENT  # the agent's file was already HEAD plus admissible additions
    ruff = _ruff()
    if ruff is None:
        pytest.skip("ruff is not installed next to this interpreter")
    target = tmp_path / "discounts.py"
    target.write_text(out.source, encoding="utf-8")
    run = subprocess.run(
        [*ruff, "check", "--isolated", "--select", "E,F,I,B,UP", "--line-length", "110", str(target)],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    assert run.returncode == 0, run.stdout + run.stderr


def test_typing_dot_type_checking_counts_as_well():
    agent = AGENT.replace("from typing import TYPE_CHECKING", "import typing").replace(
        "if TYPE_CHECKING:", "if typing.TYPE_CHECKING:"
    )
    out = classify_red_changes(HEAD, agent)
    assert out.restored == () and "if typing.TYPE_CHECKING:\n    from pricing.cart import Cart\n" in out.source


@pytest.mark.parametrize(
    "block",
    [
        "if TYPE_CHECKING:\n    from pricing.cart import Cart\n    LIMIT = 10\n",  # not only imports
        "if TYPE_CHECKING:\n    from pricing.cart import Cart\nelse:\n    Cart = object\n",  # an else branch runs
        "if DEBUG:\n    from pricing.cart import Cart\n",  # not the type-checking flag
    ],
)
def test_a_block_that_is_more_than_type_only_imports_is_not_applied(block: str):
    agent = AGENT.replace("if TYPE_CHECKING:\n    from pricing.cart import Cart\n", block)
    out = classify_red_changes(HEAD, agent)
    ast.parse(out.source)
    assert block not in out.source
    assert any("was not applied" in r for r in out.restored), out.restored


HEAD_WITH_BLOCK = HEAD.replace(
    "from decimal import Decimal\n",
    "from decimal import Decimal\nfrom typing import TYPE_CHECKING\n\n"
    "if TYPE_CHECKING:\n    from pricing.cart import Cart\n",
)


def test_an_import_added_to_an_existing_type_checking_block_is_kept():
    agent = (
        HEAD_WITH_BLOCK.replace(
            "    from pricing.cart import Cart\n",
            "    from pricing.cart import Cart, LineItem\n    from pricing.web import page\n",
        )
        + "\n\ndef bulk_discount(cart: Cart, item: LineItem) -> Decimal:\n    raise NotImplementedError\n"
    )
    out = classify_red_changes(HEAD_WITH_BLOCK, agent)
    assert out.restored == (), out.restored
    assert "    from pricing.cart import Cart, LineItem\n    from pricing.web import page\n" in out.source
    assert out.source.count("if TYPE_CHECKING:") == 1


def test_removing_an_import_from_an_existing_type_checking_block_is_restored():
    agent = HEAD_WITH_BLOCK.replace("    from pricing.cart import Cart\n", "    from pricing.web import page\n")
    out = classify_red_changes(HEAD_WITH_BLOCK, agent)
    assert out.source == HEAD_WITH_BLOCK
    assert out.restored, "a removed type-checking import must be reported"
