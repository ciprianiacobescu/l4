"""The post-merge acceptance profile (design D9, requirement L4-YOLO-009, scenario SCN-YOLO-18).

`run_profile` checks out one revision of the target (the merged tip) as a detached worktree in the harness cache,
runs the gate kinds of an acceptance profile on it with the existing gate runner and sandbox (`l4.gates.runner`,
`l4.sandbox`), and always removes the worktree, whatever happened. A profile is a list of gate kinds from
`yolo.profiles`: `setup`, `build`, `lint`, `typecheck`, `test`, `e2e` or `extra:<name>`. Two names are reserved: `all`
is every configured gate kind, and `none` is no check.

A profile that resolves to no gate is an `error` with the detail `profile <name> has no gate to run`, never a pass: a
check that ran nothing proves nothing. The first failing required gate ends the run (`fail`); a failing `extra` gate
that is not `required` is recorded and does not fail it. A gate kind that is not configured is skipped and named in
the detail. A profile passes only when at least one required gate other than `setup` ran and passed; a run of
`setup` and non-required extras alone is an `error` (R7): setup proves nothing about the merged code, and an extra
that may fail proves nothing either. This runner does not start servers (`gates.e2e.serve`): `all` leaves the `e2e`
gate out and says so in the detail (R7), and a named profile that lists `e2e` while a server is configured is an
`error` (admission refuses it earlier, `unsupported_profile`).
Anything the runner raises is an `error` too, so the plan step stops with a reason instead of crashing.
"""

import shutil
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path

from l4.config.defaults import cache_root
from l4.config.schema import L4Config, duration_seconds
from l4.context import AppContext
from l4.gates.runner import GateResult, GateSpec, run_gate
from l4.sandbox.base import Sandbox, gate_sandbox_spec, runner_tmp_paths
from l4.sandbox.caches import mount_caches
from l4.sandbox.env import toolchain_env
from l4.sandbox.select import select_sandbox
from l4.vcs.errors import GitError
from l4.vcs.git import Git
from l4.yolo.model import PROFILE_ALL, PROFILE_NONE, ProfileResult

AREA = ("yolo", "postcheck")  # under the runner cache
CACHE_UNIT = "openspec:yolo-postcheck"  # the name the gate caches (uv, pip, npm) are kept under
KINDS = ("setup", "build", "lint", "typecheck", "test", "e2e")
EXTRA = "extra:"


class _NoGate(Exception):
    pass


def profile_kinds(cfg: L4Config, profile: str, profiles: Mapping[str, Sequence[str]] | None) -> list[str]:
    """The gate kinds of `profile`: the reserved names first, then `profiles`, else `cfg.yolo.profiles` when the
    config has them; a named profile that does not list `setup` gets it first when `gates.setup` is configured (it never
    counts toward a pass). `ValueError` for an unknown profile or a kind that is not a gate kind."""
    if profile == PROFILE_NONE:
        return []
    if profile == PROFILE_ALL:
        return [*KINDS, *(EXTRA + extra.name for extra in cfg.gates.extra)]
    known = profiles if profiles is not None else getattr(getattr(cfg, "yolo", None), "profiles", None) or {}
    if profile not in known:
        raise ValueError(f"unknown profile {profile} (known: {', '.join(sorted(known)) or 'none'})")
    kinds = list(known[profile])
    for kind in kinds:
        if kind not in KINDS and not kind.startswith(EXTRA):
            raise ValueError(f"profile {profile}: {kind!r} is not a gate kind")
    if cfg.gates.setup and "setup" not in kinds:  # a fresh worktree has no environment: setup is a prerequisite
        kinds.insert(0, "setup")
    return kinds


def _gates_of(
    cfg: L4Config, kinds: Sequence[str], *, skip_served: bool = False
) -> tuple[list[tuple[str, str, GateSpec, bool, bool]], list[str], list[str]]:
    """(name, kind, spec, required, network) of every configured gate of `kinds`, the kinds with none, and the kinds
    left out because they need an app server (`skip_served`, for `all`; otherwise such a gate raises `_NoGate`)."""
    timeout = duration_seconds(cfg.gates.timeout)
    allowed = cfg.gates.network == "allow"
    found: list[tuple[str, str, GateSpec, bool, bool]] = []
    skipped: list[str] = []
    left_out: list[str] = []
    for kind in kinds:
        before = len(found)
        if kind in ("setup", "build", "lint", "typecheck"):
            for command in getattr(cfg.gates, kind):
                found.append(
                    (kind, kind, GateSpec(kind, command, timeout_s=timeout), True, True if kind == "setup" else allowed)
                )
        elif kind == "test" and cfg.gates.test.command.strip():
            test = cfg.gates.test
            spec = GateSpec("test", test.command, tuple(test.reports), test.format, timeout)
            found.append(("test", kind, spec, True, allowed))
        elif kind == "e2e" and cfg.gates.e2e.command.strip():
            e2e = cfg.gates.e2e
            if e2e.serve.command.strip() and skip_served:
                left_out.append(kind)
                continue
            if e2e.serve.command.strip():
                raise _NoGate("gate e2e needs an app server (gates.e2e.serve), which a profile run does not start")
            spec = GateSpec("e2e", e2e.command, tuple(e2e.reports), e2e.format, timeout)
            found.append(("e2e", kind, spec, True, allowed))
        elif kind.startswith(EXTRA):
            for extra in cfg.gates.extra:
                if EXTRA + extra.name == kind and extra.command.strip():
                    spec = GateSpec(kind, extra.command, timeout_s=timeout)
                    found.append((kind, kind, spec, extra.required, allowed))
        if len(found) == before:
            skipped.append(kind)
    return found, skipped, left_out


def _left_out_note(left_out: Sequence[str]) -> str:
    if not left_out:
        return ""
    return f"; left out (gates.e2e.serve is set and this runner starts no server): {', '.join(left_out)}"


def run_profile(
    app: AppContext,
    cfg: L4Config,
    git: Git,
    revision: str,
    profile: str,
    *,
    profiles: Mapping[str, Sequence[str]] | None = None,
    sandbox: Sandbox | None = None,
) -> ProfileResult:
    """Run the gate kinds of `profile` on a detached worktree of `revision`. `profiles` replaces `cfg.yolo.profiles`
    (the config of a repository that has none, and tests). The worktree is removed in every case."""
    sha = git.rev_parse(revision)
    if sha is None:
        return ProfileResult("error", revision, profile, detail=f"revision {revision} is not in the repository")
    try:
        kinds = profile_kinds(cfg, profile, profiles)
        planned, skipped, left_out = _gates_of(cfg, kinds, skip_served=profile == PROFILE_ALL)
    except (ValueError, _NoGate) as exc:
        return ProfileResult("error", sha, profile, detail=str(exc))
    served = _left_out_note(left_out)
    if not planned:
        return ProfileResult("error", sha, profile, detail=f"profile {profile} has no gate to run{served}")
    cache = cache_root(app.environ, repo=app.repo)
    area = cache.joinpath(*AREA)
    area.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=f"{sha[:10]}-", dir=area))
    tree = work / "tree"
    try:
        try:
            git.run("worktree", "add", "--quiet", "--detach", str(tree), sha)
        except GitError as exc:
            return ProfileResult("error", sha, profile, detail=f"cannot check out {sha[:10]}: {exc}")
        return _run(app, cfg, git, sha, profile, tree, work, planned, skipped, sandbox, served)
    except Exception as exc:  # the runner's own failure is a stop with a reason, not a crash of the plan step
        return ProfileResult("error", sha, profile, detail=f"{type(exc).__name__}: {exc}")
    finally:
        git.run("worktree", "remove", "--force", str(tree), check=False)
        shutil.rmtree(work, ignore_errors=True)
        git.run("worktree", "prune", check=False)


def _run(
    app: AppContext,
    cfg: L4Config,
    git: Git,
    sha: str,
    profile: str,
    tree: Path,
    work: Path,
    planned: Sequence[tuple[str, str, GateSpec, bool, bool]],
    skipped: Sequence[str],
    sandbox: Sandbox | None,
    served: str = "",
) -> ProfileResult:
    chosen = sandbox or select_sandbox(cfg.sandbox, app.environ, repo=app.repo)
    cache = cache_root(app.environ, repo=app.repo)
    common = Path(git.run("rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip())
    home = Path(app.environ["HOME"]) if app.environ.get("HOME") else Path.home()
    caches = mount_caches(cfg.sandbox.caches, cache, CACHE_UNIT)
    tmp = work / "gate-tmp"
    tmp.mkdir()
    logs = app.out_dir / "yolo" / "postcheck" / app.run_id
    results: list[GateResult] = []
    failure = ""
    for number, (name, _kind, spec, required, network) in enumerate(planned, start=1):
        sandbox_spec = gate_sandbox_spec(
            worktree=tree, git_common_dir=common, tmp_dir=tmp, home=home,
            configured_credential_paths=cfg.sandbox.credential_paths, caches=caches, network=network,
            runner_tmp=runner_tmp_paths(app.environ),
        )  # fmt: skip
        safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in name)[:60]
        result = run_gate(
            spec, worktree=tree, sandbox=chosen, sandbox_spec=sandbox_spec, host_env=app.environ,
            log_path=logs / f"{number:03d}-{safe}.log", redactor=app.redactor, extra_env=toolchain_env(cfg),
        )  # fmt: skip
        results.append(result)
        if result.status != "pass" and required:
            failure = f"{name} failed ({result.reason}); log {result.log_path}"
            break
    note = f"; skipped (not configured): {', '.join(skipped)}" if skipped else ""
    note += served
    if failure:
        return ProfileResult("fail", sha, profile, tuple(results), failure + note)
    proved = any(
        result.status == "pass" and required and kind != "setup"
        for result, (_name, kind, _spec, required, _network) in zip(results, planned, strict=True)
    )
    if not proved:
        ran = ", ".join(f"{r.name} {r.status}" for r in results)
        detail = f"no required gate other than setup passed ({ran}){note}"
        return ProfileResult("error", sha, profile, tuple(results), detail)
    return ProfileResult("pass", sha, profile, tuple(results), f"{len(results)} gate(s) passed{note}")
