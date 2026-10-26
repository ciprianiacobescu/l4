"""`l4 doctor --fix` end to end with a fake fetcher and a fake installer runner (no network, no real installer)."""

import json
import stat
from pathlib import Path

import pytest

from l4.cli import main
from l4.config.defaults import PLAYWRIGHT_VERSION
from l4.doctor import checks_provision
from l4.doctor.registry import REGISTRY, load_check_modules
from l4.provision.catalog import INSTALLER_URLS
from l4.provision.runner import Paths

from ._install_helpers import ChromiumRunner, FakeFetcher, InstallRunner, installer

KIRO_ONLY = """\
spec: {frameworks: [kiro]}
profiles:
  impl: {adapter: fake, vendor: a}
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
    env = {
        "PATH": str(bin_dir), "HOME": str(tmp_path / "home"), "L4_HOME": str(tmp_path / "home" / ".local/share/l4"),
        "L4_CACHE": str(tmp_path / "cache"),
    }  # fmt: skip
    paths = Paths.from_env(env)
    fetcher = FakeFetcher({INSTALLER_URLS["uv"]: installer("uv")})
    runner = InstallRunner(paths, env, {"uv": "uv 0.12.22"})
    monkeypatch.setattr(checks_provision, "_fetcher", lambda: fetcher)
    monkeypatch.setattr(checks_provision, "_runner", lambda: runner)
    return repo, env, paths, fetcher, runner


def test_the_install_fix_hangs_on_env_001_003_004_and_007_as_one_fix():
    load_check_modules()
    checks = {c.id: c for c in REGISTRY.checks()}
    fixes = [checks[i].fix for i in ("ENV-001", "ENV-003", "ENV-004", "ENV-007")]  # ENV-007: chromium-provision 1.2
    assert all(f is checks_provision.INSTALL_FIX for f in fixes)
    assert (fixes[0].kind, fixes[0].scope) == ("install", "provision")
    assert checks["ENV-002"].fix is None and {"PRV-001", "PRV-002"} <= set(checks)


def test_doctor_fix_installs_uv_into_the_home_and_a_second_run_fetches_nothing(world, capsys):
    repo, env, paths, fetcher, runner = world
    assert main(["doctor", "--repo", str(repo)], environ=env) == 3  # uv is missing
    capsys.readouterr()
    assert main(["doctor", "--fix", "--json", "--repo", str(repo)], environ=env) == 0
    document = json.loads(capsys.readouterr().out)
    assert [(f["tool"], f["status"]) for f in document["fixes"] if f["status"] != "manual"] == [("uv", "applied")]
    assert (paths.local_bin / "uv").is_file()
    assert fetcher.calls == [INSTALLER_URLS["uv"]]
    assert main(["doctor", "--fix", "--json", "--repo", str(repo)], environ=env) == 0
    again = json.loads(capsys.readouterr().out)
    assert "fixes" not in again or all(f["status"] != "applied" for f in again["fixes"])
    assert fetcher.calls == [INSTALLER_URLS["uv"]]  # zero fetches the second time


def test_ci_fix_applies_the_provisioning_fix(world, capsys):
    repo, env, paths, fetcher, _ = world
    assert main(["doctor", "--ci", "--fix", "--repo", str(repo)], environ=env) == 0
    assert (paths.local_bin / "uv").is_file()
    assert "fix  uv  applied" in capsys.readouterr().out


def test_offline_uv_missing_exits_3_with_the_manual_command(world, monkeypatch, capsys):
    repo, env, paths, _, _ = world
    offline = FakeFetcher(offline=True)
    monkeypatch.setattr(checks_provision, "_fetcher", lambda: offline)
    assert main(["doctor", "--fix", "--repo", str(repo)], environ=env) == 3
    out = capsys.readouterr().out
    assert "astral.sh" in out and "run manually: curl -LsSf" in out
    assert not paths.local_bin.exists()


def test_self_provision_false_installs_nothing(world, capsys):
    repo, env, paths, fetcher, _ = world
    (repo / ".l4" / "config.yaml").write_text(KIRO_ONLY + "ci: {self_provision: false}\n")
    assert main(["doctor", "--ci", "--fix", "--repo", str(repo)], environ=env) == 3
    assert fetcher.calls == [] and "skipped" in capsys.readouterr().out


E2E = KIRO_ONLY.replace(
    "gates: {test: {command: pytest -q}}", "gates: {test: {command: pytest -q}, e2e: {command: npx playwright test}}"
)


def test_ci_fix_installs_chromium_and_env_007_passes_in_the_same_run(world, monkeypatch, capsys):
    """chromium-provision 1.2 (SCN-ADO-57, D5): ENV-007 fails on an empty browser folder, `--ci --fix` fills it and the
    re-run of ENV-007 passes; a second run installs nothing."""
    repo, env, paths, fetcher, _ = world
    (repo / ".l4" / "config.yaml").write_text(E2E)
    uv = paths.local_bin / "uv"  # uv is there, so ENV-007 is the one failing check that carries the fix
    uv.parent.mkdir(parents=True)
    uv.write_text("#!/bin/sh\n")
    uv.chmod(0o755)
    runner = ChromiumRunner(paths, env, {"uv": "uv 0.12.22"})
    monkeypatch.setattr(checks_provision, "_runner", lambda: runner)
    folder = paths.l4_cache / "shared" / "ms-playwright"

    def env_007(*flags):
        code = main(["doctor", *flags, "--json", "--repo", str(repo)], environ=env)
        document = json.loads(capsys.readouterr().out)
        return code, document, next(c for c in document["checks"] if c["id"] == "ENV-007")

    assert env_007("--ci")[2]["status"] == "fail"
    code, document, check = env_007("--ci", "--fix")
    chromium = next(f for f in document["fixes"] if f["tool"] == "chromium")
    assert (chromium["status"], chromium["message"]) == ("applied", f"chromium {PLAYWRIGHT_VERSION}")
    assert any(folder.glob("chromium*"))
    assert check["status"] == "pass" and code == 0, document
    installs = [c for c in runner.calls if c[-3:] == ("playwright", "install", "chromium")]
    assert len(installs) == 1
    code, document, check = env_007("--ci", "--fix")
    assert (
        check["status"] == "pass"
        and len([c for c in runner.calls if c[-3:] == ("playwright", "install", "chromium")]) == 1
    )
