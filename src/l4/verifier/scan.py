"""Source scans of step 1 (SPEC 10.2), Python only and pure: they take text and return what they found.

- `result_hooks`: pytest hooks that decide what a test run reports (2.6);
- `addopts_added`: runner options that select or hide tests (2.6);
- `skip_markers` and `defined_tests`: what the unit did to pre-existing tests (2.4);
- `suppressions_in`: inline suppression comments (2.10); `task_tags`: the human tags of a task title.
A source that does not parse yields nothing: a syntax error is a failure of the build and test gates, not of a scan.
M1: verifier 2.7 (support files that patch the unit's own symbols), jest/vitest/Playwright/Go equivalents.
"""

import ast
import re
from collections import Counter
from collections.abc import Collection, Iterator
from dataclasses import dataclass

_REPORT_HOOKS = ("pytest_runtest_makereport", "pytest_report_teststatus", "pytest_runtest_logreport")
_WRAPPED_HOOKS = ("pytest_runtest_call", "pytest_runtest_protocol")
_DESELECTING_CALLS = ("remove", "pop", "clear", "pytest_deselected")
_SKIP_MARK = re.compile(
    r"(?:^|\.)mark\.(?:skip|skipif|xfail)\b|\bunittest\.(?:skip|skipIf|skipUnless|expectedFailure)\b"
)
_SKIP_CALL = re.compile(r"^(?:pytest\.(?:skip|xfail)|[\w.]*\.skipTest)$")
_TAG = re.compile(r"\[([A-Za-z][A-Za-z-]*)\]")
_RISKY_OPTIONS = ("-p", "--deselect", "-k", "--ignore")  # `--ignore` also covers `--ignore-glob`


def _parse(source: str) -> ast.Module | None:
    try:
        return ast.parse(source)
    except (SyntaxError, ValueError, MemoryError, RecursionError):
        return None


def _functions(tree: ast.AST) -> Iterator[ast.FunctionDef | ast.AsyncFunctionDef]:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            yield node


def _is_wrapper(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for decorator in function.decorator_list:
        if isinstance(decorator, ast.Call) and "hookimpl" in ast.unparse(decorator.func):
            wrapped = (k for k in decorator.keywords if k.arg in ("hookwrapper", "wrapper"))
            if any(ast.unparse(k.value) != "False" for k in wrapped):
                return True
    return False


def _deselects(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    args = function.args.args
    items = args[-1].arg if args else "items"
    for node in ast.walk(function):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in _DESELECTING_CALLS:
                return True
            if node.func.attr == "add_marker" and re.search(r"skip|xfail", ast.unparse(node)):
                return True
        targets = node.targets if isinstance(node, ast.Assign | ast.Delete) else []
        if any(isinstance(t, ast.Subscript) and ast.unparse(t.value) == items for t in targets):
            return True
    return False


def result_hooks(source: str) -> list[str]:
    """The result-manipulating constructs a conftest or plugin source contains, one short description each."""
    tree = _parse(source)
    if tree is None:
        return []
    found: list[str] = []
    for function in _functions(tree):
        if function.name in _REPORT_HOOKS:
            found.append(f"{function.name}: rewrites what the run reports")
        elif function.name == "pytest_collection_modifyitems" and _deselects(function):
            found.append("pytest_collection_modifyitems: removes or skips collected tests")
        elif function.name in _WRAPPED_HOOKS and _is_wrapper(function):
            found.append(f"{function.name}: a hook wrapper around the test call")
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Attribute) and t.attr == "exitstatus" for t in node.targets
        ):
            found.append("assignment to exitstatus: decides the exit code of the run")
    return found


_HARNESS_PLUGINS = ("l4_trace", "l4_cov")
_COVERAGE_MODULE = "coverage"  # the plugin imports the project's coverage.py by this name
_MODULE_SUFFIXES = (".py", ".pyc", ".pyo", ".pyw", ".so", ".pyd")
_COVERAGE_REFS = re.compile(r"l4_cov|L4_COV|\.l4-out\b[^\n]*?\bcov\b")  # the output dir: `.l4-out`, `cov`, one line


def plugin_module(path: str, roots: Collection[str] = ()) -> str | None:
    """The harness plugin (`l4_trace`, `l4_cov`), or coverage.py, that a repository file would provide on `sys.path`:
    a module file of any importable suffix (`l4_cov.py`, `l4_cov.cpython-312-x86_64-linux-gnu.so`) or a package's
    `__init__`. The gate runs `python -m pytest` from the root, so a root module is imported in place of the harness's
    own. `coverage` counts only at the top level (the root, or directly under one of `roots`, which an ini `pythonpath`
    puts on `sys.path`): `src/shop/coverage.py` is a submodule, not coverage.py."""
    parts = path.split("/")
    name = parts[-1]
    package = name.startswith("__init__.") and len(parts) > 1
    if package:
        name, parts = parts[-2], parts[:-1]
    elif not name.endswith(_MODULE_SUFFIXES):
        return None
    module = name.split(".", 1)[0]
    if module in _HARNESS_PLUGINS:
        return module
    top_level = len(parts) == 1 or (len(parts) == 2 and parts[0] in roots)
    return module if module == _COVERAGE_MODULE and top_level else None


def coverage_refs(source: str) -> list[str]:
    """The mentions of the coverage plugin (`l4_cov`, `L4_COV_*`) and of its output directory (`.l4-out/cov`, also
    written as `.l4-out` and `cov` on one line) in a source text (M1.6). Project code has no reason to name them, and
    code that does can rewrite the diff-coverage evidence after the plugin wrote it; other files under `.l4-out` (a
    serve wrapper's pid file, a JUnit path) are not the coverage output. Text, not AST: a string, a comment and an
    import all count. A name assembled at run time or across lines is not seen: this narrows the SC-03-class hole of
    m16-plan's Risks section, it does not close it."""
    found = {m.group(0) for m in _COVERAGE_REFS.finditer(source)}
    return sorted({".l4-out/cov" if ref.startswith(".") else ref for ref in found})


def addopts_added(before: str, after: str) -> list[str]:
    """The `addopts` options (`-p`, `--deselect`, `-k`, `--ignore...`) that `after` has and `before` did not.
    Both are the text of one runner config file (ini, cfg or the pyproject text): every line that reads
    `addopts` is looked at, a TOML list or string alike."""

    def options(text: str) -> Counter[str]:
        found: Counter[str] = Counter()
        reading = False
        for line in text.splitlines():
            if "addopts" in line:
                reading, rest = True, line.split("addopts", 1)[1]
            elif reading and line[:1] in (" ", "\t", "]"):  # a continued value (ini) or a TOML list
                rest = line
            else:
                reading = False
                continue
            for token in re.findall(r"""[^\s"',=\[\]]+(?:=[^\s"',\[\]]+)?""", rest):
                name = token.split("=", 1)[0]
                if name in _RISKY_OPTIONS or name.startswith(("--deselect", "--ignore", "-p", "-k")):
                    found[token] += 1
        return found

    return sorted((options(after) - options(before)).elements())


def _qualified(tree: ast.Module) -> Iterator[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
    """Module-level functions and the methods of module-level classes, with their dotted names."""
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            yield node.name, node
        elif isinstance(node, ast.ClassDef):
            for member in node.body:
                if isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef):
                    yield f"{node.name}.{member.name}", member


def defined_tests(source: str) -> set[str]:
    tree = _parse(source)
    if tree is None:
        return set()
    return {name for name, _ in _qualified(tree) if name.rsplit(".", 1)[-1].startswith("test")}


def _skips_in(node: ast.AST) -> int:
    count = 0
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call) and _SKIP_CALL.match(ast.unparse(sub.func)):
            count += 1
    return count


def skip_markers(source: str) -> Counter[str]:
    """Per test (and `<module>` for module-wide ones) how many skip, skipif and xfail markers or calls it carries."""
    tree = _parse(source)
    found: Counter[str] = Counter()
    if tree is None:
        return found
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(ast.unparse(t) == "pytestmark" for t in node.targets):
            found["<module>"] += len(_SKIP_MARK.findall(ast.unparse(node.value)))
        elif isinstance(node, ast.Expr):
            found["<module>"] += _skips_in(node)
    for name, function in _qualified(tree):
        marks = sum(len(_SKIP_MARK.findall(ast.unparse(d))) for d in function.decorator_list)
        found[name] += marks + _skips_in(function)
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            found[node.name] += sum(len(_SKIP_MARK.findall(ast.unparse(d))) for d in node.decorator_list)
    return +found  # drops the zero counts


@dataclass(frozen=True)
class Suppression:
    kind: str  # one of the four names in _PATTERNS
    text: str  # the comment as written


_PATTERNS = (
    ("noqa", re.compile(r"#\s*noqa\b(?::\s*[A-Za-z0-9_, ]+)?", re.IGNORECASE)),
    ("type-ignore", re.compile(r"#\s*type:\s*ignore\b(?:\[[^\]]*\])?")),
    ("nosec", re.compile(r"#\s*nosec\b(?:\s+B\d+)?", re.IGNORECASE)),
    ("gitleaks", re.compile(r"gitleaks:allow")),
)


def suppressions_in(line: str) -> list[Suppression]:
    return [Suppression(kind, m.group(0).strip()) for kind, pattern in _PATTERNS for m in pattern.finditer(line)]


@dataclass(frozen=True)
class AddedLine:
    path: str
    number: int
    text: str


def added_lines(diff: str) -> list[AddedLine]:
    """The added lines of a `git diff -U0` text, with their line numbers in the new file."""
    found: list[AddedLine] = []
    path, number = "", 0
    for line in diff.splitlines():
        if line.startswith("+++ "):
            target = line[4:].split("\t", 1)[0]
            path = "" if target == "/dev/null" else target.removeprefix("b/")
        elif line.startswith("@@"):
            match = re.match(r"@@ -\S+ \+(\d+)", line)
            number = int(match.group(1)) if match else 0
        elif line.startswith("+") and path:
            found.append(AddedLine(path, number, line[1:]))
            number += 1
    return found


def task_tags(title: str) -> frozenset[str]:
    """The `[docs]`, `[config]`, `[test-infra]` ... tags a task title carries (lower case)."""
    return frozenset(m.group(1).lower() for m in _TAG.finditer(title))
