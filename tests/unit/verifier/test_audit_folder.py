"""L4-VER-090 (audit-writer-chain): the audit test goes next to the unit's own Python tests only when step 3's unit-gate
report shows them; otherwise the audit confirms that the test command collects the file."""

from l4.gates.junit import TestCase, TestReport
from l4.specs.base import Criterion, Framework
from l4.verifier import audit as audit_module
from l4.verifier.audit import red_test_directory, run_audit

from ..implementer.test_fix_chore_e2e import commit_files
from .test_audit import CID, Replies

TEST = "def test_n():\n    assert 1\n"
CODE = "def test_audit():\n    assert 1\n"
WRITER_REPLY = {"criterion": CID, "code": CODE}


def report(*ids: str) -> TestReport:
    return TestReport({i: TestCase(i, "passed") for i in ids})


def changed(bench, files: dict[str, str]) -> tuple[str, str]:
    base = bench.wb.head()
    commit_files(bench, files)
    return base, bench.wb.head()


def audit_in(bench, base: str, head: str, *, rep, monkeypatch, collected: bool = True):
    """`run_audit` for one criterion with the unit-gate run stubbed: -> (the folder checks made, the path written)."""
    checks: list[str] = []
    paths: list[str] = []

    def confirm(wb, rel):
        checks.append(rel)
        return collected

    monkeypatch.setattr(audit_module, "confirm_collected", confirm)
    monkeypatch.setattr(audit_module, "_judge_written", lambda wb, written, *a, **k: paths.extend(written.values()))
    criterion = Criterion(CID, "a > b > c", Framework.OPENSPEC, "pricing", "b", "c", "WHEN x THEN y", "specs/x.md", 1)
    run_audit(
        bench.wb, Replies(WRITER_REPLY), {CID: criterion}, [CID], [], base_sha=base, head=head, round_no=1,
        timeout_s=5, emit=lambda *a, **k: None, report=rep,
    )  # fmt: skip
    return checks, paths


def test_scn_ver_360_the_audit_file_goes_where_the_report_shows_the_units_tests(make_bench, monkeypatch):
    bench = make_bench([])
    base, head = changed(
        bench,
        {"src/a.py": "A = 1\n", "tests/test_a.py": TEST, "e2e/test_x.py": TEST, "e2e/test_y.py": TEST},
    )
    assert red_test_directory(bench.wb, base, head, report("tests.test_a::test_n")) == "tests"
    checks, paths = audit_in(bench, base, head, rep=report("tests.test_a::test_n"), monkeypatch=monkeypatch)
    assert checks == [] and paths == [f"tests/test_l4_audit_c_{CID.removeprefix('C-')}_r1.py"]


def test_scn_ver_361_a_folder_the_report_does_not_show_is_confirmed_first(make_bench, monkeypatch):
    bench = make_bench([])
    base, head = changed(bench, {"src/a.py": "A = 1\n", "e2e/test_x.py": TEST, "e2e/test_y.py": TEST})
    rep = report("tests.test_a::test_n")  # the unit gate runs tests/ only
    assert red_test_directory(bench.wb, base, head, rep) is None
    checks, paths = audit_in(bench, base, head, rep=rep, monkeypatch=monkeypatch, collected=False)
    assert len(checks) == 1 and "test_l4_audit_c_" in checks[0]  # the audit-collect-check, before the file is kept
    assert not checks[0].startswith("e2e/")  # the folder of the unit's own e2e tests was not trusted
    assert paths == [f"tests/test_l4_audit_c_{CID.removeprefix('C-')}_r1.py"]  # not collected: written under tests/


def test_a_confirmed_folder_is_kept(make_bench, monkeypatch):
    bench = make_bench([])
    base, head = changed(bench, {"src/a.py": "A = 1\n", "e2e/test_x.py": TEST})
    checks, paths = audit_in(bench, base, head, rep=report("e2e.test_x::test_n"), monkeypatch=monkeypatch)
    assert checks == [] and paths[0].startswith("e2e/")  # the report shows the file: it is collected


def test_without_a_report_no_folder_is_trusted(make_bench):
    bench = make_bench([])
    base, head = changed(bench, {"tests/test_a.py": TEST})
    assert red_test_directory(bench.wb, base, head, None) is None
