"""`l4 eval` (L4-EVAL-014 to 019): the matrix of cells, run strictly one at a time, and the files of a run.

No network from the harness: building the matrix, rendering configs, scoring, writing the scorecard and comparing open
no socket. The only network in a real run is the agent CLIs' own (L4-EVAL-018).
"""

import hashlib
import json
import os
import shlex
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import Any

import click
import yaml

import l4
from l4.config.defaults import cache_root
from l4.config.schema import ValueFree, duration_seconds
from l4.context import AppContext
from l4.eval.cellconfig import KEPT_SECTIONS
from l4.eval.cellresult import REFERENCE_UNAVAILABLE, finish_cell
from l4.eval.cellrun import Cell, Runner, run_cell, subprocess_runner
from l4.eval.compare import NOTHING_COMPARED, compare, find_baseline
from l4.eval.env import capture_env, cli_version, tool_versions
from l4.eval.render import render_comparison, render_markdown
from l4.eval.scorecard import build_scorecard, canonical_json, cell_result
from l4.eval.seeds import SeedError, SeedSet, load_seed_set, seed_set_sha256
from l4.exitcodes import ExitCode, L4Exit
from l4.redact import Redactor
from l4.schemacheck import validate


class RunnerBusy(Exception):
    pass


def _usage(message: str) -> L4Exit:
    return L4Exit(ExitCode.USAGE_ERROR, message)


POLL_S = 20.0  # how often a busy --idle-check is asked again


def default_idle(argv: Sequence[str]) -> int:
    """Run the hook without a shell; its output is dropped, only the exit code is read (0: quiet)."""
    try:
        done = subprocess.run(
            list(argv), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120,
            check=False,
        )  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        return 127
    return done.returncode


def eval_uv_cache(environ: Mapping[str, str]) -> Path:
    """The uv cache every cell shares: `<L4_CACHE>/eval/uv`, warmed by `l4 eval --warm-cache`."""
    return cache_root(environ) / "eval" / "uv"


def default_warm(project: Path, env: dict[str, str]) -> int:
    """`uv sync --frozen` in a scratch copy of the base project: the one eval step that reaches an index."""
    try:
        return subprocess.run(["uv", "sync", "--frozen"], cwd=project, env=env, check=False).returncode
    except OSError:
        return 127


@dataclass
class Deps:
    """What a test replaces: the child process, the clock and the waits."""

    runner: Runner = subprocess_runner
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic
    idle: Callable[[Sequence[str]], int] = default_idle
    warm: Callable[[Path, dict[str, str]], int] = default_warm
    version_of: Callable[[str], str | None] = cli_version
    tools: Callable[[Mapping[str, str]], dict[str, str | None]] = tool_versions
    harness_dir: Path = field(default_factory=lambda: Path(l4.__file__).resolve().parents[2])


@dataclass(frozen=True)
class Options:
    impl: tuple[str, ...] = ()
    judge: tuple[str, ...] = ()
    ref_judge: str | None = None
    units: tuple[str, ...] = ()
    k: int = 1
    out: Path | None = None
    cell_timeout: str = "50m"
    runner: bool = False
    dry_run: bool = False
    resume: bool = False
    idle_check: str | None = None
    idle_wait: str = "30m"
    warm_cache: bool = False
    seeds: Path | None = None
    compare: Path | None = None
    new: Path | None = None
    baseline_dir: Path | None = None
    max_drop: float = 0.20
    allow_seed_change: bool = False
    require_all: bool = False
    as_json: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


def default_seeds_dir() -> Path:
    return Path(l4.__file__).resolve().parents[2] / "tests" / "eval" / "seeds"


def _seconds(text: str, flag: str) -> float:
    try:
        return float(duration_seconds(text))
    except ValueFree:
        raise _usage(f"{flag}: expected a duration such as 50m (digits and one of s, m, h)") from None


def _load_seeds(path: Path | None) -> SeedSet:
    directory = path or default_seeds_dir()
    try:
        return load_seed_set(directory)
    except SeedError as exc:
        raise _usage(f"seed set: {exc} (pass --seeds <dir>)") from None


def _base_config(app: AppContext) -> dict[str, Any]:
    if app.config_path is None:
        raise _usage("eval needs --config <profiles.yaml>: the file that defines the profiles to measure")
    try:
        loaded = yaml.safe_load(app.config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise _usage(f"cannot read --config {app.config_path.name}: {type(exc).__name__}") from None
    if not isinstance(loaded, dict) or not isinstance(loaded.get("profiles"), dict):
        raise _usage("--config must be a YAML mapping with a `profiles` mapping")
    return loaded


def build_matrix(opts: Options, seeds: SeedSet) -> list[Cell]:
    """Implementer cells (profile x unit x k; judge-only units are left out), then judge cells (profile x unit x k)."""
    units = [u for u in seeds.units if not opts.units or u.id in opts.units]
    cells = [
        Cell("implementer", profile, unit.id, k)
        for profile in opts.impl for unit in units if not unit.judge_only for k in range(opts.k)
    ]  # fmt: skip
    cells += [Cell("judge", profile, unit.id, k) for profile in opts.judge for unit in units for k in range(opts.k)]
    return cells


def _validate(opts: Options, app: AppContext, seeds: SeedSet) -> dict[str, Any]:
    if not opts.impl and not opts.judge:
        raise _usage("give at least one --impl or --judge profile to measure")
    if opts.impl and not opts.ref_judge:
        raise _usage("--ref-judge is required with --impl: an implementer cell ends in a verdict by a fixed judge")
    known = {u.id for u in seeds.units}
    for unit in opts.units:
        if unit not in known:
            raise _usage(f"unknown unit {unit!r} (known: {', '.join(sorted(known))})")
    base = _base_config(app)
    for name in (*opts.impl, *opts.judge, *([opts.ref_judge] if opts.ref_judge else [])):
        if name not in base["profiles"]:
            raise _usage(f"profile {name!r} is not in --config")
    _seconds(opts.cell_timeout, "--cell-timeout")
    _seconds(opts.idle_wait, "--idle-wait")
    if opts.idle_check is not None and not shlex.split(opts.idle_check):
        raise _usage("--idle-check is empty: give the command to run")
    if opts.k < 1:
        raise _usage("--k must be at least 1")
    return base


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def _write_scorecard(
    out: Path, results: Sequence[dict[str, Any]], env: dict[str, Any], seeds: SeedSet, complete: bool
) -> None:
    unit_ids = [u.id for u in seeds.units]
    card = build_scorecard(results, env, {"sha256": env["seed_set_sha256"], "units": unit_ids}, complete=complete)
    _write_atomic(out / "scorecard.json", canonical_json(card))
    _write_atomic(out / "scorecard.md", render_markdown(card))


BLOCKING = ("rate_limited", "endpoint_unavailable")  # an invalid reason that stops the profile for this run
MEASURED = ("pass", "fail")  # what `--resume` keeps; an `invalid` cell was not measured and runs again
ENV_KEY = "env_sha256"  # in `result.json` only: the environment a cell was measured in


def env_sha256(env: Mapping[str, Any]) -> str:
    """The environment a cell is measured in, without the run's start time and `k` (a cell does not depend on how
    many repetitions the run has): harness commit, templates, CLI versions, profiles, seeds, timeout, machine."""
    body = {key: value for key, value in env.items() if key not in ("started_at", "k")}
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def _load_done(out: Path, seed_hash: str, env_hash: str) -> dict[str, dict[str, Any]]:
    """The cells already measured in `out` for this seed set and this environment, by cell key. An unreadable or
    foreign result is not done; nor is an `invalid` one (a 429, a busy runner, a harness error: nothing was measured),
    nor one measured in another environment (a reused cell would sit under an environment record that is not its)."""
    done: dict[str, dict[str, Any]] = {}
    for path in sorted((out / "cells").glob("*/result.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (
            isinstance(doc, dict) and doc.get("seed_set_sha256") == seed_hash and doc.get(ENV_KEY) == env_hash
            and doc.get("status") in MEASURED and isinstance(doc.get("cell_key"), str)
        ):  # fmt: skip
            done[doc["cell_key"]] = {key: value for key, value in doc.items() if key != ENV_KEY}
    return done


def _store(cell_dir: Path, result: dict[str, Any], seed_hash: str, env_hash: str) -> dict[str, Any]:
    result = {**result, "seed_set_sha256": seed_hash}
    _write_text(cell_dir / "result.json", json.dumps({**result, ENV_KEY: env_hash}, sort_keys=True, indent=1) + "\n")
    return result


def _wait_for_quiet(opts: Options, deps: Deps) -> bool:
    """True when the hook says quiet (exit 0), within `--idle-wait`; the cell does not start otherwise."""
    if opts.idle_check is None:
        return True
    argv = shlex.split(opts.idle_check)
    deadline = deps.clock() + _seconds(opts.idle_wait, "--idle-wait")
    while deps.idle(argv) != 0:
        if deps.clock() >= deadline:
            return False
        deps.sleep(POLL_S)
    return True


def _run_cells(
    opts: Options,
    app: AppContext,
    seeds: SeedSet,
    base: dict[str, Any],
    cells: Sequence[Cell],
    deps: Deps,
    env: dict[str, Any],
) -> list[dict[str, Any]]:
    assert opts.out is not None
    redactor: Redactor = app.redactor
    timeout = _seconds(opts.cell_timeout, "--cell-timeout")
    seed_hash = seed_set_sha256(seeds.root)
    env_hash = env_sha256(env)
    done = _load_done(opts.out, seed_hash, env_hash) if opts.resume else {}
    uv_cache = eval_uv_cache(app.environ)  # read only: each cell copies it into its own cache
    results: list[dict[str, Any]] = []
    blocked: set[str] = set()
    reference_down: set[str] = set()  # cell roles whose reference profile was unavailable
    for cell in cells:
        if cell.key in done:  # measured before, in this environment
            results.append(done[cell.key])
            _write_scorecard(opts.out, results, env, seeds, complete=False)
            continue
        cell_dir = opts.out / "cells" / cell.dirname
        shutil.rmtree(cell_dir, ignore_errors=True)
        cell_dir.mkdir(parents=True, exist_ok=True)
        if cell.role in reference_down:  # the fixed judge (or the replay) of this role cannot run: nothing to measure
            skipped = cell_result(
                {"role": cell.role, "profile": cell.profile, "unit": cell.unit, "k": cell.k, "status": "invalid",
                 "invalid_reason": "skipped_reference_unavailable"}
            )  # fmt: skip
            results.append(_store(cell_dir, skipped, seed_hash, env_hash))
            _write_scorecard(opts.out, results, env, seeds, complete=False)
            continue
        if cell.profile not in blocked and not _wait_for_quiet(opts, deps):
            busy = cell_result(
                {"role": cell.role, "profile": cell.profile, "unit": cell.unit, "k": cell.k, "status": "invalid",
                 "invalid_reason": "runner_busy"}
            )  # fmt: skip
            results.append(_store(cell_dir, busy, seed_hash, env_hash))
            _write_scorecard(opts.out, results, env, seeds, complete=False)
            raise RunnerBusy
        if cell.profile in blocked:
            skipped = cell_result(
                {"role": cell.role, "profile": cell.profile, "unit": cell.unit, "k": cell.k, "status": "invalid",
                 "invalid_reason": "skipped_after_rate_limit"}
            )  # fmt: skip
            results.append(_store(cell_dir, skipped, seed_hash, env_hash))
            _write_scorecard(opts.out, results, env, seeds, complete=False)
            continue
        raw = run_cell(
            cell, seeds=seeds, base_cfg=base, cell_dir=cell_dir, ref_judge=opts.ref_judge, runner=deps.runner,
            environ=app.environ, timeout_s=timeout, redactor=redactor, uv_cache=str(uv_cache),
        )  # fmt: skip
        free = bool((base["profiles"][cell.profile].get("options") or {}).get("free"))
        result = finish_cell(cell, raw, seeds.unit(cell.unit).expected, free=free, redactor=redactor)
        _write_text(cell_dir / "run.log", raw.log_text)
        _write_text(cell_dir / "ledger.jsonl", "".join(json.dumps(e, sort_keys=True) + "\n" for e in raw.ledger_events))
        results.append(_store(cell_dir, result, seed_hash, env_hash))
        if result["invalid_reason"] in BLOCKING:
            blocked.add(cell.profile)
        if result["invalid_reason"] == REFERENCE_UNAVAILABLE:  # the reference, not the profile: stop the role's cells
            reference_down.add(cell.role)
        for scratch in ("ws", "cache", "reference"):  # nothing that holds a raw prompt stays in the run directory
            shutil.rmtree(cell_dir / scratch, ignore_errors=True)
        _write_scorecard(opts.out, results, env, seeds, complete=False)
    _write_scorecard(opts.out, results, env, seeds, complete=True)
    return results


def _warm_cache(opts: Options, app: AppContext, seeds: SeedSet, deps: Deps) -> ExitCode:
    if opts.impl or opts.judge:
        raise _usage("--warm-cache runs alone: it is refused together with --impl or --judge")
    cache = eval_uv_cache(app.environ)
    cache.mkdir(parents=True, exist_ok=True)
    env = {k: v for k, v in app.environ.items() if k in ("PATH", "HOME", "UV_INDEX_URL", "UV_EXTRA_INDEX_URL")}
    env["UV_CACHE_DIR"] = str(cache)
    with tempfile.TemporaryDirectory(prefix="l4-eval-warm-") as scratch:
        project = Path(scratch) / "base"
        shutil.copytree(seeds.base, project, ignore=shutil.ignore_patterns("__pycache__", ".venv", ".pytest_cache"))
        code = deps.warm(project, env)
    if code != 0:
        raise L4Exit(ExitCode.DOCTOR_FAILED, f"uv sync --frozen exited {code}: the eval cache is not warm")
    click.echo(f"eval: uv cache warmed at {cache}")
    return ExitCode.OK


def load_scorecard(path: Path, label: str) -> dict[str, Any]:
    """A scorecard file, checked against the schema; any problem is a usage error (exit 2) that names the file."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except OSError:
        raise _usage(f"{label} scorecard: cannot read {path.name}") from None
    except ValueError:
        raise _usage(f"{label} scorecard: {path.name} is not JSON") from None
    schema = json.loads(resources.files("l4.eval").joinpath("scorecard.schema.json").read_text(encoding="utf-8"))
    problems = validate(doc, schema)
    if problems:
        raise _usage(f"{label} scorecard: {path.name} is not an l4/eval-scorecard@1 ({problems[0]})")
    return doc


NO_BASELINE = "no baseline for this seed set: run `l4 eval ... --out <dir>` and commit the scorecard"


def _compare_step(opts: Options, old_path: Path | None, new_path: Path, out_dir: Path | None) -> ExitCode:
    new = load_scorecard(new_path, "new")
    if old_path is None:  # --baseline-dir: the newest committed scorecard of the same seed set
        assert opts.baseline_dir is not None
        before = str((new.get("env") or {}).get("started_at") or "") or None
        old_path = find_baseline(opts.baseline_dir, new["seeds"]["sha256"], exclude=new_path, before=before)
        if old_path is None:
            raise _usage(NO_BASELINE)
    old = load_scorecard(old_path, "old")
    result = compare(old, new, opts.max_drop, allow_seed_change=opts.allow_seed_change, require_all=opts.require_all)
    vacuous = not result.failed and not result.seed_changed and result.compared == 0
    code = ExitCode.REGRESSION if result.failed else ExitCode.USAGE_ERROR if vacuous else ExitCode.OK
    markdown = render_comparison(result)
    if out_dir is not None:
        _write_atomic(out_dir / "comparison.md", markdown)
    click.echo(json.dumps(result.as_dict(int(code)), indent=1, sort_keys=True) if opts.as_json else markdown, nl=False)
    if vacuous:  # the report is printed, but a gate with no evidence never passes
        raise _usage(NOTHING_COMPARED)
    return code


def run_eval(app: AppContext, *, deps: Deps | None = None, **options: Any) -> ExitCode:
    known = {f for f in Options.__dataclass_fields__ if f != "extra"}
    opts = Options(**{k: v for k, v in options.items() if k in known})
    deps = deps or Deps()
    comparing = opts.compare is not None or opts.baseline_dir is not None
    if opts.new is not None and not comparing:
        raise _usage("--new needs --compare or --baseline-dir: the baseline to judge the new scorecard against")
    if comparing and not 0.0 <= opts.max_drop <= 1.0:  # NaN fails too; a negative drop would fail equal scorecards
        raise _usage("--max-drop must be a number from 0 to 1 (a drop of a pass rate)")
    if comparing and opts.new is not None:  # two files: no agent runs, no seed set needed
        return _compare_step(opts, opts.compare, opts.new, None)
    seeds = _load_seeds(opts.seeds)
    if opts.warm_cache:
        return _warm_cache(opts, app, seeds, deps)
    base = _validate(opts, app, seeds)
    cells = build_matrix(opts, seeds)
    if opts.dry_run:
        for cell in cells:
            click.echo(f"cell {cell.role} {cell.profile} {cell.unit} k{cell.k}")
        return ExitCode.OK
    if opts.out is None:
        raise _usage("--out <dir> is required for a run")
    used = [*opts.impl, *opts.judge, *([opts.ref_judge] if opts.ref_judge else [])]
    env = capture_env(
        harness_dir=deps.harness_dir, profiles=base["profiles"], used=used, seed_set_sha256=seed_set_sha256(seeds.root),
        k=opts.k, cell_timeout_s=_seconds(opts.cell_timeout, "--cell-timeout"), runner=opts.runner,
        redactor=app.redactor, version_of=deps.version_of, tools=deps.tools(app.environ),
        kept={section: base[section] for section in KEPT_SECTIONS if isinstance(base.get(section), Mapping)},
    )  # fmt: skip
    try:
        _run_cells(opts, app, seeds, base, cells, deps, env)
    except RunnerBusy:  # the stop is exit 12: waiting for capacity
        click.echo("eval: the runner stayed busy past --idle-wait; stopped (resume with --resume)", err=True)
        return ExitCode.WAITING_CAPACITY
    if comparing:
        return _compare_step(opts, opts.compare, opts.out / "scorecard.json", opts.out)
    return ExitCode.OK
