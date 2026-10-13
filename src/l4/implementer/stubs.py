"""The red-phase stub guard (SPEC L4-IMP-002, "Admissible non-test changes" and "Guard") and zero-value variants.

`classify_red_changes` rebuilds one production file as the bytes of HEAD plus its admissible additions: the agent's
text is never patched in place. Admissible are new imports and `__all__` entries, new symbols (stub-ified: a body that
is only `raise NotImplementedError`, class fields without values), new methods (appended to the end of their class)
and guarded-parameter stubs. Any change to or removal of existing code is simply not applied, so it is "restored".
`enforce_red_scope` applies this to every changed non-test file of a red step.
`zero_value_variant` rewrites stub bodies (or every public function) to the zero value of their return annotation.
M1: implementer-tdd-loop 2.9 (other languages: a per-language pattern table).
"""

import ast
import shutil
import textwrap
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from l4.implementer.workbench import Workbench
from l4.security.protected import changed_paths, glob_match
from l4.specs.base import Task

ALLOWED_DECORATORS = frozenset({"dataclass", "staticmethod", "classmethod", "property", "abstractmethod", "overload"})
_PROPERTY_ACCESSORS = frozenset({"setter", "getter", "deleter"})
_ENUM_BASES = ("Enum", "Flag")  # members of an enum are its declaration, not behaviour
_GUARD_NAMES = frozenset({"None", "True", "False"})
LOCKFILES = ("uv.lock", "poetry.lock", "Pipfile.lock", "package-lock.json", "pnpm-lock.yaml", "yarn.lock")

_ZERO_EXPR = {
    "str": '""', "int": "0", "float": "0.0", "bool": "False", "list": "[]", "List": "[]", "dict": "{}", "Dict": "{}",
    "set": "set()", "Set": "set()", "frozenset": "frozenset()", "tuple": "()", "Tuple": "()", "bytes": 'b""',
}  # fmt: skip

_GUARD_NODES = (
    ast.BoolOp, ast.UnaryOp, ast.Compare, ast.Name, ast.Constant, ast.Load, ast.And, ast.Or, ast.Not, ast.Is, ast.IsNot,
    ast.Eq, ast.NotEq, ast.In, ast.NotIn, ast.Tuple, ast.List,
)  # fmt: skip
_Def = ast.FunctionDef | ast.AsyncFunctionDef


@dataclass(frozen=True)
class RedChanges:
    source: str  # HEAD plus the admissible additions
    stubs: tuple[str, ...]  # qualified names of the symbols the rebuilt file stubs (new symbols and guarded ones)
    restored: tuple[str, ...]  # one note per region of the agent's text that was not applied


def _name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    return node.attr if isinstance(node, ast.Attribute) else None


def _decorator_ok(node: ast.expr) -> bool:
    if isinstance(node, ast.Call):
        plain = all(isinstance(a, ast.Constant) for a in node.args) and all(
            isinstance(k.value, ast.Constant) for k in node.keywords
        )
        return plain and _decorator_ok(node.func)
    if isinstance(node, ast.Attribute) and node.attr in _PROPERTY_ACCESSORS:
        return isinstance(node.value, ast.Name)  # @value.setter
    return _name(node) in ALLOWED_DECORATORS


def _is_not_implemented(stmt: ast.stmt) -> bool:
    if not isinstance(stmt, ast.Raise) or stmt.cause is not None or stmt.exc is None:
        return False
    exc = stmt.exc
    if isinstance(exc, ast.Call):
        if exc.keywords or not all(isinstance(a, ast.Constant) for a in exc.args):
            return False
        exc = exc.func
    return isinstance(exc, ast.Name) and exc.id == "NotImplementedError"


def _docstring(body: Sequence[ast.stmt]) -> list[ast.stmt]:
    first = body[0] if body else None
    value = first.value if isinstance(first, ast.Expr) else None
    return [first] if first is not None and isinstance(value, ast.Constant) and isinstance(value.value, str) else []


def _is_stub_body(body: Sequence[ast.stmt]) -> bool:
    rest = body[len(_docstring(body)) :]
    return len(rest) == 1 and _is_not_implemented(rest[0])


def _ends_with_stub(body: Sequence[ast.stmt]) -> bool:
    """A partial stub: guards (an earlier task's behaviour) and then a final bare `raise NotImplementedError`."""
    return len(body) > len(_docstring(body)) + 1 and _is_not_implemented(body[-1])


def _raise_stub() -> ast.stmt:
    return ast.Raise(exc=ast.Name("NotImplementedError", ast.Load()), cause=None)


def _uses(node: ast.AST | None, names: frozenset[str]) -> bool:
    return node is not None and any(isinstance(n, ast.Name) and n.id in names for n in ast.walk(node))


def _without_dropped(fn: _Def, dropped: frozenset[str]) -> None:
    """A default or an annotation is evaluated when the module is imported: one that reads a module-level value the
    rebuild dropped would raise NameError there, so the stub keeps `None` (a guarded stub keeps the semantics)."""
    args = fn.args
    args.defaults = [ast.Constant(None) if _uses(d, dropped) else d for d in args.defaults]
    args.kw_defaults = [ast.Constant(None) if _uses(d, dropped) else d for d in args.kw_defaults]
    for arg in _params(args):
        if _uses(arg.annotation, dropped):
            arg.annotation = None
    if _uses(fn.returns, dropped):
        fn.returns = None


def _stub_function(fn: _Def, dropped: frozenset[str] = frozenset()) -> _Def:
    out = ast.parse(ast.unparse(fn)).body[0]
    assert isinstance(out, _Def)
    if dropped:
        _without_dropped(out, dropped)
    out.decorator_list = [d for d in out.decorator_list if _decorator_ok(d)]
    if not _is_stub_body(out.body):
        out.body = [*_docstring(out.body), _raise_stub()]
    return out


def _stub_class(cls: ast.ClassDef, dropped: frozenset[str] = frozenset()) -> ast.ClassDef:
    out = ast.parse(ast.unparse(cls)).body[0]
    assert isinstance(out, ast.ClassDef)
    out.decorator_list = [d for d in out.decorator_list if _decorator_ok(d)]
    out.keywords = [k for k in out.keywords if isinstance(k.value, ast.Name | ast.Attribute | ast.Constant)]
    enum = any((_name(b) or "").endswith(_ENUM_BASES) for b in out.bases)
    body: list[ast.stmt] = _docstring(out.body)
    for stmt in out.body[len(body) :]:
        if isinstance(stmt, _Def):
            body.append(_stub_function(stmt, dropped))
        elif isinstance(stmt, ast.ClassDef):
            body.append(_stub_class(stmt, dropped))
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            body.append(ast.AnnAssign(stmt.target, stmt.annotation, None, 1))
        elif isinstance(stmt, ast.Pass | ast.Expr) and not (
            isinstance(stmt, ast.Expr) and not isinstance(stmt.value, ast.Constant)
        ):
            body.append(stmt)  # pass, `...`, a docstring-like constant
        elif enum and isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Constant):
            body.append(stmt)
    out.body = body or [ast.Pass()]
    return out


def _stub_text(node: _Def | ast.ClassDef, source: str, dropped: frozenset[str] = frozenset()) -> tuple[str, bool]:
    """(text of the stub-ified node, whether the agent's node already was one). A pure node keeps the agent's own
    formatting, so that a project's formatter has nothing to complain about."""
    stub = _stub_class(node, dropped) if isinstance(node, ast.ClassDef) else _stub_function(node, dropped)
    if ast.dump(stub) == ast.dump(node):
        return _segment(source.splitlines(keepends=True), node, 0), True
    return ast.unparse(stub), False


def _span(node: ast.stmt) -> tuple[int, int]:
    """[start, end) line indexes of a statement, decorators included."""
    firsts = [node.lineno, *(d.lineno for d in getattr(node, "decorator_list", []))]
    assert node.end_lineno is not None
    return min(firsts) - 1, node.end_lineno


def _segment(lines: Sequence[str], node: ast.stmt, to_col: int) -> str:
    """The statement's own lines, moved from its column to `to_col` (untouched when they already agree)."""
    start, end = _span(node)
    chunk = lines[start:end]
    col = len(chunk[0]) - len(chunk[0].lstrip(" \t"))
    if col == to_col:
        return "".join(chunk)
    text = "".join(line[col:] if not line[:col].strip() else line for line in chunk)
    return textwrap.indent(text, " " * to_col, lambda line: bool(line.strip()))


def _blank_line_between(lines: Sequence[str], first: ast.stmt, second: ast.stmt) -> bool:
    """Whether a blank line separates two statements of `lines` (`first` ends before `second` starts)."""
    assert first.end_lineno is not None
    return any(not line.strip() for line in lines[first.end_lineno : _span(second)[0]])


def _d(node: ast.AST | None) -> str:
    return ast.dump(node) if node is not None else ""


def _params(args: ast.arguments) -> list[ast.arg]:
    named = [*args.posonlyargs, *args.args, *args.kwonlyargs]
    return [*named, *([args.vararg] if args.vararg else []), *([args.kwarg] if args.kwarg else [])]


def _guard_ok(stmt: ast.stmt, names: set[str]) -> bool:
    """`if <expression over the parameter names and None/True/False>: raise NotImplementedError`."""
    if not isinstance(stmt, ast.If) or stmt.orelse or len(stmt.body) != 1 or not _is_not_implemented(stmt.body[0]):
        return False
    for node in ast.walk(stmt.test):
        if not isinstance(node, _GUARD_NODES):
            return False
        if isinstance(node, ast.Name) and node.id not in names | _GUARD_NAMES:
            return False
        if isinstance(node, ast.Constant) and not (node.value is None or isinstance(node.value, bool)):
            return False
    return True


def _same(a: Sequence[ast.AST | None], b: Sequence[ast.AST | None]) -> bool:
    return [_d(x) for x in a] == [_d(x) for x in b]


def _args_extended(head: ast.arguments, new: ast.arguments) -> bool:
    """`new` is `head` plus trailing parameters that all have defaults (and no other change)."""
    if not (_same(head.posonlyargs, new.posonlyargs) and _same(head.args, new.args[: len(head.args)])):
        return False
    extra = len(new.args) - len(head.args)
    if extra and head.vararg:
        return False  # the new parameter would capture what `*args` took
    if not _same(head.defaults, new.defaults[: len(head.defaults)]) or len(new.defaults) != len(head.defaults) + extra:
        return False
    kept = len(head.kwonlyargs)
    return (
        _same(head.kwonlyargs, new.kwonlyargs[:kept])
        and _same(head.kw_defaults, new.kw_defaults[:kept])
        and all(d is not None for d in new.kw_defaults[kept:])
        and _d(head.vararg) == _d(new.vararg)
        and _d(head.kwarg) == _d(new.kwarg)
    )


def _is_guarded_stub(head: _Def, new: _Def) -> bool:
    """New trailing defaulted parameters, a guard as the first statement, everything else AST-identical to HEAD."""
    if type(head) is not type(new) or head.name != new.name or _d(head.returns) != _d(new.returns):
        return False
    if not _same(head.decorator_list, new.decorator_list) or not _args_extended(head.args, new.args):
        return False
    doc = len(_docstring(head.body))
    if len(new.body) <= doc or not _same(head.body[:doc], new.body[:doc]):
        return False
    if not _guard_ok(new.body[doc], {a.arg for a in _params(new.args)}):
        return False
    return _same(head.body[doc:], new.body[doc + 1 :])


def _all_entries(node: ast.stmt) -> list[str] | None:
    value = node.value if isinstance(node, ast.Assign | ast.AnnAssign) else None
    if not isinstance(value, ast.List | ast.Tuple):
        return None
    names = [e.value for e in value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    return names if len(names) == len(value.elts) else None


def _assigns_all(node: ast.stmt) -> bool:
    targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
    return any(isinstance(t, ast.Name) and t.id == "__all__" for t in targets)


def _import_or_all(node: ast.stmt) -> bool:
    return isinstance(node, ast.Import | ast.ImportFrom) or _assigns_all(node)


def _import_kept(before: ast.stmt, body: Sequence[ast.stmt]) -> bool:
    """Whether an import of HEAD is still in `body`: the same statement, or the same `from` import with more names."""
    return any(
        _d(s) == _d(before)
        or (
            isinstance(s, ast.ImportFrom)
            and isinstance(before, ast.ImportFrom)
            and (s.module, s.level) == (before.module, before.level)
            and {(a.name, a.asname) for a in before.names} <= {(a.name, a.asname) for a in s.names}
        )
        for s in body
    )


def _type_checking_imports(node: ast.stmt) -> bool:
    """`if TYPE_CHECKING:` (or `if typing.TYPE_CHECKING:`) with no else branch and nothing but imports in its body: an
    import of names for annotations only (SPEC L4-IMP-002 (iii)), the usual way to name a type whose module would be a
    circular import."""
    if not isinstance(node, ast.If) or node.orelse or not node.body:
        return False
    test = node.test
    flag = isinstance(test, ast.Name) and test.id == "TYPE_CHECKING"
    flag = flag or (
        isinstance(test, ast.Attribute)
        and test.attr == "TYPE_CHECKING"
        and isinstance(test.value, ast.Name)
        and test.value.id == "typing"
    )
    return flag and all(isinstance(s, ast.Import | ast.ImportFrom) for s in node.body)


def _bound(node: ast.stmt) -> list[str]:
    """Names a plain module-level assignment binds."""
    if isinstance(node, ast.Assign):
        targets = node.targets
    elif isinstance(node, ast.AnnAssign | ast.AugAssign):
        targets = [node.target]
    else:
        return []
    return [n.id for t in targets for n in ast.walk(t) if isinstance(n, ast.Name)]


def _kind(node: ast.stmt) -> tuple[str, str] | None:
    if isinstance(node, _Def):
        return "def", node.name
    return ("class", node.name) if isinstance(node, ast.ClassDef) else None


def _header(cls: ast.ClassDef) -> tuple[list[str], list[str], list[str]]:
    return [_d(b) for b in cls.bases], [_d(d) for d in cls.decorator_list], [_d(k) for k in cls.keywords]


class _Rebuild:
    """The edits that turn HEAD into HEAD plus the admissible additions, as (start, end, text) line replacements."""

    def __init__(self, head_src: str, new_src: str) -> None:
        self.head_lines = head_src.splitlines(keepends=True)
        self.new_lines = new_src.splitlines(keepends=True)
        self.new_src = new_src
        self.edits: list[tuple[int, int, str]] = []
        self.appended: list[str] = []
        self.stubs: list[str] = []
        self.restored: list[str] = []
        self.dropped: frozenset[str] = frozenset()  # module-level values of the agent's text that are not applied
        self.type_blocks: list[str] = []  # new `if TYPE_CHECKING:` import blocks, placed after the imports
        self.extended: set[str] = set()  # dumps of HEAD's type-checking blocks the agent's version extends
        # A new module (no HEAD text) keeps the agent's module docstring and the blank lines between its import
        # sections, so a lint-clean file stays lint-clean (kiro-e2e H1 finding 3: joined sections failed ruff I001).
        self.new_module = not head_src.strip()
        self.module_doc = ""
        self.last_import: ast.stmt | None = None

    def replace(self, head: ast.stmt, new: ast.stmt) -> None:
        start, end = _span(head)
        self.edits.append((start, end, _segment(self.new_lines, new, head.col_offset)))

    def new_symbol(self, node: _Def | ast.ClassDef, qual: str, indent: int) -> str:
        text, pure = _stub_text(node, self.new_src, self.dropped)
        self.stubs.append(qual)
        if not pure:
            self.restored.append(f"the implementation of {qual} was replaced by a stub")
        return textwrap.indent(text, " " * indent) if indent else text

    def members(self, head: ast.ClassDef, new: ast.ClassDef) -> None:
        qual = head.name
        if _header(head) != _header(new):
            self.restored.append(f"the header of class {qual} was changed")
        old = {k: n for n in head.body if (k := _kind(n))}
        head_dumps = {_d(n) for n in head.body}
        seen: set[tuple[str, str]] = set()
        added: list[str] = []
        for node in new.body:
            key = _kind(node)
            if key is None:
                if _d(node) not in head_dumps:
                    self.restored.append(f"a statement of class {qual} (line {node.lineno}) was not applied")
                continue
            seen.add(key)
            before = old.get(key)
            if before is None and isinstance(node, _Def):
                added.append(self.new_symbol(node, f"{qual}.{node.name}", head.body[0].col_offset))
            elif before is None:
                self.restored.append(f"the nested class {qual}.{key[1]} was not applied")
            elif _d(before) == _d(node):
                continue
            elif isinstance(before, _Def) and isinstance(node, _Def) and _is_guarded_stub(before, node):
                self.replace(before, node)
                self.stubs.append(f"{qual}.{node.name} (guard)")
            else:
                self.restored.append(f"{qual}.{key[1]} was changed")
        self.restored += [f"{qual}.{k[1]} was removed" for k in old if k not in seen]
        if not added:
            return
        if head.body[0].lineno == head.lineno:
            self.restored.append(f"methods could not be added to the one-line class {qual}")
        else:
            assert head.end_lineno is not None
            self.edits.append((head.end_lineno, head.end_lineno, "".join("\n" + t.rstrip("\n") + "\n" for t in added)))

    def rebuild(self, head: ast.Module, new: ast.Module) -> RedChanges:
        old = {k: n for n in head.body if (k := _kind(n))}
        head_dumps = {_d(n) for n in head.body}
        new_dumps = {_d(n) for n in new.body}
        seen: set[tuple[str, str]] = set()
        imports: list[str] = []
        futures: list[str] = []
        self.dropped = frozenset(
            name for node in new.body if _kind(node) is None and _d(node) not in head_dumps for name in _bound(node)
        )
        for node in new.body:
            key = _kind(node)
            if key is not None:
                seen.add(key)
                self._definition(old.get(key), node)
            elif isinstance(node, ast.Import | ast.ImportFrom):
                if _d(node) not in head_dumps:
                    self._import(head, node, imports, futures)
            elif _assigns_all(node):
                self._dunder_all(head, node)
            elif _type_checking_imports(node):
                if _d(node) not in head_dumps:
                    self._type_block(head, node)
            elif self.new_module and node is new.body[0] and _docstring([node]):
                self.module_doc = _segment(self.new_lines, node, 0)
            elif _d(node) not in head_dumps and not _docstring([node]):
                self.restored.append(f"the statement at line {node.lineno} was not applied")
        for node in head.body:
            key = _kind(node)
            if key is not None and key not in seen:
                self.restored.append(f"{key[1]} was removed")
            elif (
                key is None and _d(node) not in new_dumps and not _import_or_all(node) and _d(node) not in self.extended
            ):
                self.restored.append(f"the statement at line {node.lineno} was changed or removed")
        return self._apply(head, imports, futures)

    def _definition(self, before: ast.stmt | None, node: ast.stmt) -> None:
        assert isinstance(node, _Def | ast.ClassDef)
        if before is None:
            self.appended.append(self.new_symbol(node, node.name, 0))
        elif _d(before) == _d(node):
            return
        elif isinstance(before, ast.ClassDef) and isinstance(node, ast.ClassDef):
            self.members(before, node)
        elif isinstance(before, _Def) and isinstance(node, _Def) and _is_guarded_stub(before, node):
            self.replace(before, node)
            self.stubs.append(f"{node.name} (guard)")
        else:
            self.restored.append(f"{node.name} was changed")

    def _import(
        self, head: ast.Module, node: ast.Import | ast.ImportFrom, imports: list[str], futures: list[str]
    ) -> None:
        if isinstance(node, ast.ImportFrom):
            wanted = {a.name for a in node.names}
            for before in head.body:
                if (
                    isinstance(before, ast.ImportFrom)
                    and (before.module, before.level) == (node.module, node.level)
                    and {a.name for a in before.names} <= wanted
                    and not any(a.asname for a in before.names)
                ):
                    self.replace(before, node)  # the same import with more names
                    return
        text = _segment(self.new_lines, node, 0)
        if self.new_module:
            if self.last_import is not None and _blank_line_between(self.new_lines, self.last_import, node):
                text = "\n" + text  # the agent's section break (isort groups) is kept
            self.last_import = node
        (futures if isinstance(node, ast.ImportFrom) and node.module == "__future__" else imports).append(text)

    def _type_block(self, head: ast.Module, node: ast.If) -> None:
        """A new type-checking import block is added after the imports; one that extends HEAD's block (every import of
        HEAD's block is still in it) replaces that block; anything else would remove an import and is not applied."""
        before = next((n for n in head.body if _type_checking_imports(n)), None)
        if before is None:
            self.type_blocks.append(_segment(self.new_lines, node, 0))
            return
        assert isinstance(before, ast.If)
        if all(_import_kept(s, node.body) for s in before.body):
            self.replace(before, node)
            self.extended.add(_d(before))
        else:
            self.restored.append(f"the type-checking import block at line {node.lineno} was not applied")

    def _dunder_all(self, head: ast.Module, node: ast.stmt) -> None:
        entries = _all_entries(node)
        before = next((n for n in head.body if _assigns_all(n)), None)
        if entries is None:
            self.restored.append("__all__ is not a plain list of names; it was not applied")
        elif before is None:
            self.appended.append(_segment(self.new_lines, node, 0))
        elif _d(before) != _d(node):
            if set(_all_entries(before) or ()) <= set(entries):
                self.replace(before, node)
            else:
                self.restored.append("entries of __all__ were removed")

    def _apply(self, head: ast.Module, imports: list[str], futures: list[str]) -> RedChanges:
        lines = list(self.head_lines)
        docstring_end = (head.body[0].end_lineno or 0) if _docstring(head.body) else 0
        last_import = max(
            (n.end_lineno or 0 for n in head.body if isinstance(n, ast.Import | ast.ImportFrom)), default=0
        )
        after_imports = last_import or docstring_end
        if futures and after_imports == docstring_end:
            imports = [*futures, *imports]
        elif futures:
            self.edits.append((docstring_end, docstring_end, "".join(futures)))
        if imports or self.type_blocks:
            blocks = "".join("\n" + b for b in self.type_blocks)
            text = "".join(imports) + blocks
            self.edits.append((after_imports, after_imports, f"{self.module_doc}\n{text}" if self.module_doc else text))
        elif self.module_doc:
            self.edits.append((0, 0, self.module_doc))
        for start, end, text in sorted(self.edits, key=lambda e: (e[0], e[1]), reverse=True):
            lines[start:end] = [text]
        source = "".join(lines)
        if self.appended:
            added = "\n\n".join(t.strip("\n") + "\n" for t in self.appended)
            source = f"{source.rstrip(chr(10))}\n\n\n{added}" if source.strip() else added
        return RedChanges(source, tuple(self.stubs), tuple(self.restored))


def classify_red_changes(head_src: str, new_src: str) -> RedChanges:
    """HEAD's text plus whatever of `new_src` is admissible in red (`head_src` is "" for a new module)."""
    try:
        new_tree = ast.parse(new_src)
    except SyntaxError:
        return RedChanges(head_src, (), ("the file does not parse; it was restored",))
    try:
        head_tree = ast.parse(head_src)
    except SyntaxError:
        return RedChanges(head_src, (), ("the file did not parse at the step base; it was restored",))
    return _Rebuild(head_src, new_src).rebuild(head_tree, new_tree)


def has_stub(source: str) -> bool:
    """Whether any function of `source` has a not-implemented body, a not-implemented guard or a final
    `raise NotImplementedError` after other statements (a partial stub: its not-implemented path is still a stub)."""
    return bool(_stub_sites(ast.parse(source)))


def _stub_sites(tree: ast.Module) -> list[ast.stmt]:
    """The `raise NotImplementedError` statements that are a whole function body, a guard body or the last statement."""
    found: list[ast.stmt] = []
    for fn in (n for n in ast.walk(tree) if isinstance(n, _Def)):
        doc = len(_docstring(fn.body))
        if _is_stub_body(fn.body):
            found.append(fn.body[-1])
        elif (
            len(fn.body) > doc
            and isinstance(fn.body[doc], ast.If)
            and _guard_ok(fn.body[doc], {a.arg for a in _params(fn.args)})
        ):
            found.append(fn.body[doc].body[0])  # type: ignore[attr-defined]
        if _ends_with_stub(fn.body):
            found.append(fn.body[-1])
    return found


def _zero_expr(annotation: ast.expr | None) -> str | None:
    """Source of the zero value of a return annotation; None for `-> None` (nothing to return)."""
    if annotation is None:
        return "None"
    if isinstance(annotation, ast.Constant):
        if annotation.value is None:
            return None
        if isinstance(annotation.value, str):
            try:
                return _zero_expr(ast.parse(annotation.value, mode="eval").body)
            except SyntaxError:
                return "None"
    node = annotation.value if isinstance(annotation, ast.Subscript) else annotation
    return _ZERO_EXPR.get(_name(node) or "", "None")


def _zero_statement(fn: _Def) -> ast.stmt:
    expr = _zero_expr(fn.returns)
    return ast.Pass() if expr is None else ast.parse(f"return {expr}").body[0]


class _Zero(ast.NodeTransformer):
    """Stub bodies (or, with `public`, every public function and method) answer the zero value of their return type."""

    def __init__(self, public: bool) -> None:
        self.public = public

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.ClassDef:
        node.body = [self._member(n) for n in node.body]
        return node

    def _member(self, node: ast.stmt) -> ast.stmt:
        if isinstance(node, ast.ClassDef):
            return self.visit_ClassDef(node)
        return self._function(node) if isinstance(node, _Def) else node

    def _function(self, fn: _Def) -> _Def:
        doc = len(_docstring(fn.body))
        if self.public:
            if not fn.name.startswith("_"):
                fn.body = [*fn.body[:doc], _zero_statement(fn)]
        elif _is_stub_body(fn.body):
            fn.body = [*fn.body[:doc], _zero_statement(fn)]
        elif (
            len(fn.body) > doc
            and isinstance(guard := fn.body[doc], ast.If)
            and _guard_ok(guard, {a.arg for a in _params(fn.args)})
        ):
            guard.body = [_zero_statement(fn)]  # the guard body gets the same treatment
        if not self.public and _ends_with_stub(fn.body):
            fn.body[-1] = _zero_statement(fn)  # a partial stub: its guards stay, its final raise answers the zero value
        return fn

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        return self._function(node)  # type: ignore[return-value]

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]


def zero_value_variant(source: str, *, public: bool = False) -> str:
    """`source` with each red stub (`public`: each public function and method) answering the zero value of its
    return annotation: `str` "", `int` 0, `float` 0.0, `bool` False, `list` [], `dict` {}, `set` set(), `tuple` (),
    `bytes` b""; unannotated or unknown None; `-> None` nothing. A partial stub (guards, then a final bare
    `raise NotImplementedError`) keeps its guards and answers the zero value in place of that raise, so a test of the
    unwritten path fails by assertion, not by error (L4-IMP-002 check 5). Nested functions are left alone."""
    tree = ast.parse(source)
    tree.body = [_Zero(public)._member(n) for n in tree.body]
    return ast.unparse(ast.fix_missing_locations(tree)) + "\n"


@dataclass(frozen=True)
class RedScope:
    stub_files: tuple[str, ...]  # production files that contain stubs after the rebuild (the zero-value scope)
    stubs: tuple[str, ...]
    restored: tuple[str, ...]  # "<path>: <region>"


def _is_inside(root: Path, path: Path) -> bool:
    try:
        return not path.is_symlink() and path.resolve().is_relative_to(root.resolve())
    except OSError:
        return False


def _exempt(wb: Workbench, path: str) -> bool:
    tdd = wb.cfg.tdd
    globs = (*tdd.test_globs, *tdd.test_support_globs, *tdd.runner_config_files)
    exempt = any(glob_match(g, path) or glob_match(f"**/{g}", path) for g in globs)
    return (
        exempt or path.rsplit("/", 1)[-1] in LOCKFILES or path == wb.ledger_rel or wb.protected.match(path) is not None
    )


def restore_to_base(wb: Workbench, base: str, path: str, existed: bool | None = None) -> None:
    """Put `path` back to its content at `base`; a file that did not exist there is deleted."""
    if existed is None:
        existed = wb.git.run("cat-file", "-e", f"{base}:{path}", check=False).returncode == 0
    target = wb.worktree / path
    if existed:
        if target.is_symlink():
            target.unlink()
        wb.git.run("checkout", base, "--", f":(literal){path}")
    else:
        target.unlink(missing_ok=True)
        wb.git.run("rm", "--quiet", "--cached", "--ignore-unmatch", "--", f":(literal){path}")


def enforce_red_scope(wb: Workbench, task: Task, base: str) -> RedScope:
    """Rebuild every changed non-test file of the red step (SPEC "Guard"). Python files become HEAD plus their
    admissible additions; other production files go back to HEAD (new ones are deleted). Records a
    `guard.violation{phase: red}` per region that was not applied and one `stub.purity` for the step."""
    stub_files: list[str] = []
    stubs: list[str] = []
    restored: list[str] = []

    def violation(path: str, note: str, action: str) -> None:
        restored.append(f"{path}: {note}")
        wb.emit("guard.violation", phase="red", path=path, rule="red scope", action=action, region=note)

    for path, existed in sorted(changed_paths(wb.git, base, excludes=wb.excludes).items()):
        if _exempt(wb, path):
            continue
        target = wb.worktree / path
        if not path.endswith(".py"):
            restore_to_base(wb, base, path, existed)
            violation(
                path,
                "a production file other than Python source was not part of red",
                "restored" if existed else "removed",
            )
            continue
        if not target.exists() and not target.is_symlink():
            restore_to_base(wb, base, path, existed)  # deleted by the agent
            violation(path, "the file was deleted", "restored")
            continue
        try:
            if not _is_inside(wb.worktree, target):
                raise ValueError("not a regular file inside the worktree")
            new_src = target.read_bytes().decode("utf-8")
            head_src = wb.git.run_bytes("show", f"{base}:{path}").decode("utf-8") if existed else ""
        except (ValueError, UnicodeDecodeError, OSError):
            restore_to_base(wb, base, path, existed)
            violation(path, "the file is not readable Python source", "restored" if existed else "removed")
            continue
        change = classify_red_changes(head_src, new_src)
        if change.source != new_src:
            target.write_bytes(change.source.encode("utf-8"))
        for note in change.restored:
            violation(path, note, "restored")
        stubs += [f"{path}:{name}" for name in change.stubs]
        if has_stub(change.source):
            stub_files.append(path)
    wb.emit("stub.purity", task=task.key, stubs=stubs, restored=len(restored))
    return RedScope(tuple(stub_files), tuple(stubs), tuple(restored))


_NOISE = ("__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache")


class ProductionGuard:
    """The production files as `enforce_red_scope` left them. Gates run agent-written test code with a writable
    worktree, so after every gate (and before every commit) the production state is recomputed: any added, changed
    or deleted non-exempt path is put back to the guarded state and reported (`gate-mutated-production`)."""

    def __init__(self, wb: Workbench, base: str) -> None:
        self.wb = wb
        self.base = base
        self.guarded: dict[str, bytes] = {}  # path -> the content the red step is allowed to commit
        for path in self._production():
            data = self._read(path)
            if data is not None:
                self.guarded[path] = data

    def _production(self) -> dict[str, bool]:
        wb = self.wb
        return {
            path: existed
            for path, existed in changed_paths(wb.git, self.base, excludes=wb.excludes).items()
            if not _exempt(wb, path)
            and not any(part in _NOISE for part in path.split("/"))
            and not path.endswith(".pyc")
        }

    def _read(self, path: str) -> bytes | None:
        target = self.wb.worktree / path
        try:
            if not _is_inside(self.wb.worktree, target) or not target.is_file():
                return None
            return target.read_bytes()
        except OSError:
            return None

    def release(self, paths: Sequence[str]) -> None:
        """The harness itself put these paths back to `base` (an unused stub): they are guarded as unchanged."""
        for path in paths:
            self.guarded.pop(path, None)

    def check(self, where: str) -> list[str]:
        """Restore what a gate run changed and return one note per path (empty when nothing moved)."""
        wb = self.wb
        now = self._production()
        notes: list[str] = []
        for path in sorted(set(now) | set(self.guarded)):
            expected = self.guarded.get(path)
            if expected is None:
                if path not in now:
                    continue  # unchanged, as guarded
                restore_to_base(wb, self.base, path, now[path])
                notes.append(f"{path}: added or changed by a gate run ({where})")
                wb.emit(
                    "guard.violation",
                    phase="red",
                    path=path,
                    rule="gate-mutated-production",
                    action="restored",
                    where=where,
                )
                continue
            if self._read(path) == expected:
                continue
            target = wb.worktree / path
            if target.is_symlink() or target.is_file():
                target.unlink()
            elif target.is_dir():
                shutil.rmtree(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(expected)
            notes.append(f"{path}: changed or deleted by a gate run ({where})")
            wb.emit(
                "guard.violation",
                phase="red",
                path=path,
                rule="gate-mutated-production",
                action="restored",
                where=where,
            )
        return notes
