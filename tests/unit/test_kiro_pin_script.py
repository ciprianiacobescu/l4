"""scripts/dev/kiro_pin.py prints the catalog row and the prereqs.sh lines for a Kiro version (design D11)."""

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "dev" / "kiro_pin.py"

DIGESTS = {
    "kirocli-x86_64-linux.zip": "a" * 64,
    "kirocli-aarch64-linux.zip": "b" * 64,
    "kirocli-x86_64-linux-musl.zip": "c" * 64,
    "kirocli-aarch64-linux-musl.zip": "d" * 64,
}


def package(version: str, name: str, digest: str) -> dict:
    return {"fileType": "zip", "download": f"{version}/{name}", "sha256": digest, "size": 10, "channel": "stable"}


@pytest.fixture
def index(tmp_path: Path) -> Path:
    full = [package("2.40.0", name, digest) for name, digest in DIGESTS.items()]
    full.append({"fileType": "dmg", "download": "2.40.0/Kiro CLI.dmg", "sha256": "e" * 64, "size": 10})
    full.append({"fileType": "tarGz", "download": "2.40.0/kirocli-x86_64-linux.tar.gz", "sha256": "f" * 64, "size": 1})
    gnu_only = [package("2.39.0", n, d) for n, d in DIGESTS.items() if "musl" not in n]
    path = tmp_path / "index.json"
    path.write_text(json.dumps({"supported": [], "versions": [
        {"version": "2.40.0", "packages": full}, {"version": "2.39.0", "packages": gnu_only},
    ]}))  # fmt: skip
    return path


@pytest.fixture
def script():
    spec = importlib.util.spec_from_file_location("kiro_pin", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_prints_the_row_and_the_prereqs_lines(script, index, capsys):
    assert script.main(["2.40.0", "--index", str(index)]) == 0
    out = capsys.readouterr().out
    assert '"2.40.0": {' in out
    assert f'"linux-x64": "{"a" * 64}"' in out and f'"linux-arm64": "{"b" * 64}"' in out
    assert f'"linux-x64-musl": "{"c" * 64}"' in out and f'"linux-arm64-musl": "{"d" * 64}"' in out
    assert f'"2.40.0": "{"e" * 64}"' in out  # the disk image entry
    assert "KIRO_VERSION=${KIRO_VERSION:-2.40.0}" in out
    assert f"KIRO_SHA256_X86_64=${{KIRO_SHA256_X86_64:-{'a' * 64}}}" in out
    assert f"KIRO_SHA256_AARCH64_MUSL=${{KIRO_SHA256_AARCH64_MUSL:-{'d' * 64}}}" in out


def test_a_missing_zip_exits_1(script, index, capsys):
    assert script.main(["2.39.0", "--index", str(index)]) == 1
    err = capsys.readouterr().err
    assert "kirocli-x86_64-linux-musl.zip" in err and "kirocli-aarch64-linux-musl.zip" in err


def test_an_unknown_version_exits_1(script, index, capsys):
    assert script.main(["9.9.9", "--index", str(index)]) == 1
    assert "9.9.9" in capsys.readouterr().err
