"""A task that delivers documentation which a test glob covers (test-path-intake D1; L4-YOLO-094).

The freeze restores every write to a path under `tdd.test_globs` or `tdd.test_support_globs` after green, so a task that
tells the implementer to write `docs/x/fixtures/a.json` (documentation, a scope-exempt path, that a default glob
`**/fixtures/**` also covers) cannot finish. Every input is known before the first run: the task's text and the
effective globs. `test_path_named` reads a unit's tasks (and nothing else) and gives warnings only; it never refuses a
unit. The match is the freeze's own (`guards._matches`), so intake and freeze cannot disagree.

A finding needs all of: a pending required task without the human `[test-infra]` tag, a path-like token of the task's
own text that is not source code (an extension in `evidence.diffcov.CODE_SUFFIXES`: test code under `docs/` is red's
work), a test or support glob that matches it, a scope-exempt glob that matches it, and no negation word before the
token on its line. The finding names every glob of the two lists that matches. A directory token (no extension) counts
as a file directly in it; a glob token with a file pattern (`docs/x/fixtures/*.json`) is shown as its directory and
probed as a file with that pattern (`docs/x/fixtures/_.json`).
"""

import re
from collections.abc import Iterator, Sequence
from typing import TYPE_CHECKING, NamedTuple

from l4.implementer.guards import _matches
from l4.specs.base import UnitRef
from l4.specs.paths import is_code_file, named_paths
from l4.verifier.scan import has_human_tag
from l4.yolo.forbidden import _ANY_PATH, PathFinding, _file_like, _host_like, _negated, _pending, _read

if TYPE_CHECKING:
    from l4.config.schema import L4Config

CODE = "test_path"
_DIRECTORY_FILE = "_"  # the name of the file "directly in" a directory token that the globs are tried on
# a glob token with a file pattern: `docs/x/fixtures/*.json`, `./docs/x/test_*.md` (the directory, then the pattern)
_GLOB_TOKEN = re.compile(r"(?<![\w./*-])(?:\./)?((?:[\w.-]+/)+)([\w.-]*\*[\w.*-]*)(?![\w/])")


class PathGlobs(NamedTuple):
    """The globs of one config that the rule reads: `tdd.test_globs`, `tdd.test_support_globs` (the `extra_` lists
    already merged) and `verifier.evidence.scope_exempt`."""

    test: Sequence[str]
    support: Sequence[str]
    exempt: Sequence[str]

    @classmethod
    def of(cls, cfg: "L4Config") -> "PathGlobs":
        return cls(cfg.tdd.test_globs, cfg.tdd.test_support_globs, cfg.verifier.evidence.scope_exempt)


def _fix(path: str, *, one: bool) -> str:
    return (
        f"have a person tag the task [test-infra] (the freeze then lets it write {path}), or leave "
        f"{'the glob' if one else 'all of them'} out of "
        "tdd.test_globs and tdd.test_support_globs in .l4/config.yaml on the base branch"
    )


def _matching(globs: Sequence[str], probe: str) -> list[str]:
    """Every one of `globs` that the freeze's matcher matches against `probe`, in list order."""
    return [glob for glob in globs if _matches((glob,), probe)]


def _tokens(line: str) -> Iterator[tuple[str, str, str]]:
    """`(shown, probe, written)` for each path the line names: a glob token with a file pattern is shown as its
    directory and probed as a file with that pattern (`*` read as `_`); any other path-like token is probed as written,
    a directory token (no extension) as a file directly in it."""
    rest = line
    for match in _GLOB_TOKEN.finditer(line):
        folder, tail = match.group(1), match.group(2)
        rest = rest.replace(match.group(0), " " * len(match.group(0)), 1)
        yield folder, folder + tail.replace("*", "_"), match.group(0).removeprefix("./")
    for path in named_paths(rest, _ANY_PATH):
        probe = path if _file_like(path) else f"{path.rstrip('/')}/{_DIRECTORY_FILE}"
        yield path, probe, path


def test_path_named(
    ref: UnitRef,
    test_globs: Sequence[str],
    support_globs: Sequence[str],
    exempt_globs: Sequence[str],
) -> list[PathFinding]:
    """The warnings of `ref`'s pending tasks against the effective `tdd.test_globs`, `tdd.test_support_globs` and the
    scope-exempt globs (`verifier.evidence.scope_exempt`). A finding names every glob of the two lists that matches, so
    removing one leaves no other in the way. At most one finding per task and path."""
    if not exempt_globs or not (test_globs or support_globs):
        return []
    data = _read(ref.path / "tasks.md")
    if data is None:
        return []
    found: list[PathFinding] = []
    for task, text in _pending(ref, data):
        if has_human_tag(ref.path, task.title, "test-infra"):
            continue
        seen: set[str] = set()
        for line in text.splitlines():
            for path, probe, written in _tokens(line):
                if ".." in path.split("/") or path in seen or _host_like(path) or _negated(line, written):
                    continue
                seen.add(path)
                if is_code_file(probe) or not _matching(exempt_globs, probe):
                    continue  # test code under docs/ is not documentation; so is no path an exempt glob misses
                by_test = _matching(test_globs, probe)
                by_support = [g for g in _matching(support_globs, probe) if g not in by_test]
                rules = [*by_test, *by_support]
                if not rules:
                    continue
                kind = "test and test support" if by_test and by_support else "test" if by_test else "test support"
                one = len(rules) == 1
                body = (
                    f"task {task.key} names {path}, which the {kind} {'glob' if one else 'globs'} {', '.join(rules)} "
                    f"{'matches' if one else 'match'} although it is documentation (a scope-exempt path): the test "
                    f"path freeze restores every write to it after red. Fix: {_fix(path, one=one)}."
                )
                found.append(PathFinding(False, path, ", ".join(rules), body, CODE))
    return found


test_path_named.__test__ = False  # type: ignore[attr-defined]  # not a pytest test
