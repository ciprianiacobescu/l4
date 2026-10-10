"""What to change when the gates fail at HEAD (M1.8 A2/A3): suggestions for `doctor --adoption`, from the dry run.

A suggestion is a sentence naming one config edit, derived from facts (a missing module, a lint command that passes
once narrowed), never from a guess about the project. `--all-extras` is never suggested: a heavy extra such as
`embed` pulls torch.
"""

import shlex
from collections.abc import Sequence

from l4.config.schema import L4Config
from l4.gates.dryrun import NARROW_SELECT, GateDryRun, GateRun
from l4.gates.pyproject import PyProject, distribution_for


def _setup_with(cfg: L4Config, extras: Sequence[str]) -> str | None:
    """`gates.setup` rewritten with the extras added to its `uv sync` line; None when there is no such line."""
    for command in cfg.gates.setup:
        try:
            words = shlex.split(command)
        except ValueError:
            continue
        if words[:2] == ["uv", "sync"] or ("uv" in words and "sync" in words):
            have = {words[i + 1] for i, w in enumerate(words[:-1]) if w == "--extra"}
            added = [e for e in extras if e not in have]
            if not added:
                return None
            return command + "".join(f" --extra {e}" for e in added)
    return None


def _missing_module_hint(cfg: L4Config, project: PyProject, runs: Sequence[GateRun]) -> list[str]:
    modules = dict.fromkeys(m for run in runs if run.gate == "test" for m in run.missing_modules)
    wanted: dict[str, list[str]] = {}
    for module in modules:
        dist = distribution_for(module)
        if extras := project.extras_providing(dist):
            wanted[module] = extras
    if not wanted:
        return []
    extras = list(dict.fromkeys(e for provided in wanted.values() for e in provided[:1]))
    names = ", ".join(f"{m} (extra {'/'.join(e)})" for m, e in wanted.items())
    rewritten = _setup_with(cfg, extras)
    todo = (
        f"change gates.setup `{next(c for c in cfg.gates.setup if 'sync' in c)}` to `{rewritten}`"
        if rewritten
        else "add " + " ".join(f"`--extra {e}`" for e in extras) + " to gates.setup"
    )
    return [f"tests need modules from optional extras: {names}; {todo}"]


def _lint_hint(run: GateRun) -> str | None:
    if run.status != "fail":
        return None
    if run.narrowed is None:
        return f"lint `{run.command}` fails: fix its findings, or set gates.lint to [] until you do"
    if run.narrowed_ok:
        return (
            f"lint `{run.command}` fails on style findings; `{run.narrowed}` passes: use it in gates.lint "
            "(it keeps the errors that break a run), and widen it when the rest is fixed"
        )
    if run.narrowed_paths and run.narrowed_paths_ok:
        return (
            f"lint `{run.command}` fails even narrowed to {NARROW_SELECT}; on the source and test directories "
            f"(`{run.narrowed_paths}`) it passes: use that in gates.lint"
        )
    return f"lint `{run.command}` fails even narrowed to {NARROW_SELECT}: fix those, or set gates.lint to []"


def _deselect(test_id: str) -> str | None:
    """`tests.test_x::test_a` -> `tests/test_x.py::test_a`; only for a module-level test (a class would be a guess)."""
    classname, _, name = test_id.partition("::")
    parts = classname.split(".")
    if not name or not parts or not parts[-1].startswith("test"):
        return None
    return "/".join(parts) + ".py::" + name.split("[", 1)[0]


def suggestions(cfg: L4Config, project: PyProject, result: GateDryRun) -> list[str]:
    """Edits that would turn the failing rows of `result` green, one sentence each, most useful first."""
    out: list[str] = []
    out += _missing_module_hint(cfg, project, result.runs)
    needs_extras = bool(out)  # the failing tests are then most likely that: the next run says what is left
    for run in result.runs:
        if run.gate == "lint" and (hint := _lint_hint(run)):
            out.append(hint)
    for run in result.runs:
        if run.gate == "test" and run.status == "fail" and run.failing_tests and not needs_extras:
            ids = [d for t in run.failing_tests[:3] if (d := _deselect(t))]
            flags = " ".join(f"--deselect {i}" for i in ids)
            out.append(
                f"{len(run.failing_tests)} test(s) fail at the base, so every verification FAILs step 3 until they "
                "pass: fix them first, or deselect them in gates.test.command"
                + (f" (for example `{flags}`)" if flags else "")
            )
    return out
