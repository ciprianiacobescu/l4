"""`l4 upgrade` (M1.1 gap G11): bring the adopted harness up to the checkout it is run from, without `init --force`.

Vendor mode only. Re-vendors `.l4/vendor/` from the harness checkout at HEAD, re-renders `.l4/ci/l4.gitlab-ci.yml` and
`.l4/bin/l4`, and rewrites two scalars of `.l4/config.yaml`, `harness.version` and `harness.commit`; every other byte
of the human-owned config stays (L4-CFG-004). `.gitlab-ci.yml` and `.gitignore` are never touched, and neither is any
other project file but one entry: when the test gate runs pytest, the `l4` marker is registered in the project's pytest
configuration (`l4.init.pytest_marker`), once, or the snippet is printed. New config keys are reported, never written.
M1: forge-and-ci 1.14 and 1.20 (the `uvx` pin form).
"""

import contextlib
import difflib
import logging
import os
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import click
import yaml
from pydantic import BaseModel, TypeAdapter, ValidationError

from l4 import __version__
from l4.buildinfo import harness_commit
from l4.ci.budget import read_workflow, upgrade_notes
from l4.ci.github import ACTION_PATH, WORKFLOW_RELPATH, ActionPin, render_github_action_ci, render_github_ci
from l4.ci.render import (
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
from l4.config.schema import L4Config, Sha, effective_delivery
from l4.context import AppContext
from l4.exitcodes import ExitCode, L4Exit
from l4.fsutil import UnsafeFile, atomic_write_bytes, read_regular_file, reject_symlinks
from l4.init.action import packaged_action, read_pin, remote_url, resolve_ref
from l4.init.init import (
    PlannedFile,
    _serena_seed,
    apply_marker,
    loaded_config,
    marker_message,
    swap_in_vendor,
    validated_config,
    write_planned_file,
)
from l4.init.pytest_marker import MarkerEdit, MarkerRefusal, register_l4_marker
from l4.init.vendor import VendorSource, collect_vendor_source, harness_root
from l4.vcs.git import Git, GitError

log = logging.getLogger("l4.upgrade")

MAX_CONFIG_BYTES = 1024 * 1024
_DIFF_LINES = 40
_VERSION_LINE = re.compile(rb'^__version__\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)
_BLOCK = re.compile(r"^harness:[ \t]*(#.*)?$")
_PIN = re.compile(
    r"""^(?P<lead>[ \t]+(?P<key>version|commit):[ \t]*)"""
    r"""(?P<value>"[^"\n]*"|'[^'\n]*'|[^\s#"'][^#\n]*?)(?P<tail>[ \t]*(?:#.*)?)$"""
)
_SKIPPED_DIRS = frozenset({".venv", "__pycache__"})


def _refuse(message: str) -> L4Exit:
    return L4Exit(ExitCode.USAGE_ERROR, f"upgrade: {message}")


def _gitlab_template(cfg: L4Config) -> str:
    """The GitLab job for the config as it is now (L4-OPS-016): a changed base branch or prefix changes the file."""
    try:
        return render_gitlab_ci(cfg)
    except ValueError as exc:
        raise _refuse(str(exc)) from None


def rewrite_pins(text: str, *, version: str | None, commit: str) -> str:
    """Replace the scalars of `harness.version` and `harness.commit` and nothing else: the quotes of each value, a
    trailing comment, the line endings and every other line stay. Refuses a file where either is not a plain
    `key: value` line of the `harness:` block (a flow mapping, an anchor): the human edits that one. `version=None`
    (a fetched harness, L4-GHP-010) leaves `harness.version` alone."""
    wanted = {"commit": commit} if version is None else {"version": version, "commit": commit}
    lines = text.splitlines(keepends=True)
    inside = False
    done: set[str] = set()
    for index, raw in enumerate(lines):
        body = raw.rstrip("\r\n")
        eol = raw[len(body) :]
        if _BLOCK.match(body):
            inside = True
            continue
        if inside and body.strip() and not body.startswith((" ", "\t", "#")):
            inside = False
        match = _PIN.match(body) if inside else None
        if match and match["key"] in wanted and match["key"] not in done:
            value = match["value"]
            quote = value[0] if value[0] in "\"'" else ""
            lines[index] = f"{match['lead']}{quote}{wanted[match['key']]}{quote}{match['tail']}{eol}"
            done.add(match["key"])
    if done != set(wanted):
        raise _refuse(
            "cannot find `harness.version` and `harness.commit` as plain `key: value` lines in .l4/config.yaml; "
            "set them by hand (the harness checkout is at "
            f"{commit[:12]}, version {version})"
        )
    new = "".join(lines)
    try:
        pins = yaml.safe_load(new)["harness"]
    except (yaml.YAMLError, KeyError, TypeError):
        pins = {}
    if (
        not isinstance(pins, dict)
        or (version is not None and str(pins.get("version")) != version)
        or str(pins.get("commit")) != commit
    ):
        raise _refuse("the rewritten pins do not read back as the new version and commit; set them by hand")
    return new


def _vendor_version(source: VendorSource) -> str:
    """The version of the harness being vendored (not of the l4 that runs the upgrade, when `--harness` differs)."""
    init_py = source.files.get("src/l4/__init__.py")
    match = _VERSION_LINE.search(init_py.data) if init_py else None
    return match.group(1).decode() if match else __version__


def _old_vendor(repo: Path) -> dict[str, bytes]:
    root = repo / VENDOR_RELPATH
    found: dict[str, bytes] = {}
    if not root.is_dir():
        return found
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if _SKIPPED_DIRS & set(relative.parts) or not path.is_file() or path.is_symlink():
            continue
        found[relative.as_posix()] = path.read_bytes()
    return found


def _model_paths(model: type[BaseModel], prefix: str = "") -> list[str]:
    paths = []
    for name, field in model.model_fields.items():
        annotation = field.annotation
        paths.append(f"{prefix}{name}")
        if isinstance(annotation, type) and issubclass(annotation, BaseModel):
            paths.extend(_model_paths(annotation, f"{prefix}{name}."))
    return paths


def missing_keys(config: Mapping[str, Any]) -> list[str]:
    """The shallowest keys of the schema that the file lacks (a missing section is one entry, not all its keys)."""
    absent = []
    for path in _model_paths(L4Config):
        node: Any = config
        for part in path.split("."):
            if not isinstance(node, Mapping) or part not in node:
                node = None
                break
            node = node[part]
        if node is None and not any(path.startswith(f"{gone}.") for gone in absent):
            absent.append(path)
    return absent


@dataclass(frozen=True)
class UpgradePlan:
    files: tuple[PlannedFile, ...]  # the shim, the setup script, the template and the config, whose bytes differ
    vendor: VendorSource | None  # None: a fetched harness, nothing is vendored
    vendor_added: tuple[str, ...]
    vendor_changed: tuple[str, ...]
    vendor_removed: tuple[str, ...]
    missing: tuple[str, ...]
    seeded: tuple[PlannedFile, ...] = ()  # files created only when absent (`.serena/project.yml`), never overwritten
    marker: MarkerEdit | MarkerRefusal | None = None  # registers the `l4` pytest marker (P4)
    commit: str = ""  # the harness commit the plan pins or vendors
    notes: tuple[str, ...] = ()  # printed after the files (the re-rendered workflow and its changed lines)

    @property
    def vendor_differs(self) -> bool:
        return bool(self.vendor_added or self.vendor_changed or self.vendor_removed)


def plan_upgrade(
    repo: Path,
    environ: Mapping[str, str],
    harness: Path | None,
    pin: str | None = None,
    ref: str | None = None,
    action_repo: str | None = None,
) -> UpgradePlan:
    """The plan of the delivery, then the budget lines (L4-IMP-079): the job's timeout is the `timeout-minutes` of the
    workflow the upgrade leaves (the planned bytes, else the file on disk). They change no file."""
    plan = _plan_delivery(repo, environ, harness, pin, ref, action_repo)
    text: str | None = next(
        (p.data.decode("utf-8", "replace") for p in plan.files if p.path == WORKFLOW_RELPATH), None
    ) or read_workflow(repo)
    lines = upgrade_notes(load_config(repo), text)
    return replace(plan, notes=(*plan.notes, *lines)) if lines else plan


def _plan_delivery(
    repo: Path,
    environ: Mapping[str, str],
    harness: Path | None,
    pin: str | None = None,
    ref: str | None = None,
    action_repo: str | None = None,
) -> UpgradePlan:
    if pin is not None and ref is not None:
        raise _refuse("--harness-ref and --harness-commit exclude each other")
    config_path = repo / CONFIG_RELPATH
    for relative in (str(CONFIG_RELPATH), SHIM_RELPATH, SETUP_RELPATH, TEMPLATE_RELPATH, VENDOR_RELPATH):
        try:
            reject_symlinks(repo, *Path(relative).parts)
        except UnsafeFile as exc:
            raise _refuse(str(exc)) from None
    try:
        old_config = read_regular_file(config_path, limit=MAX_CONFIG_BYTES).decode("utf-8")
    except FileNotFoundError:
        raise _refuse(f"{CONFIG_RELPATH} not found: run l4 init first") from None
    except (UnsafeFile, UnicodeDecodeError) as exc:
        raise _refuse(f"cannot read {CONFIG_RELPATH}: {exc}") from None
    loaded = load_config(repo)  # it must load as it is, or the human has a problem that an upgrade should not hide
    delivery = effective_delivery(loaded)
    if delivery == "action":
        return _plan_action(repo, loaded, old_config, environ, harness, pin, ref, action_repo)
    if action_repo is not None:
        raise _refuse("--action-repo is for an adoption by the setup action (harness.delivery: action)")
    if delivery == "fetched":
        return _plan_fetched(repo, loaded, old_config, harness, pin, ref, environ)
    if pin is not None or ref is not None:
        raise _refuse(
            "--harness-commit and --harness-ref are for a fetched harness (harness.repository) or the setup action "
            "(harness.delivery: action); this adoption is vendored"
        )
    vendor = collect_vendor_source(harness_root(harness), environ)
    new_config = rewrite_pins(old_config, version=_vendor_version(vendor), commit=vendor.commit)
    validated_config(new_config)
    wanted = (
        PlannedFile(str(CONFIG_RELPATH), new_config.encode("utf-8"), 0o644),
        PlannedFile(SHIM_RELPATH, render_shim().encode(), 0o755),
        PlannedFile(SETUP_RELPATH, render_setup().encode(), 0o755),
        PlannedFile(TEMPLATE_RELPATH, _gitlab_template(loaded).encode(), 0o644),
    )
    differing = tuple(p for p in wanted if not _same(repo / p.path, p.data))
    seeded = tuple(_serena_seed(repo, loaded))
    old = _old_vendor(repo)
    new = {name: item.data for name, item in vendor.files.items()}
    return UpgradePlan(
        differing, vendor,
        vendor_added=tuple(sorted(new.keys() - old.keys())),
        vendor_changed=tuple(sorted(n for n in new.keys() & old.keys() if new[n] != old[n])),
        vendor_removed=tuple(sorted(old.keys() - new.keys())),
        missing=tuple(missing_keys(yaml.safe_load(new_config) or {})), seeded=seeded,
        marker=register_l4_marker(repo) if "pytest" in loaded.gates.test.command else None,
        commit=vendor.commit,
    )  # fmt: skip


def _rerender_note(old: str, new: str) -> str:
    """`re-rendered <workflow> (N lines changed)` and the changed lines, as a short unified diff."""
    diff = [
        line
        for line in difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=0)
        if not line.startswith(("---", "+++", "@@"))
    ]
    shown = diff[:_DIFF_LINES] + ([f"... {len(diff) - _DIFF_LINES} more"] if len(diff) > _DIFF_LINES else [])
    return f"re-rendered {WORKFLOW_RELPATH} ({sum(line.startswith('+') for line in diff)} lines changed)" + "".join(
        f"\n    {line}" for line in shown
    )


def _default_branch(repo: Path, environ: Mapping[str, str]) -> str | None:
    """The branch the local `origin/HEAD` names (`main` for `refs/remotes/origin/main`), or None when it is not set."""
    try:
        done = Git(repo, environ=environ).run("symbolic-ref", "--quiet", "refs/remotes/origin/HEAD", check=False)
    except (L4Exit, OSError):
        return None
    ref = done.stdout.strip()
    return ref.removeprefix("refs/remotes/origin/") if done.returncode == 0 and ref else None


def _default_branch_reminder(repo: Path, environ: Mapping[str, str], base: str) -> str | None:
    """GitHub runs a schedule from the default branch's copy of the workflow: when that branch is not the base, a pin
    moved on the base is not the pin the cron runs until the file is copied there too (L4-ADO-005). From 0.4.19 on, a
    stopped scheduled run of that copy relays to the base (L4-IMP-072). Without a known default branch the reminder
    is conditional."""
    default = _default_branch(repo, environ)
    if default is None:
        return (
            f"if the default branch is not {base}, copy {WORKFLOW_RELPATH} there once: GitHub runs the schedule from "
            "that copy"
        )
    if default == base:
        return None
    return (
        f"copy {WORKFLOW_RELPATH} to {default} as well (merge it there): the schedule runs {default}'s copy, "
        f"and {default} is not the base ({base}); from 0.4.19 on, that copy's scheduled runs relay to {base}"
    )


def _plan_action(
    repo: Path,
    loaded: L4Config,
    old_config: str,
    environ: Mapping[str, str],
    harness: Path | None,
    pin: str | None,
    ref: str | None,
    action_repo: str | None = None,
) -> UpgradePlan:
    """An action adoption (L4-ACT-005): the workflow is re-rendered from the config with the template of the harness
    that runs and the new pin (`@<sha> # <REF>`, or the `commit` input of a copy of the action), as the fetched form's
    upgrade re-renders its CI file, so a fix in the template reaches the adoption. `action_repo` (OWNER/REPO) moves the
    pin to another repository: GitHub redirects git and the API after a repository is renamed, but not a `uses:` line
    (live, 2026-10-14: `Unable to resolve action. Repository not found`). A copy of the action names the harness by its
    git URL, which redirects, so it keeps its repository."""
    if harness is not None:
        raise _refuse("--harness vendors a checkout; this adoption gets its harness from the setup action")
    try:
        reject_symlinks(repo, *Path(WORKFLOW_RELPATH).parts)
        text = read_regular_file(repo / WORKFLOW_RELPATH, limit=MAX_CONFIG_BYTES).decode("utf-8")
    except FileNotFoundError:
        raise _refuse(f"{WORKFLOW_RELPATH} not found: run `l4 init --ci github --action` first") from None
    except (UnsafeFile, UnicodeDecodeError) as exc:
        raise _refuse(f"cannot read {WORKFLOW_RELPATH}: {exc}") from None
    found = read_pin(text)
    if found is None or (found.repository is None and action_repo is None):
        raise _refuse(
            f"cannot find the setup action (and its repository) in {WORKFLOW_RELPATH}; edit its `uses:` line by hand"
        )
    if action_repo is not None and found.local:
        raise _refuse("--action-repo moves a `uses:` pin; a copy of the setup action keeps its git URL (it redirects)")
    repository = action_repo or found.repository
    assert repository is not None
    if ref is not None:
        sha = resolve_ref(remote_url(repository), ref, environ)
    else:
        sha = pin or harness_commit() or ""
        if not sha:
            raise _refuse("the running harness's commit is unknown; pass --harness-ref REF or --harness-commit SHA")
        try:
            TypeAdapter(Sha).validate_python(sha)
        except ValidationError:
            raise _refuse(f"--harness-commit must be 40 lowercase hex characters, not {sha!r}") from None
    try:
        pinned = ActionPin(repository, sha, ref, copy=found.local)
    except ValueError as exc:
        raise _refuse(f"cannot move the pin: {exc}") from None
    new = render_github_action_ci(loaded, pinned)
    notes: tuple[str, ...] = ()
    changed: tuple[PlannedFile, ...] = ()
    if new != text:
        changed = (PlannedFile(WORKFLOW_RELPATH, new.encode("utf-8"), 0o644),)
        notes = (_rerender_note(text, new),)
        reminder = _default_branch_reminder(repo, environ, loaded.forge.base_branch)
        if reminder is not None:
            notes += (reminder,)
    if found.local:  # the consumer's own copy of the setup action is refreshed from the one this `l4` ships
        action_path = f"{ACTION_PATH}/action.yml"
        try:
            reject_symlinks(repo, *Path(action_path).parts)
        except UnsafeFile as exc:
            raise _refuse(str(exc)) from None
        shipped = packaged_action()
        if not _same(repo / action_path, shipped):
            changed += (PlannedFile(action_path, shipped, 0o644),)
    missing = tuple(m for m in missing_keys(yaml.safe_load(old_config) or {}) if not m.startswith("harness."))
    return UpgradePlan(
        changed, None, (), (), (), missing=missing, seeded=tuple(_serena_seed(repo, loaded)),
        marker=register_l4_marker(repo) if "pytest" in loaded.gates.test.command else None, commit=sha, notes=notes,
    )  # fmt: skip


def _plan_fetched(
    repo: Path,
    loaded: L4Config,
    old_config: str,
    harness: Path | None,
    pin: str | None,
    ref: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> UpgradePlan:
    """A fetched adoption (L4-GHP-010): only `harness.commit` moves; the shim, the setup script and the CI file are
    re-rendered from the harness that runs; nothing is vendored."""
    if harness is not None:
        raise _refuse("--harness vendors a checkout; this adoption fetches its harness (harness.repository)")
    if ref is not None:
        assert loaded.harness.repository is not None
        commit: str | None = resolve_ref(loaded.harness.repository, ref, environ or {})
    else:
        commit = pin or harness_commit()
    if commit is None:
        raise _refuse("the running harness's commit is unknown; pass --harness-commit SHA")
    try:
        TypeAdapter(Sha).validate_python(commit)
    except ValidationError:
        raise _refuse(f"--harness-commit must be 40 lowercase hex characters, not {commit!r}") from None
    new_config = rewrite_pins(old_config, version=None, commit=commit)
    new_cfg = loaded_config(new_config)
    wanted = [
        PlannedFile(str(CONFIG_RELPATH), new_config.encode("utf-8"), 0o644),
        PlannedFile(SHIM_RELPATH, render_fetched_shim().encode(), 0o755),
        PlannedFile(SETUP_RELPATH, render_setup().encode(), 0o755),
    ]
    platform = loaded.ci.platform
    if platform in ("gitlab", "auto") and (repo / TEMPLATE_RELPATH).exists():
        wanted.append(PlannedFile(TEMPLATE_RELPATH, _gitlab_template(new_cfg).encode(), 0o644))
    if platform in ("github", "auto") and (repo / WORKFLOW_RELPATH).exists():
        wanted.append(PlannedFile(WORKFLOW_RELPATH, render_github_ci(new_cfg).encode(), 0o644))
    return UpgradePlan(
        tuple(p for p in wanted if not _same(repo / p.path, p.data)), None, (), (), (),
        missing=tuple(missing_keys(yaml.safe_load(new_config) or {})), seeded=tuple(_serena_seed(repo, loaded)),
        marker=register_l4_marker(repo) if "pytest" in loaded.gates.test.command else None, commit=commit,
    )  # fmt: skip


def _same(path: Path, data: bytes) -> bool:
    try:
        return path.read_bytes() == data
    except OSError:
        return False


def apply_upgrade(repo: Path, plan: UpgradePlan) -> None:
    if plan.vendor is not None and plan.vendor_differs:
        swap_in_vendor(repo, plan.vendor)  # the step most likely to fail goes first
    for planned in plan.files:
        if planned.path == str(CONFIG_RELPATH):
            atomic_write_bytes(repo / planned.path, planned.data)  # keeps the file's mode
        else:
            write_planned_file(repo, planned)
    for planned in plan.seeded:
        write_planned_file(repo, planned)
    apply_marker(repo, plan.marker)
    load_config(repo)  # the upgraded file must load


def _branch_pin(git: Git, ref: str, delivery: str) -> str | None:
    """The harness commit that the branch's own files pin: for an action adoption the setup action in its workflow,
    for a fetched or vendored one `harness.commit` of its config. None when the file is absent or says nothing."""
    path = WORKFLOW_RELPATH if delivery == "action" else str(CONFIG_RELPATH)
    shown = git.run("show", f"{ref}:{path}", check=False)
    if shown.returncode != 0 or len(shown.stdout) > MAX_CONFIG_BYTES:
        return None
    if delivery == "action":
        found = read_pin(shown.stdout)
        return found.effective if found is not None else None
    try:
        document = yaml.safe_load(shown.stdout)
    except yaml.YAMLError:
        return None
    harness = document.get("harness") if isinstance(document, dict) else None
    commit = harness.get("commit") if isinstance(harness, dict) else None
    return str(commit) if commit else None


def stale_branches_note(repo: Path, environ: Mapping[str, str], commit: str) -> str | None:
    """After a pin moved: the open unit branches on origin (the remote-tracking refs the last fetch left, no network)
    whose own copy pins another commit. GitHub runs a push with the workflow of the pushed branch, so a push to one of
    them runs the old pin, whose guard (CFG-008) does no work; runs start on the base."""
    try:
        cfg = load_config(repo)
        git = Git(repo, environ=environ)
        listed = git.run(
            "for-each-ref", "--format=%(refname:strip=3)", f"refs/remotes/origin/{cfg.forge.branch_prefix}", check=False
        )
        if listed.returncode != 0:
            return None
        delivery = effective_delivery(cfg)
        stale = [
            name
            for name in listed.stdout.split()
            if name != cfg.forge.base_branch
            and (pin := _branch_pin(git, f"refs/remotes/origin/{name}", delivery)) is not None
            and pin != commit
        ]
    except (L4Exit, GitError, OSError):
        return None
    if not stale:
        return None
    shown = ", ".join(stale[:5]) + (f" and {len(stale) - 5} more" if len(stale) > 5 else "")
    return (
        f"{len(stale)} open unit branch(es) on origin keep the old workflow copy ({shown}): a push to one of them "
        f"does no work (GitHub runs the pushed branch's copy, which pins the old harness); runs start on the base, "
        f"{cfg.forge.base_branch} (`l4 retry`, `l4 questions` and the schedule do that)"
    )


def _say(lines: list[str]) -> None:
    """Print the report. A closed stdout (`l4 upgrade | head -1`) ends the report, not the command."""
    try:
        for line in lines:
            click.echo(line)
    except BrokenPipeError:
        with contextlib.suppress(OSError, ValueError, AttributeError):  # stdout is flushed at exit: aim it at /dev/null
            os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())


def run_upgrade(
    app: AppContext,
    *,
    harness: Path | None = None,
    dry_run: bool = False,
    harness_commit_pin: str | None = None,
    harness_ref: str | None = None,
    action_repo: str | None = None,
) -> ExitCode:
    plan = plan_upgrade(app.repo, app.environ, harness, harness_commit_pin, harness_ref, action_repo)
    lines: list[str] = []
    verb = "would change" if dry_run else "changed"
    if plan.vendor is not None and plan.vendor_differs:
        lines.append(
            f"{verb} {VENDOR_RELPATH}/ ({len(plan.vendor_added)} added, {len(plan.vendor_changed)} changed, "
            f"{len(plan.vendor_removed)} removed) to the harness at {plan.vendor.commit[:12]}"
        )
    for planned in plan.files:
        pins = (
            (" (harness.commit)" if plan.vendor is None else " (harness.version, harness.commit)")
            if planned.path == str(CONFIG_RELPATH)
            else " (the setup action, from the copy this l4 ships)"
            if planned.path == f"{ACTION_PATH}/action.yml"
            else ""
        )
        lines.append(f"{verb} {planned.path}{pins}")
    for planned in plan.seeded:
        verb_new = "would create" if dry_run else "created"
        lines.append(f"{verb_new} {planned.path} (in Serena's own form, so that its start changes nothing)")
    for note in plan.notes:
        lines.append(note.replace("re-rendered", "would re-render" if dry_run else "re-rendered", 1))
    said = marker_message(plan.marker, dry_run=dry_run)
    if said is not None:
        lines.append(said)
    if not plan.vendor_differs and not plan.files and not plan.seeded and said is None:
        lines.append(
            f"up to date: the harness at {plan.commit[:12]} is already {'vendored' if plan.vendor else 'pinned'}"
        )
    if plan.missing:
        lines.append(f"not in {CONFIG_RELPATH}, the defaults apply (nothing is written): {', '.join(plan.missing)}")
    if plan.vendor_differs or plan.files:  # the pin moved (or would): the unit branches have their own copies
        stale = stale_branches_note(app.repo, app.environ, plan.commit)
        if stale is not None:
            lines.append(stale)
    if not dry_run:
        apply_upgrade(app.repo, plan)  # first: a reader that quits early (`| head`) must not stop the write
    _say(lines)
    return ExitCode.OK
