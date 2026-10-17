"""A dry run of the gates at HEAD (M1.8 A3, L4-GAT-001): what the first unit's baseline would see.

Every unit of a run fails verification step 3 on a failing test at its base and step 2 on a failing lint or setup, so a
repository adopted with a red base fails every unit. The dry run runs `gates.setup`, `build`, `lint`, `typecheck` and
`gates.test.command` in a detached worktree of HEAD (never the working tree: a run starts from a commit), in the gate
sandbox when bwrap is usable. Outside CI a missing sandbox is accepted (the code is the maintainer's own and committed)
and said so; in CI it is a failure, because a runner without a sandbox is a runner that cannot run a unit either.
"""

import dataclasses
import re
import shlex
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from l4.agents.proc import ProcRunner
from l4.config.defaults import cache_root
from l4.config.redaction import redactor_for_config
from l4.config.schema import L4Config, duration_seconds
from l4.exitcodes import L4Exit
from l4.gates.pyproject import project_dirs, read_pyproject
from l4.gates.runner import GateResult, GateSpec, run_gate
from l4.proc import run_process
from l4.safepath import resolve_tool
from l4.sandbox.base import Sandbox, SandboxUnavailable, gate_sandbox_spec
from l4.sandbox.bwrap import BwrapSandbox
from l4.sandbox.caches import mount_caches
from l4.sandbox.env import toolchain_env
from l4.sandbox.none import NoSandbox
from l4.vcs.git import Git, GitError

MAX_FAILING = 10
EXCERPT_LINES = 10
_MISSING_MODULE = re.compile(r"No module named '([A-Za-z0-9_.]+)'")
_BLOCKED_IMPORT = re.compile(r"import of ([A-Za-z0-9_.]+) halted")  # `sys.modules[name] = None`: a blocked import
NARROW_SELECT = "F,E9"  # pyflakes errors and syntax errors: what makes a run fail, not style
_RUFF_CHECK = re.compile(r"\bruff\s+check\b")
_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def narrow_ruff(command: str) -> str | None:
    """The same `ruff check` command restricted to `--select F,E9`; None for any other command."""
    found = _RUFF_CHECK.search(command)
    if found is None or "--select" in command:
        return None
    return command[: found.end()] + f" --select {NARROW_SELECT}" + command[found.end() :]


# the value options of `ruff check` that the path narrowing reads (they take the next token), and the flags it knows
_RUFF_VALUE_OPTIONS = frozenset({
    "--select", "--extend-select", "--ignore", "--extend-ignore", "--exclude", "--extend-exclude", "--config",
    "--line-length", "--target-version", "--output-format", "--per-file-ignores", "--cache-dir",
})  # fmt: skip
_RUFF_FLAGS = frozenset({
    "--fix", "--no-fix", "--unsafe-fixes", "--no-unsafe-fixes", "--show-fixes", "--diff", "--no-cache", "--isolated",
    "--preview", "--no-preview", "--statistics", "--exit-zero", "--exit-non-zero-on-fix", "--fix-only",
    "--force-exclude", "--ignore-noqa", "--quiet", "--verbose", "--silent", "-q", "-v", "-s",
})  # fmt: skip


def narrow_ruff_paths(command: str, dirs: Sequence[str]) -> str | None:
    """`command` (a `ruff check` already narrowed to some rules) with its positional paths replaced by `dirs`: the dot
    of `ruff check .`, or no path at all (ruff then checks `.`). None when the project chose its own paths, when there
    is no directory to narrow to, when the command is not `ruff check`, or when an option is not one this reads (it
    could take a value, so which token is a path would be a guess)."""
    if not dirs:
        return None
    try:
        tokens = shlex.split(command)
    except ValueError:
        return None
    at = next((i for i, t in enumerate(tokens[:-1]) if Path(t).name == "ruff" and tokens[i + 1] == "check"), None)
    if at is None:
        return None
    rest = tokens[at + 2 :]
    paths: list[str] = []
    index = 0
    while index < len(rest):
        token = rest[index]
        name = token.split("=", 1)[0]
        if token.startswith("-"):
            if name in _RUFF_VALUE_OPTIONS:
                if "=" not in token:
                    index += 1
                    if index >= len(rest):
                        return None
            elif token not in _RUFF_FLAGS:
                return None
        else:
            paths.append(token)
        index += 1
    if paths not in ([], ["."]):
        return None
    kept = list(rest)
    if paths:  # the options keep their place; the one path token is the dot
        kept.remove(".")
    return shlex.join([*tokens[: at + 2], *kept, *dirs])


@dataclass(frozen=True)
class GateRun:
    gate: str  # setup | build | lint | typecheck | test
    command: str
    status: Literal["pass", "fail", "skipped"]
    reason: str = ""
    excerpt: str = ""  # the first lines of a failing lint, the last lines of anything else that failed
    failing_tests: tuple[str, ...] = ()
    failure_messages: tuple[str, ...] = ()  # the first line of each failing test's message (same order)
    missing_modules: tuple[str, ...] = ()  # top-level names the run could not import
    tests_passed: int | None = None
    tests_total: int | None = None
    narrowed: str | None = None  # a failing `ruff check`, narrowed to `--select F,E9` (suggest.NARROW_SELECT)...
    narrowed_ok: bool | None = None  # ...and whether that passed
    narrowed_paths: str | None = None  # when that failed too: the same command on the project's source and test dirs
    narrowed_paths_ok: bool | None = None  # ...and whether that passed (M1.10 decision 15)


@dataclass(frozen=True)
class GateDryRun:
    sha: str = ""
    sandbox: str = ""  # what the gates ran in
    runs: tuple[GateRun, ...] = ()
    error: str = ""  # the dry run itself could not be made (no commit, no sandbox in CI)

    @property
    def ok(self) -> bool:
        return not self.error and all(run.status != "fail" for run in self.runs)


def _sandbox(cfg: L4Config, environ: Mapping[str, str], repo: Path, in_ci: bool) -> tuple[Sandbox | None, str, str]:
    """(sandbox, label, error). `auto` and `bwrap` use bwrap when it starts a sandbox; `none` is the config's accepted
    risk; otherwise the gates run unsandboxed outside CI, and fail in CI."""
    mode = cfg.sandbox.mode
    if mode == "none":
        try:
            return NoSandbox(allow_none=cfg.sandbox.allow_none), "none (sandbox.mode: none)", ""
        except SandboxUnavailable as exc:
            return None, "", str(exc)
    why = "bwrap was not found on PATH"
    if mode in ("auto", "bwrap"):
        exe = resolve_tool("bwrap", environ, forbid=(repo,))
        if exe is not None:
            sandbox = BwrapSandbox(exe, run_process)
            verdict = sandbox.available()
            if verdict.ok:
                return sandbox, "bwrap", ""
            why = verdict.reason
    if in_ci:
        return None, "", f"no usable gate sandbox in CI ({why}): a runner without one cannot run a unit either"
    return NoSandbox(allow_none=True), f"unsandboxed ({why}; your own committed code runs as you)", ""


def _commands(cfg: L4Config) -> list[tuple[str, str]]:
    gates = cfg.gates
    pairs = [("setup", c) for c in gates.setup] + [("build", c) for c in gates.build]
    pairs += [("lint", c) for c in gates.lint] + [("typecheck", c) for c in gates.typecheck]
    if gates.test.command.strip():
        pairs.append(("test", gates.test.command))
    return pairs


def _lines(text: str) -> list[str]:
    return [line.rstrip() for line in _ANSI.sub("", text).splitlines() if line.strip()]


def _run_of(gate: str, command: str, result: GateResult) -> GateRun:
    text = result.log_path.read_text(encoding="utf-8", errors="replace") if result.log_path.exists() else ""
    lines = _lines(text)
    missing = tuple(
        dict.fromkeys(m.split(".")[0] for m in [*_MISSING_MODULE.findall(text), *_BLOCKED_IMPORT.findall(text)])
    )
    report = result.report
    failing: list[str] = []
    messages: list[str] = []
    if report is not None:
        for test_id in sorted(report.ids_with("failed") | report.ids_with("error")):
            failing.append(test_id)
            messages.append((report.tests[test_id].message.splitlines() or [""])[0][:200])
        failing += [f"{name} (collection)" for name in report.collection_errors]
        messages += ["collection failure"] * len(report.collection_errors)
    if result.status == "pass":
        passed = len(report.ids_with("passed")) if report else None
        return GateRun(gate, command, "pass", "", "", (), (), (), passed, report.total if report else None)
    shown = lines[:EXCERPT_LINES] if gate == "lint" else lines[-EXCERPT_LINES:]
    return GateRun(
        gate, command, "fail", result.reason, "\n".join(shown), tuple(failing), tuple(messages), missing,
        len(report.ids_with("passed")) if report else None, report.total if report else None,
    )  # fmt: skip


def dry_run_gates(
    cfg: L4Config,
    repo: Path,
    environ: Mapping[str, str],
    *,
    in_ci: bool,
    sandbox: Sandbox | None = None,
    runner: ProcRunner | None = None,
) -> GateDryRun:
    try:
        git = Git(repo, environ=environ)
    except L4Exit as exc:
        return GateDryRun(error=str(exc))
    sha = git.rev_parse("HEAD")
    if sha is None:
        return GateDryRun(error="the repository has no commit yet: commit first, the gates run at HEAD")
    commands = _commands(cfg)
    if not commands:
        return GateDryRun(sha, "", (), "")
    chosen, label, error = (sandbox, sandbox.name, "") if sandbox is not None else _sandbox(cfg, environ, repo, in_ci)
    if chosen is None:
        return GateDryRun(sha, error=error)
    cache = cache_root(environ, repo=repo)
    base = cache / "adoption"
    tree, logs = base / sha[:12], base / f"{sha[:12]}-logs"
    for stale in (tree, logs):
        shutil.rmtree(stale, ignore_errors=True)
    git.run("worktree", "prune", check=False)
    base.mkdir(parents=True, exist_ok=True)
    try:
        git.run("worktree", "add", "--detach", "--quiet", str(tree), sha)
    except GitError as exc:
        return GateDryRun(sha, label, error=f"cannot make a worktree of HEAD: {(str(exc).splitlines() or [''])[-1]}")
    runs: list[GateRun] = []
    try:
        home = Path(environ["HOME"]) if environ.get("HOME") else Path.home()
        common = Path(git.run("rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip())
        caches = mount_caches(cfg.sandbox.caches, cache, "openspec:l4-adoption-check")
        redactor = redactor_for_config(cfg, environ)
        timeout = duration_seconds(cfg.gates.timeout)
        setup_failed = False
        for number, (gate, command) in enumerate(commands, start=1):
            if setup_failed:
                runs.append(GateRun(gate, command, "skipped", "gates.setup failed"))
                continue
            reports = tuple(cfg.gates.test.reports) if gate == "test" else ()
            spec = GateSpec(gate, command, reports, cfg.gates.test.format, timeout)
            network = True if gate == "setup" else cfg.gates.network == "allow"
            sandbox_spec = gate_sandbox_spec(
                worktree=tree, git_common_dir=common, tmp_dir=base / f"{sha[:12]}-tmp", home=home,
                configured_credential_paths=cfg.sandbox.credential_paths, caches=caches, network=network,
            )  # fmt: skip
            (base / f"{sha[:12]}-tmp").mkdir(exist_ok=True)
            result = run_gate(
                spec, worktree=tree, sandbox=chosen, sandbox_spec=sandbox_spec, host_env=environ,
                log_path=logs / f"{number:03d}-{gate}.log", redactor=redactor, runner=runner,
                extra_env=toolchain_env(cfg),
            )  # fmt: skip
            run = _run_of(gate, command, result)
            if gate == "lint" and run.status == "fail" and (narrowed := narrow_ruff(command)) is not None:
                again = run_gate(
                    dataclasses.replace(spec, name="lint-narrow", command=narrowed), worktree=tree, sandbox=chosen,
                    sandbox_spec=sandbox_spec, host_env=environ, log_path=logs / f"{number:03d}-lint-narrow.log",
                    redactor=redactor, runner=runner, extra_env=toolchain_env(cfg),
                )  # fmt: skip
                run = dataclasses.replace(run, narrowed=narrowed, narrowed_ok=again.status == "pass")
                if (
                    again.status != "pass"
                    and (by_dirs := narrow_ruff_paths(narrowed, project_dirs(tree, read_pyproject(tree)))) is not None
                ):
                    third = run_gate(
                        dataclasses.replace(spec, name="lint-narrow-paths", command=by_dirs), worktree=tree,
                        sandbox=chosen, sandbox_spec=sandbox_spec, host_env=environ,
                        log_path=logs / f"{number:03d}-lint-narrow-paths.log", redactor=redactor, runner=runner,
                        extra_env=toolchain_env(cfg),
                    )  # fmt: skip
                    run = dataclasses.replace(run, narrowed_paths=by_dirs, narrowed_paths_ok=third.status == "pass")
            runs.append(run)
            setup_failed = setup_failed or (gate == "setup" and run.status == "fail")
    finally:
        git.run("worktree", "remove", "--force", str(tree), check=False)
        shutil.rmtree(tree, ignore_errors=True)
        git.run("worktree", "prune", check=False)
        shutil.rmtree(base / f"{sha[:12]}-tmp", ignore_errors=True)
    return GateDryRun(sha, label, tuple(runs))
