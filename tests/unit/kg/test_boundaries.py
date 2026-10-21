"""The boundary of the experience graph (L4-KG-001, design D1; SCN-KG-01, SCN-KG-02).

Three checks, from the cheapest to the most direct:

- statically, an AST scan of `src/l4/**` finds no import of `l4.kg` outside `src/l4/kg/`, none of `l4.memory.promote`
  or `l4.memory.inbox` outside `l4.memory.cli` (and `promote` itself, which needs the inbox), and no import from
  `src/l4/kg/` of an agent, a model, a forge, a sandbox, a push, a refresh or a network module;
- dynamically, a fresh interpreter imports the run-path modules and finds none of those modules in `sys.modules`;
- by behaviour, the four commands run on a fixture repository with `socket.socket` patched to raise and a recording
  `Git` that refuses every subcommand outside the read-only list.
"""

import ast
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from l4.cli import main
from l4.kg import cli as kg_cli

SRC = Path(__file__).resolve().parents[3] / "src"
L4 = SRC / "l4"

RUN_PATH = (
    "l4.cli", "l4.orchestrator", "l4.planner", "l4.verifier.ladder", "l4.state.status", "l4.ci.sweeper", "l4.archive",
    "l4.postmerge", "l4.memory.round", "l4.implementer.tdd", "l4.eval.run",
)  # fmt: skip
KG_ONLY = ("l4.kg",)
MEMORY_ONLY = ("l4.memory.promote", "l4.memory.inbox")
FORBIDDEN_IN_KG = (
    "l4.agents", "l4.llm", "l4.s1", "l4.forge", "l4.sandbox", "l4.availability", "l4.vcs.refresh", "l4.vcs.push",
    "socket", "urllib", "http",
)  # fmt: skip


def module_of(path: Path) -> str:
    parts = list(path.relative_to(SRC).with_suffix("").parts)
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def imports(path: Path) -> set[str]:
    package = module_of(path) if path.name == "__init__.py" else module_of(path).rpartition(".")[0]
    return imports_of(path.read_text(encoding="utf-8"), package)


def imports_of(source: str, package: str) -> set[str]:
    """Every module a source imports, with `from a import b` counted as `a` and as `a.b`; relative names resolved
    against `package` (the package of the importing module)."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                anchor = package.split(".")[: len(package.split(".")) - (node.level - 1)]
                base = ".".join([*anchor, *([base] if base else [])])
            found.add(base)
            found.update(f"{base}.{alias.name}" for alias in node.names)
    return found


def under(name: str, prefixes: tuple[str, ...]) -> bool:
    return any(name == prefix or name.startswith(prefix + ".") for prefix in prefixes)


def test_no_module_outside_kg_imports_the_graph():
    offenders = [
        f"{module_of(path)} imports {name}"
        for path in sorted(L4.rglob("*.py"))
        if not module_of(path).startswith("l4.kg")
        for name in sorted(imports(path))
        if under(name, KG_ONLY)
    ]
    assert offenders == []


def test_promote_and_inbox_are_imported_only_by_the_lessons_command():
    allowed = {"l4.memory.cli": MEMORY_ONLY, "l4.memory.promote": ("l4.memory.inbox",)}
    offenders = [
        f"{module_of(path)} imports {name}"
        for path in sorted(L4.rglob("*.py"))
        for name in sorted(imports(path))
        if under(name, MEMORY_ONLY) and not under(name, allowed.get(module_of(path), ()))
        and module_of(path) not in MEMORY_ONLY  # a module may name itself and its own package path
    ]  # fmt: skip
    assert offenders == []


def test_the_graph_imports_no_agent_model_forge_sandbox_push_or_network_module():
    kg_files = sorted((L4 / "kg").rglob("*.py"))
    assert kg_files
    offenders = [
        f"{module_of(path)} imports {name}"
        for path in kg_files
        for name in sorted(imports(path))
        if under(name, FORBIDDEN_IN_KG)
    ]
    assert offenders == []


def test_the_scan_sees_every_form_of_import():
    source = "import socket\nfrom l4 import forge\nfrom urllib.request import urlopen\nfrom ..vcs import push\n"
    found = imports_of(source, "l4.kg")
    assert {name for name in found if under(name, FORBIDDEN_IN_KG)} == {"socket", "l4.forge", "l4.vcs.push"} | {
        "urllib.request", "urllib.request.urlopen",
    }  # fmt: skip
    assert "l4.kg.store" in imports_of("from . import store", "l4.kg")


def test_the_run_path_never_loads_the_graph_code():
    """SCN-KG-01: a fresh interpreter imports every run-path module."""
    code = (
        "import importlib, sys\n"
        f"for name in {RUN_PATH!r}:\n"
        "    importlib.import_module(name)\n"
        "bad = sorted(m for m in sys.modules if m == 'l4.kg' or m.startswith('l4.kg.')\n"
        "             or m in ('l4.memory.promote', 'l4.memory.inbox'))\n"
        "print('LOADED:' + ','.join(bad))\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False,
        env={"PYTHONPATH": str(SRC), "PATH": "/usr/bin:/bin", "HOME": "/nonexistent"},
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip().splitlines()[-1] == "LOADED:"


INDIRECT = ("l4.agents", "l4.availability", "l4.sandbox", "l4.forge", "l4.llm")


def test_importing_the_graph_loads_no_agent_model_forge_or_sandbox_package_even_transitively():
    """Review #10: the static scan only sees direct imports; a fresh interpreter sees the whole import graph."""
    modules = sorted(module_of(path) for path in (L4 / "kg").rglob("*.py"))
    assert "l4.kg.cli" in modules
    code = (
        "import importlib, sys\n"
        f"for name in {['l4.kg.cli', *modules]!r}:\n"
        "    importlib.import_module(name)\n"
        f"bad = sorted(m for m in sys.modules if any(m == p or m.startswith(p + '.') for p in {INDIRECT!r}))\n"
        "print('LOADED:' + ','.join(bad))\n"
    )
    done = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=False,
        env={"PYTHONPATH": str(SRC), "PATH": "/usr/bin:/bin", "HOME": "/nonexistent"},
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip().splitlines()[-1] == "LOADED:"


# --- by behaviour --------------------------------------------------------------------------------------------------


@pytest.fixture
def history(kg_repo):
    kg_repo.unit("openspec:a", runs=[kg_repo.run(("task.red_ok", {"task": "1.1"}))])
    kg_repo.unit(
        "openspec:a", where="branch",
        runs=[kg_repo.run(kg_repo.restart_event("openspec:a", 1), ("task.red_ok", {"task": "1.1"}))],
        verdicts=[kg_repo.verdict(1, "FAIL", findings=[kg_repo.finding("lint is red")])],
    )  # fmt: skip
    kg_repo.unit("openspec:a", where="attempt:1", runs=[kg_repo.run(("task.red_ok", {"task": "1.1"}))])
    return kg_repo


def test_no_network_no_model_and_read_only_git(history, monkeypatch):
    """SCN-KG-02"""
    for name in ("report", "why", "propose"):  # the real modules, not stand-ins
        assert Path(sys.modules[f"l4.kg.{name}"].__file__).parent == Path(kg_cli.__file__).parent

    def no_socket(*args, **kwargs):
        raise AssertionError("the network was used")

    monkeypatch.setattr(socket, "socket", no_socket)
    recording = history.recording_git()
    monkeypatch.setattr(kg_cli, "Git", lambda repo, environ=None: recording)
    refs, status = history.refs(), history.status()
    environ = {**history.environ, "L4_CACHE": str(history.cache)}
    for args in (("build",), ("report",), ("why", "openspec:a"), ("propose", "--dry-run")):
        assert main(["kg", *args, "--repo", str(history.root)], environ=environ) == 0, args
    assert recording.subcommands
    assert "fetch" not in recording.subcommands and "push" not in recording.subcommands
    assert history.refs() == refs and history.status() == status
