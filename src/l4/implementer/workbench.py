"""Everything a TDD step needs from one unit's checkout: git in the worktree, the sandbox specs of agent and gate,
the gate runner, commits with trailers, and the ledger.

The harness stages with its own ignore file (`.venv/`, `.l4-out/`, caches): a repository whose `.gitignore` forgets
them must not get a virtual environment in a checkpoint commit.
"""

import hashlib
import logging
import os
import re
import secrets
import shutil
import threading
from collections.abc import Callable, Collection, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Literal

from l4.agents.base import AgentAdapter, McpServer
from l4.agents.credentials import CREDENTIAL_FILE
from l4.agents.factory import Selected
from l4.agents.opencode import CONFIG_DIR
from l4.agents.opencode_provider import KEY_FILE
from l4.agents.proc import ProcRunner
from l4.config.defaults import cache_root
from l4.config.schema import L4Config, duration_seconds
from l4.context import AppContext
from l4.deadline import DeadlineReached
from l4.fsutil import LinkedPath, UnsafeFile, atomic_write_bytes, linked_component, remove_link
from l4.gates.collection import MAX_COLLECTION_ERROR_CHARS, ledger_excerpt
from l4.gates.coverage import merge_pytest_env
from l4.gates.junit import TestReport
from l4.gates.outcomes import altered, read_record
from l4.gates.runner import GateResult, GateSpec, run_gate
from l4.gates.trace import trace_env
from l4.implementer import envguard
from l4.implementer.envguard import diff_manifest, remove_env_dir, take_manifest
from l4.implementer.gateconfig import restore_config, snapshot_config
from l4.implementer.guardnotes import GuardNote, note_of
from l4.memory.inject import branch_changed_files
from l4.memory.serena import SerenaStatus, check_serena, mcp_server_for, serena_context
from l4.redact import Redactor
from l4.safepath import resolve_tool
from l4.sandbox.base import (
    SCRATCH_DIR,
    CacheMount,
    Sandbox,
    SandboxSpec,
    expand_credential_paths,
    gate_sandbox_spec,
    readonly_with_scratch,
    remove_tree,
    runner_tmp_paths,
)
from l4.sandbox.caches import mount_caches
from l4.sandbox.env import toolchain_env
from l4.sandbox.envdirs import env_dirs, reset_tool_caches, tracked_env_paths
from l4.sandbox.home import spec_paths
from l4.security.protected import ProtectedSet, restore_protected, revert_unsnapshotted, snapshot_protected
from l4.specs.base import SpecProvider, UnitRef
from l4.state.ledger import ledger_path
from l4.vcs.errors import GitError
from l4.vcs.git import Git
from l4.vcs.names import unit_dir
from l4.vcs.repokey import key_of_common_dir
from l4.vcs.trailers import CommitTrailers
from l4.vcs.wip import restore_wip, snapshot_wip, wip_ref

log = logging.getLogger("l4.implementer")


def discard_tree(path: Path) -> None:
    """Remove a private tree at the end of a step or a gate: a failure is a warning, because the start of the next step
    removes the same tree again and raises when it still cannot (L4-SEC-039)."""
    try:
        remove_tree(path)
    except OSError as exc:
        log.warning("could not remove %s: %s", path, exc)


HARNESS_EXCLUDES = (
    ".venv/", ".l4-out/", ".pytest_cache/", ".ruff_cache/", ".mypy_cache/", "node_modules/", "__pycache__/", "*.pyc",
    ".coverage", ".serena/cache/", ".serena/project.local.yml",
    ".serena/.gitignore",  # Serena 1.7.0 writes it at every start, even when project.yml is committed
    ".l4-result",  # the result alias of a prompt-contract step (`resultalias`); no slash: a symlink, not a directory
)  # fmt: skip
MAX_REPORTED_PLANTS = envguard.MAX_REPORTED  # planted paths named in the ledger per rebuild; the rest is counted
MAX_SUBJECT_CHARS = 200
SKIP_CI = "[skip ci]"  # SPEC: a checkpoint commit MUST carry it, so the clip must never cut it off
LOG_TAIL_CHARS = 2000
MAX_GATE_LOG_NAME = 60  # characters of a gate's name kept in its log file name


SERENA_PROJECT = ".serena/project.yml"
# (run id, Serena context, worktree) -> the one `check_serena` of that run for that CLI in that unit's worktree (SPEC
# L4-MEM-004), and what Serena 1.7.0 wrote to `.serena/project.yml` when it started there (None: nothing): the same
# bytes come back when the agent's own server starts, and they are Serena's, not the agent's. A fallback to another
# CLI is checked on its own, and so is every unit's worktree: Serena names the project after its directory.
_SERENA_CHECKED: dict[tuple[str, str, str], tuple[SerenaStatus, bytes | None]] = {}

_BYTECODE_KEPT = frozenset({".git", ".venv", "node_modules"})  # the installed environment and git are not ours here


def env_root(rel: str) -> str:
    """The environment directory a manifest path belongs to: `.venv`, or the path up to the first `node_modules`."""
    parts = rel.split("/")
    if parts[0] == ".venv":
        return ".venv"
    return "/".join(parts[: parts.index("node_modules") + 1]) if "node_modules" in parts else parts[0]


def private_dir(path: Path) -> None:
    """The directory, and mode 0700 on it: only the unit's own sandboxes may see what a step keeps there. The mode is
    set after the `mkdir` because the umask can only remove bits, never add them (L4-PRV-040)."""
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.chmod(0o700)


def remove_leftover_credentials(agent_tmp: Path) -> list[Path]:
    """A provider key file and a credential-loader file that a killed run (SIGKILL skips every `finally`) left in the
    unit's step directory are removed before any agent or gate runs. Returns what it removed (L4-PRV-041)."""
    removed: list[Path] = []
    for path in (agent_tmp / CONFIG_DIR / KEY_FILE, agent_tmp / CREDENTIAL_FILE):
        if path.is_file() or path.is_symlink():
            path.unlink()
            removed.append(path)
    if removed:
        log.warning("%s: removed %d credential file(s) a killed run left behind", agent_tmp.parent.name, len(removed))
    return removed


def purge_bytecode(worktree: Path, tracked: Collection[str] = ()) -> None:
    """Delete every untracked `*.pyc` file and everything in a `__pycache__` directory of the work tree (not under
    `.venv/`, `node_modules/` or a `.git`). Gates run agent-written test code with the work tree writable, and an
    unchecked hash-based `.pyc` is never compared with its source: planted by one gate it would run, in place of the
    committed source, in every later gate (a stub would pass green). The harness ignores these files, so no guard
    sees them; they are removed before each gate instead. A symlink is removed, never followed."""
    for top, dirs, files in os.walk(worktree):
        here = Path(top)
        keep: list[str] = []
        for name in dirs:
            path = here / name
            if name in _BYTECODE_KEPT:
                continue
            if path.is_symlink():
                if name == "__pycache__":
                    path.unlink()
                continue
            keep.append(name)
        dirs[:] = keep
        cache = here.name == "__pycache__"
        for name in files:
            path = here / name
            if (cache or name.endswith(".pyc")) and path.relative_to(worktree).as_posix() not in tracked:
                path.unlink(missing_ok=True)


def clip_subject(message: str) -> str:
    """One line of at most MAX_SUBJECT_CHARS; a trailing `[skip ci]` survives the clip."""
    subject = " ".join(message.split())
    if not subject.endswith(SKIP_CI):
        return subject[:MAX_SUBJECT_CHARS]
    room = MAX_SUBJECT_CHARS - len(SKIP_CI) - 1
    return subject[: -len(SKIP_CI)].rstrip()[:room].rstrip() + " " + SKIP_CI


@dataclass(frozen=True)
class UnsafeWrite:
    """A harness write that was refused (L4-SEC-021): the `path` it was for, the `rule` (`planted link` or `restore
    failed`) and the step it happened in (`where`). `link` is the planted link itself, `target` where it pointed."""

    path: str
    rule: str
    where: str
    link: str = ""
    target: str = ""


MAX_UNSAFE_SHOWN = 5


@dataclass(frozen=True)
class PreviousAttempt:
    """What the next profile is told after a limit cut a task short: who it was and which limit, never a transcript."""

    profile: str
    limit_kind: str | None
    task: str | None = None
    why: Literal["limit", "escalation"] = "limit"
    phase: str | None = None
    failures: tuple[tuple[str, str], ...] = ()  # (profile, reason) of the failed attempts, oldest first


@dataclass
class StepOutcomeBox:
    """What `Workbench.wip_snapshots` records as the `status` of `step.finished` (default: the step returned)."""

    status: str = "ok"


@dataclass
class Workbench:
    cfg: L4Config
    ref: UnitRef  # the unit inside the worktree
    provider: SpecProvider  # bound to the worktree
    worktree: Path
    git: Git  # runs in the worktree
    ledger: Any  # LedgerWriter: `append(type, **data)`
    sandbox: Sandbox
    selected: Selected  # the implementer: adapter, profile name and profile
    host_env: Mapping[str, str]
    redactor: Redactor
    run_id: str
    iteration: int
    unit_cache: Path
    cache_root: Path
    repo_key: str
    out_dir: Path
    home: Path
    git_common_dir: Path
    caches: tuple[CacheMount, ...]
    protected: ProtectedSet
    ledger_rel: str
    unit_rel: str
    push: Callable[[], None] = lambda: None
    runner: ProcRunner = field(default_factory=ProcRunner)
    baselines: dict[str, TestReport] = field(default_factory=dict)
    static_baselines: dict[str, dict[tuple[str, str], str]] = field(default_factory=dict)  # per base commit
    # (base commit, job) -> how a failing CI step ran at that base: (reproduced|skipped, reason), M1.10 decision 4
    ci_reproductions: dict[tuple[str, str], tuple[str, str | None]] = field(default_factory=dict)
    setup_at: str | None = None  # the HEAD `gates.setup` last ran at, valid until an agent step has run
    previous_attempt: PreviousAttempt | None = None  # set by the orchestrator after a mid-run fallback
    event_context: Mapping[str, Any] = field(default_factory=dict)  # added to every event: a fix unit's name
    coverage_checked: bool = False  # `check_coverage_after_setup` has answered once for this workbench
    seed_checked: bool = False  # `ensure_uv_seed` has looked at this workbench's uv cache once
    guard_notes: list[GuardNote] = field(default_factory=list)  # what the guards put back since `run_task` cleared it
    unsafe: list[UnsafeWrite] = field(default_factory=list)  # harness writes refused since `run_task` cleared it
    activated_digest: str | None = None  # the unit folder's digest frozen at the plan's activation (plan step), if any
    activated_plan: str | None = None  # the plan that froze it
    # tree -> the manifest of its environment directories as the last passing `gates.setup` left them (L4-SEC-036). In
    # memory only: a file under the cache would be one more thing `sandbox.mode: none` code could edit.
    env_manifests: dict[Path, envguard.EnvManifest] = field(default_factory=dict)
    held_removals: list[str] = field(default_factory=list)  # saved held steps (L4-IMP-065) the next step commit deletes
    replay_expected: Any = ()  # path -> (mode, blob id, size) | None: base plus the saved patch (held_patch.py)
    replay_links: Any = ()  # the links the saved patch creates (path -> blob of its target)
    replay_guard: Any = None  # the `ReplayGuard` of a replayed step (held_patch.py), armed before its first gate
    replay_question: str | None = None  # the question whose saved step this step replays: its accept applies now
    commit_agent: str | None = (
        None  # the `L4-Agent` of the next commit, when a replayed step was written by another profile
    )
    # the model the latest agent step of this task reported as served (None: the adapter reports none, or no step ran)
    served_model: str | None = None

    def asker(self) -> dict[str, Any]:
        """Who a question raised now is asked by (L4-DLG-002): the step's profile and the model that served it, else
        the profile's configured model (None when neither is known). The delegate must be neither."""
        return {"profile": self.selected.profile_name, "model": self.served_model or self.selected.profile.model}

    def __post_init__(self) -> None:
        private_dir(self.unit_cache)  # the unit's step files are for its own sandboxes only (L4-PRV-040)
        remove_leftover_credentials(self.unit_cache / "agent-tmp")  # a killed run skipped the `finally` (L4-PRV-041)
        for sub in ("agent-tmp", "gate-tmp"):
            private_dir(self.unit_cache / sub)
        self.excludes.write_text("\n".join(HARNESS_EXCLUDES) + "\n", encoding="utf-8")

    @property
    def impl(self) -> AgentAdapter:
        return self.selected.impl

    @property
    def excludes(self) -> Path:
        return self.unit_cache / "excludes"  # outside the worktree and never mounted: the agent cannot edit it

    @property
    def agent_tmp(self) -> Path:
        return self.unit_cache / "agent-tmp"

    @property
    def exclude_config(self) -> tuple[tuple[str, str], ...]:
        return (("core.excludesFile", str(self.excludes)),)

    def emit(self, event_type: str, /, **data: Any) -> None:
        if (note := note_of(event_type, data)) is not None:  # the next attempt's prompt tells the agent (F3)
            self.guard_notes.append(note)
        self.ledger.append(event_type, **{**data, **self.event_context})

    def append(self, event_type: str, /, **data: Any) -> None:
        """The event sink of the guards, which would otherwise write to the ledger without the context."""
        self.emit(event_type, **data)

    def refused_write(self, exc: UnsafeFile, *, path: str, where: str, root: Path | None = None) -> None:
        """A harness write was refused (L4-SEC-020). A planted link is removed itself (never its target) and recorded as
        `guard.violation{phase: gate, rule: "planted link"}`; any other refusal is `rule: "restore failed"`. Nothing is
        raised: this runs in `finally` blocks. The same link is recorded once per attempt. `root`: the checkout the
        gate ran in (the worktree by default)."""
        root = root or self.worktree
        if isinstance(exc, LinkedPath):
            if any(u.rule == "planted link" and u.link == exc.link for u in self.unsafe):
                remove_link(root, exc.link)
                return
            try:
                target = os.readlink(root / exc.link)
            except OSError:
                target = ""
            remove_link(root, exc.link)
            self.unsafe.append(UnsafeWrite(path, "planted link", where, exc.link, target))
            self.emit(
                "guard.violation", phase="gate", rule="planted link", path=exc.link, action="removed", where=where,
                target=path, points_to=target,
            )  # fmt: skip
            return
        self.unsafe.append(UnsafeWrite(path, "restore failed", where))
        self.emit(
            "guard.violation", phase="gate", rule="restore failed", path=path, action="refused", where=where,
            why=str(exc),
        )  # fmt: skip

    def planted_links(self) -> list[UnsafeWrite]:
        return [u for u in self.unsafe if u.rule == "planted link"]

    def unsafe_reason(self) -> str:
        """ "" when no harness write was refused in this attempt; else why the attempt cannot stand (L4-SEC-021)."""
        if not self.unsafe:
            return ""
        planted = self.planted_links()
        pool = planted or self.unsafe
        paths = list(dict.fromkeys(u.link if u.rule == "planted link" else u.path for u in pool))
        shown = ", ".join(paths[:MAX_UNSAFE_SHOWN]) + (
            f" (+{len(paths) - MAX_UNSAFE_SHOWN} more)" if len(paths) > MAX_UNSAFE_SHOWN else ""
        )
        if planted:
            return (
                f"a gate run put a symbolic link at {shown} (on the path of a file the harness restores); the harness "
                "removed it and wrote nothing through it. Nothing of this attempt is kept"
            )
        return f"the harness could not put {shown} back after a gate run. Nothing of this attempt is kept"

    @property
    def credential_paths(self) -> dict[str, tuple[Path, ...]]:
        return expand_credential_paths(self.cfg.sandbox.credential_paths, self.home)

    def agent_spec(self) -> SandboxSpec:
        """Only the selected adapter's login is visible; the sandbox hides every other adapter's."""
        tools, _ = spec_paths(
            self.host_env, home=self.home, cache_root=self.cache_root, kind="agent", sandbox_cfg=self.cfg.sandbox,
            credential_paths=self.credential_paths, forbid=(self.worktree, self.git_common_dir.parent),
        )  # fmt: skip
        return SandboxSpec(
            "agent", self.worktree, self.git_common_dir, self.agent_tmp, self.home, self.credential_paths,
            adapter=self.selected.profile.adapter, network=True,
            caches=readonly_with_scratch(self.caches, self.agent_tmp, create=False),
            runner_tmp=runner_tmp_paths(self.host_env), cache_root=self.cache_root, tool_paths=tools,
        )  # fmt: skip

    def gate_spec(
        self,
        *,
        network: bool,
        tree: Path | None = None,
        caches: tuple[CacheMount, ...] | None = None,
        builds_env: bool = False,
        record_dir: Path | None = None,
    ) -> SandboxSpec:
        """No adapter: the sandbox hides every login, so agent-written tests cannot read one. `caches` replaces the
        unit's own mounts (the uv seed's fill, which runs no agent-written code). `builds_env` is true for a
        `gates.setup` command: it alone gets `sandbox.setup_paths` (L4-SEC-033)."""
        root = tree or self.worktree
        tools, setup = spec_paths(
            self.host_env, home=self.home, cache_root=self.cache_root, kind="gate", sandbox_cfg=self.cfg.sandbox,
            credential_paths=self.credential_paths, forbid=(root, self.git_common_dir.parent), builds_env=builds_env,
        )  # fmt: skip
        return gate_sandbox_spec(
            worktree=root, git_common_dir=self.git_common_dir, tmp_dir=self.unit_cache / "gate-tmp",
            home=self.home, configured_credential_paths=self.cfg.sandbox.credential_paths,
            caches=self.caches if caches is None else caches,
            network=network, runner_tmp=runner_tmp_paths(self.host_env), record_dir=record_dir,
            cache_root=self.cache_root, tool_paths=tools, setup_paths=setup, builds_env=builds_env,
            tracked=() if builds_env else self._tracked_env(self.git if tree is None else self.git.at(root)),
        )  # fmt: skip

    def run_gate(
        self,
        name: str,
        command: str,
        *,
        reports: Sequence[str] = (),
        network: bool | None = None,
        must_contain: Collection[str] = (),
        extra_env: Mapping[str, str] | None = None,
        note: Callable[[TestReport], dict] | None = None,
        builds_env: bool = False,
    ) -> GateResult:
        """`network` defaults to `gates.network`; the setup step passes True (it downloads the dependencies).
        `extra_env` (the coverage plugin's `cov_env`) is merged with the trace plugin's: `PYTEST_ADDOPTS` and
        `PYTHONPATH` join, any other key is added."""
        allowed = self.cfg.gates.network == "allow" if network is None else network
        spec = GateSpec(
            name, command, tuple(reports), self.cfg.gates.test.format, duration_seconds(self.cfg.gates.timeout),
            frozenset(must_contain),
        )  # fmt: skip
        return self.run_gate_spec(spec, network=allowed, extra_env=extra_env, note=note, builds_env=builds_env)

    def run_gate_spec(
        self,
        spec: GateSpec,
        *,
        network: bool,
        tree: Path | None = None,
        extra_env: Mapping[str, str] | None = None,
        caches: tuple[CacheMount, ...] | None = None,
        note: Callable[[TestReport], dict] | None = None,
        builds_env: bool = False,
    ) -> GateResult:
        """The one way a gate runs, in the unit's worktree or in another checkout of the repository (the merge base the
        verifier serves): bytecode purged before, the protected set put back after, the trace plugin loaded, the
        ledger restored and `gate.finished` emitted. Every gate runs agent-written code with the tree writable."""
        root = self.worktree if tree is None else tree
        git = self.git if tree is None else self.git.at(root)
        log = self._next_gate_log(spec.name)
        # the outcome record: a random name in a directory of its own that the gate's TMPDIR does not hold (a glob over
        # `tempfile.gettempdir()` finds nothing), made fresh for this run and removed after the cross-check
        record_dir = self.unit_cache / "records" / secrets.token_hex(8)
        record_dir.mkdir(parents=True, exist_ok=True)
        record = record_dir / f"{secrets.token_hex(16)}.jsonl"
        purge_bytecode(root, self._tracked_bytecode(git))
        self._report_links(root, spec)  # a link on a report path is removed and recorded: the gate writes a real one
        tracked_env = self._tracked_env(git)
        if builds_env:
            if root not in self.env_manifests:  # L4-SEC-037: never build on an environment this workbench did not
                self._remove_unverified_env(root, tracked_env)
        else:
            reset_tool_caches(root, tracked_env)  # empty and writable at every gate; the only protection of them here
        before = snapshot_protected(root, self.protected)
        configs = snapshot_config(self.cfg, root, git, self.excludes)
        try:
            result = run_gate(
                spec, worktree=root, sandbox=self.sandbox,
                sandbox_spec=(
                    self.gate_spec(network=network, tree=root, builds_env=builds_env, record_dir=record_dir)
                    if caches is None
                    else self.gate_spec(
                        network=network, tree=root, caches=caches, builds_env=builds_env, record_dir=record_dir
                    )
                ),
                host_env=self.host_env, log_path=log,
                redactor=self.redactor, runner=self.runner,
                extra_env=merge_pytest_env(
                    toolchain_env(self.cfg),
                    trace_env(self.cfg.gates.test_timeout_seconds()),
                    extra_env or {},
                    {"L4_OUTCOME_FILE": str(record)},
                ),
            )  # fmt: skip
        finally:
            # agent-written test code ran with the tree writable: what it wrote into the unit directory (a forged
            # human answer in `questions.md`, an earlier run's ledger) must not reach the next commit
            # ... and what it wrote anywhere else a protected rule reaches (`src/pkg/CLAUDE.md`, a migration): the
            # snapshot holds only the anchored roots. Both act on the tree the gate ran in.
            for v in [*restore_protected(root, self.protected, before),
                      *revert_unsnapshotted(git, self.protected, excludes=self.excludes)]:  # fmt: skip
                self.emit("guard.violation", path=v.path, rule=v.rule, action=v.action, phase="gate")
            # ... and the gate and runner configuration the gates read (L4-IMP-040): a test that loosens `ruff.toml`
            # while it runs must not change what the lint gate that follows judges. No tag lifts this.
            restore_config(self, root, git, configs, where=spec.name)
        self._report_links(root, spec)  # ... and one the gate planted: the restores that follow must find a real folder
        self.restore_ledger()
        result = self._cross_check(spec, result, record)
        shutil.rmtree(record_dir, ignore_errors=True)
        discard_tree(self.unit_cache / "gate-tmp" / SCRATCH_DIR)  # a gate's private caches go with it
        if builds_env:
            if result.status == "pass":
                reset_tool_caches(root, tracked_env)
                self.env_manifests[root] = take_manifest(root, tracked_env)
            else:
                self.env_manifests.pop(root, None)  # a half-built environment is nobody's: the next setup starts over
        else:
            self.check_env(root, phase="gate", git=git)
        readable = result.report is not None and result.status == "fail"  # a red note is for a failing gate
        extra = note(result.report) if note is not None and readable else {}
        if result.report is not None:
            extra = {**extra, "collection_errors": len(result.report.collection_errors)}
        if excerpt := self._gate_excerpt(spec, result):
            extra = {**extra, "excerpt": excerpt}
        self.emit(
            "gate.finished", name=spec.name, status=result.status, exit_code=result.exit_code, reason=result.reason,
            log=os.path.relpath(log, self.out_dir.parent), tests=result.report.total if result.report else None,
            passed=len(result.report.ids_with("passed")) if result.report else None,
            failed=len(result.report.ids_with("failed") | result.report.ids_with("error")) if result.report else None,
            **extra,
        )  # fmt: skip
        if result.deadline:  # after every restore and `gate.finished`: the step is handed back (L4-IMP-068)
            raise DeadlineReached("during", during="gate", gate=spec.name)
        return result

    def _report_links(self, root: Path, spec: GateSpec) -> None:
        for rel in spec.reports:
            if (link := linked_component(root, rel)) is not None:
                self.refused_write(LinkedPath(link), path=rel, where=spec.name, root=root)

    def _tracked_env(self, git: Git | None = None) -> frozenset[str]:
        """Paths git tracks inside `.venv` or any `node_modules`: such a directory is source, not an environment."""
        return tracked_env_paths(git or self.git)

    def _remove_unverified_env(self, tree: Path, tracked: Collection[str]) -> None:
        """L4-SEC-037: the first `gates.setup` command of this workbench in `tree` finds an environment it did not
        build (the implementer's, in the verifier's workbench): it goes before the setup builds one."""
        dirs = [d for d in env_dirs(tree, tracked) if os.path.lexists(d)]
        if not dirs:
            return
        for path in dirs:
            remove_env_dir(path)
        self._env_removed(tree, dirs, "unverified", phase="setup", diff=envguard.EnvDiff((), (), ()), plants=None)

    def check_env(self, tree: Path, *, phase: str, changed: Collection[str] = (), git: Git | None = None) -> bool:
        """Compare the environment directories of `tree` with the manifest the last passing setup took (L4-SEC-036). A
        directory that differs, is new or has no manifest is removed, so the next `gates.setup` builds it again, and
        recorded: one `env.rebuilt`, then one `guard.violation` (rule `environment`) per path that no install explains
        and one `guard.notice` per path of a dependency change without a lock file (at most MAX_REPORTED together).
        Returns whether anything was removed."""
        git = git or (self.git if tree == self.worktree else self.git.at(tree))
        tracked = self._tracked_env(git)
        manifest = self.env_manifests.get(tree)
        after = take_manifest(tree, tracked)
        if manifest is None and not after:
            return False
        before = manifest if manifest is not None else {}
        diff = diff_manifest(before, after)
        if not diff:
            return False
        existing = {d.relative_to(tree).as_posix(): d for d in env_dirs(tree, tracked)}
        hit = sorted({env_root(p) for p in (*diff.added, *diff.changed, *diff.removed)})  # directories that differ
        # no manifest: a project without `gates.setup`, or a tree setup never built: whatever is there is new to us
        reason = "created" if manifest is None or any(rel not in before for rel in hit) else "changed"
        # classified before anything is removed: the RECORD files and the hashes are read from the files themselves
        plants = envguard.classify(tree, diff, changed, read_head=self._head_reader(git))
        gone = [rel for rel in hit if rel not in existing]  # a directory the step or gate deleted
        for rel in hit:
            if rel in existing:
                remove_env_dir(existing[rel])
        for key in [k for k in before if any(k == rel or k.startswith(rel + "/") for rel in hit)]:
            before.pop(key, None)  # the manifest forgets what was removed
        if manifest is not None:
            self.env_manifests[tree] = before
        self._env_removed(tree, hit, reason, phase=phase, diff=diff, plants=plants)
        return bool(hit) or bool(gone)

    def _head_reader(self, git: Git) -> Callable[[str], bytes | None]:
        def read(path: str) -> bytes | None:
            try:
                return git.run_bytes("show", f"HEAD:{path}")
            except GitError:
                return None

        return read

    def _env_removed(
        self, tree: Path, dirs: Sequence[Path | str], reason: str, *, phase: str, diff: envguard.EnvDiff,
        plants: envguard.Plants | None,
    ) -> None:  # fmt: skip
        if tree == self.worktree:
            self.setup_at = None  # the next `run_setup` builds the environment again
        else:
            self.env_manifests.pop(tree, None)
        reported = [("guard.violation", p) for p in plants.violations] if plants else []
        reported += [("guard.notice", p) for p in plants.notices] if plants else []
        shown = reported[:MAX_REPORTED_PLANTS]
        self.emit(
            "env.rebuilt", tree="worktree" if tree == self.worktree else tree.name,
            dirs=[d if isinstance(d, str) else d.relative_to(tree).as_posix() for d in dirs], phase=phase,
            added=len(diff.added), changed=len(diff.changed), removed=len(diff.removed), reason=reason,
            declared=bool(plants and plants.declared), planted_more=len(reported) - len(shown),
        )  # fmt: skip
        for event, path in shown:
            self.emit(event, path=path, rule="environment", action="removed", phase=phase)

    def _cross_check(self, spec: GateSpec, result: GateResult, record: Path) -> GateResult:
        """The JUnit report against the plugin's record of what pytest judged (detect-test-tamper, third review): code
        that rewrote the report after the run makes the gate fail with no readable report, naming the tests. With no
        record there is no check."""
        if result.report is None:
            return result
        loaded = record.exists()  # the plugin creates the record when it is imported: a file means pytest ran with it
        rows = read_record(record)
        record.unlink(missing_ok=True)
        if not rows and result.report.tests and (loaded or re.search(r"\bpy\.?test\b", spec.command)):
            # the harness's plugin ran (the record exists, or the command names pytest): an empty, missing or unreadable
            # record under a report that holds test cases is the record being removed (fourth and fifth review); a
            # runner without the plugin (Go, TypeScript) never creates one and is not held to it
            self.emit("guard.report_altered", gate=spec.name, tests=[], reason="no outcome record")
            reason = f"the test report was altered (no outcome record): {result.report.total} test(s) in the report"
            return replace(result, status="fail", report=None, reason=reason)
        bad = altered(result.report, rows)
        if not bad:
            return result
        shown = ", ".join(bad[:5]) + (f" (+{len(bad) - 5} more)" if len(bad) > 5 else "")
        self.emit("guard.report_altered", gate=spec.name, tests=bad[:50])
        return replace(result, status="fail", report=None, reason=f"the test report was altered: {shown}")

    def _gate_excerpt(self, spec: GateSpec, result: GateResult) -> str:
        """What the committed ledger keeps of a test gate that failed without telling which test (no report, no test
        executed, or a collection error): the `E` lines and the deepest repository location, at most 600 characters and
        redacted (L4-IMP-064). It is read from the first collection error's traceback, else from the end of the gate
        log, and no prompt ever reads it. A failing gate with no reports (setup, lint, typecheck) keeps the redacted
        last 600 characters of its log. Empty for a passing gate and for a test gate whose report names the failures."""
        report = result.report
        if result.status != "fail":
            return ""
        if not spec.reports:  # setup, lint, typecheck: no report to read, so the redacted end of the log (rv18-ops 3b)
            try:
                text = result.log_path.read_text(encoding="utf-8", errors="replace")[-40_000:]
            except OSError:
                return ""
            tail = self.redactor.redact_text(text).strip()[-MAX_COLLECTION_ERROR_CHARS:]  # redacted whole, then cut
            return self.redactor.redact_text(tail)
        if report is not None and report.executed > 0 and not report.collection_errors:
            return ""
        text = (
            report.collection_details.get(report.collection_errors[0], "")
            if report and report.collection_errors
            else ""
        )
        if not text:
            try:
                text = result.log_path.read_text(encoding="utf-8", errors="replace")[-40_000:]
            except OSError:
                text = ""
        # redacted whole first, cut after: a cut inside a secret would leave a prefix the redactor cannot see
        return self.redactor.redact_text(ledger_excerpt(self.redactor.redact_text(text)))

    def _tracked_bytecode(self, git: Git | None = None) -> frozenset[str]:
        """Bytecode the repository itself commits (rare): a changed copy is a production change the guards see."""
        raw = (git or self.git).run_bytes("ls-files", "-z", "--", ":(glob)**/*.pyc", ":(glob)**/__pycache__/**")
        return frozenset(os.fsdecode(p) for p in raw.split(b"\0") if p)

    def _next_gate_log(self, name: str) -> Path:
        """Numbered after the logs already in the run's directory: the verifier builds a new Workbench under the same
        run id, and its logs must not replace the implementer's."""
        folder = self.out_dir / "gates" / self.run_id
        taken = [int(p.name[:3]) for p in folder.glob("[0-9][0-9][0-9]-*.log")] if folder.is_dir() else []
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", name).replace("..", "_")[
            :MAX_GATE_LOG_NAME
        ]  # a job name: `/`, `:`, `..`
        return folder / f"{max(taken, default=0) + 1:03d}-{safe}.log"

    def restore_ledger(self, **context: object) -> None:
        """Agent steps and gates run in the worktree that holds this run's ledger, and the protected-path revert
        deliberately skips it: put it back to what the writer wrote before anything is folded or committed."""
        if (tamper := self.ledger.restore_if_tampered()) is not None:
            self.emit("guard.violation", path=self.ledger_rel, rule="run ledger", action="restored",
                      **tamper.fields(), **context)  # fmt: skip

    def head(self) -> str:
        sha = self.git.rev_parse("HEAD")
        if sha is None:
            raise RuntimeError("the worktree has no HEAD")
        return sha

    def changed_files(self) -> list[str]:
        """Paths that differ from HEAD, untracked ones included, without the harness's ignored directories."""
        raw = self.git.run_bytes("-c", f"core.excludesFile={self.excludes}", "-c", "status.renames=false",
                                 "status", "--porcelain=v1", "-z", "--untracked-files=all")  # fmt: skip
        return [os.fsdecode(rec[3:]) for rec in raw.split(b"\0") if len(rec) > 3]

    def branch_changed_files(self) -> list[str]:
        """Paths the unit branch has already committed since the base branch (see `inject.branch_changed_files`)."""
        return branch_changed_files(self.git, f"refs/remotes/origin/{self.cfg.forge.base_branch}")

    def is_clean(self) -> bool:
        """No change but the harness's own output (`.venv/`, `.l4-out/`, ...): a plain `git status` would list the
        JUnit report the test gate writes into the worktree. This run's ledger is the harness's own file too."""
        return all(path == self.ledger_rel for path in self.changed_files())

    def commit(
        self, message: str, *, task: str, attempt: int, phase: str, tdd: str | None, paths: Sequence[str] = ()
    ) -> str:
        """Stage (everything not ignored, or just `paths` plus the run's ledger) and commit with trailers."""
        self.restore_ledger()
        if paths:
            self.git.run("add", "--", *paths, self.ledger_rel)
        else:
            removed = list(self.held_removals)
            for rel in removed:  # a replayed or spent held step goes with the commit that used it
                (self.worktree / rel).unlink(missing_ok=True)
            self.held_removals.clear()
            if self.replay_guard is not None:  # a replayed step commits base plus patch, never what the tree holds
                staged = self.replay_guard.stage_paths(removed)
                for start in range(0, len(staged), 200):
                    self.git.run("add", "-A", "-f", "--", *(f":(literal){p}" for p in staged[start : start + 200]))
            else:
                self.git.run("add", "-A", config=self.exclude_config)
        profile = self.selected.profile
        agent = self.commit_agent or (
            f"{self.selected.profile_name}/{profile.model}" if profile.model else self.selected.profile_name
        )
        self.commit_agent = None
        trailers = CommitTrailers(
            unit=self.ref.id, run_id=self.run_id, iteration=self.iteration, phase="implementing", task=task, tdd=tdd,
            agent=agent, step=f"{task}/{phase}/{attempt}", fallback_from=self.selected.fallback_from,
        )  # fmt: skip
        sha = self.git.commit(clip_subject(message), trailers)
        # the step is on the branch: its snapshot is stale and must not be reported as an interrupted step next run
        self.git.run("update-ref", "-d", wip_ref(self.ref.id))
        return sha

    @contextmanager
    def at_clean_head(self) -> Iterator[None]:
        """A baseline is a measurement of the step base. After a crash the reconciler has put the killed run's work
        back into the worktree, and everything that work broke would read as 'already failing at the base': set it
        aside (a private snapshot, never the unit's WIP ref), run, and put it back. The ledger stays where it is."""
        sha = (
            None
            if self.is_clean()
            else snapshot_wip(
                self.git, self.ref.id, config=self.exclude_config, update_ref=False, exclude=self.ledger_rel
            )
        )
        if sha is None:
            yield
            return
        self._reset_to_head(ignored=False)
        try:
            yield
        finally:
            restore_wip(self.git, sha, exclude=self.ledger_rel)

    def _reset_to_head(self, *, ignored: bool) -> None:
        keep = self.ledger_rel
        self.git.run("checkout", "HEAD", "--", ".", f":(exclude){keep}")
        # ignored=True (-x): a file the agent hid behind .gitignore must not survive into the next attempt; the
        # harness's own directories (.venv, .l4-out, ...) and the ledger are kept by -e, which still applies under -x
        keeps = [arg for pattern in (f"/{keep}", *HARNESS_EXCLUDES) for arg in ("-e", pattern)]
        self.git.run("clean", "-fdxq" if ignored else "-fdq", *keeps)

    def discard_changes(self) -> None:
        """Back to HEAD for everything but this run's ledger, which an open file descriptor is appending to: a
        plain `reset --hard` would replace the file under the writer and lose every later line."""
        self._reset_to_head(ignored=True)
        # the snapshot of the discarded attempt must not come back: a later run would restore its files onto a head
        # that never had them
        self.git.run("update-ref", "-d", wip_ref(self.ref.id))

    def agent_log_paths(self, stem: str) -> tuple[Path, Path]:
        """(private, published) path of an agent's raw event stream. The adapter writes the first, outside the
        worktree and `.l4-out/`; only the redacted copy under the second is ever uploaded (L4-OBS-002)."""
        private = self.unit_cache / "agent-raw" / self.run_id / f"{stem}.jsonl"
        return private, self.out_dir / "agent" / self.run_id / f"{stem}.jsonl"

    def publish_agent_logs(self, private: Path, published: Path) -> None:
        """Redacted copies of the stream and its `.stderr` sibling; the raw files are deleted."""
        published.parent.mkdir(parents=True, exist_ok=True)
        for source in sorted(private.parent.glob(private.stem + ".*")):
            if source.is_file() and not source.is_symlink():
                text = source.read_text(encoding="utf-8", errors="replace")
                (published.parent / source.name).write_text(self.redactor.redact_text(text), encoding="utf-8")
            source.unlink()

    def publish_prompt(self, published: Path, text: str) -> Path:
        """The prompt as sent (already redacted) next to the agent's events, so a reviewer can see what the agent
        was told: the CLIs do not echo their stdin into the event stream. A judge call publishes its prompt document,
        without the schema instruction a prompt-contract adapter appends (`agent_judge.schema_suffix`, L4-VER-005)."""
        target = published.with_suffix(".prompt.md")
        target.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_bytes(target, text.encode("utf-8"))
        return target

    @contextmanager
    def wip_snapshots(self, task: str, phase: str, attempt: int) -> Iterator[StepOutcomeBox]:
        """Around one agent run (L4-IMP-011, local form): `step.started`, a timer that snapshots the worktree every
        `implementer.wip_snapshot_interval`, and a last snapshot when the agent returns; then `wip.snapshot{shas}` (when
        any was taken) and `step.finished{status}`, both written by the calling thread. A snapshot is a local ref and
        never a commit of the unit branch; one that fails is logged and costs the run nothing. The block sets
        `box.status` to the agent's own `RunResult.status` when the run returned (`rate_limited`, `quota`, `auth`, ...):
        that is what `step.finished` records, so a throttled step is not `ok`. An exception out of it is `error`."""
        self.emit("step.started", task=task, phase=phase, attempt=attempt, agent=self.selected.profile_name)
        shas: list[str] = []
        stop = threading.Event()
        interval = max(duration_seconds(self.cfg.implementer.wip_snapshot_interval), 1)
        step = f"{task}/{phase}/{attempt}"

        def take() -> None:
            try:
                sha = snapshot_wip(self.git, self.ref.id, config=self.exclude_config, step=step)
            except Exception as exc:  # noqa: BLE001 - a snapshot is a courtesy; the agent's run must go on
                log.warning("%s: WIP snapshot failed: %s", self.ref.id, type(exc).__name__)
                return
            if sha is not None and sha not in shas:
                shas.append(sha)

        def tick() -> None:
            while not stop.wait(interval):
                take()

        timer = threading.Thread(target=tick, name="l4-wip-snapshots", daemon=True)
        timer.start()
        status = "error"
        box = StepOutcomeBox()
        try:
            yield box
            status = box.status
        finally:
            stop.set()
            timer.join()
            take()  # what the agent left behind, even when it ended in an error
            if shas:
                self.emit("wip.snapshot", task=task, phase=phase, attempt=attempt, shas=list(shas))
            self.emit("step.finished", task=task, phase=phase, attempt=attempt, status=status)

    def mcp_servers(self, env: Mapping[str, str]) -> list[McpServer]:
        """The MCP servers of an implement-mode request: Serena, when memory and Serena are on, the adapter has a
        Serena context and the run's one `check_serena` passed (SCN-MEM-06: a failed check records
        `memory.serena{status: failed}` and the run goes on without it). `env` is the request's own environment: the
        check runs Serena in the environment the agent's CLI starts it in. Call after `reset_agent_tmp`."""
        cfg = self.cfg.memory.serena
        adapter = self.selected.profile.adapter or ""
        if not (self.cfg.memory.enabled and cfg.enabled) or serena_context(adapter, cfg.context) is None:
            return []
        binary = resolve_tool("serena", env, forbid=(self.worktree,))
        key = (self.run_id, serena_context(adapter, cfg.context) or "", str(self.worktree))
        status, _ = _SERENA_CHECKED.get(key, (None, None))
        if status is None:
            if binary is None:
                status = SerenaStatus(False, "serena was not found on the agent PATH")
                self.emit("memory.serena", status="failed", reason=status.reason, startup_ms=0)
            else:
                spec = self.agent_spec()
                status = check_serena(
                    binary, self.worktree, self.agent_tmp, adapter=adapter, cfg=cfg,
                    wrap=lambda argv, e: self.sandbox.wrap(argv, spec, e), environ=env, events=self,
                )  # fmt: skip
            _SERENA_CHECKED[key] = (status, self._take_serena_project())
        if not status.ok or binary is None:
            return []
        server = mcp_server_for(adapter, self.worktree, self.agent_tmp, cfg=cfg, binary=binary, environ=env)
        return [server] if server is not None else []

    def reset_agent_tmp(self) -> Path:
        remove_tree(self.agent_tmp)  # raises when it cannot: the step must start from an empty directory
        private_dir(self.agent_tmp)
        readonly_with_scratch(self.caches, self.agent_tmp, create=True)  # makes the step's private cache directories
        return self.agent_tmp

    def discard_scratch(self) -> None:
        """The agent's private caches go with the step (L4-SEC-039)."""
        discard_tree(self.agent_tmp / SCRATCH_DIR)

    def _take_serena_project(self) -> bytes | None:
        """What Serena left in `.serena/project.yml` while it started (it rewrites the file into its full form, or
        creates it); the file goes back to HEAD at once, so the check leaves the work tree as it found it."""
        path = self.worktree / SERENA_PROJECT
        written = path.read_bytes() if path.is_file() and not path.is_symlink() else None
        self._restore_project(self.head())
        return written

    def _restore_project(self, base: str) -> None:
        target = self.worktree / SERENA_PROJECT
        if self.git.run("cat-file", "-e", f"{base}:{SERENA_PROJECT}", check=False).returncode == 0:
            if target.is_symlink():
                target.unlink()
            self.git.run("checkout", base, "--", f":(literal){SERENA_PROJECT}")
        elif target.is_file() or target.is_symlink():
            target.unlink()

    def settle_serena_project(self, base: str) -> None:
        """After an agent step, before the protected-path revert: when `.serena/project.yml` holds exactly what Serena
        wrote at its start (the agent's own server does the same), put it back to `base` without a violation. Any
        other content is the agent's and is left to the revert."""
        path = self.worktree / SERENA_PROJECT
        if not path.is_file() or path.is_symlink():
            return
        found = path.read_bytes()
        forms = [
            form
            for (run, _, tree), (_, form) in _SERENA_CHECKED.items()
            if run == self.run_id and tree == str(self.worktree)
        ]
        if any(form == found for form in forms):
            self._restore_project(base)
        elif forms:  # live M1.7: it fired at every agent step and the log did not say how the two differed
            seen = ", ".join("none" if f is None else hashlib.sha256(f).hexdigest()[:12] for f in forms)
            log.warning(
                "%s: %s differs from what Serena wrote at its check (sha256 %s, the check's %s)",
                self.ref.id, SERENA_PROJECT, hashlib.sha256(found).hexdigest()[:12], seen,
            )  # fmt: skip


def make_workbench(
    *,
    cfg: L4Config,
    app: AppContext,
    ref: UnitRef,
    provider: SpecProvider,
    worktree: Path,
    git: Git,
    ledger: Any,
    sandbox: Sandbox,
    selected: Selected,
    iteration: int,
    push: Callable[[], None] = lambda: None,
    event_context: Mapping[str, Any] | None = None,
    extra_unit_dirs: Sequence[str] = (),
    family_glob: str | None = None,
    caches: tuple[CacheMount, ...] | None = None,
    ledger_rel: str | None = None,
) -> Workbench:
    """A fix unit's workbench (M1.3) works in its parent's run: `event_context` names the fix unit, `extra_unit_dirs`
    protects the parent's directory, `caches` reuses the parent's mounts and `ledger_rel` is the parent's run ledger
    (the one file of the run that every step leaves alone). `family_glob` is the namespace of fix units that no step
    may create or edit (`<changes>/<parent>-fix-*`; the unit's own by default): only the harness writes them."""
    cache = cache_root(app.environ, repo=app.repo)
    common = Path(git.run("rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip())
    repo_key = key_of_common_dir(common, app.environ)  # the key every per-unit directory carries (L4-SEC-034)
    unit_rel = ref.path.resolve().relative_to(worktree.resolve()).as_posix()
    ledger_rel = ledger_rel or ledger_path(ref.path, app.run_id).resolve().relative_to(worktree.resolve()).as_posix()
    home = Path(app.environ["HOME"]) if app.environ.get("HOME") else Path.home()
    return Workbench(
        cfg=cfg, ref=ref, provider=provider, worktree=worktree, git=git, ledger=ledger, sandbox=sandbox,
        selected=selected, host_env=app.environ, redactor=app.redactor, run_id=app.run_id, iteration=iteration,
        unit_cache=unit_dir(cache, repo_key, ref.id), cache_root=cache, repo_key=repo_key, out_dir=app.out_dir,
        home=home, git_common_dir=common,
        caches=caches if caches is not None else mount_caches(cfg.sandbox.caches, cache, ref.id, repo_key),
        protected=ProtectedSet(
            tuple(cfg.odd.forbidden_paths), unit_rel, ledger_rel, tuple(extra_unit_dirs),
            (family_glob or f"{unit_rel}-fix-*",),
        ),
        ledger_rel=ledger_rel, unit_rel=unit_rel, push=push, event_context=dict(event_context or {}),
    )  # fmt: skip
