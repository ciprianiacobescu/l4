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

from l4.config.schema import L4Config
from l4.security.protected import glob_match
from l4.verifier import scan

MODULE = "<module>"

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


def _scopes_of(qualname: str, head: str) -> set[str]:
    """The scopes whose skip constructs can skip `qualname`: itself, its class, the module and every function or method
    of the file that no runner collects as a test (a fixture, whatever its name, a helper, `setUp`, a collection hook):
    the tests share those."""
    scopes = {qualname, MODULE}
    if "." in qualname:
        scopes.add(qualname.split(".", 1)[0])
    return scopes | scan.shared_scopes(head)


def no_skip_added(base: str, head: str, qualname: str, changed: Collection[str], cfg: L4Config) -> bool:
    """Rules (b) and (c): the unit added or changed no skip construct that can affect the test `qualname` of a file
    whose text is `base` at the base and `head` at the head, and changed no test-support or runner-configuration file
    (one that does, whatever the file holds, can skip the test from outside). A source that does not parse, a test that
    was not collected at the base, and a construct added in a scope that can skip the test are False."""
    before, after = scan.skip_constructs(base), scan.skip_constructs(head)
    if before is None or after is None or qualname not in scan.collected_tests(base):
        return False
    scopes = _scopes_of(qualname, head)
    if any(scope in scopes for scope, _ in after - before):  # a multiset difference: a removed skip never counts
        return False
    outside = (*cfg.tdd.test_support_globs, *cfg.tdd.runner_config_files)
    return not any(glob_match(g, p) for p in changed for g in outside)


def skip_predates(
    base: str, head: str, qualname: str, changed: Collection[str], cfg: L4Config, *, skipped_at_base: bool
) -> bool:
    """True when the skip of the test `qualname` predates the unit: `skipped_at_base` (a base report with statuses holds
    the test as skipped, rule (a)) and `no_skip_added` (rules (b) and (c))."""
    return skipped_at_base and no_skip_added(base, head, qualname, changed, cfg)
