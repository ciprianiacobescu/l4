import os
import shutil
import tempfile
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from l4.sandbox.base import CacheMount, SandboxSpec


@pytest.fixture
def make_spec(tmp_path: Path) -> Callable[..., SandboxSpec]:
    """A spec over real files under tmp_path: ~/.codex and ~/.opencode/share are directories, ~/.claude.json a file,
    ~/.claude is missing (a login that was never made)."""
    home = tmp_path / "home"
    (home / ".codex").mkdir(parents=True)
    (home / ".local" / "share" / "opencode").mkdir(parents=True)
    (home / ".claude.json").write_text("{}")
    for sub in ("work/wt", "main/.git", "res"):
        (tmp_path / sub).mkdir(parents=True)

    def make(kind: str = "agent", adapter: str | None = "codex", **over: object) -> SandboxSpec:
        adapter = over.pop("force_adapter", adapter if kind == "agent" else None)  # type: ignore[assignment]
        base: dict[str, object] = {
            "kind": kind,
            "worktree": tmp_path / "work" / "wt",
            "git_common_dir": tmp_path / "main" / ".git",
            "tmp_dir": tmp_path / "res",
            "home": home,
            "credential_paths": {
                "codex": (home / ".codex",),
                "claude-code": (home / ".claude", home / ".claude.json"),
                "opencode": (home / ".local" / "share" / "opencode",),
            },
            "adapter": adapter,
            "cache_root": tmp_path / "runner-cache",  # absent unless a test makes it: no tmpfs for it then
            "tool_paths": (),
        }
        return SandboxSpec(**{**base, **over})  # type: ignore[arg-type]

    make.cache = lambda name, read_only=False: CacheMount(tmp_path / "cache" / name, f"{name.upper()}_CACHE", read_only)  # type: ignore[attr-defined]
    return make


@pytest.fixture
def var_tmp_dir() -> Iterator[Path]:
    """A fresh directory under /var/tmp, removed afterwards; the test is skipped when /var/tmp is not writable."""
    if not (Path("/var/tmp").is_dir() and os.access(Path("/var/tmp"), os.W_OK)):
        pytest.skip("/var/tmp is not writable")
    path = Path(tempfile.mkdtemp(prefix="l4-live-", dir=Path("/var/tmp"))).resolve()
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
