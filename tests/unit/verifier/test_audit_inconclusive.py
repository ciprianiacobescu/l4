"""Step 4a with an audit run that could not decide (L4-VER-050, L4-VER-009; SCN-VER-150, 155): the test is recorded
`inconclusive`, nothing is rejected, no finding is raised, and a real decorator factory no longer breaks the run."""

from l4.implementer.discrimination import PreSatisfied
from l4.implementer.tdd import run_setup
from l4.specs.base import Criterion, Framework
from l4.verifier import audit as audit_module
from l4.verifier.audit import run_audit
from l4.verifier.report import render_verification_md
from l4.verifier.types import AuditRecord, Verdict, VerifyResult

from .test_audit import CID, Replies

REASON = (
    "the test-presatisfied run ran no test (exit 2, 45 collection errors): "
    "E   TypeError: 'NoneType' object is not callable"
)
TOTAL = "from pytdd.pricing import total\n\n\ndef test_x():\n    assert total([1.0]) == 1.0\n"
STORE = "from pytdd.store import Store\n\n\ndef test_add():\n    assert Store().add(1, 2) == 3\n"
TELEMETRY = """\
from collections.abc import Callable
from typing import Any, TypeVar

_F = TypeVar("_F", bound=Callable[..., Any])


def traced(name: str) -> Callable[[_F], _F]:
    def decorate(fn: _F) -> _F:
        return fn

    return decorate
"""
STORE_SRC = """\
from pytdd import telemetry


class Store:
    @telemetry.traced("store.add")
    def add(self, a: int, b: int) -> int:
        return a + b
"""


def audit_once(make_bench, code: str, *, files: dict[str, str] | None = None):
    bench = make_bench([])
    for path, text in (files or {}).items():
        (bench.wb.worktree / path).write_text(text)
    run_setup(bench.wb)
    criterion = Criterion(CID, "a > b > c", Framework.OPENSPEC, "pricing", "b", "c", "WHEN x THEN y", "specs/x.md", 1)
    out = run_audit(
        bench.wb, Replies({"criterion": CID, "code": code}), {CID: criterion}, [CID], [], base_sha="HEAD", head="HEAD",
        round_no=1, timeout_s=5, emit=lambda kind, **data: None,
    )  # fmt: skip
    return bench, out


def test_scn_ver_150_an_inconclusive_audit_run_is_not_a_rejection(make_bench, monkeypatch):
    monkeypatch.setattr(
        audit_module,
        "confirm_pre_satisfied",
        lambda wb, candidates, *, real=None: PreSatisfied(inconclusive={c: REASON for c in candidates}),
    )
    bench, out = audit_once(make_bench, TOTAL)
    [record] = out.records
    assert (record.criterion, record.status) == (CID, "inconclusive")
    assert "E   TypeError: 'NoneType' object is not callable" in record.reason
    assert out.findings == [] and out.accepted == []
    assert not (bench.wb.worktree / record.test_path).exists()  # the file is removed
    result = VerifyResult("openspec:u", 1, Verdict.NEEDS_HUMAN, "", "abc")
    result.audit = list(out.records)
    text = render_verification_md(result)
    assert f"| {CID} | inconclusive |" in text
    section = text.partition("## Inconclusive audit runs")[2].partition("\n## ")[0]
    assert CID in section and "TypeError" in section


def test_a_not_applicable_audit_test_is_accepted_with_its_label(make_bench, monkeypatch):
    monkeypatch.setattr(
        audit_module,
        "confirm_pre_satisfied",
        lambda wb, candidates, *, real=None: PreSatisfied(not_applicable={c: tuple(t) for c, t in candidates.items()}),
    )
    _, out = audit_once(make_bench, TOTAL)
    [record] = out.records
    assert (record.status, record.reason) == ("accepted", "not applicable: no project code")
    assert len(out.accepted) == 1 and out.findings == []


def test_scn_ver_155_the_audits_zero_value_run_keeps_a_decorator_factory(make_bench):
    files = {"src/pytdd/telemetry.py": TELEMETRY, "src/pytdd/store.py": STORE_SRC}
    _, out = audit_once(make_bench, STORE, files=files)
    assert [(r.criterion, r.status) for r in out.records] == [(CID, "accepted")], out.records
    assert out.findings == []


def test_the_record_type_names_inconclusive():
    assert "inconclusive" in (AuditRecord.__doc__ or "")
