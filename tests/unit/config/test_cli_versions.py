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
    assert (
        "ci.cli_versions: unknown agent CLI gemini "
        "(one of claude-code, codex, copilot-cli, kiro-cli, opencode, opencode2)" in message
    )
    with pytest.raises(ValidationError):
        cfg(gemini="1.0.0")


@pytest.mark.parametrize("value", ["latest", "2.28", "v2.28.0", "2.28.0-beta", "2.28.0\nx"])
def test_a_malformed_version_is_a_load_error(tmp_path, value):  # SCN-PRV-127
    with pytest.raises(ValidationError) as exc:
        cfg(codex=value)
    assert "ci.cli_versions: codex:" in str(exc.value) and "is not a version N.N.N" in str(exc.value)
    assert "ci.cli_versions: codex: is not a version N.N.N" in load_error(tmp_path, "{codex: latest}")  # R2: no value


TOKEN = "ghp_" + "aB3dE5gH7jK9mN1pQ3sT5vW7yZ9bC1dE3fG5"  # 40 characters


@pytest.mark.parametrize("shape", ["value", "key"])
def test_a_token_is_never_echoed_by_a_load_error(tmp_path, shape):  # R2
    assert len(TOKEN) == 40
    with pytest.raises(ValidationError) as exc:
        cfg(**({"codex": TOKEN} if shape == "value" else {TOKEN: "1.0.0"}))
    raw = str(exc.value)
    assert TOKEN not in raw and TOKEN[:12] not in raw
    body = f"{{codex: {TOKEN}}}" if shape == "value" else f"{{{TOKEN}: '1.0.0'}}"
    message = load_error(tmp_path, body)
    assert TOKEN not in message and TOKEN[:12] not in message


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
    assert set(plain) == set(catalog.CLI_PINS) and plain["opencode2"] == (catalog.OPENCODE2_VERSION, "catalog")
    held = catalog.effective_pins(cfg(**{"kiro-cli": "2.28.0"}))
    assert held["kiro-cli"] == ("2.28.0", "ci.cli_versions")
    assert held["codex"] == (catalog.CODEX_VERSION, "catalog")
    assert catalog.effective_pins(L4Config())["claude-code"] == (catalog.CLAUDE_VERSION, "catalog")


def test_the_schema_imports_alone():
    done = subprocess.run([sys.executable, "-c", "import l4.config.schema"], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr


def test_a_copilot_override_never_crosses_the_major(tmp_path):  # L4-OCG-006
    assert (
        "ci.cli_versions: copilot-cli: 2.0.0 is Copilot CLI 2; this harness runs Copilot CLI 1 (L4-OCG-001, "
        "L4-OCG-006); a major moves with an L4 release, not with configuration"
    ) in load_error(tmp_path, "{copilot-cli: '2.0.0'}")
    assert cfg(**{"copilot-cli": "1.0.103"}).ci.cli_versions == {"copilot-cli": "1.0.103"}  # same major: loads


def test_opencode2_is_a_key_of_major_2_only(tmp_path):  # SCN-OCV-28
    held = cfg(opencode2="2.0.32")
    assert held.ci.cli_versions == {"opencode2": "2.0.32"}
    assert catalog.effective_pins(held)["opencode2"] == ("2.0.32", "ci.cli_versions")
    assert cfg(opencode2="2.0.33").ci.cli_versions == {"opencode2": "2.0.33"}  # same major: loads
    message = load_error(tmp_path, "{opencode2: '1.18.34'}")
    assert (
        "ci.cli_versions: opencode2: 1.18.34 is OpenCode 1; this harness runs OpenCode 2 (L4-OCG-001, L4-OCV-002); a "
        "major moves with an L4 release, not with configuration"
    ) in message
    other = tmp_path / "other"
    other.mkdir()
    assert "OpenCode 2; this harness runs OpenCode 1 (L4-OCG-001, L4-OCG-005)" in load_error(
        other, "{opencode: '2.0.32'}"
    )
