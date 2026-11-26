"""A test file the unit only added whole new tests to does not keep a UI criterion a gap (L4-VER-097, L4-VER-098).

Condition 3 of the carry (L4-VER-086) wants the files of a criterion's tracing tests to be the base's. A file that the
unit changed only by adding new tests keeps every old test as it was, and the rule here proves that from the two texts:
no deleted line, every old test's block is the base's text, and the lines outside the tests are the base's, so that what
was added is whole new tests. Pure: two texts, names and the facts of the diff; nothing is read from git here, and
nothing raises (any failure is False, the criterion stays a gap).

JavaScript and TypeScript read a block as `test_locate` does and require it to be a call line that names the test, found
once and closed. Python reads the AST. Step 1's run of the base's file on the unit's code (the other leg of the rule) is
`base_run_covers`; the glue that reads git and the reports is in `ladder`.
"""

import ast
import io
import tokenize
from collections.abc import Collection, Iterable
from dataclasses import dataclass

from l4.implementer.tamper import names_test_id
from l4.implementer.test_locate import call_span, outside_tests
from l4.verifier.gate_repeat import JS_EXTENSIONS
from l4.verifier.scan import _qualified

_OPEN = {"(": ")", "[": "]", "{": "}"}
_CLOSE = {v: k for k, v in _OPEN.items()}


@dataclass(frozen=True)
class FileFacts:
    """What `git diff --name-status --no-renames` and `--numstat` say of one file between the unit's base and head:
    `status` is the letter (`M` modified), `deleted` the number of deleted lines, None for a binary file."""

    status: str
    deleted: int | None


@dataclass(frozen=True)
class BaseRun:
    """The four lists of step 1's `verify.base_tests` event of this round (L4-VER-097 (b)): the files it ran at their
    base version on the unit's code and the test ids that failed there, did not run there or were flaky."""

    reverted: tuple[str, ...] = ()
    failing: tuple[str, ...] = ()
    not_run: tuple[str, ...] = ()
    flaky: tuple[str, ...] = ()


def base_run_covers(run: BaseRun | None, path: str, traced: Iterable[str]) -> bool:
    """(b): step 1 ran `path` at its base version on the unit's code, and no tracing test of the file (any criterion's)
    is among what failed, did not run or was flaky there. No record of step 1 (it did not run, or stopped early) says
    no."""
    if run is None or path not in run.reverted:
        return False
    bad = {*run.failing, *run.not_run, *run.flaky}
    return not any(test in bad for test in traced)


def is_closed(text: str) -> bool:
    """Do the `(`, `{` and `[` of a JavaScript or TypeScript block balance, with strings, template literals and
    comments skipped, and no count negative? A quoted string that does not end on its line (JSX text with an apostrophe
    opens one) or an unterminated template or comment is not closed. A scanner, not a parser: a regular expression
    literal that holds a quote can mislead it (D3 of the change names the residual risk)."""
    stack: list[str] = []
    i, n = 0, len(text)

    def template(at: int) -> int | None:
        """Scan a template literal from just after its opening backtick: the index after the closing backtick, or the
        index of the code of a `${` (pushed), or None when it does not end."""
        while at < n:
            c = text[at]
            if c == "\\":
                at += 2
            elif c == "`":
                return at + 1
            elif c == "$" and text.startswith("${", at):
                stack.append("${")
                return at + 2
            else:
                at += 1
        return None

    while i < n:
        c = text[i]
        if c in "\"'":
            j = i + 1
            while j < n and text[j] != c:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j] == "\n":
                    return False
                j += 1
            if j >= n:
                return False
            i = j + 1
        elif c == "`":
            found = template(i + 1)
            if found is None:
                return False
            i = found
        elif text.startswith("//", i):
            end = text.find("\n", i)
            i = n if end < 0 else end
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end < 0:
                return False
            i = end + 2
        elif c in _OPEN:
            stack.append(c)
            i += 1
        elif c in _CLOSE:
            if not stack:
                return False
            top = stack.pop()
            if top == "${":
                if c != "}":
                    return False
                found = template(i + 1)
                if found is None:
                    return False
                i = found
                continue
            if top != _CLOSE[c]:
                return False
            i += 1
        else:
            i += 1
    return not stack


def _block(lines: list[str], name: str) -> tuple[int, int] | None:
    """The lines of the test `name` as a closed block that starts at a call line naming it, found once; else None."""
    span = call_span(lines, name)
    if span is None or not is_closed("\n".join(lines[span[0] : span[1]])):
        return None
    return span


def _js_only_added_tests(base: str, head: str, traced: Collection[str], names: Collection[str]) -> bool:
    before, after = base.splitlines(), head.splitlines()
    old: list[str] = []
    new: list[str] = []
    for name in dict.fromkeys(names):
        if _block(before, name) is not None:
            old.append(name)
        elif _block(after, name) is not None:
            new.append(name)
    if not traced or not all(test in old for test in traced):
        return False
    for name in old:
        was, now = _block(before, name), _block(after, name)
        if was is None or now is None or before[was[0] : was[1]] != after[now[0] : now[1]]:
            return False
    return outside_tests(base, old) == outside_tests(head, [*old, *new])


def _droppable(text: str) -> set[int] | None:
    """The 1-based lines of `text` that are blank or hold only a comment (by `tokenize`, so that a blank line inside a
    triple-quoted string is not one), or None when it cannot be tokenized."""
    code: set[int] = set()
    skip = {
        tokenize.COMMENT, tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT, tokenize.ENDMARKER,
        tokenize.ENCODING,
    }  # fmt: skip
    try:
        for tok in tokenize.generate_tokens(io.StringIO(text).readline):
            if tok.type not in skip:
                code.update(range(tok.start[0], tok.end[0] + 1))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return None
    return set(range(1, len(text.splitlines()) + 1)) - code


def _tests(tree: ast.Module) -> dict[str, list[ast.FunctionDef | ast.AsyncFunctionDef]]:
    """The collected tests of a module: its functions and the methods of its module-level classes whose name starts with
    `test`, by qualified name (`scan._qualified`). A name defined twice has two nodes."""
    found: dict[str, list[ast.FunctionDef | ast.AsyncFunctionDef]] = {}
    for name, node in _qualified(tree):
        if name.rsplit(".", 1)[-1].startswith("test"):
            found.setdefault(name, []).append(node)
    return found


def _bindings(body: list[ast.stmt], name: str) -> int:
    """How many statements of the scope bind `name`, looking into `if`, `try`, `with`, `for` and `while` but not into a
    nested function or class (which only bind their own name here). A comprehension or lambda inside a statement is
    walked too: counting too many only makes the rule refuse."""
    count = 0
    stack: list[ast.AST] = list(body)
    while stack:
        node = stack.pop()
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            count += node.name == name
            continue
        if isinstance(node, ast.Import | ast.ImportFrom):
            count += sum((a.asname or a.name.split(".")[0]) == name for a in node.names)
        if isinstance(node, ast.ExceptHandler) and node.name == name:
            count += 1
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store | ast.Del) and node.id == name:
            count += 1
        if isinstance(node, ast.Global | ast.Nonlocal):
            count += name in node.names
        stack.extend(ast.iter_child_nodes(node))
    return count


def _scope_of(tree: ast.Module, qualified: str) -> list[ast.stmt] | None:
    """The statements of the scope a test of that qualified name is bound in: the module's, or the body of the
    module-level class that owns it (None when the module has no such class)."""
    owner = qualified.rpartition(".")[0]
    if not owner:
        return tree.body
    return next((n.body for n in tree.body if isinstance(n, ast.ClassDef) and n.name == owner), None)


def _qualified_of(test_id: str, path: str) -> str | None:
    """`tests.test_a.TestA::test_x[p]` in `tests/test_a.py` is `TestA.test_x`, `tests.test_a::test_x` is `test_x`; a
    deeper class path (a nested class) or an id that does not name the module is None."""
    module = path.removesuffix(".py").replace("/", ".")
    where, _, tail = test_id.rpartition("::")
    function = tail.split("[", 1)[0]
    if not function:
        return None
    if where == module:
        return function if names_test_id(test_id, path, function) else None
    if where.startswith(module + "."):
        owner = where[len(module) + 1 :]
        qualified = f"{owner}.{function}"
        return qualified if "." not in owner and names_test_id(test_id, path, qualified) else None
    return None


def _py_only_added_tests(path: str, base: str, head: str, traced: Collection[str]) -> bool:
    try:
        before_tree, after_tree = ast.parse(base), ast.parse(head)
    except (SyntaxError, ValueError, RecursionError):
        return False
    old, now = _tests(before_tree), _tests(after_tree)
    if not traced:
        return False
    for test_id in traced:
        qualified = _qualified_of(test_id, path)
        if qualified is None or qualified not in old or qualified not in now:
            return False
    spans: list[tuple[int, int]] = []
    for qualified, nodes in now.items():
        if qualified in old:
            continue
        if len(nodes) != 1:
            return False
        node = nodes[0]
        if node.decorator_list:  # a mark, a `parametrize` or a fixture alias could reach a fixture, a skip or a reorder
            return False
        leaf = qualified.rpartition(".")[2]
        in_head, in_base = _scope_of(after_tree, qualified), _scope_of(before_tree, qualified)
        if in_head is None or in_base is None or _bindings(in_head, leaf) != 1 or _bindings(in_base, leaf) != 0:
            return False  # a later definition of an old name would replace the old test
        spans.append((min([node.lineno, *(d.lineno for d in node.decorator_list)]), node.end_lineno or node.lineno))
    removed = {line for first, last in spans for line in range(first, last + 1)}
    skip_before, skip_after = _droppable(base), _droppable(head)
    if skip_before is None or skip_after is None:
        return False
    keep_before = [t for at, t in enumerate(base.splitlines(), 1) if at not in skip_before]
    keep_after = [t for at, t in enumerate(head.splitlines(), 1) if at not in skip_after and at not in removed]
    return keep_before == keep_after


def appended_only(
    path: str, base: str | None, head: str | None, traced: Collection[str], names: Collection[str],
    facts: FileFacts | None,
) -> bool:  # fmt: skip
    """Did the unit only add whole new tests to the test file `path` (L4-VER-097 for JavaScript and TypeScript,
    L4-VER-098 for Python)? `base` and `head` are the two blobs (None: not read), `traced` the ids of every test of the
    file that step 4 traced to a criterion, listed or ignored, `names` the test names of the file in the head's step-3
    reports (JavaScript and TypeScript), `facts` the diff's (`FileFacts`). Condition (b), step 1's run, is
    `base_run_covers`. A file of another language is False. Never raises: any doubt is False."""
    try:
        if facts is None or facts.status != "M" or facts.deleted != 0 or base is None or head is None:
            return False
        extension = path.rsplit(".", 1)[-1] if "." in path else ""
        if extension in JS_EXTENSIONS:
            return _js_only_added_tests(base, head, [t.partition("::")[2] for t in traced], names)
        if extension == "py":
            return _py_only_added_tests(path, base, head, list(traced))
    except Exception:  # noqa: BLE001 - a doubt is a gap, never a crash of the verifier
        return False
    return False
