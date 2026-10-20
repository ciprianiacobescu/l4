"""What gate and runner configuration is, and how a change to it is seen (SPEC L4-IMP-040; design D6, D6.1).

*Gate configuration* is what a lint, type-check, build or scanner gate reads to judge the code: `mypy.ini`, `ruff.toml`,
the `[tool.mypy]` section of `pyproject.toml`, the script a gate command runs. *Runner configuration* is what the test
run reads: `pytest.ini`, `.coveragerc`, `[tool.pytest.ini_options]`, `addopts`, plugins, `jest` in `package.json`. A
step that can rewrite either can make its own gates pass, so both are put back to the step base unless a person allowed
it (L4-IMP-041). Everything else in a manifest (dependencies, project metadata) and the lock files stay free.

A *whole file* is compared by its bytes. A *section* of a manifest is compared by its parsed value (TOML, INI, JSON), so
a comment or a key order is no change. One exception is made for a pytest `markers` list (owner decision 5): a step may
ADD entries, since a new test needs its marker registered; removing or changing an entry, or any other runner key
(`asyncio_mode`, `addopts`, plugins), is a change.
"""

import configparser
import fnmatch
import json
import os
import posixpath
import shlex
import tomllib
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from l4.config.schema import L4Config
from l4.fsutil import LinkedPath, UnsafeFile, read_inside, unlink_inside, write_inside
from l4.security.protected import changed_paths, glob_match, untracked_files
from l4.specs.base import Task
from l4.vcs.errors import GitError
from l4.vcs.git import Git
from l4.verifier.scan import task_tags

if TYPE_CHECKING:  # the workbench imports this module for the gate guard
    from l4.implementer.workbench import Workbench

Kind = Literal["gate", "runner"]
KINDS: tuple[Kind, ...] = ("gate", "runner")

MANIFESTS = ("pyproject.toml", "setup.cfg", "tox.ini", "package.json")
# whole files that are runner configuration whatever `tdd.runner_config_files` holds (design D6)
RUNNER_FILES = ("pytest.ini", ".pytest.ini", "pytest.toml", ".pytest.toml", ".coveragerc")
# pytest files that are parsed for the `markers` exception; the others are compared by bytes
PYTEST_INI = ("pytest.ini", ".pytest.ini")
PYTEST_TOML = ("pytest.toml", ".pytest.toml")

_PYPROJECT_GATE = (
    "mypy", "ruff", "pylint", "pyright", "basedpyright", "black", "isort", "flake8", "bandit", "pydocstyle",
    "codespell",
)  # fmt: skip
_PYPROJECT_RUNNER = ("pytest", "coverage")
_CFG_GATE = ("mypy", "mypy-*", "flake8", "pylint*", "isort", "pycodestyle", "pydocstyle", "bandit")
_CFG_RUNNER = ("tool:pytest", "pytest", "coverage:*")
_JSON_GATE = ("eslintConfig", "eslintIgnore", "prettier", "stylelint")
_JSON_RUNNER = ("jest", "mocha", "nyc", "c8", "ava")
_BROKEN = object()  # a file that does not parse

MAX_BYTES = 4 * 1024 * 1024  # a configuration file the guard reads
View = dict[str, tuple[Kind, Any]]


def _at_any_depth(globs: list[str] | tuple[str, ...], path: str) -> bool:
    return any(glob_match(g, path) or glob_match(f"**/{g}", path) for g in globs)


def _basename(path: str) -> str:
    return path.rsplit("/", 1)[-1]


# --- the script entries a gate command runs (D6.1) -------------------------------------------------------------------

_SPLITTERS = ("&&", "||", ";", "|")
_WRAPPERS = ("env", "uv", "poetry", "npx", "pnpm", "command", "exec")


def _simple_commands(command: str, depth: int = 0) -> list[list[str]]:
    """The simple commands of `command`: `shlex` tokens cut at `&&`, `||`, `;` and `|`. `sh -c '<text>'` (and `bash
    -c`) is split once more."""
    try:
        tokens = shlex.split(command)
    except ValueError:
        return []
    commands: list[list[str]] = [[]]
    for token in tokens:
        if token in _SPLITTERS:
            commands.append([])
        else:
            commands[-1].append(token)
    out: list[list[str]] = []
    for simple in commands:
        if not simple:
            continue
        if depth == 0 and len(simple) >= 3 and simple[0] in ("sh", "bash", "zsh") and simple[1] == "-c":
            out += _simple_commands(simple[2], depth + 1)
        else:
            out.append(simple)
    return out


def _strip(simple: list[str]) -> list[str]:
    """Without leading `VAR=value`, `env`, `uv run`, `poetry run`, `npx`, `pnpm exec` and a `.venv/bin/` prefix."""
    words = list(simple)
    while words:
        head = words[0]
        assignment = (
            "=" in head and not head.startswith(("-", "/", ".")) and head.split("=", 1)[0].replace("_", "").isalnum()
        )
        if assignment or head in ("env", "npx", "command", "exec"):
            words.pop(0)
        elif head in ("uv", "poetry", "pnpm") and len(words) > 1 and words[1] in ("run", "exec"):
            if head == "pnpm" and words[1] == "run":
                break  # `pnpm run lint` is a package script, not a wrapper
            del words[:2]
        else:
            break
    if words and words[0].startswith(".venv/bin/"):
        words[0] = words[0].removeprefix(".venv/bin/")
    return words


def _is_script_path(arg: str, root: Path) -> bool:
    if not arg or arg.startswith(("-", "/", "~")) or ".." in arg.split("/"):
        return False
    path = root / arg
    return path.is_file() or (not path.exists() and bool(Path(arg).suffix))


def _script_keys(words: list[str], root: Path) -> list[str]:
    """The files and manifest sections that a simple command runs (D6.1); empty when it resolves to nothing."""
    if not words:
        return []
    head, args = words[0], words[1:]
    if head in ("sh", "bash", "zsh", "python", "python3", "node"):
        first = args[0] if args else ""
        return [posixpath.normpath(first)] if _is_script_path(first, root) else []
    if head == "make":
        return ["Makefile", "makefile", "GNUmakefile"]
    if head == "just":
        return ["justfile", "Justfile", ".justfile"]
    if head == "tox":
        return ["tox.ini"]
    if head == "poe":
        return ["tool.poe"]
    if head in ("npm", "pnpm", "yarn"):
        rest = [a for a in args if not a.startswith("-")]
        if rest and rest[0] == "run":
            rest = rest[1:]
        elif head == "npm" and rest and rest[0] not in ("test", "start"):
            return []
        if not rest:
            return []
        name = rest[0]
        return [f"scripts.{name}", f"scripts.pre{name}", f"scripts.post{name}"]
    if head.startswith(("./", "scripts/")) or "/" in head:
        cleaned = posixpath.normpath(head)
        return [cleaned] if _is_script_path(cleaned, root) else []
    return []


def resolve_scripts(commands: Mapping[Kind, list[str]], root: Path) -> dict[str, Kind]:
    """Script path or manifest section -> kind, for the commands of each kind. A runner entry wins over a gate one."""
    found: dict[str, Kind] = {}
    for kind in ("gate", "runner"):  # runner last: it wins
        for command in commands.get(kind, []):
            for simple in _simple_commands(command):
                for key in _script_keys(_strip(simple), root):
                    found[key] = kind
    return found


# --- parsing ---------------------------------------------------------------------------------------------------------


def _toml(data: bytes) -> Any:
    try:
        return tomllib.loads(data.decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError):
        return _BROKEN


def _ini(data: bytes) -> Any:
    parser = configparser.RawConfigParser(strict=False, interpolation=None)
    parser.optionxform = str  # type: ignore[assignment, method-assign]
    try:
        parser.read_string(data.decode("utf-8"))
    except (configparser.Error, UnicodeDecodeError):
        return _BROKEN
    return {name: dict(parser.items(name)) for name in parser.sections()}


def _json(data: bytes) -> Any:
    try:
        value = json.loads(data.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, RecursionError):
        return _BROKEN
    return value if isinstance(value, dict) else _BROKEN


def _markers(value: Any) -> set[str] | None:
    """The marker entries of a pytest `markers` value: an INI string (one entry per line) or a TOML list."""
    if isinstance(value, str):
        return {line.strip() for line in value.splitlines() if line.strip()}
    if isinstance(value, list) and all(isinstance(entry, str) for entry in value):
        return {entry.strip() for entry in value}
    return None


def _same_but_for_new_markers(before: Any, after: Any) -> bool:
    """Owner decision 5: the pytest settings `before` and `after` (a mapping each) are the same except that `after` has
    more `markers` entries. Removing or changing an entry, or any other key, is a difference."""
    if not isinstance(before, dict) or not isinstance(after, dict):
        return False
    if {k: v for k, v in before.items() if k != "markers"} != {k: v for k, v in after.items() if k != "markers"}:
        return False
    old, new = _markers(before.get("markers", "")), _markers(after.get("markers", ""))
    return old is not None and new is not None and old <= new


def _equal(name: str, before: Any, after: Any) -> bool:
    """Are two parsed section values the same, for the guard? `pytest` sections accept new `markers` entries."""
    if before == after:
        return True
    if name in ("pytest", "tool:pytest"):
        return _same_but_for_new_markers(before, after)
    if name == "tool.pytest" and isinstance(before, dict) and isinstance(after, dict):
        old = {k: v for k, v in before.items() if k != "ini_options"}
        new = {k: v for k, v in after.items() if k != "ini_options"}
        return old == new and _same_but_for_new_markers(before.get("ini_options", {}), after.get("ini_options", {}))
    return False


def _is_section(key: str) -> bool:
    """A key of `GateConfig.scripts` that names a section of a manifest, not a file."""
    return key.startswith(("scripts.", "tool."))


@dataclass(frozen=True)
class GateConfig:
    globs: tuple[tuple[str, Kind], ...]  # whole-file globs and their kind (a runner glob wins over a gate glob)
    scripts: dict[str, Kind]  # a script path, or a manifest section such as `scripts.lint` or `tool.poe` (D6.1)

    @classmethod
    def of(cls, cfg: L4Config, root: Path) -> "GateConfig":
        tdd = cfg.tdd
        gate = [(g, "gate") for g in dict.fromkeys([*tdd.gate_config_globs, *tdd.extra_gate_config_globs])]
        runner_files = [*RUNNER_FILES, *(g for g in tdd.runner_config_files if g not in MANIFESTS)]
        runner = [(g, "runner") for g in dict.fromkeys(runner_files)]
        gates = cfg.gates
        commands: dict[Kind, list[str]] = {
            "gate": [*gates.build, *gates.lint, *gates.typecheck, *(g.command for g in gates.extra)],
            "runner": [c for c in (gates.test.command, gates.e2e.command) if c],
        }
        return cls(tuple([*gate, *runner]), resolve_scripts(commands, root))  # type: ignore[arg-type]

    # -- what a path is --

    def _glob_kind(self, path: str) -> Kind | None:
        """The kind of the whole-file glob that matches `path`: runner wins over gate."""
        kinds = {kind for glob, kind in self.globs if _at_any_depth([glob], path)}
        return "runner" if "runner" in kinds else "gate" if kinds else None

    def _script_file(self, path: str) -> Kind | None:
        key = posixpath.normpath(path)
        return self.scripts.get(key) if not _is_section(key) else None

    def kinds(self, path: str) -> frozenset[Kind]:
        """The kinds of configuration `path` holds: empty when it is none; a manifest can hold both."""
        found: set[Kind] = set()
        if (kind := self._glob_kind(path)) is not None:
            found.add(kind)
        if (kind := self._script_file(path)) is not None:
            found.add(kind)
        if _basename(path) in MANIFESTS:
            found |= {"gate", "runner"}
        return frozenset(found)

    # -- what a file says --

    def _whole_kind(self, path: str) -> Kind | None:
        """The kind of a path that is guarded as a whole file (by its bytes), or None when it is guarded by sections."""
        name = _basename(path)
        if name in PYTEST_INI + PYTEST_TOML:
            return None  # parsed, for the `markers` exception
        if (kind := self._glob_kind(path)) is not None:
            return kind
        if name == "tox.ini":
            return self.scripts.get("tox.ini")  # the gate runs tox: the whole file is the script
        return None if name in MANIFESTS else self._script_file(path)

    def _sections(self, path: str, data: bytes) -> View | None:
        """The guarded sections of a parsed file; None when it does not parse. Whole files have the one section ""."""
        name = _basename(path)
        if (whole := self._whole_kind(path)) is not None:
            return {"": (whole, data)}
        if name in PYTEST_INI:
            parsed = _ini(data)
            return None if parsed is _BROKEN else {sec: ("runner", value) for sec, value in parsed.items()}
        if name in PYTEST_TOML:
            parsed = _toml(data)
            return None if parsed is _BROKEN else {sec: ("runner", value) for sec, value in parsed.items()}
        if name not in MANIFESTS:
            return {}
        parsed = {"pyproject.toml": _toml, "package.json": _json}.get(name, _ini)(data)
        if parsed is _BROKEN:
            return None
        view: View = {}
        if name == "pyproject.toml":
            tool = parsed.get("tool", {})
            for key, value in tool.items() if isinstance(tool, dict) else ():
                if key.startswith(_PYPROJECT_RUNNER):
                    view[f"tool.{key}"] = ("runner", value)
                elif key.startswith(_PYPROJECT_GATE):
                    view[f"tool.{key}"] = ("gate", value)
                elif key == "poe" and "tool.poe" in self.scripts:
                    view["tool.poe"] = (self.scripts["tool.poe"], value)
        elif name == "package.json":
            for key, value in parsed.items():
                if key in _JSON_GATE:
                    view[key] = ("gate", value)
                elif key in _JSON_RUNNER:
                    view[key] = ("runner", value)
            scripts = parsed.get("scripts", {})
            for key, value in scripts.items() if isinstance(scripts, dict) else ():
                if (kind := self.scripts.get(f"scripts.{key}")) is not None:
                    view[f"scripts.{key}"] = (kind, value)
            if isinstance(scripts, dict) and "test" in scripts:
                view["scripts.test"] = ("runner", scripts["test"])
        else:  # setup.cfg, tox.ini
            for section, value in parsed.items():
                if any(fnmatch.fnmatchcase(section, p) for p in _CFG_RUNNER):
                    view[section] = ("runner", value)
                elif any(fnmatch.fnmatchcase(section, p) for p in _CFG_GATE):
                    view[section] = ("gate", value)
        return view

    def view(self, path: str, data: bytes | None) -> View:
        """Section name ("" for a whole file) -> (kind, parsed value or bytes), only the guarded sections; absent -> {}.
        A file that does not parse is one `""` section per kind of the path, holding its bytes."""
        if data is None:
            return {}
        sections = self._sections(path, data)
        if sections is not None:
            return sections
        kind = "gate" if "gate" in self.kinds(path) else "runner"
        return {"": (kind, data)}

    def changed(self, path: str, before: bytes | None, after: bytes | None) -> dict[Kind, tuple[str, ...]]:
        """Per kind, the guarded section names (sorted) whose views differ between `before` and `after`; `("",)` is the
        whole file. A file that parses at one end only is changed in every kind the path can hold; a file that parses
        at neither is compared by its bytes."""
        if before == after:
            return {}
        possible = [kind for kind in KINDS if kind in self.kinds(path)]
        old = None if before is None else self._sections(path, before)
        new = None if after is None else self._sections(path, after)
        if (before is not None and old is None) or (after is not None and new is None):
            return {kind: ("",) for kind in possible}  # one end, or both, does not parse and the bytes differ
        old, new = old or {}, new or {}
        out: dict[Kind, list[str]] = {}
        for section in sorted(set(old) | set(new)):
            if section in old and section in new and _equal(section, old[section][1], new[section][1]):
                continue
            kind = (new.get(section) or old[section])[0]
            out.setdefault(kind, []).append(section)
        return {kind: tuple(sections) for kind, sections in out.items()}


# --- the guard after an agent step (D7, D8) --------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfigChange:
    path: str
    kind: Kind
    sections: tuple[str, ...]
    action: str  # restored | removed


def allowed_kinds(phase: str, tags: frozenset[str], *, opened: bool) -> frozenset[Kind]:
    """The kinds of configuration a step of `phase` may change (D8). Gate configuration: a human `[config]` or
    `[test-infra]` tag, or a person's answer that opens the file. Runner configuration: `[test-infra]` or an answer, in
    red and in a fix chore, and never in green (the red-to-green freeze of L4-IMP-002)."""
    kinds: set[Kind] = set()
    if opened or tags & {"config", "test-infra"}:
        kinds.add("gate")
    if phase != "green" and (opened or "test-infra" in tags):
        kinds.add("runner")
    return frozenset(kinds)


def _before(wb: "Workbench", base: str, path: str) -> bytes | None:
    if wb.git.run("cat-file", "-e", f"{base}:{path}", check=False).returncode != 0:
        return None
    return wb.git.run_bytes("show", f"{base}:{path}", check=False)


def _describe(sections: tuple[str, ...]) -> str:
    return ", ".join(s or "the whole file" for s in sections)


def revert_gate_config(
    wb: "Workbench", task: Task, base: str, *, phase: str, opened: Collection[str] = (), attempt: int = 0
) -> list[ConfigChange]:
    """After an agent step (L4-IMP-040): every gate or runner configuration file that differs from the step base `base`
    in a guarded section that the task may not change goes back to `base` WHOLE (a new file is removed). One
    `guard.violation{phase, rule: "gate configuration" | "runner configuration", path, sections, why, action, task,
    attempt}` per kind. A dependency change in the same file is undone with it: the guard note says to write it again.
    Nothing is raised for an unreadable file; it counts as changed."""
    from l4.implementer.stubs import restore_to_base

    gc = GateConfig.of(wb.cfg, wb.worktree)
    tags = task_tags(task.title)
    found: list[ConfigChange] = []
    for path, existed in sorted(changed_paths(wb.git, base, excludes=wb.excludes).items()):
        kinds = gc.kinds(path)
        if not kinds:
            continue
        permitted = allowed_kinds(phase, tags, opened=path in opened)
        try:
            read = read_inside(wb.worktree, path, limit=MAX_BYTES)
            changed = gc.changed(path, _before(wb, base, path), None if read is None else read[0])
        except (UnsafeFile, OSError, ValueError):
            changed = {kind: ("",) for kind in KINDS if kind in kinds}  # unreadable: changed everywhere
        refused = {kind: sections for kind, sections in changed.items() if kind not in permitted}
        if not refused:
            continue
        restore_to_base(wb, base, path)
        action = "restored" if existed else "removed"
        for kind, sections in refused.items():
            found.append(ConfigChange(path, kind, sections, action))
            wb.emit(
                "guard.violation", phase=phase, rule=f"{kind} configuration", path=path, sections=list(sections),
                why=f"changed {_describe(sections)}", action=action, task=task.key, attempt=attempt,
            )  # fmt: skip
    return found


# --- the guard after a gate run (D7) ---------------------------------------------------------------------------------

# path -> (bytes, mode) of a configuration file just before the gate; None: it was there and cannot be read (left alone)
Snapshot = dict[str, tuple[bytes, int] | None]


def _pathspecs(gc: GateConfig) -> list[str]:
    """Git pathspecs that hold every possible configuration file: whole-file globs at any depth, the manifests, and the
    script files a gate command runs."""
    specs = [f":(glob)**/{glob}" if "/" not in glob else f":(glob){glob}" for glob, _ in gc.globs]
    specs += [f":(glob)**/{name}" for name in MANIFESTS]
    specs += [f":(literal){key}" for key in gc.scripts if not _is_section(key)]
    return specs


def config_files(cfg: L4Config, root: Path, git: Git) -> dict[str, frozenset[Kind]]:
    """Every tracked configuration file at HEAD of `root`, with its kinds."""
    gc = GateConfig.of(cfg, root)
    tracked = git.run_bytes("ls-files", "-z", "--", *_pathspecs(gc), check=False).split(b"\0")
    return {path: gc.kinds(path) for p in sorted(tracked) if p and gc.kinds(path := os.fsdecode(p))}


def _candidates(git: Git, gc: GateConfig, excludes: Path | None) -> list[str]:
    """Tracked files (HEAD's index) and untracked files that HEAD's ignore rules do not hide, that are configuration."""
    tracked = git.run_bytes("ls-files", "-z", "--", *_pathspecs(gc), check=False).split(b"\0")
    paths = {os.fsdecode(p) for p in tracked if p}
    try:
        paths |= set(untracked_files(git, "HEAD", excludes=excludes))
    except GitError:  # a checkout with no HEAD: the usual ignore rules decide
        others = git.run_bytes("ls-files", "--others", "--exclude-standard", "-z", check=False).split(b"\0")
        paths |= {os.fsdecode(p) for p in others if p}
    return sorted(p for p in paths if gc.kinds(p))


def _read(root: Path, path: str) -> tuple[bytes, int] | None:
    try:
        return read_inside(root, path, limit=MAX_BYTES)
    except (UnsafeFile, OSError, ValueError):
        return None


def snapshot_config(cfg: L4Config, root: Path, git: Git, excludes: Path | None = None) -> Snapshot:
    """Every configuration file in the checkout `root` as it is just before a gate runs (design D7)."""
    gc = GateConfig.of(cfg, root)
    return {path: _read(root, path) for path in _candidates(git, gc, excludes)}


def restore_config(wb: "Workbench", root: Path, git: Git, snapshot: Snapshot, *, where: str) -> list[ConfigChange]:
    """After a gate run: any gate or runner configuration that differs from `snapshot` is put back to it (a file that
    was not there is removed), recorded as `guard.violation{phase: "gate", rule, path, sections, action, where}`. No
    tag or answer lifts this: no gate has a reason to edit configuration. A write that is refused goes to
    `wb.refused_write`; nothing is raised."""
    gc = GateConfig.of(wb.cfg, root)
    found: list[ConfigChange] = []
    for path in sorted({*snapshot, *_candidates(git, gc, wb.excludes)}):
        before = snapshot.get(path)
        if path in snapshot and before is None:
            continue  # it could not be read before the gate: there is nothing to put back
        now = _read(root, path)
        try:
            changed = gc.changed(path, before[0] if before else None, now[0] if now else None)
        except (ValueError, OSError):
            changed = {}
        if not changed:
            continue
        action = _put_config(wb, root, path, before, where)
        for kind, sections in changed.items():
            found.append(ConfigChange(path, kind, sections, action))
            wb.emit(
                "guard.violation", phase="gate", rule=f"{kind} configuration", path=path, sections=list(sections),
                why=f"changed {_describe(sections)}", action=action, where=where,
            )  # fmt: skip
    return found


def _put_config(wb: "Workbench", root: Path, path: str, before: tuple[bytes, int] | None, where: str) -> str:
    try:
        if before is None:
            unlink_inside(root, path)
            return "removed"
        write_inside(root, path, before[0], mode=before[1])
    except LinkedPath as exc:
        wb.refused_write(exc, path=path, where=where, root=root)
        if before is not None:
            try:
                write_inside(root, path, before[0], mode=before[1])
            except (UnsafeFile, OSError, ValueError) as again:
                wb.refused_write(_unsafe(again), path=path, where=where, root=root)
    except (UnsafeFile, OSError, ValueError) as exc:
        wb.refused_write(_unsafe(exc), path=path, where=where, root=root)
    return "removed" if before is None else "restored"


def _unsafe(exc: BaseException) -> UnsafeFile:
    return exc if isinstance(exc, UnsafeFile) else UnsafeFile(str(exc))
