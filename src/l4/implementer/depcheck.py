"""Is a test a check on a dependency and on no project code? (SPEC L4-IMP-062, design D9)

A test that pins a dependency's version (`importlib.metadata.version("pytest") == pytest.__version__`) passes on the
zero values and at the unit base alike: no variant run can ever show it discriminating. Such a test is *dependency
only*: its function, its `parametrize` lists and its defaults use no name bound to a module inside the repository
(project or test helper), no name bound by a module-level definition of its file other than a constant, no fixture
other than pytest's built-ins and the names of its own `parametrize`, no project code reached by a string
(`pytest.importorskip`, `importlib.import_module`, `__import__`, `request.getfixturevalue`, `sys.modules`), and it reads
a dependency's version with a LITERAL distribution name that the criterion's text names: a call of
`importlib.metadata.version` / `distribution` / `metadata`, or `<dependency>.__version__`. `assert 1 + 1 == 2`,
`json.loads("1") == 1` and `assert pytest.__version__` under a criterion about something else stay not discriminating.

Pure static analysis of the test's file; a file or a function that cannot be found or parsed is not dependency only.
"""

import ast
import builtins
import re
import sys
from collections.abc import Sequence
from pathlib import Path

from l4.implementer.discrimination import _resolve, _test_file
from l4.implementer.workbench import Workbench

BUILTIN_FIXTURES = frozenset(
    {"tmp_path", "tmp_path_factory", "monkeypatch", "capsys", "capsysbinary", "capfd", "capfdbinary", "caplog",
     "recwarn", "request", "pytestconfig"}
)  # fmt: skip
METADATA_CALLS = frozenset({"version", "distribution", "metadata", "distributions"})
_METADATA = frozenset(f"importlib.metadata.{call}" for call in METADATA_CALLS)
_BY_NAME = frozenset({"importorskip", "import_module", "__import__", "getfixturevalue"})  # project code by a string
_Def = ast.FunctionDef | ast.AsyncFunctionDef
_RELATIVE = "."  # a binding to a module of the repository, by a relative import


def _normal(text: str) -> str:
    """Lower case, with every `-`, `_` and `.` as one `-`: `typing_extensions` names `typing-extensions`."""
    return re.sub(r"[-_.]+", "-", text.lower())


def _chain(node: ast.expr) -> list[str] | None:
    """`a.b.c` as ['a', 'b', 'c']; None when the expression is not a plain dotted name."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    return [node.id, *reversed(parts)]


def _constant(node: ast.expr | None) -> bool:
    if isinstance(node, ast.Constant):
        return True
    if isinstance(node, ast.Tuple | ast.List | ast.Set):
        return all(_constant(e) for e in node.elts)
    if isinstance(node, ast.Dict):
        return all(k is not None and _constant(k) and _constant(v) for k, v in zip(node.keys, node.values, strict=True))
    return isinstance(node, ast.UnaryOp) and _constant(node.operand)


def _bind_import(node: ast.Import | ast.ImportFrom, into: dict[str, str]) -> None:
    """name -> the dotted module or object it is bound to (`_RELATIVE` for a relative import)."""
    if isinstance(node, ast.Import):
        for alias in node.names:
            if alias.asname:
                into[alias.asname] = alias.name
            else:
                into[alias.name.split(".")[0]] = alias.name.split(".")[0]
        return
    for alias in node.names:
        if alias.name == "*":
            continue
        base = _RELATIVE if node.level else (node.module or "")
        into[alias.asname or alias.name] = base if base == _RELATIVE else f"{base}.{alias.name}"


def _module_scope(tree: ast.Module) -> tuple[dict[str, str], set[str], set[str]]:
    """(imports, project-like definitions, constants) bound at module level; the statements of an `if` or `try` count,
    the inside of a function or a class does not."""
    imports: dict[str, str] = {}
    defined: set[str] = set()
    constants: set[str] = set()
    pending: list[ast.stmt] = list(tree.body)
    while pending:
        node = pending.pop()
        if isinstance(node, ast.Import | ast.ImportFrom):
            _bind_import(node, imports)
        elif isinstance(node, _Def | ast.ClassDef):
            defined.add(node.name)
        elif isinstance(node, ast.Assign | ast.AnnAssign):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = {n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name)}
            (constants if _constant(node.value) else defined).update(names)
        else:
            pending.extend(c for c in ast.iter_child_nodes(node) if isinstance(c, ast.stmt))
    return imports, defined - constants, constants


def _find(tree: ast.Module, classname: str | None, name: str) -> _Def | None:
    scope: list[ast.stmt] = tree.body
    if classname:
        owner = next((n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == classname), None)
        if owner is None:
            return None
        scope = owner.body
    return next((n for n in scope if isinstance(n, _Def) and n.name == name), None)


def _parametrized(fn: _Def) -> tuple[set[str], list[ast.expr]]:
    """The argument names the function's own `parametrize` decorators supply, and their value expressions."""
    names: set[str] = set()
    values: list[ast.expr] = []
    for dec in fn.decorator_list:
        if not (isinstance(dec, ast.Call) and (chain := _chain(dec.func)) and chain[-1] == "parametrize"):
            continue
        if dec.args and isinstance(dec.args[0], ast.Constant) and isinstance(dec.args[0].value, str):
            names |= {n.strip() for n in dec.args[0].value.split(",") if n.strip()}
        elif dec.args and isinstance(dec.args[0], ast.List | ast.Tuple):
            names |= {e.value for e in dec.args[0].elts if isinstance(e, ast.Constant) and isinstance(e.value, str)}
        values.extend(dec.args[1:])
        values.extend(k.value for k in dec.keywords)
    return names, values


def _locals(fn: _Def) -> tuple[set[str], dict[str, str]]:
    """Names bound inside the function (parameters, assignments, loops, imports) and its own import bindings."""
    bound: set[str] = {a.arg for a in [*fn.args.posonlyargs, *fn.args.args, *fn.args.kwonlyargs]}
    bound |= {a.arg for a in (fn.args.vararg, fn.args.kwarg) if a is not None}
    imports: dict[str, str] = {}
    for node in ast.walk(fn):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store | ast.Del):
            bound.add(node.id)
        elif isinstance(node, ast.Import | ast.ImportFrom):
            _bind_import(node, imports)
        elif (isinstance(node, _Def | ast.ClassDef) and node is not fn) or (
            isinstance(node, ast.ExceptHandler) and node.name
        ):
            bound.add(node.name)  # type: ignore[union-attr]
    return bound - set(imports), imports


def _repository(wb: Workbench, dotted: str, roots: Sequence[str], near: str) -> bool:
    if dotted == _RELATIVE:
        return True
    if _resolve(wb, dotted, [*roots, near]):
        return True
    return bool(_resolve(wb, dotted.rsplit(".", 1)[0], [*roots, near])) if "." in dotted else False


def dependency_only(wb: Workbench, test_id: str, roots: Sequence[str], criterion_text: str = "") -> bool:
    """See the module docstring; `criterion_text` is the text of the criterion the test traces."""
    file = _test_file(wb, test_id)
    if file is None:
        return False
    try:
        tree = ast.parse((wb.worktree / file).read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError, OSError):
        return False
    module, _, rest = test_id.partition("::")
    owner = module.rsplit(".", 1)[-1]
    fn = _find(tree, None if owner == Path(file).stem else owner, rest.split("[", 1)[0])
    if fn is None:
        return False
    near = Path(file).parent.as_posix()
    near = "" if near == "." else near
    imports, defined, constants = _module_scope(tree)
    bound, inner = _locals(fn)
    imports = {**imports, **inner}
    names, values = _parametrized(fn)
    params = [a.arg for a in [*fn.args.posonlyargs, *fn.args.args, *fn.args.kwonlyargs] if a.arg not in ("self", "cls")]
    if any(p not in BUILTIN_FIXTURES and p not in names for p in params):
        return False
    named = _normal(criterion_text)
    reads_pin = False
    scanned: list[ast.AST] = [*fn.body, *fn.args.defaults, *[d for d in fn.args.kw_defaults if d is not None], *values]
    for root in scanned:
        for node in ast.walk(root):
            if isinstance(node, ast.Import | ast.ImportFrom):
                targets = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or "."]
                if getattr(node, "level", 0) or any(_repository(wb, t, roots, near) for t in targets):
                    return False
                continue
            if isinstance(node, ast.Call) and (chain := _chain(node.func)):
                if chain[-1] in _BY_NAME:  # project code reached by a name the static scan cannot follow
                    return False
                head = imports.get(chain[0]) if chain[0] not in bound else None
                if head and ".".join([head, *chain[1:]]) in _METADATA:
                    first = node.args[0] if node.args else None
                    if (
                        isinstance(first, ast.Constant)
                        and isinstance(first.value, str)
                        and _normal(first.value) in named
                    ):
                        reads_pin = True  # a literal distribution name that the criterion names
                    else:
                        return False
            if isinstance(node, ast.Attribute) and _chain(node) == ["sys", "modules"]:
                return False
            if isinstance(node, ast.Attribute) and node.attr == "__version__":
                owner = _chain(node.value)
                target = imports.get(owner[0]) if owner and owner[0] not in bound else None
                if (
                    target
                    and target.split(".")[0] not in sys.stdlib_module_names
                    and not _repository(wb, target, roots, near)
                ):
                    if _normal(target.split(".")[0]) in named:
                        reads_pin = True  # `<dependency>.__version__` for a dependency the criterion names
                    else:
                        return False
            if not (isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)):
                continue
            name = node.id
            if name in bound or name in constants or hasattr(builtins, name):
                continue
            if name in defined:
                return False
            target = imports.get(name)
            if target is None:
                return False  # a name the file does not bind: a fixture-like or unknown global
            if _repository(wb, target, roots, near):
                return False
    return reads_pin
