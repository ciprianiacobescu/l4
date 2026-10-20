"""Paths, environment, downloads and the plan of `doctor --fix` (SPEC L4-DOC-002, runner-provisioning D2-D7).

Everything that touches the network goes through a `Fetcher` and every child process through a `CommandRunner`
(`l4.proc.Runner`), so a test can replace both. M1: runner-provisioning 2.2 (`provision_lock`).
"""

import hashlib
import logging
import os
import platform as platform_module
import shutil
import socket
import ssl
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal, Protocol

import httpx

from l4.config.defaults import cache_root, l4_home, openspec_entrypoint, openspec_env
from l4.config.schema import L4Config
from l4.doctor.context import CmdResult
from l4.llm.system_one import laya_checkpoint_present, laya_version
from l4.proc import Runner as CommandRunner
from l4.provision.catalog import (
    LAYA_CHECKPOINT,
    ROOT_PREREQS,
    SUPPORTED_MAJORS,
    ToolSpec,
    distro_command,
    manual_command,
    required_tools,
)
from l4.safepath import safe_path
from l4.versions import major_of, parse_version, version_at_least

log = logging.getLogger("l4.provision")

# kept in a child's environment; everything else (forge tokens, agent keys, CI variables) is dropped (L4-PRV-015)
_KEEP = (
    "HOME", "LANG", "TMPDIR", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY", "http_proxy", "https_proxy",
    "no_proxy", "all_proxy", "SSL_CERT_FILE", "SSL_CERT_DIR", "NODE_EXTRA_CA_CERTS", "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
)  # fmt: skip
VERSION_TIMEOUT_S = 30.0


@dataclass(frozen=True)
class Paths:
    home: Path
    local_bin: Path
    l4_home: Path
    l4_cache: Path

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "Paths":
        home = Path(env["HOME"]) if env.get("HOME") else Path.home()
        return cls(home, home / ".local" / "bin", l4_home(env), cache_root(env))

    @property
    def npm_prefix(self) -> Path:
        return self.l4_home / "npm"

    @property
    def laya_tools(self) -> Path:
        """Laya's own uv tool directory, apart from the harness's (L4-ADO-019, design D9)."""
        return self.l4_home / "laya"

    @property
    def laya_hf_home(self) -> Path:
        return self.l4_cache / "laya" / "hf"


def laya_checkpoint_cached(paths: Paths, env: Mapping[str, str]) -> bool:
    """The checkpoint is in the Hugging Face cache of the environment (`HF_HOME`, else the default) or in ours."""
    return laya_checkpoint_present(env, LAYA_CHECKPOINT) or laya_checkpoint_present(
        {"HF_HOME": str(paths.laya_hf_home)}, LAYA_CHECKPOINT
    )


def harness_path(paths: Paths, inherited: str = "", *, forbid: Sequence[Path] = ()) -> str:
    """PATH for every tool the harness starts: user-local installs first, then what the environment brought. Empty,
    relative and in-checkout entries of the inherited PATH are dropped (L4-SEC-006)."""
    first = [
        paths.local_bin, paths.l4_home / "node" / "bin", paths.npm_prefix / "node_modules" / ".bin",
        paths.home / ".opencode" / "bin",
    ]  # fmt: skip
    return safe_path({"PATH": os.pathsep.join([*map(str, first), inherited])}, forbid=forbid)


def find_tool(name: str, paths: Paths, env: Mapping[str, str], *, forbid: Sequence[Path] = ()) -> Path | None:
    found = shutil.which(name, path=harness_path(paths, env.get("PATH", ""), forbid=forbid))
    return Path(found) if found else None


def resolve_self_provision(cfg: L4Config, env: Mapping[str, str]) -> bool:
    """`auto` provisions on a persistent runner and not on a disposable or GitHub-hosted one (L4-PRV-010).
    `L4_SELF_PROVISION` = true | false | auto (any case) replaces the configured value (L4-PRV-019); any other
    non-empty value is ignored with one warning and the configured value applies."""
    setting = cfg.ci.self_provision
    raw = env.get("L4_SELF_PROVISION", "")
    override = raw.strip().lower()
    if override in ("true", "false", "auto"):
        setting = {"true": True, "false": False, "auto": "auto"}[override]
    elif override:
        log.warning(
            "ignoring L4_SELF_PROVISION=%r: not true, false or auto; the configured ci.self_provision applies", raw
        )
    if setting != "auto":
        return setting
    return env.get("CI_DISPOSABLE_ENVIRONMENT") != "true" and env.get("RUNNER_ENVIRONMENT") != "github-hosted"


def scrub_env(env: Mapping[str, str], paths: Paths) -> dict[str, str]:
    """The environment of an installer: an allow-list, PATH from `harness_path`, npm's cache under `$L4_CACHE`."""
    clean = {k: v for k, v in env.items() if k in _KEEP or k.startswith("LC_")}
    clean["PATH"] = harness_path(paths, env.get("PATH", ""))
    clean["npm_config_cache"] = str(paths.l4_cache / "npm")
    clean["DISABLE_AUTOUPDATER"] = "1"  # L4-PRV-044; never DISABLE_UPDATES, which blocks `claude install`
    return clean


def detect_platform() -> str:
    system = platform_module.system().lower()
    machine = platform_module.machine().lower()
    arch = {"x86_64": "x64", "amd64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(machine, machine)
    return f"{system}-{arch}"


# --- downloads ---


class OfflineError(Exception):
    """A download did not happen. Maps to a `failed` action and exit 3; `manual_command` tells a human what to run."""

    def __init__(self, host: str, reason: str, tool: str = "", manual_command: str = "") -> None:
        super().__init__(f"cannot download from {host} ({reason})" + (f" to install {tool}" if tool else ""))
        self.host, self.reason, self.tool, self.manual_command = host, reason, tool, manual_command

    def for_tool(self, tool: str, manual: str) -> "OfflineError":
        return OfflineError(self.host, self.reason, tool, manual)


class IntegrityError(Exception):
    """A downloaded file does not match its published digest; the partial files are already removed."""


class Fetcher(Protocol):
    def download(self, url: str, dest: Path) -> Path: ...

    def reachable(self, host: str) -> bool: ...


class HttpxFetcher:
    """connect 10 s, read 300 s; one retry on an HTTP 5xx and none on a transport error (a missing network is a
    configuration problem, not a transient one)."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        timeout = httpx.Timeout(connect=10.0, read=300.0, write=60.0, pool=10.0)
        self._client = client or httpx.Client(timeout=timeout, follow_redirects=True)

    def download(self, url: str, dest: Path) -> Path:
        host = httpx.URL(url).host
        for attempt in (1, 2):
            try:
                with self._client.stream("GET", url) as response:
                    if response.status_code >= 500 and attempt == 1:
                        continue
                    if response.status_code >= 400:
                        raise OfflineError(host, f"HTTP {response.status_code}")
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with dest.open("wb") as handle:
                        for chunk in response.iter_bytes():
                            handle.write(chunk)
                    return dest
            except httpx.TransportError as exc:
                dest.unlink(missing_ok=True)
                raise OfflineError(host, type(exc).__name__) from None
        raise AssertionError("unreachable")  # pragma: no cover  (attempt 2 always returns or raises)

    def reachable(self, host: str) -> bool:
        try:
            with socket.create_connection((host, 443), timeout=10) as raw:
                ssl.create_default_context().wrap_socket(raw, server_hostname=host).close()
        except OSError:
            return False
        return True


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_sha256(path: Path, expected: str) -> None:
    """Compare against the published digest; on a mismatch the file is removed and `IntegrityError` raised."""
    actual = sha256_of(path)
    if actual != expected.lower():
        path.unlink(missing_ok=True)
        raise IntegrityError(f"{path.name}: sha256 {actual} does not match the published {expected}")


def save_installer(fetcher: Fetcher, url: str, dest: Path, *, expected: str | None = None) -> str:
    """Download an installer script to a file (never into a shell), log its digest, return it. The file appears at
    `dest` only when complete (and, with `expected`, verified); nothing is left behind on failure."""
    partial = dest.with_name(f".{dest.name}.partial")
    try:
        fetcher.download(url, partial)
        if expected is not None:
            verify_sha256(partial, expected)
        digest = sha256_of(partial)
        partial.chmod(0o700)
        partial.replace(dest)
    finally:
        partial.unlink(missing_ok=True)
    log.info("saved installer %s sha256=%s", url, digest)
    return digest


# --- never authenticate, never escalate ---

_FORBIDDEN_ARGV = (("login",), ("setup-token",), ("auth", "login"))
_ESCALATION = ("sudo", "su", "doas")


class RefusedCommand(Exception):
    pass


class GuardedCommandRunner:
    """Wraps a `CommandRunner` and refuses to start anything that would log in or escalate (L4-PRV-006, -007)."""

    def __init__(self, inner: CommandRunner) -> None:
        self._inner = inner

    def __call__(self, argv: Sequence[str], cwd: Path, env: Mapping[str, str], timeout: float) -> CmdResult:
        names = [Path(a).name for a in argv]
        if names and names[0] in _ESCALATION:
            raise RefusedCommand(f"refusing to run {names[0]}: the harness never escalates privileges")
        for pattern in _FORBIDDEN_ARGV:
            width = len(pattern)
            if any(tuple(argv[i : i + width]) == pattern for i in range(len(argv) - width + 1)):
                raise RefusedCommand(f"refusing to run `{' '.join(pattern)}`: the harness never authenticates")
        return self._inner(argv, cwd, env, timeout)


# --- the plan ---

Status = Literal["planned", "applied", "already present", "manual", "failed", "skipped"]


@dataclass(frozen=True)
class FixAction:
    tool: str
    reason: str
    target: str
    commands: tuple[str, ...]  # shown to a human; the harness runs its own argv
    needs_root: bool
    status: Status
    message: str = ""

    def with_status(self, status: Status, message: str = "") -> "FixAction":
        return replace(self, status=status, message=message)


def installed_version(tool: ToolSpec, paths: Paths, env: Mapping[str, str], run: CommandRunner) -> str | None:
    """The version a present tool reports, or None when it is missing or does not report one. OpenSpec is asked the way
    the provider runs it (L4-OSP-001): the harness node on the file, never the shim."""
    clean = scrub_env(env, paths)
    if tool.kind == "laya":  # the version of the `laya` package that the `laya-serve` on PATH belongs to
        exe = find_tool(tool.binary, paths, env)
        return (laya_version(str(exe), clean) or None) if exe is not None else None
    if tool.kind == "openspec":
        entry, node = openspec_entrypoint(env), find_tool("node", paths, env)
        if not entry.is_file() or node is None:
            return None
        done = run([str(node), str(entry), "--version"], paths.home, openspec_env(env), VERSION_TIMEOUT_S)
    else:
        exe = find_tool(tool.binary, paths, env)
        if exe is None:
            return None
        done = run([str(exe), "--version"], paths.home, clean, VERSION_TIMEOUT_S)
    found = parse_version(done.stdout) if done.returncode == 0 else None
    return ".".join(map(str, found)) if found else None


def wrong_major(tool: ToolSpec, found: str) -> bool:
    """An agent CLI listed in `SUPPORTED_MAJORS` whose found version has another major (OpenCode v2 as `opencode`)."""
    supported = SUPPORTED_MAJORS.get(tool.adapter or "")
    return supported is not None and major_of(found) not in (None, supported)


def is_satisfied(tool: ToolSpec, found: str | None) -> bool:
    if found is None:
        return False
    if tool.kind in ("openspec", "laya"):
        return tool.version is not None and parse_version(found) == parse_version(tool.version)
    if wrong_major(tool, found):  # a different program under the same name: no floor can make it right (L4-OCG-004)
        return False
    return tool.min_version is None or version_at_least(found, tool.min_version) is True


def plan_root_prereqs(paths: Paths, env: Mapping[str, str], platform: str, os_release: str) -> list[FixAction]:
    """Prerequisites only root can install: a `manual` action with the exact line, never an argv we start."""
    actions = []
    for prereq in ROOT_PREREQS:
        if (prereq.linux_only and not platform.startswith("linux")) or find_tool(prereq.binary, paths, env):
            continue
        command = distro_command(prereq, os_release)
        actions.append(
            FixAction(prereq.name, f"{prereq.binary} is not on PATH", "system", (command,), True, "manual", command)
        )
    return actions


def _floor_above_pin(tool: ToolSpec) -> bool:
    """An agent whose profile floor is newer than the version the harness pins: the harness installs only what it has
    vetted, so it never downloads an installer for such a version (the floor stays the person's to resolve)."""
    return (
        tool.kind == "agent" and tool.version is not None and tool.min_version is not None
        and version_at_least(tool.min_version, tool.version) is True
        and version_at_least(tool.version, tool.min_version) is not True
    )  # fmt: skip


def plan_fixes(
    cfg: L4Config,
    paths: Paths,
    env: Mapping[str, str],
    platform: str,
    *,
    openspec_active: bool,
    run: CommandRunner,
    os_release: str = "",
    allow_install: bool = True,
) -> list[FixAction]:
    """One action per needed tool: `already present` (decided by running its version probe from the harness path),
    `planned`, or `skipped` when installs are switched off. Root-only prerequisites follow as `manual` actions."""
    actions: list[FixAction] = []
    for tool in required_tools(cfg, openspec_active=openspec_active):
        found = installed_version(tool, paths, env, run)
        command = manual_command(tool, platform, str(paths.l4_home))
        if tool.kind == "laya" and is_satisfied(tool, found) and not laya_checkpoint_cached(paths, env):
            reason = f"laya {found} without the {LAYA_CHECKPOINT} checkpoint"
            status: Status = "planned" if allow_install else "skipped"
            message = "" if allow_install else "ci.self_provision resolves to false"
            actions.append(FixAction(tool.name, reason, "", (command,), False, status, message))
        elif is_satisfied(tool, found):
            actions.append(FixAction(tool.name, "needed", str(find_tool(tool.binary, paths, env)), (), False,
                                     "already present", f"{tool.name} {found}"))  # fmt: skip
        elif _floor_above_pin(tool):
            actions.append(FixAction(tool.name, "needed", "", (command,), False, "skipped",
                                     f"min_version {tool.min_version} is above the pinned {tool.version}; "
                                     "not installing"))  # fmt: skip
        elif not allow_install:
            actions.append(FixAction(tool.name, "needed", "", (command,), False, "skipped",
                                     "ci.self_provision resolves to false"))  # fmt: skip
        else:
            if found is not None and wrong_major(tool, found):
                supported = SUPPORTED_MAJORS[tool.adapter or ""]
                reason = (
                    f"found {found} (OpenCode v{major_of(found)}), need opencode-ai {supported}.x "
                    f"(pinned {tool.version})"
                )
            else:
                reason = "missing" if found is None else f"found {found}, need {tool.min_version or tool.version}"
            actions.append(FixAction(tool.name, reason, "", (command,), False, "planned"))
    return [*actions, *plan_root_prereqs(paths, env, platform, os_release)]
