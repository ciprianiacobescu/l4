"""ENV-015 (L4-PRV-046): each agent CLI a role chain uses, against its effective pin."""

import hashlib
import json
import stat
from pathlib import Path

import pytest

from l4.cli import main
from l4.config.schema import L4Config
from l4.doctor import checks_env as env
from l4.doctor import checks_provision
from l4.doctor.registry import REGISTRY, Check, Registry, exit_code, load_check_modules, run_checks
from l4.provision import catalog
from l4.provision.runner import Paths

from ..provision._install_helpers import FakeFetcher, KiroRunner, installer, kiro_zip


def cfg(profiles=("kiro", "claude"), **ci) -> L4Config:
    known = {"kiro": {"adapter": "kiro-cli", "model": "auto"}, "claude": {"adapter": "claude-code"}}
    return L4Config.model_validate(
        {
            "profiles": {name: known[name] for name in profiles},
            "roles": {"implementer": list(profiles), "judges": []},
            "ci": ci,
        }
    )


def outcome(ctx):
    registry = Registry()
    registry.register(Check("ENV-015", "pins", "warn", env._env_015))
    (result,) = run_checks(ctx, registry=registry)
    return result, exit_code([result])


def test_passes_at_the_pins_and_names_overrides(make_ctx):  # SCN-PRV-125
    tools = {"kiro-cli": "kiro-cli 2.32.0", "claude": "2.1.288 (Claude Code)"}
    ctx, _ = make_ctx(tools=tools, cfg=cfg())
    result, _ = outcome(ctx)
    assert result.status == "pass" and result.message == "claude 2.1.288, kiro-cli 2.32.0 at their pins"
    held, _ = make_ctx(tools={**tools, "kiro-cli": "kiro-cli 2.28.0"}, cfg=cfg(cli_versions={"kiro-cli": "2.28.0"}))
    result, _ = outcome(held)
    assert result.status == "pass"
    assert "kiro-cli 2.28.0 held by ci.cli_versions; L4 pins 2.32.0" in result.message
    same, _ = make_ctx(tools=tools, cfg=cfg(cli_versions={"kiro-cli": "2.32.0"}))
    assert "remove" in outcome(same)[0].message  # an override equal to the pin is noted


def test_warns_on_a_drift_with_both_versions_and_the_fix(make_ctx, monkeypatch):  # SCN-PRV-120
    monkeypatch.setattr("l4.doctor.checks_env.detect_platform", lambda: "linux-x64")
    monkeypatch.setattr("l4.provision.catalog._read_libc", lambda: "glibc 2.39")
    tools = {"kiro-cli": "kiro-cli 2.33.0", "claude": "2.1.288 (Claude Code)"}
    ctx, _ = make_ctx(tools=tools, cfg=cfg())
    result, code = outcome(ctx)
    assert (result.status, result.severity) == ("fail", "warn") and int(code) == 0
    assert "kiro-cli 2.33.0 at /fake/bin/kiro-cli, pinned 2.32.0" in result.message
    assert "claude" not in result.message
    assert "l4 doctor --ci --fix" in result.fix_hint and "sha256sum -c" in result.fix_hint


def test_names_the_override_it_drifts_from(make_ctx):
    ctx, _ = make_ctx(tools={"kiro-cli": "kiro-cli 2.32.0"}, cfg=cfg(("kiro",), cli_versions={"kiro-cli": "2.28.0"}))
    result, _ = outcome(ctx)
    assert result.status == "fail" and "pinned 2.28.0 (ci.cli_versions)" in result.message


def test_leaves_a_missing_cli_and_a_wrong_major_to_env_004(make_ctx):
    ctx, _ = make_ctx(tools={"claude": "2.1.288 (Claude Code)"}, cfg=cfg())  # no kiro-cli at all
    assert outcome(ctx)[0].status == "pass"
    ctx, _ = make_ctx(tools={"kiro-cli": "kiro-cli 3.0.0", "claude": "2.1.288"}, cfg=cfg())
    result, _ = outcome(ctx)
    assert result.status == "pass" and "kiro-cli" not in result.message


def test_skips_without_an_agent_cli(make_ctx):
    ctx, _ = make_ctx(cfg=L4Config.model_validate({"profiles": {"f": {"adapter": "fake"}}, "roles": {"judges": ["f"]}}))
    assert outcome(ctx)[0].status == "skip"


def test_the_install_fix_is_attached():
    load_check_modules()
    assert {c.id: c for c in REGISTRY.checks()}["ENV-015"].fix is checks_provision.INSTALL_FIX


KIRO_ONLY = """\
spec: {frameworks: [kiro]}
profiles:
  impl: {adapter: kiro-cli, model: auto}
  judge: {adapter: fake, vendor: b}
roles: {implementer: [impl], judges: [judge]}
gates: {test: {command: pytest -q}}
"""


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    git = bin_dir / "git"
    git.write_text('#!/bin/sh\necho "git version 2.43.0"\n')
    git.chmod(git.stat().st_mode | stat.S_IXUSR)
    repo = tmp_path / "repo"
    (repo / ".l4").mkdir(parents=True)
    (repo / ".l4" / "config.yaml").write_text(KIRO_ONLY)
    environ = {
        "PATH": str(bin_dir), "HOME": str(tmp_path / "home"), "L4_HOME": str(tmp_path / "home" / ".local/share/l4"),
        "L4_CACHE": str(tmp_path / "cache"),
    }  # fmt: skip
    paths = Paths.from_env(environ)
    archive = kiro_zip()
    monkeypatch.setitem(catalog.KIRO_SHA256["2.32.0"], "linux-x64", hashlib.sha256(archive).hexdigest())
    monkeypatch.setattr("l4.provision.catalog._read_libc", lambda: "glibc 2.39")
    monkeypatch.setattr("l4.doctor.checks_provision.detect_platform", lambda: "linux-x64")
    monkeypatch.setattr("l4.doctor.checks_env.detect_platform", lambda: "linux-x64", raising=False)
    fetcher = FakeFetcher(
        {catalog.kiro_archive_url("2.32.0", "linux-x64"): archive, catalog.INSTALLER_URLS["uv"]: installer("uv")}
    )
    runner = KiroRunner(paths, environ, {"uv": "uv 0.12.22"})
    monkeypatch.setattr(checks_provision, "_fetcher", lambda: fetcher)
    monkeypatch.setattr(checks_provision, "_runner", lambda: runner)
    return repo, environ, paths, fetcher


def put_kiro(paths: Paths, version: str) -> None:
    paths.local_bin.mkdir(parents=True, exist_ok=True)
    file = paths.local_bin / "kiro-cli"
    file.write_text(f'#!/bin/sh\necho "kiro-cli {version}"\n')
    file.chmod(0o755)


def doctor(repo, environ, capsys, *flags):
    code = main(["doctor", *flags, "--json", "--repo", str(repo)], environ=environ)
    return code, json.loads(capsys.readouterr().out)


def env_015(doc):
    return next(c for c in doc["checks"] if c["id"] == "ENV-015")


def test_ci_fix_then_passes_in_a_fake_install_world(world, capsys):
    repo, environ, paths, fetcher = world
    put_kiro(paths, "2.33.0")
    _, before = doctor(repo, environ, capsys, "--ci")
    assert env_015(before)["status"] == "fail" and env_015(before)["severity"] == "warn"
    code, after = doctor(repo, environ, capsys, "--ci", "--fix")
    kiro = next(f for f in after["fixes"] if f["tool"] == "kiro-cli")
    assert kiro["status"] == "applied" and fetcher.calls
    assert env_015(after)["status"] == "pass"
    assert code == 0, after


def test_a_manual_override_warns_and_exits_0(world, capsys):  # SCN-PRV-127, the second world
    repo, environ, paths, fetcher = world
    (repo / ".l4" / "config.yaml").write_text(KIRO_ONLY + "ci: {cli_versions: {kiro-cli: '2.31.1'}}\n")
    put_kiro(paths, "2.32.0")
    code, doc = doctor(repo, environ, capsys, "--ci", "--fix")
    kiro = next(f for f in doc["fixes"] if f["tool"] == "kiro-cli")
    assert kiro["status"] == "manual" and not any("kirocli" in url for url in fetcher.calls)
    check = env_015(doc)
    assert (check["status"], check["severity"]) == ("fail", "warn")
    assert "2.31.1" in check["message"] and "2.32.0" in check["message"]
    assert check["severity"] == "warn"
    assert code == 0, doc  # a manual action is not failed, and a warning never makes doctor exit 3
