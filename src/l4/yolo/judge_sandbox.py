"""The sandbox of a readiness judge outside CI (review-resolution design D5, section 8). Contract only: the body
comes in wave 1."""

from collections.abc import Mapping
from pathlib import Path

from l4.config.schema import L4Config
from l4.sandbox.base import Sandbox

TOOL_LESS_ADAPTERS = ("claude-code", "opencode", "fake")


def choose(cfg: L4Config, environ: Mapping[str, str], repo: Path, *, adapter: str, in_ci: bool) -> tuple[Sandbox, str]:
    """The sandbox and its label (`bwrap` or `none`); raises `SandboxUnavailable` for a refusal."""
    raise NotImplementedError
