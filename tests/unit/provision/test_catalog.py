import re
from pathlib import Path

import pytest

from l4.provision import catalog
from l4.provision.catalog import (
    PLATFORMS,
    node_sha256,
    node_shasums_url,
    node_tarball_url,
    parse_shasums,
)

from .conftest import FIXTURES

PREREQS = Path(__file__).resolve().parents[3] / "scripts" / "runner" / "prereqs.sh"


def test_catalog_pins_equal_the_defaults_in_prereqs_sh():
    # contract C20: the pins stay in the top block as NAME_VERSION=${NAME_VERSION:-x.y.z}
    pins = {f"{name}_{kind}": value for name, kind, value in re.findall(
        r"^([A-Z0-9]+)_(VERSION|MIN)=\$\{[A-Z0-9_]+:-([0-9][0-9.]*)\}", PREREQS.read_text(), re.MULTILINE
    )}  # fmt: skip
    assert pins["UV_VERSION"] == catalog.UV_VERSION
    assert pins["NODE_VERSION"] == catalog.NODE_VERSION
    assert pins["NODE_MIN"] == catalog.NODE_MIN
    assert pins["OPENSPEC_VERSION"] == catalog.OPENSPEC_DEFAULT
    assert pins["CLAUDE_VERSION"] == catalog.CLAUDE_VERSION
    assert pins["CODEX_VERSION"] == catalog.CODEX_VERSION
    assert pins["OPENCODE_VERSION"] == catalog.OPENCODE_VERSION
    assert pins["OPENCODE2_VERSION"] == catalog.OPENCODE2_VERSION
    assert pins["COPILOT_VERSION"] == catalog.COPILOT_VERSION
    assert pins["KIRO_VERSION"] == catalog.KIRO_VERSION


def test_shasums_lists_pinned_tarballs():
    text = (FIXTURES / "SHASUMS256.txt").read_text()
    sums = parse_shasums(text)
    for platform in PLATFORMS:
        digest = node_sha256(text, catalog.NODE_VERSION, platform)
        assert re.fullmatch(r"[0-9a-f]{64}", digest)
        assert sums[f"node-v{catalog.NODE_VERSION}-{platform}.tar.xz"] == digest
    # recorded 2026-10-04 from https://nodejs.org/dist/v22.23.0/SHASUMS256.txt
    assert (
        node_sha256(text, "22.23.0", "linux-x64") == "14d7de44f235534799f8b171a4050d9a6a4bc99c87e053a25d3d54afa580aa20"
    )


def test_urls_and_unknown_platform():
    assert node_tarball_url("22.23.0", "linux-x64") == "https://nodejs.org/dist/v22.23.0/node-v22.23.0-linux-x64.tar.xz"
    assert node_shasums_url("22.23.0") == "https://nodejs.org/dist/v22.23.0/SHASUMS256.txt"
    with pytest.raises(ValueError):
        node_tarball_url("22.23.0", "windows-x64")
    with pytest.raises(ValueError, match="does not list"):
        node_sha256("", "22.23.0", "linux-x64")


def test_parse_shasums_ignores_junk_lines():
    good = "a" * 64
    assert parse_shasums(f"{good}  file.tar.xz\nnot a line\n{'g' * 64}  bad\n{good} *star.tar\n") == {
        "file.tar.xz": good,
        "star.tar": good,
    }


# --- Kiro: the pin, the archive and its digests (L4-PRV-042) ---

KIRO_2_32_0 = {
    "linux-x64": "7cea2c90198edc60ccaee9e0d9c9de26902b3824f54a66aa3639a365f7242fbb",
    "linux-arm64": "f66faaa3fa202e7730979e10ad907c43f83220577609c97fdffbb07fc8ef1848",
    "linux-x64-musl": "f12968c2b154cd17f4d1d68b563f3dfba2135065c5c6552f19cceddd60258485",
    "linux-arm64-musl": "219a047427ca2b43681f4788104df5e784eda030d98abeec1c732aac9090eb8b",
}
DMG_2_32_0 = "88721f97dbe98c9e4f84a46e8a2584a8dd29289b81264d96ee2987dd2c014e3c"


def test_kiro_is_pinned_and_in_catalog_pins():  # SCN-PRV-118
    assert catalog.ADAPTER_PINS["kiro-cli"] == "2.32.0"
    assert catalog.catalog_pins()["agent:kiro-cli"] == "2.32.0"
    assert "kiro-cli" not in catalog.INSTALLER_URLS


def test_catalog_hash_moves_with_the_kiro_pin(monkeypatch):  # SCN-PRV-118
    before = catalog.catalog_hash()
    monkeypatch.setattr(catalog, "KIRO_VERSION", "2.28.0")
    monkeypatch.setitem(catalog.ADAPTER_PINS, "kiro-cli", "2.28.0")
    assert catalog.catalog_pins()["agent:kiro-cli"] == "2.28.0"
    assert catalog.catalog_hash() != before


def test_the_kiro_digest_table():
    assert set(catalog.KIRO_SHA256) >= {"2.32.0", "2.28.0", "2.27.1"}
    for version, row in catalog.KIRO_SHA256.items():
        assert set(row) == {"linux-x64", "linux-arm64", "linux-x64-musl", "linux-arm64-musl"}, version
        assert all(re.fullmatch(r"[0-9a-f]{64}", digest) for digest in row.values()), version
    assert catalog.KIRO_SHA256["2.32.0"] == KIRO_2_32_0
    assert catalog.KIRO_VERSION in catalog.KIRO_SHA256
    assert catalog.KIRO_DMG_SHA256["2.32.0"] == DMG_2_32_0


def test_kiro_archive_url():
    base = "https://prod.download.cli.kiro.dev/stable/2.32.0"
    assert catalog.kiro_archive_url("2.32.0", "linux-x64") == f"{base}/kirocli-x86_64-linux.zip"
    assert catalog.kiro_archive_url("2.32.0", "linux-arm64-musl") == f"{base}/kirocli-aarch64-linux-musl.zip"
    assert catalog.kiro_archive_url("2.32.0", "linux-x64-musl") == f"{base}/kirocli-x86_64-linux-musl.zip"
    assert catalog.kiro_archive_url("2.32.0", "linux-arm64") == f"{base}/kirocli-aarch64-linux.zip"
    assert "latest" not in Path(catalog.__file__).read_text()


def test_kiro_platform_follows_the_glibc():  # SCN-PRV-115
    assert catalog.kiro_platform("linux-arm64", "glibc 2.35") == "linux-arm64-musl"
    assert catalog.kiro_platform("linux-x64", "glibc 2.35") == "linux-x64"
    assert catalog.kiro_platform("linux-arm64", "glibc 2.39") == "linux-arm64"
    assert catalog.kiro_platform("linux-x64", "glibc 2.33") == "linux-x64-musl"
    assert catalog.kiro_platform("linux-x64", None) == "linux-x64-musl"
    assert catalog.kiro_platform("linux-arm64", None) == "linux-arm64-musl"
    assert catalog.kiro_platform("linux-x64", "musl") == "linux-x64-musl"


def test_kiro_platform_refuses_other_systems():
    with pytest.raises(ValueError):
        catalog.kiro_platform("darwin-arm64", "glibc 2.39")


def _kiro_tool(version="2.32.0"):
    return catalog.ToolSpec("kiro-cli", "agent", "kiro-cli", version, None, "kiro-cli")


def test_manual_command_for_kiro(monkeypatch):
    monkeypatch.setattr(catalog, "_read_libc", lambda: "glibc 2.35")
    text = catalog.manual_command(_kiro_tool(), "linux-x64", "/l4")
    assert "https://prod.download.cli.kiro.dev/stable/2.32.0/kirocli-x86_64-linux.zip" in text
    assert KIRO_2_32_0["linux-x64"] in text
    assert "sha256sum -c" in text and "unzip" in text
    assert text.count("install -m 755") == 3
    assert "cli.kiro.dev/install" not in text
    arm = catalog.manual_command(_kiro_tool(), "linux-arm64", "/l4")
    assert "kirocli-aarch64-linux-musl.zip" in arm and KIRO_2_32_0["linux-arm64-musl"] in arm
    mac = catalog.manual_command(_kiro_tool(), "darwin-arm64", "/l4")
    assert "https://prod.download.cli.kiro.dev/stable/2.32.0/Kiro%20CLI.dmg" in mac
    assert DMG_2_32_0 in mac and "install -m 755" not in mac


# --- the major gate's wording (L4-OCG-005, D8) ---

KIRO_3_PROBLEM = (
    "kiro-cli 3.0.0 is Kiro CLI 3; L4 runs Kiro CLI 2: install kiro-cli {pin} (in CI l4 doctor --ci --fix installs "
    "it; l4 doctor prints the command for this machine); Kiro CLI 3 support comes in a later L4 release"
)


def test_supported_majors_follow_the_pins():
    assert catalog.SUPPORTED_MAJORS == {"opencode": 1, "opencode2": 2, "kiro-cli": 2, "copilot-cli": 1}
    assert set(catalog.MAJOR_WORDS) == set(catalog.SUPPORTED_MAJORS)
    assert isinstance(catalog.MAJOR_WORDS["kiro-cli"], catalog.MajorWords)


def test_kiro_major_problem_names_the_cause_and_the_pin():  # SCN-OCG-11
    assert catalog.major_problem("kiro-cli", "kiro-cli", "kiro-cli 3.0.0", "2.32.0") == KIRO_3_PROBLEM.format(
        pin="2.32.0"
    )
    assert "install kiro-cli 2.28.0 (" in (
        catalog.major_problem("kiro-cli", "kiro-cli", "kiro-cli 3.0.0", "2.28.0") or ""
    )
    assert catalog.major_problem("kiro-cli", "kiro-cli", "kiro-cli 2.33.0", "2.32.0") is None
    assert catalog.major_problem("codex", "codex", "codex-cli 9.0.0", "0.160.0") is None


def test_the_opencode_texts_are_unchanged():  # L4-OCG-002
    assert catalog.major_problem("opencode", "opencode", "opencode v2.0.32", "1.18.34") == (
        "opencode 2.0.32 is OpenCode v2; this profile runs v1 (opencode-ai 1.x): install opencode-ai@1.18.34 "
        "(l4 doctor --fix installs it user-locally) or set options.cli_major: 2 to run OpenCode 2 (experimental)"
    )
    words = catalog.MAJOR_WORDS["opencode"]
    assert words.product == "OpenCode"
    # the plan_fixes reason, the _verified text and the fail-closed text of today, built from the table
    assert (
        f"found 2.0.32 ({words.major_name.format(major=2)}), need {words.need.format(supported=1)} (pinned 1.18.34)"
        == "found 2.0.32 (OpenCode v2), need opencode-ai 1.x (pinned 1.18.34)"
    )
    assert (
        f"opencode at /p reports 2.0.32 ({words.major_name.format(major=2)}) after the install, "
        f"need {words.need.format(supported=1)} (pinned 1.18.34)"
        == "opencode at /p reports 2.0.32 (OpenCode v2) after the install, need opencode-ai 1.x (pinned 1.18.34)"
    )
    assert (
        f"opencode reports no version, so its {words.product} major cannot be checked"
        == "opencode reports no version, so its OpenCode major cannot be checked"
    )
    kiro = catalog.MAJOR_WORDS["kiro-cli"]
    assert f"found 3.0.0 ({kiro.major_name.format(major=3)}), need {kiro.need.format(supported=2)} (pinned 2.32.0)" == (
        "found 3.0.0 (Kiro CLI 3), need kiro-cli 2.x (pinned 2.32.0)"
    )


# --- the cache key moves with an override of a CLI in use (L4-PRV-045, SCN-PRV-125) ---


def _cfg(**versions):
    from l4.config.schema import L4Config

    return L4Config.model_validate(
        {
            "profiles": {"k": {"adapter": "kiro-cli"}, "c": {"adapter": "claude-code"}},
            "roles": {"implementer": ["k"]},
            "ci": {"cli_versions": versions},
        }
    )


def test_an_override_of_a_cli_in_use_changes_the_key():
    assert catalog.clis_cache_hash(_cfg(**{"kiro-cli": "2.28.0"})) != catalog.clis_cache_hash(_cfg())
    assert catalog.clis_cache_hash(_cfg(**{"kiro-cli": "2.28.0"})) != catalog.clis_cache_hash(
        _cfg(**{"kiro-cli": "2.27.1"})
    )


def test_an_override_of_an_unused_cli_keeps_the_key():
    assert catalog.clis_cache_hash(_cfg(codex="0.150.0")) == catalog.clis_cache_hash(_cfg())


def test_no_override_keeps_the_catalog_key():
    assert catalog.clis_cache_hash(_cfg()) == catalog.catalog_hash(["kiro-cli"])
    assert catalog.catalog_hash(["kiro-cli"], {}) == catalog.catalog_hash(["kiro-cli"])
    assert catalog.catalog_hash(["kiro-cli"], {"kiro-cli": "2.28.0"}) != catalog.catalog_hash(["kiro-cli"])


def test_kiro_pin_and_digests_equal_prereqs_sh():
    text = PREREQS.read_text()
    assert re.search(rf"^KIRO_VERSION=\$\{{KIRO_VERSION:-{re.escape(catalog.KIRO_VERSION)}\}}", text, re.MULTILINE)
    found = dict(re.findall(r"^(KIRO_SHA256_\w+)=\$\{\1:-([0-9a-f]{64})\}", text, re.MULTILINE))
    row = catalog.KIRO_SHA256[catalog.KIRO_VERSION]
    assert found == {
        "KIRO_SHA256_X86_64": row["linux-x64"],
        "KIRO_SHA256_AARCH64": row["linux-arm64"],
        "KIRO_SHA256_X86_64_MUSL": row["linux-x64-musl"],
        "KIRO_SHA256_AARCH64_MUSL": row["linux-arm64-musl"],
    }


# --- Copilot CLI: the pin, the archive and its digests (L4-PRV-047, L4-OCG-006) ---

COPILOT_1_0_102 = {
    "linux-x64": "cabbb04a88a8034ddfa21234cbd52b7676536aec2b292624e6fd6796f891a8ff",
    "linux-arm64": "634ee7cc4fa4b7447ac41e2c3ce54928d8f5214f418954e3af36f372e849c9c9",
    "linux-x64-musl": "7e6d64a86b287105415357d158b459bdaede840de797e03677213d5419a597c9",
    "linux-arm64-musl": "995c180500e741688c10e4e2368059ee2751fcc8812bdc58337e4ac920ef2971",
    "darwin-x64": "7a2af746ce5d11e2be486f06d85ce2fc620d5965413c8088fea8ceb2b1d9cb54",
    "darwin-arm64": "606f9539b88af1198523f671ffeeb6e58571ab71564252efbc3b2196f1ed3f2b",
}
COPILOT_BASE = "https://github.com/github/copilot-cli/releases/download/v1.0.102"


def test_copilot_is_pinned_and_in_catalog_pins():
    assert catalog.ADAPTER_PINS["copilot-cli"] == "1.0.102"
    assert catalog.ADAPTER_BINARIES["copilot-cli"] == "copilot"
    assert catalog.catalog_pins()["agent:copilot-cli"] == "1.0.102"
    assert catalog.COPILOT_VERSION == "1.0.102"
    assert "copilot-cli" not in catalog.INSTALLER_URLS


def test_the_copilot_digest_table():
    assert catalog.COPILOT_SHA256["1.0.102"] == COPILOT_1_0_102
    for version, row in catalog.COPILOT_SHA256.items():
        assert len(row) == 6, version
        assert all(re.fullmatch(r"[0-9a-f]{64}", digest) for digest in row.values()), version
    assert catalog.COPILOT_VERSION in catalog.COPILOT_SHA256
    assert catalog.copilot_digest("1.0.102", "darwin-arm64") == COPILOT_1_0_102["darwin-arm64"]
    assert catalog.copilot_digest("1.0.103", "linux-x64") is None
    assert catalog.copilot_digest("1.0.102", "linux-riscv") is None
    assert catalog.COPILOT_MEMBER == "copilot" and catalog.COPILOT_MEMBER_MAX == 512 * 1024 * 1024


def test_copilot_platform():  # SCN-PRV-131
    assert catalog.copilot_platform("linux-arm64", "glibc 2.39") == "linux-arm64"
    assert catalog.copilot_platform("linux-x64", "glibc 2.17") == "linux-x64"  # no threshold is guessed
    assert catalog.copilot_platform("linux-x64", None) == "linux-x64-musl"
    assert catalog.copilot_platform("linux-arm64", "musl") == "linux-arm64-musl"
    assert catalog.copilot_platform("darwin-arm64") == "darwin-arm64"
    assert catalog.copilot_platform("darwin-x64", None) == "darwin-x64"
    with pytest.raises(ValueError):
        catalog.copilot_platform("win32-x64")


def test_copilot_platform_reads_the_host_libc_only_when_none_is_given(monkeypatch):
    monkeypatch.setattr(catalog, "_read_libc", lambda: "glibc 2.35")
    assert catalog.copilot_platform("linux-x64") == "linux-x64"
    monkeypatch.setattr(catalog, "_read_libc", lambda: None)
    assert catalog.copilot_platform("linux-x64") == "linux-x64-musl"


def test_copilot_archive_url():
    assert catalog.copilot_archive_url("1.0.102", "linux-arm64") == f"{COPILOT_BASE}/copilot-linux-arm64.tar.gz"
    assert catalog.copilot_archive_url("1.0.102", "linux-x64-musl") == f"{COPILOT_BASE}/copilot-linuxmusl-x64.tar.gz"
    assert catalog.copilot_archive_url("1.0.102", "darwin-arm64") == f"{COPILOT_BASE}/copilot-darwin-arm64.tar.gz"
    assert (
        catalog.copilot_archive_url("1.0.102", "linux-arm64-musl") == f"{COPILOT_BASE}/copilot-linuxmusl-arm64.tar.gz"
    )


COPILOT_2_PROBLEM = (
    "copilot 2.0.0 is Copilot CLI 2; L4 runs Copilot CLI 1: install copilot 1.0.102 (in CI l4 doctor --ci --fix "
    "installs it; l4 doctor prints the command for this machine); Copilot CLI 2 support comes in a later L4 release"
)


def test_copilot_major_words():  # SCN-OCG-15
    assert catalog.SUPPORTED_MAJORS["copilot-cli"] == 1
    assert catalog.major_problem("copilot-cli", "copilot", "GitHub Copilot CLI 2.0.0.", "1.0.102") == COPILOT_2_PROBLEM
    assert catalog.major_problem("copilot-cli", "copilot", "GitHub Copilot CLI 1.0.103.\n", "1.0.102") is None
    assert catalog.major_problem("copilot-cli", "copilot", "GitHub Copilot CLI 1.0.102.", "1.0.102") is None
    assert catalog.major_plan_reason("copilot-cli", "2.0.0", 2, "1.0.102") == (
        "found 2.0.0 (Copilot CLI 2), need copilot 1.x (pinned 1.0.102)"
    )
    assert catalog.major_no_version_text("copilot-cli", "copilot") == (
        "copilot reports no version, so its Copilot CLI major cannot be checked"
    )
    assert catalog.major_config_error("copilot-cli", "copilot-cli", "2.0.0", 2) == (
        "ci.cli_versions: copilot-cli: 2.0.0 is Copilot CLI 2; this harness runs Copilot CLI 1 (L4-OCG-001, "
        "L4-OCG-006); a major moves with an L4 release, not with configuration"
    )
    # the OpenCode and Kiro texts are unchanged
    assert "(L4-OCG-001, L4-OCG-005)" in catalog.major_config_error("kiro-cli", "kiro-cli", "3.0.0", 3)
    assert "(L4-OCG-001, L4-OCG-005)" in catalog.major_config_error("opencode", "opencode", "2.0.0", 2)
    assert catalog.major_problem("kiro-cli", "kiro-cli", "kiro-cli 3.0.0", "2.32.0") == KIRO_3_PROBLEM.format(
        pin="2.32.0"
    )


def _copilot_tool(version="1.0.102"):
    return catalog.ToolSpec("copilot", "agent", "copilot", version, None, "copilot-cli")


def test_manual_command_for_copilot(monkeypatch):  # T24
    monkeypatch.setattr(catalog, "_read_libc", lambda: "glibc 2.39")
    text = catalog.manual_command(_copilot_tool(), "linux-x64", "/l4")
    assert text == (
        f"curl -fsSL -o copilot-linux-x64.tar.gz {COPILOT_BASE}/copilot-linux-x64.tar.gz && "
        f'echo "{COPILOT_1_0_102["linux-x64"]}  copilot-linux-x64.tar.gz" | sha256sum -c - && '
        "tar -xzf copilot-linux-x64.tar.gz copilot && mkdir -p ~/.local/bin && "
        "install -m 755 copilot ~/.local/bin/copilot && "
        "XDG_CACHE_HOME=/l4/copilot-cache COPILOT_AUTO_UPDATE=false ~/.local/bin/copilot --version"
    )
    mac = catalog.manual_command(_copilot_tool(), "darwin-arm64", "/l4")
    assert "shasum -a 256 -c -" in mac and "sha256sum" not in mac
    assert f"{COPILOT_BASE}/copilot-darwin-arm64.tar.gz" in mac and COPILOT_1_0_102["darwin-arm64"] in mac
    monkeypatch.setattr(catalog, "_read_libc", lambda: None)
    assert "copilot-linuxmusl-x64.tar.gz" in catalog.manual_command(_copilot_tool(), "linux-x64", "/l4")
    unheld = catalog.manual_command(_copilot_tool("1.0.103"), "linux-x64", "/l4")
    assert unheld == (
        "install copilot 1.0.103 yourself from "
        "https://github.com/github/copilot-cli/releases/download/v1.0.103/copilot-linuxmusl-x64.tar.gz and keep it"
    )


def test_archive_adapters():
    assert catalog.ARCHIVE_ADAPTERS == ("kiro-cli", "copilot-cli")
    assert catalog.copilot_unheld_text("1.0.103", "ci.cli_versions") == (
        "copilot 1.0.103 (ci.cli_versions) has no sha256 in this harness (it holds 1.0.102): install it yourself "
        "and keep it, or hold one of those"
    )


# --- OpenCode 2: its pin, its package and its cache key (L4-OCV-002, amendment E3) ---


def _v2_cfg(*, v1: bool = False, v2: bool = True, **versions):
    from l4.config.schema import L4Config

    profiles = {}
    if v1:
        profiles["oc1"] = {"adapter": "opencode", "model": "m", "vendor": "unknown"}
    if v2:
        profiles["oc2"] = {
            "adapter": "opencode", "model": "m", "vendor": "unknown", "options": {"cli_major": 2},
            "min_version": "2.0.30",
        }  # fmt: skip
    return L4Config.model_validate(
        {"profiles": profiles, "roles": {"implementer": list(profiles)}, "ci": {"cli_versions": versions}}
    )


def test_opencode2_is_pinned_and_in_catalog_pins():  # SCN-OCV-04
    assert catalog.OPENCODE2_VERSION == "2.0.32" and catalog.OPENCODE2_PACKAGE == "@opencode/cli"
    assert catalog.CLI_PINS == {**catalog.ADAPTER_PINS, "opencode2": "2.0.32"}
    pins = catalog.catalog_pins()
    assert pins["agent:opencode2"] == "2.0.32" and pins["npm:opencode2"] == "@opencode/cli"
    assert pins["agent:opencode"] == "1.18.34" and pins["npm:opencode"] == "opencode-ai"
    assert "opencode2" not in catalog.ADAPTER_PINS and "opencode2" not in catalog.NPM_PACKAGES  # keyed by adapter


def test_effective_pins_cover_opencode2_and_name_their_source():  # SCN-OCV-28
    assert catalog.effective_pins(None)["opencode2"] == ("2.0.32", "catalog")
    assert set(catalog.effective_pins(None)) == set(catalog.CLI_PINS)
    held = catalog.effective_pins(_v2_cfg(opencode2="2.0.33"))
    assert held["opencode2"] == ("2.0.33", "ci.cli_versions") and held["opencode"] == ("1.18.34", "catalog")
    assert catalog.gate_pin(_v2_cfg(opencode2="2.0.33"), "opencode2") == "2.0.33"  # one source of pins
    assert catalog.gate_pin(None, "opencode2") == "2.0.32"


def test_required_tools_follow_the_major_of_each_profile():  # SCN-OCV-04
    def tools(config):
        return {t.name: t for t in catalog.required_tools(config, openspec_active=False) if t.kind == "agent"}

    only_v1 = tools(_v2_cfg(v1=True, v2=False))
    assert list(only_v1) == ["opencode"] and only_v1["opencode"].version == "1.18.34"
    only_v2 = tools(_v2_cfg())
    assert list(only_v2) == ["opencode2"]
    v2 = only_v2["opencode2"]
    assert (v2.binary, v2.version, v2.min_version, v2.adapter, v2.pin_source) == (
        "opencode2", "2.0.32", "2.0.30", "opencode", "catalog",
    )  # fmt: skip
    assert v2.gate_key == "opencode2" and only_v1["opencode"].gate_key == "opencode"
    both = tools(_v2_cfg(v1=True))
    assert list(both) == ["opencode", "opencode2"]
    held = tools(_v2_cfg(opencode2="2.0.33"))["opencode2"]
    assert (held.version, held.pin_source) == ("2.0.33", "ci.cli_versions")
    names = [t.name for t in catalog.required_tools(_v2_cfg(), openspec_active=False)]
    assert "node" in names  # an npm-installed CLI: a v2-only configuration still gets Node


def test_adapters_in_use_keeps_the_adapter_and_clis_in_use_splits_the_majors():
    config = _v2_cfg(v1=True)
    assert catalog.adapters_in_use(config) == {"opencode": ["oc1", "oc2"]}
    assert catalog.clis_in_use(config) == {"opencode": ["oc1"], "opencode2": ["oc2"]}


def test_the_cache_key_follows_the_v2_profile():  # SCN-OCV-05
    without, with_v2 = catalog.clis_cache_hash(_v2_cfg(v1=True, v2=False)), catalog.clis_cache_hash(_v2_cfg(v1=True))
    assert without != with_v2
    assert with_v2 == catalog.catalog_hash(["opencode", "opencode2"])
    assert without == catalog.catalog_hash(["opencode"])
    assert catalog.clis_cache_hash(_v2_cfg(opencode2="2.0.33")) != catalog.clis_cache_hash(_v2_cfg())


def test_an_opencode2_override_is_in_the_key_only_with_a_v2_profile():
    held = _v2_cfg(v1=True, v2=False, opencode2="2.0.33")
    assert catalog.clis_cache_hash(held) == catalog.clis_cache_hash(_v2_cfg(v1=True, v2=False))


def test_opencode2_is_installed_by_hand_into_its_own_prefix():
    config = _v2_cfg()
    (tool,) = [t for t in catalog.required_tools(config, openspec_active=False) if t.name == "opencode2"]
    command = catalog.manual_command(tool, "linux-x64", "/home/u/.local/share/l4")
    assert "npm install --prefix /home/u/.local/share/l4/npm-opencode2 " in command
    assert command.count("@opencode/cli@2.0.32") == 1 and "opencode-ai" not in command
    assert "ln -sf /home/u/.local/share/l4/npm-opencode2/node_modules/.bin/opencode2 ~/.local/bin/opencode2" in command
    assert "--prefix /home/u/.local/share/l4/npm " not in command  # never the v1 prefix


def test_the_opencode2_config_error_names_both_requirements():  # SCN-OCV-28
    text = catalog.major_config_error("opencode2", "opencode2", "1.18.34", 1)
    assert text == (
        "ci.cli_versions: opencode2: 1.18.34 is OpenCode 1; this harness runs OpenCode 2 (L4-OCG-001, L4-OCV-002); a "
        "major moves with an L4 release, not with configuration"
    )
