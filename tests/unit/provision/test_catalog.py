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
        r"^([A-Z]+)_(VERSION|MIN)=\$\{[A-Z_]+:-([0-9][0-9.]*)\}", PREREQS.read_text(), re.MULTILINE
    )}  # fmt: skip
    assert pins["UV_VERSION"] == catalog.UV_VERSION
    assert pins["NODE_VERSION"] == catalog.NODE_VERSION
    assert pins["NODE_MIN"] == catalog.NODE_MIN
    assert pins["OPENSPEC_VERSION"] == catalog.OPENSPEC_DEFAULT
    assert pins["CLAUDE_VERSION"] == catalog.CLAUDE_VERSION
    assert pins["CODEX_VERSION"] == catalog.CODEX_VERSION
    assert pins["OPENCODE_VERSION"] == catalog.OPENCODE_VERSION


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
    assert catalog.SUPPORTED_MAJORS == {"opencode": 1, "kiro-cli": 2}
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
        "(l4 doctor --fix installs it user-locally); OpenCode 2 support comes in a later L4 release"
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
