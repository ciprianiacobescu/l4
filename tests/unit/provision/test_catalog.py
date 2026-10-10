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
