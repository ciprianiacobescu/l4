"""ci.toolchains (L4-CI-005): SCN-CI-21 and the default caches gobuild and pnpm."""

import pytest
from pydantic import ValidationError

from l4.config.loader import ConfigSchemaError, load_config
from l4.config.schema import L4Config


def ci(**toolchains) -> L4Config:
    return L4Config.model_validate({"ci": {"toolchains": toolchains}})


def test_toolchains_default_to_none_and_dump_as_empty():
    cfg = L4Config()
    assert cfg.ci.toolchains.go is None and cfg.ci.toolchains.node is None and cfg.ci.toolchains.pnpm is None
    assert cfg.model_dump(mode="json")["ci"]["toolchains"] == {}


def test_go_node_and_pnpm_load_with_version_or_version_file():
    cfg = ci(go={"version_file": "go.work"}, node={"version": "22"}, pnpm={"version": "11"})
    assert cfg.ci.toolchains.go.version_file == "go.work" and cfg.ci.toolchains.go.version is None
    assert cfg.ci.toolchains.node.version == "22"
    assert cfg.ci.toolchains.pnpm.version == "11"
    assert ci(go={"version": "1.26"}, node={"version_file": ".nvmrc"}).ci.toolchains.node.version_file == ".nvmrc"
    again = L4Config.model_validate(cfg.model_dump(mode="json"))  # the dump loads back
    assert again.ci.toolchains == cfg.ci.toolchains


@pytest.mark.parametrize(
    "entry",
    [{}, {"version": "1.26", "version_file": "go.work"}],
    ids=["neither", "both"],
)
@pytest.mark.parametrize("tool", ["go", "node"])
def test_scn_ci_21_an_entry_needs_exactly_one_of_version_and_version_file(tool, entry):
    """SCN-CI-21 (-): refused with a message naming ci.toolchains.<tool>."""
    with pytest.raises(ValidationError) as exc:
        ci(**{tool: entry})
    assert f"ci.toolchains.{tool}" in str(exc.value)


def test_scn_ci_21_the_loader_names_the_key_not_the_value(tmp_path):
    """SCN-CI-21 (-): the load error is the ValueFree message."""
    (tmp_path / ".l4").mkdir()
    (tmp_path / ".l4" / "config.yaml").write_text(
        "version: 1\nci:\n  toolchains:\n    go: {version: '1.26', version_file: go.work}\n"
    )
    with pytest.raises(ConfigSchemaError) as exc:
        load_config(tmp_path)
    assert "ci.toolchains.go: give exactly one of version and version_file" in str(exc.value)


@pytest.mark.parametrize(
    "bad",
    [
        {"go": {"version": "1.26", "extra": 1}},
        {"pnpm": {}},
        {"pnpm": {"version_file": "x"}},
        {"ruby": {"version": "3"}},
        {"go": {"version_file": "../go.work"}},
        {"go": {"version_file": "/etc/go.work"}},
        {"node": {"version": "22\nrun: x"}},
    ],
)
def test_unknown_keys_and_unsafe_values_are_refused(bad):
    with pytest.raises(ValidationError):
        ci(**bad)


def test_default_caches_include_gobuild_and_pnpm():
    caches = L4Config().sandbox.caches
    assert caches["go"].env == "GOMODCACHE"
    assert caches["gobuild"].env == "GOCACHE" and caches["gobuild"].path.endswith("/cache/gobuild")
    assert caches["pnpm"].env == "pnpm_config_store_dir" and caches["pnpm"].path.endswith("/cache/pnpm")
    assert not caches["gobuild"].read_only and not caches["pnpm"].read_only
