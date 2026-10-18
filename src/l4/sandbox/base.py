"""Sandbox types (SPEC L4-SEC-005). One `Sandbox.wrap` is the choke point every agent and gate spawn goes through."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from l4.config.defaults import CREDENTIAL_PATHS
from l4.exitcodes import ExitCode, L4Exit

SandboxKind = Literal["agent", "gate"]


class SandboxUnavailable(L4Exit):
    """No usable sandbox: fail closed, exit 3 before any agent or gate runs."""

    def __init__(self, message: str) -> None:
        super().__init__(ExitCode.DOCTOR_FAILED, message)


@dataclass(frozen=True)
class CacheMount:
    path: Path
    env: str
    read_only: bool = False


@dataclass(frozen=True)
class SandboxSpec:
    """What one spawn may see. `credential_paths` maps every adapter to its (absolute) login paths; an agent sandbox
    binds read-write only those of `adapter`, and every other adapter's are hidden. A gate sandbox has no adapter."""

    kind: SandboxKind
    worktree: Path
    git_common_dir: Path
    tmp_dir: Path  # private, writable; holds the result file (L4_RESULT_PATH) and TMPDIR
    home: Path
    credential_paths: Mapping[str, tuple[Path, ...]] = field(default_factory=dict)
    adapter: str | None = None
    caches: tuple[CacheMount, ...] = ()
    network: bool = True
    runner_tmp: tuple[Path, ...] = ()  # the CI runner's own scratch dirs (job-token git config, CA file): hidden
    record_dir: Path | None = None  # writable, apart from TMPDIR: holds the gate's outcome record (a random file name)

    def __post_init__(self) -> None:
        if (self.kind == "agent") != (self.adapter is not None):
            raise ValueError("an agent sandbox names its adapter; a gate sandbox has none")


@dataclass(frozen=True)
class WrappedCommand:
    argv: list[str]
    env: dict[str, str]


@dataclass(frozen=True)
class Availability:
    ok: bool
    reason: str = ""


class Sandbox(Protocol):
    name: str

    def available(self) -> Availability: ...

    def wrap(
        self, argv: Sequence[str], spec: SandboxSpec, env: Mapping[str, str], cwd: Path | None = None
    ) -> WrappedCommand: ...


def expand_credential_paths(configured: Mapping[str, Sequence[str]], home: Path) -> dict[str, tuple[Path, ...]]:
    """`sandbox.credential_paths` with `~` resolved against `home`. Relative paths are a config error: they would
    resolve against whatever directory bwrap runs in."""
    out: dict[str, tuple[Path, ...]] = {}
    for adapter, paths in configured.items():
        expanded = []
        for raw in paths:
            path = home / raw[2:] if raw.startswith("~/") else Path(raw)
            if not path.is_absolute():
                raise ValueError(f"sandbox.credential_paths.{adapter}: {raw!r} must start with ~/ or be absolute")
            expanded.append(path)
        out[adapter] = tuple(expanded)
    return out


def runner_tmp_paths(environ: Mapping[str, str]) -> tuple[Path, ...]:
    """gitlab-runner keeps `.gitlab-runner.ext.conf` (the job token in an `insteadOf` rule, included from the
    checkout's `.git/config`) and the CA file in `<CI_PROJECT_DIR>.tmp`, which `--ro-bind / /` would leave readable
    to agents and gates. That is also the `*.tmp` of this project beside the others under `CI_BUILDS_DIR`: one path.
    On GitHub `$RUNNER_TEMP` holds the harness's deploy key (L4-GHP-010) and the runner's file-command files."""
    paths: list[Path] = []
    project_dir = environ.get("CI_PROJECT_DIR", "")
    if project_dir.startswith("/"):
        paths.append(Path(f"{project_dir.rstrip('/')}.tmp"))
    runner_temp = environ.get("RUNNER_TEMP", "")
    if runner_temp.startswith("/") and runner_temp.rstrip("/"):  # relative: whatever bwrap's cwd is; "/": everything
        paths.append(Path(runner_temp.rstrip("/")))
    return tuple(dict.fromkeys(paths))


def hidden_credential_paths(spec: SandboxSpec) -> list[Path]:
    """Every login this spawn must not see: the built-in defaults and the configured paths of every adapter but its
    own, so that a user override of one adapter's path (what is mounted for it) never un-hides the default from the
    others (L4-SEC-005)."""
    builtin = expand_credential_paths({name: list(paths) for name, paths in CREDENTIAL_PATHS.items()}, spec.home)
    hidden: list[Path] = []
    for adapter in dict.fromkeys([*spec.credential_paths, *builtin]):
        if adapter == spec.adapter:
            continue
        for path in (*spec.credential_paths.get(adapter, ()), *builtin.get(adapter, ())):
            if path not in hidden:
                hidden.append(path)
    return hidden


# Where the CLIs read repository guidance (skills, commands, agents, steering, plugin config) from a directory (HB-X1):
# no switch of Codex removes `.agents/skills` and `.codex/skills`, and a CLI update can add a root. Every one is a
# contract-protected path (L4-SEC-004), so an agent step has no use for it. `.kiro` holds the spec root
# (`.kiro/specs/**`), which the step reads: only the Kiro CLI's own guidance directories are listed. `.serena`
# is not here: Serena's project config and memories are read by the MCP server.
GUIDANCE_DIRS = (
    ".claude", ".agents", ".codex", ".opencode", ".hermes",
    ".kiro/steering", ".kiro/agents", ".kiro/settings", ".kiro/hooks", ".kiro/prompts",
)  # fmt: skip


def repo_guidance_masks(worktree: Path) -> list[Path]:
    """The directories of `GUIDANCE_DIRS` that exist in `worktree`, to be covered by a tmpfs inside the sandbox. A
    missing one is skipped (under a read-only root bwrap cannot create the mount point, and it would create the
    directory in the real worktree), and so is a symlink: bwrap resolves a destination, so `.claude -> /etc` would
    put a tmpfs over `/etc`. Mirrored in `m0_guidance` of scripts/runner/sandbox-probe.sh."""
    return [path for rel in GUIDANCE_DIRS if (path := worktree / rel).is_dir() and not path.is_symlink()]


def gate_sandbox_spec(
    *,
    worktree: Path,
    git_common_dir: Path,
    tmp_dir: Path,
    home: Path,
    configured_credential_paths: Mapping[str, Sequence[str]],
    caches: tuple[CacheMount, ...],
    network: bool,
    runner_tmp: tuple[Path, ...] = (),
    record_dir: Path | None = None,
) -> SandboxSpec:
    """The one way to build a gate sandbox: no adapter, so every adapter's login is hidden. A spec without
    `credential_paths` hides nothing, which is how a gate could read `~/.codex`. `configured_credential_paths` is
    `cfg.sandbox.credential_paths`; `caches` come from `l4.sandbox.caches.mount_caches`."""
    return SandboxSpec(
        "gate", worktree, git_common_dir, tmp_dir, home, expand_credential_paths(configured_credential_paths, home),
        caches=caches, network=network, runner_tmp=runner_tmp, record_dir=record_dir,
    )  # fmt: skip
