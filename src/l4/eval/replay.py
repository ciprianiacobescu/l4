"""The deterministic reference implementer of a judge cell (L4-EVAL-006, plan D3).

A `command` profile runs `python -m l4.eval.replay --reference <dir> --prompt {prompt_file} --result {result_path}` as
the implementer, through the real implement path: on the red step it writes the unit's reference red files into the
worktree (its cwd) and on the green step the reference green files, each with a result object that conforms to the
implementer result schema. The commits, trailers and ledger the judge then sees are harness-made.

`<dir>` holds `red/` and `green/`, the project-relative files of the seed unit's `reference/`. It must be readable
from the agent sandbox (anything outside `/tmp`). Nothing here reads the network or the environment.
"""

import argparse
import json
import re
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from l4.eval.seeds import SeedUnit

_PHASE = re.compile(r"^# Phase: (RED|GREEN)\b", re.MULTILINE)
_TASK = re.compile(r"^# Task (\S+)", re.MULTILINE)
_CRITERION = re.compile(r"C-[0-9a-f]{8}")
_TEST_DEF = re.compile(r"^def (test_\w+)\(", re.MULTILINE)


class ReplayError(RuntimeError):
    pass


def files_of(reference: Path, kind: str) -> list[str]:
    """The project-relative files of `reference/<kind>/`, sorted; a symlink or an escaping path is refused."""
    root = (reference / kind).resolve()
    if not root.is_dir():
        raise ReplayError(f"{kind}/ is missing from the reference")
    found = []
    for path in sorted((reference / kind).rglob("*")):
        if path.is_symlink():
            raise ReplayError("the reference holds a symlink")
        if path.is_file():
            if "__pycache__" in path.parts or path.name.endswith(".pyc"):
                continue
            rel = path.relative_to(reference / kind)
            if rel.is_absolute() or ".." in rel.parts:
                raise ReplayError("a reference path leaves the project")
            found.append(rel.as_posix())
    return found


def materialize_reference(unit: SeedUnit, dest: Path) -> Path:
    """`dest/red/...` and `dest/green/...` from the unit's reference files, for a cell's replay profile."""
    if dest.exists():
        shutil.rmtree(dest)
    for kind, files in (("red", unit.reference_red), ("green", unit.reference_green)):
        for rel, data in files.items():
            target = dest / kind / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    return dest


def reference_profile(reference: Path, python: str | None = None) -> dict[str, Any]:
    """The `command` profile that replays `reference`; its vendor is its own, so it never vetoes a judge."""
    return {
        "adapter": "command",
        "vendor": "eval-reference",
        "options": {
            "argv": [
                python or sys.executable, "-m", "l4.eval.replay", "--reference", str(reference.resolve()),
                "--prompt", "{prompt_file}", "--result", "{result_path}",
            ],
        },
    }  # fmt: skip


def _result(phase: str, task: str, written: dict[str, str]) -> dict[str, object]:
    tests = sorted(f"{rel}::{name}" for rel, text in written.items() if rel.startswith("tests/")
                   for name in _TEST_DEF.findall(text))  # fmt: skip
    criteria = sorted(
        {c for rel, text in written.items() if rel.startswith("tests/") for c in _CRITERION.findall(text)}
    )
    out: dict[str, object] = {
        "status": "done", "phase": phase, "task_ids": [task],
        "summary": f"replayed the reference {phase} step of the eval seed", "files_changed": sorted(written),
    }  # fmt: skip
    if tests:
        out["tests_added"] = tests
    if phase == "red":
        out["criteria_ids"] = criteria
    return out


def main(argv: Sequence[str] | None = None, *, cwd: Path | None = None) -> int:
    parser = argparse.ArgumentParser(prog="l4.eval.replay")
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--prompt", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)
    work = (cwd or Path.cwd()).resolve()
    try:
        prompt = args.prompt.read_text(encoding="utf-8")
        match = _PHASE.search(prompt)
        if match is None:
            raise ReplayError("the prompt names no RED or GREEN phase")
        phase = match.group(1).lower()
        task = (_TASK.search(prompt) or [None, "1.1"])[1]
        written: dict[str, str] = {}
        for rel in files_of(args.reference, phase):
            target = (work / rel).resolve()
            if work not in target.parents:
                raise ReplayError("a reference path leaves the worktree")
            target.parent.mkdir(parents=True, exist_ok=True)
            text = (args.reference / phase / rel).read_text(encoding="utf-8")
            target.write_text(text, encoding="utf-8")
            written[rel] = text
        args.result.parent.mkdir(parents=True, exist_ok=True)
        args.result.write_text(json.dumps(_result(phase, task, written)), encoding="utf-8")
    except (ReplayError, OSError) as exc:
        print(f"replay: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
