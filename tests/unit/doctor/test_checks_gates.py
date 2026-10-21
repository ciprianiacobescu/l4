"""GATE-001 (M1.8 A3): the gates at HEAD, before the first unit fails on a base that was never green."""

import json

import yaml

from l4.cli import main
from l4.doctor import checks_gates as cg
from l4.doctor.registry import REGISTRY, exit_code, load_check_modules, run_checks
from l4.gates.dryrun import GateDryRun, GateRun

SHA = "0123456789abcdef0123456789abcdef01234567"


def canned(monkeypatch, result: GateDryRun) -> list[bool]:
    seen: list[bool] = []

    def fake(cfg, repo, environ, *, in_ci, **kw):
        seen.append(in_ci)
        return result

    monkeypatch.setattr(cg, "dry_run_gates", fake)
    return seen


def red_base() -> GateDryRun:
    ids = tuple(f"tests.test_a::test_{n:02d}" for n in range(12))
    runs = (
        GateRun("setup", "uv sync --frozen", "pass"),
        GateRun("lint", "ruff check .", "fail", "exit code 1", "F401 `os` imported but unused\nE501 too long"),
        GateRun(
            "test", ".venv/bin/python -m pytest", "fail", "exit code 1", "", ids, ("assert 1 == 2",) * 12, (), 180, 192
        ),
    )
    return GateDryRun(SHA, "bwrap", runs)


def test_gate001_lists_preexisting_failures_and_exits_3(make_ctx, monkeypatch):
    canned(monkeypatch, red_base())
    ctx, _ = make_ctx()
    [outcome] = run_checks(ctx, scopes={"adoption"}, only={"GATE-001"})
    assert outcome.status == "fail" and outcome.severity == "error"
    assert "lint: fail" in outcome.message and "F401 `os` imported but unused" in outcome.message
    assert "test: fail (180/192 passed)" in outcome.message or "12 failing" in outcome.message
    assert "tests.test_a::test_09" in outcome.message and "tests.test_a::test_10" not in outcome.message
    assert "+2 more" in outcome.message  # ten ids at most, then a count
    assert exit_code([outcome]).value == 3


def test_gate001_passes_on_a_green_base(make_ctx, monkeypatch):
    runs = (GateRun("setup", "uv sync", "pass"), GateRun("test", "pytest", "pass", "", "", (), (), (), 41, 41))
    canned(monkeypatch, GateDryRun(SHA, "bwrap", runs))
    ctx, _ = make_ctx()
    [outcome] = run_checks(ctx, scopes={"adoption"}, only={"GATE-001"})
    assert outcome.status == "pass" and "41" in outcome.message
    assert exit_code([outcome]).value == 0


def test_gate001_names_the_head_and_the_sandbox_state(make_ctx, monkeypatch):
    unsandboxed = GateDryRun(SHA, "unsandboxed (bwrap was not found on PATH; your own committed code runs as you)", ())
    canned(
        monkeypatch,
        GateDryRun(SHA, unsandboxed.sandbox, (GateRun("test", "pytest", "pass", "", "", (), (), (), 1, 1),)),
    )
    ctx, _ = make_ctx()
    [outcome] = run_checks(ctx, scopes={"adoption"}, only={"GATE-001"})
    assert "HEAD 0123456789" in outcome.message and "uncommitted changes are not included" in outcome.message
    assert "unsandboxed" in outcome.message


def test_gate001_in_ci_is_told_so(make_ctx, monkeypatch):
    seen = canned(monkeypatch, GateDryRun(SHA, "bwrap", ()))
    ctx, _ = make_ctx(GITLAB_CI="true")
    run_checks(ctx, scopes={"adoption"}, only={"GATE-001"})
    ctx, _ = make_ctx()
    run_checks(ctx, scopes={"adoption"}, only={"GATE-001"})
    assert seen == [True, False]


def test_gate001_a_dry_run_that_could_not_be_made_fails(make_ctx, monkeypatch):
    canned(monkeypatch, GateDryRun(error="no usable gate sandbox in CI (bwrap was not found on PATH)"))
    ctx, _ = make_ctx()
    [outcome] = run_checks(ctx, scopes={"adoption"}, only={"GATE-001"})
    assert outcome.status == "fail" and "no usable gate sandbox" in outcome.message


def test_gate001_skips_when_no_gate_is_configured(make_ctx, monkeypatch):
    canned(monkeypatch, GateDryRun(SHA, "", ()))
    ctx, _ = make_ctx()
    [outcome] = run_checks(ctx, scopes={"adoption"}, only={"GATE-001"})
    assert outcome.status == "skip"


def test_gate001_is_an_error_in_the_adoption_scope_only():
    load_check_modules()
    import l4.doctor.run  # noqa: F401

    check = next(c for c in REGISTRY.checks() if c.id == "GATE-001")
    assert check.severity == "error" and check.scopes == {"adoption"}


def test_doctor_adoption_exits_3_on_a_red_base_and_names_the_test(tdd_repo, raw, capsys):
    (tdd_repo.repo / "tests" / "test_base_failure.py").write_text("def test_base_failure():\n    assert 1 == 2\n")
    raw(tdd_repo.repo, "add", "-A")
    raw(tdd_repo.repo, "commit", "-q", "-m", "red base")
    body = yaml.safe_load(tdd_repo.config())
    (tdd_repo.repo / ".l4").mkdir(exist_ok=True)
    (tdd_repo.repo / ".l4" / "config.yaml").write_text(yaml.safe_dump(body))
    raw(tdd_repo.repo, "add", "-A")
    raw(tdd_repo.repo, "commit", "-q", "-m", "config")
    assert main(["doctor", "--adoption", "--json", "--repo", str(tdd_repo.repo)], environ=tdd_repo.environ) == 3
    doc = json.loads(capsys.readouterr().out)
    gate = next(c for c in doc["checks"] if c["id"] == "GATE-001")
    assert gate["status"] == "fail" and "test_base_failure" in gate["message"]
    assert not {c["id"] for c in doc["checks"] if c["id"].startswith(("ENV-", "PRV-", "SANDBOX-"))}


def test_gate001_fix_column_carries_the_suggestions(make_ctx, monkeypatch):
    canned(monkeypatch, red_base())
    ctx, _ = make_ctx()
    [outcome] = run_checks(ctx, scopes={"adoption"}, only={"GATE-001"})
    assert outcome.fix_hint and "fail at the base" in outcome.fix_hint and "gates.lint" in outcome.fix_hint
