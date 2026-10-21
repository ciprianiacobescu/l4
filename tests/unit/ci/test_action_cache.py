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
    assert capsys.readouterr().out == catalog.catalog_hash() + "\n"  # no config: the pins alone


def write_config(repo: Path, chains: dict[str, list[str]], profiles: dict[str, dict]) -> None:
    (repo / ".l4").mkdir(exist_ok=True)
    (repo / ".l4/config.yaml").write_text(yaml.safe_dump({"profiles": profiles, "roles": chains}))


def key_of(repo: Path, capsys) -> str:
    capsys.readouterr()
    assert main(["ci", "cache-key", "clis", "--repo", str(repo)], environ={}) == 0
    return capsys.readouterr().out.strip()


def test_key_changes_when_a_profile_with_a_new_adapter_joins_a_role(tmp_path, capsys):
    """The cache restored as a hit without kiro-cli when kiro joined the config (a key of the pins alone)."""
    claude = {"claude": {"adapter": "claude-code", "model": "sonnet"}}
    kiro = {"kiro": {"adapter": "kiro-cli", "model": "auto"}}
    write_config(tmp_path, {"implementer": ["claude"]}, claude)
    before = key_of(tmp_path, capsys)
    write_config(tmp_path, {"implementer": ["claude", "kiro"]}, {**claude, **kiro})
    after = key_of(tmp_path, capsys)
    assert after != before and before != catalog.catalog_hash()
    write_config(tmp_path, {"implementer": ["claude"]}, {**claude, **kiro})  # defined but in no chain: not installed
    assert key_of(tmp_path, capsys) == before


def test_key_ignores_a_model_and_a_non_cli_field(tmp_path, capsys):
    base = {"claude": {"adapter": "claude-code", "model": "sonnet"}}
    write_config(tmp_path, {"implementer": ["claude"]}, base)
    before = key_of(tmp_path, capsys)
    write_config(tmp_path, {"implementer": ["claude"]}, {"claude": {"adapter": "claude-code", "model": "opus"}})
    assert key_of(tmp_path, capsys) == before
    (tmp_path / ".l4/config.yaml").write_text(
        (tmp_path / ".l4/config.yaml").read_text() + "forge:\n  base_branch: trunk\n"
    )
    assert key_of(tmp_path, capsys) == before


def test_key_does_not_depend_on_the_order_of_the_chains(tmp_path, capsys):
    both = {
        "a": {"adapter": "claude-code", "model": "sonnet"},
        "b": {"adapter": "codex", "model": "gpt"},
    }
    write_config(tmp_path, {"implementer": ["a", "b"]}, both)
    first = key_of(tmp_path, capsys)
    write_config(tmp_path, {"implementer": ["b", "a"]}, both)
    assert key_of(tmp_path, capsys) == first


def test_key_falls_back_to_the_catalog_for_an_unreadable_config(tmp_path, capsys):
    (tmp_path / ".l4").mkdir()
    (tmp_path / ".l4/config.yaml").write_text("roles: [not, a, mapping\n")
    assert key_of(tmp_path, capsys) == catalog.catalog_hash()


def test_the_action_runs_the_key_in_the_workspace():
    clikey = next(s for s in _steps() if s.get("id") == "clikey")
    assert clikey["working-directory"] == "${{ github.workspace }}"


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

    step = next(s for s in _steps() if s.get("id") == "clipaths")
    lines = step["run"].splitlines()
    start = lines.index("paths<<L4_CLI_PATHS") + 1
    paths = [p for p in lines[start : lines.index("L4_CLI_PATHS", start)] if not p.startswith("!")]
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


# --- the Laya cache (adoption-lessons 7.4, L4-ADO-019, design D9) ----------------------------------------------------

LAYA = {"laya": {"backend": "system-one", "engine": "laya-local"}}
RUNNER = {"RUNNER_OS": "Linux", "RUNNER_ARCH": "X64", "ImageOS": "ubuntu24"}


def laya_key(repo: Path, capsys, environ=RUNNER) -> str:
    capsys.readouterr()
    assert main(["ci", "cache-key", "laya", "--repo", str(repo)], environ=dict(environ)) == 0
    return capsys.readouterr().out.strip()


def test_the_laya_key_names_the_runner_the_pin_and_the_checkpoint(tmp_path, capsys):
    write_config(tmp_path, {"s1_judge": ["laya"]}, LAYA)
    expected = f"l4-laya-Linux-X64-ubuntu24-{catalog.LAYA_VERSION}-{catalog.LAYA_CHECKPOINT}"
    assert laya_key(tmp_path, capsys) == expected == "l4-laya-Linux-X64-ubuntu24-0.3.24-typed-decisions"
    (tmp_path / ".l4/config.yaml").write_text(
        yaml.safe_dump({"profiles": LAYA, "verifier": {"s1": {"shadow": ["laya"]}}})
    )
    assert laya_key(tmp_path, capsys) == expected  # the shadow list counts


def test_there_is_no_laya_key_without_a_laya_local_profile_in_a_system_one_list(tmp_path, capsys):
    """SCN-ADO-53: no config, a profile used nowhere, or another engine: nothing is printed."""
    assert laya_key(tmp_path, capsys) == ""
    write_config(tmp_path, {}, LAYA)
    assert laya_key(tmp_path, capsys) == ""
    jev = {"jev": {"backend": "system-one", "engine": "jev", "base_url": "https://api.typesafe.ai", "api_key_env": "K"}}
    write_config(tmp_path, {"s1_judge": ["jev"]}, jev)
    assert laya_key(tmp_path, capsys) == ""


def test_the_cli_cache_key_does_not_change_with_a_laya_profile(tmp_path, capsys):
    claude = {"claude": {"adapter": "claude-code", "model": "sonnet"}}
    write_config(tmp_path, {"implementer": ["claude"]}, claude)
    before = key_of(tmp_path, capsys)
    write_config(tmp_path, {"implementer": ["claude"], "s1_judge": ["laya"]}, {**claude, **LAYA})
    assert key_of(tmp_path, capsys) == before


def test_an_unknown_cache_still_exits_2(tmp_path, capsys):
    assert main(["ci", "cache-key", "nope", "--repo", str(tmp_path)], environ={}) == 2


def test_an_override_of_a_cli_in_use_changes_the_printed_key(tmp_path, capsys):  # SCN-PRV-125
    profiles = {"kiro": {"adapter": "kiro-cli", "model": "auto"}, "codex": {"adapter": "codex"}}
    write_config(tmp_path, {"implementer": ["kiro"]}, profiles)
    plain = key_of(tmp_path, capsys)
    (tmp_path / ".l4/config.yaml").write_text(
        yaml.safe_dump(
            {"profiles": profiles, "roles": {"implementer": ["kiro"]}, "ci": {"cli_versions": {"kiro-cli": "2.28.0"}}}
        )
    )
    assert key_of(tmp_path, capsys) != plain
    (tmp_path / ".l4/config.yaml").write_text(
        yaml.safe_dump(
            {"profiles": profiles, "roles": {"implementer": ["kiro"]}, "ci": {"cli_versions": {"codex": "0.150.0"}}}
        )
    )
    assert key_of(tmp_path, capsys) == plain  # codex is in no role chain
