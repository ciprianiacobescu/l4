"""What the harness can provision, and the pins it provisions: one table, checked against `scripts/runner/prereqs.sh`
by a drift test. Versions here are defaults; `spec.openspec.version` and `Profile.min_version` come from config."""

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Literal

from l4.config.defaults import OPENSPEC_PACKAGE, OPENSPEC_VERSION
from l4.config.schema import L4Config
from l4.versions import parse_version

PLATFORMS = ("linux-x64", "linux-arm64", "darwin-arm64", "darwin-x64")
UV_VERSION = "0.12.22"
NODE_MIN = "20.19.0"
NODE_VERSION = "22.23.0"
OPENSPEC_DEFAULT = OPENSPEC_VERSION
CLAUDE_VERSION = "2.1.288"
CODEX_VERSION = "0.160.0"
OPENCODE_VERSION = "1.18.34"
# Kiro's installer takes no version argument and ships no changelog we can pin to [U]: it is installed as released.

NPM_PACKAGES = {"codex": "@openai/codex", "opencode": "opencode-ai"}
INSTALLER_URLS = {
    "uv": f"https://astral.sh/uv/{UV_VERSION}/install.sh",
    "claude-code": "https://claude.ai/install.sh",
    "kiro-cli": "https://cli.kiro.dev/install",
}
ADAPTER_BINARIES = {"claude-code": "claude", "codex": "codex", "opencode": "opencode", "kiro-cli": "kiro-cli"}
ADAPTER_PINS = {"claude-code": CLAUDE_VERSION, "codex": CODEX_VERSION, "opencode": OPENCODE_VERSION}


def catalog_pins() -> dict[str, str]:
    """Every version the harness pins for a runner tool (uv, Node, OpenSpec and its package, each agent CLI). Kiro and
    bwrap have no pin [U]: they are installed as released, so they add no entry."""
    pins = {
        "uv": UV_VERSION,
        "node": NODE_VERSION,
        "openspec": f"{OPENSPEC_PACKAGE}@{OPENSPEC_DEFAULT}",
    }
    pins.update({f"agent:{name}": version for name, version in ADAPTER_PINS.items()})
    pins.update({f"npm:{name}": package for name, package in NPM_PACKAGES.items()})
    return pins


def catalog_hash() -> str:
    """The suffix of the agent-CLI cache key (L4-ACT-002): a stable hash of the pinned versions and nothing else, so a
    new harness commit keeps the cache and a changed pin replaces it."""
    text = json.dumps(catalog_pins(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class ToolSpec:
    name: str  # the tool's own name: uv, node, openspec, claude, codex, opencode, kiro-cli
    kind: Literal["uv", "node", "openspec", "agent"]
    binary: str
    version: str | None  # the pinned version that gets installed; None: installed as released
    min_version: str | None  # a present tool at least this new is left alone
    adapter: str | None = None  # agents: the adapter whose profiles need it


def _node_tarball(version: str, platform: str) -> str:
    if platform not in PLATFORMS:
        raise ValueError(f"no Node tarball for platform {platform!r}")
    return f"node-v{version}-{platform}.tar.xz"


def node_tarball_url(version: str, platform: str) -> str:
    return f"https://nodejs.org/dist/v{version}/{_node_tarball(version, platform)}"


def node_shasums_url(version: str) -> str:
    return f"https://nodejs.org/dist/v{version}/SHASUMS256.txt"


def parse_shasums(text: str) -> dict[str, str]:
    """`SHASUMS256.txt`: `<64 hex>  <file name>` per line."""
    found = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) == 2 and re.fullmatch(r"[0-9a-f]{64}", parts[0]):
            found[parts[1].lstrip("*")] = parts[0]
    return found


def node_sha256(shasums: str, version: str, platform: str) -> str:
    name = _node_tarball(version, platform)
    try:
        return parse_shasums(shasums)[name]
    except KeyError:
        raise ValueError(f"SHASUMS256.txt for v{version} does not list {name}") from None


def adapters_in_use(cfg: L4Config) -> dict[str, list[str]]:
    """adapter name -> the profile names that use it, over every role chain (fallbacks included)."""
    used: dict[str, list[str]] = {}
    for role in type(cfg.roles).model_fields:
        for name in getattr(cfg.roles, role):
            profile = cfg.profiles.get(name)
            if profile is not None and profile.adapter in ADAPTER_BINARIES:
                names = used.setdefault(profile.adapter, [])
                if name not in names:
                    names.append(name)
    return used


def required_tools(cfg: L4Config, *, openspec_active: bool) -> list[ToolSpec]:
    """uv always; Node and OpenSpec when OpenSpec is active (Node also when an npm-installed agent is needed); an agent
    CLI only when a profile of its adapter is in some role chain."""
    agents = adapters_in_use(cfg)
    tools = [ToolSpec("uv", "uv", "uv", UV_VERSION, None)]
    if openspec_active or any(a in NPM_PACKAGES for a in agents):
        tools.append(ToolSpec("node", "node", "node", NODE_VERSION, NODE_MIN))
    if openspec_active:
        tools.append(ToolSpec("openspec", "openspec", "openspec", cfg.spec.openspec.version, None))
    for adapter in ADAPTER_BINARIES:
        if adapter not in agents:
            continue
        minimums = [cfg.profiles[n].min_version for n in agents[adapter] if cfg.profiles[n].min_version]
        tools.append(
            ToolSpec(
                ADAPTER_BINARIES[adapter], "agent", ADAPTER_BINARIES[adapter], ADAPTER_PINS.get(adapter),
                max(minimums, key=lambda v: parse_version(v) or (0, 0, 0)) if minimums else None, adapter,
            )
        )  # fmt: skip
    return tools


@dataclass(frozen=True)
class RootPrereq:
    name: str  # what it is called in output
    binary: str
    package: str
    linux_only: bool


ROOT_PREREQS = (
    RootPrereq("bubblewrap", "bwrap", "bubblewrap", True),
    RootPrereq("git", "git", "git", False),
)
_DISTRO_COMMANDS = {
    "apt-get": "sudo apt-get install -y {package}",
    "dnf": "sudo dnf install -y {package}",
}
_FAMILIES = {
    "apt-get": {"debian", "ubuntu"},
    "dnf": {"fedora", "rhel", "centos", "rocky", "almalinux"},
}


def distro_command(prereq: RootPrereq, os_release: str) -> str:
    """The exact line a human runs as root, from `/etc/os-release` `ID` and `ID_LIKE`; a generic instruction when the
    distribution is not recognised. The harness never runs it."""
    fields = {}
    for line in os_release.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            fields[key.strip()] = value.strip().strip("\"'")
    names = {fields.get("ID", "").lower(), *fields.get("ID_LIKE", "").lower().split()}
    for manager, family in _FAMILIES.items():
        if names & family:
            return _DISTRO_COMMANDS[manager].format(package=prereq.package)
    return f"install {prereq.package} with your distribution's package manager (as root)"


def manual_command(tool: ToolSpec, platform: str, l4_home: str) -> str:
    """What a human can run instead (shown on `failed` and `planned` actions; the harness runs its own argv)."""
    pin = f"@{tool.version}" if tool.version else ""
    if tool.kind == "uv":
        return f"curl -LsSf {INSTALLER_URLS['uv']} | env UV_NO_MODIFY_PATH=1 sh"
    if tool.kind == "node":
        url = node_tarball_url(NODE_VERSION, platform) if platform in PLATFORMS else "https://nodejs.org/en/download"
        return f"download {url} and extract it to {l4_home}/node"
    if tool.kind == "openspec":
        return f"npm install --prefix {l4_home}/npm --save-exact {OPENSPEC_PACKAGE}{pin}"
    assert tool.adapter is not None
    if tool.adapter in NPM_PACKAGES:
        return f"npm install --prefix {l4_home}/npm --save-exact {NPM_PACKAGES[tool.adapter]}{pin}"
    version_arg = f" -s {tool.version}" if tool.version else ""
    return f"curl -fsSL {INSTALLER_URLS[tool.adapter]} | bash{version_arg}"
