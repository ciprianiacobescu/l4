"""`items_from_evidence` reads code, tests and the proposal from git blobs (like `collect.py`), not from the worktree:
a symlink or an edit in the working tree cannot put other text into a state (and so into training data)."""

import os
from pathlib import Path

from l4.config.schema import L4Config
from l4.evidence.collect import collect_evidence
from l4.gates.junit import TestCase, TestReport
from l4.redact import Redactor
from l4.s1 import questions as q
from l4.s1.items import items_from_evidence
from l4.specs.base import Framework, UnitRef

from ..evidence.test_root_files import Bench, _cov_dir, _repo

SRC = "def total(a):\n    b = a + 1\n    c = b + 1\n    return c\n"
TEST = "from shop.cart import total\n\n\ndef test_total():\n    assert total(1) == 3\n"
SECRET = "SECRET-OUTSIDE-THE-REPOSITORY"


def build(tmp_path: Path):
    git, base, head = _repo(tmp_path / "r", {}, {"src/shop/cart.py": SRC, "tests/test_cart.py": TEST})
    cfg = L4Config()
    _cov_dir(
        tmp_path / "cov", {"src/shop/cart.py": {"executed_lines": [1, 2, 3, 4], "missing_lines": [], "contexts": {}}}
    )
    ref = UnitRef(Framework.OPENSPEC, "u", tmp_path / "r" / "specs" / "u")
    report = TestReport({"tests.test_cart::test_total": TestCase("tests.test_cart::test_total", "passed")})
    wb = Bench(git, cfg, tmp_path / "r")
    ev = collect_evidence(
        wb, base, head, report, tmp_path / "cov", ref, new_tests={"tests.test_cart::test_total"},
        gate_passed=True, cov_nonce="n1",
    )  # fmt: skip

    def items():
        return items_from_evidence(
            ev, git=git, cfg=cfg, redactor=Redactor({}), project="p", unit_id="openspec:u",
            unit_name="u", spec_dir="specs/u", base=base, head=head, report=report,
            new_tests={"tests.test_cart::test_total"}, origin="live", run_id="R", round=1,
        )  # fmt: skip

    return tmp_path / "r", items


def test_a_tampered_worktree_changes_no_state(tmp_path: Path):
    root, items = build(tmp_path)
    clean = items()
    assert {i.question_set for i in clean} >= {q.CHANGE_COVERED, q.TESTS_OK}
    secret = tmp_path / "secret.txt"
    secret.write_text(SECRET)
    (root / "src/shop/cart.py").write_text("def total(a):\n    return 'edited in the worktree'\n")
    (root / "tests/test_cart.py").unlink()
    os.symlink(secret, root / "tests/test_cart.py")  # a test file that is a link to a file outside the repository
    (root / "specs/u/proposal.md").unlink()
    os.symlink(secret, root / "specs/u/proposal.md")
    tampered = items()
    assert [(i.item_key, i.state) for i in tampered] == [(i.item_key, i.state) for i in clean]
    assert not any(SECRET in i.state or "edited in the worktree" in i.state for i in tampered)
