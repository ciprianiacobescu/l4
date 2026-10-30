"""LOCAL-001 (local-doctor, SPEC L4-SEC-041): `l4 doctor` on a person's computer says when `l4 run` and `l4 verify`
will refuse there. A warning in the `local` scope only: `l4 doctor --ci` never runs it."""

import dataclasses
from collections.abc import Sequence
from pathlib import Path

import pytest

from l4.config.schema import L4Config, SandboxCfg
from l4.doctor import checks_local as lc
from l4.doctor.context import CmdResult
from l4.doctor.registry import REGISTRY, Check, Registry, doctor_scopes, exit_code, load_check_modules, run_checks


class Probe:
    def __init__(self, result: CmdResult) -> None:
        self.result = result
        self.calls: list[list[str]] = []

    def run(self, argv: Sequence[str], timeout: float = 10.0, env=None) -> CmdResult:
        self.calls.append(list(argv))
        return self.result


def fake_bwrap(tmp_path: Path) -> str:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    exe = bin_dir / "bwrap"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    return str(bin_dir)


def run_local(make_ctx, sandbox: SandboxCfg, *, path: str, probe: Probe | None = None, platform: str | None = None):
    ctx, _ = make_ctx(cfg=L4Config(sandbox=sandbox), PATH=path)
    probe = probe or Probe(CmdResult(0, "", ""))
    ctx = dataclasses.replace(ctx, run=probe.run)
    return lc._local_001(ctx, platform), probe


def test_scn_nfr_05_macos_without_bubblewrap_warns_with_the_ways_out(make_ctx, tmp_path):
    result, probe = run_local(make_ctx, SandboxCfg(), path=str(tmp_path / "empty"), platform="darwin")
    assert result.status == "fail" and not probe.calls
    assert result.message.startswith("l4 run/l4 verify will refuse on this computer: bwrap was not found on PATH")
    assert "Linux machine or VM with bubblewrap" in result.message and "`l4 ci start`" in result.message
    assert "`l4 retry` for a halted or escalated unit" in result.message
    assert "allow unprivileged user namespaces" not in result.message


def test_linux_without_bubblewrap_keeps_the_install_hint(make_ctx, tmp_path):
    result, _ = run_local(make_ctx, SandboxCfg(), path=str(tmp_path / "empty"), platform="linux")
    assert (
        result.status == "fail" and "apt install bubblewrap" in result.message and "l4 ci start" not in result.message
    )


def test_a_bwrap_that_cannot_start_a_sandbox_fails_with_its_reason(make_ctx, tmp_path):
    blocked = Probe(CmdResult(1, "", "bwrap: No permissions to create new namespace\n"))
    result, _ = run_local(make_ctx, SandboxCfg(), path=fake_bwrap(tmp_path), probe=blocked, platform="linux")
    assert result.status == "fail" and "No permissions to create new namespace" in result.message
    assert result.message.startswith("l4 run/l4 verify will refuse on this computer: ")


def test_scn_doc_11_a_bwrap_that_runs_passes_and_names_bwrap(make_ctx, tmp_path):
    result, probe = run_local(make_ctx, SandboxCfg(), path=fake_bwrap(tmp_path), platform="linux")
    assert result.status == "pass" and "bwrap" in result.message
    assert len(probe.calls) == 1 and probe.calls[0][-1] == "true"  # the preflight's own self-test, through ctx.run


def test_scn_doc_11_mode_none_with_allow_none_passes_and_names_none(make_ctx, tmp_path):
    result, probe = run_local(make_ctx, SandboxCfg(mode="none", allow_none=True), path=str(tmp_path))
    assert result.status == "pass" and "none" in result.message and not probe.calls


def test_mode_none_without_allow_none_fails_with_the_preflights_reason(make_ctx, tmp_path):
    result, _ = run_local(make_ctx, SandboxCfg(mode="none"), path=str(tmp_path))
    assert result.status == "fail" and "allow_none" in result.message
    assert result.message.startswith("l4 run/l4 verify will refuse on this computer: ")


@pytest.mark.parametrize("mode", ["user", "container"])
def test_a_mode_that_is_not_built_yet_is_a_fail_naming_it_not_a_crash(make_ctx, tmp_path, mode):
    result, _ = run_local(make_ctx, SandboxCfg(mode=mode), path=str(tmp_path))
    assert result.status == "fail" and f"sandbox.mode: {mode}" in result.message and "not built yet" in result.message
    assert result.message.startswith("l4 run/l4 verify will refuse on this computer: ")


def test_a_bwrap_symlinked_into_the_repository_is_a_fail_not_a_crash(make_ctx, tmp_path):
    ctx, _ = make_ctx()
    planted = ctx.repo / "planted-bwrap"
    planted.write_text("#!/bin/sh\n")
    planted.chmod(0o755)
    trusted = tmp_path / "trusted"
    trusted.mkdir()
    (trusted / "bwrap").symlink_to(planted)
    result, _ = run_local(make_ctx, SandboxCfg(), path=str(trusted), platform="linux")
    assert result.status == "fail" and "inside the repository" in result.message


def test_the_row_is_a_warning_in_the_local_scope_only():
    load_check_modules()
    (check,) = [c for c in REGISTRY.checks() if c.id == "LOCAL-001"]
    assert check.severity == "warn" and check.scopes == frozenset({"local"})
    assert not [c for c in REGISTRY.checks() if c.id == "SANDBOX-001"]  # SANDBOX-001 stays unregistered


def test_scn_doc_10_ci_scopes_leave_the_row_out_and_a_failure_keeps_the_exit_code(make_ctx, tmp_path):
    ctx, _ = make_ctx(cfg=L4Config(sandbox=SandboxCfg(mode="user")), PATH=str(tmp_path))
    registry = Registry()
    registry.register(Check("LOCAL-001", "x", "warn", lc._local_001, frozenset({"local"})))
    assert run_checks(ctx, registry=registry, scopes=doctor_scopes(ci=True, adoption=False, no_gates=False)) == []
    (outcome,) = run_checks(ctx, registry=registry, scopes=doctor_scopes(ci=False, adoption=False, no_gates=False))
    assert (outcome.id, outcome.status, outcome.severity) == ("LOCAL-001", "fail", "warn")
    assert int(exit_code([outcome])) == 0
