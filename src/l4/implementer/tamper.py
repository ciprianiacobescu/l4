"""The comparison of a pre-existing test, per test, on the AST (detect-test-tamper, L4-IMP-045..047, L4-IMP-049).

Pure: text in, facts out; Python only; no git. A test is its file and qualified name (`test_x`, or `Class.test_x` for a
method of a module-level class), never a bare name. Its definition is every statement that binds its name in its
scope, in order, as an AST dump without positions (decorators, parametrisation, requested fixtures and body), so a
second `def`, an assignment, an import or a `del` of the name is a change. What the test uses in its own file (helpers,
constants, fixtures, autouse fixtures, `pytestmark`, module setup, its class) is part of it too (its closure). Comments,
layout and a trailing newline are not in the AST and change nothing.

No public name here starts with `test` (a test module that imports this one must not collect it)."""

import ast
import hashlib
import inspect
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from functools import lru_cache

from l4.implementer.guards import _MODULE_HOOKS, _defines_only, _inert, _pytest_mark

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
    func: bool = False  # the statement is a `def` of the name


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def _doc(text: str) -> str:
    return "\n".join(line.rstrip() for line in inspect.cleandoc(text).splitlines()).strip()


def _parse(source: str) -> ast.Module | None:
    """The tree, with every docstring replaced by its normalised text: re-indenting one is no change, new words are."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError, RecursionError):
        return None
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef) and node.body:
            first = node.body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                first.value.value = _doc(first.value.value)
    return tree


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


def _locals_of(body: Iterable[ast.AST]) -> set[str]:
    """The names bound in the scope of these statements (no nested scope), less the ones declared global."""
    declared: set[str] = set()
    names: set[str] = set()
    for node in _own_nodes(body):
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


def _arg_names(a: ast.arguments) -> set[str]:
    return {arg.arg for arg in (*a.posonlyargs, *a.args, *a.kwonlyargs, a.vararg, a.kwarg) if arg}


def _annotations(a: ast.arguments) -> list[ast.expr]:
    every = (*a.posonlyargs, *a.args, *a.kwonlyargs, a.vararg, a.kwarg)
    return [arg.annotation for arg in every if arg and arg.annotation]


class _Reader:
    """The module-level names a statement reads. A name that is local to a function, a lambda, a class body or a
    comprehension around the read is not the module's name of the same spelling (design D12)."""

    def __init__(self) -> None:
        self.out: set[str] = set()

    def visit(self, node: ast.AST, env: frozenset[str], outer: frozenset[str]) -> None:
        if isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Load) and node.id not in env:
                self.out.add(node.id)
            return
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            a = node.args
            for expr in [*node.decorator_list, *a.defaults, *(d for d in a.kw_defaults if d), *_annotations(a)]:
                self.visit(expr, env, outer)
            if node.returns:
                self.visit(node.returns, env, outer)
            inner = outer | _arg_names(a) | _locals_of(node.body)
            for statement in node.body:
                self.visit(statement, inner, inner)
            return
        if isinstance(node, ast.Lambda):
            for expr in [*node.args.defaults, *(d for d in node.args.kw_defaults if d)]:
                self.visit(expr, env, outer)
            inner = env | _arg_names(node.args)
            self.visit(node.body, inner, inner)
            return
        if isinstance(node, ast.ClassDef):
            for expr in [*node.decorator_list, *node.bases, *(k.value for k in node.keywords)]:
                self.visit(expr, env, outer)
            inner = env | _locals_of(node.body)
            for statement in node.body:
                self.visit(statement, inner, outer)
            return
        if isinstance(node, _COMPREHENSIONS):
            targets = {n.id for g in node.generators for n in ast.walk(g.target) if isinstance(n, ast.Name)}
            self.visit(node.generators[0].iter, env, outer)
            inner = env | targets
            for position, generator in enumerate(node.generators):
                if position:
                    self.visit(generator.iter, inner, inner)
                for condition in generator.ifs:
                    self.visit(condition, inner, inner)
            for child in (node.key, node.value) if isinstance(node, ast.DictComp) else (node.elt,):
                self.visit(child, inner, inner)
            return
        if isinstance(node, ast.Call) and ast.unparse(node.func).endswith("usefixtures"):
            self.out |= {a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)}
        for child in ast.iter_child_nodes(node):
            self.visit(child, env, outer)


def _reads(node: ast.stmt, owner: str | None) -> frozenset[str]:
    """The module names (and `<Class>.<attr>` for `self.<attr>`) a statement reads, and the fixtures a test function
    requests (its parameters)."""
    reader = _Reader()
    reader.visit(node, frozenset(), frozenset())
    names = reader.out
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        names |= _arg_names(node.args)
        if owner and (first := (*node.args.posonlyargs, *node.args.args)):
            me = first[0].arg
            names |= {
                f"{owner}.{sub.attr}"
                for sub in ast.walk(node)
                if isinstance(sub, ast.Attribute) and isinstance(sub.value, ast.Name) and sub.value.id == me
            }
    return frozenset(names)


def _plain_fixture(decorator: ast.expr) -> bool:
    """A fixture decorator (`pytest.fixture`, `fixture(...)`, `pytest_asyncio.fixture`) that is not autouse."""
    call = decorator if isinstance(decorator, ast.Call) else None
    name = ast.unparse(call.func if call else decorator)
    if name != "fixture" and not name.endswith(".fixture"):
        return False
    if call is None:
        return True
    for keyword in call.keywords:
        if keyword.arg == "autouse" and not (isinstance(keyword.value, ast.Constant) and keyword.value.value is False):
            return False
    return _inert(*call.args, *(k.value for k in call.keywords))


def _plain(node: ast.stmt, *, top: bool) -> bool:
    """A statement that only defines (`guards._defines_only`), where a fixture that is not autouse also counts: it
    reaches only the tests that request it, and the closure follows requests. Anything else reaches every test."""
    if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        a = node.args
        marks = [d for d in node.decorator_list if _pytest_mark(d)]
        others = [d for d in node.decorator_list if not _pytest_mark(d)]
        return (
            (top or not node.name.startswith("__"))
            and all(_plain_fixture(d) for d in others)
            and _inert(*marks, *a.defaults, *a.kw_defaults, node.returns, *_annotations(a))
        )
    if isinstance(node, ast.ClassDef):
        return (
            not node.keywords
            and all(_pytest_mark(d) for d in node.decorator_list)
            and _inert(*node.decorator_list, *node.bases)
            and all(_plain(statement, top=False) for statement in node.body)
        )
    return _defines_only(node, top=top)


def _scope(body: list[ast.stmt], owner: str | None, pseudo: str) -> dict[str, list[_Part]]:
    """name -> its parts, in order, for one scope (the module body, or one class body). The statements that are not
    plain definitions are the parts of the pseudo-name `pseudo` (`<module>`, `<class>`), a leading docstring aside."""
    out: dict[str, list[_Part]] = {}

    def add(name: str, part: _Part) -> None:
        parts = out.setdefault(name, [])
        if not (part.is_import and any(p.is_import and p.text == part.text for p in parts)):
            parts.append(part)  # a repeated import is no rebinding

    for position, statement in enumerate(body):
        line = getattr(statement, "lineno", 0)
        docstring = (
            position == 0
            and isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Constant)
            and isinstance(statement.value.value, str)
        )
        if docstring:
            continue
        dump = ast.dump(statement, include_attributes=False)
        if not _plain(statement, top=owner is None):
            add(pseudo, _Part(dump, line, _reads(statement, owner)))
        if isinstance(statement, ast.Import | ast.ImportFrom):
            for name, text in _import_parts(statement):
                add(name, _Part(text, line, frozenset(), True))
            if any(a.name == "*" for a in statement.names):
                add("*", _Part(f"from {statement.module or ''} import *", line, frozenset(), True))
            continue
        names = _stored(statement)
        if not names:
            continue
        func = isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef)
        part = _Part(dump, line, _reads(statement, owner), False, func)
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


def _shell(node: ast.ClassDef) -> ast.ClassDef:
    """The class header: decorators, bases and keywords, with an empty body."""
    shell = ast.ClassDef(
        name=node.name,
        bases=node.bases,
        keywords=node.keywords,
        body=[ast.Pass()],
        decorator_list=node.decorator_list,
        type_params=getattr(node, "type_params", []),
    )
    return ast.fix_missing_locations(shell)


def _closure(
    own: str,
    parts: list[_Part],
    module: dict[str, list[_Part]],
    classes: dict[str, ast.ClassDef],
    members: dict[str, dict[str, list[_Part]]],
    chain: list[str],
    autouse: set[str],
) -> tuple[str, dict[str, str]]:
    """What a test uses in its file. `chain` is its class followed by the module-level classes it inherits from."""
    seeds: set[str] = set().union(*(p.reads for p in parts)) if parts else set()
    seeds |= autouse
    seeds |= {n for n in module if _MODULE_HOOKS.match(n) and not (n.startswith("__") and n.endswith("__"))}
    if "*" in module:
        seeds.add("*")
    if "<module>" in module:
        seeds.add("<module>")
    uses: dict[str, str] = {}
    cls = chain[0] if chain else None
    for name in chain:
        shell = _shell(classes[name])
        uses[f"{name}:"] = _sha(ast.dump(shell, include_attributes=False))
        uses[f"{name}#"] = str(len(module.get(name, [])))
        seeds |= _reads(shell, None)
        if "<class>" in members[name]:
            seeds.add(f"{name}.<class>")
        seeds |= {f"{cls}.{m}" for m in members[name] if not m.startswith("test") and m != "<class>"}

    def lookup(name: str) -> list[_Part]:
        if "." not in name:
            return module.get(name, [])
        prefix, attr = name.split(".", 1)
        if prefix not in chain:
            return []
        if attr == "<class>":
            return members[prefix].get("<class>", [])
        for member in chain:  # the class itself first, then what it inherits: the override wins
            if attr in members[member]:
                return members[member][attr]
        return []

    todo = sorted(seeds)
    seen: set[str] = set()
    while todo:
        name = todo.pop()
        if name in seen or name == own:
            continue
        seen.add(name)
        if "." in name and name.split(".", 1)[0] in chain and name.split(".", 1)[0] != cls:
            name = f"{cls}.{name.split('.', 1)[1]}"  # `self.attr` read in a base class method: the subclass's view
            if name in seen:
                continue
            seen.add(name)
        found = lookup(name)
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
    `test` and, for each module-level class, `Class.<name>` for the `test*` names its body binds and those it inherits
    from module-level classes of the same file. `None` when the source does not parse. A name is a test
    (`Facts.test`) when a `def` of it is among its parts."""
    tree = _parse(source)
    if tree is None:
        return None
    module = _scope(tree.body, None, "<module>")
    autouse = {n.name for n in tree.body if is_autouse(n) and isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)}
    classes: dict[str, ast.ClassDef] = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}  # the last wins
    members = {name: _scope(node.body, name, "<class>") for name, node in classes.items()}
    facts: dict[str, Facts] = {}

    def record(key: str, parts: list[_Part], texts: list[str], chain: list[str]) -> None:
        closure, uses = _closure(key, parts, module, classes, members, chain, autouse)
        facts[key] = Facts(
            tuple(texts),
            tuple(p.line for p in parts),
            _sha("\n".join(texts)),
            closure,
            uses,
            any(p.func for p in parts),
            frozenset(n for n in uses if n in module and all(p.is_import for p in module[n])),
        )

    for name, parts in module.items():
        if name.startswith("test"):
            record(name, parts, [p.text for p in parts], [])

    def chain_of(name: str, seen: list[str]) -> None:
        if name in seen:
            return
        seen.append(name)
        for base in classes[name].bases:
            if isinstance(base, ast.Name) and base.id in classes:
                chain_of(base.id, seen)

    for cls in classes:
        chain: list[str] = []
        chain_of(cls, chain)
        owner: dict[str, str] = {}
        for member in chain:
            for name in members[member]:
                if name.startswith("test"):
                    owner.setdefault(name, member)
        for name, defining in owner.items():
            parts = members[defining][name]
            record(f"{cls}.{name}", parts, [f"{defining}:{p.text}" for p in parts], chain)
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
    real = {n for n in named if not n.endswith(("<module>", "<class>")) and not n.lower().startswith("test")}
    pseudo = {n for n in named if n.endswith(("<module>", "<class>"))}
    named = real or pseudo or named  # a new autouse fixture is named, not only the `<module>` statement it is
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
