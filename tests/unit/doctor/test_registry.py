import json

import pytest

from l4.config.schema import L4Config
from l4.doctor.registry import Check, CheckResult, DuplicateCheckError, Registry, exit_code, run_checks
from l4.doctor.report import render_json, render_table
from l4.exitcodes import ExitCode


def fail(message: str = "broken") -> CheckResult:
    return CheckResult("fail", message, fix_hint="do the thing")


def passing(_ctx) -> CheckResult:
    return CheckResult("pass", "fine")


def make_registry(*checks: Check) -> Registry:
    registry = Registry()
    for check in checks:
        registry.register(check)
    return registry


def test_error_failure_exits_3_and_warn_does_not(make_ctx):
    ctx, _ = make_ctx()
    err = Check("T-ERR", "error check", "error", lambda c: fail())
    warn = Check("T-WARN", "warn check", "warn", lambda c: fail())
    outcomes = run_checks(ctx, registry=make_registry(err, warn, Check("T-OK", "ok", "error", passing)))
    assert [o.status for o in outcomes] == ["fail", "fail", "pass"]
    assert exit_code(outcomes) is ExitCode.DOCTOR_FAILED
    assert exit_code(run_checks(ctx, registry=make_registry(warn))) is ExitCode.OK


def test_skipped_and_passing_error_checks_do_not_fail(make_ctx):
    ctx, _ = make_ctx()
    skip = Check("T-SKIP", "skipped", "error", lambda c: CheckResult("skip", "not active"))
    registry = make_registry(skip, Check("T-OK", "ok", "error", passing))
    assert exit_code(run_checks(ctx, registry=registry)) is ExitCode.OK


def test_duplicate_id_rejected():
    registry = make_registry(Check("ENV-001", "a", "error", passing))
    with pytest.raises(DuplicateCheckError, match="ENV-001"):
        registry.register(Check("ENV-001", "b", "warn", passing))


def test_severity_function_of_config(make_ctx):
    def downgrade_when_local(cfg: L4Config):
        return "warn" if cfg.ci.platform == "local" else "error"

    check = Check("T-SEV", "downgraded", downgrade_when_local, lambda c: fail())
    registry = make_registry(check)
    local_ctx, _ = make_ctx(cfg=L4Config.model_validate({"ci": {"platform": "local"}}))
    github_ctx, _ = make_ctx(cfg=L4Config.model_validate({"ci": {"platform": "github"}}))
    (local,) = run_checks(local_ctx, registry=registry)
    (github,) = run_checks(github_ctx, registry=registry)
    assert (local.severity, github.severity) == ("warn", "error")
    assert exit_code([local]) is ExitCode.OK and exit_code([github]) is ExitCode.DOCTOR_FAILED


def test_live_checks_run_only_with_the_live_flag(make_ctx):
    ctx, _ = make_ctx()
    probe = CheckResult("pass", "ok", cost_usd=0.25)
    live = Check("LIVE-X", "live", "error", lambda c: probe, scopes=frozenset({"live"}))
    registry = make_registry(Check("T-OK", "ok", "error", passing), live)
    assert [o.id for o in run_checks(ctx, registry=registry)] == ["T-OK"]
    with_live = run_checks(ctx, live=True, registry=registry)
    assert [o.id for o in with_live] == ["T-OK", "LIVE-X"]
    assert with_live[1].cost_usd == 0.25


def test_json_report_shape(make_ctx):
    ctx, _ = make_ctx()
    outcomes = run_checks(ctx, registry=make_registry(Check("T-ERR", "e", "error", lambda c: fail("bad"))))
    doc = json.loads(render_json(outcomes, exit_code(outcomes)))
    assert doc == {
        "schema": "l4/doctor@1",
        "ok": False,
        "exit_code": 3,
        "checks": [{"id": "T-ERR", "severity": "error", "status": "fail", "message": "bad", "fix": "do the thing"}],
        "probe_cost_usd": 0.0,
    }
    ok_doc = json.loads(render_json([], ExitCode.OK))
    assert ok_doc["ok"] is True and ok_doc["checks"] == []


def test_table_has_the_five_columns(make_ctx):
    ctx, _ = make_ctx()
    outcomes = run_checks(ctx, registry=make_registry(Check("T-ERR", "e", "error", lambda c: fail("bad"))))
    lines = render_table(outcomes).splitlines()
    assert lines[0].split() == ["id", "severity", "status", "message", "fix"]
    assert lines[2].split()[:3] == ["T-ERR", "error", "fail"]
    assert "bad" in lines[2] and "do the thing" in lines[2]


def test_load_check_modules_skips_an_absent_module_but_not_a_broken_one(tmp_path, monkeypatch):
    from l4.doctor.registry import load_check_modules

    (tmp_path / "l4_fake_checks_broken.py").write_text("import l4_missing_dependency_xyz\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    load_check_modules(("l4_fake_checks_absent",))  # not there yet: skipped
    with pytest.raises(ModuleNotFoundError, match="l4_missing_dependency_xyz"):
        load_check_modules(("l4_fake_checks_broken",))


def test_a_crashing_check_becomes_a_failed_outcome_and_the_rest_run(make_ctx):
    ctx, _ = make_ctx()

    def boom(_ctx) -> CheckResult:
        raise RuntimeError("tool resolves into the checkout")

    registry = make_registry(Check("T-BOOM", "boom", "error", boom), Check("T-OK", "ok", "error", passing))
    outcomes = run_checks(ctx, registry=registry)
    assert [o.status for o in outcomes] == ["fail", "pass"]
    assert outcomes[0].message == "check crashed: RuntimeError: tool resolves into the checkout"
    assert exit_code(outcomes) is ExitCode.DOCTOR_FAILED
    json.loads(render_json(outcomes, exit_code(outcomes)))
