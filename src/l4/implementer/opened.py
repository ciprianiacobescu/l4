"""What a support file that a task's text or a person's answer opened may become in green (design D5).

Three rules, checked on the red version and the new version of the file, after the agent step and before the frozen
files are put back:

1. every top-level statement of the red version is still there, unchanged (`ast.dump`) and in order; new statements may
   come between them (`guards.appended_only` without its "only at the end" and "definitions only" limits);
2. no new statement binds a name that the red version binds, or a name that pytest reads at module level;
3. no new code patches or assigns a symbol of a production module that the unit changed.

`check_opened` returns the reason to put the file back (the `why` of `guard.violation{rule: "opened file"}`), or
None."""

import ast
from collections import Counter
from collections.abc import Collection, Iterable
from pathlib import PurePosixPath

from ..config.schema import L4Config
from ..evidence.scope import file_kind
from .guards import _MODULE_HOOKS, _bound


def check_opened(
    before: str,
    after: str,
    *,
    named_by_task: bool,
    unit_modules: Collection[str],
) -> str | None:
    """None when `after` is an allowed edit of `before`, else why not. Rules 1 and 2 apply to a file opened by task
    text (`named_by_task`); a file opened by an answer keeps only rule 3."""
    try:
        old, new = ast.parse(before).body, ast.parse(after).body
    except (SyntaxError, ValueError):
        return "does not parse"
    if named_by_task and (why := _kept_and_not_rebound(old, new)):
        return why
    return _patches(before, after, unit_modules) if unit_modules else None


def _kept_and_not_rebound(old: list[ast.stmt], new: list[ast.stmt]) -> str | None:
    kept, added = 0, []
    for node in new:
        if kept < len(old) and ast.dump(node) == ast.dump(old[kept]):
            kept += 1
        else:
            added.append(node)
    if kept < len(old):
        return "changes an existing statement"
    bound = {name for node in old for name in _bound(node)}
    for node in added:
        if isinstance(node, ast.Import | ast.ImportFrom) and any(ast.dump(node) == ast.dump(o) for o in old):
            continue  # a repeated import is no rebinding
        for name in sorted(_bound(node)):
            if name in bound or _MODULE_HOOKS.match(name):
                return f"rebinds {name}"
        bound |= _bound(node)
    return None


def unit_modules(paths: Iterable[str], cfg: L4Config) -> frozenset[str]:
    """The dotted names of the production modules the unit changed: its `.py` files that are neither test, support nor
    exempt paths, with the root rule of the fix gate (`src/app/otel.py` is `app.otel`, `pkg/mod.py` is `pkg.mod`, a
    package's `__init__.py` is the package)."""
    roots = cfg.verifier.evidence.module_roots
    out: set[str] = set()
    for path in paths:
        parts = path.split("/")
        if not path.endswith(".py") or ".." in parts or file_kind(path, "", cfg) != "code":
            continue
        if parts[0] in roots and len(parts) > 1:
            parts = parts[1:]
        stem = PurePosixPath(parts[-1]).stem
        dotted = [*parts[:-1], *([] if stem == "__init__" else [stem])]
        if dotted and all(p.isidentifier() for p in dotted):
            out.add(".".join(dotted))
    return frozenset(out)


_PATCH_CALLS = {
    ("setattr",): "attr",
    ("delattr",): "attr",
    ("patch",): "string",
    ("patch", "object"): "attr",
    ("patch", "multiple"): "object",
}


def _chain(expr: ast.expr) -> list[str] | None:
    """`a.b.c` as ["a", "b", "c"]; None for anything that is not a plain name chain."""
    out: list[str] = []
    while isinstance(expr, ast.Attribute):
        out.insert(0, expr.attr)
        expr = expr.value
    return [expr.id, *out] if isinstance(expr, ast.Name) else None


def _aliases(tree: ast.AST) -> dict[str, str]:
    """What each imported name stands for: `import a.b as o` -> o is a.b, `import a.b` -> a is a, `from a import b`
    -> b is a.b."""
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.asname:
                    out[a.asname] = a.name
                else:
                    out[a.name.split(".")[0]] = a.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for a in node.names:
                out[a.asname or a.name] = f"{node.module}.{a.name}"
    return out


def _dotted(expr: ast.expr, alias: dict[str, str]) -> str | None:
    """The dotted name a module object expression stands for, or None (a fixture parameter, a local)."""
    if isinstance(expr, ast.Call) and (c := _chain(expr.func)) and c[-1] == "import_module" and expr.args:
        arg = expr.args[0]
        return arg.value if isinstance(arg, ast.Constant) and isinstance(arg.value, str) else None
    chain = _chain(expr)
    if not chain or chain[0] not in alias:
        return None
    return ".".join([alias[chain[0]], *chain[1:]])


def _string(expr: ast.expr) -> str | None:
    return expr.value if isinstance(expr, ast.Constant) and isinstance(expr.value, str) else None


def _targets(node: ast.AST, alias: dict[str, str]) -> list[str]:
    """The dotted symbols one node patches or assigns."""
    if isinstance(node, ast.Call):
        chain = _chain(node.func)
        if not chain or not node.args:
            return []
        last2 = (chain[-2:][0], chain[-1]) if len(chain) > 1 else ()
        kind = _PATCH_CALLS.get(last2) or _PATCH_CALLS.get((chain[-1],))
        if kind is None:
            return []
        first = node.args[0]
        if (target := _string(first)) is not None:  # `monkeypatch.setattr("a.b.c", v)`, `patch("a.b.c")`
            return [target]
        if kind == "string":
            return []
        base = _dotted(first, alias)
        if base is None:
            return []
        if kind == "object":  # patch.multiple(obj, name=value, ...)
            return [f"{base}.{k.arg}" for k in node.keywords if k.arg]
        name = _string(node.args[1]) if len(node.args) > 1 else None
        return [f"{base}.{name}" if name else base]
    targets: list[ast.expr] = []
    if isinstance(node, ast.Assign):
        targets = list(node.targets)
    elif isinstance(node, ast.AnnAssign | ast.AugAssign):
        targets = [node.target]
    out: list[str] = []
    while targets:
        t = targets.pop()
        if isinstance(t, ast.Tuple | ast.List):
            targets.extend(t.elts)
        elif isinstance(t, ast.Starred):
            targets.append(t.value)
        elif isinstance(t, ast.Attribute) and (base := _dotted(t.value, alias)) is not None:
            out.append(f"{base}.{t.attr}")
    return out


def _hits(tree: ast.AST, alias: dict[str, str], modules: Collection[str]) -> Counter[tuple[str, str]]:
    """(target, dump of the node) of every patch or assignment of a symbol of `modules`."""
    found: Counter[tuple[str, str]] = Counter()
    for node in ast.walk(tree):
        for target in _targets(node, alias):
            if any(target == m or target.startswith(m + ".") for m in modules):
                found[target, ast.dump(node)] += 1
    return found


def _patches(before: str, after: str, modules: Collection[str]) -> str | None:
    """Rule 3: the first new patch or assignment of a symbol of a module the unit changed."""
    old_tree, new_tree = ast.parse(before), ast.parse(after)
    old = _hits(old_tree, _aliases(old_tree), modules)
    new = _hits(new_tree, _aliases(new_tree), modules)
    for target, _ in sorted(new - old):
        return f"patches {target}, which the unit changed"
    return None
