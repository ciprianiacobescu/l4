from pathlib import Path

import pytest

from l4.config.schema import CacheCfg, SandboxCfg
from l4.sandbox.base import CacheMount
from l4.sandbox.caches import mount_caches


def test_default_caches_expand_cache_root_and_unit_and_are_created(tmp_path: Path):
    mounts = mount_caches(SandboxCfg().caches, tmp_path / "cache", "openspec:add-x")
    by_env = {m.env: m for m in mounts}
    uv = by_env["UV_CACHE_DIR"]
    assert uv == CacheMount(tmp_path / "cache" / "units" / "openspec" / "add-x" / "cache" / "uv", "UV_CACHE_DIR", False)
    assert uv.path.is_dir()  # bwrap refuses to bind a source that does not exist


def test_a_read_only_cache_that_does_not_exist_is_skipped(tmp_path: Path):
    mounts = mount_caches(SandboxCfg().caches, tmp_path / "cache", "openspec:add-x")
    assert "PLAYWRIGHT_BROWSERS_PATH" not in {m.env for m in mounts}
    shared = tmp_path / "cache" / "shared" / "ms-playwright"
    shared.mkdir(parents=True)
    again = mount_caches(SandboxCfg().caches, tmp_path / "cache", "openspec:add-x")
    assert CacheMount(shared, "PLAYWRIGHT_BROWSERS_PATH", True) in again


def test_a_path_outside_the_cache_root_is_refused(tmp_path: Path):
    caches = {"evil": CacheCfg(path="/etc", env="X_CACHE")}
    with pytest.raises(ValueError, match="inside the runner cache"):
        mount_caches(caches, tmp_path / "cache", "openspec:add-x")


def test_a_unit_that_is_not_a_unit_id_is_refused(tmp_path: Path):
    with pytest.raises(ValueError):
        mount_caches(SandboxCfg().caches, tmp_path / "cache", "../../etc")
