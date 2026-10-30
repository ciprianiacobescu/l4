"""A task that delivers documentation which a test glob covers (test-path-intake D1; L4-YOLO-094).

The freeze restores every write to a path under `tdd.test_globs` or `tdd.test_support_globs` after green, so a task that
tells the implementer to write `docs/x/fixtures/a.json` (documentation, a scope-exempt path, that a default glob
`**/fixtures/**` also covers) cannot finish. Every input is known before the first run: the task's text and the
effective globs. `test_path_named` reads a unit's tasks (and nothing else) and gives warnings only; it never refuses a
unit. The match is the freeze's own (`guards._matches`), so intake and freeze cannot disagree.

A finding needs all of: a pending required task without the human `[test-infra]` tag, a path-like token of the task's
own text, a test or support glob that matches it, a scope-exempt glob that matches it, and no negation word before the
token on its line. A directory token (no extension, or a trailing `/`: a glob token like `docs/x/*.json` reads as its
directory) counts as a file directly in it.
"""

from collections.abc import Sequence
from typing import TYPE_CHECKING, NamedTuple

from l4.implementer.guards import _matches
from l4.specs.base import UnitRef
from l4.specs.paths import named_paths
from l4.verifier.scan import has_human_tag
from l4.yolo.forbidden import _ANY_PATH, PathFinding, _file_like, _host_like, _negated, _pending, _read

if TYPE_CHECKING:
    from l4.config.schema import L4Config

CODE = "test_path"
_DIRECTORY_FILE = "_"  # the name of the file "directly in" a directory token that the globs are tried on


class PathGlobs(NamedTuple):
    """The globs of one config that the rule reads: `tdd.test_globs`, `tdd.test_support_globs` (the `extra_` lists
    already merged) and `verifier.evidence.scope_exempt`."""

    test: Sequence[str]
    support: Sequence[str]
    exempt: Sequence[str]

    @classmethod
    def of(cls, cfg: "L4Config") -> "PathGlobs":
        return cls(cfg.tdd.test_globs, cfg.tdd.test_support_globs, cfg.verifier.evidence.scope_exempt)


def _fix(path: str) -> str:
    return (
        f"have a person tag the task [test-infra] (the freeze then lets it write {path}), or leave the glob out of "
        "tdd.test_globs and tdd.test_support_globs in .l4/config.yaml on the base branch"
    )


def _first(globs: Sequence[str], probe: str) -> str | None:
    """The first of `globs` that the freeze's matcher matches against `probe`."""
    return next((glob for glob in globs if _matches((glob,), probe)), None)


def test_path_named(
    ref: UnitRef,
    test_globs: Sequence[str],
    support_globs: Sequence[str],
    exempt_globs: Sequence[str],
) -> list[PathFinding]:
    """The warnings of `ref`'s pending tasks against the effective `tdd.test_globs`, `tdd.test_support_globs` and the
    scope-exempt globs (`verifier.evidence.scope_exempt`). At most one finding per task and path."""
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
            for path in named_paths(line, _ANY_PATH):
                if ".." in path.split("/") or path in seen or _host_like(path) or _negated(line, path):
                    continue
                seen.add(path)
                probe = path if _file_like(path) else f"{path.rstrip('/')}/{_DIRECTORY_FILE}"
                if _first(exempt_globs, probe) is None:
                    continue
                kind, rule = next(
                    (
                        (k, g)
                        for k, gs in (("test", test_globs), ("test support", support_globs))
                        if (g := _first(gs, probe))
                    ),
                    (None, None),
                )
                if rule is None:
                    continue
                body = (
                    f"task {task.key} names {path}, which the {kind} glob {rule} matches although it is documentation "
                    f"(a scope-exempt path): the test path freeze restores every write to it after red. "
                    f"Fix: {_fix(path)}."
                )
                found.append(PathFinding(False, path, rule, body, CODE))
    return found
