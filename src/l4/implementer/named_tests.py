"""The existing tests that a task's reviewed text names (L4-IMP-082, design D1 of named-tests).

A red step may change, in place, a test that existed at its base when the text a person reviewed (the task's block, and
the criteria it cites) names that test. Everything here is read at the red step's base commit and the reviewed text;
the Python AST decides what a test is (`tamper.facts_of`).
"""

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from l4.implementer.tamper import facts_of
from l4.security.protected import glob_match
from l4.specs.base import Task

if TYPE_CHECKING:
    from l4.implementer.workbench import Workbench

MAX_NAMED_TESTS = 5
MAX_TEST_FILE_BYTES = 2_000_000

_NODE = re.compile(r"(?<![\w./-])((?:\./)?[\w][\w./-]*\.py)::(\w+)(?:::(\w+))?(?:\[[^\]\s]*\])?")
_BARE = re.compile(r"(?<![\w.:/-])(test_\w+|Test[A-Z]\w*)(?!\w|\.\w)")

Pair = tuple[str, str]


@dataclass(frozen=True)
class NamedTests:
    source: str | None = None  # the source of named_task_text, None: nothing reviewed
    tests: tuple[Pair, ...] = ()  # (path, name), name as tamper.facts_of keys it (`Class.test_x` or `test_x`)
    kept: tuple[Pair, ...] = ()  # (token as written, why it opens nothing)

    def ids(self) -> tuple[str, ...]:
        """The test ids `module.dotted[.Class]::function` (the form `tamper.names_test_id` reads)."""
        found: list[str] = []
        for path, name in self.tests:
            module = path.removesuffix(".py").replace("/", ".")
            owner, _, function = name.rpartition(".")
            found.append(f"{module}{'.' + owner if owner else ''}::{function}")
        return tuple(found)


def _tests_of(source: str) -> dict[str, str] | None:
    """test key -> its last name part, for the tests (functions) of a file; None when it does not parse."""
    facts = facts_of(source)
    if facts is None:
        return None
    return {name: name.rsplit(".", 1)[-1] for name, f in facts.items() if f.test}


def _classes_of(source: str) -> set[str]:
    return {name.split(".", 1)[0] for name in (_tests_of(source) or {}) if "." in name}


def find_named(texts: Sequence[str], files: Mapping[str, str]) -> tuple[tuple[Pair, ...], tuple[Pair, ...]]:
    """(tests, kept) the `texts` name among `files` ({path: source at the base}). Pure. A token that matches nothing is
    ignored; an ambiguous bare name and every test beyond `MAX_NAMED_TESTS` are kept with their reason."""
    parsed = {path: tests for path, source in files.items() if (tests := _tests_of(source)) is not None}
    classes = {path: _classes_of(source) for path, source in files.items() if path in parsed}
    named: set[Pair] = set()
    kept: list[Pair] = []

    def keep(token: str, why: str) -> None:
        if (token, why) not in kept:
            kept.append((token, why))

    text = "\n".join(texts)
    for found in _NODE.finditer(text):
        path = found.group(1).removeprefix("./")
        first, second = found.group(2), found.group(3)
        if path not in parsed:
            continue
        tests = parsed[path]
        if second is not None:
            key = f"{first}.{second}"
            if key in tests:
                named.add((path, key))
        elif first in tests:
            named.add((path, first))
        elif first in classes[path]:
            named.update((path, k) for k in tests if k.startswith(f"{first}."))
    for found in _BARE.finditer(text):
        token = found.group(1)
        hits = [path for path, tests in parsed.items() if any(last == token for last in tests.values())]
        owners = [path for path in parsed if token in classes[path]]
        where = sorted({*hits, *owners})
        if len(where) > 1:
            keep(token, f"named in {len(where)} test files: write <path>::{token}")
        elif where:
            path = where[0]
            named.update((path, k) for k, last in parsed[path].items() if last == token or k.startswith(f"{token}."))
    ordered = sorted(named)
    for path, name in ordered[MAX_NAMED_TESTS:]:
        keep(f"{path}::{name}", f"more than {MAX_NAMED_TESTS} existing tests named")
    return tuple(ordered[:MAX_NAMED_TESTS]), tuple(kept)


def _reviewed_criteria(wb: "Workbench", task: Task, source: str) -> list[str]:
    """The texts of the criteria the task cites explicitly, when they are as reviewed as the task's own block: the
    source is an activated plan's digest, or the unit folder is the same on the base branch."""
    from l4.implementer.tdd import cited_criteria  # tdd imports this module
    from l4.specs.criteria import linked_criteria, own_criteria
    from l4.yolo.digest import unit_digest

    if not task.links:
        return []
    if not source.startswith("plan:"):
        ref = f"refs/remotes/origin/{wb.cfg.forge.base_branch}"
        try:
            if unit_digest(wb.git, "HEAD", wb.unit_rel) != unit_digest(wb.git, ref, wb.unit_rel):
                return []
        except Exception:  # a missing revision or folder: the criteria are not shown to be reviewed
            return []
    if not cited_criteria(wb.provider, wb.ref, task.links):
        return []
    return [f"{c.alias}\n{c.text}" for c in linked_criteria(own_criteria(wb.provider, wb.ref), task.links)]


def _candidate_files(wb: "Workbench", base: str, text: str) -> dict[str, str]:
    listing = wb.git.run("ls-tree", "-r", base, check=False).stdout.splitlines()
    globs = wb.cfg.tdd.test_globs
    blobs: dict[str, str] = {}
    for row in listing:
        meta, _, path = row.partition("\t")
        mode, kind, blob = (meta.split() + ["", "", ""])[:3]
        regular = kind == "blob" and mode in ("100644", "100755") and path.endswith(".py")
        if regular and any(glob_match(g, path) for g in globs):
            blobs[path] = blob
    wanted = {m.group(1).removeprefix("./") for m in _NODE.finditer(text)}
    tokens = sorted({m.group(1) for m in _BARE.finditer(text)})
    if tokens:  # a bare name can be defined in any test file: only the files that hold the word are read
        args = [a for t in tokens for a in ("-e", t)]
        found = wb.git.run("grep", "-l", "-F", *args, base, "--", check=False).stdout.splitlines()
        wanted |= {line.removeprefix(f"{base}:") for line in found}
    files: dict[str, str] = {}
    for path in sorted(wanted & set(blobs)):
        data = wb.git.run_bytes("cat-file", "blob", blobs[path], check=False)
        if len(data) <= MAX_TEST_FILE_BYTES:
            files[path] = data.decode("utf-8", errors="replace")
    return files


def named_tests(wb: "Workbench", task: Task, base: str) -> NamedTests:
    """The existing tests the reviewed text of `task` names, as they are at `base`. Nothing for a task without reviewed
    text (a fix unit, a text only the unit branch has)."""
    from l4.implementer.tdd import named_task_text  # tdd imports this module

    reviewed = named_task_text(wb, task)
    if reviewed is None:
        return NamedTests()
    source, block = reviewed
    texts = [block, *_reviewed_criteria(wb, task, source)]
    joined = "\n".join(texts)
    if "::" not in joined and not _BARE.search(joined):
        return NamedTests(source)
    tests, kept = find_named(texts, _candidate_files(wb, base, joined))
    return NamedTests(source, tests, kept)
