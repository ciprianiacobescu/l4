"""`l4 simulate` (SPEC L4-SIM-002, M14-G4): the real orchestrator against scripted agents, a local forge and a
throw-away git remote.

A scenario runs `run_command` as `l4 run` does, up to `max_runs` times, with the one change that the agent adapter
is a `ProfileRouter` over the scripted profiles. Config, lease, worktree, gates, ledger, verifier and the archive
hooks are the real ones; the sandbox is off (`mode: none`, the scenario's accepted risk), the forge is `LocalForge`,
and `openspec validate` is answered from the files (`fake_openspec_cli`). A scripted human edits the remote between
runs. What happened is read back from the remote the way `l4 status` reads it: the unit branch's ledger plus the
pending ledger of its lock ref.
M1: simulation-harness 2.12-2.14 (`--with-repo-config`, the `release` gate, the process spy).
"""

import hashlib
import json
import logging
import os
import shlex
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

import click
import yaml

from l4.agents.base import LimitSignal, ProbeResult, ProbeStep
from l4.config.loader import load_config
from l4.config.redaction import redactor_for_config
from l4.context import AppContext
from l4.exitcodes import ExitCode, L4Exit, classify_exception
from l4.orchestrator import run_command
from l4.outcome import CommandResult, new_run_id
from l4.redact import Redactor
from l4.safepath import safe_path
from l4.sim.builtin.manifest import BUILTIN, scenario_text
from l4.sim.expect import Observed, compare_expect, format_mismatches, normalize_events
from l4.sim.fakes import PROFILE_OPTION, ProfileRouter, ScriptedAgent, ScriptedS1, fake_openspec_cli
from l4.sim.remote import SimRepo
from l4.sim.replay import ReplayRouter
from l4.sim.scenarios import ProbeScript, Scenario, ScenarioError, load_scenario, load_scenario_file
from l4.specs.providers import providers_for
from l4.state.ledger import LedgerRead, parse_ledger_files
from l4.state.pending import merge_ledgers, read_pending
from l4.vcs.git import Git
from l4.vcs.names import lock_ref, unit_branch
from l4.vcs.tree import regular_blobs

log = logging.getLogger("l4.sim")

SCHEMA = "l4/simulate@1"
IMPLEMENTER_VENDOR = "sim-implementer"
JUDGE_VENDOR = "sim-judge"  # a judge must not share the implementer's vendor (L4-VER independence)
CONFIG_FILE = "sim-config.yaml"
SCENARIO_FILE = "scenario.json"  # for the child process of a killing scenario
CHILD_TIMEOUT_S = 180
S1_PROFILE = "s1"  # the profile behind `scenario.s1`; its role is `s1_judge`
Status = Literal["pass", "fail", "pending"]


@dataclass(frozen=True)
class ScenarioResult:
    name: str
    status: Status
    exit_code: int | None = None
    final_phase: str | None = None
    report: str = ""  # what differed (fail) or who owns it (pending)
    events: tuple[dict[str, Any], ...] = ()  # normalized: two runs of a scenario produce equal ones
    owner: str | None = None
    driver: str = "orchestrator"  # always: the skeleton driver of simulation-harness 1.8 is not built


# --- configuration ------------------------------------------------------------------------------------------------


def _merged(base: dict[str, Any], over: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in over.items():
        out[key] = _merged(out[key], value) if isinstance(out.get(key), dict) and isinstance(value, Mapping) else value
    return out


def sim_config(scenario: Scenario) -> dict[str, Any]:
    """The scenario's `.l4/config.yaml`: one `fake` profile per scripted profile, the real gate of the fixture, and
    what the scenario's own `config:` says on top. Roles default to the implementer profiles and the judge profiles
    that no role named in `config` already uses."""
    profiles: dict[str, Any] = {
        **{n: _profile(n, IMPLEMENTER_VENDOR) for n in scenario.profiles},
        **{n: _replay_profile(n) if j.replay else _profile(n, JUDGE_VENDOR) for n, j in scenario.judges.items()},
        **({S1_PROFILE: _profile(S1_PROFILE, JUDGE_VENDOR)} if scenario.s1 else {}),
    }
    named = {p for chain in scenario.config.get("roles", {}).values() for p in chain}
    roles: dict[str, list[str]] = {
        "implementer": list(scenario.profiles),
        "judges": [n for n in scenario.judges if n not in named],
    }
    if scenario.s1:
        roles["s1_judge"] = [S1_PROFILE]
    base: dict[str, Any] = {
        "version": 1,
        "sandbox": {"mode": "none", "allow_none": True},
        "forge": {"type": "local", "base_branch": "main"},
        "ci": {"platform": "local"},
        "profiles": profiles,
        "roles": roles,
        "gates": {"setup": [], "test": {"command": f"{shlex.quote(sys.executable)} tests/run_junit.py"}},
    }
    return _merged(base, scenario.config)


def _profile(name: str, vendor: str) -> dict[str, Any]:
    return {"adapter": "fake", "vendor": vendor, "options": {PROFILE_OPTION: name}}


def _replay_profile(name: str) -> dict[str, Any]:
    """A replayed Kiro judge has no model and no vendor: it runs `--model auto` and is routed (kiro-judge D10)."""
    return {"adapter": "kiro-cli", "options": {PROFILE_OPTION: name}}


def replay_router(scenario: Scenario) -> ReplayRouter | None:
    streams = {n: j.replay.stream for n, j in scenario.judges.items() if j.replay}
    return ReplayRouter(streams) if streams else None


def sim_adapters(scenario: Scenario, run_number: int | None = None) -> dict[str, Any]:
    """The adapters `run_command` gets: the scripted `fake` router, and `kiro-cli` when a judge is replayed."""
    adapters: dict[str, Any] = {"fake": ProfileRouter(scripted_agents(scenario, run_number))}
    if (replay := replay_router(scenario)) is not None:
        adapters["kiro-cli"] = replay
    return adapters


def _scripted_probes(profile: str, probe: ProbeScript | None) -> dict[ProbeStep, ProbeResult]:
    """A scripted `quota` is an exhausted window, in the shape of the real quota probe (`evaluate_windows`)."""
    if probe is None or probe.quota is None:
        return {}
    used, minutes = float(probe.quota["used_percent"]), probe.quota.get("window_minutes")
    window = {"name": f"{minutes}m" if minutes else "window", "used_percent": used, "window_minutes": minutes}
    reason = f"{window['name']} {used:g}% used, {max(100 - used, 0):g}% remaining"
    limit = LimitSignal(profile, None, "usage_limit", None, "sim.quota", "")  # M1.2 widens it with the window
    detail = {"windows": [window], "quota_used_percent": used, "quota_window": window["name"]}
    return {"quota": ProbeResult("quota", False, detail, reason=reason, limit=limit)}


def scripted_agents(scenario: Scenario, run_number: int | None = None) -> dict[str, ScriptedAgent]:
    """`run_number` is given only by the child process of a killing scenario (`l4.sim.child`)."""
    agents: dict[str, ScriptedAgent] = {}
    for name, script in scenario.profiles.items():
        probes = _scripted_probes(name, script.probe)
        agents[name] = ScriptedAgent(script.steps, run_number=run_number, probes=probes)
    for name, judge in scenario.judges.items():
        if judge.replay is None:
            agents[name] = ScriptedAgent(verdict=judge.verdict)
    if scenario.s1:  # the stand-in S1 judge sides with the clarifier when the scripted probability is at least a half
        agents[S1_PROFILE] = ScriptedS1(scenario.s1.default_p >= 0.5)
    return agents


# --- reading back what happened -----------------------------------------------------------------------------------


def _events(remote: Git, unit_id: str, unit_rel: str, prefix: str) -> list[dict[str, Any]]:
    """The ledger as the fold sees it: the unit branch of the remote, plus the pending files of its lock ref."""
    ref = f"refs/heads/{unit_branch(unit_id, prefix)}"
    files: dict[str, bytes] = {}
    if remote.rev_parse(ref) is not None:
        for blob in regular_blobs(remote, ref, f"{unit_rel}/.l4/ledger/", 1 << 22):
            if blob.path.endswith(".jsonl"):
                files[blob.path.rsplit("/", 1)[-1]] = remote.run_bytes("cat-file", "blob", blob.oid)
    read: LedgerRead = merge_ledgers(parse_ledger_files(files), read_pending(remote, lock_ref(unit_id)))
    return [
        {"run_id": e.run_id, "seq": e.seq, "type": e.type, "unit": e.unit, **e.data}
        for e in sorted(read.events, key=lambda e: (e.ts, e.run_id, e.seq))
    ]


def _trailers(remote: Git, unit_id: str, prefix: str, base: str) -> dict[str, list[str]]:
    ref = f"refs/heads/{unit_branch(unit_id, prefix)}"
    found: dict[str, list[str]] = {}
    if remote.rev_parse(ref) is None:
        return found
    log_text = remote.run("log", "--format=%(trailers:only,unfold)%x1e", f"refs/heads/{base}..{ref}").stdout
    for line in log_text.replace("\x1e", "\n").splitlines():
        key, sep, value = line.partition(": ")
        if sep:
            found.setdefault(key, []).append(value)
    return found


def _final_phase(events: Sequence[Mapping[str, Any]]) -> str | None:
    phases = [e["to"] for e in events if e["type"] == "phase.changed"]
    return phases[-1] if phases else None


# --- one scenario -------------------------------------------------------------------------------------------------


def sim_environment(root: Path) -> dict[str, str]:
    return {
        "PATH": safe_path(os.environ),
        "HOME": str(root),
        "L4_HOME": str(root / "home"),
        "L4_CACHE": str(root / "cache"),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
    }


def sim_app(root: Path) -> AppContext:
    """The `l4 run` context of a scenario world: the clone, the scenario's config, and an environment that is the
    world's own."""
    return AppContext(
        (root / "clone").resolve(), root / CONFIG_FILE, "human", 0, new_run_id(), sim_environment(root), Redactor({})
    )


def run_scenario(scenario: Scenario, *, keep: bool = False, root: Path | None = None) -> ScenarioResult:
    """Run one scenario in its own temporary world and judge it. An exception inside the run (a scripted agent that
    has no step for what it was asked, a refusal) is a failed scenario that says why, never a crash of the command."""
    sim = SimRepo.create(scenario.fixture, root=root, keep=keep)
    try:
        return _drive(scenario, sim)
    finally:
        sim.cleanup()
        if keep:
            click.echo(f"kept {sim.root}", err=True)


def _drive(scenario: Scenario, sim: SimRepo) -> ScenarioResult:
    root = sim.root.resolve()
    config_path = root / CONFIG_FILE
    config_path.write_text(yaml.safe_dump(sim_config(scenario)), encoding="utf-8")
    environ = sim_environment(root)
    app = sim_app(root)
    code: int | None = None
    failure = ""
    reasons: list[str] = []  # why units stopped, from `outcome.json`'s `exit_reason` (a unit that raised is caught)
    if scenario.kills:
        (root / SCENARIO_FILE).write_text(scenario.model_dump_json(), encoding="utf-8")
    adapters = sim_adapters(scenario)
    with fake_openspec_cli():
        for number in range(scenario.max_runs):
            if number and number - 1 < len(scenario.between_runs):
                human = scenario.between_runs[number - 1]
                sim.human_commit(human.write, human.message, human.branch)
                sim.git.fetch("origin")  # a CI job refreshes its refs first (`l4.vcs.refresh`); a local run is stale
            try:
                if scenario.kills:
                    code = _run_in_child(root, number + 1)
                else:
                    result = run_command(replace(app, run_id=new_run_id()), adapters=adapters)
                    code = int(result.code)
                    reasons += [u.exit_reason for u in result.units if u.exit_reason and code != 0]
            except Exception as exc:  # noqa: BLE001 - a scenario that blows up is a failed scenario with the reason
                code, message = classify_exception(exc)
                failure = f"run {number + 1} raised {type(exc).__name__}: {message}"
                break
    cfg = load_config(app.repo, config_path=config_path)
    app.redactor.adopt(redactor_for_config(cfg, environ))
    remote = Git(sim.remote, environ=environ)
    events: list[dict[str, Any]] = []
    trailers: dict[str, list[str]] = {}
    for unit_id, unit_rel in _units(app, cfg.forge.branch_prefix):
        events += _events(remote, unit_id, unit_rel, cfg.forge.branch_prefix)
        for key, values in _trailers(remote, unit_id, cfg.forge.branch_prefix, cfg.forge.base_branch).items():
            trailers.setdefault(key, []).extend(values)
    exit_code = code if code is not None else int(ExitCode.INTERNAL_ERROR)
    observed = Observed(exit_code, _final_phase(events), events, trailers)
    mismatches = compare_expect(scenario.expect, observed)
    report = format_mismatches(mismatches, events)
    if failure:
        report = f"{failure}\n{report}".strip()
    if reasons and mismatches:  # a unit that raised no longer ends the command: its reason is in the outcome
        report = f"{report}\nunit exit reason: {'; '.join(dict.fromkeys(reasons))}".strip()
    normalized = tuple(normalize_events(events, [str(root), str(sim.root)]))
    return ScenarioResult(
        scenario.name, "fail" if mismatches or failure else "pass", observed.exit_code, observed.final_phase,
        app.redactor.redact_text(report), normalized,
    )  # fmt: skip


def _run_in_child(root: Path, number: int) -> int:
    """`l4 run` of run number `number` in its own process, which a scripted step may SIGKILL (`l4.sim.child`). The exit
    code is the child's, or `128 + signal` when it died of one."""
    done = subprocess.run(
        [sys.executable, "-m", "l4.sim.child", str(root), str(number)],
        env=sim_environment(root), cwd=root, capture_output=True, text=True, timeout=CHILD_TIMEOUT_S, check=False,
    )  # fmt: skip
    if done.returncode < 0:
        log.info("run %d was killed by signal %d", number, -done.returncode)
        return 128 - done.returncode
    if done.stderr.strip():
        log.info("run %d: %s", number, done.stderr.strip()[-2000:])
    return done.returncode


def _units(app: AppContext, prefix: str) -> list[tuple[str, str]]:
    """(unit id, unit directory relative to the repository) of every unit in the clone's seed."""
    cfg = load_config(app.repo, config_path=app.config_path)
    found = []
    for provider in providers_for(cfg, app.repo, app.environ):
        for ref in provider.list_units():
            found.append((ref.id, provider.unit_dir(ref).resolve().relative_to(app.repo.resolve()).as_posix()))
    return sorted(found)


# --- the command ---------------------------------------------------------------------------------------------------


def _load(name: str) -> tuple[Scenario | None, str | None]:
    """A built-in name or the path of a scenario file: (scenario, None), or (None, owner) for a pending built-in."""
    path = Path(name)
    if name in BUILTIN:
        entry = BUILTIN[name]
        if not entry.ready:
            return None, entry.owner
        return load_scenario(scenario_text(name), source=f"{name}.yaml"), None
    if path.suffix in (".yaml", ".yml") and path.is_file():
        return load_scenario_file(path), None
    raise L4Exit(ExitCode.USAGE_ERROR, f"simulate: {name!r} is neither a built-in scenario nor a scenario file")


def _line(result: ScenarioResult) -> str:
    head = f"{result.status.upper():8} {result.name}"
    if result.status == "pending":
        return f"{head}  (owner: {result.owner})"
    if result.status == "fail":
        return f"{head}\n{_indent(result.report)}"
    return head


def _indent(text: str) -> str:
    return "\n".join(f"    {line}" for line in text.splitlines())


def run_simulate(
    app: AppContext,
    *,
    scenarios: Sequence[str] = (),
    all_scenarios: bool = False,
    with_repo_config: bool = False,
    keep: bool = False,
    as_json: bool = False,
) -> CommandResult:
    """`l4 simulate [SCENARIO...|--all] [--keep] [--json]`: exit 1 when a ready scenario fails; a pending one is
    listed with its owner and never changes the exit code."""
    if with_repo_config:
        raise L4Exit(
            ExitCode.USAGE_ERROR, "simulate: --with-repo-config not yet implemented (M1: simulation-harness 2.12)"
        )
    names = list(BUILTIN) if all_scenarios else list(scenarios)
    if not names:
        raise L4Exit(ExitCode.USAGE_ERROR, "simulate: name a scenario or pass --all")
    results: list[ScenarioResult] = []
    for name in names:
        try:
            scenario, owner = _load(name)
        except ScenarioError as exc:
            raise L4Exit(ExitCode.USAGE_ERROR, f"simulate: {exc}") from None
        if scenario is None:
            results.append(ScenarioResult(name, "pending", owner=owner, report=f"pending on {owner}"))
        else:
            results.append(run_scenario(scenario, keep=keep))
    counts = {s: sum(r.status == s for r in results) for s in ("pass", "fail", "pending")}
    summary = f"{counts['pass']} passed, {counts['fail']} failed, {counts['pending']} pending"
    if as_json:
        document = {
            "schema": SCHEMA,
            "scenarios": [_as_json(r) for r in results],
            "summary": counts,
        }
        click.echo(json.dumps(document, indent=2, ensure_ascii=False))
    else:
        click.echo("\n".join([*(_line(r) for r in results), summary]))
    return CommandResult(ExitCode.INTERNAL_ERROR if counts["fail"] else ExitCode.OK)


def _as_json(result: ScenarioResult) -> dict[str, Any]:
    body: dict[str, Any] = {"name": result.name, "status": result.status, "driver": result.driver}
    if result.status == "pending":
        body["owner"] = result.owner
    else:
        digest = hashlib.sha256(json.dumps(result.events, sort_keys=True, default=str).encode()).hexdigest()
        body |= {"exit_code": result.exit_code, "final_phase": result.final_phase, "events_sha256": digest}
        if result.report:
            body["mismatches"] = result.report
    return body
