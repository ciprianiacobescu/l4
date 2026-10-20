"""The preflight of `l4 yolo go` (L4-YOLO-081): can the plan go from the working tree to an active plan? The same
local checks as the skill's `scripts/yolo_preflight.py`, which stays the arbiter: `plan-file` (the plan file is in the
working tree and is JSON) and `clean-tree` (no tracked file differs from HEAD, no untracked file under `.l4/` or under
the folder of a unit the plan lists). They need no network and read nothing from the forge. The script's other
checks (origin, HEAD against origin, the plan on origin, the judge roles, the harness) are `go`'s own steps: the push,
the check, the review.

An untracked file anywhere else is not a problem: a checkout may hold a person's own notes. A test runs the script and
this function on the same repositories and asserts that both pass or both fail.
"""

import json
from dataclasses import dataclass
from pathlib import Path

from l4.vcs.git import Git

MAX_NAMED = 3
DOT_L4 = ".l4/"


@dataclass(frozen=True)
class Problem:
    """`code`: `plan_missing`, `plan_not_json`, `dirty`, `plan_uncommitted` or `unit_uncommitted`; `text` says what is
    wrong; `fix` is the one command that clears it."""

    code: str
    text: str
    fix: str


def unit_folder(unit_id: str, openspec_root: str, kiro_root: str) -> str:
    """The folder of a unit id, as the script and `plans.unit_infos` resolve it."""
    framework, _, name = unit_id.partition(":")
    return "/".join(
        [
            *Path(openspec_root if framework == "openspec" else kiro_root).parts,
            *(["changes"] if framework == "openspec" else []),
            name,
        ]
    )


def plan_units(doc: object) -> list[str]:
    ids: list[str] = []
    if isinstance(doc, dict):
        for batch in doc.get("batches") or []:
            for unit in (batch.get("units") or []) if isinstance(batch, dict) else []:
                if isinstance(unit, dict) and isinstance(unit.get("id"), str) and unit["id"] not in ids:
                    ids.append(unit["id"])
    return ids


def _named(items: list[str]) -> str:
    shown = ", ".join(items[:MAX_NAMED])
    return shown + (f" (+{len(items) - MAX_NAMED} more)" if len(items) > MAX_NAMED else "")


def problems(
    repo: Path,
    git: Git,
    plan_id: str,
    *,
    base_ref: str,
    openspec_root: str = "openspec",
    kiro_root: str = ".kiro/specs",
) -> list[Problem]:
    """Every problem of the working tree, in the script's order: the plan file, then the tree. `base_ref` is the
    remote-tracking ref of the base branch (`refs/remotes/origin/<base>`); it only words the fix of a plan that is on
    origin and not in this checkout."""
    found: list[Problem] = []
    rel = f".l4/plans/{plan_id}.json"
    path = repo / rel
    doc: object = None
    if not path.is_file():
        branch = base_ref.removeprefix("refs/remotes/origin/")
        on_origin = git.run("cat-file", "-e", f"{base_ref}:{rel}", check=False).returncode == 0
        found.append(
            Problem(
                "plan_missing",
                f"{rel} does not exist in this working tree" + (f" (it is on origin/{branch})" if on_origin else ""),
                f"git pull --ff-only origin {branch}" if on_origin else f"l4 yolo draft {plan_id}",
            )
        )
    else:
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            found.append(Problem("plan_not_json", f"{rel} is not JSON", f"l4 yolo check {plan_id} --worktree"))
    status = git.run("status", "--porcelain=v1", "--untracked-files=all", check=False)
    if status.returncode != 0:
        found.append(Problem("dirty", f"git status failed: {status.stderr.strip()[:120]}", "git status"))
        return found
    folders = [unit_folder(u, openspec_root, kiro_root) for u in plan_units(doc)]
    dirty: list[str] = []
    plan_files: list[str] = []
    unit_files: list[str] = []
    for line in status.stdout.splitlines():
        if len(line) < 4:
            continue
        name = line[3:].split(" -> ")[-1].strip().strip('"')
        if not line.startswith("??"):
            dirty.append(name)
        elif name.startswith(DOT_L4):
            plan_files.append(name)
        elif any(name.startswith(f"{folder}/") for folder in folders):
            unit_files.append(name)
    if dirty:
        found.append(Problem("dirty", f"tracked files differ from HEAD: {_named(dirty)}", "git status"))
    if plan_files:
        found.append(
            Problem(
                "plan_uncommitted",
                f"untracked under .l4/: {_named(plan_files)}",
                f"git add {plan_files[0]} && git commit",
            )
        )
    if unit_files:
        folder = next(f for f in folders if unit_files[0].startswith(f"{f}/"))
        found.append(
            Problem(
                "unit_uncommitted",
                f"untracked in a unit folder: {_named(unit_files)}",
                f"git add {folder} && git commit",
            )
        )
    return found
