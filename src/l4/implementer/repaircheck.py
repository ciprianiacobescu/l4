"""The structural check of a repair (own-test-repair, L4-IMP-091, second paragraph).

Pure: the text of a test file before and after a repair step, and the qualified names of the tests the step may repair
(`test_x`, or `Class.test_x` for a method of a module-level class), in; the rules the change breaks, out. Python only,
no git. A repair may change the definitions of those tests and add imports, and nothing else: every other statement of
the module (helpers, fixtures, constants, other tests, the class around a repaired method) is equal on the AST,
imports may only be added (never duplicated or moved, never a builtin or a check-like name shadowed), and a repaired
test keeps its decorators and signature, its number of top-level statements and every check it had, by name, in its
own scope. It adds no return, no always-true assert, no check that a short-circuit or a conditional may skip, no write
to a name outside its locals, and no call that reaches the module or the interpreter (`globals`, `setattr`, `exec`,
`__import__`, ...). The file must be UTF-8 (`encoding_problem`): pytest honours a `# coding:` cookie, so another
codec could hide code from this AST. What the rules cannot see is a check rewritten into a weaker one that still
passes: the repair step re-proves the repaired tests by the discrimination runs (L4-IMP-091), and the judge sees the
diff in the next round (L4-VER-070).

No public name here starts with `test` (a test module that imports this one must not collect it)."""

import ast
import builtins
import io
import tokenize
from collections import Counter
from collections.abc import Collection, Iterable
from dataclasses import dataclass, field

from l4.implementer.tamper import Facts, _import_parts, _parse, _stored, facts_of

MAX_NAMES = 5  # names a rule lists
MAX_CHANGED_STATEMENTS = 3  # top-level statements of a repaired test that may differ, each replaced in place
_COMPOUND = (ast.Try, ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Match, ast.TryStar)
_BAILOUTS = frozenset({"skip", "skipif", "xfail", "importorskip", "exit", "_exit", "quit", "SystemExit", "SkipTest"})
_WEAK_WAITS = frozenset({"wait_for_timeout", "wait_for_load_state"})  # these wait and check nothing
_DEF = (ast.FunctionDef, ast.AsyncFunctionDef)
_NESTED = (
    ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef,
    ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp,
)  # fmt: skip
_CONDITIONAL = (ast.BoolOp, ast.IfExp, ast.NamedExpr)  # a check below one of these may be skipped
_REACH_OUT = frozenset({"globals", "vars", "setattr", "delattr", "__import__", "exec", "eval", "compile"})
_CHECK_PREFIXES = ("assert", "expect", "wait_for")  # a name an import may not bind: the test would "call a check"
_BANNED_IMPORT_NAMES = frozenset({"ANY"})  # `unittest.mock.ANY` equals everything
_BUILTIN_NAMES = frozenset(dir(builtins))
_UTF8 = ("utf-8", "utf-8-sig")
# What a replaced statement may not even load, under any alias: the process, the filesystem, the interpreter's
# internals, and the reflection that reaches them. A proof run is told from the real gate by exactly these (the
# environment, a file that only one of them has), and a payload that rebinds what other tests use needs exactly these.
_DENIED = frozenset({
    "os", "sys", "pathlib", "open", "inspect", "__file__", "__dict__", "__globals__", "__builtins__", "__setattr__",
    "setattr", "getattr", "delattr", "globals", "vars", "object", "type", "functools", "operator", "importlib",
    "builtins", "environ", "getenv",
})  # fmt: skip
_DENIED_ATTRS = frozenset({
    "environ", "getenv", "setattr", "getattr", "delattr", "globals", "vars", "importlib", "builtins", "functools",
    "operator", "inspect", "sys", "os", "pathlib",
})  # fmt: skip  # an attribute of this name, or any dunder attribute
_IMPORT_ALLOWED = frozenset({"re", "json", "datetime", "math", "decimal", "fractions"})  # what a repair may import
_SAFE_BUILTINS = frozenset({
    "len", "str", "int", "float", "bool", "list", "dict", "tuple", "set", "frozenset", "sum", "min", "max", "abs",
    "round", "sorted", "reversed", "range", "enumerate", "zip", "map", "filter", "any", "all", "repr", "bytes",
    "print", "isinstance",
})  # fmt: skip


@dataclass(frozen=True)
class Broken:
    rule: str  # a short name, stable for the retry prompt and the tests
    detail: str  # what changed, for the agent


def reason(found: Iterable[Broken]) -> str:
    """The failure text of an attempt: every rule the change broke, with what changed."""
    return "; ".join(f"{b.rule}: {b.detail}" for b in found)


def encoding_problem(data: bytes) -> str | None:
    """Why a test file cannot be checked as UTF-8 text, or None. Python reads a source file in the encoding of its
    `# coding:` cookie (or a BOM), so a file that declares another codec is not the text the AST was built from: code
    can hide in what looks like a comment (`# coding: utf-7`). Only UTF-8, with or without a BOM, is accepted."""
    try:
        declared, _ = tokenize.detect_encoding(io.BytesIO(data).readline)
    except (SyntaxError, LookupError, ValueError) as exc:
        return f"its encoding declaration cannot be read ({exc})"
    if declared not in _UTF8:
        return f"it declares the encoding {declared}; a repaired test file is UTF-8"
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return "it is not UTF-8 text"
    return None


def _bound(tree: ast.Module, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    """The function a qualified test name stands for, when the module has one class of that name and one def."""
    scope: list[ast.stmt] = tree.body
    owner, _, function = name.rpartition(".")
    if owner:
        classes = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == owner]
        if len(classes) != 1:
            return None
        scope = classes[0].body
    defs = [n for n in scope if isinstance(n, _DEF) and n.name == function]
    return defs[0] if len(defs) == 1 else None


def _defined_once(facts: dict[str, Facts], tree: ast.Module, name: str) -> bool:
    """`name` is a test bound by one `def` (no second def, assignment, import or `del` of it) in its scope."""
    fact = facts.get(name)
    return fact is not None and fact.test and len(fact.parts) == 1 and _bound(tree, name) is not None


def _blank(tree: ast.Module, names: Collection[str]) -> None:
    """Replace each repaired function by a stand-in at the same place, so that what is left can be compared."""
    for name in names:
        owner, _, function = name.rpartition(".")
        scopes = (
            [tree.body] if not owner else [c.body for c in tree.body if isinstance(c, ast.ClassDef) and c.name == owner]
        )
        for body in scopes:
            for index, node in enumerate(body):
                if isinstance(node, _DEF) and node.name == function:
                    body[index] = ast.Expr(ast.Constant(f"<repaired {name}>"))


def _imports(tree: ast.Module) -> list[ast.Import | ast.ImportFrom]:
    return [n for n in tree.body if isinstance(n, ast.Import | ast.ImportFrom)]


def _bindings(imports: Iterable[ast.Import | ast.ImportFrom]) -> set[tuple[str, str]]:
    found: set[tuple[str, str]] = set()
    for node in imports:
        found |= set(_import_parts(node))
        if any(a.name == "*" for a in node.names):
            found.add(("*", f"from {node.module or ''} import *"))
    return found


def _dump(node: ast.AST) -> str:
    return ast.dump(node, include_attributes=False)


def _has_substance(node: ast.AST) -> bool:
    """The expression reads a name, calls something or reads an attribute or an item: its value can depend on what the
    page or the product does. `1 == 1`, `-1`, `not None` and `True` cannot."""
    return any(isinstance(n, ast.Name | ast.Call | ast.Attribute | ast.Subscript | ast.Await) for n in ast.walk(node))


def _trivial(test: ast.expr) -> bool:
    """An assert that cannot fail whatever the page does: it reads nothing, it is a non-empty container (always true),
    it compares an expression with itself, or it is an `or` with such an operand."""
    if not _has_substance(test):
        return True
    if isinstance(test, ast.Tuple | ast.List | ast.Set):
        return bool(test.elts)
    if isinstance(test, ast.Dict):
        return bool(test.keys)
    if isinstance(test, ast.Compare) and len(test.comparators) == 1:
        same = _dump(test.left) == _dump(test.comparators[0])
        return same and isinstance(test.ops[0], ast.Eq | ast.Is | ast.LtE | ast.GtE)
    if isinstance(test, ast.BoolOp):
        return (
            any(_trivial(v) for v in test.values)
            if isinstance(test.op, ast.Or)
            else all(_trivial(v) for v in test.values)
        )
    return False


def _norm(name: str) -> str:
    """A check's name without its family prefix, so that `expect(page).to_have_url(...)` and `page.wait_for_url(...)`
    are the same check; a negated matcher keeps its `not_`."""
    for prefix in ("not_to_have_", "not_to_be_", "not_to_"):
        if name.startswith(prefix) and len(name) > len(prefix):
            return "not_" + name[len(prefix) :].lower()
    for prefix in ("to_have_", "to_be_", "to_", "wait_for_", "assert_", "assert"):
        if name.startswith(prefix) and len(name) > len(prefix):
            return name[len(prefix) :].lower()
    return name.lower()


def _rooted_in_expect(node: ast.expr) -> bool:
    while isinstance(node, ast.Attribute):
        node = node.value
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name | ast.Attribute)
        and ((node.func.id if isinstance(node.func, ast.Name) else node.func.attr) == "expect")
    )


def _check_name(call: ast.Call) -> str | None:
    """The normalised name of the check a call is: a matcher of `expect(...)` (`to_have_url`), a call named `assert...`
    or `wait_for_...` (not the ones that only wait). `expect(page)` alone checks nothing and is no check."""
    func = call.func
    if isinstance(func, ast.Attribute):
        if func.attr.startswith(("to_", "not_to_")) and _rooted_in_expect(func.value):
            return _norm(func.attr)
        name = func.attr
    elif isinstance(func, ast.Name):
        name = func.id
    else:
        return None
    if name.startswith("assert") or (name.startswith("wait_for") and name not in _WEAK_WAITS):
        return _norm(name)
    return None


def _root(node: ast.expr) -> ast.expr:
    while isinstance(node, ast.Attribute | ast.Subscript):
        node = node.value
    return node


@dataclass
class _Scan:
    """What one test does, counted: checks by name in its own scope and in the scopes nested in it (a nested `def`, a
    lambda, a comprehension: code that may never run), and the things a repair may not add."""

    checks: Counter[str] = field(default_factory=Counter)
    nested_checks: Counter[str] = field(default_factory=Counter)
    asserts: int = 0  # assert statements of the test's own scope
    conditional: int = 0  # checks below a short-circuit, a conditional expression or a walrus
    returns: int = 0  # return, yield and yield from of the test's own scope
    trivial: int = 0  # asserts that cannot fail
    constant_operands: int = 0  # and/or operands that read nothing
    bails: Counter[str] = field(default_factory=Counter)
    reach: int = 0  # writes outside the test's locals, global/nonlocal, calls that reach the module or interpreter


def _scope_nodes(body: Iterable[ast.AST]) -> Iterable[ast.AST]:
    """The nodes of one scope: a nested `def`, class, lambda or comprehension is yielded itself, not entered (its
    decorators and defaults are the enclosing scope's, and are entered)."""
    todo = list(body)
    while todo:
        node = todo.pop()
        yield node
        if isinstance(node, (*_DEF, ast.ClassDef)):
            todo.extend(node.decorator_list)
        elif isinstance(node, ast.Lambda):
            todo.extend([*node.args.defaults, *(d for d in node.args.kw_defaults if d)])
        elif isinstance(node, _NESTED):
            continue
        else:
            todo.extend(ast.iter_child_nodes(node))


def _params(args: ast.arguments) -> set[str]:
    return {x.arg for x in (*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg) if x}


def _locals_of(func: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """The names bound in the test's OWN scope: its parameters and what its own statements bind. A comprehension's
    target or a nested function's local is not one (it could otherwise make a module name look local)."""
    names = _params(func.args)
    for node in _scope_nodes(func.body):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
        elif isinstance(node, ast.Import | ast.ImportFrom):
            names |= {n for n, _ in _import_parts(node)}
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(node.name)
    return names


def _scan(func: ast.FunctionDef | ast.AsyncFunctionDef) -> _Scan:
    scan, local = _Scan(), _locals_of(func)
    awaited = isinstance(func, ast.AsyncFunctionDef)  # there a check that is not awaited never runs

    def visit(node: ast.AST, nested: bool, cond: bool, parent: ast.AST | None = None) -> None:
        if isinstance(node, ast.Assert):
            (scan.nested_checks if nested else scan.checks)["assert"] += 1
            scan.asserts += 0 if nested else 1
            scan.trivial += _trivial(node.test)
        elif isinstance(node, ast.Call):
            if (name := _check_name(node)) is not None and (nested or not awaited or isinstance(parent, ast.Await)):
                (scan.nested_checks if nested else scan.checks)[name] += 1
                scan.conditional += cond
            callee = node.func
            terminal = (
                callee.id if isinstance(callee, ast.Name) else callee.attr if isinstance(callee, ast.Attribute) else ""
            )
            root = _root(callee) if isinstance(callee, ast.Attribute) else callee
            reaches = terminal in _REACH_OUT and (isinstance(callee, ast.Name) or terminal != "compile")  # `re.compile`
            if reaches or (isinstance(root, ast.Name) and root.id == "importlib"):
                scan.reach += 1
        elif isinstance(node, ast.BoolOp):
            scan.constant_operands += sum(not _has_substance(v) for v in node.values)
        elif isinstance(node, ast.Return | ast.Yield | ast.YieldFrom) and not nested:
            scan.returns += 1
        elif isinstance(node, ast.Global | ast.Nonlocal):
            scan.reach += 1
        elif isinstance(node, ast.Attribute | ast.Subscript) and isinstance(node.ctx, ast.Store | ast.Del):
            base = _root(node)
            scan.reach += not (isinstance(base, ast.Name) and base.id in local)
        ident = node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else ""
        if ident in _BAILOUTS:
            scan.bails[ident] += 1
        for child in ast.iter_child_nodes(node):
            visit(child, nested or isinstance(child, _NESTED), cond or isinstance(node, _CONDITIONAL), node)

    for statement in func.body:
        visit(statement, isinstance(statement, _NESTED), False)
    return scan


def _compound_added(was: ast.stmt, now: ast.stmt) -> list[str]:
    def count(node: ast.AST) -> Counter[str]:
        return Counter(type(n).__name__ for n in ast.walk(node) if isinstance(n, _COMPOUND))

    a, b = count(was), count(now)
    return sorted(k for k in b if b[k] > a[k])


@dataclass(frozen=True)
class _Module:
    """What the module around the tests says that the vocabulary rule needs: the names its imports and plain aliases
    stand for (`aliases`), the names it binds exactly once at module level (`once`; a name bound twice is rebound and
    cannot be trusted), and the names the step's new, allowed imports bind (`added`)."""

    aliases: dict[str, str]
    once: frozenset[str]
    added: frozenset[str]


def _dotted(node: ast.expr) -> str | None:
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if not isinstance(node, ast.Name):
        return None
    return ".".join([node.id, *reversed(parts)])


def _aliases(body: Iterable[ast.AST]) -> dict[str, str]:
    """name -> the dotted name it stands for, from imports (`import os as o`, `from os import path as p`) and plain
    assignments of a name or an attribute chain (`o = os`)."""
    found: dict[str, str] = {}
    for node in body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                found[alias.asname or alias.name.split(".")[0]] = (
                    alias.name if alias.asname else alias.name.split(".")[0]
                )
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                found[alias.asname or alias.name] = ".".join(
                    x for x in ("." * node.level + (node.module or ""), alias.name) if x
                )
        elif (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and (value := _dotted(node.value)) is not None
        ):
            found[node.targets[0].id] = value
    return found


def _module_facts(old: ast.Module, new: ast.Module, extras: Collection[ast.stmt]) -> _Module:
    counts: Counter[str] = Counter()
    for statement in old.body:
        if isinstance(statement, ast.Import | ast.ImportFrom):
            counts.update(n for n, _ in _import_parts(statement))
        else:
            counts.update(_stored(statement))
    added = {
        n
        for node in extras
        if isinstance(node, ast.Import | ast.ImportFrom) and _import_module(node) in _IMPORT_ALLOWED
        for n, _ in _import_parts(node)
    }
    return _Module(_aliases(new.body), frozenset(n for n, c in counts.items() if c == 1), frozenset(added))


def _import_module(node: ast.Import | ast.ImportFrom) -> str:
    """The top-level module an import brings in ("" for a relative import or a `*`)."""
    if isinstance(node, ast.ImportFrom):
        return "" if node.level or not node.module else node.module.split(".")[0]
    tops = {a.name.split(".")[0] for a in node.names}
    return tops.pop() if len(tops) == 1 else ""


def _denied(name: str, aliases: dict[str, str]) -> bool:
    """`name`, or what it is an alias of, is a denied name (or a dunder)."""
    seen: set[str] = set()
    while name not in seen:
        seen.add(name)
        parts = name.split(".")
        if any(part in _DENIED or (part.startswith("__") and part.endswith("__")) for part in parts):
            return True
        target = aliases.get(parts[0])
        if target is None:
            return False
        name = ".".join([target, *parts[1:]])
    return False


def _vocabulary(
    now: ast.FunctionDef | ast.AsyncFunctionDef,
    was: ast.FunctionDef | ast.AsyncFunctionDef,
    changed: Iterable[ast.stmt],
    module: _Module,
) -> list[str]:
    """The names a replaced statement loads that it may not: a denied name or attribute (under any alias), a name the
    test never used before the step and the module does not bind exactly once, or a name that only a new import not on
    the short list would bind. What the statement binds itself, a lambda's or a comprehension's own names, the test's
    parameters and its own locals (its own scope only) are fine, and so are the pure builtins."""
    used = {n.id for n in ast.walk(was) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    aliases = {**module.aliases, **_aliases(_scope_nodes(now.body))}
    own = _locals_of(now)
    allowed = used | module.once | module.added | own | _SAFE_BUILTINS
    found: list[str] = []

    def visit(node: ast.AST, bound: frozenset[str]) -> None:
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            if _denied(node.id, aliases) or (node.id not in bound and node.id not in allowed):
                found.append(node.id)
        elif isinstance(node, ast.Attribute) and (
            node.attr in _DENIED_ATTRS or (node.attr.startswith("__") and node.attr.endswith("__"))
        ):
            found.append(f".{node.attr}")
        if isinstance(node, ast.Lambda):
            for default in (*node.args.defaults, *(d for d in node.args.kw_defaults if d)):
                visit(default, bound)
            visit(node.body, bound | _params(node.args))
        elif isinstance(node, ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp):
            targets = {n.id for g in node.generators for n in ast.walk(g.target) if isinstance(n, ast.Name)}
            inner = bound | targets
            visit(node.generators[0].iter, bound)  # evaluated in the enclosing scope
            for position, generator in enumerate(node.generators):
                if position:
                    visit(generator.iter, inner)
                for condition in generator.ifs:
                    visit(condition, inner)
            for child in (node.key, node.value) if isinstance(node, ast.DictComp) else (node.elt,):
                visit(child, inner)
        elif isinstance(node, _DEF):
            inner = bound | _params(node.args) | _locals_of(node)
            for expression in (*node.decorator_list, *node.args.defaults, *(d for d in node.args.kw_defaults if d)):
                visit(expression, bound)
            for statement in node.body:
                visit(statement, inner)
        else:
            for child in ast.iter_child_nodes(node):
                visit(child, bound)

    for statement in changed:
        visit(statement, frozenset())
    return sorted(dict.fromkeys(found))


def _function_rules(
    name: str, was: ast.FunctionDef | ast.AsyncFunctionDef, now: ast.FunctionDef | ast.AsyncFunctionDef,
    module: _Module,
) -> list[Broken]:  # fmt: skip
    found: list[Broken] = []
    if [_dump(n) for n in was.decorator_list] != [_dump(n) for n in now.decorator_list]:
        found.append(Broken("decorators", f"{name}: its decorators or marks changed"))
    signature = lambda f: (type(f).__name__, ast.dump(f.args), ast.dump(f.returns) if f.returns else "")  # noqa: E731
    if signature(was) != signature(now):
        found.append(
            Broken("signature", f"{name}: its parameters (the fixtures it requests) or its return type changed")
        )
    if len(was.body) != len(now.body):
        found.append(Broken("statement-count", f"{name}: it had {len(was.body)} statements and has {len(now.body)}"))
    else:
        differing = [i for i, (a, b) in enumerate(zip(was.body, now.body, strict=True)) if _dump(a) != _dump(b)]
        if len(differing) > MAX_CHANGED_STATEMENTS:
            found.append(
                Broken(
                    "too-many-statements",
                    f"{name}: {len(differing)} statements changed, at most {MAX_CHANGED_STATEMENTS} may",
                )
            )
        for i in differing:
            if added := _compound_added(was.body[i], now.body[i]):
                found.append(Broken("compound-added", f"{name}: statement {i + 1} gained a {', '.join(added)}"))
        if offending := _vocabulary(now, was, [now.body[i] for i in differing], module):
            found.append(
                Broken(
                    "vocabulary",
                    f"{name}: a replaced statement loads {', '.join(offending[:MAX_NAMES])}, which the test did not "
                    "use before and the module does not bind once, or which a repair may not touch",
                )
            )
    before, after = _scan(was), _scan(now)
    if after.asserts < before.asserts:
        found.append(
            Broken("assert-removed", f"{name}: it had {before.asserts} assert statements and has {after.asserts}")
        )
    gone = sorted(
        [k for k in before.checks if after.checks[k] < before.checks[k]]
        + [f"{k} (nested)" for k in before.nested_checks if after.nested_checks[k] < before.nested_checks[k]]
    )
    if gone:
        found.append(Broken("check-dropped", f"{name}: fewer of these checks than before: {', '.join(gone)}"))
    if after.conditional > before.conditional:
        found.append(
            Broken(
                "conditional-check",
                f"{name}: a check sits below `and`/`or`, a conditional or `:=`, where it may not run",
            )
        )
    if after.returns > before.returns:
        found.append(Broken("return-added", f"{name}: a return or yield was added; the rest of the test may never run"))
    if after.trivial > before.trivial:
        found.append(Broken("assert-constant", f"{name}: an assert that cannot fail was added"))
    if after.constant_operands > before.constant_operands:
        found.append(Broken("constant-operand", f"{name}: an and/or operand that reads nothing was added"))
    if bails := sorted(k for k in after.bails if after.bails[k] > before.bails[k]):
        found.append(Broken("skip-added", f"{name}: it now uses {', '.join(bails)}"))
    if after.reach > before.reach:
        found.append(
            Broken("side-effect", f"{name}: it now writes outside its locals or reaches the module or the interpreter")
        )
    return found


def _new_imports(old: ast.Module, new: ast.Module) -> tuple[list[ast.stmt], list[str]]:
    """The import statements of `new` that `old` does not have, and the imports of `old` that `new` lost, as a multiset
    (an import repeated is a new one). Their order and place among the other statements is checked with the rest of the
    module."""
    remaining = Counter(_dump(n) for n in _imports(old))
    extras: list[ast.stmt] = []
    for node in _imports(new):
        key = _dump(node)
        if remaining[key] > 0:
            remaining[key] -= 1
        else:
            extras.append(node)
    return extras, sorted(k for k, n in remaining.items() for _ in range(n))


def check_repair(before: str, after: str, tests: Collection[str]) -> list[Broken]:
    """The rules the change from `before` to `after` breaks for a repair of `tests`; empty when it keeps them all."""
    old, new = _parse(before), _parse(after)
    if old is None or new is None:
        return [
            Broken(
                "unparsable", "the file before the step does not parse" if old is None else "the file does not parse"
            )
        ]
    names = sorted(set(tests))
    facts_before, facts_after = facts_of(before) or {}, facts_of(after) or {}
    sides = ((facts_before, old), (facts_after, new))
    missing = (
        [n for n in names if not all(_defined_once(f, t, n) for f, t in sides)] if names else ["(none named)"]
    )  # nothing named repairs nothing
    if missing:
        return [Broken("repaired-test-missing", f"not defined once in the file before and after: {', '.join(missing)}")]
    found: list[Broken] = []
    pairs = [(n, _bound(old, n), _bound(new, n)) for n in names]
    blank_old, blank_new = _parse(before), _parse(after)
    assert blank_old is not None and blank_new is not None
    _blank(blank_old, names)
    _blank(blank_new, names)
    extras, lost = _new_imports(blank_old, blank_new)
    kept = {id(n) for n in extras}
    if [_dump(n) for n in blank_old.body] != [_dump(n) for n in blank_new.body if id(n) not in kept]:
        found.append(
            Broken(
                "outside-changed", "a statement of the file other than the repaired tests and the new imports changed"
            )
        )
    if lost:
        found.append(Broken("import-removed", f"imports may only be added, in place: {lost[0]}"))
    old_imports = {_dump(n) for n in _imports(old)}
    if duplicated := [n for n in extras if _dump(n) in old_imports]:
        found.append(Broken("import-duplicated", f"an existing import was repeated: {ast.unparse(duplicated[0])}"))
    new_bindings = _bindings(n for n in extras if isinstance(n, ast.Import | ast.ImportFrom))
    if any(n == "*" for n, _ in new_bindings):
        found.append(Broken("import-star", "`from x import *` binds names nobody can see"))
    if any(t.startswith("from __future__") for _, t in new_bindings):
        found.append(Broken("future-import", "a `__future__` import changes the whole file"))
    taken: set[str] = {n for n, _ in _bindings(_imports(old))} | _BUILTIN_NAMES
    for statement in old.body:
        if not isinstance(statement, ast.Import | ast.ImportFrom):
            taken |= _stored(statement)
    bound = {n for n, _ in new_bindings if n != "*"}
    if shadows := sorted(bound & taken):
        found.append(
            Broken(
                "import-shadows", f"a new import binds a name the file or Python already binds: {', '.join(shadows)}"
            )
        )
    if banned := sorted(n for n in bound if n.startswith(_CHECK_PREFIXES) or n in _BANNED_IMPORT_NAMES):
        found.append(Broken("import-banned", f"a new import binds a name that looks like a check: {', '.join(banned)}"))
    if foreign := sorted({ast.unparse(n) for n in extras if _import_module(n) not in _IMPORT_ALLOWED}):  # type: ignore[arg-type]
        found.append(
            Broken(
                "import-banned",
                f"a repair may import only {', '.join(sorted(_IMPORT_ALLOWED))}: {foreign[0]}",
            )
        )
    module = _module_facts(old, new, extras)
    for name, was, now in pairs:
        assert was is not None and now is not None
        found += _function_rules(name, was, now, module)
    return found


def check_repair_files(before: bytes, after: bytes, tests: Collection[str]) -> list[Broken]:
    """`check_repair` on the bytes of the two files: both must be UTF-8 (`encoding_problem`), else the first rule broken
    is `encoding`. What the step and the verifier both call."""
    for when, data in (("before", before), ("after", after)):
        if (why := encoding_problem(data)) is not None:
            return [Broken("encoding", f"the file {when} the step: {why}")]
    return check_repair(before.decode("utf-8-sig"), after.decode("utf-8-sig"), tests)


def function_source(source: str, name: str) -> str | None:
    """The lines of the test `name` (decorators included) in `source`, or None when the file does not parse or does not
    define it once: what the judge is shown of a repaired test, before and after the repair (L4-VER-070)."""
    tree = _parse(source)
    node = _bound(tree, name) if tree is not None else None
    if node is None:
        return None
    first = min([node.lineno, *(d.lineno for d in node.decorator_list)])
    lines = source.splitlines()[first - 1 : node.end_lineno]
    return "\n".join(lines)
