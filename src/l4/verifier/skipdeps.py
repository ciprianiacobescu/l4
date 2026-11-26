"""What makes a Python test skip, and everything that decides it inside its file (skipped-test-hold D1 (d)).

`scan.skip_constructs` reads the skip calls, markers and decorators of a file. It cannot see that the unit changed WHY
an unchanged construct skips: the flag a `skipif` reads, the condition of a guard `if not os.environ.get("S"):
pytest.skip(...)`, the body of a helper the condition calls. `SkipFacts` parses a source once and answers, per test,
with its **closure**: a multiset of `(label, text)` pairs of

- the skip-relevant parts of the test: its decorators; its class's decorators, bases and class-level skip statements;
  the module-level skip statements (`pytestmark` whatever its value, a module `importorskip`, `pytest.skip(...,
  allow_module_level=True)`); the statements of its body up to and including the last one that contains or encloses a
  skip, or that calls a name or a method that skips (so a guard `if` and the setup before it are in); the whole
  definition of each fixture the test takes (by parameter or `usefixtures`, and the fixtures those take), of each
  `autouse=True` fixture, and of each function or method of the module or of the test's class that no runner collects
  and that skips;
- every name those parts load and the module (or the class) binds (import, from-import, assignment, `def`, `class`),
  with the binding's text, and the names that binding loads, in turn, up to `DEPTH` levels.

A closure that is the same at the base and at the head means the unit did not change what decides the skip inside the
file. Not read: a name bound by a dynamic form (`globals()`, `getattr`, `importlib.import_module`, a name set in a
function through `global`), production code, and the content of an imported module: the base report of rule (a) and
the runbook's known limits stand in front of these.
"""

import ast
from collections import Counter
from collections.abc import Iterable

from l4.verifier import scan

DEPTH = 20  # levels of names that a closure follows; one that needs more is not compared (fail closed)
Closure = Counter[tuple[str, str]]
_FUNCTIONS = ast.FunctionDef | ast.AsyncFunctionDef


def _loaded(nodes: Iterable[ast.AST]) -> frozenset[str]:
    return frozenset(
        n.id for root in nodes for n in ast.walk(root) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)
    )


class _Binding:
    """One statement that binds a name: its text (the same for the same code, whatever its position) and the names it
    loads. A name bound inside a block (`try: import x / except ImportError: x = None`) has the block's whole top-level
    statement as its binding, because the block's condition decides which of the bindings is in force."""

    def __init__(self, node: ast.AST, text: str | None = None) -> None:
        self.node, self._text, self._loads = node, text, None

    def text(self) -> str:
        if self._text is None:
            self._text = ast.dump(self.node)
        return self._text

    def loads(self) -> frozenset[str]:
        if self._loads is None:
            self._loads = frozenset() if isinstance(self.node, ast.Import | ast.ImportFrom) else _loaded([self.node])
        return self._loads


def _assigned(node: ast.Assign | ast.AnnAssign | ast.AugAssign) -> set[str]:
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    return {n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}


def _bind_one(found: dict[str, list[_Binding]], statement: ast.stmt, whole: ast.stmt) -> None:
    """The names `statement` binds, each with a binding: an import alias of the body's own statement by its own text
    (an unrelated name added to the same import line is no change), anything else, an import inside a block too, by
    `whole`, the statement of the scope's body that holds it (the block's condition decides which binding holds)."""
    own = statement is whole
    if isinstance(statement, ast.Import):
        for a in statement.names:
            text = f"import {a.name} as {a.asname}" if own else None
            found.setdefault(a.asname or a.name.split(".")[0], []).append(_Binding(whole, text))
    elif isinstance(statement, ast.ImportFrom):
        for a in statement.names:
            text = f"from {'.' * statement.level}{statement.module} import {a.name} as {a.asname}" if own else None
            found.setdefault(a.asname or a.name, []).append(_Binding(whole, text))
    elif isinstance(statement, _FUNCTIONS | ast.ClassDef):
        found.setdefault(statement.name, []).append(_Binding(whole))
    elif isinstance(statement, ast.Assign | ast.AnnAssign | ast.AugAssign):
        for name in _assigned(statement):
            found.setdefault(name, []).append(_Binding(whole))


def _bindings(body: list[ast.stmt]) -> dict[str, list[_Binding]]:
    """Name -> its bindings in a module or class body, also those inside an `if`, `try`, `with`, `for` there."""
    found: dict[str, list[_Binding]] = {}
    for top in body:
        for sub in scan.flat([top]):
            if sub is top:
                _bind_one(found, top, top)
            else:
                _bind_one(found, sub, top)
    return found


def _is_pytestmark(node: ast.stmt) -> bool:
    return isinstance(node, ast.Assign | ast.AnnAssign) and "pytestmark" in _assigned(node)


def _is_autouse(function: _FUNCTIONS) -> bool:
    for decorator in function.decorator_list:
        if isinstance(decorator, ast.Call):
            for k in decorator.keywords:
                if k.arg == "autouse" and isinstance(k.value, ast.Constant) and k.value.value is True:
                    return True
    return False


def _fixture_name(function: _FUNCTIONS) -> str:
    for decorator in function.decorator_list:
        if isinstance(decorator, ast.Call):
            for k in decorator.keywords:
                if k.arg == "name" and isinstance(k.value, ast.Constant) and isinstance(k.value.value, str):
                    return k.value.value
    return function.name


def _params(function: _FUNCTIONS) -> list[str]:
    a = function.args
    return [p.arg for p in (*a.posonlyargs, *a.args, *a.kwonlyargs) if p.arg not in ("self", "cls")]


def _used_fixtures(decorators: Iterable[ast.expr]) -> list[str]:
    """The names of `@pytest.mark.usefixtures("a", "b")`."""
    out: list[str] = []
    for d in decorators:
        if isinstance(d, ast.Call) and ast.unparse(d.func).endswith("usefixtures"):
            out += [a.value for a in d.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
    return out


class SkipFacts:
    """Everything the skip rule reads from one source, computed once: `ok` (it parses), the constructs, the collected
    tests, the shared scopes, and, per test, the closure (`closure`)."""

    def __init__(self, source: str) -> None:
        tree = scan.parse(source)
        self.ok = tree is not None
        self.constructs: Counter[tuple[str, str]] = Counter()
        self.collected: set[str] = set()
        self.shared: set[str] = set()
        self.tests: list[tuple[str, _FUNCTIONS]] = []
        self.ambiguous: set[str] = set()
        self._defs: dict[str, tuple[_FUNCTIONS, ast.ClassDef | None]] = {}
        if tree is None:
            return
        self.tree = tree
        self.reader = scan.SkipReader(tree)
        self.constructs = scan.skip_constructs_in(tree, self.reader)
        self.collected = scan.collected_in(tree)
        names = scan.fixture_names(tree)
        qualified = list(scan.qualified(tree))
        self.shared = {q for q, _ in qualified} - self.collected
        self.tests = [(q, f) for q, f in qualified if q in self.collected]  # every def of a collected test, in order
        twice = Counter(q for q, _ in qualified)
        top = Counter(n.name for n in tree.body if isinstance(n, _FUNCTIONS | ast.ClassDef))
        self.ambiguous = {name for name, n in (*twice.items(), *top.items()) if n > 1}  # which def runs is not told
        classes = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
        for q, function in qualified:
            self._defs[q] = (function, classes.get(q.split(".")[0]) if "." in q else None)
        self._fixture_names = names
        self._module = _bindings(tree.body)
        self._class_cache: dict[str, dict[str, list[_Binding]]] = {}
        self._methods_cache: dict[str, frozenset[str]] = {}
        self._dumps: dict[int, str] = {}
        self._loads: dict[int, frozenset[str]] = {}
        self._skippy_names: frozenset[str] | None = None
        self._prefixes: dict[int, list[ast.stmt]] = {}
        self._fixtures: dict[str | None, dict[str, list[_FUNCTIONS]]] = {}
        self._fixtures[None] = self._fixtures_of(tree.body)
        for c in classes.values():
            self._fixtures[c.name] = self._fixtures_of(c.body)
        self._shared_cache: dict[str | None, list[ast.AST]] = {}

    # --- the parts ---------------------------------------------------------------------------------------------------

    def _fixtures_of(self, body: list[ast.stmt]) -> dict[str, list[_FUNCTIONS]]:
        out: dict[str, list[_FUNCTIONS]] = {}
        for node in body:
            if isinstance(node, _FUNCTIONS) and scan.is_fixture(node, self._fixture_names):
                out.setdefault(_fixture_name(node), []).append(node)
        return out

    def _skippy(self, node: ast.AST) -> bool:
        return self.reader.skippy(node)

    def _skippy_binding_names(self) -> frozenset[str]:
        """The module names whose binding skips, or loads a name that does (`requires_stack = pytest.mark.skipif(...)`,
        a helper that calls `pytest.skip`, a fixture that does)."""
        if self._skippy_names is None:
            names = {
                n
                for n, bindings in self._module.items()
                if any(not isinstance(b.node, ast.Import | ast.ImportFrom) and self._skippy(b.node) for b in bindings)
            }
            grown = True
            while grown:
                grown = False
                for n, bindings in self._module.items():
                    if n not in names and any(b.loads() & names for b in bindings):
                        names.add(n)
                        grown = True
            self._skippy_names = frozenset(names)
        return self._skippy_names

    def _shared_parts(self, cls: ast.ClassDef | None) -> list[ast.AST]:
        """The parts every test of the module (`cls` None) or of the class `cls` has: skip statements that are not defs,
        the whole of every function or method that no runner collects and that skips, every `autouse` fixture."""
        key = None if cls is None else cls.name
        if key not in self._shared_cache:
            body = self.tree.body if cls is None else cls.body
            parts: list[ast.AST] = []
            for node in body:
                if isinstance(node, _FUNCTIONS):
                    qualified = node.name if cls is None else f"{cls.name}.{node.name}"
                    if qualified not in self.collected and (_is_autouse(node) or self._skippy(node)):
                        parts.append(node)
                elif not isinstance(node, ast.ClassDef) and (_is_pytestmark(node) or self._skippy(node)):
                    parts.append(node)
            self._shared_cache[key] = parts
        return self._shared_cache[key]

    def _dump(self, node: ast.AST) -> str:
        """`ast.dump` of a part, once: the module's own parts are in the closure of every test of the file."""
        if id(node) not in self._dumps:
            self._dumps[id(node)] = ast.dump(node)
        return self._dumps[id(node)]

    def _loads_of(self, node: ast.AST) -> frozenset[str]:
        if id(node) not in self._loads:
            self._loads[id(node)] = _loaded([node])
        return self._loads[id(node)]

    def _skippy_methods(self, cls: ast.ClassDef | None) -> frozenset[str]:
        """The names of the methods of `cls` that no runner collects and that skip (`self.need()` in a body)."""
        if cls is None:
            return frozenset()
        if cls.name not in self._methods_cache:
            self._methods_cache[cls.name] = frozenset(
                m.name
                for m in cls.body
                if isinstance(m, _FUNCTIONS) and f"{cls.name}.{m.name}" not in self.collected and self._skippy(m)
            )
        return self._methods_cache[cls.name]

    def _prefix(self, function: _FUNCTIONS, cls: ast.ClassDef | None) -> list[ast.stmt]:
        """The statements of the body up to and including the last that can skip (once per function)."""
        if id(function) not in self._prefixes:
            self._prefixes[id(function)] = self._prefix_of(function, cls)
        return self._prefixes[id(function)]

    def _prefix_of(self, function: _FUNCTIONS, cls: ast.ClassDef | None) -> list[ast.stmt]:
        names = self._skippy_binding_names()
        methods = self._skippy_methods(cls)
        last = -1
        for i, statement in enumerate(function.body):
            walked = list(ast.walk(statement))
            if (
                self._skippy(statement)
                or any(isinstance(n, ast.Name) and n.id in names for n in walked)
                or any(isinstance(n, ast.Attribute) and n.attr in methods for n in walked)
            ):
                last = i
        return function.body[: last + 1]

    def _fixture_parts(self, function: _FUNCTIONS, cls: ast.ClassDef | None) -> list[ast.AST]:
        """The definitions of the fixtures the test takes and of those they take (a class's own before the module's)."""
        wanted = [*_params(function), *_used_fixtures(function.decorator_list)]
        if cls is not None:
            wanted += _used_fixtures(cls.decorator_list)
        scopes = [self._fixtures.get(cls.name if cls else None, {}), self._fixtures[None]]
        for scope in scopes:
            wanted += [name for name, defs in scope.items() if any(_is_autouse(d) for d in defs)]
        seen: set[str] = set()
        parts: list[ast.AST] = []
        while wanted:
            name = wanted.pop()
            if name in seen:
                continue
            seen.add(name)
            for scope in scopes:
                for definition in scope.get(name, ()):
                    parts.append(definition)
                    wanted += _params(definition)
        return parts

    def _class_bindings(self, cls: ast.ClassDef) -> dict[str, list[_Binding]]:
        if cls.name not in self._class_cache:
            self._class_cache[cls.name] = _bindings(cls.body)
        return self._class_cache[cls.name]

    def skip_relevant(self, qualname: str) -> tuple[_FUNCTIONS, list[ast.stmt]] | None:
        """The def of the test `qualname` and the statements of its body that can decide whether it skips (the prefix
        of the closure); None when the source does not hold it, or holds it more than once."""
        found = self._defs.get(qualname) if self.ok else None
        if found is None or qualname in self.ambiguous or qualname.split(".", 1)[0] in self.ambiguous:
            return None
        return found[0], self._prefix(*found)

    # --- the closure -------------------------------------------------------------------------------------------------

    def closure(self, qualname: str) -> Closure | None:
        """The closure of the test `qualname` (module function or method of a module-level class), None when the source
        does not hold it or the names go deeper than `DEPTH`."""
        found = self._defs.get(qualname) if self.ok else None
        if found is None:
            return None
        function, cls = found
        parts: list[ast.AST] = [*function.decorator_list, *self._prefix(function, cls)]
        if cls is not None:
            parts += [*cls.decorator_list, *cls.bases, *(k.value for k in cls.keywords)]
        parts += [*self._shared_parts(cls), *self._shared_parts(None), *self._fixture_parts(function, cls)]
        out: Closure = Counter()
        seen_parts: set[int] = set()
        unique: list[ast.AST] = []
        for part in parts:
            if id(part) not in seen_parts:
                seen_parts.add(id(part))
                unique.append(part)
                out[("part", self._dump(part))] += 1
        class_bindings = self._class_bindings(cls) if cls is not None else {}
        seen: set[str] = set()
        frontier = set().union(*(self._loads_of(part) for part in unique))
        for _ in range(DEPTH):
            seen |= frontier
            following: set[str] = set()
            for name in frontier:
                for binding in class_bindings.get(name) or self._module.get(name) or ():
                    out[(f"bind {name}", binding.text())] += 1
                    following |= binding.loads()
            frontier = following - seen
            if not frontier:
                return out
        return None
