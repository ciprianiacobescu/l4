from collections.abc import Callable
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
