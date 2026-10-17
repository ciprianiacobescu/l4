"""The gates `l4 init` proposes, from `pyproject.toml` (forge-and-ci 1.19, reduced to uv/pytest/ruff; L4-GAT-003).

Only what the file says is used, and every assumption becomes a `# TODO:` line at the top of the config (L4-INS-003):
`dev` as an optional extra gives `uv sync --frozen --extra dev`; `dev` as a dependency group needs no flag (`uv sync`
installs it); every other extra is listed as not installed and `--all-extras` is never written, because a heavy extra
(`embed` pulls torch) must not become every runner's setup. Other ecosystems keep the M0 gates and a TODO.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from l4.gates.pyproject import PyProject, read_pyproject

M0_GATES: dict = {
    "setup": ["uv sync --frozen"],
    "test": {"command": ".venv/bin/python -m pytest --junitxml=.l4-out/junit.xml"},
    "lint": [".venv/bin/ruff check --extend-exclude .l4 ."],  # .l4/vendor is the harness, not the target's code
}
_COVERAGE = {"coverage", "pytest_cov"}


@dataclass(frozen=True)
class PythonEco:
    project: PyProject
    installed: frozenset[str] = frozenset()  # distributions the proposed setup installs
    dev_extra: bool = False
    pyproject: bool = False


@dataclass(frozen=True)
class Proposal:
    gates: dict
    todos: tuple[str, ...] = ()  # one `# TODO:` line each, at the top of the config
    notes: tuple[str, ...] = ()  # what init tells the human
    extras_not_installed: tuple[str, ...] = field(default=())
    toolchains: dict = field(default_factory=dict)  # the proposed `ci.toolchains` (L4-CI-005)


def detect_python(repo: Path) -> PythonEco:
    project = read_pyproject(repo)
    if not project.present:
        return PythonEco(project)
    dev_extra = "dev" in project.extras
    installed = set(project.dependencies) | set(project.groups.get("dev", ()))
    if dev_extra:
        installed |= set(project.extras["dev"])
    return PythonEco(project, frozenset(installed), dev_extra, True)


def propose_gates(eco: PythonEco) -> Proposal:
    if not eco.pyproject:
        return Proposal(
            {
                **M0_GATES,
                "setup": list(M0_GATES["setup"]),
                "lint": list(M0_GATES["lint"]),
                "test": dict(M0_GATES["test"]),
            },
            ("no pyproject.toml: the gates are the uv/pytest/ruff defaults; set gates.setup, gates.test, gates.lint",),
        )
    project = eco.project
    todos: list[str] = []
    notes: list[str] = []
    setup = "uv sync --frozen" + (" --extra dev" if eco.dev_extra else "")
    if eco.dev_extra:
        todos.append("gates.setup installs the `dev` extra (--extra dev); add the extras your tests need")
    elif "dev" in project.groups:
        todos.append("gates.setup is plain `uv sync --frozen`: it installs the `dev` dependency group")
    else:
        todos.append("no `dev` extra or dependency group: gates.setup installs the project dependencies only")
    if not project.has_lock:
        todos.append("there is no uv.lock: run `uv lock` and commit it (gates.setup is frozen and fails without it)")
    others = tuple(sorted(e for e in project.extras if e != "dev"))
    if others:
        notes.append(
            f"extras not installed by gates.setup: {', '.join(others)}; a test that needs one fails until you add "
            "`--extra <name>` to gates.setup (`l4 doctor --adoption` says which)"
        )
    ruff_in = "ruff" in eco.installed
    if ruff_in:
        lint = list(M0_GATES["lint"])
    else:
        lint = []
        where = [f"extra {e}" for e in project.extras_providing("ruff")] + [
            f"group {g}" for g in project.groups_providing("ruff")
        ]
        if where:
            todos.append(
                f"ruff is only in {', '.join(where)}, which gates.setup does not install: add `--extra <name>` to it "
                "and set gates.lint to `.venv/bin/ruff check --extend-exclude .l4 .`"
            )
        else:
            todos.append("ruff is not a dependency: gates.lint is empty; add ruff and set gates.lint to use it")
    if "pytest" not in eco.installed:
        todos.append("pytest is not installed by gates.setup: add the extra or group that provides it")
    if not eco.installed & _COVERAGE:
        notes.append("coverage.py is not installed by gates.setup: diff coverage will be recorded `not_run`")
    gates = {"setup": [setup], "test": dict(M0_GATES["test"]), "lint": lint}
    return Proposal(gates, tuple(todos), tuple(notes), others)


def _package_json(repo: Path) -> dict:
    try:
        data = json.loads((repo / "package.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def detect_toolchains(repo: Path) -> dict:
    """The proposed `ci.toolchains` (L4-CI-005) from what the repository says about its toolchains, at its root: Go
    from `go.work` or else `go.mod` (`version_file`), Node from `.nvmrc` (`version_file`) or else `package.json`
    `engines.node` (`version`), pnpm from `packageManager: "pnpm@X"` (`version: X`, a `+sha` suffix dropped).
    Nothing is proposed for what the files do not name."""
    found: dict = {}
    for name in ("go.work", "go.mod"):
        if (repo / name).is_file():
            found["go"] = {"version_file": name}
            break
    package = _package_json(repo)
    engines = package.get("engines")
    node = engines.get("node") if isinstance(engines, dict) else None
    if (repo / ".nvmrc").is_file():
        found["node"] = {"version_file": ".nvmrc"}
    elif isinstance(node, str) and node.strip():
        found["node"] = {"version": node.strip()}
    manager = package.get("packageManager")
    if isinstance(manager, str) and manager.startswith("pnpm@") and manager[5:].split("+")[0]:
        found["pnpm"] = {"version": manager[5:].split("+")[0]}
    return found


def toolchain_todos(toolchains: dict) -> tuple[str, ...]:
    if not toolchains:
        return ()
    names = ", ".join(toolchains)
    return (
        f"ci.toolchains sets up {names} before L4 in the GitHub workflow (GitLab: the image must provide them); "
        "the gates below are the Python defaults: add the gates of the other languages (gates.setup, build, lint, "
        "test)",
    )
