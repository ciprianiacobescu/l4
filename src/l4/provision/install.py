"""Doing what `plan_fixes` planned (L4-PRV-004/005): user-local installs from saved installers and verified tarballs.

Nothing here runs as root, pipes a download into a shell, or touches a profile file. Every installer runs from a saved
file under `scrub_env`; every install is followed by a version probe from the harness path, and a CLI that is still
below its floor is `failed` with both versions named. A tool that is already present is never reinstalled, so a second
run makes no download and no write. M1: runner-provisioning 2.2 (`provision_lock`), 2.3 (`--fix --dry-run`).
"""

import logging
import os
import shutil
import stat
import tarfile
import tempfile
import time
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import IO

from l4.config.schema import L4Config
from l4.llm.system_one import laya_interpreter
from l4.proc import Runner as CommandRunner
from l4.provision.catalog import (
    INSTALLER_URLS,
    KIRO_MEMBER_MAX,
    KIRO_MEMBERS,
    LAYA_CHECKPOINT,
    LAYA_REPO,
    LAYA_REVISION,
    NODE_VERSION,
    NPM_PACKAGES,
    SUPPORTED_MAJORS,
    ToolSpec,
    kiro_archive_url,
    kiro_digest,
    kiro_platform,
    kiro_unheld_text,
    major_verified_text,
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
    laya_checkpoint_cached,
    plan_fixes,
    save_installer,
    scrub_env,
    verify_sha256,
    wrong_major,
)
from l4.versions import major_of

log = logging.getLogger("l4.provision")

INSTALL_TIMEOUT_S = 900.0
STALE_AFTER_S = 3600.0
STDERR_TAIL = 300
NODE_LINKS = ("node", "npm", "npx")
SYSTEM_DIRS = ("/usr/bin", "/bin")  # where `sh` and `bash` are even when the runner's PATH is sparse


class InstallFailed(Exception):
    """An installer ran and did not leave a usable tool; the message is what a human reads. `manual` False leaves the
    manual command off the action (a command that would fail the same way)."""

    def __init__(self, message: str, *, manual: bool = True) -> None:
        super().__init__(message)
        self.manual = manual


@dataclass(frozen=True)
class _Ctx:
    cfg: L4Config
    paths: Paths
    env: Mapping[str, str]
    clean: Mapping[str, str]
    platform: str
    fetcher: Fetcher
    run: CommandRunner
    replace_present: bool = False  # `doctor --ci`: an agent CLI must be exactly its pin after an install (D5)

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


def _link(target: Path, link: Path, *, replace_files: bool = True) -> None:
    """Point `link` at `target`, replacing what is there. With `replace_files` False a path that exists and is not a
    symlink is never replaced (it may be a person's own binary): `InstallFailed` names it (L4-OCG-004)."""
    link.parent.mkdir(parents=True, exist_ok=True)
    if not replace_files and not link.is_symlink() and link.exists():
        raise InstallFailed(f"{link} is a regular file, not a link, and is never replaced")
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
        _link(
            ctx.paths.npm_prefix / "node_modules" / ".bin" / tool.binary, ctx.paths.local_bin / tool.binary,
            replace_files=tool.adapter not in SUPPORTED_MAJORS,
        )  # fmt: skip
    elif tool.adapter == "claude-code":
        _run_saved_installer(ctx, INSTALLER_URLS["claude-code"], "bash", (version,) if version else ())
    elif tool.adapter == "kiro-cli":
        _install_kiro(ctx, tool)
    else:
        raise InstallFailed(f"no installer for {tool.name}")


def _copy_bounded(source: IO[bytes], target: IO[bytes], limit: int) -> None:
    """Copy at most `limit` bytes; a member that runs past it (a header that understated its size) fails."""
    written = 0
    while block := source.read(1 << 20):
        written += len(block)
        if written > limit:
            raise InstallFailed("a member of the Kiro archive is larger than its header says")
        target.write(block)


def _swap_in_kiro(archive: Path, destination: Path) -> None:
    """Check the three members (exact names, regular files, at most `KIRO_MEMBER_MAX`), stage each beside its target
    with mode 0755, and rename them over their targets only when all three are staged, `kiro-cli` last (D2). Nothing
    else in the archive is read; any error removes every staged file and leaves `destination` as it was."""
    with zipfile.ZipFile(archive) as zipped:
        infos = []
        for member in KIRO_MEMBERS:
            try:
                info = zipped.getinfo(member)
            except KeyError:
                raise InstallFailed(f"{member} is missing from the Kiro archive") from None
            if not stat.S_ISREG(info.external_attr >> 16):
                raise InstallFailed(f"{member} in the Kiro archive is not a regular file")
            if info.file_size > KIRO_MEMBER_MAX:
                raise InstallFailed(f"{member} in the Kiro archive is larger than {KIRO_MEMBER_MAX} bytes")
            infos.append(info)
        destination.mkdir(parents=True, exist_ok=True)
        staged: list[tuple[Path, Path]] = []
        backups: dict[Path, Path | None] = {}  # target -> its backup, None when the target did not exist
        try:
            for info in infos:
                name = Path(info.filename).name
                part = destination / f".{name}.tmp.{os.getpid()}"
                part.unlink(missing_ok=True)  # never write through a link planted at the predictable path
                staged.append((part, destination / name))
                try:
                    fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                    with os.fdopen(fd, "wb") as target, zipped.open(info) as source:
                        _copy_bounded(source, target, KIRO_MEMBER_MAX)
                except OSError as exc:
                    raise InstallFailed(f"cannot write {info.filename}: {exc.strerror or exc}") from None
                part.chmod(0o755)
            for _, final in staged:
                backups[final] = _back_up(final)
            try:
                for part, final in staged:
                    os.replace(part, final)
            except OSError:
                _restore(backups)
                raise
        finally:
            for part, _ in staged:
                part.unlink(missing_ok=True)
            for backup in backups.values():
                if backup is not None:
                    backup.unlink(missing_ok=True)


def _back_up(final: Path) -> Path | None:
    """Keep what `final` holds beside it as `<name>.bak.<pid>` (a hard link, else a copy); None when it is absent."""
    if not final.is_file():
        return None
    backup = final.with_name(f"{final.name}.bak.{os.getpid()}")
    backup.unlink(missing_ok=True)
    try:
        os.link(final, backup)
    except OSError:
        shutil.copy2(final, backup)
    return backup


def _restore(backups: dict[Path, Path | None]) -> None:
    """Put every original back (a failure of one restore does not stop the others) and remove a file that had none."""
    for final, backup in backups.items():
        try:
            if backup is None:
                final.unlink(missing_ok=True)
            else:
                os.replace(backup, final)
        except OSError:
            continue


def _install_kiro(ctx: _Ctx, tool: ToolSpec) -> None:
    """Design D2: the versioned archive, checked against the harness's digest table, three files into `~/.local/bin`.
    The vendor's installer script is never downloaded and no file of the archive is run."""
    version = tool.version or ""
    try:
        key = kiro_platform(ctx.platform)
    except ValueError as exc:
        raise InstallFailed(str(exc)) from None
    expected = kiro_digest(version, key)
    if expected is None:
        raise InstallFailed(kiro_unheld_text(version, tool.pin_source))
    url = kiro_archive_url(version, key)
    with tempfile.TemporaryDirectory(prefix="kiro-", dir=ctx.downloads) as tmp:
        try:
            archive = ctx.fetcher.download(url, Path(tmp) / url.rsplit("/", 1)[1])
        except OfflineError as exc:
            if exc.reason in ("HTTP 403", "HTTP 404"):
                raise InstallFailed(
                    f"cannot download kiro-cli {version} from {exc.host} ({exc.reason}): that version may no longer "
                    "be served; hold another version in ci.cli_versions (one the harness holds) or report it",
                    manual=False,
                ) from None
            raise
        verify_sha256(archive, expected, "the harness's digest")
        _swap_in_kiro(archive, ctx.paths.local_bin)
        log.info("provision: kiro-cli %s from %s (sha256 %s, the harness's table)", version, url, expected)


def _install_laya(ctx: _Ctx, tool: ToolSpec) -> None:
    """Design D9: the wheels go to Laya's own uv tool directory (CPU torch), `laya-serve` is linked into the user's bin,
    and the checkpoint goes to the l4 Hugging Face home. Whatever is already there at the pin is kept: only the missing
    half is installed, so a runner that `prereqs.sh` provisioned downloads nothing again."""
    laya = ctx.paths.laya_tools
    if not is_satisfied(tool, installed_version(tool, ctx.paths, ctx.env, ctx.run)):
        uv = find_tool("uv", ctx.paths, ctx.env)
        if uv is None:
            raise InstallFailed("uv is not available: install uv first")
        switches = {"UV_TOOL_DIR": str(laya), "UV_TOOL_BIN_DIR": str(laya / "bin")}
        argv = [str(uv), "tool", "install", "--torch-backend", "cpu", f"laya[serve]=={tool.version}"]
        _checked(ctx, argv, env={**ctx.clean, **switches})
        _link(laya / "bin" / tool.binary, ctx.paths.local_bin / tool.binary)
    if not laya_checkpoint_cached(ctx.paths, ctx.env):
        found = find_tool(tool.binary, ctx.paths, ctx.env)  # the Laya just installed, or the one that was there
        python = (laya_interpreter(str(found)) if found else "") or str(laya / "laya" / "bin" / "python")
        code = (
            "from huggingface_hub import snapshot_download as s; "
            f"s({LAYA_REPO!r}, revision={LAYA_REVISION!r}, allow_patterns=[{LAYA_CHECKPOINT + '/*'!r}])"
        )
        hf_home = ctx.paths.laya_hf_home
        hf_home.mkdir(parents=True, exist_ok=True)
        _checked(ctx, [python, "-c", code], env={**ctx.clean, "HF_HOME": str(hf_home)})


def _install(ctx: _Ctx, tool: ToolSpec) -> None:
    if tool.kind == "laya":
        _install_laya(ctx, tool)
    elif tool.kind == "uv":
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
    if wrong_major(tool, found):  # the binary the harness path resolves, not the one just installed (L4-OCG-004)
        resolved = find_tool(tool.binary, ctx.paths, ctx.env)
        raise InstallFailed(
            major_verified_text(
                tool.adapter or "", tool.name, resolved, found, major_of(found) or 0, tool.version or ""
            )
        )
    exact = tool.kind == "agent" and (ctx.replace_present or tool.adapter == "kiro-cli")
    if not is_satisfied(tool, found, exact=exact):
        if exact:
            raise InstallFailed(f"installed {found}, but {tool.version} (pinned) is needed")
        wanted = tool.version if tool.kind in ("openspec", "laya") else f">= {tool.min_version}"
        raise InstallFailed(f"installed {found}, but {wanted} is needed")
    if tool.kind == "laya" and not laya_checkpoint_cached(ctx.paths, ctx.env):
        raise InstallFailed(f"the {LAYA_CHECKPOINT} checkpoint is not in the Hugging Face cache after the fetch")
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
        return action.with_status("failed", f"{exc}; run manually: {manual}" if exc.manual else str(exc))
    except (OSError, tarfile.TarError, zipfile.BadZipFile) as exc:
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
    replace_present: bool = False,
) -> list[FixAction]:
    """`plan_fixes`, then every `planned` action carried out in order (uv, Node, OpenSpec, the agent CLIs). Nothing
    planned means no download, no write and no directory (L4-PRV-012, -013)."""
    actions = plan_fixes(
        cfg, paths, env, platform, openspec_active=openspec_active, run=run, os_release=os_release,
        allow_install=allow_install, replace_present=replace_present,
    )  # fmt: skip
    if not any(a.status == "planned" for a in actions):
        return actions
    tools = {t.name: t for t in required_tools(cfg, openspec_active=openspec_active)}
    ctx = _Ctx(cfg, paths, env, scrub_env(env, paths), platform, fetcher, run, replace_present)
    done = []
    for action in actions:
        if action.status == "planned" and action.tool in tools:
            log.info("installing %s", action.tool)
            action = _apply(ctx, tools[action.tool], action)
        done.append(action)
    return done
