"""The comparison of a pre-existing test, per test, on the AST (detect-test-tamper, L4-IMP-045..047).

Pure: text in, facts out; Python only; no git. A test is its file and qualified name (`test_x`, or `Class.test_x` for a
method of a module-level class), never a bare name. Its definition is every statement that binds its name in its
scope, in order, as an AST dump without positions (decorators, parametrisation, requested fixtures and body), so a
second `def`, an assignment, an import or a `del` of the name is a change. What the test uses in its own file (helpers,
constants, fixtures, autouse fixtures, `pytestmark`, module setup, its class) is part of it too (its closure). Comments,
layout and a trailing newline are not in the AST and change nothing.

No public name here starts with `test` (a test module that imports this one must not collect it)."""

import ast
import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import lru_cache

from l4.implementer.guards import _MODULE_HOOKS
from l4.verifier.scan import _qualified

MAX_NAMES = 5
_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
_SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
_COMPREHENSIONS = (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)


@dataclass(frozen=True)
class Facts:
    """What one revision of a file says about one name of a scope. `parts` are the bindings of the name in order,
    `lines` the line of each, `definition` their digest, `closure` the digest of what the name uses in its file and
    `uses` that closure (name -> digest of the name's parts). `test` is true when the name is a test function."""

    parts: tuple[str, ...]
    lines: tuple[int, ...]
    definition: str
    closure: str
    uses: Mapping[str, str]
    test: bool = True
    imports: frozenset[str] = frozenset()  # the names of `uses` that only imports bind


@dataclass(frozen=True)
class Tampered:
    path: str
    name: str
    kind: str  # changed | rebound | deleted | unparsable
    why: str


@dataclass(frozen=True)
class _Part:
    text: str
    line: int
    reads: frozenset[str]
    is_import: bool = False


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def _parse(source: str) -> ast.Module | None:
    try:
        return ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return None


# --- what a statement binds ----------------------------------------------------------------------------------------


def _own_nodes(nodes: Iterable[ast.AST]) -> Iterable[ast.AST]:
    """Every node of a statement list that belongs to its own scope: nested function, class and lambda bodies are other
    scopes (their names are bound, their insides are not) and so are comprehension targets (a `:=` still binds out)."""
    todo = list(nodes)
    while todo:
        node = todo.pop()
        yield node
        if isinstance(node, _DEFS):
            todo.extend(node.decorator_list)  # a `:=` in a decorator runs in this scope
            continue
        if isinstance(node, ast.Lambda):
            continue
        if isinstance(node, _COMPREHENSIONS):
            todo.extend(n.target for n in ast.walk(node) if isinstance(n, ast.NamedExpr))
            continue
        todo.extend(ast.iter_child_nodes(node))


def _import_parts(node: ast.Import | ast.ImportFrom) -> list[tuple[str, str]]:
    out = []
    for alias in node.names:
        if isinstance(node, ast.Import):
            if alias.asname:
                out.append((alias.asname, f"import {alias.name}"))
            else:
                top = alias.name.split(".")[0]
                out.append((top, f"import {top}"))
        else:
            source = f"from {'.' * node.level}{node.module or ''} import {alias.name}"
            out.append((alias.asname or alias.name, source))
    return out


def _stored(statement: ast.stmt) -> set[str]:
    """Every name a statement binds in its scope (any depth of compound statements, no nested scope)."""
    names: set[str] = set()
    for node in _own_nodes([statement]):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store | ast.Del):
            names.add(node.id)
        elif isinstance(node, _DEFS):
            names.add(node.name)
        elif isinstance(node, ast.Import | ast.ImportFrom):
            names |= {name for name, _ in _import_parts(node)}
        elif isinstance(node, ast.ExceptHandler | ast.MatchAs | ast.MatchStar) and node.name:
            names.add(node.name)
        elif isinstance(node, ast.MatchMapping) and node.rest:
            names.add(node.rest)
        elif isinstance(node, ast.Global | ast.Nonlocal):
            names |= set(node.names)
    return names


def _function_locals(function: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    declared: set[str] = set()
    names: set[str] = set()
    for node in _own_nodes(function.body):
        if isinstance(node, ast.Global | ast.Nonlocal):
            declared |= set(node.names)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store | ast.Del):
            names.add(node.id)
        elif isinstance(node, _DEFS):
            names.add(node.name)
        elif isinstance(node, ast.Import | ast.ImportFrom):
            names |= {name for name, _ in _import_parts(node)}
        elif isinstance(node, ast.ExceptHandler | ast.MatchAs | ast.MatchStar) and node.name:
            names.add(node.name)
    return names - declared


def _params(node: ast.AST) -> set[str]:
    found: set[str] = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            a = sub.args
            found |= {arg.arg for arg in (*a.posonlyargs, *a.args, *a.kwonlyargs)}
            found |= {arg.arg for arg in (a.vararg, a.kwarg) if arg}
    return found


def _loads(nodes: Iterable[ast.AST]) -> set[str]:
    found: set[str] = set()
    for root in nodes:
        for sub in ast.walk(root):
            if isinstance(sub, ast.Name) and isinstance(sub.ctx, ast.Load):
                found.add(sub.id)
            elif isinstance(sub, ast.Call):
                func = ast.unparse(sub.func)
                if func.endswith("usefixtures"):
                    found |= {a.value for a in sub.args if isinstance(a, ast.Constant) and isinstance(a.value, str)}
    return found


def _reads(node: ast.stmt, owner: str | None) -> frozenset[str]:
    """The module names (and `<Class>.<attr>` for `self.<attr>`) a statement reads: every name in a load context, every
    parameter of every function or lambda in it (the fixtures a test requests), the fixtures a `usefixtures` names. A
    local variable of a function is not the module's name of the same spelling."""
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        a = node.args
        annotations = [
            x.annotation for x in (*a.posonlyargs, *a.args, *a.kwonlyargs, a.vararg, a.kwarg) if x and x.annotation
        ]
        outer = [*node.decorator_list, *a.defaults, *(d for d in a.kw_defaults if d), *annotations]
        if node.returns:
            outer.append(node.returns)
        local = _function_locals(node) - _params(node)
        names = _loads(outer) | (_loads(node.body) - local)
        if owner and (first := (*a.posonlyargs, *a.args)):
            me = first[0].arg
            names |= {
                f"{owner}.{sub.attr}"
                for sub in ast.walk(node)
                if isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name) and sub.value.id == me
            }
        return frozenset(names | _params(node))
    return frozenset(_loads([node]) | _params(node))


def _scope(body: list[ast.stmt], owner: str | None) -> dict[str, list[_Part]]:
    """name -> its parts, in order, for one scope (the module body, or one class body)."""
    out: dict[str, list[_Part]] = {}

    def add(name: str, part: _Part) -> None:
        parts = out.setdefault(name, [])
        if not (part.is_import and any(p.is_import and p.text == part.text for p in parts)):
            parts.append(part)  # a repeated import is no rebinding

    for statement in body:
        line = getattr(statement, "lineno", 0)
        if isinstance(statement, ast.Import | ast.ImportFrom):
            for name, text in _import_parts(statement):
                add(name, _Part(text, line, frozenset(), True))
            if any(a.name == "*" for a in statement.names):
                add("*", _Part(f"from {statement.module or ''} import *", line, frozenset(), True))
            continue
        names = _stored(statement)
        if not names:
            continue
        part = _Part(ast.dump(statement, include_attributes=False), line, _reads(statement, owner))
        for name in names - {"*"}:
            add(name, part)
    return out


# --- the facts of a file --------------------------------------------------------------------------------------------


def is_autouse(node: ast.AST) -> bool:
    """A function decorated with a pytest fixture call whose `autouse` is not the constant False."""
    if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        return False
    for decorator in node.decorator_list:
        if isinstance(decorator, ast.Call) and ast.unparse(decorator.func).endswith("fixture"):
            for keyword in decorator.keywords:
                if keyword.arg == "autouse":
                    return not (isinstance(keyword.value, ast.Constant) and keyword.value.value is False)
    return False


def _digest_of(parts: Iterable[_Part]) -> str:
    return _sha("\n".join(p.text for p in parts))


def _closure(
    own: str,
    parts: list[_Part],
    module: dict[str, list[_Part]],
    members: dict[str, list[_Part]],
    owner: ast.ClassDef | None,
    autouse: set[str],
) -> tuple[str, dict[str, str]]:
    cls = owner.name if owner else None
    seeds: set[str] = set().union(*(p.reads for p in parts)) if parts else set()
    seeds |= autouse
    seeds |= {n for n in module if _MODULE_HOOKS.match(n) and not (n.startswith("__") and n.endswith("__"))}
    if "*" in module:
        seeds.add("*")
    uses: dict[str, str] = {}
    if owner is not None and cls is not None:
        shell = ast.ClassDef(
            name=owner.name,
            bases=owner.bases,
            keywords=owner.keywords,
            body=[ast.Pass()],
            decorator_list=owner.decorator_list,
            type_params=getattr(owner, "type_params", []),
        )
        uses[f"{cls}:"] = _sha(ast.dump(shell, include_attributes=False))
        uses[f"{cls}#"] = str(len(module.get(cls, [])))
        seeds |= _reads(ast.fix_missing_locations(shell), None)
        seeds |= {f"{cls}.{m}" for m in members if not m.startswith("test")}
    todo = sorted(seeds)
    seen: set[str] = set()
    while todo:
        name = todo.pop()
        if name in seen or name == own:
            continue
        seen.add(name)
        found = members.get(name.split(".", 1)[1], []) if cls and name.startswith(f"{cls}.") else module.get(name, [])
        if found:
            uses[name] = _digest_of(found)
            for part in found:
                if not part.is_import:
                    todo.extend(part.reads)
    digest = _sha("\n".join(f"{k}={v}" for k, v in sorted(uses.items()) if v))
    return digest, uses


@lru_cache(maxsize=512)
def facts_of(source: str) -> dict[str, Facts] | None:
    """The facts of every name that has a binding in a scope that holds a test: the module's names that start with
    `test` and, for each module-level class, `Class.<name>` for those that start with `test`. `None` when the source
    does not parse. A name is a test (`Facts.test`) when a `def` of it is a test function (`scan._qualified`)."""
    tree = _parse(source)
    if tree is None:
        return None
    module = _scope(tree.body, None)
    autouse = {n.name for n in tree.body if is_autouse(n) and isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)}
    test_names = {name for name, _ in _qualified(tree) if name.rsplit(".", 1)[-1].startswith("test")}
    facts: dict[str, Facts] = {}

    def record(key: str, parts: list[_Part], members: dict[str, list[_Part]], owner: ast.ClassDef | None) -> None:
        closure, uses = _closure(key, parts, module, members, owner, autouse)
        facts[key] = Facts(
            tuple(p.text for p in parts),
            tuple(p.line for p in parts),
            _digest_of(parts),
            closure,
            uses,
            key in test_names,
            frozenset(n for n in uses if n in module and all(p.is_import for p in module[n])),
        )

    for name, parts in module.items():
        if name.startswith("test"):
            record(name, parts, {}, None)
    classes: dict[str, ast.ClassDef] = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}  # the last wins
    for cls, node in classes.items():
        members = _scope(node.body, cls)
        for name, parts in members.items():
            if name.startswith("test"):
                record(f"{cls}.{name}", parts, members, node)
    return facts


def _lines_of(prefix: Facts, after: Facts) -> int:
    return after.lines[len(prefix.parts)]


def _closure_why(before: Facts, after: Facts) -> str:
    """The names that differ. Those that exist at both ends with other parts are the change; a name only one end has is
    often a consequence of it (a helper that stopped reading a constant), and an import that came with a new fixture is
    no news: they are named only when nothing else is."""
    differing = {n for n in {*before.uses, *after.uses} if before.uses.get(n, "") != after.uses.get(n, "")}
    both = {n for n in differing if n in before.uses and n in after.uses}
    imports = before.imports | after.imports
    named = both or {n for n in differing if n not in imports} or differing
    shown = sorted(n.rstrip("#:") for n in named)
    shown = list(dict.fromkeys(shown))
    more = f" (+{len(shown) - MAX_NAMES} more)" if len(shown) > MAX_NAMES else ""
    return f"what it uses in this file changed: {', '.join(shown[:MAX_NAMES])}{more}"


def compare(path: str, before: str, after: str | None) -> list[Tampered]:
    """What happened to each test of `before` in `after` (`None`: the file is gone). Sorted by name."""
    old = facts_of(before)
    if not old:
        return []
    tests = {name: f for name, f in old.items() if f.test}
    if after is None:
        return [Tampered(path, name, "deleted", "it was deleted") for name in sorted(tests)]
    new = facts_of(after)
    if new is None:
        return [Tampered(path, name, "unparsable", "the file does not parse") for name in sorted(tests)]
    found: list[Tampered] = []
    for name in sorted(tests):
        was, now = tests[name], new.get(name)
        if now is None:
            found.append(Tampered(path, name, "deleted", "it was deleted"))
        elif len(now.parts) > len(was.parts) and now.parts[: len(was.parts)] == was.parts:
            line = _lines_of(was, now)
            found.append(Tampered(path, name, "rebound", f"its name is bound again at line {line}, which replaces it"))
        elif now.parts != was.parts:
            found.append(Tampered(path, name, "changed", "its body, decorators or parametrisation changed"))
        elif now.closure != was.closure:
            found.append(Tampered(path, name, "changed", _closure_why(was, now)))
    return found


def moved(deleted: Mapping[tuple[str, str], str], added: Mapping[tuple[str, str], str]) -> set[tuple[str, str]]:
    """The deleted tests that are moved: another test, new at the later revision, has the same definition digest. Each
    added test stands for at most one deleted test; pairs are taken in sorted order of `(path, name)`."""
    free = dict(sorted(added.items()))
    found: set[tuple[str, str]] = set()
    for key, digest in sorted(deleted.items()):
        match = next((k for k, d in free.items() if d == digest), None)
        if match is not None:
            del free[match]
            found.add(key)
    return found


def names_test_id(test_id: str, path: str, name: str) -> bool:
    """A recorded id `tests.test_long::test_long` names the function `name` of the module `path` (a parametrised
    `name[x]` and a class between module and function count; the module must match, so a same-named test elsewhere
    stays protected). `name` may be a qualified `Class.test_x`: its last part is the function."""
    module = path.removesuffix(".py").replace("/", ".")
    function = name.rsplit(".", 1)[-1]
    where, _, tail = test_id.rpartition("::")
    return tail.split("[", 1)[0] == function and (where == module or where.startswith(f"{module}."))
