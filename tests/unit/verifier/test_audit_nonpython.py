"""Step 4a writes pytest tests only: a unit whose changed files hold no Python is `not_run`, with no writer call, no
finding and no file written (SPEC L4-VER-002 step 4a, SCN-VER-58)."""

from types import SimpleNamespace

import pytest

from l4.config.schema import L4Config
from l4.vcs.git import Git
from l4.verifier import ladder

IDENT = ("-c", "user.name=t", "-c", "user.email=t@example.invalid")
NOTE = "audit sampling writes pytest tests only; changed code is not python"


def _repo(tmp_path, files: dict[str, str]):
    git = Git(tmp_path)
    git.run("init", "--quiet")
    (tmp_path / "openspec/changes/u").mkdir(parents=True)
    (tmp_path / "openspec/changes/u/proposal.md").write_text("x\n")
    git.run("add", "-A")
    git.run(*IDENT, "commit", "-qm", "base")
    base = git.rev_parse("HEAD")
    for rel, text in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(text)
    git.run("add", "-A")
    git.run(*IDENT, "commit", "-qm", "head")
    return git, base, git.rev_parse("HEAD")


def _step(tmp_path, files, monkeypatch):
    git, base, head = _repo(tmp_path, files)
    calls: list[str] = []
    wb = SimpleNamespace(
        cfg=L4Config(), git=git, worktree=tmp_path, ref=SimpleNamespace(path=tmp_path / "openspec/changes/u", id="u"),
        emit=lambda *a, **k: None,
    )  # fmt: skip
    vc = SimpleNamespace(wb=wb, round=1, audit_writer=lambda: calls.append("writer"))
    run = SimpleNamespace(records={}, result=SimpleNamespace(head_sha=head, trace=[], findings=[], subject_sha=head))
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
