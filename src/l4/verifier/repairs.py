"""Which failing tests of a round a repair chore may touch (own-test-repair, L4-IMP-091, first paragraph).

A candidate is a failing test that (all of): sits in a Python file that matches `tdd.test_globs` and no
`tdd.test_support_globs` glob, is defined once in that file, was introduced by a harness commit that carries `L4-TDD:
red` of this unit's family (absent at the unit's base, `unit_base`, which for a fix unit is its parent's), and failed
with a kind other than `assertion` or `not_implemented` (the round's `failures`). The rule reads git, so both the
verifier (which plans the fix unit) and the fix unit's own step (which must not trust the marker) ask it, each against
its own worktree. Anything that cannot be shown is not a candidate: when in doubt, refuse."""

import os
import re
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from l4.fsutil import linked_component
from l4.implementer.discrimination import unit_base
from l4.implementer.tamper import Facts, facts_of
from l4.implementer.workbench import Workbench
from l4.security.protected import glob_match
from l4.specs.fixmark import split_fix_name
from l4.vcs.authorship import SHA, commit_records, is_harness
from l4.verifier.failures import COLLECTION_KIND

NOT_REPAIRABLE_KINDS = ("assertion", "not_implemented", COLLECTION_KIND)  # a failure of the code, not of the test
MAX_FILE_COMMITS = 50  # a test file touched by more commits than this is not analysed
MAX_TEST_BYTES = 1_000_000
_PARAMS = re.compile(r"\[.*$", re.S)


@dataclass(frozen=True)
class RepairTest:
    id: str  # the recorded test id (`e2e.test_a::test_x[1]`)
    path: str  # the test file, relative to the repository
    name: str  # `test_x`, or `Class.test_x` for a method of a module-level class
    gate: str  # the gate the test failed in: `test` or `e2e`
    kind: str
    message: str


def family_of(unit_id: str) -> tuple[str, str]:
    """(id, name) of the unit a fix unit belongs to: a fix unit `openspec:add-x-fix-2` runs inside the run of
    `openspec:add-x`, and a unit is its own family."""
    framework, _, name = unit_id.partition(":")
    split = split_fix_name(name)
    root = split[0] if split else name
    return f"{framework}:{root}", root


def locate(test_id: str) -> list[tuple[str, str]]:
    """(file, qualified name) the recorded id may stand for, most specific module first: `a.b.test_c.TestK::test_x[p]`
    is `a/b/test_c.py` and `TestK.test_x`, or `a/b/test_c/TestK.py` and `test_x`. At most one class is allowed between
    the module and the function."""
    module, sep, tail = test_id.rpartition("::")
    function = _PARAMS.sub("", tail)
    if not sep or not module or not function or "/" in module:
        return []
    parts = module.split(".")
    if any(not p or not p.isidentifier() for p in parts):
        return []
    found = []
    for cut in (len(parts), len(parts) - 1):
        if cut >= 1:
            klass = parts[cut:]
            found.append(("/".join(parts[:cut]) + ".py", ".".join([*klass, function])))
    return found


_NOT_A_USAGE_ERROR = re.compile(
    r"timeout|timed out|waiting for|strict mode violation|locator|resolved to|not found|no element|net::|expected to|"
    r"to be (visible|hidden|attached|enabled)|did not|failed to",
    re.I,
)
_USAGE_ERROR = re.compile(
    r"^(\w+\.)*(TypeError|ValueError|AttributeError|NameError):|\bmust be (a|an|one of)\b|unexpected keyword argument|"
    r"positional argument",
)


def _usage_error(message: str) -> bool:
    """A browser test's failure message that comes from the library's own argument or usage checks, or from the test's
    own call (a wrong type, value, attribute or name), and not from the page: a timeout, a locator that matched
    nothing or too much, a connection that failed. The page is the product's to control (a missing button is a
    Playwright error that is raised in the library, so the traceback cannot tell it from a usage error)."""
    return _USAGE_ERROR.search(message) is not None and _NOT_A_USAGE_ERROR.search(message) is None


def _raised_in_tests(wb: Workbench, gate: str, record: Mapping[str, str]) -> bool:
    """The failure was raised by the test itself, never by the product. Any exception from wrong product code has the
    kind `other` too, so the kind alone would let the product's own bug be "repaired" away. The round records the
    repository files the traceback passes through (`frames`) and the deepest one (`location`): every one of them SHALL
    match the test or support globs, so a production file anywhere in the traceback disqualifies it, and a record
    without them cannot be told and is no candidate. A browser test also needs a message that is a usage error, since
    its traceback ends in the library whatever is wrong with the page."""
    location, frames = record.get("location"), record.get("frames")
    if not isinstance(location, str) or not isinstance(frames, str) or not location or not frames:
        return False
    tdd = wb.cfg.tdd
    globs = (*tdd.test_globs, *tdd.test_support_globs)
    files = frames.split("\n")
    if location not in files or any(f.startswith("/") or ".." in f.split("/") for f in files):
        return False
    if not all(any(glob_match(g, f) for g in globs) for f in files):
        return False
    return gate != "e2e" or _usage_error(str(record.get("message") or ""))


def _hides_frames(wb: Workbench, base: str) -> bool:
    """A production file the unit added or changed mentions `__tracebackhide__`: pytest then leaves the frame out of the
    traceback, and an exception raised there would look as if the test's own line raised it. The unit's own code is the
    only code that can hide a frame to some purpose, and a test or support file may keep the mark."""
    done = wb.git.run("diff", "--name-only", "--no-renames", "-G__tracebackhide__", base, "HEAD", check=False)
    tdd = wb.cfg.tdd
    globs = (*tdd.test_globs, *tdd.test_support_globs)
    return any(p and not any(glob_match(g, p) for g in globs) for p in done.stdout.splitlines())


def _head_blob_ok(wb: Workbench, path: str) -> bool:
    """`path` is a regular file at HEAD and in the worktree, with no link on the way."""
    listing = wb.git.run("ls-tree", "HEAD", "--", path, check=False).stdout.split()
    if not listing or listing[0] not in ("100644", "100755"):
        return False
    target = wb.worktree / path
    return linked_component(wb.worktree, path) is None and target.is_file() and not target.is_symlink()


def _show(wb: Workbench, rev: str, path: str) -> str:
    done = wb.git.run("show", f"{rev}:{path}", check=False)
    return done.stdout if done.returncode == 0 and len(done.stdout) <= MAX_TEST_BYTES else ""


def _red_of_this_unit(wb: Workbench, sha: str) -> bool:
    """The commit carries `L4-TDD: red` and an `L4-Unit` of the unit's family."""
    out = wb.git.run(
        "log", "-1", "--format=%(trailers:key=L4-TDD,valueonly,separator=%x2c)%x01"
        "%(trailers:key=L4-Unit,valueonly,separator=%x2c)", sha, check=False,
    ).stdout  # fmt: skip
    tdd, _, unit = out.strip("\n").partition("\x01")
    root_id, root_name = family_of(wb.ref.id)
    framework = root_id.partition(":")[0]
    family = unit.strip()
    same = family == root_id or (
        (split := split_fix_name(family.partition(":")[2])) is not None
        and split[0] == root_name
        and family.partition(":")[0] == framework
    )
    return tdd.strip() == "red" and same


def _introduced_by_red(wb: Workbench, base: str, path: str, name: str) -> bool:
    """The first commit of `base..HEAD` after which `name` is a test of `path` (it was not one before) is a harness
    commit with `L4-TDD: red` of the unit's family, and no later commit by a person changed the test (its parts or what
    it uses in the file, `tamper.facts_of`) or took it out of the file (a file deleted and added again). A person's
    commit that leaves the test as it is does not matter."""
    records = commit_records(wb.git, "--reverse", "--no-merges", f"{base}..HEAD", "--", f":(literal){path}")
    if not records or len(records) > MAX_FILE_COMMITS:
        return False
    previous = ""
    introduced: Facts | None = None
    for record in records:
        now = _show(wb, record[SHA], path)
        was, here = facts_of(previous) or {}, facts_of(now) or {}
        if introduced is None:
            if name in here and here[name].test and not (name in was and was[name].test):
                if not (is_harness(record) and _red_of_this_unit(wb, record[SHA])):
                    return False
                introduced = here[name]
        elif not is_harness(record):
            fact, before = here.get(name), was.get(name)
            if fact is None or before is None or (fact.parts, fact.closure) != (before.parts, before.closure):
                return False
        elif name not in here:
            return False  # taken out of the file, whoever did it: it is not the red step's test any more
        previous = now
    return introduced is not None


def repair_candidates(wb: Workbench, failures: Mapping[str, Mapping[str, str]] | None) -> dict[str, RepairTest]:
    """test id -> its `RepairTest`, for the ids of a round's `failures` map that qualify (see the module text)."""
    if not isinstance(failures, Mapping):
        return {}
    base = unit_base(wb)
    if base is None or _hides_frames(wb, base):
        return {}
    tdd = wb.cfg.tdd
    found: dict[str, RepairTest] = {}
    for test_id, record in failures.items():
        if not isinstance(record, Mapping):
            continue
        gate, kind, message = str(record.get("gate")), str(record.get("kind")), str(record.get("message") or "")
        if gate not in ("test", "e2e") or kind in NOT_REPAIRABLE_KINDS or not _raised_in_tests(wb, gate, record):
            continue
        for path, name in locate(str(test_id)):
            if not (
                any(glob_match(g, path) for g in tdd.test_globs)
                and not any(glob_match(g, path) for g in tdd.test_support_globs)
                and PurePosixPath(path).suffix == ".py"
            ):
                continue
            if not _head_blob_ok(wb, path):
                continue
            facts = facts_of(_show(wb, "HEAD", path)) or {}
            fact = facts.get(name)
            absent_at_base = wb.git.run("cat-file", "-e", f"{base}:{path}", check=False).returncode != 0
            if (
                fact is not None and fact.test and len(fact.parts) == 1 and absent_at_base
                and _introduced_by_red(wb, base, path, name)
            ):  # fmt: skip
                found[str(test_id)] = RepairTest(str(test_id), path, name, gate, kind, message)
                break
    return found


def repair_files(candidates: Mapping[str, RepairTest]) -> list[str]:
    return sorted({c.path for c in candidates.values()})


MAX_LOG_TAIL = 600  # characters of a gate log a repair task carries


def log_tail(path: Path, limit: int = MAX_LOG_TAIL) -> str:
    """The end of a gate log, `limit` characters at most; "" when it cannot be read or is no regular file (a link is
    never followed). The caller redacts it."""
    try:
        info = os.lstat(path)
        if not stat.S_ISREG(info.st_mode):
            return ""
        with path.open("rb") as handle:
            handle.seek(max(0, info.st_size - 4 * limit))
            text = handle.read(4 * limit).decode("utf-8", errors="replace")
    except OSError:
        return ""
    return text.strip()[-limit:]
