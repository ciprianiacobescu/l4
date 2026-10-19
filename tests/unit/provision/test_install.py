import os
import time
from pathlib import Path

import pytest

from l4.config.schema import L4Config
from l4.provision.catalog import INSTALLER_URLS, node_shasums_url, node_tarball_url
from l4.provision.install import install_planned

from ._install_helpers import NODE_V, FakeFetcher, InstallRunner, installer, node_tarball, shasums

SECRETS = {"L4_FORGE_TOKEN": "glpat-fake", "ANTHROPIC_API_KEY": "sk-fake", "CI_JOB_TOKEN": "fake"}


def cfg(profiles: dict, roles: dict | None = None) -> L4Config:
    chain = {"implementer": list(profiles), "judges": []}
    return L4Config.model_validate({"profiles": profiles, "roles": roles or chain})


def install(config, paths, env, runner, fetcher, *, openspec=False, **kw):
    return {
        a.tool: a
        for a in install_planned(
            config, paths, {**env, **SECRETS}, "linux-x64", openspec_active=openspec, fetcher=fetcher, run=runner, **kw
        )
    }


def node_files() -> dict[str, bytes]:
    tarball = node_tarball()
    return {
        node_tarball_url(NODE_V, "linux-x64"): tarball,
        node_shasums_url(NODE_V): shasums(tarball).encode(),
    }


def test_missing_uv_is_installed_user_local_from_a_saved_script(paths, env, tmp_path):
    runner = InstallRunner(paths, env, {"uv": "uv 0.12.22"})
    fetcher = FakeFetcher({INSTALLER_URLS["uv"]: installer("uv")})
    actions = install(cfg({}), paths, env, runner, fetcher)
    assert actions["uv"].status == "applied" and actions["uv"].target == str(paths.local_bin / "uv")
    [(interpreter, script)] = [c for c in runner.calls if Path(c[0]).name == "sh"]
    assert Path(script).name == "install.sh" and not Path(script).exists()  # run from a file, then removed
    clean = runner.envs[runner.calls.index((interpreter, script))]
    assert clean["UV_NO_MODIFY_PATH"] == "1" and clean["UV_INSTALL_DIR"] == str(paths.local_bin)
    assert not set(SECRETS) & set(clean)  # the installer never sees a token
    assert all(Path(c[0]).name not in ("sudo", "su", "doas") for c in runner.calls)


def test_a_too_old_system_node_is_left_alone_and_extraction_is_atomic(paths, env, install_fake):
    old = install_fake("node", paths.home / "sysbin")
    versions = {"uv": "uv 0.12.22", str(old): "v18.0.0", str(paths.local_bin / "node"): f"v{NODE_V}"}
    runner = InstallRunner(paths, env, versions)
    install_fake("uv")
    fetcher = FakeFetcher(node_files())
    (paths.l4_home / "node.tmp.1").mkdir(parents=True)
    os.utime(paths.l4_home / "node.tmp.1", (time.time() - 7200, time.time() - 7200))
    actions = install(cfg({}), paths, {**env, "PATH": str(old.parent)}, runner, fetcher, openspec=True)
    # the planned install replaces nothing outside $L4_HOME: the old node file is untouched
    assert old.read_text() == "#!/bin/sh\n"
    assert (paths.l4_home / "node" / "bin" / "node").is_file()
    assert (paths.l4_home / "node" / ".l4-version").read_text() == f"{NODE_V}\n"
    assert sorted(p.name for p in paths.l4_home.iterdir() if p.name.startswith("node")) == ["node"]  # no tmp, no stale
    assert (paths.local_bin / "npm").resolve() == (paths.l4_home / "node" / "bin" / "npm").resolve()
    assert actions["node"].status == "applied" and actions["node"].message == f"node {NODE_V}"


def test_node_checksum_mismatch_fails_with_the_manual_command_and_leaves_nothing(paths, env, install_fake):
    install_fake("uv")
    runner = InstallRunner(paths, env, {"uv": "uv 0.12.22", "node": f"v{NODE_V}"})
    files = node_files()
    files[node_shasums_url(NODE_V)] = shasums(b"something else").encode()
    actions = install(cfg({}), paths, env, runner, FakeFetcher(files), openspec=True)
    assert actions["node"].status == "failed"
    message = actions["node"].message
    assert "does not match" in message and "run manually: download https://nodejs.org" in message
    assert not (paths.l4_home / "node").exists() and not list(paths.l4_home.glob("node.*"))


def test_offline_makes_failed_actions_that_name_the_host_and_the_manual_command(paths, env):
    runner = InstallRunner(paths, env, {})
    actions = install(cfg({}), paths, env, runner, FakeFetcher(offline=True))
    assert actions["uv"].status == "failed"
    assert "astral.sh" in actions["uv"].message and "run manually: curl -LsSf" in actions["uv"].message
    assert not paths.local_bin.exists()


def test_openspec_is_installed_with_the_harness_npm_into_the_one_prefix(paths, env, install_fake):
    for tool in ("uv", "node", "npm"):
        install_fake(tool)
    runner = InstallRunner(paths, env, {"uv": "uv 0.12.22", "node": "v22.23.0", "openspec": "1.14.0"})
    fetcher = FakeFetcher()
    actions = install(cfg({}), paths, env, runner, fetcher, openspec=True)
    assert actions["openspec"].status == "applied"
    [npm] = [c for c in runner.calls if len(c) > 1 and c[1] == "install"]
    assert npm == (
        str(paths.local_bin / "npm"), "install", "--prefix", str(paths.npm_prefix), "--no-fund", "--no-audit",
        "--save-exact", "@fission-ai/openspec@1.14.0",
    )  # fmt: skip
    assert runner.cwds[runner.calls.index(npm)] == paths.npm_prefix
    assert fetcher.calls == [] and all("npx" not in part for c in runner.calls for part in c)


def test_openspec_without_npm_fails_instead_of_guessing(paths, env, install_fake):
    install_fake("uv"), install_fake("node")
    runner = InstallRunner(paths, env, {"uv": "uv 0.12.22", "node": "v22.23.0"})
    actions = install(cfg({}), paths, env, runner, FakeFetcher(), openspec=True)
    assert actions["openspec"].status == "failed" and "npm is not available" in actions["openspec"].message


def test_claude_is_installed_with_the_version_argument(paths, env, install_fake):
    install_fake("uv")
    runner = InstallRunner(paths, env, {"uv": "uv 0.12.22", "claude": "2.1.288 (Claude Code)"})
    fetcher = FakeFetcher({INSTALLER_URLS["claude-code"]: installer("claude")})
    config = cfg({"impl": {"adapter": "claude-code", "min_version": "2.1.0"}})
    actions = install(config, paths, env, runner, fetcher)
    assert actions["claude"].status == "applied"
    [call] = [c for c in runner.calls if Path(c[0]).name == "bash"]
    assert call[2:] == ("2.1.288",)


def test_a_floor_above_the_pin_is_skipped_and_no_installer_runs(paths, env, install_fake):
    install_fake("uv")
    runner = InstallRunner(paths, env, {"uv": "uv 0.12.22", "claude": "2.1.288 (Claude Code)"})
    fetcher = FakeFetcher({INSTALLER_URLS["claude-code"]: installer("claude")})
    actions = install(cfg({"impl": {"adapter": "claude-code", "min_version": "99.0.0"}}), paths, env, runner, fetcher)
    assert actions["claude"].status == "skipped"
    assert actions["claude"].message == "min_version 99.0.0 is above the pinned 2.1.288; not installing"
    assert not [c for c in runner.calls if Path(c[0]).name == "bash"] and fetcher.calls == []


def test_a_floor_above_the_pin_is_skipped_for_npm_agents_too(paths, env, install_fake):
    install_fake("uv"), install_fake("node"), install_fake("npm")
    runner = InstallRunner(paths, env, {"uv": "uv 0.12.22", "node": "v22.23.0", "codex": "codex-cli 0.160.0"})
    actions = install(cfg({"c": {"adapter": "codex", "min_version": "99.0.0"}}), paths, env, runner, FakeFetcher())
    assert actions["codex"].status == "skipped" and "not installing" in actions["codex"].message
    assert not [c for c in runner.calls if "install" in c[1:2]]


def test_installed_below_floor_is_failed_and_both_versions_are_named(paths, env, install_fake):
    install_fake("uv")
    runner = InstallRunner(paths, env, {"uv": "uv 0.12.22", "claude": "2.0.5 (Claude Code)"})
    fetcher = FakeFetcher({INSTALLER_URLS["claude-code"]: installer("claude")})
    config = cfg({"impl": {"adapter": "claude-code", "min_version": "2.1.0"}})
    actions = install(config, paths, env, runner, fetcher)
    assert actions["claude"].status == "failed"
    assert "installed 2.0.5" in actions["claude"].message and ">= 2.1.0" in actions["claude"].message


def test_codex_goes_through_npm_into_the_prefix_and_is_linked_into_local_bin(paths, env, install_fake):
    for tool in ("uv", "node", "npm"):
        install_fake(tool)
    runner = InstallRunner(paths, env, {"uv": "uv 0.12.22", "node": "v22.23.0", "codex": "codex-cli 0.160.0"})
    actions = install(cfg({"cx": {"adapter": "codex"}}), paths, env, runner, FakeFetcher())
    assert actions["codex"].status == "applied"
    [npm] = [c for c in runner.calls if len(c) > 1 and c[1] == "install"]
    assert npm[-1] == "@openai/codex@0.160.0"
    link = paths.local_bin / "codex"
    assert link.is_symlink() and link.resolve() == (paths.npm_prefix / "node_modules" / ".bin" / "codex").resolve()


def test_kiro_runs_its_saved_installer_without_a_version(paths, env, install_fake):
    install_fake("uv")
    runner = InstallRunner(paths, env, {"uv": "uv 0.12.22", "kiro-cli": "kiro-cli 2.27.1"})
    fetcher = FakeFetcher({INSTALLER_URLS["kiro-cli"]: installer("kiro-cli")})
    actions = install(cfg({"k": {"adapter": "kiro-cli"}}), paths, env, runner, fetcher)
    assert actions["kiro-cli"].status == "applied"
    assert [c for c in runner.calls if Path(c[0]).name == "bash"][0][2:] == ()


def test_second_run_is_a_noop_offline(paths, env, install_fake, tmp_path):
    for tool in ("uv", "node", "npm", "claude"):
        install_fake(tool)
    entry = Path(env["L4_HOME"]) / "npm" / "node_modules" / "@fission-ai" / "openspec" / "bin" / "openspec.js"
    entry.parent.mkdir(parents=True)
    entry.write_text("// fake")
    versions = {"uv": "uv 0.12.22", "node": "v22.23.0", "openspec": "1.14.0", "claude": "2.1.288"}
    runner = InstallRunner(paths, env, versions)
    fetcher = FakeFetcher(offline=True)
    config = cfg({"impl": {"adapter": "claude-code"}})

    def snapshot() -> dict[str, float]:
        roots = [r for r in (paths.home, paths.l4_cache) if r.exists()]
        return {str(p): p.stat().st_mtime_ns for root in roots for p in root.rglob("*")}

    before = snapshot()
    actions = install(config, paths, env, runner, fetcher, openspec=True)
    assert {a.status for a in actions.values() if not a.needs_root} == {"already present"}
    assert fetcher.calls == [] and snapshot() == before
    assert all(len(c) < 2 or c[1] != "install" for c in runner.calls)


def test_installs_switched_off_do_nothing(paths, env):
    fetcher = FakeFetcher()
    actions = install(cfg({}), paths, env, InstallRunner(paths, env, {}), fetcher, allow_install=False)
    assert actions["uv"].status == "skipped" and fetcher.calls == []


@pytest.mark.parametrize("platform", ["freebsd-x64"])
def test_a_platform_without_a_node_tarball_fails_clearly(paths, env, install_fake, platform):
    install_fake("uv")
    runner = InstallRunner(paths, env, {"uv": "uv 0.12.22"})
    actions = {
        a.tool: a
        for a in install_planned(cfg({}), paths, env, platform, openspec_active=True, fetcher=FakeFetcher(), run=runner)
    }
    assert actions["node"].status == "failed" and "freebsd-x64" in actions["node"].message


def test_a_failed_node_swap_puts_the_previous_tree_back(tmp_path, monkeypatch):
    from l4.provision import install as module

    final, staging, old = tmp_path / "node", tmp_path / "node.tmp", tmp_path / "node.old"
    for directory, marker in ((final, "previous"), (staging, "new")):
        directory.mkdir()
        (directory / "who").write_text(marker)
    real = os.rename

    def failing(src, dst):
        if Path(src) == staging:
            raise OSError("disk full")
        real(src, dst)

    monkeypatch.setattr(module.os, "rename", failing)
    with pytest.raises(OSError):
        module.swap_in(staging, final, old)
    assert (final / "who").read_text() == "previous" and not old.exists()
    monkeypatch.setattr(module.os, "rename", real)
    module.swap_in(staging, final, old)
    assert (final / "who").read_text() == "new" and not old.exists() and not staging.exists()


class V1AfterInstall(InstallRunner):
    """`opencode --version` answers v2 until the npm install of the pinned package ran, then the pinned v1."""

    def __call__(self, argv, cwd, env, timeout):
        done = super().__call__(argv, cwd, env, timeout)
        if len(argv) > 1 and argv[1] == "install" and argv[-1].startswith("opencode-ai@"):
            self.versions["opencode"] = "1.18.34"
        return done


OPENCODE_CFG = {"oc": {"adapter": "opencode", "model": "opencode/big-pickle", "vendor": "unknown"}}


def _opencode_runner(paths, env, runner_class=InstallRunner, **versions):
    base = {"uv": "uv 0.12.22", "node": "v22.23.0", "opencode": "opencode v2.0.32"}
    return runner_class(paths, env, {**base, **versions})


def test_a_v2_opencode_is_replaced_by_the_pinned_v1_through_the_link(paths, env, install_fake):  # SCN-OCG-08
    for tool in ("uv", "node", "npm"):
        install_fake(tool)
    install_fake("opencode", paths.home / "sysbin")  # a v2 earlier on the inherited PATH only
    runner = _opencode_runner(paths, env, V1AfterInstall)
    actions = install(cfg(OPENCODE_CFG), paths, {**env, "PATH": str(paths.home / "sysbin")}, runner, FakeFetcher())
    assert actions["opencode"].status == "applied" and actions["opencode"].message == "opencode 1.18.34"
    [npm] = [c for c in runner.calls if len(c) > 1 and c[1] == "install"]
    assert npm[2:4] == ("--prefix", str(paths.npm_prefix)) and npm[-1] == "opencode-ai@1.18.34"
    link = paths.local_bin / "opencode"
    assert link.is_symlink() and link.resolve() == (paths.npm_prefix / "node_modules" / ".bin" / "opencode").resolve()
    assert actions["opencode"].target == str(link)


def test_a_regular_file_at_the_opencode_link_is_never_replaced(paths, env, install_fake):  # SCN-OCG-09
    for tool in ("uv", "node", "npm"):
        install_fake(tool)
    mine = install_fake("opencode")  # a regular file: a person's own binary
    before = mine.read_bytes()
    runner = _opencode_runner(paths, env, V1AfterInstall)
    actions = install(cfg(OPENCODE_CFG), paths, env, runner, FakeFetcher())
    assert actions["opencode"].status == "failed"
    assert str(mine) in actions["opencode"].message and "npm install --prefix" in actions["opencode"].message
    assert mine.read_bytes() == before and not mine.is_symlink()


def test_a_regular_file_at_the_node_link_is_still_replaced(paths, env, install_fake):  # SCN-OCG-09: scoped guard
    from l4.provision.install import InstallFailed, _link

    target = paths.home / "elsewhere"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("new")
    link = paths.local_bin / "node"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.write_text("a regular file")
    _link(target, link)  # replace_files defaults to True: Node, laya-serve and the codex link keep their behaviour
    assert link.is_symlink() and link.resolve() == target.resolve()
    other = paths.local_bin / "keep"
    other.write_text("mine")
    with pytest.raises(InstallFailed, match="keep"):
        _link(target, other, replace_files=False)
    assert other.read_text() == "mine"


def test_a_v2_still_first_after_the_install_fails_the_action_naming_the_resolved_path(paths, env, install_fake):
    for tool in ("uv", "node", "npm"):
        install_fake(tool)
    runner = _opencode_runner(paths, env)  # --version still answers v2 after the install
    actions = install(cfg(OPENCODE_CFG), paths, env, runner, FakeFetcher())
    assert actions["opencode"].status == "failed"
    assert str(paths.local_bin / "opencode") in actions["opencode"].message
    assert "2.0.32" in actions["opencode"].message and "opencode-ai 1.x" in actions["opencode"].message
