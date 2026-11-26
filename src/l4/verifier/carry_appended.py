"""A test file the unit only added whole new tests to does not keep a UI criterion a gap (L4-VER-097, L4-VER-098).

Condition 3 of the carry (L4-VER-086) wants the files of a criterion's tracing tests to be the base's. A file that the
unit changed only by adding new tests keeps every old test as it was, and the rule here proves that from the two texts:
no deleted line, every old test's block is the base's text, and the lines outside the tests are the base's, so that what
was added is whole new tests. `appended_only` is pure: two texts, names and the facts of the diff, and it never
raises (any failure is False, the criterion stays a gap). `AppendedFiles` is the glue step 5 hands to
`ui_step.carried_from_base`: it reads the facts and the two blobs from git, once per file, and only for a file that a
criterion's other conditions asked about.

JavaScript and TypeScript read an OLD test's block as `test_locate` does and require it to be a call line that names the
test, found once and closed; a NEW test is exactly one plain `it(` or `test(` statement (`_plain_calls`). Python reads
the AST. Step 1's run of the base's file on the unit's code (the other leg of the rule) is
`base_run_covers`; the glue that reads git and the reports is in `ladder`.
"""

import ast
import io
import re
import tokenize
from bisect import bisect_right
from collections import Counter
from collections.abc import Callable, Collection, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass

from l4.evidence.collect import MAX_SOURCE_BYTES
from l4.gates.junit import TestReport
from l4.implementer.tamper import names_test_id
from l4.implementer.test_locate import CallIndex, call_span, test_names_of
from l4.vcs.git import Git
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
class Step1Run:
    """The four lists of step 1's `verify.base_tests` event of this round (L4-VER-097 (b)): the files it ran at their
    base version on the unit's code and the test ids that failed there, did not run there or were flaky; and `passed`,
    the ids that PASSED in that run (R1, not in the event). None: not recorded, which fails closed."""

    reverted: tuple[str, ...] = ()
    failing: tuple[str, ...] = ()
    not_run: tuple[str, ...] = ()
    flaky: tuple[str, ...] = ()
    passed: tuple[str, ...] | None = None


def base_run_covers(run: Step1Run | None, path: str, traced: Iterable[str]) -> bool:
    """(b): step 1 ran `path` at its base version on the unit's code, and every tracing test of the file (any
    criterion's) PASSED there: it is among the ids that passed in that run and not among what failed, did not run or was
    flaky. Absence from the bad lists is not enough (a test the run never saw is in none of them). No record of step 1
    (it did not run, or stopped early) or no list of what passed says no."""
    if run is None or run.passed is None or path not in run.reverted:
        return False
    bad = {*run.failing, *run.not_run, *run.flaky}
    passed = set(run.passed)
    return all(test in passed and test not in bad for test in traced)


class _Unterminated(Exception):
    """A string, template literal or comment that does not end."""


_BRACKETS = frozenset("([{")


def _template(text: str, at: int) -> tuple[int, bool]:
    """Scan a template literal from just after its opening backtick (or from just after the `}` that closes a `${`):
    the index after the closing backtick and False, or the index after a `${` and True. `_Unterminated` when it does
    not end."""
    n = len(text)
    while at < n:
        char = text[at]
        if char == "\\":
            at += 2
        elif char == "`":
            return at + 1, False
        elif char == "$" and text.startswith("${", at):
            return at + 2, True
        else:
            at += 1
    raise _Unterminated


def _tokens(text: str, start: int = 0, *, lenient: bool = False) -> Iterator[tuple[int, str]]:
    """`(index, token)` of every significant character of `text` from `start`, with whitespace and comments skipped, a
    quoted string or a template literal's text as one token `"`, and `${` as an opener whose `}` is its closer. A quote
    that does not end on its line, an unterminated template or an unterminated block comment raises `_Unterminated`;
    with `lenient` the quote is an ordinary character instead (JSX text with an apostrophe leaves one open), and the
    template or the comment is read to the end. A scanner, not a parser: a regular expression literal that holds a quote
    can mislead it (D3 of the change names the residual risk)."""
    n = len(text)
    stack: list[str] = []
    i = start
    while i < n:
        char = text[i]
        if char.isspace():
            i += 1
        elif char in "\"'":
            j = i + 1
            while j < n and text[j] not in (char, "\n"):
                j += 2 if text[j] == "\\" else 1
            if j >= n or text[j] != char:
                if not lenient:
                    raise _Unterminated
                yield i, char
                i += 1
                continue
            yield i, '"'
            i = j + 1
        elif char == "`":
            try:
                end, opened = _template(text, i + 1)
            except _Unterminated:
                if not lenient:
                    raise
                yield i, char
                i += 1
                continue
            yield i, '"'
            if opened:
                stack.append("${")
                yield end - 2, "${"
            i = end
        elif text.startswith("//", i):
            end = text.find("\n", i)
            i = n if end < 0 else end
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end < 0:
                if not lenient:
                    raise _Unterminated
                return
            i = end + 2
        elif char in _BRACKETS:
            stack.append(char)
            yield i, char
            i += 1
        elif char in _CLOSE:
            resumes = char == "}" and bool(stack) and stack[-1] == "${"
            if stack:
                stack.pop()
            yield i, char
            if resumes:
                try:
                    end, opened = _template(text, i + 1)
                except _Unterminated:
                    if not lenient:
                        raise
                    return
                if opened:
                    stack.append("${")
                    yield end - 2, "${"
                i = end
            else:
                i += 1
        else:
            yield i, char
            i += 1


def _closes(top: str, token: str) -> bool:
    return token == "}" if top == "${" else _CLOSE[token] == top


def is_closed(text: str) -> bool:
    """Do the `(`, `{` and `[` of a JavaScript or TypeScript block balance, with strings, template literals and
    comments skipped, and no count negative? A quoted string that does not end on its line (JSX text with an apostrophe
    opens one) or an unterminated template or comment is not closed (`_tokens`)."""
    stack: list[str] = []
    try:
        for _, token in _tokens(text):
            if token in _BRACKETS or token == "${":
                stack.append(token)
            elif token in _CLOSE and (not stack or not _closes(stack.pop(), token)):
                return False
    except _Unterminated:
        return False
    return not stack


def _match(text: str, at: int) -> int | None:
    """The index after the bracket that closes the one at `text[at]`; None for a mismatch or an unterminated string."""
    stack: list[str] = []
    try:
        for pos, token in _tokens(text, at):
            if token in _BRACKETS or token == "${":
                stack.append(token)
            elif token in _CLOSE:
                if not stack or not _closes(stack.pop(), token):
                    return None
                if not stack:
                    return pos + 1
    except _Unterminated:
        return None
    return None


_SPACE = re.compile(r"\s*")
# no `describe`, no hook and no modifier (`.only`, `.skip`, `.each`): all refused
_STATEMENT = re.compile(r"(?:it|test)\s*\(")
_FUNCTION = re.compile(r"(?:async\s+)?function(?:\s+[A-Za-z_$][\w$]*)?\s*\(")
_ARROW_NAMED = re.compile(r"(?:async\s+)?[A-Za-z_$][\w$]*\s*=>\s*\{")
_ARROW_PARENS = re.compile(r"(?:async\s+)?\(")
_NUMBER = re.compile(r"\d[\d_]*(?:\.\d+)?")
_TAIL = re.compile(r"[ \t]*(;?)[ \t]*(?://.*)?")
_CONTINUES = frozenset("([`+-*/.,?:=&|<>%^~!")  # a line that starts so continues the statement before it (no `;`)
_CONTROL = re.compile(r"\b(?:if|for(?:\s+await)?|while|switch|with|catch)\s*$")  # the `(` of these heads a body


def _skip(text: str, at: int) -> int:
    return _SPACE.match(text, at).end()  # type: ignore[union-attr]  # `\s*` always matches


def _plain_params(params: str) -> bool:
    """At most one parameter, a name or a destructuring pattern with an optional type, and no default value: no `=` (but
    `=>`), no call, no string. Counts of `{`, `[` and `<` balance and no comma lies at the top."""
    flat = params.replace("=>", "")
    if "=" in flat or any(char in flat for char in "()`\"'"):
        return False
    depth = 0
    for char in flat:
        if char in "{[<":
            depth += 1
        elif char in "}]>":
            depth -= 1
            if depth < 0:
                return False
        elif char == "," and depth == 0:
            return False
    return depth == 0


def _function_body(text: str, at: int) -> int | None:
    """The index of the `{` that opens the body of the function literal at `at` (`() => {`, `async () => {`,
    `function (`, `async function (`, `ctx => {`, with at most one plain parameter), or None."""
    if found := _ARROW_NAMED.match(text, at):
        return found.end() - 1
    function = _FUNCTION.match(text, at)
    if (found := function or _ARROW_PARENS.match(text, at)) is None:
        return None
    opening = found.end() - 1
    closing = _match(text, opening)
    if closing is None or not _plain_params(text[opening + 1 : closing - 1]):
        return None
    after = _skip(text, closing)
    if function is None:  # an arrow: `=>` between the parameters and the body
        if not text.startswith("=>", after):
            return None
        after = _skip(text, after + 2)
    return after if text[after : after + 1] == "{" else None


def _title(text: str, at: int) -> tuple[str, int] | None:
    """A single string literal at `at` (quotes, or a backtick template with no `${`): its text, and the index after"""
    n = len(text)
    quote = text[at : at + 1]
    if quote not in ('"', "'", "`"):
        return None
    j = at + 1
    while j < n and text[j] != quote:
        if text[j] == "\\":
            j += 2
            continue
        if text[j] == "\n" and quote != "`" or text.startswith("${", j) and quote == "`":
            return None
        j += 1
    return (text[at + 1 : j], j + 1) if j < n else None


def _plain_call(text: str, paren: int) -> tuple[str, int] | None:
    """The call whose `(` is at `paren`, when it is `(<string>, <function literal>[, <number>][,])`: its title and the
    index after its `)`; else None."""
    if (head := _title(text, _skip(text, paren + 1))) is None:
        return None
    title, at = head
    at = _skip(text, at)
    if text[at : at + 1] != ",":
        return None
    if (body := _function_body(text, _skip(text, at + 1))) is None or (end := _match(text, body)) is None:
        return None
    at = _skip(text, end)
    if text[at : at + 1] == ",":
        at = _skip(text, at + 1)
        if number := _NUMBER.match(text, at):  # the timeout
            at = _skip(text, number.end())
            if text[at : at + 1] == ",":
                at = _skip(text, at + 1)
    return (title, at + 1) if text[at : at + 1] == ")" else None


def _ends_cleanly(text: str, end: int) -> bool:
    """After the call's `)` its line holds only an optional `;` and whitespace or a `//` comment; with no `;` the next
    code character does not continue the statement (ASI would not end it before a `(`, a `.` or an operator)."""
    newline = text.find("\n", end)
    rest = text[end : len(text) if newline < 0 else newline]
    if (tail := _TAIL.fullmatch(rest.rstrip("\r"))) is None:
        return False
    if tail.group(1):
        return True
    at = len(text) if newline < 0 else newline + 1
    while True:
        at = _skip(text, at)
        if not text.startswith("//", at):
            break
        newline = text.find("\n", at)
        at = len(text) if newline < 0 else newline
    return at >= len(text) or text[at] not in _CONTINUES


@dataclass(frozen=True)
class PlainCall:
    """One `it(` or `test(` statement of the form `_plain_call` reads, on lines `first..last` (0-based, inclusive)."""

    title: str
    first: int
    last: int


def _plain_calls(text: str) -> list[PlainCall]:
    """Every statement of `text` that is exactly one plain `it(` or `test(` call, in one scan (L4-VER-097). It starts
    its line; it is a statement: outside every string, template and comment, directly in the file or in a `{` block,
    after a `;`, a `{`, a `}` or a `)` that does not close the head of an `if`, `for` or `while`; its first argument is
    one string, its second a function literal with at most one plain parameter, an optional third a number; and its `)`
    ends its last line (`_ends_cleanly`). A call that is none of this is not listed, so its lines are outside lines."""
    starts = [0] + [m.end() for m in re.finditer("\n", text)]
    found: list[PlainCall] = []
    stack: list[str] = []
    control: list[bool] = []
    prev, closed_control, skip = None, False, 0
    for pos, token in _tokens(text, lenient=True):
        if pos < skip:
            continue
        in_block = not stack or stack[-1] == "{"
        after_statement = prev is None or prev in ";{}" or (prev == ")" and not closed_control)
        if token in ("i", "t") and in_block and after_statement and (opened := _STATEMENT.match(text, pos)):
            line = bisect_right(starts, pos) - 1
            if not text[starts[line] : pos].strip() and (call := _plain_call(text, opened.end() - 1)):
                title, end = call
                if _ends_cleanly(text, end):
                    found.append(PlainCall(title, line, bisect_right(starts, end - 1) - 1))
                    prev, closed_control, skip = ";", False, end
                    continue
        if token in _BRACKETS or token == "${":
            control.append(token == "(" and bool(_CONTROL.search(text[max(0, pos - 24) : pos])))
            stack.append(token)
        elif token in _CLOSE:
            closed_control = control.pop() if stack else False
            if stack:
                stack.pop()
        prev = token
    return found


def _titles_naming(name: str) -> set[str]:
    """The strings a test call may carry for the reported `name`: the name, or what follows one of its spaces (the
    reporter joined the `describe` names and the test's with a space or ` > `)."""
    return {name, *(name[at + 1 :] for at, char in enumerate(name) if char == " ")} - {""}


def _new_span(
    by_title: Mapping[str, Sequence[PlainCall]], name: str, taken: Callable[[PlainCall], bool]
) -> tuple[int, int] | None:
    """The lines of the one plain call that carries the longest string naming `name`, not one that lies in an old test's
    block (`taken`); None when there is no such call or several carry that string."""
    found = [call for title in _titles_naming(name) for call in by_title.get(title, ()) if not taken(call)]
    if not found:
        return None
    top = max(len(call.title) for call in found)
    longest = [call for call in found if len(call.title) == top]
    return (longest[0].first, longest[0].last + 1) if len(longest) == 1 else None


def _block(lines: list[str], name: str, calls: CallIndex) -> tuple[int, int] | None:
    """The lines of the test `name` as a closed block that starts at a call line naming it, found once; else None."""
    span = call_span(lines, name, calls)
    if span is None or not is_closed("\n".join(lines[span[0] : span[1]])):
        return None
    return span


def _outside(lines: list[str], spans: Iterable[tuple[int, int]]) -> list[str]:
    """The non-blank lines of `lines` in none of `spans` (a test appended to a file brings the blank line before it,
    which lies outside every block)."""
    inside: set[int] = set()
    for first, last in spans:
        inside.update(range(first, last))
    return [line for at, line in enumerate(lines) if at not in inside and line.strip()]


def _js_only_added_tests(base: str, head: str, traced: Collection[str], names: Collection[str]) -> bool:
    """OLD tests keep their block as it was and every traced test is one; NEW tests are plain `it(` or `test(`
    statements (`_plain_calls`); the lines outside both are the base's. Every file is read once: the names are looked
    up in an index of its calls (F4)."""
    before, after = base.splitlines(), head.splitlines()
    calls_before, calls_after = CallIndex(before), CallIndex(after)
    old: dict[str, tuple[tuple[int, int], tuple[int, int]]] = {}
    new: list[str] = []
    for name in dict.fromkeys(names):
        was = _block(before, name, calls_before)
        if was is None:
            new.append(name)
            continue
        now = _block(after, name, calls_after)
        if now is None or before[was[0] : was[1]] != after[now[0] : now[1]]:
            return False
        old[name] = (was, now)
    if not traced or not all(test in old for test in traced):
        return False
    held = [now for _, now in old.values()]
    by_title: dict[str, list[PlainCall]] = {}
    for call in _plain_calls("\n".join(after)):
        by_title.setdefault(call.title, []).append(call)
    lines_held = {at for first, last in held for at in range(first, last)}

    def taken(call: PlainCall) -> bool:
        return any(at in lines_held for at in range(call.first, call.last + 1))

    added = [_new_span(by_title, name, taken) for name in new]
    return _outside(before, (was for was, _ in old.values())) == _outside(after, [*held, *(a for a in added if a)])


_CODING = re.compile(r"^[ \t\f]*#.*?coding[:=][ \t]*([-\w.]+)")  # PEP 263, as the interpreter reads it


def _droppable(text: str) -> set[int] | None:
    """The 1-based lines of `text` that are blank or hold only a comment (by `tokenize`, so that a blank line inside a
    triple-quoted string is not one), except a shebang on line 1 and a coding declaration (PEP 263) on line 1 or 2: they
    change how the file is read, so they are code here. None when it cannot be tokenized."""
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
    lines = text.splitlines()
    for number, line in enumerate(lines[:2], 1):
        if _CODING.match(line) or (number == 1 and line.startswith("#!")):
            code.add(number)
    return set(range(1, len(lines) + 1)) - code


def _tests(tree: ast.Module) -> dict[str, list[ast.FunctionDef | ast.AsyncFunctionDef]]:
    """The collected tests of a module: its functions and the methods of its module-level classes whose name starts with
    `test`, by qualified name (`scan._qualified`). A name defined twice has two nodes."""
    found: dict[str, list[ast.FunctionDef | ast.AsyncFunctionDef]] = {}
    for name, node in _qualified(tree):
        if name.rsplit(".", 1)[-1].startswith("test"):
            found.setdefault(name, []).append(node)
    return found


def _binding_counts(body: list[ast.stmt]) -> Counter[str]:
    """How many statements of the scope bind each name, looking into `if`, `try`, `with`, `for` and `while` but not into
    a nested function or class (which only bind their own name here). A comprehension or lambda inside a statement is
    walked too: counting too many only makes the rule refuse. Read once per scope."""
    counts: Counter[str] = Counter()
    stack: list[ast.AST] = list(body)
    while stack:
        node = stack.pop()
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            counts[node.name] += 1
            continue
        if isinstance(node, ast.Import | ast.ImportFrom):
            counts.update((a.asname or a.name.split(".")[0]) for a in node.names)
        if isinstance(node, ast.ExceptHandler) and node.name:
            counts[node.name] += 1
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store | ast.Del):
            counts[node.id] += 1
        if isinstance(node, ast.Global | ast.Nonlocal):
            counts.update(node.names)
        stack.extend(ast.iter_child_nodes(node))
    return counts


def _plain_annotation(node: ast.expr) -> bool:
    """Names, attributes and subscripts of those, constants (and the tuples and lists that a subscript is made of): what
    `def` evaluates without running anything of the file's own. A call, a lambda, a walrus or an operator is not."""
    if isinstance(node, ast.Name | ast.Constant):
        return True
    if isinstance(node, ast.Attribute):
        return _plain_annotation(node.value)
    if isinstance(node, ast.Subscript):
        return _plain_annotation(node.value) and _plain_annotation(node.slice)
    if isinstance(node, ast.Tuple | ast.List):
        return all(_plain_annotation(item) for item in node.elts)
    return False


def _plain_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """A new test's `def` line runs at collection, before any test: it has no default value (positional or
    keyword-only), no type parameters, and every annotation, the return one included, is `_plain_annotation`. Plain
    fixture parameters (`db`, `db: Session`, `-> None`) pass."""
    args = node.args
    if args.defaults or any(default is not None for default in args.kw_defaults) or getattr(node, "type_params", None):
        return False
    declared = (*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg)
    annotations = [arg.annotation for arg in declared if arg is not None and arg.annotation is not None]
    if node.returns is not None:
        annotations.append(node.returns)
    return all(_plain_annotation(annotation) for annotation in annotations)


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
    counted: dict[int, Counter[str]] = {}  # the bindings of a scope, read once whatever number of tests it holds
    for qualified, nodes in now.items():
        if qualified in old:
            continue
        if len(nodes) != 1:
            return False
        node = nodes[0]
        if node.decorator_list:  # a mark, a `parametrize` or a fixture alias could reach a fixture, a skip or a reorder
            return False
        if not _plain_signature(node):  # a default value or a computed annotation runs when the module is collected
            return False
        leaf = qualified.rpartition(".")[2]
        in_head, in_base = _scope_of(after_tree, qualified), _scope_of(before_tree, qualified)
        if in_head is None or in_base is None:
            return False
        for scope in (in_head, in_base):
            if id(scope) not in counted:
                counted[id(scope)] = _binding_counts(scope)
        if counted[id(in_head)][leaf] != 1 or counted[id(in_base)][leaf] != 0:
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


MAX_BLOB_BYTES = MAX_SOURCE_BYTES  # a test file read for this rule is at most as big as any source the harness reads


def _blob(git: Git, rev: str, path: str) -> str | None:
    """The text of `path` at `rev` from git, strictly UTF-8 and at most `MAX_BLOB_BYTES` bytes; else None."""
    data = git.run_bytes("show", f"{rev}:{path}", check=False)
    if not data or len(data) > MAX_BLOB_BYTES:
        return None
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None


class AppendedFiles:
    """The predicate `carried_from_base(appended=...)` takes: `__call__(test id, file)` says whether the changed `file`
    that holds the test meets L4-VER-097 / L4-VER-098, decided once per file; `accepted` lists the files it said yes to.
    `files`: test id -> the file that holds it, for every test step 4 traced to any criterion (listed or ignored);
    `reports`: the step-3 reports at the head (the unit gate's and the end-to-end gate's); `paths`: the work tree's
    files, read only when a name list is needed; `facts`: `playwright.changed_file_facts`, read only when asked."""

    def __init__(
        self, git: Git, base_sha: str, head: str, *, run: Step1Run | None, files: Mapping[str, str | None],
        reports: Sequence[TestReport | None], paths: Callable[[], Collection[str]],
        facts: Callable[[], Mapping[str, FileFacts]],
    ) -> None:  # fmt: skip
        self._git, self._base, self._head, self._run = git, base_sha, head, run
        self._files, self._reports, self._paths, self._facts = files, reports, paths, facts
        self._decided: dict[str, bool] = {}
        self.accepted: set[str] = set()

    def __call__(self, test_id: str, file: str) -> bool:
        if file not in self._decided:
            try:
                self._decided[file] = self._decide(file)
            except Exception:  # noqa: BLE001 - a doubt is a gap, never a crash of the verifier
                self._decided[file] = False
            if self._decided[file]:
                self.accepted.add(file)
        return self._decided[file]

    def _decide(self, file: str) -> bool:
        traced = sorted(i for i, f in self._files.items() if f == file)
        if not base_run_covers(self._run, file, traced):  # (b), the cheap leg, before any blob is read
            return False
        facts = self._facts().get(file)
        if facts is None or facts.status != "M" or facts.deleted != 0:
            return False
        base, head = _blob(self._git, self._base, file), _blob(self._git, self._head, file)
        if base is None or head is None:
            return False
        names: list[str] = []
        if file.rsplit(".", 1)[-1] in JS_EXTENSIONS:
            tree = self._paths()
            for report in self._reports:
                if report is not None:
                    names += test_names_of(file, report.tests, tree)
        return appended_only(file, base, head, traced, list(dict.fromkeys(names)), facts)
