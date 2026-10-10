"""Scope: does each changed file belong to the feature the unit's spec describes? (verifier 2.11, M1.6 D2 and D3)

Declared scope is what the spec names in backticks: paths, globs and dotted module names. A module is the first path
component under one of `verifier.evidence.module_roots`, else the first component. Prose without backticks, and a
bare name (`inventory`) that is not a path or dotted module name, declare nothing. A spec that declares nothing yields
no label at all (judging every file out of scope would be noise); under `fail` it holds for a human instead.
M1: the snapshot half of verifier 2.11; non-Python import resolution for modified tests.
"""

import ast
import json
import re
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Literal

from l4.config.defaults import MODULE_ROOTS
from l4.config.schema import L4Config
from l4.security.protected import glob_match
from l4.specs.fixmark import MARKER_PATH, MARKER_SCHEMA, split_fix_name
from l4.verifier.types import Finding, Severity

Kind = Literal["code", "test", "root", "exempt"]
Label = Literal["relevant", "out_of_scope"]

HARNESS_PATHS = ("**/.l4/**", "**/.l4-out/**", ".coverage")  # at any depth: a change directory holds its own `.l4/`
SPEC_PATHS = ("openspec/changes/**", ".kiro/specs/**")  # every file of any change or spec directory is spec, not code
_BACKTICKED = re.compile(r"`([^`\n]+)`")
_FENCE = re.compile(r"^```.*?^```", re.S | re.M)
_DOTTED = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$")
_TASK_SUFFIX = re.compile(r"(::.*|:\d+(:\d+)?)$")
_EXTENSIONS = frozenset(
    ("py", "pyi", "js", "jsx", "ts", "tsx", "mjs", "cjs", "go", "rs", "java", "kt", "rb", "php", "cs", "c", "h", "cpp",
     "css", "scss", "html", "vue", "svelte", "sh", "sql", "json", "yaml", "yml", "toml", "cfg", "ini", "txt", "lock",
     "proto")
)  # fmt: skip
_SECTION = re.compile(r"^##\s+(.*?)\s*$")


@dataclass(frozen=True)
class DeclaredScope:
    paths: tuple[str, ...]  # files and directories, by unit file name then first mention
    globs: tuple[str, ...]
    modules: frozenset[str]
    sources: tuple[str, ...]  # the unit files that declared something
    tree_modules: frozenset[str] = frozenset()  # every module of the repository tree: resolves dotted names, imports

    @property
    def empty(self) -> bool:
        return not (self.paths or self.globs or self.modules)


@dataclass(frozen=True)
class ChangedFile:
    path: str  # the head path (the new name of a rename)
    status: Literal["A", "M", "D", "R"] = "M"
    source: str | None = None  # text of a test file, for its imports; None when unavailable
    human: str | None = None  # sha10 of a person's commit when only people's commits changed it (L4-SEC-004, M1.9)


@dataclass(frozen=True)
class FileScope:
    path: str
    module: str | None
    kind: Kind
    label: Label | None
    reason: str


def module_of(path: str, roots: Sequence[str] = MODULE_ROOTS) -> str | None:
    """None for a file at the repository root (it belongs to no module)."""
    parts = PurePosixPath(path).parts
    if len(parts) >= 2 and parts[0] in roots:
        name = parts[1]
        return PurePosixPath(name).stem if len(parts) == 2 and "." in name else name
    return parts[0] if len(parts) >= 2 else None


def _sections(name: str, text: str) -> str:
    """What a unit file may declare: the proposal's `## Impact`, the whole of design and tasks, nothing else."""
    base = PurePosixPath(name).name
    if base in ("design.md", "tasks.md"):
        return text
    if base != "proposal.md":
        return ""
    keep, inside = [], False
    for line in text.splitlines():
        match = _SECTION.match(line)
        if match:
            inside = match.group(1).lower() == "impact"
        elif inside:
            keep.append(line)
    return "\n".join(keep)


def _tokens(text: str) -> Iterable[str]:
    for raw in _BACKTICKED.findall(_FENCE.sub("", text)):
        token = _TASK_SUFFIX.sub("", raw.split("(", 1)[0].strip().rstrip(",;."))
        token = token.removeprefix("./")
        if token and " " not in token and not token.startswith(("/", "~")) and ".." not in token.split("/"):
            yield token


def _literal_prefix(path: str) -> str:
    parts: list[str] = []
    for part in path.split("/"):
        if any(ch in part for ch in "*?["):
            break
        parts.append(part)
    return "/".join(parts)


def declared_scope(
    unit_files: Mapping[str, str], trees: Collection[str], roots: Sequence[str] = MODULE_ROOTS
) -> DeclaredScope:
    """`unit_files`: unit-relative file name -> text (`proposal.md`, `design.md`, `tasks.md`; others are ignored).
    `trees`: the repository's file paths, to tell a module name from a file name."""
    tree_modules = frozenset(m for m in (module_of(p, roots) for p in trees) if m)
    paths: list[str] = []
    globs: list[str] = []
    modules: set[str] = set()
    sources: list[str] = []

    def note(source: str) -> None:
        if source not in sources:
            sources.append(source)

    def add(bucket: list[str], value: str, source: str) -> None:
        if value not in bucket:
            bucket.append(value)
        note(source)

    for name in sorted(unit_files):
        source = PurePosixPath(name).name
        for token in _tokens(_sections(name, unit_files[name])):
            if any(ch in token for ch in "*?["):
                add(globs, token if "/" in token else f"**/{token}", source)
                if module := module_of(_literal_prefix(token), roots):
                    modules.add(module)
            elif "/" in token:
                add(paths, token.rstrip("/"), source)
                if module := module_of(token.rstrip("/"), roots):
                    modules.add(module)
            elif _DOTTED.match(token):
                parts = token.split(".")
                head = parts[1] if parts[0] in roots and len(parts) > 1 else parts[0]
                if head in tree_modules:
                    modules.add(head)
                    note(source)
                elif parts[-1] in _EXTENSIONS:
                    add(globs, f"**/{token}", source)
    return DeclaredScope(tuple(paths), tuple(globs), frozenset(modules), tuple(sources), tree_modules)


UNIT_FILES = ("proposal.md", "design.md", "tasks.md")


def _union(own: DeclaredScope, parent: DeclaredScope) -> DeclaredScope:
    def merged(a: tuple[str, ...], b: tuple[str, ...]) -> tuple[str, ...]:
        return a + tuple(x for x in b if x not in a)

    return DeclaredScope(
        merged(own.paths, parent.paths), merged(own.globs, parent.globs), own.modules | parent.modules,
        merged(own.sources, parent.sources), own.tree_modules,
    )  # fmt: skip


def _fix_parent(read: Callable[[str], str | None], unit_rel: str) -> str | None:
    """The parent unit's folder (a sibling) when `unit_rel` carries a fix marker, else None. Never raises."""
    text = read(f"{unit_rel}/{'/'.join(MARKER_PATH)}")
    if text is None:
        return None
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("schema") != MARKER_SCHEMA or not isinstance(data.get("parent"), str):
        return None
    split = split_fix_name(PurePosixPath(unit_rel).name)  # `<parent>-fix-<n>`: the parent is the sibling folder
    if split is None:
        return None
    return str(PurePosixPath(unit_rel).with_name(split[0]))


def unit_declared_scope(
    read: Callable[[str], str | None], unit_rel: str, trees: Collection[str], roots: Sequence[str] = MODULE_ROOTS
) -> DeclaredScope:
    """The scope a unit declares: its own files, and for a fix unit (`.l4/fix.json`) the union with its parent's. The
    harness-written proposal of a fix unit only says "the code and the tests of `<parent>`", which names nothing, so the
    parent's scope is what the fix is held to. A parent never inherits from its fix units. `read(path)` is the text of
    a repository file at the base, or None."""

    def own(rel: str) -> DeclaredScope:
        files = {n: t for n in UNIT_FILES if (t := read(f"{rel}/{n}")) is not None}
        return declared_scope(files, trees, roots)

    scope = own(unit_rel)
    parent = _fix_parent(read, unit_rel)
    return _union(scope, own(parent)) if parent else scope


def _under(path: str, declared: str) -> bool:
    return path == declared or path.startswith(declared + "/")


def _named(path: str, scope: DeclaredScope) -> bool:
    return any(_under(path, p) for p in scope.paths) or any(glob_match(g, path) for g in scope.globs)


def _imports(source: str, known: frozenset[str]) -> list[str]:
    """Top-level names the module imports that are modules of this repository, sorted."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return sorted(names & known)


def file_kind(path: str, unit_dir: str, cfg: L4Config) -> Kind:
    ev = cfg.verifier.evidence
    if (
        any(glob_match(g, path) for g in (*HARNESS_PATHS, *SPEC_PATHS, *ev.scope_exempt))
        or PurePosixPath(path).name == "questions.md"
        or (unit_dir and _under(path, unit_dir.rstrip("/")))
    ):
        return "exempt"
    if any(glob_match(g, path) for g in cfg.tdd.test_globs):
        return "test"
    return "root" if "/" not in path else "code"


def classify_files(
    changed: Sequence[ChangedFile], scope: DeclaredScope, cfg: L4Config, *, unit_dir: str = ""
) -> list[FileScope]:
    roots = cfg.verifier.evidence.module_roots
    out: list[FileScope] = []
    for file in changed:
        path = file.path
        kind: Kind = "exempt" if file.human else file_kind(path, unit_dir, cfg)
        module = module_of(path, roots) if kind == "code" else None
        label: Label | None = None
        if file.human:
            reason = f"changed by human commit {file.human}"
        elif kind in ("exempt", "root"):
            reason = "exempt: harness, spec or documentation path" if kind == "exempt" else "root file, not judged"
        elif scope.empty:
            reason = "the spec declares no scope"
        elif kind == "code":
            if _named(path, scope):
                label, reason = "relevant", "named in the spec"
            elif module in scope.modules:
                label, reason = "relevant", f"module `{module}` is named in the spec"
            else:
                label, reason = "out_of_scope", f"module `{module}` is not named in the spec"
        elif file.status == "A":
            label, reason = "relevant", "new test file"
        elif _named(path, scope):
            label, reason = "relevant", "named in the spec"
        else:
            imported = _imports(file.source, scope.tree_modules) if file.source else []
            hit = [m for m in imported if m in scope.modules]
            if hit:
                label, module, reason = "relevant", hit[0], f"imports module `{hit[0]}`, named in the spec"
            elif imported:
                label, module = "out_of_scope", imported[0]
                reason = f"imports module `{module}`, which the spec does not name"
            else:
                reason = "imports no module of the repository"
        out.append(FileScope(path, module, kind, label, reason))
    return out


@dataclass(frozen=True)
class ScopeContext:
    changed: Sequence[ChangedFile]
    scope: DeclaredScope
    cfg: L4Config
    unit_dir: str = ""


@dataclass
class ScopeOutcome:
    """m13's `Outcome` fields (C-M16-2) plus the holds and the per-file labels."""

    findings: list[Finding] = field(default_factory=list)
    note: str = ""
    skipped: bool = False
    declared: list[str] = field(default_factory=list)
    holds: list[str] = field(default_factory=list)
    hold_paths: list[str] = field(default_factory=list)  # the file each hold is about, parallel to `holds` ("" if none)
    files: list[FileScope] = field(default_factory=list)


def check_scope(ctx: ScopeContext) -> ScopeOutcome:
    """Labels are always produced; the policy (`sdd.scope_check`) decides what an out-of-scope file costs:
    `off` nothing, `warn` one hold per file (NEEDS_HUMAN), `fail` a deterministic major finding (FAIL). Hold text is
    stable per (path, module): no counts, so a later round does not ask an answered hold again (C-M16-3)."""
    policy = ctx.cfg.sdd.scope_check
    files = classify_files(ctx.changed, ctx.scope, ctx.cfg, unit_dir=ctx.unit_dir)
    out = ScopeOutcome(files=files)
    out.declared = [*ctx.scope.paths, *ctx.scope.globs, *(f"module {m}" for m in sorted(ctx.scope.modules))]
    if ctx.scope.empty:
        out.skipped, out.note = True, "the spec names no path or module in backticks: nothing to compare against"
        changed_modules = sorted({str(f.module) for f in files if f.kind == "code"})
        if policy == "fail" and changed_modules:  # fail-closed, like diff coverage: no scope is not a pass
            out.holds.append(
                "scope: the spec declares no path or module; the changed modules are "
                + ", ".join(f"`{m}`" for m in changed_modules)
            )
            out.hold_paths.append("")
        return out
    for file in files:
        if file.label != "out_of_scope" or policy == "off":
            continue
        text = f"scope: `{file.path}` changes module `{file.module}`, which the spec does not name"
        if policy == "warn":
            out.holds.append(text)
            out.hold_paths.append(file.path)
        else:
            out.findings.append(
                Finding(Severity.MAJOR, f"change outside the feature: {file.path}", text, "deterministic")
            )
    return out
