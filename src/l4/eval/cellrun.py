"""Run one cell (L4-EVAL-007, plan D2): a fresh workspace, a scratch config, then the real `l4 run` as a child process.

The process is started through an injected `runner(argv, env, cwd, timeout)`, so every unit test is offline and fast;
the default is `subprocess_runner`. The scorecard reads the child's ledger and `outcome.json`, never its own timers
except for wall time. Nothing under the harness repository's `.l4` or the user's real cache is touched: the config is
passed with `--config` and `L4_CACHE` is a directory of the cell.
"""

import contextlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from l4.eval.cellconfig import Role, precheck, render_config
from l4.eval.replay import materialize_reference, reference_profile
from l4.eval.seeds import SeedSet
from l4.eval.workspace import Identity, make_workspace
from l4.redact import Redactor


@dataclass(frozen=True)
class Cell:
    role: Role
    profile: str
    unit: str
    k: int

    @property
    def key(self) -> str:
        return f"{self.role}|{self.profile}|{self.unit}|{self.k}"

    @property
    def dirname(self) -> str:
        safe = "".join(c if c.isalnum() or c in "-." else "-" for c in f"{self.role}-{self.profile}-{self.unit}")
        return f"{safe}-k{self.k}"


# The cell's private copy of the warmed uv cache. It must sit inside the cell's own `L4_CACHE`: `l4 run` refuses a
# cache path outside the runner cache (preflight, exit 2), and a shared writable cache would let one cell's agent
# change what the next cell installs.
CELL_UV_CACHE = "$L4_CACHE/eval-uv"
CELL_UV_DIR = "eval-uv"


def seed_uv_cache(shared: Path, dest: Path) -> None:
    """Copy the warmed shared uv cache into `dest`, the cell's own. uv links a wheel entry to its unpacked archive by
    an absolute symlink: a link whose target is inside the shared cache is copied as what it points at, any other
    link (out of the cache, dangling, or to its own ancestor) is dropped, so nothing of the copy leads back to the
    shared cache or out of it. A cold (absent) shared cache gives an empty copy: the offline setup then fails as
    `setup_offline_cache_cold` with its one-line fix."""
    if dest.exists():
        shutil.rmtree(dest)
    if not shared.is_dir():
        dest.mkdir(parents=True)
        return
    root = shared.resolve()

    def leaving(directory: str, names: list[str]) -> set[str]:
        here = Path(directory).resolve()
        dropped = set()
        for name in names:
            path = Path(directory) / name
            if not path.is_symlink():
                continue
            target = path.resolve()
            inside = target == root or root in target.parents
            if not inside or not target.exists() or target == here or target in here.parents:
                dropped.add(name)
        return dropped

    shutil.copytree(shared, dest, symlinks=False, ignore=leaving)


@dataclass(frozen=True)
class RunnerOutput:
    returncode: int
    output: str


Runner = Callable[[Sequence[str], Mapping[str, str], Path, float], RunnerOutput]


@dataclass
class CellRaw:
    returncode: int | None
    ledger_events: list[dict[str, Any]]
    outcome_json: dict[str, Any] | None
    log_text: str
    wall_s: float
    invalid: str | None = None  # a reason that makes the cell `invalid` before or while it ran (plan D5)
    report_text: str | None = None  # verification.md of the unit branch (the findings and their severities)
    setup_tail: str = ""  # the tail of the log of a failed setup gate: a cold offline cache shows there
    paths: dict[str, str] = field(default_factory=dict)


def subprocess_runner(argv: Sequence[str], env: Mapping[str, str], cwd: Path, timeout: float) -> RunnerOutput:
    """Run `argv` in its own process group; on a timeout kill the group and raise TimeoutExpired with its output."""
    proc = subprocess.Popen(
        list(argv), cwd=cwd, env=dict(env), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, start_new_session=True,
    )  # fmt: skip
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
        out, _ = proc.communicate()
        raise subprocess.TimeoutExpired(list(argv), timeout, output=out) from None
    return RunnerOutput(proc.returncode, out.decode("utf-8", errors="replace"))


def _git(origin: Path, *args: str) -> str | None:
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    done = subprocess.run(["git", *args], cwd=origin, env=env, capture_output=True, text=True, check=False)
    return done.stdout if done.returncode == 0 else None


def read_ledger(
    origin: Path, unit: str, *, framework: str = "openspec", branch_prefix: str = "l4/"
) -> list[dict[str, Any]]:
    """The unit's whole ledger as `origin` has it: the branch plus the lock ref's pending files, by (run_id, seq)."""
    branch = f"{branch_prefix}{framework}/{unit}"
    lock_ref = f"refs/l4/locks/{framework}/{unit}"
    sources: list[tuple[str, str]] = []  # (ref, path)
    for ref, directory in ((branch, f"openspec/changes/{unit}/.l4/ledger/"), (lock_ref, "ledger-pending/")):
        listing = _git(origin, "ls-tree", "--name-only", ref, directory)
        sources += [(ref, name) for name in (listing or "").split("\n") if name]
    events: dict[tuple[str, int], dict[str, Any]] = {}
    for ref, name in sources:
        text = _git(origin, "show", f"{ref}:{name}") or ""
        for line in text.splitlines():
            with contextlib.suppress(ValueError):
                event = json.loads(line)
                events.setdefault((str(event.get("run_id")), int(event.get("seq", 0))), event)
    return sorted(events.values(), key=lambda e: (str(e.get("ts")), str(e.get("run_id")), int(e.get("seq", 0))))


def read_unit_file(
    origin: Path, unit: str, name: str, *, framework: str = "openspec", branch_prefix: str = "l4/"
) -> str | None:
    return _git(origin, "show", f"{branch_prefix}{framework}/{unit}:openspec/changes/{unit}/{name}")


def _setup_tail(repo: Path, events: Sequence[dict[str, Any]], limit: int = 2000) -> str:
    failed = [
        e for e in events if e.get("type") == "gate.finished" and e.get("name") == "setup" and e.get("status") == "fail"
    ]
    if not failed or not failed[-1].get("log"):
        return ""
    path = (repo / str(failed[-1]["log"])).resolve()
    if repo.resolve() not in path.parents:
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")[-limit:]
    except OSError:
        return ""


def read_local_ledger(cache: Path, unit: str, *, framework: str = "openspec") -> list[dict[str, Any]]:
    """The ledger files in the unit's worktree under the cell's cache: a run parked before its first push (a 429 on
    the first step) leaves its events there and nowhere else."""
    # `worktrees/<repository key>/<framework>/<unit>` (L4-WTR-001): the cell's cache holds one repository's key, so
    # the key is matched, not recomputed
    pattern = f"worktrees/*/{framework}/{unit}/openspec/changes/{unit}/.l4/ledger/*.jsonl"
    events: list[dict[str, Any]] = []
    for path in sorted(cache.glob(pattern)):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            with contextlib.suppress(ValueError):
                events.append(json.loads(line))
    return events


def merge_ledgers(*ledgers: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[tuple[str, int], dict[str, Any]] = {}
    for ledger in ledgers:
        for event in ledger:
            merged.setdefault((str(event.get("run_id")), int(event.get("seq", 0))), event)
    return sorted(merged.values(), key=lambda e: (str(e.get("ts")), str(e.get("run_id")), int(e.get("seq", 0))))


def _read_outcome(repo: Path) -> dict[str, Any] | None:
    try:
        doc = json.loads((repo / ".l4-out" / "outcome.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def run_cell(
    cell: Cell, *, seeds: SeedSet, base_cfg: Mapping[str, Any], cell_dir: Path, ref_judge: str | None,
    runner: Runner, environ: Mapping[str, str], timeout_s: float, redactor: Redactor,
    identity: Identity | None = None, uv_cache: str | None = None, python: str | None = None,
) -> CellRaw:  # fmt: skip
    unit = seeds.unit(cell.unit)
    started = time.monotonic()
    ref_impl: dict[str, Any] | None = None
    if cell.role == "judge":
        ref_impl = reference_profile(cell_dir / "reference", python)
    reason = precheck(base_cfg, cell.role, cell.profile, ref_judge=ref_judge, ref_impl=ref_impl)
    if reason is not None:
        return CellRaw(None, [], None, "", 0.0, invalid=reason)
    workspace = make_workspace(seeds, unit, cell_dir / "ws", identity=identity)
    if cell.role == "judge":
        materialize_reference(unit, cell_dir / "reference")
    cache = cell_dir / "cache"
    cache.mkdir(parents=True, exist_ok=True)
    if uv_cache is not None:  # the warmed shared cache: the cell gets a private copy inside its own L4_CACHE
        seed_uv_cache(Path(uv_cache), cache / CELL_UV_DIR)
    cfg = render_config(
        base_cfg, cell.role, cell.profile, ref_judge=ref_judge, ref_impl=ref_impl,
        uv_cache=CELL_UV_CACHE if uv_cache is not None else None,
    )  # fmt: skip
    cfg_path = cell_dir / "cfg.yaml"
    cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=True), encoding="utf-8")
    env = {**environ, "L4_CACHE": str(cache)}
    argv = [
        python or sys.executable, "-m", "l4", "run", "--config", str(cfg_path), "--unit", f"openspec:{unit.id}",
        "--repo", str(workspace.repo),
    ]  # fmt: skip
    invalid: str | None = None
    returncode: int | None
    try:
        out = runner(argv, env, workspace.repo, timeout_s)
        returncode, text = out.returncode, out.output
    except subprocess.TimeoutExpired as exc:
        returncode, invalid = None, "cell_timeout"
        raw = exc.output if exc.output is not None else b""
        text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
    wall = time.monotonic() - started
    events = merge_ledgers(read_ledger(workspace.origin, unit.id), read_local_ledger(cache, unit.id))
    report = read_unit_file(workspace.origin, unit.id, "verification.md")
    return CellRaw(
        returncode=returncode,
        ledger_events=events,
        report_text=redactor.redact_text(report) if report else None,
        setup_tail=redactor.redact_text(_setup_tail(workspace.repo, events)),
        outcome_json=_read_outcome(workspace.repo),
        log_text=redactor.redact_text(text),
        wall_s=wall,
        invalid=invalid,
        paths={"workspace": str(workspace.repo), "origin": str(workspace.origin)},
    )
