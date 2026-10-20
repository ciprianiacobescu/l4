"""What the harness can provision, and the pins it provisions: one table, checked against `scripts/runner/prereqs.sh`
by a drift test. Versions here are defaults; `spec.openspec.version` and `Profile.min_version` come from config."""

import hashlib
import json
import os
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Literal, NamedTuple

from l4.config.defaults import LAYA_VERSION, OPENSPEC_PACKAGE, OPENSPEC_VERSION
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
# Laya (System One, L4-ADO-019): the pin is `defaults.LAYA_VERSION` (the doctor compares against it); the checkpoint
# is the folder of `LAYA_REPO` that `laya-serve` loads. `scripts/runner/prereqs.sh` carries the same two defaults.
LAYA_CHECKPOINT = "typed-decisions"
LAYA_REPO = "convaiinnovations/laya"
# The commit of `LAYA_REPO` the checkpoint is fetched at: a branch moves, a commit does not. Inferred, not re-checked
# against the network: the only snapshot in the development machine's Hugging Face cache that holds `typed-decisions`
# (the `refs/main` it had at the time). Move it only with a test run against the new weights.
LAYA_REVISION = "7b928d828b7b0e022f929d9bd2e44165aa270148"
# Kiro (L4-PRV-042): the harness downloads the versioned archive itself and checks it against `KIRO_SHA256`; it never
# runs Kiro's installer script and never reads the moving alias. `scripts/runner/prereqs.sh` carries the pin's row.
KIRO_VERSION = "2.32.0"
KIRO_DOWNLOAD = "https://prod.download.cli.kiro.dev/stable"
# version -> platform key -> sha256 of the archive, from `stable/index.json` on 2026-10-20 (recomputed over the bytes
# for the pin by `docs/live/pin-clis/README.md`). The pin and the versions with recorded fixtures: a team can hold one.
KIRO_SHA256: dict[str, dict[str, str]] = {
    "2.32.0": {
        "linux-x64": "7cea2c90198edc60ccaee9e0d9c9de26902b3824f54a66aa3639a365f7242fbb",
        "linux-arm64": "f66faaa3fa202e7730979e10ad907c43f83220577609c97fdffbb07fc8ef1848",
        "linux-x64-musl": "f12968c2b154cd17f4d1d68b563f3dfba2135065c5c6552f19cceddd60258485",
        "linux-arm64-musl": "219a047427ca2b43681f4788104df5e784eda030d98abeec1c732aac9090eb8b",
    },
    "2.28.0": {
        "linux-x64": "4d6d20c3ffed99904081a062678b3c1978dc7d68c9f6c530f3f28f163011c8ee",
        "linux-arm64": "39169fc43557ff3c007ccf5388ff95413539b2c6a8dfab6c69e4a7b8899bebbc",
        "linux-x64-musl": "8ee7e1b789af4d506ebd661fe4a2d88a1cf20b4027170aae7c3cd1daf348b98c",
        "linux-arm64-musl": "c91fb5b7bec67acbbe0cdbc239f7a6b8e541f6bff2db32e418b0e3090f5e38b2",
    },
    "2.27.1": {
        "linux-x64": "e68927fe0bffb752746a573010cb68792b0f3e97be3a6ce73792c9cc02f08007",
        "linux-arm64": "abdb1f8167693f34163c1b053ccdce4819e191140e9319a0c78c55c252b11d83",
        "linux-x64-musl": "7c7a9f5e3284c82cc6f0fb1a301597368538adb83d916927e664c957a9f953ef",
        "linux-arm64-musl": "937ff1ae3df373717b66cc09aec79c3b7f0b8e53968d746e3a4545722e1e4587",
    },
}
# The macOS disk images (shown in a manual command, never installed by the harness, D4).
KIRO_DMG_SHA256 = {
    "2.32.0": "88721f97dbe98c9e4f84a46e8a2584a8dd29289b81264d96ee2987dd2c014e3c",
    "2.28.0": "5119dfebf8234d336af874af631d1039e3b9a9bbd6da1c71874f5855173a91c8",
    "2.27.1": "850da13e0667f5bc4ef645526b5ba08a50dc8442cd92bad1ffc7546a7ce8195c",
}
KIRO_MEMBERS = ("kirocli/bin/kiro-cli-term", "kirocli/bin/kiro-cli-chat", "kirocli/bin/kiro-cli")
KIRO_MEMBER_MAX = 512 * 1024 * 1024

NPM_PACKAGES = {"codex": "@openai/codex", "opencode": "opencode-ai"}
INSTALLER_URLS = {
    "uv": f"https://astral.sh/uv/{UV_VERSION}/install.sh",
    "claude-code": "https://claude.ai/install.sh",
}
ADAPTER_BINARIES = {"claude-code": "claude", "codex": "codex", "opencode": "opencode", "kiro-cli": "kiro-cli"}
ADAPTER_PINS = {
    "claude-code": CLAUDE_VERSION, "codex": CODEX_VERSION, "opencode": OPENCODE_VERSION, "kiro-cli": KIRO_VERSION,
}  # fmt: skip
# The major of each agent CLI the harness supports where a wrong major is a different program under the same name
# (L4-OCG-001, L4-OCG-005). `opencode` and `kiro-cli` (Kiro CLI 3 changes the engine): Claude Code updates itself and
# Codex is 0.x. It follows the pin.
SUPPORTED_MAJORS = {
    "opencode": (parse_version(OPENCODE_VERSION) or (0, 0, 0))[0],
    "kiro-cli": (parse_version(KIRO_VERSION) or (0, 0, 0))[0],
}


_REPORTED = re.compile(r"\d+\.\d+\.\d+", re.ASCII)  # what every caller counts as "reported a version"


def reported_version(text: str) -> tuple[int, int, int] | None:
    """The first `N.N.N` in `text`, whatever precedes it (`x1.2.3`, `opencode_2.0.32`): the text the callers
    report as the version, so the major gate reads the same one (L4-OCG-002). None when there is none."""
    found = _REPORTED.search(text[:4096])
    if found is None:
        return None
    major, minor, patch = (int(n) for n in found.group(0).split("."))
    return major, minor, patch


class MajorWords(NamedTuple):
    """Every text about a wrong major of one adapter (L4-OCG-002, L4-OCG-005). `problem` fills {binary} {version}
    {major} {supported} {pin}; the other fields build the texts derived below."""

    product: str  # the fail-closed text and the load error
    major_name: str  # "{major}" filled: the found major as the product names it
    need: str  # "{supported}" filled: what the harness needs
    problem: str


MAJOR_WORDS: dict[str, MajorWords] = {
    "opencode": MajorWords(
        "OpenCode",
        "OpenCode v{major}",
        "opencode-ai {supported}.x",
        "{binary} {version} is OpenCode v{major}; this profile runs v{supported} (opencode-ai {supported}.x): install "
        "opencode-ai@{pin} (l4 doctor --fix installs it user-locally); OpenCode 2 support comes in a later L4 release",
    ),
    "kiro-cli": MajorWords(
        "Kiro CLI",
        "Kiro CLI {major}",
        "kiro-cli {supported}.x",
        "{binary} {version} is Kiro CLI {major}; L4 runs Kiro CLI {supported}: install kiro-cli {pin} (in CI l4 "
        "doctor --ci --fix installs it; l4 doctor prints the command for this machine); Kiro CLI 3 support comes in "
        "a later L4 release",
    ),
}


def major_problem(adapter: str, binary: str, version_text: str, pin: str) -> str | None:
    """Why `binary`'s `--version` output (`version_text`) is of a major the adapter does not run, or None: the
    adapter is not gated, the text holds no version (the caller says so), or the major is the supported one. The one
    text every caller (probe, doctor, provisioning) prints (L4-OCG-002, L4-OCG-005)."""
    supported = SUPPORTED_MAJORS.get(adapter)
    found = reported_version(version_text) or parse_version(version_text)
    if supported is None or found is None or found[0] == supported:
        return None
    return MAJOR_WORDS[adapter].problem.format(
        binary=binary, version=f"{found[0]}.{found[1]}.{found[2]}", major=found[0], supported=supported, pin=pin
    )


def major_plan_reason(adapter: str, found: str, major: int, pin: str) -> str:
    """The `plan_fixes` reason for a present CLI of another major."""
    words = MAJOR_WORDS[adapter]
    need = words.need.format(supported=SUPPORTED_MAJORS[adapter])
    return f"found {found} ({words.major_name.format(major=major)}), need {need} (pinned {pin})"


def major_verified_text(adapter: str, name: str, path: object, found: str, major: int, pin: str) -> str:
    """What a failed install says when the CLI on the harness path is still of another major."""
    words = MAJOR_WORDS[adapter]
    need = words.need.format(supported=SUPPORTED_MAJORS[adapter])
    return (
        f"{name} at {path} reports {found} ({words.major_name.format(major=major)}) after the install, "
        f"need {need} (pinned {pin})"
    )


def major_no_version_text(adapter: str, binary: str) -> str:
    """ENV-004's fail-closed text for a gated CLI whose `--version` holds no version."""
    return f"{binary} reports no version, so its {MAJOR_WORDS[adapter].product} major cannot be checked"


def major_config_error(adapter: str, key: str, value: str, major: int) -> str:
    """The load error of `ci.cli_versions` for a version of another major (L4-PRV-045)."""
    product, supported = MAJOR_WORDS[adapter].product, SUPPORTED_MAJORS[adapter]
    return (
        f"ci.cli_versions: {key}: {value} is {product} {major}; this harness runs {product} {supported} "
        "(L4-OCG-001, L4-OCG-005); a major moves with an L4 release, not with configuration"
    )


def effective_pins(cfg: L4Config | None) -> dict[str, tuple[str, str]]:
    """Each adapter's version and where it comes from: `ci.cli_versions` (L4-PRV-045) or the catalog."""
    held = cfg.ci.cli_versions if cfg is not None else {}
    return {
        adapter: (held[adapter], "ci.cli_versions") if adapter in held else (pin, "catalog")
        for adapter, pin in ADAPTER_PINS.items()
    }


def catalog_pins() -> dict[str, str]:
    """Every version the harness pins for a runner tool (uv, Node, OpenSpec and its package, each agent CLI). bwrap has
    no pin [U]: it is installed as released, so it adds no entry."""
    pins = {
        "uv": UV_VERSION,
        "node": NODE_VERSION,
        "openspec": f"{OPENSPEC_PACKAGE}@{OPENSPEC_DEFAULT}",
    }
    pins.update({f"agent:{name}": version for name, version in ADAPTER_PINS.items()})
    pins.update({f"npm:{name}": package for name, package in NPM_PACKAGES.items()})
    return pins


def catalog_hash(adapters: Iterable[str] = (), overrides: Mapping[str, str] | None = None) -> str:
    """The suffix of the agent-CLI cache key (L4-ACT-002): a stable hash of the pinned versions and the sorted set of
    agent CLIs the repository's config needs (`adapters`), so a new harness commit keeps the cache, a changed pin
    replaces it, and a CLI that joins or leaves the role chains is a new key (a cache saved without it is not a hit).
    `overrides` (adapter -> the version `ci.cli_versions` holds) is part of the key only when there is one, so a
    config without an override keeps the catalog's key. With no adapters, the hash of the pins alone."""
    needed = sorted(set(adapters))
    document: dict[str, object] = dict(catalog_pins())
    if needed:
        document["clis"] = needed
    if overrides:
        document["overrides"] = dict(sorted(overrides.items()))
    text = json.dumps(document, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def clis_cache_hash(cfg: L4Config | None) -> str:
    """`catalog_hash` for the agent CLIs `cfg` needs (the adapters of the profiles in the role chains, which
    `required_tools` installs); the catalog alone for no config."""
    if cfg is None:
        return catalog_hash()
    used = adapters_in_use(cfg)
    return catalog_hash(used, {a: v for a, v in cfg.ci.cli_versions.items() if a in used})


_GLIBC = re.compile(r"glibc\s+(\d+)\.(\d+)", re.ASCII)
_GLIBC_FLOOR = {"linux-x64": (2, 34), "linux-arm64": (2, 39)}  # the gnu build refuses to install below these [V]
_HOST_LIBC = object()


def _read_libc() -> str | None:
    """`glibc 2.39` on a glibc system; None when there is none (a musl system, or `os.confstr` cannot say)."""
    try:
        return os.confstr("CS_GNU_LIBC_VERSION")
    except (ValueError, OSError):
        return None


def kiro_platform(platform: str, libc: object = _HOST_LIBC) -> str:
    """The key into `KIRO_SHA256` for `platform`: `linux-x64` or `linux-arm64` when the glibc version (`libc`, as
    `os.confstr` words it; read from the host when omitted) is at least the vendor's floor for that architecture,
    else the `-musl` key, which is also what no glibc gives (D3). `ValueError` off Linux (D4)."""
    if platform not in _GLIBC_FLOOR:
        raise ValueError(f"no Kiro CLI archive for platform {platform!r}")
    text = _read_libc() if libc is _HOST_LIBC else libc
    found = _GLIBC.search(text) if isinstance(text, str) else None
    if found is not None and (int(found.group(1)), int(found.group(2))) >= _GLIBC_FLOOR[platform]:
        return platform
    return f"{platform}-musl"


def kiro_digest(version: str, kiro_key: str) -> str | None:
    """The sha256 the harness holds for `version`'s archive of that platform key, or None."""
    return KIRO_SHA256.get(version, {}).get(kiro_key)


def kiro_unheld_text(version: str, source: str) -> str:
    """Why a Kiro version outside `KIRO_SHA256` is never installed by the harness (L4-PRV-045, D9)."""
    held = ", ".join(sorted(KIRO_SHA256, key=lambda v: parse_version(v) or (0, 0, 0)))
    return (
        f"kiro-cli {version} ({source}) has no sha256 in this harness (it holds {held}): install it yourself and "
        "keep it, or hold one of those"
    )


def kiro_archive_url(version: str, kiro_key: str) -> str:
    arch = "x86_64" if kiro_key.startswith("linux-x64") else "aarch64"
    musl = "-musl" if kiro_key.endswith("-musl") else ""
    return f"{KIRO_DOWNLOAD}/{version}/kirocli-{arch}-linux{musl}.zip"


@dataclass(frozen=True)
class ToolSpec:
    name: str  # the tool's own name: uv, node, openspec, claude, codex, opencode, kiro-cli
    kind: Literal["uv", "node", "openspec", "agent", "laya"]
    binary: str
    version: str | None  # the pinned version that gets installed; None: installed as released
    min_version: str | None  # a present tool at least this new is left alone
    adapter: str | None = None  # agents: the adapter whose profiles need it
    pin_source: str = "catalog"  # agents: "ci.cli_versions" when `version` is the repository's override (L4-PRV-045)


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


def laya_in_use(cfg: L4Config) -> bool:
    """A `laya-local` profile is in `roles.s1_judge` or `verifier.s1.shadow` (L4-ADO-019)."""
    for name in (*cfg.roles.s1_judge, *cfg.verifier.s1.shadow):
        profile = cfg.profiles.get(name)
        if profile is not None and profile.backend == "system-one" and profile.engine == "laya-local":
            return True
    return False


def required_tools(cfg: L4Config, *, openspec_active: bool) -> list[ToolSpec]:
    """uv always; Node and OpenSpec when OpenSpec is active (Node also when an npm-installed agent is needed); an agent
    CLI only when a profile of its adapter is in some role chain; Laya (with its checkpoint) only when a `laya-local`
    profile is in a System One list."""
    agents = adapters_in_use(cfg)
    pins = effective_pins(cfg)
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
                ADAPTER_BINARIES[adapter], "agent", ADAPTER_BINARIES[adapter], pins[adapter][0],
                max(minimums, key=lambda v: parse_version(v) or (0, 0, 0)) if minimums else None, adapter,
                pins[adapter][1],
            )
        )  # fmt: skip
    if laya_in_use(cfg):
        tools.append(ToolSpec("laya", "laya", "laya-serve", LAYA_VERSION, None))
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
    if tool.kind == "laya":
        return (
            f"UV_TOOL_DIR={l4_home}/laya UV_TOOL_BIN_DIR={l4_home}/laya/bin uv tool install --torch-backend cpu "
            f"'laya[serve]=={tool.version}', link laya-serve into ~/.local/bin, then fetch the {LAYA_CHECKPOINT} "
            f"checkpoint of {LAYA_REPO} with huggingface_hub (HF_HOME=~/.cache/l4/laya/hf)"
        )
    assert tool.adapter is not None
    if tool.adapter in NPM_PACKAGES:
        return f"npm install --prefix {l4_home}/npm --save-exact {NPM_PACKAGES[tool.adapter]}{pin}"
    if tool.adapter == "kiro-cli":
        return _kiro_manual_command(tool.version or KIRO_VERSION, platform)
    version_arg = f" -s {tool.version}" if tool.version else ""
    return f"curl -fsSL {INSTALLER_URLS[tool.adapter]} | bash{version_arg}"


def _kiro_manual_command(version: str, platform: str) -> str:
    try:
        key = kiro_platform(platform)
    except ValueError:
        dmg = f"{KIRO_DOWNLOAD}/{version}/Kiro%20CLI.dmg"
        digest = KIRO_DMG_SHA256.get(version)
        check = (
            f"check it with shasum -a 256 ({digest})" if digest else "check it against the vendor's published sha256"
        )
        return (
            f"download {dmg}, {check}, open it and copy Kiro CLI.app to /Applications "
            "(this replaces an installed Kiro CLI)"
        )
    digest = KIRO_SHA256.get(version, {}).get(key)
    if digest is None:
        return f"install kiro-cli {version} yourself from {kiro_archive_url(version, key)} and keep it"
    archive = kiro_archive_url(version, key).rsplit("/", 1)[1]
    installs = " && ".join(f"install -m 755 kiro/{member} ~/.local/bin/" for member in KIRO_MEMBERS)
    return (
        f'curl -fsSL -o {archive} {kiro_archive_url(version, key)} && echo "{digest}  {archive}" | sha256sum -c - '
        f"&& unzip -q {archive} -d kiro && mkdir -p ~/.local/bin && {installs}"
    )
