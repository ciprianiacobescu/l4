"""`l4 upgrade` (M1.1 gap G11): bring the adopted harness up to the checkout it is run from, without `init --force`.

Vendor mode only. Re-vendors `.l4/vendor/` from the harness checkout at HEAD, re-renders `.l4/ci/l4.gitlab-ci.yml` and
`.l4/bin/l4`, and rewrites two scalars of `.l4/config.yaml`, `harness.version` and `harness.commit`; every other byte
of the human-owned config stays (L4-CFG-004). `.gitlab-ci.yml` and `.gitignore` are never touched, and neither is any
other project file but one entry: when the test gate runs pytest, the `l4` marker is registered in the project's pytest
configuration (`l4.init.pytest_marker`), once, or the snippet is printed. New config keys are reported, never written.
M1: forge-and-ci 1.14 and 1.20 (the `uvx` pin form).
"""

import logging
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import click
import yaml
from pydantic import BaseModel, TypeAdapter, ValidationError

from l4 import __version__
from l4.buildinfo import harness_commit
from l4.ci.github import WORKFLOW_RELPATH, render_github_ci
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
from l4.init.action import SAVE_STEP_NAME, migrate_save_paths, read_pin, remote_url, repin, resolve_ref
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

log = logging.getLogger("l4.upgrade")

MAX_CONFIG_BYTES = 1024 * 1024
_VERSION_LINE = re.compile(rb'^__version__\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)
_BLOCK = re.compile(r"^harness:[ \t]*(#.*)?$")
_PIN = re.compile(
    r"""^(?P<lead>[ \t]+(?P<key>version|commit):[ \t]*)"""
    r"""(?P<value>"[^"\n]*"|'[^'\n]*'|[^\s#"'][^#\n]*?)(?P<tail>[ \t]*(?:#.*)?)$"""
)
_SKIPPED_DIRS = frozenset({".venv", "__pycache__"})


def _refuse(message: str) -> L4Exit:
    return L4Exit(ExitCode.USAGE_ERROR, f"upgrade: {message}")


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
    notes: tuple[str, ...] = ()  # one line each, printed after the files (the save step's paths, L4-ACT-002)

    @property
    def vendor_differs(self) -> bool:
        return bool(self.vendor_added or self.vendor_changed or self.vendor_removed)


def plan_upgrade(
    repo: Path, environ: Mapping[str, str], harness: Path | None, pin: str | None = None, ref: str | None = None
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
        return _plan_action(repo, loaded, old_config, environ, harness, pin, ref)
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
        PlannedFile(TEMPLATE_RELPATH, render_gitlab_ci().encode(), 0o644),
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


def _plan_action(
    repo: Path,
    loaded: L4Config,
    old_config: str,
    environ: Mapping[str, str],
    harness: Path | None,
    pin: str | None,
    ref: str | None,
) -> UpgradePlan:
    """An action adoption (L4-ACT-005): the pin is the workflow's `uses:` line (the `commit` input of a copy of the
    action), and only that line moves: `@<sha> # <REF>`. Nothing else changes."""
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
    if found is None or found.repository is None:
        raise _refuse(
            f"cannot find the setup action (and its repository) in {WORKFLOW_RELPATH}; edit its `uses:` line by hand"
        )
    if ref is not None:
        sha = resolve_ref(remote_url(found.repository), ref, environ)
    else:
        sha = pin or harness_commit() or ""
        if not sha:
            raise _refuse("the running harness's commit is unknown; pass --harness-ref REF or --harness-commit SHA")
        try:
            TypeAdapter(Sha).validate_python(sha)
        except ValidationError:
            raise _refuse(f"--harness-commit must be 40 lowercase hex characters, not {sha!r}") from None
    new = repin(text, sha=sha, ref=ref)
    notes: tuple[str, ...] = ()
    migrated = migrate_save_paths(new)
    if migrated is not None:  # an adoption from before the paths became the action's output (once)
        new = migrated
        notes = (
            f"the `{SAVE_STEP_NAME}` step of {WORKFLOW_RELPATH} now reads its paths from the action's output "
            "clis-cache-paths (they were a literal list, which drifts from the action's restore)",
        )
    changed = () if new == text else (PlannedFile(WORKFLOW_RELPATH, new.encode("utf-8"), 0o644),)
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
        wanted.append(PlannedFile(TEMPLATE_RELPATH, render_gitlab_ci().encode(), 0o644))
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


def run_upgrade(
    app: AppContext,
    *,
    harness: Path | None = None,
    dry_run: bool = False,
    harness_commit_pin: str | None = None,
    harness_ref: str | None = None,
) -> ExitCode:
    plan = plan_upgrade(app.repo, app.environ, harness, harness_commit_pin, harness_ref)
    verb = "would change" if dry_run else "changed"
    if plan.vendor is not None and plan.vendor_differs:
        click.echo(
            f"{verb} {VENDOR_RELPATH}/ ({len(plan.vendor_added)} added, {len(plan.vendor_changed)} changed, "
            f"{len(plan.vendor_removed)} removed) to the harness at {plan.vendor.commit[:12]}"
        )
    for planned in plan.files:
        pins = (
            (" (harness.commit)" if plan.vendor is None else " (harness.version, harness.commit)")
            if planned.path == str(CONFIG_RELPATH)
            else ""
        )
        click.echo(f"{verb} {planned.path}{pins}")
    for planned in plan.seeded:
        verb_new = "would create" if dry_run else "created"
        click.echo(f"{verb_new} {planned.path} (in Serena's own form, so that its start changes nothing)")
    for note in plan.notes:
        click.echo(f"{'would change' if dry_run else 'changed'}: {note}")
    said = marker_message(plan.marker, dry_run=dry_run)
    if said is not None:
        click.echo(said)
    if not plan.vendor_differs and not plan.files and not plan.seeded and said is None:
        click.echo(
            f"up to date: the harness at {plan.commit[:12]} is already {'vendored' if plan.vendor else 'pinned'}"
        )
    if plan.missing:
        click.echo(f"not in {CONFIG_RELPATH}, the defaults apply (nothing is written): {', '.join(plan.missing)}")
    if not dry_run:
        apply_upgrade(app.repo, plan)
    return ExitCode.OK
