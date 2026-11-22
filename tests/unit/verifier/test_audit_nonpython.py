"""Step 4a writes pytest tests only: a unit whose changed files hold no Python is `not_run`, with no writer call, no
finding and no file written (SPEC L4-VER-002 step 4a, SCN-VER-58)."""

from types import SimpleNamespace

import pytest

from l4.config.schema import L4Config
from l4.gates.junit import TestCase, TestReport
from l4.vcs.git import Git
from l4.verifier import ladder

IDENT = ("-c", "user.name=t", "-c", "user.email=t@example.invalid")
NOTE = "audit sampling writes pytest tests only; changed code is not python"


def _repo(tmp_path, files: dict[str, str], base_files: dict[str, str] | None = None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    git = Git(tmp_path)
    git.run("init", "--quiet")
    (tmp_path / "openspec/changes/u").mkdir(parents=True)
    (tmp_path / "openspec/changes/u/proposal.md").write_text("x\n")
    for rel, text in (base_files or {}).items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    git.run("add", "-A")
    git.run(*IDENT, "commit", "-qm", "base")
    base = git.rev_parse("HEAD")
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    git.run("add", "-A")
    git.run(*IDENT, "commit", "-qm", "head")
    return git, base, git.rev_parse("HEAD")


def _report(*ids: str) -> TestReport:
    return TestReport({i: TestCase(i, "passed") for i in ids})


def _step(tmp_path, files, monkeypatch, *, report=None, base_files: dict[str, str] | None = None):
    """`base_files`: files of the base commit (a test the unit did not change). `report`: step 3's unit-gate report."""
    git, base, head = _repo(tmp_path, files, base_files)
    calls: list[str] = []
    wb = SimpleNamespace(
        cfg=L4Config(), git=git, worktree=tmp_path, ref=SimpleNamespace(path=tmp_path / "openspec/changes/u", id="u"),
        emit=lambda *a, **k: None,
    )  # fmt: skip
    vc = SimpleNamespace(wb=wb, round=1, audit_writer=lambda: calls.append("writer"))
    run = SimpleNamespace(
        report=report, records={}, result=SimpleNamespace(head_sha=head, trace=[], findings=[], subject_sha=head)
    )
    monkeypatch.setattr(ladder, "_emit_step", lambda *a, **k: None)
    monkeypatch.setattr(ladder, "run_audit", lambda *a, **k: pytest.fail("the writer must not be asked"))
    ladder._audit_step(vc, run, [], base)
    return run, calls


def test_a_typescript_unit_records_not_run_without_writing_anything(tmp_path, monkeypatch):
    files = {"services/engine.ts": "export const a = 1;\n", "services/engine.test.ts": "test('a', () => {});\n"}
    run, calls = _step(tmp_path, files, monkeypatch)
    record = run.records["4a"]
    assert (record.status, record.note) == ("not_run", NOTE)
    assert calls == [] and run.result.findings == []
    assert not list(tmp_path.glob("tests/test_l4_audit_*"))


def test_a_unit_with_a_python_file_still_audits(tmp_path, monkeypatch):
    run, _ = _step(tmp_path, {"src/a.py": "A = 1\n", "web/app.ts": "1\n"}, monkeypatch)
    assert run.records["4a"].status == "ok" and run.records["4a"].note == "no covered new criterion to audit"


# --- L4-VER-089: Python test files of another language's unit are no reason to audit (audit-writer-chain) ------------

NODE = _report("web.src.layout.test.ts::a")
PY_TEST = "def test_total():\n    assert 1\n"
RAN = "tests.test_pricing::test_total"


def _note(run) -> str:
    return run.records["4a"].note


def test_scn_ver_356_a_typescript_unit_with_a_changed_python_browser_test_does_not_audit(tmp_path, monkeypatch):
    files = {"web/src/layout.ts": "export const a = 1;\n", "e2e/test_layout.py": PY_TEST}
    run, calls = _step(tmp_path, files, monkeypatch, report=NODE)
    record = run.records["4a"]
    assert record.status == "not_run"
    assert record.note == f"{NOTE} (the changed Python files are tests or test support: e2e/test_layout.py)"
    assert calls == [] and run.result.findings == [] and not list(tmp_path.glob("**/test_l4_audit_*"))


def test_scn_ver_357_a_python_unit_that_changes_only_tests_still_audits(tmp_path, monkeypatch):
    run, _ = _step(tmp_path, {"tests/test_pricing.py": PY_TEST}, monkeypatch, report=_report(RAN))
    assert run.records["4a"].status == "ok" and _note(run) == "no covered new criterion to audit"


def test_scn_ver_358_python_code_next_to_another_language_audits_and_a_support_file_is_not_code(tmp_path, monkeypatch):
    first, _ = _step(tmp_path / "one", {"src/a.py": "A = 1\n", "web/app.ts": "1\n"}, monkeypatch, report=NODE)
    assert first.records["4a"].status == "ok"
    second, _ = _step(tmp_path / "two", {"web/app.ts": "1\n", "tests/conftest.py": "X = 1\n"}, monkeypatch, report=NODE)
    assert second.records["4a"].status == "not_run" and "tests/conftest.py" in _note(second)


def test_scn_ver_359_without_a_report_a_tests_only_unit_audits_as_before(tmp_path, monkeypatch):
    run, _ = _step(tmp_path, {"tests/test_pricing.py": PY_TEST}, monkeypatch, report=None)
    assert run.records["4a"].status == "ok"


def test_scn_ver_370_a_python_unit_that_changes_only_a_support_file_still_audits(tmp_path, monkeypatch):
    run, _ = _step(
        tmp_path, {"tests/conftest.py": "X = 1\n"}, monkeypatch, report=_report(RAN),
        base_files={"tests/test_pricing.py": PY_TEST},
    )  # fmt: skip
    assert run.records["4a"].status == "ok"


def test_scn_ver_371_a_unit_that_changes_only_a_python_browser_test_under_a_node_gate_does_not_audit(
    tmp_path, monkeypatch
):
    run, calls = _step(tmp_path, {"e2e/test_layout.py": PY_TEST}, monkeypatch, report=NODE)
    assert run.records["4a"].status == "not_run" and "e2e/test_layout.py" in _note(run) and calls == []


def test_a_unit_that_changed_nothing_outside_the_exempt_paths_still_audits(tmp_path, monkeypatch):
    run, _ = _step(tmp_path, {"openspec/changes/u/notes.md": "x\n"}, monkeypatch, report=NODE)
    assert run.records["4a"].status == "ok"
