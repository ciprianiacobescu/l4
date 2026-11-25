"""Rule (e) of the skip rule: where the unit may change the file (skipped-test-hold D1 (e), L4-VER-092).

(b) compares the skip constructs of a test file and (d) the dependency closure of what makes a test skip. Both list
what decides a skip (a blacklist), and a review found, round after round, one more in-file way to change WHY an already
skipped test skips that the lists miss: a flag a string condition names, an attribute of `self`, a helper method chain,
a fixture reached through `usefixtures` or `getfixturevalue`, a module-level mutation, a binding made by a `for` or a
`with`, a star import. (e) is the whitelist beside them: it does not ask what the unit changed, it asks WHERE.

For a skipped old test T in a changed test file, (e) holds only when EVERY changed line of the file, a line of the base
that the head no longer has and a line of the head that the base does not have, is one of:

1. a blank line or a comment-only line (read with `tokenize`: a line inside a string, a docstring too, is not one);
2. a line inside a collected test: a function or method that a runner collects (`scan.collected_in`: never a fixture,
   never `setUp`, `setup_method` or a helper), existing at both sides or a whole new one at the head, its decorators and
   signature included, except that for T itself the decorators, the signature (its parameters are fixtures) and the
   statements of the body up to and including the last one that can skip (`SkipFacts.skip_relevant`, the prefix of
   the closure) are never a place for a change: a test that is not T cannot skip T by its decorators;
3. a whole `import M`, `import M as N` or `from M import a, b` statement of the module that binds only names the base
   module neither binds nor loads (not `*`, not `__future__`, not a name a string condition or a builtin gives).

Nothing else of the module or of a class may be added, removed or changed: no statement, no docstring, no decorator of a
class, no other method.

How the changed lines are located. A diff of the lines would have to guess which line of the base became which line of
the head, and with repeated lines (`    assert x`, a decorator, 600 times) it guesses slowly and can guess wrong. The
structure says it exactly: the statements of the module and of its classes that are not collected tests, and the
imports the base had, pair up in order, and each pair must be the same tree (`ast.dump`: a changed docstring, a
reformatted expression and a moved statement are all a difference) and the same lines of text (comment and blank lines
left out, a line inside a string kept). A collected test is the part that is free, except T: its decorators,
signature and prefix are the same tree and the same text, and T is at the same place among the statements (a statement
moved above or below it changes what its decorators see). What is left is a line that no kept statement holds and that
is not a comment or a blank line: a line of a collected test, or of a whole new import (rule 3). Deleting the `def`
line of a test makes its body part of the function above it, and an added `def` in the middle of a helper splits it:
both change a kept statement's tree, with no changed line outside a test, and a diff of lines alone would pass them.

Anything that is not clear is False: a source that does not parse or does not tokenize, a name defined twice, a test
that is not collected at both sides, a changed coding line.

Not covered, and said so in the hold's question, the Evidence line, the runbook and the SPEC with the words of
`RESIDUALS`."""

import ast
import builtins
import copy
import io
import re
import tokenize
from collections import Counter

from l4.verifier import scan
from l4.verifier.skipdeps import SkipFacts

RESIDUALS = (
    "production code the unit changed, a module outside the tests tree that the test imports, run-time state that "
    "another test sets, and dynamic forms (`exec`, `getattr`, `importlib`, `globals()`)"
)  # what the rule does not tell apart: the hold's question, the Evidence line, the runbook and the SPEC say it so
_FUNCTIONS = ast.FunctionDef | ast.AsyncFunctionDef
_NEWLINES = re.compile(r"\r\n|\r")
_COOKIE = re.compile(r"^[ \t\f]*#.*?coding[:=][ \t]*([-\w.]+)")
_WORD = re.compile(r"[A-Za-z_]\w*")
_CONDITIONAL = frozenset({"skipif", "xfail", "skipIf", "skipUnless"})  # markers whose first argument may be a string
_GIVEN = frozenset({"os", "sys", "platform", "config"}) | frozenset(dir(builtins))  # names a condition has unbound
_NOT_CODE = frozenset(
    {tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER}
)
_PROBLEMS = (tokenize.TokenError, SyntaxError, ValueError, RecursionError, MemoryError)


def normalized(text: str) -> str:
    """The text with one kind of line ending, as the tokenizer reads it, so that a line number of the tree is the index
    of `text.split("\\n")`; `str.splitlines` also breaks at a form feed or a line separator, which Python does not."""
    return _NEWLINES.sub("\n", text)


def _span(function: _FUNCTIONS) -> tuple[int, int]:
    """First line (the first decorator) and last line of a def."""
    return min([function.lineno, *(d.lineno for d in function.decorator_list)]), function.end_lineno or function.lineno


def _code_lines(text: str) -> set[int]:
    """The lines that hold a token other than a comment or a line break: a line of a string that spans lines counts."""
    code: set[int] = set()
    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        if token.type not in _NOT_CODE:
            code.update(range(token.start[0], token.end[0] + 1))
    return code


def _bound(statement: ast.stmt) -> set[str] | None:
    """The module names an import statement binds; None for `from M import *` and `from __future__ import ...`."""
    if isinstance(statement, ast.Import):
        return {a.asname or a.name.split(".")[0] for a in statement.names}
    assert isinstance(statement, ast.ImportFrom)
    if statement.module == "__future__" or any(a.name == "*" for a in statement.names):
        return None
    return {a.asname or a.name for a in statement.names}


class _Side:
    """One source: its lines, the lines that hold code, the lines of its collected tests, and the structure that the
    other side is compared with."""

    def __init__(self, facts: SkipFacts, text: str) -> None:
        self.facts, self.ok = facts, False
        self.items: list[object] = []
        self.positions: dict[str, tuple[int, int]] = {}
        if not facts.ok:
            return
        try:
            self.lines = text.split("\n")
            self.code = _code_lines(text)
        except _PROBLEMS:
            return
        self.tree = facts.tree
        self.imports = [n for n in self.tree.body if isinstance(n, ast.Import | ast.ImportFrom)]
        self.cookie = tuple(m.group(1) if (m := _COOKIE.match(line)) else None for line in self.lines[:2])
        self.ok = True

    def trivial(self, number: int) -> bool:
        """A blank line or a comment-only line (rule 1)."""
        if number in self.code or not 1 <= number <= len(self.lines):
            return False
        line = self.lines[number - 1]
        return not line.strip() or line.lstrip().startswith("#")

    def text(self, first: int, last: int) -> tuple[str, ...]:
        """The lines `first` to `last` that are not a comment or a blank line, as written."""
        return tuple(self.lines[n - 1] for n in range(first, last + 1) if not self.trivial(n))

    def _item(self, node: ast.stmt) -> tuple[str, tuple[str, ...]]:
        """A statement as a tree and as the lines it is written in (a def or class from its first decorator)."""
        first = min([node.lineno, *(d.lineno for d in getattr(node, "decorator_list", ()))])
        return ast.dump(node), self.text(first, node.end_lineno or node.lineno)

    def build(self, leave_out: frozenset[int]) -> None:
        """The structure: every statement of the module and of its classes as a tree and its lines, a collected test
        left out (T is compared on its own, by `fingerprint`, and its `positions` among the others) and so are the
        imports whose ids are `leave_out` (the head's whole added imports)."""
        collected = self.facts.collected
        items: list[object] = []
        for node in self.tree.body:
            if id(node) in leave_out:
                continue
            if isinstance(node, _FUNCTIONS) and node.name in collected:
                self.positions[node.name] = (len(items), -1)
            elif isinstance(node, ast.ClassDef):
                members: list[object] = []
                for member in node.body:
                    q = f"{node.name}.{member.name}" if isinstance(member, _FUNCTIONS) else ""
                    if q in collected:
                        self.positions[q] = (len(items), len(members))
                    else:
                        members.append(self._item(member))
                header = copy.copy(node)
                header.body = []
                first = min([node.lineno, *(d.lineno for d in node.decorator_list)])
                ends = [node.lineno, *(getattr(n, "end_lineno", None) or 0 for n in (*node.bases, *node.keywords))]
                items.append((ast.dump(header), self.text(first, max(ends)), tuple(members)))
            else:
                items.append(self._item(node))
        self.items = items

    def fingerprint(self, qualname: str) -> tuple[object, ...] | None:
        """Everything of T that must not change: its decorators, signature and the statements up to its last skip."""
        found = self.facts.skip_relevant(qualname) if qualname in self.facts.collected else None
        if found is None:
            return None
        function, prefix = found
        return (
            isinstance(function, ast.AsyncFunctionDef),
            function.name,
            tuple(ast.dump(d) for d in function.decorator_list),
            ast.dump(function.args),
            ast.dump(function.returns) if function.returns is not None else "",
            tuple(ast.dump(t) for t in getattr(function, "type_params", ())),
            tuple(ast.dump(s) for s in prefix),
        )

    def protected(self, qualname: str) -> tuple[str, ...]:
        """The lines of T that no change may touch, as written: from its first decorator to the end of its signature,
        and every line of the statements of its prefix (comment and blank lines among them left out)."""
        found = self.facts.skip_relevant(qualname)
        assert found is not None
        function, prefix = found
        first, _ = _span(function)
        signature: list[ast.AST] = [function.args, *([function.returns] if function.returns is not None else [])]
        last = max([function.lineno, *(getattr(n, "end_lineno", None) or 0 for p in signature for n in ast.walk(p))])
        lines = set(range(first, last + 1))
        for statement in prefix:
            lines.update(range(statement.lineno, (statement.end_lineno or statement.lineno) + 1))
        return tuple(self.lines[n - 1] for n in sorted(lines) if not self.trivial(n))


class _Names:
    """What the base module binds or loads, for the names a new import or a new test may take."""

    def __init__(self, tree: ast.Module) -> None:
        self.module: set[str] = set()  # a name any statement loads, or that the module binds
        self.attributes: set[str] = set()
        self.members: set[str] = set()  # the defs of the module and of its classes
        self.words: set[str] = set()  # the words of the string conditions of the skip markers
        self.star = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                self.module.add(node.id)
            elif isinstance(node, ast.Attribute):
                self.attributes.add(node.attr)
            elif isinstance(node, ast.alias):
                self.module.add(node.asname or node.name.split(".")[0])
                self.star = self.star or node.name == "*"
            elif isinstance(node, ast.Global | ast.Nonlocal):
                self.module.update(node.names)
            elif isinstance(node, ast.ExceptHandler | ast.MatchAs | ast.MatchStar) and node.name:
                self.module.add(node.name)
            elif isinstance(node, ast.MatchMapping) and node.rest:
                self.module.add(node.rest)
            elif isinstance(node, ast.Call):
                self._condition(node)
        for statement in scan.flat(tree.body):
            if isinstance(statement, _FUNCTIONS | ast.ClassDef):
                self.module.add(statement.name)
                self.members.add(statement.name)
            if isinstance(statement, ast.ClassDef):
                self.members.update(
                    s.name for s in scan.flat(statement.body) if isinstance(s, _FUNCTIONS | ast.ClassDef)
                )

    def _condition(self, call: ast.Call) -> None:
        """`skipif("FLAG and sys.platform == 'x'")`: pytest evaluates the string with the module's names."""
        func = call.func
        name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
        if name in _CONDITIONAL:
            given = [*call.args[:1], *(k.value for k in call.keywords if k.arg == "condition")]
            for value in given:
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    self.words.update(_WORD.findall(value.value))

    def free(self, name: str) -> bool:
        """The module may bind `name` newly: nothing binds or loads it, no string condition names it, pytest and the
        builtins do not give it."""
        return name not in self.module and name not in self.words and name not in _GIVEN


class Confined:
    """Rule (e) for the tests of one file, with the base text `base` and the head text `head` and their facts."""

    def __init__(self, base: str, head: str, before: SkipFacts, after: SkipFacts) -> None:
        self.base, self.head = _Side(before, normalized(base)), _Side(after, normalized(head))
        self._ready: bool | None = None
        self._names: _Names | None = None

    def holds(self, qualname: str) -> bool:
        """True when every change the unit made to the file is in a place the rule allows, for the test `qualname`."""
        if self._ready is None:
            self._ready = self._compare()
        if not self._ready:
            return False
        before, after = self.base.fingerprint(qualname), self.head.fingerprint(qualname)
        if before is None or before != after or self.base.positions.get(qualname) != self.head.positions.get(qualname):
            return False
        return self.base.protected(qualname) == self.head.protected(qualname)

    def _compare(self) -> bool:
        """What does not depend on the test: both sides read, the coding line the same, the added imports and the added
        tests take no name that matters, and the statements that are not collected tests the same, as trees and as
        written (see the module's text for why the lines of the diff are not read)."""
        base, head = self.base, self.head
        if not (base.ok and head.ok) or base.cookie != head.cookie:
            return False
        imports = self._added_imports()
        if imports is None or not self._new_tests_are_free():
            return False
        base.build(frozenset())
        head.build(frozenset(id(n) for n in imports))
        return base.items == head.items

    def _base_names(self) -> _Names:
        if self._names is None:
            self._names = _Names(self.base.tree)
        return self._names

    def _added_imports(self) -> list[ast.stmt] | None:
        """The head's module-level imports that the base does not have, when each is a whole statement of its own
        lines that binds only free names (rule 3); `[]` when there are none, None when one is not allowed."""
        base, head = self.base, self.head
        have = Counter(ast.dump(n) for n in base.imports)
        new: list[ast.stmt] = []
        for statement in head.imports:
            text = ast.dump(statement)
            if have[text] > 0:
                have[text] -= 1
            else:
                new.append(statement)
        if not new:
            return []
        names = self._base_names()
        if names.star:
            return None
        taken: set[str] = set()
        for statement in new:
            bound = _bound(statement)
            if bound is None or not all(names.free(n) for n in bound) or bound & taken:
                return None
            taken |= bound
            if any(
                other is not statement
                and other.lineno <= (statement.end_lineno or 0)
                and (other.end_lineno or 0) >= statement.lineno
                for other in head.tree.body
            ):
                return None  # `import json; X = 1`: the line holds another statement
        return new

    def _new_tests_are_free(self) -> bool:
        """A test the head has and the base has not takes no name the base binds, loads or reads as an attribute."""
        base, head = self.base, self.head
        fresh = [q for q, _ in head.facts.tests if q not in base.facts.collected]
        if not fresh:
            return True
        names = self._base_names()
        return all(
            (leaf := q.rsplit(".", 1)[-1]) not in names.module
            and leaf not in names.attributes
            and leaf not in names.members
            for q in fresh
        )
