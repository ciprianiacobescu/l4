"""Text edits behind the canary mutations (M16-G12). Pure functions over source text: no git, no test run, no engine.

Each returns the new text of one file (or None when the edit does not apply). The canary decides what the Stage A
checks must then say about the result; a mutation that does not produce its intended label is dropped there.
"""

import ast
import hashlib
import keyword
import re
from collections.abc import Sequence

MUTATIONS = (
    "none", "transplant_hunk", "template_edit", "drop_covering_test", "untested_function", "break_test",
    "add_passing_test", "skip_old_test",
)  # fmt: skip
SKIP_REASONS = ("flaky on CI", "needs network", "slow", "temporarily disabled", "revisit later")
LEAK = re.compile(r"canary|untested|template|l4", re.I)  # a state must never name the generator or its label
_FALLBACK_WORDS = ("value", "item", "entry", "total", "count", "index", "result", "state")


def pick(seed: int, count: int, *parts: object) -> int:
    """A stable index below `count` from the seed and the parts (a unit, a mutation, a variant)."""
    digest = hashlib.sha256("\0".join(str(p) for p in (seed, *parts)).encode()).hexdigest()
    return int(digest[:12], 16) % count if count else 0


def _ensure_newline(text: str) -> str:
    return text if text.endswith("\n") or not text else text + "\n"


def _vocabulary(text: str) -> list[str]:
    """The words of the file's own identifiers, so that generated names look like the project's and carry no marker."""
    words: set[str] = set()
    for name in re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text):
        words.update(w.lower() for w in name.split("_") if w.isalpha() and 3 <= len(w) <= 12)
    kept = sorted(w for w in words if not LEAK.search(w) and w not in _KEYWORDS)
    return kept if len(kept) >= 2 else list(_FALLBACK_WORDS)


_KEYWORDS = frozenset(
    ("def", "class", "import", "from", "return", "self", "none", "true", "false", "lambda", "pass", "with", "assert")
)


def fresh_name(text: str, variant: int, salt: str) -> str:
    """A snake_case name made of two words of the file's vocabulary that the file does not use yet."""
    words = _vocabulary(text)
    digest = hashlib.sha256(text.encode()).hexdigest()
    for attempt in range(len(words) ** 2 + 1):
        first = words[pick(variant + attempt, len(words), salt, "a", digest)]
        second = words[pick(variant + attempt, len(words), salt, "b", digest)]
        name = f"{first}_{second}" if first != second else f"{first}_{attempt + 2}"
        if not re.search(rf"\b{re.escape(name)}\b", text):
            return name
    return f"{words[0]}_{variant + 2}"


_TYPES = ("int", "str", "float", "bool", "bytes", "list[str]", "dict[str, int]", "tuple[int, ...]", "set[str]")


def _own_signatures(text: str) -> list[tuple[tuple[str, ...], str | None]]:
    """(parameters as written, return annotation) of the file's own functions that take a parameter: a generated
    function copies one of them, so that no fixed parameter name or type marks the template."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return []
    found: set[tuple[tuple[str, ...], str | None]] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name.startswith(("test", "__")):
            continue
        args = [a for a in (*node.args.posonlyargs, *node.args.args) if a.arg not in ("self", "cls")][:3]
        if not args or any(LEAK.search(a.arg) or keyword.iskeyword(a.arg) for a in args):
            continue
        params = tuple(a.arg if a.annotation is None else f"{a.arg}: {ast.unparse(a.annotation)}" for a in args)
        found.add((params, None if node.returns is None else ast.unparse(node.returns)))
    return sorted(found, key=lambda sig: (sig[0], sig[1] or ""))


def _drawn_signature(text: str, variant: int, name: str) -> tuple[tuple[str, ...], str | None]:
    digest = hashlib.sha256(text.encode()).hexdigest()
    own = _own_signatures(text)
    if own:
        return own[pick(variant, len(own), "sig", digest)]
    words = [w for w in _vocabulary(text) if w != name and not keyword.iskeyword(w)]
    count = 1 + pick(variant, 2, "sig-count", digest)
    params: list[str] = []
    for slot in range(count):
        word = words[pick(variant, len(words), "sig-name", slot, digest)]
        if word in (p.split(":")[0] for p in params):
            continue
        typed = pick(variant, 4, "sig-typed", slot, digest) != 0
        params.append(f"{word}: {_TYPES[pick(variant, len(_TYPES), 'sig-type', slot, digest)]}" if typed else word)
    returns = _TYPES[pick(variant, len(_TYPES), "sig-ret", digest)] if pick(variant, 4, "sig-rt", digest) else None
    return tuple(params), returns


def add_untested_function(text: str, variant: int) -> tuple[str, str]:
    """(new text, the new function's name): a function nothing calls, appended to the file. Its parameters and
    annotations are drawn from the file's own functions (else from its vocabulary and a seeded list of types)."""
    name = fresh_name(text, variant, "func")
    params, returns = _drawn_signature(text, variant, name)
    first = params[0].split(":")[0]
    bodies = (
        f"return {first}", f"return [{first}]", f"return ({first}, {variant + 1})", f"return {first} or {variant + 1}",
    )  # fmt: skip
    line = bodies[pick(variant, len(bodies), "body", name)]
    arrow = f" -> {returns}" if returns else ""
    return _ensure_newline(text) + f"\n\ndef {name}({', '.join(params)}){arrow}:\n    {line}\n", name


def add_template_edit(text: str, variant: int) -> str:
    """A module-level constant named from the file's vocabulary: an edit unrelated to any feature."""
    name = fresh_name(text, variant, "const").upper()
    return _ensure_newline(text) + f"\n{name} = {variant + 3}\n"


def top_level_block(text: str, span: tuple[int, int], target: str = "", variant: int = 0) -> str | None:
    """The source of a top-level def or class (1-based inclusive `span`), or None when it does not parse standalone
    or holds more than definitions. It is renamed `<name>_<variant + 2>` only when `target` already uses the name."""
    lines = text.splitlines()
    block = "\n".join(lines[span[0] - 1 : span[1]])
    try:
        tree = ast.parse(block)
    except SyntaxError:
        return None
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
        return None
    node = tree.body[0]
    first = (node.decorator_list[0].lineno if node.decorator_list else node.lineno) - 1
    pattern = rf"^(\s*(?:async\s+def|def|class)\s+){re.escape(node.name)}\b"
    out = block.splitlines()
    if re.search(rf"\b{re.escape(node.name)}\b", target):
        out[node.lineno - 1] = re.sub(pattern, rf"\g<1>{node.name}_{variant + 2}", out[node.lineno - 1], count=1)
    return "\n".join(out[first:])


def append_blocks(text: str, blocks: Sequence[str]) -> str:
    return _ensure_newline(text) + "\n\n" + "\n\n\n".join(blocks) + "\n"


def _test_nodes(tree: ast.Module) -> list[tuple[ast.ClassDef | None, ast.FunctionDef | ast.AsyncFunctionDef]]:
    found: list[tuple[ast.ClassDef | None, ast.FunctionDef | ast.AsyncFunctionDef]] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            found.append((None, node))
        elif isinstance(node, ast.ClassDef):
            found += [(node, m) for m in node.body if isinstance(m, ast.FunctionDef | ast.AsyncFunctionDef)]
    return found


def _first_line(node: ast.FunctionDef | ast.AsyncFunctionDef) -> int:
    return (node.decorator_list[0].lineno if node.decorator_list else node.lineno) - 1


def remove_or_skip_tests(
    text: str, targets: Sequence[tuple[str | None, str]], *, skip: bool, variant: int = 0
) -> str | None:
    """Delete the named tests (`(class or None, function)`), or put `@pytest.mark.skip` on each. None when no
    target is found or the file does not parse. A class left empty keeps a `pass`."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    wanted = set(targets)
    hits = [(cls, fn) for cls, fn in _test_nodes(tree) if ((cls.name if cls else None), fn.name) in wanted]
    if not hits:
        return None
    lines = text.splitlines()
    for cls, node in sorted(hits, key=lambda h: h[1].lineno, reverse=True):
        start = _first_line(node)
        indent = re.match(r"\s*", lines[node.lineno - 1]).group(0)  # type: ignore[union-attr]
        if skip:
            reason = SKIP_REASONS[pick(variant, len(SKIP_REASONS), node.name)]
            lines.insert(start, f'{indent}@pytest.mark.skip(reason="{reason}")')
            continue
        sole = cls is not None and sum(isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) for n in cls.body) == 1
        lines[start : node.end_lineno] = [indent + "pass"] if sole and len(cls.body) == 1 else []  # type: ignore[union-attr]
    out = "\n".join(lines) + "\n"
    if skip and not re.search(r"^\s*import pytest\b", out, re.M):
        split = out.splitlines()
        future = [i for i, ln in enumerate(split) if ln.startswith("from __future__")]
        split.insert((future[-1] + 1) if future else 0, "import pytest")
        out = "\n".join(split) + "\n"
    return out


def flip_expected_literal(text: str, variant: int, only_in: Sequence[str] | None = None) -> str | None:
    """Add 1 to an integer literal compared with `==` in an `assert` of a test function (of `only_in` when given):
    the test then fails. The `variant` picks which literal when there are several."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    hits: list[ast.Constant] = []
    for _, fn in _test_nodes(tree):
        if only_in is not None and fn.name not in only_in:
            continue
        for node in ast.walk(fn):
            if (
                isinstance(node, ast.Assert)
                and isinstance(node.test, ast.Compare)
                and isinstance(node.test.ops[0], ast.Eq)
            ):
                for side in (node.test.left, *node.test.comparators):
                    if isinstance(side, ast.Constant) and type(side.value) is int and side.lineno == side.end_lineno:
                        hits.append(side)
    if not hits:
        return None
    hits.sort(key=lambda n: (n.lineno, n.col_offset))
    target = hits[variant % len(hits)]
    lines = text.splitlines()
    row = lines[target.lineno - 1].encode("utf-8")
    new = row[: target.col_offset] + str(int(target.value) + 1).encode() + row[target.end_col_offset :]  # type: ignore[operator]
    lines[target.lineno - 1] = new.decode("utf-8")
    return "\n".join(lines) + "\n"


def add_missing_fixture(text: str, variant: int, only_in: Sequence[str] | None = None) -> str | None:
    """Add a parameter no fixture provides to a test function whose signature is on one line: the test then errors at
    setup. The `variant` picks which function."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    lines = text.splitlines()
    hits = [
        fn for _, fn in _test_nodes(tree)
        if fn.name.startswith("test") and (only_in is None or fn.name in only_in)
        and fn.lineno == fn.body[0].lineno - 1 and lines[fn.lineno - 1].rstrip().endswith(":")
        and ")" in lines[fn.lineno - 1]
    ]  # fmt: skip
    if not hits:
        return None
    target = hits[variant % len(hits)]
    row = lines[target.lineno - 1]
    close = row.rindex(")")
    name = fresh_name(text, variant, "fixture")
    has_args = bool(target.args.args or target.args.kwonlyargs or target.args.vararg or target.args.kwarg)
    lines[target.lineno - 1] = f"{row[:close]}{', ' if has_args else ''}{name}{row[close:]}"
    return "\n".join(lines) + "\n"


def skip_a_test(text: str, variant: int) -> str | None:
    """`@pytest.mark.skip` on one test function (the `variant`-th), so that it is reported skipped."""
    try:
        nodes = [(c, f) for c, f in _test_nodes(ast.parse(text)) if f.name.startswith("test")]
    except SyntaxError:
        return None
    if not nodes:
        return None
    cls, fn = nodes[variant % len(nodes)]
    return remove_or_skip_tests(text, [(cls.name if cls else None, fn.name)], skip=True, variant=variant)


def add_passing_test(text: str, variant: int) -> str | None:
    """A new test function that passes, appended to a test file: the run then has one more passing (new) test, so the
    `tests-ok` state changes while its answer stays yes. None when the file does not parse or defines no test."""
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    if not any(fn.name.startswith("test") for _, fn in _test_nodes(tree)):
        return None
    name = fresh_name(text, variant, "passing")
    value = variant + 2
    return _ensure_newline(text) + f"\n\ndef test_{name}():\n    {name} = {value}\n    assert {name} == {value}\n"
