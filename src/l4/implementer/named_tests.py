"""The existing tests that a task's reviewed text names (L4-IMP-082, design D1 of named-tests).

A red step may change, in place, a test that existed at its base when the text a person reviewed (the task's block, and
the criteria it cites) names that test. Everything here is read at the red step's base commit and the reviewed text;
the Python AST decides what a test is (`tamper.facts_of`). A test of another language is named by a backticked
`<path>::<name>` and resolved against the base report (L4-IMP-089, design D1 of named-test-any-language).
"""

import re
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from l4.gates.junit import TestReport
from l4.implementer.guards import IGNORE_FILE_GLOBS
from l4.implementer.tamper import facts_of
from l4.implementer.test_locate import file_of_id, window
from l4.security.protected import glob_match
from l4.specs.base import Task

if TYPE_CHECKING:
    from l4.implementer.workbench import Workbench

MAX_NAMED_TESTS = 5
MAX_TEST_FILE_BYTES = 2_000_000

_NODE = re.compile(r"(?<![\w./-])((?:\./)?[\w][\w./-]*\.py)::(\w+)(?:::(\w+))?(?:\[[^\]\s]*\])?")
_BARE = re.compile(r"(?<![\w.:/-])(test_\w+|Test[A-Z]\w*)(?!\w|\.\w)")
# a whole backticked `<path>::<name>`: the path has no space, the name is every character up to the closing backtick
_OTHER = re.compile(r"`((?:\./)?[^`\s:]+)::([^`]+)`")
_LANGUAGES = {
    ".ts": "typescript", ".tsx": "typescript", ".mts": "typescript", ".cts": "typescript",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".go": "go", ".rs": "rust", ".java": "java", ".kt": "kotlin", ".cs": "csharp", ".rb": "ruby", ".php": "php",
    ".swift": "swift", ".scala": "scala", ".dart": "dart", ".ex": "elixir", ".exs": "elixir",
}  # fmt: skip

Pair = tuple[str, str]


def language_of(path: str) -> str:
    """The language of a test file by its suffix: `typescript` for `.ts`; the suffix itself when it is not listed."""
    suffix = PurePosixPath(path).suffix.lower()
    return _LANGUAGES.get(suffix, suffix.lstrip(".") or "unknown")


def test_id(path: str, name: str) -> str:
    """`module.dotted[.Class]::function` for the test `name` (as `tamper.facts_of` keys it) of the file `path`."""
    module = path.removesuffix(".py").replace("/", ".")
    owner, _, function = name.rpartition(".")
    return f"{module}{'.' + owner if owner else ''}::{function}"


@dataclass(frozen=True)
class NamedTests:
    source: str | None = None  # the source of named_task_text, None: nothing reviewed
    tests: tuple[Pair, ...] = ()  # (path, name), name as tamper.facts_of keys it (`Class.test_x` or `test_x`)
    kept: tuple[Pair, ...] = ()  # (token as written, why it opens nothing)
    other: tuple[Pair, ...] = ()  # (path, report id) of the named tests of other languages (L4-IMP-089)

    def other_ids(self) -> tuple[str, ...]:
        """The report ids of the named tests of other languages."""
        return tuple(test for _, test in self.other)

    def ids(self) -> tuple[str, ...]:
        """The test ids `module.dotted[.Class]::function` (the form `tamper.names_test_id` reads)."""
        return tuple(test_id(path, name) for path, name in self.tests)


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


def _report_name(test: str) -> str:
    return test.partition("::")[2]


def _matches(reported: str, given: str) -> bool:
    """The report's test name is the given name, or ends with it after a describe separator (` > `)."""
    return reported == given or reported.endswith(" > " + given)


def find_named_other(
    texts: Sequence[str], files: Mapping[str, str], ids: Iterable[str], paths: Collection[str] = ()
) -> tuple[tuple[Pair, ...], tuple[Pair, ...]]:
    """(tests, kept) the `texts` name among the tests of other languages. Pure. A token is a whole backticked
    `<path>::<name>` (split at the first `::`; the name may hold spaces, ids and punctuation), whose path is one of
    `files` ({path: source at the base}, the eligible non-Python test files) and is not Python. `ids` are the base
    report's test ids; the ones of the file (`test_locate.file_of_id` over `paths`, default the files) whose name is the
    given one, or ends with it after ` > `, are its matches: exactly one names a test, none or several are kept with
    their reason, and so is a test whose lines (`test_locate.window`) are not found in the file. A path that is not in
    `files` names nothing and is not listed. Returns (path, report id) pairs."""
    known = set(paths) | set(files)
    reported = list(ids)
    named: dict[str, Pair] = {}
    kept: list[Pair] = []
    for found in _OTHER.finditer("\n".join(texts)):
        path, given = found.group(1).removeprefix("./"), found.group(2).strip()
        if path.endswith(".py") or path not in files or not given:
            continue
        token = f"{path}::{given}"
        hits = [t for t in reported if _matches(_report_name(t), given) and file_of_id(t, known) == path]
        if len(hits) > 1:
            kept.append((token, "more than one test matches"))
        elif not hits:
            kept.append((token, "no test of that name in the base report"))
        elif window(files[path], _report_name(hits[0])) is None:
            kept.append((token, f"the lines of the test are not found in {path}"))
        else:
            named[hits[0]] = (path, hits[0])
    return tuple(sorted(named.values())), tuple(dict.fromkeys(kept))


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


def _other_files(wb: "Workbench", base: str, text: str) -> tuple[dict[str, str], set[str]]:
    """({path: source at the base}, every regular path) for the files a backticked `<path>::<name>` of `text` names that
    are tracked, regular, not Python, in `tdd.test_globs` and in no support or ignore glob (L4-IMP-089)."""
    listing = wb.git.run("ls-tree", "-r", base, check=False).stdout.splitlines()
    tdd = wb.cfg.tdd
    skip = (*tdd.test_support_globs, *IGNORE_FILE_GLOBS)
    blobs: dict[str, str] = {}
    regular: set[str] = set()
    for row in listing:
        meta, _, path = row.partition("\t")
        mode, kind, blob = (meta.split() + ["", "", ""])[:3]
        if kind == "blob" and mode in ("100644", "100755"):
            regular.add(path)
            listed = not path.endswith(".py") and any(glob_match(g, path) for g in tdd.test_globs)
            if listed and not any(glob_match(g, path) for g in skip):
                blobs[path] = blob
    wanted = {m.group(1).removeprefix("./") for m in _OTHER.finditer(text)} & set(blobs)
    files: dict[str, str] = {}
    for path in sorted(wanted):
        data = wb.git.run_bytes("cat-file", "blob", blobs[path], check=False)
        if len(data) <= MAX_TEST_FILE_BYTES:
            files[path] = data.decode("utf-8", errors="replace")
    return files, regular


def named_tests(wb: "Workbench", task: Task, base: str, base_report: TestReport | None = None) -> NamedTests:
    """The existing tests the reviewed text of `task` names, as they are at `base`. Nothing for a task without reviewed
    text (a fix unit, a text only the unit branch has). `base_report`: the base's test report, against which a
    backticked `<path>::<name>` of a test of another language is resolved (without it none is named)."""
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
    other: tuple[Pair, ...] = ()
    if base_report is not None and _OTHER.search(joined):
        files, regular = _other_files(wb, base, joined)
        other, why = find_named_other(texts, files, base_report.tests, regular)
        kept = (*kept, *why)
        for path, test in other[max(MAX_NAMED_TESTS - len(tests), 0) :]:  # the cap counts both kinds
            kept = (*kept, (f"{path}::{_report_name(test)}", f"more than {MAX_NAMED_TESTS} existing tests named"))
        other = other[: max(MAX_NAMED_TESTS - len(tests), 0)]
    return NamedTests(source, tests, kept, other)
