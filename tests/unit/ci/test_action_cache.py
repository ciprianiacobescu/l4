"""The two caches of the setup action (L4-ACT-002): the CLI cache key is a hash of the catalog's pins and never of
the harness; `l4 ci cache-key clis` prints it; `l4 ci render-setup` prints the runner setup script (L4-ACT-003)."""

import re
from pathlib import Path

import pytest
import yaml

from l4.ci import render
from l4.cli import main
from l4.provision import catalog

ACTION = Path(__file__).resolve().parents[3] / ".github" / "actions" / "l4" / "action.yml"


def _steps() -> list[dict]:
    return yaml.safe_load(ACTION.read_text(encoding="utf-8"))["runs"]["steps"]


def test_catalog_hash_is_stable_hex():
    """SCN-ACT-05: the same pins give the same key suffix on every call."""
    first = catalog.catalog_hash()
    assert first == catalog.catalog_hash()
    assert re.fullmatch(r"[0-9a-f]{16}", first)


@pytest.mark.parametrize(
    "name,value",
    [
        ("UV_VERSION", "9.9.9"),
        ("NODE_VERSION", "99.0.0"),
        ("OPENSPEC_DEFAULT", "9.9.9"),
    ],
)
def test_catalog_hash_changes_with_a_pinned_version(monkeypatch, name, value):
    """SCN-ACT-06: a changed pin is a new CLI cache."""
    before = catalog.catalog_hash()
    monkeypatch.setattr(catalog, name, value)
    assert catalog.catalog_hash() != before


def test_catalog_hash_changes_with_an_agent_pin(monkeypatch):
    before = catalog.catalog_hash()
    monkeypatch.setitem(catalog.ADAPTER_PINS, "codex", "0.0.1")
    assert catalog.catalog_hash() != before


def test_catalog_hash_does_not_depend_on_the_harness(monkeypatch):
    """SCN-ACT-06: neither the harness version nor a commit is an input."""
    before = catalog.catalog_hash()
    import l4

    monkeypatch.setattr(l4, "__version__", "99.99.99")
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    assert catalog.catalog_hash() == before


def test_cache_key_command_prints_the_suffix(capsys, tmp_path):
    assert main(["ci", "cache-key", "clis", "--repo", str(tmp_path)], environ={}) == 0
    assert capsys.readouterr().out == catalog.catalog_hash() + "\n"


def test_cache_key_rejects_an_unknown_cache(capsys, tmp_path):
    assert main(["ci", "cache-key", "harness", "--repo", str(tmp_path)], environ={}) == 2


def test_render_setup_command_prints_the_script(capsys, tmp_path):
    """SCN-ACT-07: the same text as render_setup(), with the catalog's uv pinned in."""
    assert main(["ci", "render-setup", "--repo", str(tmp_path)], environ={}) == 0
    out = capsys.readouterr().out
    assert out == render.render_setup()
    assert "@@UV_VERSION@@" not in out and catalog.UV_VERSION in out


def test_cli_cache_paths_are_the_hosted_tool_cache_minus_the_harness():
    """SCN-ACT-05: the CLI cache restores the paths `doctor --ci --fix` installs into, none of uv's harness dirs."""
    from l4.ci.github import CACHE_PATHS

    step = next(s for s in _steps() if s.get("id") == "clis")
    paths = [p.strip() for p in step["with"]["path"].splitlines() if p.strip()]
    assert paths
    assert set(paths) <= set(CACHE_PATHS)
    assert not [p for p in paths if "uv" in p]


def test_cli_key_is_built_from_the_catalog_hash_and_the_image_only():
    """SCN-ACT-06: no source, commit or hashFiles in the CLI key."""
    step = next(s for s in _steps() if s.get("id") == "clis")
    key = step["with"]["key"]
    assert "steps.clikey.outputs.key" in key
    clikey = next(s for s in _steps() if s.get("id") == "clikey")
    script = clikey["run"]
    assert "l4-clis-$RUNNER_OS-$RUNNER_ARCH-${ImageOS:-image}-" in script
    assert "ci cache-key clis" in script
    for forbidden in ("commit", "COMMIT", "mode", "MODE", "hashFiles"):
        assert forbidden not in script


def test_harness_key_shape():
    """SCN-ACT-05: l4-harness-<os>-<arch>-<image>-py<python>-<source>-<hash>."""
    src = next(s for s in _steps() if s.get("id") == "src")["run"]
    assert 'echo "key=l4-harness-$RUNNER_OS-$RUNNER_ARCH-${ImageOS:-image}-py$INPUT_PYTHON-$mode-$key"' in src


def test_clis_none_skips_the_cli_cache():
    for step_id in ("clikey", "clis"):
        step = next(s for s in _steps() if s.get("id") == step_id)
        assert "inputs.clis" in step["if"] and "none" in step["if"]
