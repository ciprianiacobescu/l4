"""Does the skip of an old test predate the unit? (skipped-test-hold D1, L4-VER-092)

The pure part of the rule: the two sources of one test file, the paths the unit changed and what a base report says
about the test go in, a decision comes out. `l4.evidence.collect.skip_predating` reads the blobs from git, asks for the
base report and calls it.

A test's skip predates the unit only when all three hold, and any doubt is False (the skip stays a deterministic
finding):

(a) a base report with statuses (the base's tests on the base's code) holds the test as `skipped`;
(b) the file adds or changes no skip construct in a scope that can affect the test (`scan.skip_constructs`, compared
    at the base and at the head);
(c) the unit changed no file that matches `tdd.test_support_globs` or `tdd.runner_config_files`.

(a) is what ties the skip to the base: the comparison of constructs alone cannot see a marker imported from another
module, a condition that depends on a variable the unit changed, or a base class that is skipped. The report is looked
up only when (b) and (c) hold for at least one test (`BaseLookup`).
"""

from collections.abc import Callable, Collection
from dataclasses import dataclass
from pathlib import PurePosixPath

from l4.config.schema import L4Config
from l4.security.protected import glob_match
from l4.verifier.skipdeps import SkipFacts

MODULE = "<module>"
RUNNER_NAMES = frozenset(
    {
        "conftest.py",
        "pytest.ini",
        ".pytest.ini",
        "pytest.toml",
        ".pytest.toml",
        "pyproject.toml",
        "setup.cfg",
        "tox.ini",
    }
)  # a file of this name changes how the tests run wherever it is

STEP1_SOURCE = "step 1 base run"
EARLIER_SOURCE = "an earlier round's record"
WORKTREE_SOURCE = "a base worktree run"


@dataclass(frozen=True)
class BaseSkips:
    """What a base report with statuses says: the ids it holds as `skipped` (None: there is no such report, and `why`
    says why), and where it came from (`STEP1_SOURCE`, `EARLIER_SOURCE` or `WORKTREE_SOURCE`)."""

    skipped: frozenset[str] | None
    source: str = ""
    why: str = ""


BaseLookup = Callable[[], BaseSkips]  # called at most once per round, and only when a skip could predate the unit


def qualified_name(test_id: str, path: str) -> str | None:
    """The `Name` or `Class.name` of a JUnit id in the file `path` (`tests.test_a.TestK::test_x[1]` in `tests/test_a.py`
    is `TestK.test_x`); None when the id is not one of those two shapes (a nested class, a path that does not fit)."""
    classname, sep, name = test_id.partition("::")
    function = name.split("[", 1)[0]
    if not sep or not function or not path.endswith(".py"):
        return None
    parts = classname.split(".")
    for modules in range(len(parts), 0, -1):
        module = "/".join(parts[:modules]) + ".py"
        if path == module or path.endswith("/" + module):
            classes = parts[modules:]
            if len(classes) > 1:
                return None
            return f"{classes[0]}.{function}" if classes else function
    return None


def _outside(changed: Collection[str], cfg: L4Config) -> bool:
    """Rule (c): the unit changed a file that can skip a test from outside: one that matches `tdd.test_support_globs` or
    `tdd.runner_config_files`, or whose name is one of `RUNNER_NAMES` in any directory (a nested `conftest.py` or
    `pyproject.toml`, which a root-anchored glob does not match). `changed` holds the head path of every change and the
    old path of a rename."""
    globs = (*cfg.tdd.test_support_globs, *cfg.tdd.runner_config_files)
    return any(PurePosixPath(p).name in RUNNER_NAMES or any(glob_match(g, p) for g in globs) for p in changed)


class SkipRule:
    """Rules (b), (c) and (d) for the tests of one file whose text is `base` at the base and `head` at the head: the two
    sources are parsed and scanned once, and each test is asked against the result (`no_skip_added`)."""

    def __init__(self, base: str, head: str, changed: Collection[str], cfg: L4Config) -> None:
        self.outside = _outside(changed, cfg)
        self.before, self.after = SkipFacts(base), SkipFacts(head)

    def no_skip_added(self, qualname: str) -> bool:
        """Rules (b), (c) and (d): the unit added or changed no skip construct that can affect the test `qualname`,
        changed no test-support or runner-configuration file (one that does, whatever the file holds, can skip the test
        from outside), and changed nothing inside the file that decides whether an unchanged construct skips (the
        closure of the test's skip-relevant parts, `skipdeps`). A source that does not parse, a test that was not
        collected at the base or is not in the head, and a construct added in a scope that can skip the test are
        False."""
        before, after = self.before, self.after
        if self.outside or not before.ok or not after.ok or qualname not in before.collected:
            return False
        scopes = {qualname, MODULE, *([qualname.split(".", 1)[0]] if "." in qualname else []), *after.shared}
        if any(scope in scopes for scope, _ in after.constructs - before.constructs):  # a removed skip never counts
            return False
        closure = before.closure(qualname)
        return closure is not None and closure == after.closure(qualname)


def no_skip_added(base: str, head: str, qualname: str, changed: Collection[str], cfg: L4Config) -> bool:
    """`SkipRule(base, head, changed, cfg).no_skip_added(qualname)`, for one test."""
    return SkipRule(base, head, changed, cfg).no_skip_added(qualname)


def skip_predates(
    base: str, head: str, qualname: str, changed: Collection[str], cfg: L4Config, *, skipped_at_base: bool
) -> bool:
    """True when the skip of the test `qualname` predates the unit: `skipped_at_base` (a base report with statuses holds
    the test as skipped, rule (a)) and `no_skip_added` (rules (b) and (c))."""
    return skipped_at_base and no_skip_added(base, head, qualname, changed, cfg)
