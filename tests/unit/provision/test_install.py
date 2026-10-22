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


def install(config, paths, env, runner, fetcher, *, openspec=False, platform="linux-x64", **kw):
    return {
        a.tool: a
        for a in install_planned(
            config, paths, {**env, **SECRETS}, platform, openspec_active=openspec, fetcher=fetcher, run=runner, **kw
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


def test_kiro_installs_its_pinned_archive_not_an_installer(paths, env, install_fake, monkeypatch):
    import hashlib

    from l4.provision import catalog
    from l4.provision.catalog import kiro_archive_url

    from ._install_helpers import KiroRunner, kiro_zip

    install_fake("uv")
    archive = kiro_zip()
    monkeypatch.setitem(catalog.KIRO_SHA256["2.32.0"], "linux-x64", hashlib.sha256(archive).hexdigest())
    url = kiro_archive_url("2.32.0", "linux-x64")
    fetcher = FakeFetcher({url: archive})
    runner = KiroRunner(paths, env, {"uv": "uv 0.12.22"})
    actions = install(cfg({"k": {"adapter": "kiro-cli"}}), paths, env, runner, fetcher)
    assert actions["kiro-cli"].status == "applied" and fetcher.calls == [url]
    assert not [c for c in runner.calls if Path(c[0]).name in ("bash", "sh")]  # no installer script ran


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


def test_the_link_guard_runs_on_python_3_11(paths, monkeypatch):  # the 3.11 signature of Path.exists has no keyword
    from l4.provision.install import InstallFailed, _link

    real_exists = Path.exists

    def exists_3_11(self):
        return real_exists(self)

    monkeypatch.setattr(Path, "exists", exists_3_11)
    target = paths.home / "elsewhere"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("new")
    keep = paths.local_bin / "keep"
    keep.parent.mkdir(parents=True, exist_ok=True)
    keep.write_text("mine")
    with pytest.raises(InstallFailed, match="keep"):
        _link(target, keep, replace_files=False)
    assert keep.read_text() == "mine" and not keep.is_symlink()
    other = paths.local_bin / "other"
    other.write_text("a regular file")
    _link(target, other)  # replace_files defaults to True
    assert other.is_symlink() and other.resolve() == target.resolve()


def test_a_regular_file_at_the_node_link_is_replaced_by_the_node_install(paths, env, install_fake):  # SCN-OCG-09
    old = install_fake("node", paths.home / "sysbin")
    install_fake("uv")
    node_link = paths.local_bin / "node"
    node_link.write_text("a regular file")
    versions = {"uv": "uv 0.12.22", str(old): "v18.0.0", str(node_link): f"v{NODE_V}"}
    runner = InstallRunner(paths, env, versions)
    actions = install(
        cfg({}), paths, {**env, "PATH": str(old.parent)}, runner, FakeFetcher(node_files()), openspec=True
    )
    assert actions["node"].status == "applied"
    assert node_link.is_symlink()
    assert node_link.resolve() == (paths.l4_home / "node" / "bin" / "node").resolve()


def test_a_v2_still_first_after_the_install_fails_the_action_naming_the_resolved_path(paths, env, install_fake):
    for tool in ("uv", "node", "npm"):
        install_fake(tool)
    runner = _opencode_runner(paths, env)  # --version still answers v2 after the install
    actions = install(cfg(OPENCODE_CFG), paths, env, runner, FakeFetcher())
    assert actions["opencode"].status == "failed"
    assert str(paths.local_bin / "opencode") in actions["opencode"].message
    assert "2.0.32" in actions["opencode"].message and "opencode-ai 1.x" in actions["opencode"].message


# --- Copilot CLI: the pinned tarball, its digest, the one member, the warm-up (L4-PRV-047, L4-PRV-048) ---

COPILOT_URL = "https://github.com/github/copilot-cli/releases/download/v1.0.102/copilot-linux-x64.tar.gz"
COPILOT_CFG = {"c": {"adapter": "copilot-cli"}}


def copilot_world(paths, env, install_fake, monkeypatch, archive, *, key="linux-x64", **runner_kw):
    """uv present (so it is not installed), the digest table holding `archive`'s sha256, a fetcher serving it."""
    import hashlib

    from l4.provision import catalog

    from ._install_helpers import CopilotRunner

    install_fake("uv")
    monkeypatch.setitem(catalog.COPILOT_SHA256["1.0.102"], key, hashlib.sha256(archive).hexdigest())
    url = catalog.copilot_archive_url("1.0.102", key)
    return FakeFetcher({url: archive}), CopilotRunner(paths, env, {"uv": "uv 0.12.22"}, **runner_kw)


def version_reads(paths, runner):
    """The environments of the `copilot --version` reads of a run."""
    version = (str(paths.local_bin / "copilot"), "--version")
    return [e for c, e in zip(runner.calls, runner.envs, strict=True) if c == version]


def test_scn_prv_129_ci_installs_copilot_from_the_pinned_tarball(paths, env, install_fake, monkeypatch):
    from ._install_helpers import copilot_tar

    fetcher, runner = copilot_world(paths, env, install_fake, monkeypatch, copilot_tar())
    actions = install(cfg(COPILOT_CFG), paths, env, runner, fetcher, replace_present=True)
    action = actions["copilot"]
    assert action.status == "applied" and action.message == "copilot 1.0.102"
    assert fetcher.calls == [COPILOT_URL]
    target = paths.local_bin / "copilot"
    assert target.is_file() and (target.stat().st_mode & 0o777) == 0o755
    assert sorted(p.name for p in paths.local_bin.iterdir()) == ["copilot", "uv"]  # no staged file, no backup
    assert not list((paths.l4_cache / "installers").glob("copilot-*"))  # the temporary directory is gone
    assert not [c for c in runner.calls if Path(c[0]).name in ("bash", "sh")]  # no vendor installer ran


def test_scn_prv_130_a_tarball_whose_digest_differs_installs_nothing(paths, env, install_fake, monkeypatch):
    import hashlib

    from ._install_helpers import copilot_tar

    served = copilot_tar("1.0.999")
    fetcher, runner = copilot_world(paths, env, install_fake, monkeypatch, copilot_tar())
    fetcher.files[COPILOT_URL] = served
    before = sorted(p.name for p in paths.local_bin.iterdir())
    action = install(cfg(COPILOT_CFG), paths, env, runner, fetcher, replace_present=True)["copilot"]
    assert action.status == "failed" and hashlib.sha256(served).hexdigest() in action.message
    assert hashlib.sha256(copilot_tar()).hexdigest() in action.message
    assert action.message.endswith(
        "do not install it by hand: report it, or hold another version in ci.cli_versions (one the harness holds)"
    )
    assert sorted(p.name for p in paths.local_bin.iterdir()) == before
    assert not list((paths.l4_cache / "installers").glob("copilot-*"))


@pytest.mark.parametrize(
    ("variant", "text"),
    [
        ({"member": "other"}, "copilot is missing from the Copilot CLI archive"),
        ({"kind": "link"}, "copilot in the Copilot CLI archive is not a regular file"),
        ({"limit": 8}, "copilot in the Copilot CLI archive is larger than 8 bytes"),  # the real limit: see below
    ],
)
def test_scn_prv_132_a_missing_linked_or_oversized_member_is_never_extracted(
    paths, env, install_fake, monkeypatch, variant, text
):
    from l4.provision import catalog

    from ._install_helpers import copilot_tar

    assert catalog.COPILOT_MEMBER_MAX == 536870912  # the text of the real limit names these bytes
    variant = dict(variant)
    if "limit" in variant:  # a member of a few bytes stands for one above the limit
        monkeypatch.setattr("l4.provision.install.COPILOT_MEMBER_MAX", variant.pop("limit"))
    fetcher, runner = copilot_world(paths, env, install_fake, monkeypatch, copilot_tar(**variant))
    before = sorted(p.name for p in paths.local_bin.iterdir())
    action = install(cfg(COPILOT_CFG), paths, env, runner, fetcher, replace_present=True)["copilot"]
    assert action.status == "failed" and action.message.startswith(text)
    assert sorted(p.name for p in paths.local_bin.iterdir()) == before


def test_scn_prv_133_a_download_refused_with_404_names_the_version_and_the_way_out(
    paths, env, install_fake, monkeypatch
):
    from l4.provision.runner import OfflineError

    from ._install_helpers import copilot_tar

    class Refuses(FakeFetcher):
        def download(self, url, dest):
            self.calls.append(url)
            raise OfflineError("github.com", "HTTP 404")

    _, runner = copilot_world(paths, env, install_fake, monkeypatch, copilot_tar())
    fetcher = Refuses()
    action = install(cfg(COPILOT_CFG), paths, env, runner, fetcher, replace_present=True)["copilot"]
    assert action.status == "failed"
    assert action.message == (
        "cannot download copilot 1.0.102 from github.com (HTTP 404): that version may no longer be served; "
        "hold another version in ci.cli_versions (one the harness holds) or report it"
    )  # no manual command: it would download the same file
    assert fetcher.calls == [COPILOT_URL]


def test_an_existing_copilot_is_replaced_and_nothing_is_left_beside_it(paths, env, install_fake, monkeypatch):
    from ._install_helpers import copilot_tar

    fetcher, runner = copilot_world(paths, env, install_fake, monkeypatch, copilot_tar())
    old = install_fake("copilot")
    old.write_text('#!/bin/sh\necho "GitHub Copilot CLI 2.0.0."\n')  # SCN-OCG-16: another major, replaced in CI
    action = install(cfg(COPILOT_CFG), paths, env, runner, fetcher, replace_present=True)["copilot"]
    assert action.status == "applied" and action.message == "copilot 1.0.102"
    assert "1.0.102" in old.read_text()
    assert sorted(p.name for p in paths.local_bin.iterdir()) == ["copilot", "uv"]


def test_an_existing_copilot_is_kept_when_the_rename_fails(paths, env, install_fake, monkeypatch):
    from ._install_helpers import copilot_tar

    fetcher, runner = copilot_world(paths, env, install_fake, monkeypatch, copilot_tar())
    old = install_fake("copilot")
    text = '#!/bin/sh\necho "GitHub Copilot CLI 1.0.101."\n'
    old.write_text(text)
    real = os.replace

    def replace(src, dst, *a, **kw):
        if Path(src).name.startswith(".copilot.tmp."):
            raise OSError(13, "Permission denied")
        return real(src, dst, *a, **kw)

    monkeypatch.setattr("l4.provision.install.os.replace", replace)
    action = install(cfg(COPILOT_CFG), paths, env, runner, fetcher, replace_present=True)["copilot"]
    assert action.status == "failed" and "Permission denied" in action.message
    assert old.read_text() == text
    assert sorted(p.name for p in paths.local_bin.iterdir()) == ["copilot", "uv"]  # the staged file and backup are gone


def test_scn_prv_134_the_install_warms_the_package_cache(paths, env, install_fake, monkeypatch):
    from ._install_helpers import copilot_tar

    fetcher, runner = copilot_world(paths, env, install_fake, monkeypatch, copilot_tar())
    action = install(cfg(COPILOT_CFG), paths, env, runner, fetcher, replace_present=True)["copilot"]
    cache = paths.l4_home / "copilot-cache"
    assert action.status == "applied"
    warm = [
        e
        for c, e in zip(runner.calls, runner.envs, strict=True)
        if c == (str(paths.local_bin / "copilot"), "--version")
    ]
    assert warm and all(e["XDG_CACHE_HOME"] == str(cache) and e["COPILOT_AUTO_UPDATE"] == "false" for e in warm)
    assert any((cache / "copilot" / "pkg").iterdir())
    assert not any(Path(e["COPILOT_HOME"]).exists() for e in warm if "COPILOT_HOME" in e)  # the throw-away home
    assert all(e["COPILOT_HOME"] != str(paths.home / ".copilot") for e in warm if "COPILOT_HOME" in e)


def test_scn_prv_134_a_binary_that_extracts_nothing_fails_the_action_with_the_warm_up_text(
    paths, env, install_fake, monkeypatch
):
    from ._install_helpers import copilot_tar

    fetcher, runner = copilot_world(paths, env, install_fake, monkeypatch, copilot_tar(), extracts=False)
    action = install(cfg(COPILOT_CFG), paths, env, runner, fetcher, replace_present=True)["copilot"]
    cache = paths.l4_home / "copilot-cache"
    assert action.status == "failed"
    assert action.message == (
        f"copilot 1.0.102 did not extract its package into {cache}/copilot/pkg "
        f"(copilot --version ran with XDG_CACHE_HOME={cache})"
    )


def test_on_macos_the_warm_up_uses_the_persons_home_and_only_the_version_is_checked(
    paths, env, install_fake, monkeypatch
):
    from ._install_helpers import copilot_tar

    fetcher, runner = copilot_world(
        paths, env, install_fake, monkeypatch, copilot_tar(), key="darwin-arm64", extracts=False
    )  # the CLI ignores XDG_CACHE_HOME there: nothing lands in the L4 cache
    action = install(cfg(COPILOT_CFG), paths, env, runner, fetcher, replace_present=True, platform="darwin-arm64")[
        "copilot"
    ]
    assert action.status == "applied" and action.message == "copilot 1.0.102"
    assert fetcher.calls == [COPILOT_URL.replace("linux-x64", "darwin-arm64")]
    warm = [
        e
        for c, e in zip(runner.calls, runner.envs, strict=True)
        if c == (str(paths.local_bin / "copilot"), "--version")
    ]
    assert warm and all(e["HOME"] == env["HOME"] for e in warm)
