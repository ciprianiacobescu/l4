"""Diff coverage's side of the test run (M1.6, D4): the environment that loads `l4_cov`, the harness-owned
coverage rc file, and the merge with the other harness pytest plugins (`l4_trace` of M1.3).

`cov_env` is the only thing a caller needs: it returns the variables to add to the test gate's environment.
"""

import os
import shlex
import uuid
from collections.abc import Callable, Collection, Mapping, Sequence
from pathlib import Path

from l4.config.schema import L4Config

RC_NAME = "coveragerc"
STATUS_NAME = "status.json"
JSON_NAME = "coverage.json"
NONCE_NAME = "nonce"


def project_python(cfg: L4Config, repo: Path, which: Callable[[str], str | None]) -> Path | None:
    """The interpreter the unit gate runs: the first word of `gates.test.command` when it is a Python, else the
    repository's `.venv`. Shared by the doctor's COV-001 (before `gates.setup`) and the run's check after it."""
    try:
        words = shlex.split(cfg.gates.test.command)
    except ValueError:
        words = []
    first = words[0] if words else ""
    if first and Path(first).name.startswith("python"):
        found = (repo / first) if "/" in first else (Path(w) if (w := which(first)) else None)
        if found is not None and found.exists():
            return found
    venv = repo / ".venv" / "bin" / "python"
    return venv if venv.exists() else None


def is_python_gate(command: str) -> bool:
    """Does the test gate run Python? An empty command is taken to (the default `gates.test` is pytest); a
    command with no Python word in it (`npm test`, `npx vitest run`, `dotnet test`) does not."""
    try:
        words = shlex.split(command)
    except ValueError:
        words = []
    names = [Path(w).name for w in words]
    return not words or any(n.startswith("python") or n in ("pytest", "py.test", "tox", "nox") for n in names)


def plugin_dir() -> Path:
    return Path(__file__).resolve().parent / "pytest_cov"


def write_rc(out_dir: Path, packages: Sequence[str]) -> Path:
    """The rc file the repository cannot change. `packages` are directories (relative to the test run's working
    directory): unimported files in them are reported with every line missing. Exclusions, including
    `pragma: no cover`, are switched off, so a pragma cannot hide a changed line."""
    for p in packages:
        if any(ord(c) < 32 or ord(c) == 127 for c in p) or p[:1] in ("[", "#", ";", "") or p != p.strip():
            raise ValueError(f"unsafe coverage source: {p.encode('unicode_escape').decode()!r}")
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in (STATUS_NAME, JSON_NAME, NONCE_NAME, *(p.name for p in out_dir.glob(".coverage*"))):
        (out_dir / stale).unlink(missing_ok=True)  # an earlier round's output must not pass for this one's
    lines = [
        "[run]",
        f"data_file = {out_dir / '.coverage'}",
        "dynamic_context = test_function",
        "relative_files = True",
        "branch = False",
        "parallel = False",
        "disable_warnings = module-not-imported, no-data-collected, module-not-measured, couldnt-parse",
    ]
    if packages:
        lines.append("source =")
        lines += [f"    {p.replace('$', '$$')}" for p in packages]
    lines += [
        "", "[report]", "exclude_lines =", "exclude_also =", "include_namespace_packages = True",
        "", "[json]", "show_contexts = True", "",
    ]  # fmt: skip
    rc = out_dir / RC_NAME
    rc.write_text("\n".join(lines), encoding="utf-8")
    return rc


def cov_env(out_dir: Path, packages: Sequence[str]) -> dict[str, str]:
    """`PYTEST_ADDOPTS` / `PYTHONPATH` that load the plugin, `L4_COV_RC`, and `L4_COV_NONCE`. Writes the rc file,
    clears the directory of earlier output and records the per-run nonce the plugin must echo into `status.json`.
    `packages` are relative to the working directory of the test run: the gate must run from the repository root."""
    rc = write_rc(out_dir, packages)
    nonce = uuid.uuid4().hex
    (out_dir / NONCE_NAME).write_text(nonce, encoding="utf-8")
    return {
        "PYTEST_ADDOPTS": "-p l4_cov", "PYTHONPATH": str(plugin_dir()), "L4_COV_RC": str(rc), "L4_COV_NONCE": nonce,
    }  # fmt: skip


def merge_pytest_env(*envs: Mapping[str, str]) -> dict[str, str]:
    """Join `PYTEST_ADDOPTS` with spaces and `PYTHONPATH` with `os.pathsep` (empty values dropped); for any other
    key the last value wins. Two harness plugins in one run (C-M16-1) need both."""
    merged: dict[str, str] = {}
    for env in envs:
        for key, value in env.items():
            if key in ("PYTEST_ADDOPTS", "PYTHONPATH") and value:
                sep = " " if key == "PYTEST_ADDOPTS" else os.pathsep
                merged[key] = f"{merged[key]}{sep}{value}" if merged.get(key) else value
            elif key not in ("PYTEST_ADDOPTS", "PYTHONPATH"):
                merged[key] = value
    return merged


def junit_ids(contexts: Collection[str], report_ids: Collection[str]) -> set[str]:
    """JUnit ids (`classname::name`) of the tests behind coverage contexts. A context is `<module>.<function>` as
    pytest imported the module (`test_x.test_a`, `test_x.TestC.test_m`), while the JUnit classname starts at the
    rootdir (`tests.test_x`); so the match is on the dotted suffix. A parametrized id matches its base function."""
    wanted = {c.split("|", 1)[0] for c in contexts if c}
    found: set[str] = set()
    for test_id in report_ids:
        classname, _, name = test_id.rpartition("::")
        dotted = f"{classname}.{name.split('[', 1)[0]}" if classname else name.split("[", 1)[0]
        if any(dotted == w or dotted.endswith("." + w) for w in wanted):
            found.add(test_id)
    return found
