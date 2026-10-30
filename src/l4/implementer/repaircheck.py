"""The structural check of a repair (own-test-repair, L4-IMP-091, second paragraph).

Pure: the text of a test file before and after a repair step, and the qualified names of the tests the step may repair
(`test_x`, or `Class.test_x` for a method of a module-level class), in; the rules the change breaks, out. Python only,
no git. A repair may change the definitions of those tests and add imports, and nothing else: every other statement of
the module (helpers, fixtures, constants, other tests, the class around a repaired method) is equal on the AST,
imports may only be added, and a repaired test keeps its decorators and signature, its number of top-level statements
and every check it had. What it cannot see is a check rewritten into a weaker one that still passes; the judge sees the
diff in the next round (L4-VER-070).

No public name here starts with `test` (a test module that imports this one must not collect it)."""

import ast
from collections import Counter
from collections.abc import Collection, Iterable
from dataclasses import dataclass

from l4.implementer.tamper import Facts, _import_parts, _parse, _stored, facts_of

MAX_CHANGED_STATEMENTS = 3  # top-level statements of a repaired test that may differ, each replaced in place
_COMPOUND = (ast.Try, ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Match, ast.TryStar)
_BAILOUTS = frozenset({"skip", "skipif", "xfail", "importorskip", "exit", "_exit", "quit", "SystemExit"})
_WEAK_WAITS = frozenset({"wait_for_timeout", "wait_for_load_state"})  # these wait and check nothing
_DEF = (ast.FunctionDef, ast.AsyncFunctionDef)


@dataclass(frozen=True)
class Broken:
    rule: str  # a short name, stable for the retry prompt and the tests
    detail: str  # what changed, for the agent


def reason(found: Iterable[Broken]) -> str:
    """The failure text of an attempt: every rule the change broke, with what changed."""
    return "; ".join(f"{b.rule}: {b.detail}" for b in found)


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


def _outside(tree: ast.Module) -> list[str]:
    """The module's statements other than top-level imports, as AST dumps."""
    return [ast.dump(n, include_attributes=False) for n in tree.body if not isinstance(n, ast.Import | ast.ImportFrom)]


def _trivial(test: ast.expr) -> bool:
    """An assert that cannot fail whatever the page does: a constant, a non-empty tuple (always true), or an `or` with
    a constant operand."""
    if isinstance(test, ast.Constant):
        return True
    if isinstance(test, ast.Tuple):
        return bool(test.elts)
    return isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or) and any(_trivial(v) for v in test.values)


def _count(node: ast.AST) -> Counter[str]:
    """What a test does that can fail it or end it early: asserts, calls of `expect`, `assert...` and `wait_for_...`,
    constant asserts, compound statements and the names that skip or stop a run."""
    found: Counter[str] = Counter()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Assert):
            found["assert"] += 1
            found["check"] += 1
            if _trivial(sub.test):
                found["constant"] += 1
        elif isinstance(sub, ast.Call):
            name = (
                sub.func.id
                if isinstance(sub.func, ast.Name)
                else sub.func.attr
                if isinstance(sub.func, ast.Attribute)
                else ""
            )
            if (
                name == "expect"
                or name.startswith("assert")
                or (name.startswith("wait_for") and name not in _WEAK_WAITS)
            ):
                found["check"] += 1
        if isinstance(sub, _COMPOUND):
            found[f"compound:{type(sub).__name__}"] += 1
        ident = sub.id if isinstance(sub, ast.Name) else sub.attr if isinstance(sub, ast.Attribute) else ""
        if ident in _BAILOUTS:
            found[f"bail:{ident}"] += 1
    return found


def _same_shape(before: ast.stmt, after: ast.stmt) -> bool:
    return ast.dump(before, include_attributes=False) == ast.dump(after, include_attributes=False)


def _function_rules(
    name: str, was: ast.FunctionDef | ast.AsyncFunctionDef, now: ast.FunctionDef | ast.AsyncFunctionDef
) -> list[Broken]:
    found: list[Broken] = []
    dump = lambda nodes: [ast.dump(n, include_attributes=False) for n in nodes]  # noqa: E731
    if dump(was.decorator_list) != dump(now.decorator_list):
        found.append(Broken("decorators", f"{name}: its decorators or marks changed"))
    signature = lambda f: (type(f).__name__, ast.dump(f.args), ast.dump(f.returns) if f.returns else "")  # noqa: E731
    if signature(was) != signature(now):
        found.append(
            Broken("signature", f"{name}: its parameters (the fixtures it requests) or its return type changed")
        )
    if len(was.body) != len(now.body):
        found.append(Broken("statement-count", f"{name}: it had {len(was.body)} statements and has {len(now.body)}"))
    else:
        differing = [i for i, (a, b) in enumerate(zip(was.body, now.body, strict=True)) if not _same_shape(a, b)]
        if len(differing) > MAX_CHANGED_STATEMENTS:
            found.append(
                Broken(
                    "too-many-statements",
                    f"{name}: {len(differing)} statements changed, at most {MAX_CHANGED_STATEMENTS} may",
                )
            )
        for i in differing:
            a, b = _count(was.body[i]), _count(now.body[i])
            added = sorted(k.removeprefix("compound:") for k in b if k.startswith("compound:") and b[k] > a[k])
            if added:
                found.append(Broken("compound-added", f"{name}: statement {i + 1} gained a {', '.join(added)}"))
    before, after = _count(was), _count(now)
    if after["assert"] < before["assert"]:
        found.append(
            Broken("assert-removed", f"{name}: it had {before['assert']} assert statements and has {after['assert']}")
        )
    if after["check"] < before["check"]:
        found.append(
            Broken(
                "check-dropped",
                f"{name}: it had {before['check']} checks (assert, expect, wait_for) and has {after['check']}",
            )
        )
    if after["constant"] > before["constant"]:
        found.append(Broken("assert-constant", f"{name}: an assert on a constant was added"))
    bails = sorted(k.removeprefix("bail:") for k in after if k.startswith("bail:") and after[k] > before[k])
    if bails:
        found.append(Broken("skip-added", f"{name}: it now uses {', '.join(bails)}"))
    return found


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
    if _outside(blank_old) != _outside(blank_new):
        found.append(
            Broken("outside-changed", "a statement of the file other than the repaired tests and the imports changed")
        )
    was_imports, now_imports = _bindings(_imports(old)), _bindings(_imports(new))
    if removed := sorted(t for _, t in was_imports - now_imports):
        found.append(Broken("import-removed", f"imports may only be added: {removed[0]}"))
    new_imports = now_imports - was_imports
    if any(n == "*" for n, _ in new_imports):
        found.append(Broken("import-star", "`from x import *` binds names nobody can see"))
    if any(t.startswith("from __future__") for _, t in new_imports):
        found.append(Broken("future-import", "a `__future__` import changes the whole file"))
    taken: set[str] = {n for n, _ in was_imports}
    for statement in old.body:
        if not isinstance(statement, ast.Import | ast.ImportFrom):
            taken |= _stored(statement)
    if shadows := sorted({n for n, _ in new_imports if n != "*" and n in taken}):
        found.append(
            Broken("import-shadows", f"a new import binds a name the file already binds: {', '.join(shadows)}")
        )
    for name, was, now in pairs:
        assert was is not None and now is not None
        found += _function_rules(name, was, now)
    return found


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
