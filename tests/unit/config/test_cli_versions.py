"""ci.cli_versions (L4-PRV-045, design D9): SCN-PRV-126 and SCN-PRV-127 at load, and the effective pins."""

import subprocess
import sys

import pytest
from pydantic import ValidationError

from l4.config.loader import ConfigSchemaError, load_config
from l4.config.schema import L4Config
from l4.provision import catalog


def cfg(**versions: str) -> L4Config:
    return L4Config.model_validate({"ci": {"cli_versions": versions}})


def load_error(tmp_path, body: str) -> str:
    (tmp_path / ".l4").mkdir()
    (tmp_path / ".l4" / "config.yaml").write_text(f"version: 1\nci:\n  cli_versions: {body}\n")
    with pytest.raises(ConfigSchemaError) as exc:
        load_config(tmp_path)
    return str(exc.value)


def test_the_default_is_empty():
    assert L4Config().ci.cli_versions == {}
    assert L4Config().model_dump(mode="json")["ci"]["cli_versions"] == {}


def test_a_held_version_loads_and_dumps_back():
    held = cfg(**{"kiro-cli": "2.28.0", "codex": "0.150.0"})
    assert held.ci.cli_versions == {"kiro-cli": "2.28.0", "codex": "0.150.0"}
    assert L4Config.model_validate(held.model_dump(mode="json")).ci.cli_versions == held.ci.cli_versions


def test_an_unknown_adapter_is_a_load_error(tmp_path):  # SCN-PRV-127
    message = load_error(tmp_path, "{gemini: '1.0.0'}")
    assert "ci.cli_versions: unknown agent CLI gemini (one of claude-code, codex, kiro-cli, opencode)" in message
    with pytest.raises(ValidationError):
        cfg(gemini="1.0.0")


@pytest.mark.parametrize("value", ["latest", "2.28", "v2.28.0", "2.28.0-beta", "2.28.0\nx"])
def test_a_malformed_version_is_a_load_error(tmp_path, value):  # SCN-PRV-127
    with pytest.raises(ValidationError) as exc:
        cfg(codex=value)
    assert "ci.cli_versions: codex:" in str(exc.value) and "is not a version N.N.N" in str(exc.value)
    assert "ci.cli_versions: codex: latest is not a version N.N.N" in load_error(tmp_path, "{codex: latest}")


def test_an_override_never_crosses_the_major(tmp_path):  # SCN-PRV-126
    assert (
        "ci.cli_versions: kiro-cli: 3.0.0 is Kiro CLI 3; this harness runs Kiro CLI 2 (L4-OCG-001, L4-OCG-005); a "
        "major moves with an L4 release, not with configuration"
    ) in load_error(tmp_path, "{kiro-cli: '3.0.0'}")
    other = tmp_path / "other"
    other.mkdir()
    assert (
        "ci.cli_versions: opencode: 2.0.32 is OpenCode 2; this harness runs OpenCode 1 (L4-OCG-001, L4-OCG-005); a "
        "major moves with an L4 release, not with configuration"
    ) in load_error(other, "{opencode: '2.0.32'}")
    assert cfg(**{"kiro-cli": "2.31.1"}).ci.cli_versions == {"kiro-cli": "2.31.1"}  # same major, no digests: loads


def test_effective_pins_name_their_source():
    plain = catalog.effective_pins(None)
    assert plain["kiro-cli"] == ("2.32.0", "catalog") and plain["codex"] == (catalog.CODEX_VERSION, "catalog")
    assert set(plain) == set(catalog.ADAPTER_PINS)
    held = catalog.effective_pins(cfg(**{"kiro-cli": "2.28.0"}))
    assert held["kiro-cli"] == ("2.28.0", "ci.cli_versions")
    assert held["codex"] == (catalog.CODEX_VERSION, "catalog")
    assert catalog.effective_pins(L4Config())["claude-code"] == (catalog.CLAUDE_VERSION, "catalog")


def test_the_schema_imports_alone():
    done = subprocess.run([sys.executable, "-c", "import l4.config.schema"], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
