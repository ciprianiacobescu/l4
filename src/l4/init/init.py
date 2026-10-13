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
from pydantic import ValidationError

from l4 import __version__
from l4.agents.credentials import hosted_login_problem
from l4.buildinfo import github_slug, harness_commit, harness_origin
from l4.ci.github import ACTION_PATH, WORKFLOW_RELPATH, ActionPin, render_github_action_ci, render_github_ci
from l4.ci.render import (
    INCLUDE_SNIPPET,
    SETUP_RELPATH,
    SHIM_RELPATH,
    TEMPLATE_RELPATH,
    VENDOR_RELPATH,
    render_fetched_shim,
    render_gitlab_ci,
    render_setup,
    render_shim,
)
from l4.config.loader import CONFIG_RELPATH, load_config
from l4.config.schema import HarnessCfg, L4Config
from l4.context import AppContext
from l4.exitcodes import ExitCode, L4Exit
from l4.fsutil import UnsafeFile, atomic_write_bytes, read_regular_file, reject_symlinks
from l4.init.action import packaged_action, remote_url, resolve_ref
from l4.init.ciedit import merge_include
from l4.init.dependabot import DEPENDABOT_RELPATH, merge_dependabot
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


DEFAULT_PROFILES: dict[str, dict[str, str]] = {
    "codex": {"adapter": "codex", "vendor": "openai", "auth": "subscription"},
    "claude-code": {"adapter": "claude-code", "vendor": "anthropic", "auth": "subscription"},
}
DEFAULT_ROLES: dict[str, list[str]] = {"implementer": ["codex"], "judges": ["claude-code"]}
HOSTED_FORGE_TOKEN = "GITHUB_TOKEN"  # the workflow's own token: an action adoption's default (adoption-kit D6)


def hosted_login_todos(
    profiles: Mapping[str, Mapping[str, str]] = DEFAULT_PROFILES, roles: Mapping[str, list[str]] = DEFAULT_ROLES
) -> tuple[str, ...]:
    """One todo per profile of a role chain that cannot log in on a GitHub-hosted runner (see
    `l4.agents.credentials.hosted_login_problem`): the person's agents are theirs to choose, so it only says what."""
    todos = []
    seen: set[str] = set()
    for role, chain in roles.items():
        for name in chain:
            profile = profiles.get(name, {})
            problem = None if name in seen else hosted_login_problem(profile.get("adapter"), profile.get("auth"))
            seen.add(name)
            if problem:
                todos.append(f"profile {name} (roles.{role}) cannot log in on a GitHub-hosted runner: {problem}")
    return tuple(todos)


def render_config(
    commit: str | None,
    ci: str = "gitlab",
    *,
    memory: bool = True,
    proposal: Proposal | None = None,
    repository: str | None = None,
    delivery: str | None = None,
    runner_tags: tuple[str, ...] | None = None,
    token_env: str | None = None,
    todos: tuple[str, ...] = (),
) -> str:
    """The M0 pair of SPEC 3.2: Codex implements, Claude Code judges, a different vendor each. Models are left to the
    CLIs' defaults; set `model` and `options.reasoning_effort` on a profile to pin them. `ci`: the platform, or `both`
    (two CI files: the environment decides which forge a run talks to). `memory=False` writes `memory.enabled: false`
    (the repository ignores the paths memory would commit, M1.8 A5). `proposal`: the gates read from pyproject.toml,
    with a `# TODO:` line for each assumption (M1.8 A2, L4-INS-003); without it the M0 gates. `repository`: the
    harness is fetched at run time from that URL at `commit` (L4-GHP-010), not vendored. `delivery: action`: the
    harness comes from the setup action, whose pin is the workflow's `uses:` line: no version and no commit here.
    `runner_tags` (written as `ci.runner_tags`, `()` meaning GitHub-hosted) and `token_env` (`forge.token_env`) are
    written only when given; `todos` are extra `# TODO:` lines at the top."""
    platform = "auto" if ci == "both" else ci
    pins = (
        {"delivery": "action"}
        if delivery == "action"
        else {"version": __version__, "commit": commit, **({"repository": repository} if repository else {})}
    )
    body = {
        "version": 1,
        "harness": pins,
        "spec": {"frameworks": ["openspec"]},
        "gates": proposal.gates if proposal else GATES,
        "profiles": DEFAULT_PROFILES,
        "roles": DEFAULT_ROLES,
        "forge": {"type": platform, **({"token_env": token_env} if token_env else {})},
        "ci": {"platform": platform, **({"runner_tags": list(runner_tags)} if runner_tags is not None else {})},
        **({} if memory else {"memory": {"enabled": False}}),
    }
    todos = "".join(f"# TODO: {todo}\n" for todo in (*todos, *(proposal.todos if proposal else ())))
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
    vendor: VendorSource | None  # None: the harness is fetched at run time, nothing is vendored
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


def _extend_gitignore(repo: Path, entries: tuple[str, ...] = GITIGNORE_ENTRIES) -> bytes | None:
    path = repo / ".gitignore"
    try:
        reject_symlinks(repo, ".gitignore")
        current = read_regular_file(path, limit=MAX_GITIGNORE_BYTES) if path.exists() else b""
        text = current.decode("utf-8")
    except (UnsafeFile, UnicodeDecodeError) as exc:
        raise L4Exit(ExitCode.USAGE_ERROR, f"init: cannot extend .gitignore: {exc}") from None
    eol = "\r\n" if "\r\n" in text else "\n"
    present = {line.strip() for line in text.splitlines()}
    missing = [entry for entry in entries if entry not in present]
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


def _fetched_pins(repository: str, commit: str) -> tuple[str, str]:
    """The repository (scp form normalised) and the commit, checked by the rules the config applies to them."""
    try:
        pins = HarnessCfg(repository=repository, commit=commit)
    except ValidationError as exc:
        reasons = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        raise L4Exit(ExitCode.USAGE_ERROR, f"init: --harness-repo/--harness-commit: {reasons}") from None
    assert pins.repository is not None and pins.commit is not None
    return pins.repository, pins.commit


def _action_file(harness: Path | None) -> bytes:
    """The setup action for `--action-copy`: the consumer keeps its own copy of it. `--harness PATH` names a checkout
    to copy it from; without it the copy is the one the running `l4` ships (no checkout is needed)."""
    if harness is None:
        return packaged_action()
    root = harness_root(harness)
    relative = f"{ACTION_PATH}/action.yml"
    try:
        reject_symlinks(root, *Path(relative).parts)
        return read_regular_file(root / relative, limit=MAX_GITIGNORE_BYTES)
    except (UnsafeFile, OSError):
        raise L4Exit(
            ExitCode.USAGE_ERROR, f"init --action-copy: the harness checkout {root} has no {relative} to copy"
        ) from None


def _dependabot(repo: Path) -> tuple[PlannedFile | None, tuple[str, ...]]:
    """`.github/dependabot.yml` (`--dependabot`): created, or the `github-actions` entry added to the file there is."""
    try:
        reject_symlinks(repo, *Path(DEPENDABOT_RELPATH).parts)
        path = repo / DEPENDABOT_RELPATH
        text = read_regular_file(path, limit=MAX_GITIGNORE_BYTES).decode("utf-8") if path.exists() else None
    except (UnsafeFile, UnicodeDecodeError) as exc:
        raise L4Exit(ExitCode.USAGE_ERROR, f"init: cannot edit {DEPENDABOT_RELPATH}: {exc}") from None
    edit = merge_dependabot(text)
    if edit.action == "refuse":
        raise L4Exit(
            ExitCode.USAGE_ERROR,
            f"init: {DEPENDABOT_RELPATH} is left alone: {edit.reason}. Nothing was written. Add this entry to its "
            f"`updates` list by hand, then run `l4 init` again without --dependabot:\n{edit.snippet}",
        )
    if edit.action == "noop":
        return None, (f"{DEPENDABOT_RELPATH} already updates github-actions",)
    mode = (repo / DEPENDABOT_RELPATH).stat().st_mode & 0o777 if text is not None else 0o644
    verb = "created" if edit.action == "create" else "got the github-actions entry added"
    return PlannedFile(DEPENDABOT_RELPATH, edit.text.encode("utf-8"), mode), (f"{DEPENDABOT_RELPATH} {verb}",)


def plan_init(
    repo: Path,
    environ: Mapping[str, str],
    *,
    force: bool,
    harness: Path | None = None,
    ci: str = "gitlab",
    ci_edit: bool = True,
    fetched: tuple[str, str] | None = None,
    action: ActionPin | None = None,
    dependabot: bool = False,
    runner_tags: tuple[str, ...] = (),
    token_env: str = HOSTED_FORGE_TOKEN,
) -> InitPlan:
    """Everything init will write, or an exit-2 refusal naming what is in the way. `fetched`: (repository, commit) of a
    harness fetched at run time (L4-GHP-010): the fetched shim, and no vendored copy. `action`: the harness comes from
    the setup action (L4-ACT-004): the config, the action-form workflow, the action itself with `action.copy`, and no
    `.l4/bin/` file at all; `dependabot` adds or merges `.github/dependabot.yml`. An action adoption runs on a
    GitHub-hosted runner unless `runner_tags` are given, and uses the workflow's own `GITHUB_TOKEN` unless `token_env`
    says otherwise; a profile that cannot log in there is named in a todo."""
    vendor: VendorSource | None = None
    repository: str | None = None
    if action is not None:
        commit = action.sha
    elif fetched is None:
        vendor = collect_vendor_source(harness_root(harness), environ)
        commit = vendor.commit
    else:
        repository, commit = _fetched_pins(*fetched)
    ignored = ignored_harness_paths(repo, environ)  # `.serena/` in .gitignore: neither the seed nor lessons commit
    proposal = propose_gates(detect_python(repo))
    login_todos = hosted_login_todos() if action is not None and not runner_tags else ()
    config_text = render_config(
        None if action else commit, ci, memory=not ignored, proposal=proposal, repository=repository,
        delivery="action" if action else None, runner_tags=runner_tags if action else None,
        token_env=token_env if action else None, todos=login_todos,
    )  # fmt: skip
    cfg = loaded_config(config_text)
    files = [PlannedFile(str(CONFIG_RELPATH), config_text.encode(), 0o644)]
    if action is None:
        files += [
            PlannedFile(SHIM_RELPATH, (render_shim() if fetched is None else render_fetched_shim()).encode(), 0o755),
            PlannedFile(SETUP_RELPATH, render_setup().encode(), 0o755),
        ]
    ci_notes: tuple[str, ...] = ()
    edited: PlannedFile | None = None
    merged: PlannedFile | None = None
    if ci in ("gitlab", "both"):
        files.append(PlannedFile(TEMPLATE_RELPATH, render_gitlab_ci().encode(), 0o644))
        if ci_edit:
            edited, ci_notes = _ci_edit(repo, cfg, proposal)
            if edited is not None:
                files.append(edited)
    if action is not None:
        files.append(PlannedFile(WORKFLOW_RELPATH, render_github_action_ci(cfg, action).encode(), 0o644))
        if action.copy:
            files.append(PlannedFile(f"{ACTION_PATH}/action.yml", _action_file(harness), 0o644))
        if dependabot:
            merged, dependabot_notes = _dependabot(repo)
            if merged is not None:
                files.append(merged)
            ci_notes += dependabot_notes
    elif ci in ("github", "both"):
        files.append(PlannedFile(WORKFLOW_RELPATH, render_github_ci(cfg).encode(), 0o644))
    for planned in (*files, *([PlannedFile(VENDOR_RELPATH, b"", 0o644)] if vendor else [])):
        try:
            reject_symlinks(repo, *Path(planned.path).parts)
        except UnsafeFile as exc:
            raise L4Exit(ExitCode.USAGE_ERROR, f"init: {exc}") from None
    seed = _serena_seed(repo, cfg)
    existing = tuple(p.path for p in files if p is not edited and p is not merged and (repo / p.path).exists())
    vendor_exists = vendor is not None and (repo / VENDOR_RELPATH).exists()
    in_the_way = (*existing, *([VENDOR_RELPATH] if vendor_exists else ()))
    if in_the_way and not force:
        raise L4Exit(ExitCode.USAGE_ERROR, f"init: would overwrite {', '.join(in_the_way)}; pass --force to replace")
    notes = (
        f"memory is off (memory.enabled: false): {carve_out_text(ignored)}\nthen set memory.enabled: true",
    ) if ignored else ()  # fmt: skip
    notes += (*ci_notes, *proposal.notes)
    marker = register_l4_marker(repo) if "pytest" in cfg.gates.test.command else None
    return InitPlan(
        (*files, *seed),
        vendor,
        vendor_exists,
        _extend_gitignore(repo, GITIGNORE_ENTRIES if vendor else GITIGNORE_ENTRIES[:1]),
        in_the_way,
        notes,
        marker,
        (*login_todos, *proposal.todos),
    )


def files_to_commit(plan: InitPlan) -> list[str]:
    """What the adopter commits after init, computed from what the plan writes (M1.10 decision 16): `.l4/` for
    everything under it, `.gitignore` when extended, the CI file when created or edited, the file the marker edit
    writes, and the Serena seed files."""
    outside = [f.path for f in plan.files if not f.path.startswith(".l4/")]
    ci = [p for p in outside if p in (CI_FILE, WORKFLOW_RELPATH) or p.startswith(".github/")]
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
    if plan.vendor is not None:
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


def _require_m0_form(ci: str | None, framework: str | None, vendor: bool, dry_run: bool, fetched: bool) -> None:
    deferred = {"--dry-run": dry_run, "--framework kiro": framework == "kiro"}
    for flag, used in deferred.items():
        if used:
            raise L4Exit(ExitCode.USAGE_ERROR, f"init: {flag} not yet implemented (M1: forge-and-ci)")
    if vendor and fetched:
        raise L4Exit(ExitCode.USAGE_ERROR, "init: --vendor and --harness-repo exclude each other")
    if ci is None or not (vendor or fetched):
        raise L4Exit(
            ExitCode.USAGE_ERROR,
            "init: needs `--ci gitlab|github|both` and either `--vendor` or `--harness-repo URL`",
        )


def _action_pin(
    app: AppContext,
    *,
    action_repo: str | None,
    action_copy: bool,
    harness_repo: str | None,
    harness_commit_pin: str | None,
    harness_ref: str | None,
) -> ActionPin:
    """The pin of an action-form workflow (L4-ACT-004, L4-ACT-005): the harness repository (`--action-repo`, else the
    one `--harness-repo` names, else the one the running harness was installed from), and its commit (`--harness-ref`
    resolved once with `git ls-remote`, `--harness-commit`, else the running harness's own)."""
    remote = _fetched_pins(harness_repo, "0" * 40)[0] if harness_repo else None
    repository = action_repo or (github_slug(remote) if remote else None) or harness_origin()
    if repository is None:
        raise L4Exit(
            ExitCode.USAGE_ERROR,
            "init --action: the repository that holds the setup action is unknown; pass --action-repo OWNER/REPO",
        )
    try:
        ActionPin(repository, "0" * 40)
    except ValueError as exc:
        raise L4Exit(ExitCode.USAGE_ERROR, f"init --action: {exc}") from None
    ref: str | None = None
    if harness_ref is not None:
        sha = resolve_ref(remote or remote_url(repository), harness_ref, app.environ)
        ref = harness_ref
    else:
        sha = harness_commit_pin or harness_commit()
        if sha is None:
            raise L4Exit(
                ExitCode.USAGE_ERROR,
                "init --action: the running harness's commit is unknown (it is neither vendored nor installed from "
                "git); pass --harness-ref REF or --harness-commit SHA",
            )
    try:
        return ActionPin(repository, sha, ref, copy=action_copy)
    except ValueError as exc:
        raise L4Exit(ExitCode.USAGE_ERROR, f"init --action: {exc}") from None


def _action_notes(pin: ActionPin) -> tuple[str, ...]:
    """What to do after an action-form init: the environment and its secrets, who may use the action, a local l4."""
    who = (
        f"the copy of the action in {ACTION_PATH}/ fetches the harness over ssh: add its read-only deploy key as the "
        "secret L4_HARNESS_SSH_KEY"
        if pin.copy
        else f"{pin.repository} must let this repository use its action (Settings > Actions > Access), which a private "
        "repository can do for its owner's other private repositories; anyone else needs --action-copy"
    )
    return (
        f"commit {WORKFLOW_RELPATH} and .l4/, push, then run `l4 setup github` (with an `l4` of your own, see the "
        "last note): it "
        "creates the environment `l4` whose secrets the job reads (agent keys with `--secret NAME=ENVVAR`; the forge "
        "token is the workflow's own GITHUB_TOKEN, `forge.token_env: GITHUB_TOKEN`, so there is none to set)",
        who,
        f"there is no .l4/bin/l4: install one to run commands here, `uv tool install git+https://github.com/"
        f"{pin.repository}@{pin.sha}`",
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
    harness_repo: str | None = None,
    harness_commit_pin: str | None = None,
    action: bool = False,
    action_repo: str | None = None,
    action_copy: bool = False,
    dependabot: bool = False,
    harness_ref: str | None = None,
    runner_tag: tuple[str, ...] = (),
    forge_token_env: str | None = None,
) -> ExitCode:
    if harness_ref is not None and harness_commit_pin is not None:
        raise L4Exit(ExitCode.USAGE_ERROR, "init: --harness-ref and --harness-commit exclude each other")
    if not action:
        extras = (("--action-repo", action_repo), ("--action-copy", action_copy), ("--dependabot", dependabot),
                  ("--runner-tag", runner_tag), ("--forge-token-env", forge_token_env))
        for flag, used in extras:
            if used:
                raise L4Exit(ExitCode.USAGE_ERROR, f"init: {flag} needs --action")
        if harness_ref is not None and harness_repo is None:
            raise L4Exit(ExitCode.USAGE_ERROR, "init: --harness-ref needs --harness-repo URL or --action")
    pin: ActionPin | None = None
    if action:
        if dependabot and action_copy:
            raise L4Exit(
                ExitCode.USAGE_ERROR,
                "init: --dependabot and --action-copy exclude each other: Dependabot moves `uses:` pins, and in copy "
                "mode the pin is the `commit:` input, which it cannot move (use `l4 upgrade --harness-ref`)",
            )
        if ci != "github":
            raise L4Exit(ExitCode.USAGE_ERROR, "init: --action needs --ci github")
        if vendor:
            raise L4Exit(ExitCode.USAGE_ERROR, "init: --action and --vendor exclude each other")
        pin = _action_pin(
            app, action_repo=action_repo, action_copy=action_copy, harness_repo=harness_repo,
            harness_commit_pin=harness_commit_pin, harness_ref=harness_ref,
        )  # fmt: skip
        _require_m0_form(ci, framework, False, dry_run, True)
    else:
        _require_m0_form(ci, framework, vendor, dry_run, harness_repo is not None)
    if harness_repo is None and harness_commit_pin is not None and not action:
        raise L4Exit(ExitCode.USAGE_ERROR, "init: --harness-commit needs --harness-repo (or --action)")
    fetched: tuple[str, str] | None = None
    if harness_repo is not None and not action:
        if harness_ref is not None:
            fetched_pin: str | None = resolve_ref(_fetched_pins(harness_repo, "0" * 40)[0], harness_ref, app.environ)
        else:
            fetched_pin = harness_commit_pin or harness_commit()
        if fetched_pin is None:
            raise L4Exit(
                ExitCode.USAGE_ERROR,
                "init: the running harness's commit is unknown (it is neither vendored nor installed from git); "
                "pass --harness-commit SHA",
            )
        fetched = (harness_repo, fetched_pin)
    plan = plan_init(
        app.repo, app.environ, force=force, harness=harness, ci=ci or "gitlab", ci_edit=not no_ci_edit, fetched=fetched,
        action=pin, dependabot=dependabot, runner_tags=tuple(runner_tag),
        token_env=forge_token_env or HOSTED_FORGE_TOKEN,
    )  # None was refused  # fmt: skip
    apply_plan(app.repo, plan)
    for planned in plan.files:
        log.info("wrote %s", planned.path)
    if plan.vendor is not None:
        log.info(
            "vendored the harness at %s into %s/ (%d files)",
            plan.vendor.commit[:12],
            VENDOR_RELPATH,
            len(plan.vendor.files),
        )
    elif pin is not None:
        log.info("the harness comes from the setup action, pinned at %s in %s", pin.sha[:12], WORKFLOW_RELPATH)
    else:
        log.info("the harness is fetched at run time (harness.repository, harness.commit in %s)", CONFIG_RELPATH)
    if plan.gitignore is not None:
        log.info("extended .gitignore")
    if ci in ("gitlab", "both") and no_ci_edit:
        log.info("add this to .gitlab-ci.yml, then commit .l4/ and the include:")
        click.echo(INCLUDE_SNIPPET, nl=False)
    if pin is not None:
        for line in _action_notes(pin):
            click.echo(f"note: {line}", err=True)
    elif ci in ("github", "both"):
        click.echo(
            f"note: commit {WORKFLOW_RELPATH} and .l4/, push, then run `.l4/bin/l4 setup github`: it creates the "
            "environment `l4` whose secrets the job reads (agent keys with `--secret NAME=ENVVAR`; the forge token is "
            "L4_FORGE_TOKEN there, or the workflow's own GITHUB_TOKEN with `forge.token_env: GITHUB_TOKEN`)",
            err=True,
        )
    for note in plan.notes:
        click.echo(f"note: {note}", err=True)
    if (said := marker_message(plan.marker)) is not None:
        click.echo(said, err=True)
    for todo in plan.todos:  # the same lines as the `# TODO:` ones at the top of the config, where nobody looks
        click.echo(f"todo: {todo}", err=True)
    click.echo(
        f"next: run `{'l4' if pin is not None else '.l4/bin/l4'} doctor --adoption` (the config rows and a dry run of "
        "the gates at HEAD), then commit "
        + _listed(files_to_commit(plan)),
        err=True,
    )
    if plan.vendor is not None:
        click.echo(
            f"note: the harness lint gate skips {VENDOR_RELPATH}/; exclude `.l4/` from the repo's own lint too "
            "(for example `ruff check --extend-exclude .l4 .` in .gitlab-ci.yml)",
            err=True,
        )
    return ExitCode.OK
