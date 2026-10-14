"""Doing what `plan_fixes` planned (L4-PRV-004/005): user-local installs from saved installers and verified tarballs.

Nothing here runs as root, pipes a download into a shell, or touches a profile file. Every installer runs from a saved
file under `scrub_env`; every install is followed by a version probe from the harness path, and a CLI that is still
below its floor is `failed` with both versions named. A tool that is already present is never reinstalled, so a second
run makes no download and no write. M1: runner-provisioning 2.2 (`provision_lock`), 2.3 (`--fix --dry-run`).
"""

import logging
import os
import shutil
import tarfile
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from l4.config.schema import L4Config
from l4.proc import Runner as CommandRunner
from l4.provision.catalog import (
    INSTALLER_URLS,
    NODE_VERSION,
    NPM_PACKAGES,
    ToolSpec,
    manual_command,
    node_sha256,
    node_shasums_url,
    node_tarball_url,
    required_tools,
)
from l4.provision.runner import (
    Fetcher,
    FixAction,
    IntegrityError,
    OfflineError,
    Paths,
    find_tool,
    installed_version,
    is_satisfied,
    plan_fixes,
    save_installer,
    scrub_env,
    verify_sha256,
)

log = logging.getLogger("l4.provision")

INSTALL_TIMEOUT_S = 900.0
STALE_AFTER_S = 3600.0
STDERR_TAIL = 300
NODE_LINKS = ("node", "npm", "npx")
SYSTEM_DIRS = ("/usr/bin", "/bin")  # where `sh` and `bash` are even when the runner's PATH is sparse


class InstallFailed(Exception):
    """An installer ran and did not leave a usable tool; the message is what a human reads."""


@dataclass(frozen=True)
class _Ctx:
    cfg: L4Config
    paths: Paths
    env: Mapping[str, str]
    clean: Mapping[str, str]
    platform: str
    fetcher: Fetcher
    run: CommandRunner

    @property
    def downloads(self) -> Path:
        directory = self.paths.l4_cache / "installers"
        directory.mkdir(parents=True, exist_ok=True)
        return directory


def _target_version(tool: ToolSpec) -> str | None:
    """The pin; a floor above it never reaches here (`plan_fixes` skips that action)."""
    return tool.version


def _checked(ctx: _Ctx, argv: list[str], *, env: Mapping[str, str] | None = None, cwd: Path | None = None) -> None:
    done = ctx.run(argv, cwd or ctx.paths.home, env or ctx.clean, INSTALL_TIMEOUT_S)
    if done.returncode != 0:
        tail = " ".join(done.stderr.strip().splitlines()[-3:])[-STDERR_TAIL:]
        what = " ".join([Path(argv[0]).name, *argv[1:2]])
        raise InstallFailed(f"`{what}` exited {done.returncode}: {tail}")


def _interpreter(ctx: _Ctx, name: str) -> str:
    found = shutil.which(name, path=os.pathsep.join([ctx.clean["PATH"], *SYSTEM_DIRS]))
    if found is None:
        raise InstallFailed(f"{name} is not on PATH")
    return found


def _run_saved_installer(
    ctx: _Ctx, url: str, interpreter: str, args: tuple[str, ...] = (), extra_env: Mapping[str, str] | None = None
) -> None:
    with tempfile.TemporaryDirectory(prefix="installer-", dir=ctx.downloads) as tmp:
        script = Path(tmp) / "install.sh"
        save_installer(ctx.fetcher, url, script)
        _checked(ctx, [_interpreter(ctx, interpreter), str(script), *args], env={**ctx.clean, **(extra_env or {})})


def _link(target: Path, link: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    staged = link.with_name(f".{link.name}.tmp.{os.getpid()}")
    staged.unlink(missing_ok=True)
    staged.symlink_to(target)
    os.replace(staged, link)


def _remove_stale(directory: Path, pattern: str) -> None:
    for leftover in directory.glob(pattern):
        if leftover.is_dir() and time.time() - leftover.stat().st_mtime > STALE_AFTER_S:
            shutil.rmtree(leftover, ignore_errors=True)


def _extract(tarball: Path, staging: Path) -> None:
    """The tarball's top directory is dropped, so `staging` becomes the Node tree itself. The `data` filter refuses
    absolute paths, `..` and links that point out of the tree."""
    with tarfile.open(tarball, "r:xz") as tar:
        members = []
        for member in tar.getmembers():
            _, _, rest = member.name.partition("/")
            if rest:
                member.name = rest
                members.append(member)
        tar.extractall(staging, members=members, filter="data")


def _install_node(ctx: _Ctx, tool: ToolSpec) -> None:
    home = ctx.paths.l4_home
    home.mkdir(parents=True, exist_ok=True)
    _remove_stale(home, "node.tmp.*")
    _remove_stale(home, "node.old.*")
    try:
        url, sums_url = node_tarball_url(NODE_VERSION, ctx.platform), node_shasums_url(NODE_VERSION)
    except ValueError as exc:
        raise InstallFailed(str(exc)) from None
    staging, final = home / f"node.tmp.{os.getpid()}", home / "node"
    with tempfile.TemporaryDirectory(prefix="node-", dir=ctx.downloads) as tmp:
        sums = ctx.fetcher.download(sums_url, Path(tmp) / "SHASUMS256.txt").read_text(encoding="utf-8")
        try:
            expected = node_sha256(sums, NODE_VERSION, ctx.platform)
        except ValueError as exc:
            raise InstallFailed(str(exc)) from None
        tarball = ctx.fetcher.download(url, Path(tmp) / url.rsplit("/", 1)[1])
        verify_sha256(tarball, expected)
        shutil.rmtree(staging, ignore_errors=True)
        try:
            _extract(tarball, staging)
            (staging / ".l4-version").write_text(f"{NODE_VERSION}\n", encoding="utf-8")
            old = home / f"node.old.{os.getpid()}"
            swap_in(staging, final, old)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
    for name in NODE_LINKS:  # a login shell's PATH has ~/.local/bin and not $L4_HOME/node/bin (prereqs.sh PRQ-07)
        _link(final / "bin" / name, ctx.paths.local_bin / name)


def swap_in(staging: Path, final: Path, old: Path) -> None:
    """Put `staging` at `final`, keeping the previous tree at `old` until the new one is in place and removing it then;
    if the second rename fails the previous tree goes back, so the harness is never left without a Node."""
    if final.exists():
        os.rename(final, old)
    try:
        os.rename(staging, final)
    except OSError:
        if old.exists():
            os.rename(old, final)
        raise
    shutil.rmtree(old, ignore_errors=True)


def _npm_install(ctx: _Ctx, package: str, version: str | None) -> None:
    npm = find_tool("npm", ctx.paths, ctx.env)
    if npm is None:
        raise InstallFailed("npm is not available: install Node first")
    prefix = ctx.paths.npm_prefix
    prefix.mkdir(parents=True, exist_ok=True)
    spec = f"{package}@{version}" if version else package
    argv = [str(npm), "install", "--prefix", str(prefix), "--no-fund", "--no-audit", "--save-exact", spec]
    _checked(ctx, argv, cwd=prefix)


def _install_agent(ctx: _Ctx, tool: ToolSpec) -> None:
    version = _target_version(tool)
    if tool.adapter in NPM_PACKAGES:
        _npm_install(ctx, NPM_PACKAGES[tool.adapter], version)
        _link(ctx.paths.npm_prefix / "node_modules" / ".bin" / tool.binary, ctx.paths.local_bin / tool.binary)
    elif tool.adapter == "claude-code":
        _run_saved_installer(ctx, INSTALLER_URLS["claude-code"], "bash", (version,) if version else ())
    else:
        _run_saved_installer(ctx, INSTALLER_URLS[tool.adapter or ""], "bash")


def _install(ctx: _Ctx, tool: ToolSpec) -> None:
    if tool.kind == "uv":
        switches = {"UV_NO_MODIFY_PATH": "1", "UV_INSTALL_DIR": str(ctx.paths.local_bin)}
        _run_saved_installer(ctx, INSTALLER_URLS["uv"], "sh", extra_env=switches)
    elif tool.kind == "node":
        _install_node(ctx, tool)
    elif tool.kind == "openspec":
        _npm_install(ctx, ctx.cfg.spec.openspec.package, tool.version)
    else:
        _install_agent(ctx, tool)


def _verified(ctx: _Ctx, tool: ToolSpec) -> str:
    found = installed_version(tool, ctx.paths, ctx.env, ctx.run)
    if found is None:
        raise InstallFailed(f"{tool.name} was installed but reports no version")
    if not is_satisfied(tool, found):
        wanted = tool.version if tool.kind == "openspec" else f">= {tool.min_version}"
        raise InstallFailed(f"installed {found}, but {wanted} is needed")
    return found


def _apply(ctx: _Ctx, tool: ToolSpec, action: FixAction) -> FixAction:
    manual = manual_command(tool, ctx.platform, str(ctx.paths.l4_home))
    try:
        _install(ctx, tool)
        found = _verified(ctx, tool)
    except OfflineError as exc:
        return action.with_status("failed", f"{exc.for_tool(tool.name, manual)}; run manually: {manual}")
    except IntegrityError as exc:
        return action.with_status("failed", f"{exc}; run manually: {manual}")
    except InstallFailed as exc:
        return action.with_status("failed", f"{exc}; run manually: {manual}")
    except (OSError, tarfile.TarError) as exc:
        return action.with_status("failed", f"{type(exc).__name__}: {exc}; run manually: {manual}")
    target = find_tool(tool.binary, ctx.paths, ctx.env)
    return replace(action, status="applied", message=f"{tool.name} {found}", target=str(target or ""))


def install_planned(
    cfg: L4Config,
    paths: Paths,
    env: Mapping[str, str],
    platform: str,
    *,
    openspec_active: bool,
    fetcher: Fetcher,
    run: CommandRunner,
    os_release: str = "",
    allow_install: bool = True,
) -> list[FixAction]:
    """`plan_fixes`, then every `planned` action carried out in order (uv, Node, OpenSpec, the agent CLIs). Nothing
    planned means no download, no write and no directory (L4-PRV-012, -013)."""
    actions = plan_fixes(
        cfg, paths, env, platform, openspec_active=openspec_active, run=run, os_release=os_release,
        allow_install=allow_install,
    )  # fmt: skip
    if not any(a.status == "planned" for a in actions):
        return actions
    tools = {t.name: t for t in required_tools(cfg, openspec_active=openspec_active)}
    ctx = _Ctx(cfg, paths, env, scrub_env(env, paths), platform, fetcher, run)
    done = []
    for action in actions:
        if action.status == "planned" and action.tool in tools:
            log.info("installing %s", action.tool)
            action = _apply(ctx, tools[action.tool], action)
        done.append(action)
    return done
