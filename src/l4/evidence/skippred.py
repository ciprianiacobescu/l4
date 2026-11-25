"""Does the skip of an old test predate the unit? (skipped-test-hold D1, L4-VER-092)

The pure part of the rule: the two sources of one test file, the paths the unit changed and what a base report says
about the test go in, a decision comes out. `l4.evidence.collect.skip_predating` reads the blobs from git, asks for the
base report and calls it.

A test's skip predates the unit only when all of these hold, and any doubt is False (the skip stays a deterministic
finding):

(a) a base report with statuses (the base's tests on the base's code) holds the test as `skipped`;
(b) the file adds or changes no skip construct in a scope that can affect the test (`scan.skip_constructs`, compared
    at the base and at the head);
(c) the unit changed no file that can skip a test from outside: a support or runner-configuration file (the globs of
    `tdd`, a runner file by name in any directory, a module of the tests tree that defines no test), and no file that
    sets up the interpreter or the dependencies (`sitecustomize.py`, `noxfile.py`, `requirements*.txt`, a lock file);
(d) nothing that decides an unchanged skip changed inside the file (`skipdeps`, the dependency closure);
(e) every changed line of the file is in a place the unit may change (`skipscope`: a comment or blank line, the body of
    a collected test beyond what skips it, a whole new import of a name the base does not use). (b) and (d) list what
    decides a skip; (e) bounds where a change can be, so that a way to change why a test skips that they do not list
    is still out.

(a) is what ties the skip to the base: the comparison of constructs alone cannot see a marker imported from another
module, a condition that depends on a variable the unit changed, or a base class that is skipped. The report is looked
up only when (b) and (c) hold for at least one test (`BaseLookup`).
"""

from collections.abc import Callable, Collection
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import PurePosixPath

from l4.config.schema import L4Config
from l4.evidence.skipscope import Confined, normalized
from l4.security.protected import glob_match
from l4.verifier.skipdeps import SkipFacts
from l4.verifier.support_base import is_support_source

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
        "sitecustomize.py",
        "usercustomize.py",
        "noxfile.py",
        "setup.py",
        "Pipfile",
        "Pipfile.lock",
        "poetry.lock",
        "uv.lock",
        "pdm.lock",
    }
)  # a file of this name changes how the tests run, or what they run against, wherever it is
RUNNER_PATTERNS = ("requirements*.txt", "constraints*.txt")  # matched against the name, in any directory

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


def _outside(changed: Collection[str], cfg: L4Config, support_modules: Collection[str] = ()) -> bool:
    """Rule (c): the unit changed a file that can skip a test from outside: one that matches `tdd.test_support_globs` or
    `tdd.runner_config_files`, or whose name is one of `RUNNER_NAMES` or matches `RUNNER_PATTERNS` in any directory (a
    nested `conftest.py` or `pyproject.toml`, which a root-anchored glob does not match; `sitecustomize.py`, a
    requirements or lock file), or one of `support_modules`. `changed` holds the head path of every change and the old
    path of a rename."""
    globs = (*cfg.tdd.test_support_globs, *cfg.tdd.runner_config_files)
    return bool(support_modules) or any(
        (name := PurePosixPath(p).name) in RUNNER_NAMES
        or any(fnmatchcase(name, pattern) for pattern in RUNNER_PATTERNS)
        or any(glob_match(g, p) for g in globs)
        for p in changed
    )


def support_module(cfg: L4Config, path: str, source: str | None) -> bool:
    """A changed Python file of the tests tree (a path that matches `tdd.test_globs`) that defines no test: an
    `__init__.py`, a helper, a module a test imports. Importing it runs code that can skip a test or set what a skip
    reads, and the file of the skip need not mention it. `source` is the file at the head (at the base for a deleted or
    renamed one); None when it cannot be read counts as one (`support_base.is_support_source`)."""
    return (
        path.endswith(".py")
        and any(glob_match(g, path) for g in cfg.tdd.test_globs)
        and is_support_source(cfg, path, source)
    )


class SkipRule:
    """Rules (b) to (e) for the tests of one file whose text is `base` at the base and `head` at the head: the two
    sources are parsed and scanned once, and each test is asked against the result (`no_skip_added`).
    `support_modules` are the changed files of the tests tree that define no test (`support_module`): the caller reads
    them from git; with none given the rule is blind to them."""

    def __init__(
        self,
        base: str,
        head: str,
        changed: Collection[str],
        cfg: L4Config,
        support_modules: Collection[str] = (),
    ) -> None:
        self.outside = _outside(changed, cfg, support_modules)
        base, head = normalized(base), normalized(head)
        self.before, self.after = SkipFacts(base), SkipFacts(head)
        self.confined = Confined(base, head, self.before, self.after)

    def no_skip_added(self, qualname: str) -> bool:
        """Rules (b) to (e): the unit added or changed no skip construct that can affect the test `qualname`, changed no
        file that can skip it from outside (rule (c): whatever such a file holds), changed nothing inside the file that
        decides whether an unchanged construct skips (the closure of the test's skip-relevant parts, `skipdeps`), and
        made every change of the file in a place the rule allows (`changes_confined`). A source that does not parse, a
        test that was not collected at the base or is not in the head, and a construct added in a scope that can skip
        the test are False."""
        before, after = self.before, self.after
        if self.outside or not before.ok or not after.ok or qualname not in before.collected:
            return False
        scopes = {qualname, MODULE, *([qualname.split(".", 1)[0]] if "." in qualname else []), *after.shared}
        if any(scope in scopes for scope, _ in after.constructs - before.constructs):  # a removed skip never counts
            return False
        closure = before.closure(qualname)
        return closure is not None and closure == after.closure(qualname) and self.changes_confined(qualname)

    def changes_confined(self, qualname: str) -> bool:
        """Rule (e), alone: every changed line of the file is a comment or blank line, a line of a collected test beyond
        what can skip `qualname`, or a whole new import of a name the base does not use (`skipscope`)."""
        return self.confined.holds(qualname)


def no_skip_added(base: str, head: str, qualname: str, changed: Collection[str], cfg: L4Config) -> bool:
    """`SkipRule(base, head, changed, cfg).no_skip_added(qualname)`, for one test."""
    return SkipRule(base, head, changed, cfg).no_skip_added(qualname)


def skip_predates(
    base: str, head: str, qualname: str, changed: Collection[str], cfg: L4Config, *, skipped_at_base: bool
) -> bool:
    """True when the skip of the test `qualname` predates the unit: `skipped_at_base` (a base report with statuses holds
    the test as skipped, rule (a)) and `no_skip_added` (rules (b) to (e))."""
    return skipped_at_base and no_skip_added(base, head, qualname, changed, cfg)
