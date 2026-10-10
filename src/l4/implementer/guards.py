"""The green-phase freeze (SPEC L4-IMP-002, L4-IMP-006): the red tests and the test-support files are put back.

`FreezeManifest` records, at the red commit, a hash per frozen file: every test file red changed or added, and every
file that matches `tdd.test_support_globs`. After the green agent step `restore_frozen` compares, restores what
differs from the red commit and removes support files that did not exist there. Adapter permission rules are no
freeze (shell redirects write under `Edit(./**)`, spikes/01), so this runs for every adapter.
M1: the test-runner sections of `tdd.runner_config_files`, `scan_test_tamper` on the AST, `revert_gate_config`,
`fold_agent_commits` (sandbox-security 1.16 drops agent commits instead), the red-scope stub guard.
"""

import ast
import hashlib
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from l4.agents.base import EventSink
from l4.security.protected import glob_match, untracked_files
from l4.vcs.git import Git

Kind = Literal["test", "support"]
# An ignore file decides what `git add` and `git status` hide: green must not be able to plant a support file and
# list it in .gitignore. They are frozen like support files.
IGNORE_FILE_GLOBS = (".gitignore", "**/.gitignore")


@dataclass(frozen=True)
class FrozenFile:
    sha256: str | None  # None: the file is a symlink or unreadable at the red commit (it is restored regardless)
    kind: Kind


@dataclass(frozen=True)
class FreezeManifest:
    red_sha: str
    files: dict[str, FrozenFile]
    support_globs: tuple[str, ...]


def _matches(globs: Sequence[str], path: str) -> bool:
    return any(glob_match(glob, path) for glob in globs)


def _names(raw: bytes) -> list[str]:
    return [os.fsdecode(part) for part in raw.split(b"\0") if part]


def _digest(root: Path, relative: str) -> str | None:
    path = root / relative
    if path.is_symlink() or not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_manifest(
    git: Git, red_sha: str, base_sha: str, *, test_globs: Sequence[str], support_globs: Sequence[str]
) -> FreezeManifest:
    """`git` runs in the worktree, which is at `red_sha`."""
    support_globs = (*support_globs, *IGNORE_FILE_GLOBS)
    changed = _names(git.run_bytes("diff", "--name-only", "-z", "--no-renames", "--diff-filter=AM", base_sha, red_sha))
    tracked = _names(git.run_bytes("ls-tree", "-r", "--name-only", "-z", red_sha))
    files: dict[str, FrozenFile] = {}
    for path in sorted({*changed, *tracked}):
        if _matches(support_globs, path):
            kind: Kind = "support"
        elif path in changed and _matches(test_globs, path):
            kind = "test"
        else:
            continue
        files[path] = FrozenFile(_digest(git.repo, path), kind)
    return FreezeManifest(red_sha, files, tuple(support_globs))


def manifest_at_head(
    git: Git, head: str, paths: Sequence[str], *, support_globs: Sequence[str]
) -> FreezeManifest:
    """`paths` as they are in the work tree now (HEAD is `head`): what a step that has no red phase of its own may not
    change. Support files and ignore files are frozen like in green; a path that is not a file at HEAD is left out."""
    support_globs = (*support_globs, *IGNORE_FILE_GLOBS)
    files = {
        p: FrozenFile(digest, "test")
        for p in sorted(set(paths))
        if not _matches(support_globs, p) and (digest := _digest(git.repo, p)) is not None
    }  # a path a later red renamed or deleted has no proof left to protect, and `git checkout` could not restore it
    tracked = _names(git.run_bytes("ls-tree", "-r", "--name-only", "-z", head))
    for path in tracked:
        if _matches(support_globs, path):
            files[path] = FrozenFile(_digest(git.repo, path), "support")
    return FreezeManifest(head, files, tuple(support_globs))


# Names pytest gives a meaning at a module's top level: a mark or a plugin list that reaches every test of the file,
# xunit setup and teardown that run around them, a hook (`pytest_generate_tests` parametrises them), and dunders.
_MODULE_HOOKS = re.compile(
    r"^(?:pytestmark|pytest_\w+|setup|teardown|setup_module|teardown_module|setup_function|teardown_function"
    r"|setUpModule|tearDownModule|__\w+__)$"
)


def _bound(node: ast.stmt) -> set[str]:
    """The names a top-level statement binds (a def, a class, an assignment target, an import)."""
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
        return {node.name}
    if isinstance(node, ast.Import | ast.ImportFrom):
        return {(a.asname or a.name).split(".")[0] for a in node.names}
    targets: list[ast.expr] = []
    if isinstance(node, ast.Assign):
        targets = list(node.targets)
    elif isinstance(node, ast.AnnAssign | ast.AugAssign):
        targets = [node.target]
    return {n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name)}


def _requested(body: Sequence[ast.stmt]) -> set[str]:
    """The fixture names the file's own tests ask for: every parameter of a function it defines and every name of a
    `usefixtures` mark. An added binding of one (an imported or aliased fixture) would replace what those tests get."""
    names: set[str] = set()
    for node in ast.walk(ast.Module(body=list(body), type_ignores=[])):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            a = node.args
            names |= {arg.arg for arg in (*a.posonlyargs, *a.args, *a.kwonlyargs)}
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "usefixtures":
            names |= {arg.value for arg in node.args if isinstance(arg, ast.Constant) and isinstance(arg.value, str)}
    return names


def _pytest_mark(expr: ast.expr) -> bool:
    """`pytest.mark.<name>`, `pytest.mark.<name>(...)` or `pytest.param(...)`: the only calls an added statement may
    make while the module is imported."""
    func = expr.func if isinstance(expr, ast.Call) else expr
    chain: list[str] = []
    while isinstance(func, ast.Attribute):
        chain.insert(0, func.attr)
        func = func.value
    return isinstance(func, ast.Name) and func.id == "pytest" and (chain[:1] == ["mark"] or chain == ["param"])


def _inert(*exprs: ast.expr | None) -> bool:
    """Evaluating these at import runs no code of the test's choosing: no call but a pytest mark, and no `:=` (it
    binds a module name from inside an expression)."""
    nodes = (node for expr in exprs if expr is not None for node in ast.walk(expr))
    return not any(isinstance(n, ast.NamedExpr) or (isinstance(n, ast.Call) and not _pytest_mark(n)) for n in nodes)


def _plain_target(target: ast.expr) -> bool:
    if isinstance(target, ast.Tuple | ast.List):
        return all(_plain_target(t) for t in target.elts)
    return isinstance(target.value, ast.Name) if isinstance(target, ast.Starred) else isinstance(target, ast.Name)


def _defines_only(node: ast.stmt, *, top: bool) -> bool:
    """An added statement that only defines: a test, a class of tests, a constant or an import, whose definition runs
    nothing at import but pytest marks. A fixture, a decorator, a default, a class body or a value that calls anything
    else could reach the tests the file already has (an autouse fixture, a patch made at import)."""
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        a = node.args
        annotations = [arg.annotation for arg in (*a.posonlyargs, *a.args, *a.kwonlyargs, a.vararg, a.kwarg) if arg]
        return (
            (top or not node.name.startswith("__"))
            and all(_pytest_mark(d) for d in node.decorator_list)
            and _inert(*node.decorator_list, *a.defaults, *a.kw_defaults, node.returns, *annotations)
        )
    if isinstance(node, ast.ClassDef):
        return (
            not node.keywords  # a metaclass runs code when the class is made
            and all(_pytest_mark(d) for d in node.decorator_list)
            and _inert(*node.decorator_list, *node.bases)
            and all(_defines_only(statement, top=False) for statement in node.body)
        )
    if isinstance(node, ast.Assign):
        return all(_plain_target(t) for t in node.targets) and _inert(node.value)
    if isinstance(node, ast.AnnAssign):
        return _plain_target(node.target) and _inert(node.annotation, node.value)
    if isinstance(node, ast.Import | ast.ImportFrom):
        return top and all(a.name != "*" for a in node.names)
    return not top and (
        isinstance(node, ast.Pass) or (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant))
    )  # a class body's `pass` or docstring


def appended_only(base: str, head: str) -> bool:
    """True when `head` is `base` plus new top-level definitions (M1.11 decision 7): every top-level statement of `base`
    survives, unchanged and in order (`ast.dump`: comments and layout do not count), so nothing existing was edited or
    removed; and every statement added only defines (`_defines_only`) and binds no name that `base` binds, that the
    file's tests request as a fixture, or that pytest reads at module level (`pytestmark`, `setup_module`,
    `pytest_generate_tests`, ...). Python rebinds a name, so an appended `def test_x(): pass` would shadow a proof test
    while its id stays present and passing; an appended autouse fixture, fixture override, module mark or call made at
    import would make the proof tests pass whatever the code does (m1.11 review). A file that does not parse is not
    appended-only. M1: a new test file can still patch the code at import (as one green adds can): not checked here."""
    try:
        before, after = ast.parse(base).body, ast.parse(head).body
    except (SyntaxError, ValueError):
        return False
    bound = {name for node in before for name in _bound(node)}
    requested = _requested(before)
    kept = 0
    for node in after:
        if kept < len(before) and ast.dump(node) == ast.dump(before[kept]):
            kept += 1
            continue
        if isinstance(node, ast.Import | ast.ImportFrom) and _same_import(node, before):
            continue  # a repeated `import pytest` is no rebinding
        names = _bound(node)
        if not _defines_only(node, top=True) or names & (bound | requested) or any(map(_MODULE_HOOKS.match, names)):
            return False
        bound |= names
    return kept == len(before)


def _same_import(node: ast.stmt, before: Sequence[ast.stmt]) -> bool:
    """An import the file already has (a repeated `import pytest` is no rebinding)."""
    return any(ast.dump(node) == ast.dump(old) for old in before)


def restore_frozen(
    git: Git,
    manifest: FreezeManifest,
    *,
    events: EventSink | None = None,
    excludes: Path | None = None,
    phase: str = "green",
) -> list[str]:
    """Put every frozen file back to its content at the red commit and remove new support files. A test file is
    reported as `guard.test_tamper`, a support file as `guard.violation`. Returns the paths touched. `excludes` is
    the harness's ignore file; the red commit's ignore rules hide installed dependencies (a `fixtures` directory
    inside `.venv` is not a support file)."""
    root = git.repo
    touched: list[tuple[str, str]] = []
    restore = []
    for path, frozen in manifest.files.items():
        target = root / path
        if frozen.sha256 is None or target.is_symlink() or _digest(root, path) != frozen.sha256:
            restore.append(path)
            touched.append((path, "guard.test_tamper" if frozen.kind == "test" else "guard.violation"))
    if restore:
        for path in restore:
            if (root / path).is_symlink():
                (root / path).unlink()
        git.run("checkout", manifest.red_sha, "--", *[f":(literal){p}" for p in restore])
    # the ignore rules of the red commit, not the work tree's: a file the agent listed in .gitignore is still a planted
    # file, and an ignored dependency directory is not (cf. protected.changed_paths)
    for path in untracked_files(git, manifest.red_sha, excludes=excludes):
        if path not in manifest.files and _matches(manifest.support_globs, path):
            (root / path).unlink()
            touched.append((path, "guard.violation"))
    if events is not None:
        for path, event in touched:
            events.append(event, path=path, phase=phase)
    return [path for path, _ in touched]
