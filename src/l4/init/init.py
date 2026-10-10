"""`l4 init --ci gitlab|github|both --vendor` (forge-and-ci 1.23, 1.27 and 2.27, reduced).

`plan_init` only builds bytes and checks every precondition; `apply_plan` is the only code that writes, and it runs
after the plan is complete, so a refusal leaves the repository as it was. Files are written through temp file and
rename, the vendored harness as a staged directory that is swapped in. `.gitlab-ci.yml` gets the include through
`l4.init.ciedit.merge_include` (M1.8 A1: created, or the include added as text; a form it cannot edit safely is
refused with the snippet, and `--no-ci-edit` only prints it); `.github/workflows/l4.yml` is a file of its own,
written like the others and refused when it exists (without `--force`).
M1: forge-and-ci 1.19 ecosystem detection beyond uv/pytest/ruff, 1.20 the `v<version>` tag pin, 1.21 OpenSpec
bootstrap, 1.24 `.gitattributes`, 1.26 `--dry-run`, `.serena/` and `.l4/prompts/`, `GITLAB_RUNNER_NOTICE`.
"""

import logging
import os
import shutil
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import click
import yaml

from l4 import __version__
from l4.ci.github import WORKFLOW_RELPATH, render_github_ci
from l4.ci.render import INCLUDE_SNIPPET, SHIM_RELPATH, TEMPLATE_RELPATH, VENDOR_RELPATH, render_gitlab_ci, render_shim
from l4.config.loader import CONFIG_RELPATH, load_config
from l4.config.schema import L4Config
from l4.context import AppContext
from l4.exitcodes import ExitCode, L4Exit
from l4.fsutil import UnsafeFile, atomic_write_bytes, read_regular_file, reject_symlinks
from l4.init.ciedit import merge_include
from l4.init.ecosystem import M0_GATES, Proposal, detect_python, propose_gates
from l4.init.pytest_marker import MarkerEdit, MarkerRefusal, register_l4_marker
from l4.init.vendor import VendorSource, collect_vendor_source, harness_root
from l4.memory.ignore import carve_out_text, ignored_harness_paths
from l4.memory.serena import SEED_PROJECT_RELPATH, render_seed_project_yml

log = logging.getLogger("l4.init")

CI_FILE = ".gitlab-ci.yml"
GITIGNORE_ENTRIES = (".l4-out/", f"{VENDOR_RELPATH}/.venv/")  # the runner's uv builds the vendored project's venv
MAX_GITIGNORE_BYTES = 1024 * 1024
GATES = M0_GATES  # the gates of a repository without a readable pyproject.toml (L4-GAT-003)


def render_config(commit: str, ci: str = "gitlab", *, memory: bool = True, proposal: Proposal | None = None) -> str:
    """The M0 pair of SPEC 3.2: Codex implements, Claude Code judges, a different vendor each. Models are left to the
    CLIs' defaults; set `model` and `options.reasoning_effort` on a profile to pin them. `ci`: the platform, or `both`
    (two CI files: the environment decides which forge a run talks to). `memory=False` writes `memory.enabled: false`
    (the repository ignores the paths memory would commit, M1.8 A5). `proposal`: the gates read from pyproject.toml,
    with a `# TODO:` line for each assumption (M1.8 A2, L4-INS-003); without it the M0 gates."""
    platform = "auto" if ci == "both" else ci
    body = {
        "version": 1,
        "harness": {"version": __version__, "commit": commit},
        "spec": {"frameworks": ["openspec"]},
        "gates": proposal.gates if proposal else GATES,
        "profiles": {
            "codex": {"adapter": "codex", "vendor": "openai", "auth": "subscription"},
            "claude-code": {"adapter": "claude-code", "vendor": "anthropic", "auth": "subscription"},
        },
        "roles": {"implementer": ["codex"], "judges": ["claude-code"]},
        "forge": {"type": platform},
        "ci": {"platform": platform},
        **({} if memory else {"memory": {"enabled": False}}),
    }
    todos = "".join(f"# TODO: {todo}\n" for todo in (proposal.todos if proposal else ()))
    return (
        "# Written by `l4 init`; see docs/SPEC.md 3.2 for every key.\n" + todos + yaml.safe_dump(body, sort_keys=False)
    )


@dataclass(frozen=True)
class PlannedFile:
    path: str  # relative to the repository, posix
    data: bytes
    mode: int


@dataclass(frozen=True)
class InitPlan:
    files: tuple[PlannedFile, ...]
    vendor: VendorSource
    vendor_exists: bool
    gitignore: bytes | None  # the new content, None when nothing needs adding
    overwrites: tuple[str, ...] = field(default=())
    notes: tuple[str, ...] = field(default=())  # what the human is told after the files are written
    marker: MarkerEdit | MarkerRefusal | None = None  # registers the `l4` pytest marker in the project (P4)
    todos: tuple[str, ...] = field(default=())  # the `# TODO:` lines of the config, printed as `todo:` lines too


def loaded_config(config_text: str) -> L4Config:
    """What init writes must load, or init has a bug: load it with the loader every command uses."""
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / CONFIG_RELPATH
        target.parent.mkdir()
        target.write_text(config_text, encoding="utf-8")
        return load_config(Path(tmp))


def validated_config(config_text: str) -> str:
    loaded_config(config_text)
    return config_text


def _extend_gitignore(repo: Path) -> bytes | None:
    path = repo / ".gitignore"
    try:
        reject_symlinks(repo, ".gitignore")
        current = read_regular_file(path, limit=MAX_GITIGNORE_BYTES) if path.exists() else b""
        text = current.decode("utf-8")
    except (UnsafeFile, UnicodeDecodeError) as exc:
        raise L4Exit(ExitCode.USAGE_ERROR, f"init: cannot extend .gitignore: {exc}") from None
    eol = "\r\n" if "\r\n" in text else "\n"
    present = {line.strip() for line in text.splitlines()}
    missing = [entry for entry in GITIGNORE_ENTRIES if entry not in present]
    if not missing:
        return None
    lead = "" if not text or text.endswith("\n") else eol
    return (text + lead + eol.join(missing) + eol).encode("utf-8")


def _serena_seed(repo: Path, cfg: L4Config) -> list[PlannedFile]:
    """`.serena/project.yml` in the form Serena 1.7.0 keeps (L4-INS-002), when memory and Serena are on. A file that is
    already there is the human's: it is left alone, without `--force` too."""
    if not (cfg.memory.enabled and cfg.memory.serena.enabled):
        return []
    try:
        reject_symlinks(repo, *Path(SEED_PROJECT_RELPATH).parts)
    except UnsafeFile as exc:
        raise L4Exit(ExitCode.USAGE_ERROR, f"init: {exc}") from None
    if (repo / SEED_PROJECT_RELPATH).exists():
        return []
    return [PlannedFile(SEED_PROJECT_RELPATH, render_seed_project_yml(repo.resolve().name).encode(), 0o644)]


def _ci_edit(repo: Path, cfg: L4Config, proposal: Proposal) -> tuple[PlannedFile | None, tuple[str, ...]]:
    """The `.gitlab-ci.yml` edit (M1.8 A1): planned like every other file, so a refusal writes nothing."""
    try:
        reject_symlinks(repo, CI_FILE)
        path = repo / CI_FILE
        text = read_regular_file(path, limit=MAX_GITIGNORE_BYTES).decode("utf-8") if path.exists() else None
    except (UnsafeFile, UnicodeDecodeError) as exc:
        raise L4Exit(ExitCode.USAGE_ERROR, f"init: cannot edit {CI_FILE}: {exc}") from None
    edit = merge_include(text, cfg.ci.runner_tags, proposal.gates)
    if edit.action == "refuse":
        raise L4Exit(
            ExitCode.USAGE_ERROR,
            f"init: {CI_FILE} is left alone: {edit.reason}. Nothing was written. Add this to it by hand, then run "
            f"`l4 init` again with --no-ci-edit:\n{edit.snippet}",
        )
    if edit.action == "noop" or edit.text is None:
        return None, (f"{CI_FILE} already includes {TEMPLATE_RELPATH}",)
    verb = {
        "create": "created with the include and a `test` job that runs the gates: the job is yours to change",
        "insert-include": "got the include added at the top",
        "extend-include": "got the include added to its `include:` list",
    }[edit.action]
    mode = (repo / CI_FILE).stat().st_mode & 0o777 if text is not None else 0o644
    return PlannedFile(CI_FILE, edit.text.encode("utf-8"), mode), (f"{CI_FILE} {verb}", *edit.warnings)


def plan_init(
    repo: Path,
    environ: Mapping[str, str],
    *,
    force: bool,
    harness: Path | None = None,
    ci: str = "gitlab",
    ci_edit: bool = True,
) -> InitPlan:
    """Everything init will write, or an exit-2 refusal naming what is in the way."""
    vendor = collect_vendor_source(harness_root(harness), environ)
    ignored = ignored_harness_paths(repo, environ)  # `.serena/` in .gitignore: neither the seed nor lessons commit
    proposal = propose_gates(detect_python(repo))
    config_text = render_config(vendor.commit, ci, memory=not ignored, proposal=proposal)
    cfg = loaded_config(config_text)
    files = [
        PlannedFile(str(CONFIG_RELPATH), config_text.encode(), 0o644),
        PlannedFile(SHIM_RELPATH, render_shim().encode(), 0o755),
    ]
    ci_notes: tuple[str, ...] = ()
    edited: PlannedFile | None = None
    if ci in ("gitlab", "both"):
        files.append(PlannedFile(TEMPLATE_RELPATH, render_gitlab_ci().encode(), 0o644))
        if ci_edit:
            edited, ci_notes = _ci_edit(repo, cfg, proposal)
            if edited is not None:
                files.append(edited)
    if ci in ("github", "both"):
        files.append(PlannedFile(WORKFLOW_RELPATH, render_github_ci(cfg).encode(), 0o644))
    for planned in (*files, PlannedFile(VENDOR_RELPATH, b"", 0o644)):
        try:
            reject_symlinks(repo, *Path(planned.path).parts)
        except UnsafeFile as exc:
            raise L4Exit(ExitCode.USAGE_ERROR, f"init: {exc}") from None
    seed = _serena_seed(repo, cfg)
    existing = tuple(p.path for p in files if p is not edited and (repo / p.path).exists())
    vendor_exists = (repo / VENDOR_RELPATH).exists()
    in_the_way = (*existing, *([VENDOR_RELPATH] if vendor_exists else ()))
    if in_the_way and not force:
        raise L4Exit(ExitCode.USAGE_ERROR, f"init: would overwrite {', '.join(in_the_way)}; pass --force to replace")
    notes = (
        f"memory is off (memory.enabled: false): {carve_out_text(ignored)}\nthen set memory.enabled: true",
    ) if ignored else ()  # fmt: skip
    notes += (*ci_notes, *proposal.notes)
    marker = register_l4_marker(repo) if "pytest" in cfg.gates.test.command else None
    return InitPlan(
        (*files, *seed), vendor, vendor_exists, _extend_gitignore(repo), in_the_way, notes, marker, proposal.todos
    )


def files_to_commit(plan: InitPlan) -> list[str]:
    """What the adopter commits after init, computed from what the plan writes (M1.10 decision 16): `.l4/` for
    everything under it, `.gitignore` when extended, the CI file when created or edited, the file the marker edit
    writes, and the Serena seed files."""
    outside = [f.path for f in plan.files if not f.path.startswith(".l4/")]
    ci = [p for p in outside if p in (CI_FILE, WORKFLOW_RELPATH)]
    seed = [p for p in outside if p not in ci]
    marker = [plan.marker.path] if isinstance(plan.marker, MarkerEdit) and plan.marker.data is not None else []
    return [".l4/", *([".gitignore"] if plan.gitignore is not None else []), *ci, *marker, *seed]


def _listed(names: list[str]) -> str:
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def write_planned_file(repo: Path, planned: PlannedFile) -> None:
    target = repo / planned.path
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_bytes(target, planned.data)
    os.chmod(target, planned.mode)


def swap_in_vendor(repo: Path, source: VendorSource) -> None:
    """Stage the whole tree next to its destination, then swap: a failure leaves the old vendor directory."""
    parent = repo / ".l4"
    parent.mkdir(exist_ok=True)
    staged = Path(tempfile.mkdtemp(dir=parent, prefix=".vendor-"))
    destination = repo / VENDOR_RELPATH
    old: Path | None = None
    try:
        for name, item in source.files.items():
            target = staged / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(item.data)
            os.chmod(target, 0o755 if item.executable else 0o644)
        if destination.exists():
            old = Path(tempfile.mkdtemp(dir=parent, prefix=".vendor-old-"))
            os.replace(destination, old / "vendor")
        os.replace(staged, destination)
        if old is not None:
            shutil.rmtree(old, ignore_errors=True)
    except BaseException:
        shutil.rmtree(staged, ignore_errors=True)
        if old is not None and not destination.exists():
            os.replace(old / "vendor", destination)
        raise


def apply_plan(repo: Path, plan: InitPlan) -> None:
    swap_in_vendor(repo, plan.vendor)  # the step most likely to fail goes first: nothing else is written then
    for planned in plan.files:
        write_planned_file(repo, planned)
    if plan.gitignore is not None:
        atomic_write_bytes(repo / ".gitignore", plan.gitignore)
    apply_marker(repo, plan.marker)


def apply_marker(repo: Path, marker: MarkerEdit | MarkerRefusal | None) -> None:
    """Write the marker edit (one file, atomically); a refusal and an already-registered marker write nothing."""
    if isinstance(marker, MarkerEdit) and marker.data is not None:
        target = repo / marker.path
        atomic_write_bytes(target, marker.data)  # keeps the mode of an existing file
        if marker.created:
            os.chmod(target, 0o644)


def marker_message(marker: MarkerEdit | MarkerRefusal | None, *, dry_run: bool = False) -> str | None:
    """What to tell the person about the marker; None when there is nothing to say (it was there already)."""
    if isinstance(marker, MarkerRefusal):
        return (
            f"could not register the l4 pytest marker ({marker.reason}); without it `pytest --strict-markers` rejects "
            f"the harness's tests. Add this by hand:\n{marker.snippet}"
        )
    if isinstance(marker, MarkerEdit) and marker.data is not None:
        return f"{'would register' if dry_run else 'registered'} the l4 pytest marker in {marker.path}"
    return None


def _require_m0_form(ci: str | None, framework: str | None, vendor: bool, dry_run: bool) -> None:
    deferred = {"--dry-run": dry_run, "--framework kiro": framework == "kiro"}
    for flag, used in deferred.items():
        if used:
            raise L4Exit(ExitCode.USAGE_ERROR, f"init: {flag} not yet implemented (M1: forge-and-ci)")
    if ci is None or not vendor:
        raise L4Exit(
            ExitCode.USAGE_ERROR,
            "init: M0 needs `--ci gitlab|github|both --vendor` (M1: forge-and-ci 1.14 adds the uvx form of the shim)",
        )


def run_init(
    app: AppContext,
    *,
    ci: str | None = None,
    framework: str | None = None,
    vendor: bool = False,
    dry_run: bool = False,
    force: bool = False,
    harness: Path | None = None,
    no_ci_edit: bool = False,
) -> ExitCode:
    _require_m0_form(ci, framework, vendor, dry_run)
    plan = plan_init(
        app.repo, app.environ, force=force, harness=harness, ci=ci or "gitlab", ci_edit=not no_ci_edit
    )  # None was refused
    apply_plan(app.repo, plan)
    for planned in plan.files:
        log.info("wrote %s", planned.path)
    log.info(
        "vendored the harness at %s into %s/ (%d files)",
        plan.vendor.commit[:12],
        VENDOR_RELPATH,
        len(plan.vendor.files),
    )
    if plan.gitignore is not None:
        log.info("extended .gitignore")
    if ci in ("gitlab", "both") and no_ci_edit:
        log.info("add this to .gitlab-ci.yml, then commit .l4/ and the include:")
        click.echo(INCLUDE_SNIPPET, nl=False)
    if ci in ("github", "both"):
        click.echo(
            f"note: commit {WORKFLOW_RELPATH} and .l4/, and add the repository secret L4_FORGE_TOKEN "
            "(a token that can push branches and open pull requests)",
            err=True,
        )
    for note in plan.notes:
        click.echo(f"note: {note}", err=True)
    if (said := marker_message(plan.marker)) is not None:
        click.echo(said, err=True)
    for todo in plan.todos:  # the same lines as the `# TODO:` ones at the top of the config, where nobody looks
        click.echo(f"todo: {todo}", err=True)
    click.echo(
        "next: run `.l4/bin/l4 doctor --adoption` (the config rows and a dry run of the gates at HEAD), then commit "
        + _listed(files_to_commit(plan)),
        err=True,
    )
    click.echo(
        f"note: the harness lint gate skips {VENDOR_RELPATH}/; exclude `.l4/` from the repo's own lint too "
        "(for example `ruff check --extend-exclude .l4 .` in .gitlab-ci.yml)",
        err=True,
    )
    return ExitCode.OK
