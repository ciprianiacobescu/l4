"""Browser tests of a task (L4-IMP-101): which test functions pytest would collect, which ids of the e2e report are
theirs, and when the e2e command cannot be judged by the module and function of a test.

Plain data and the AST, no harness state. The tamper guard's `names_test_id` and `facts_of` stay as they are: they
protect a test by suffix and by name, and what this module decides is only whether a *report* names a test."""

import ast
import fnmatch
import shlex
from collections.abc import Collection, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from l4.evidence.testsran import file_of_test

PYTEST_FILE_GLOBS = ("test_*.py", "*_test.py")  # pytest's default `python_files`


def is_pytest_file(path: str) -> bool:
    """A path whose name matches pytest's default `python_files`."""
    name = PurePosixPath(path).name
    return any(fnmatch.fnmatchcase(name, glob) for glob in PYTEST_FILE_GLOBS)


def _is_fixture(node: ast.AST) -> bool:
    """A function decorated as a pytest fixture (`pytest.fixture`, `fixture(...)`, `pytest_asyncio.fixture`)."""
    if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
        return False
    for decorator in node.decorator_list:
        name = ast.unparse(decorator.func if isinstance(decorator, ast.Call) else decorator)
        if name == "fixture" or name.endswith(".fixture"):
            return True
    return False


def _functions(body: Iterable[ast.stmt]) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    """The functions a scope binds by `def`, the last binding of a name winning."""
    found: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for node in body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            found[node.name] = node
    return found


def collectable_tests(source: str) -> frozenset[str]:
    """The names (the keys of `tamper.facts_of`: `test_x`, `TestA.test_x`) of the tests pytest would collect from a
    module with its default settings: the module-level `def test*` / `async def test*` that is not a fixture, and the
    `test*` methods of module-level classes named `Test*` with no `__init__` (their own or an in-file base's; a base
    imported from elsewhere cannot be read and counts as having none). A fixture or a helper that only happens to start
    with `test` is no test. A source that does not parse gives none."""
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return frozenset()
    found: set[str] = {
        name for name, node in _functions(tree.body).items() if name.startswith("test") and not _is_fixture(node)
    }
    classes = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}  # the last definition wins

    def chain(name: str, seen: list[str]) -> list[str]:
        if name not in seen:
            seen.append(name)
            for base in classes[name].bases:
                if isinstance(base, ast.Name) and base.id in classes:
                    chain(base.id, seen)
        return seen

    for name in classes:
        if not name.startswith("Test"):
            continue
        members = chain(name, [])
        if any("__init__" in _functions(classes[m].body) for m in members):
            continue  # pytest does not collect a class that has an `__init__`
        owner: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
        for member in members:
            for method, node in _functions(classes[member].body).items():
                owner.setdefault(method, node)
        found |= {f"{name}.{m}" for m, node in owner.items() if m.startswith("test") and not _is_fixture(node)}
    return frozenset(found)


def selecting_option(command: str) -> str | None:
    """`-m` or `-k` when the e2e command selects tests with it after its `pytest` word (`pytest e2e -m browser`,
    `-k "not slow"`, `-mbrowser`), else None: the report then holds only part of what its directory holds."""
    try:
        words = shlex.split(command)
    except ValueError:
        return None
    start = next((i for i, w in enumerate(words) if PurePosixPath(w).name == "pytest"), None)
    for word in words[start + 1 :] if start is not None else ():
        if word.startswith("-") and not word.startswith("--") and word[1:2] in ("m", "k"):
            return word[:2]
    return None


def _class_of(classname: str) -> str:
    """The class between module and function of a JUnit classname: its trailing capitalised parts (`Outer.Inner`)."""
    parts = classname.split(".")
    tail: list[str] = []
    while parts and parts[-1][:1].isupper():
        tail.append(parts.pop())
    return ".".join(reversed(tail))


def _function_of(test_id: str) -> str:
    return test_id.rpartition("::")[2].split("[", 1)[0]


@dataclass
class TaskMatch:
    """The ids of an e2e report that belong to a task's browser tests. `found`: `(path, name)` -> its ids; a test with
    no entry was not seen. `ambiguous`: report ids that name a test function of a task's module but whose module two
    files of the tree both fit (a rootdir below the repository root), left out rather than guessed."""

    found: dict[tuple[str, str], list[str]] = field(default_factory=dict)
    ambiguous: list[str] = field(default_factory=list)


def _suffix_files(parts: Sequence[str], files: Collection[str]) -> list[str]:
    """Every file of `files` whose path is the module path `parts` or ends with it after a `/`."""
    path = "/".join(parts) + ".py"
    return sorted(f for f in files if f == path or f.endswith("/" + path))


def _module_parts(classname: str) -> list[str]:
    parts = classname.split(".")
    cls = _class_of(classname)
    return parts[: len(parts) - len(cls.split("."))] if cls else parts


def match_task_tests(report_ids: Iterable[str], tests: Sequence[tuple[str, str]], files: Collection[str]) -> TaskMatch:
    """Which report ids are the ids of `tests` (`(path, name)` pairs; `name` is `test_x` or `Class.test_x`). The module
    of an id is resolved as `evidence.testsran.file_of_test` does for a JUnit id: the exact path wins, else the one file
    of `files` (every Python file of the tree) whose path ends with the module path, since pytest writes the classname
    from its rootdir (`test_layout`, not `e2e.test_layout`, under an `e2e/pytest.ini`). When two files fit, the id is
    left out and listed in `ambiguous` (when it names a test of the task), not guessed. The class must be the test's
    own class (a plain function has none), so `TestA::test_x` is never the id of `TestB.test_x`; the function name ends
    at a `[param]` suffix."""
    tree = frozenset(files)
    out = TaskMatch()
    resolutions: dict[str, str | None] = {}  # a report holds many ids of one module
    for test_id in sorted(set(report_ids)):
        classname = test_id.rpartition("::")[0]
        function, cls = _function_of(test_id), _class_of(classname)
        if not function or not classname:
            continue
        if classname not in resolutions:
            resolutions[classname] = file_of_test(classname, tree, tree)
        resolved = resolutions[classname]
        hits = [resolved] if resolved is not None else _suffix_files(_module_parts(classname), tree)
        listed = False
        for path, name in tests:
            owner, _, base = name.rpartition(".")
            if owner != cls or base != function or path not in hits:
                continue
            if resolved is not None:
                out.found.setdefault((path, name), []).append(test_id)
            elif not listed:
                out.ambiguous.append(test_id)  # two files fit the module of the id: not guessed
                listed = True
    return out


def module_files(names: Iterable[str], files: Collection[str]) -> dict[str, str | None]:
    """The file of each dotted module name of a collection error, None when it is not one file of the tree."""
    tree = frozenset(files)
    return {name: file_of_test(name, tree, tree) for name in names}


def shared_with_unit_gate(directory: str, unit_ids: Iterable[str], files: Collection[str]) -> list[str]:
    """The ids of the unit gate's report that lie in `directory`: tests the unit gate runs and the e2e command would run
    again, so every test of the directory is not a browser test. The module of an id is resolved once per classname."""
    tree = frozenset(files)
    prefix = directory.strip("/") + "/"
    resolved: dict[str, str | None] = {}
    found = []
    for test_id in unit_ids:
        classname = test_id.split("::", 1)[0]
        if classname not in resolved:
            resolved[classname] = file_of_test(classname, tree, tree)
        file = resolved[classname]
        if file is not None and file.startswith(prefix):
            found.append(test_id)
    return sorted(found)
