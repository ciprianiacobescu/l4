"""chromium-provision 1.1 (L4-ADO-020, design D1 to D4): Chromium in runner provisioning. Nothing is downloaded: the
runner and the fetcher are fakes, and the browser folder is a directory of the test's own."""

from pathlib import Path

import pytest

from l4.config.defaults import PLAYWRIGHT_VERSION
from l4.config.schema import L4Config
from l4.provision.catalog import ToolSpec, required_tools
from l4.provision.install import install_planned
from l4.provision.runner import Paths, plan_fixes

from ._install_helpers import ChromiumRunner, FakeFetcher

SECRETS = {"L4_FORGE_TOKEN": "glpat-fake", "OPENAI_API_KEY": "sk-fake"}
UV_VERSIONS = {"uv": "uv 0.12.22"}
INSTALL = ("playwright", "install", "chromium")


def cfg(command: str = "npx playwright test", **verifier) -> L4Config:
    document: dict = {"profiles": {}, "roles": {}, "gates": {"e2e": {"command": command}}}
    if verifier:
        document["verifier"] = {"playwright": verifier}
    return L4Config.model_validate(document)


def folder_of(paths: Paths) -> Path:
    return paths.l4_cache / "shared" / "ms-playwright"


def run_install(paths, env, runner, *, fetcher=None, **kw):
    return {
        a.tool: a
        for a in install_planned(
            cfg(), paths, {**env, **SECRETS}, "linux-x64", openspec_active=False, fetcher=fetcher or FakeFetcher(),
            run=runner, **kw,
        )
    }  # fmt: skip


def test_chromium_is_planned_only_with_a_playwright_e2e_gate():
    """SCN-ADO-57, SCN-ADO-58: planned for an e2e command with Playwright on `auto`, after the other tools."""
    tools = required_tools(cfg(), openspec_active=False)
    assert [t.name for t in tools] == ["uv", "chromium"]
    assert tools[-1] == ToolSpec("chromium", "chromium", "playwright", PLAYWRIGHT_VERSION, None)
    assert required_tools(cfg(), openspec_active=True)[-1].name == "chromium"  # after node and openspec too
    assert "chromium" in [t.name for t in required_tools(cfg(enabled=True), openspec_active=False)]
    for off in (cfg(""), cfg("   "), cfg(enabled=False), cfg("", enabled=True)):
        assert "chromium" not in [t.name for t in required_tools(off, openspec_active=False)]


def test_a_cached_browser_is_already_present(paths, env, install_fake):
    install_fake("uv")
    for name in ("chromium-1200", "chromium_headless_shell-1200"):
        (folder_of(paths) / name).mkdir(parents=True)
    runner = ChromiumRunner(paths, env, UV_VERSIONS)
    actions = run_install(paths, env, runner)
    action = actions["chromium"]
    assert (action.status, action.target) == ("already present", str(folder_of(paths)))
    assert action.message == f"chromium {PLAYWRIGHT_VERSION}"
    [probe] = [(c, e) for c, e in zip(runner.calls, runner.envs, strict=True) if "--dry-run" in c]
    assert probe[0][1:] == ("tool", "run", "--from", f"playwright=={PLAYWRIGHT_VERSION}", "playwright", "install",
                            "--dry-run", "chromium")  # fmt: skip
    assert probe[1]["PLAYWRIGHT_BROWSERS_PATH"] == str(folder_of(paths))
    assert not any(c[-3:] == INSTALL for c in runner.calls)  # nothing is installed again
    plan = plan_fixes(cfg(), paths, env, "linux-x64", openspec_active=False, run=runner)
    assert {a.tool: a.status for a in plan}["chromium"] == "already present"


def test_a_listed_directory_that_is_missing_is_not_present(paths, env, install_fake):
    install_fake("uv")
    (folder_of(paths) / "chromium-1200").mkdir(parents=True)  # chromium_headless_shell-1200 is listed and absent
    plan = plan_fixes(
        cfg(), paths, env, "linux-x64", openspec_active=False, run=ChromiumRunner(paths, env, UV_VERSIONS)
    )
    assert {a.tool: a.status for a in plan}["chromium"] == "planned"
    nothing = plan_fixes(cfg(), paths, env, "linux-x64", openspec_active=False,
                         run=ChromiumRunner(paths, env, UV_VERSIONS, listed=()))  # fmt: skip
    assert {a.tool: a.status for a in nothing}["chromium"] == "planned"  # a dry run that names no location


def test_a_missing_browser_is_installed_into_the_shared_cache(paths, env, install_fake):
    install_fake("uv")
    runner = ChromiumRunner(paths, env, UV_VERSIONS)
    actions = run_install(paths, env, runner)
    action = actions["chromium"]
    assert action.status == "applied" and action.target == str(folder_of(paths))
    assert action.message == f"chromium {PLAYWRIGHT_VERSION}"
    [(argv, clean)] = [(c, e) for c, e in zip(runner.calls, runner.envs, strict=True) if c[-3:] == INSTALL]
    assert list(argv) == [str(paths.local_bin / "uv"), "tool", "run", "--from", f"playwright=={PLAYWRIGHT_VERSION}",
                          "playwright", "install", "chromium"]  # fmt: skip
    assert clean["PLAYWRIGHT_BROWSERS_PATH"] == str(folder_of(paths))
    assert not set(SECRETS) & set(clean)
    assert runner.folder_existed == [True]  # the install created the folder before it ran
    assert folder_of(paths).is_dir() and not any(Path(c[0]).name == "sudo" for c in runner.calls)


def test_an_install_that_leaves_the_browser_missing_fails_with_the_manual_command(
    paths, env, install_fake, monkeypatch
):
    monkeypatch.setenv("L4_CACHE", env["L4_CACHE"])  # the manual command names the folder of the process environment
    install_fake("uv")
    actions = run_install(paths, env, ChromiumRunner(paths, env, UV_VERSIONS, installs=False))
    manual = (
        f"PLAYWRIGHT_BROWSERS_PATH={folder_of(paths)} uvx --from playwright=={PLAYWRIGHT_VERSION} {' '.join(INSTALL)}"
    )
    assert actions["chromium"].status == "failed"
    assert f"run manually: {manual}" in actions["chromium"].message


def test_no_uv_fails_the_chromium_install(paths, env):
    actions = run_install(paths, env, ChromiumRunner(paths, env, {}))  # no uv anywhere, and nothing to download it from
    assert actions["chromium"].status == "failed" and "uv is not available" in actions["chromium"].message


def test_self_provision_off_skips_it(paths, env, install_fake):
    install_fake("uv")
    runner = ChromiumRunner(paths, env, UV_VERSIONS)
    actions = run_install(paths, env, runner, allow_install=False)
    assert actions["chromium"].status == "skipped" and "ci.self_provision" in actions["chromium"].message
    assert not any(c[-3:] == INSTALL for c in runner.calls) and not folder_of(paths).exists()


@pytest.mark.parametrize("command", ["", "  "])
def test_no_e2e_gate_plans_no_chromium_action(paths, env, install_fake, command):
    install_fake("uv")
    runner = ChromiumRunner(paths, env, UV_VERSIONS)
    plan = plan_fixes(cfg(command), paths, env, "linux-x64", openspec_active=False, run=runner)
    assert "chromium" not in [a.tool for a in plan] and not any("--dry-run" in c for c in runner.calls)
