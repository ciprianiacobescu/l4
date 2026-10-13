"""Tests ran: did the tests the unit added actually run and pass? (verifier 1.8 delta, M1.6 D5)

SPEC step 3 asks that every test added in the unit executed. The gate already fails on a non-zero exit, a missing
report, collection errors and a missing red test; it let a skipped new test pass. This check closes that and gives
the `tests_ok` ground-truth label: the gate passed, nothing failed or errored, every new test passed.
"""

from collections.abc import Collection
from dataclasses import dataclass, field

from l4.gates.junit import TestReport
from l4.verifier.types import Finding, Severity

MAX_NAMED = 5


@dataclass(frozen=True)
class TestsSummary:
    __test__ = False  # not a pytest class

    total: int = 0
    passed: int = 0
    failed: int = 0
    errored: int = 0
    skipped: int = 0
    new: int = 0
    new_passed: int = 0
    skipped_unchanged: tuple[str, ...] = ()  # skipped tests in files the unit did not touch: listed, never judged


@dataclass
class TestsRanOutcome:
    __test__ = False

    findings: list[Finding] = field(default_factory=list)
    label: bool = False  # `tests_ok`
    summary: TestsSummary = field(default_factory=TestsSummary)

    @property
    def all_passed(self) -> bool:
        """The S1 sanity label, the literal question "did every test of the run pass?": `label`, and no test of the
        run skipped, old ones included (the state lists them under "Not passed")."""
        return self.label and self.summary.skipped == 0


def file_of_test(test_id: str, candidates: Collection[str], tree: Collection[str] | None = None) -> str | None:
    """The file a JUnit id belongs to: `classname.replace('.', '/') + '.py'`, dropping trailing class names
    (`tests.test_a.TestK` resolves to `tests/test_a.py`; only a capitalised part is a class, so `tests.test_x` is
    never read as `tests.py`). `tree`: every file of the head tree (default: `candidates`). The exact path wins when it
    is a file of the tree. Only when it is not, the one tree file that ends with `/<module path>` is the file (the
    classname starts at pytest's rootdir, a subdirectory under `cd backend && pytest`); two such files are ambiguous.
    The answer counts only when it is one of `candidates`: a test of an unchanged file is attributed to nothing."""
    files = candidates if tree is None else tree
    if not isinstance(files, set | frozenset):
        files = frozenset(files)
    parts = test_id.split("::", 1)[0].split(".")
    for end in range(len(parts), 0, -1):
        if end < len(parts) and not parts[end][:1].isupper():
            break
        path = "/".join(parts[:end]) + ".py"
        if path in files:
            found = path
        else:
            under = sorted(f for f in files if f.endswith("/" + path))
            if not under:
                continue
            found = under[0] if len(under) == 1 else None
        return found if found in candidates else None
    return None


def _named(ids: Collection[str]) -> str:
    shown = sorted(ids)[:MAX_NAMED]
    return ", ".join(shown) + (f" and {len(ids) - MAX_NAMED} more" if len(ids) > MAX_NAMED else "")


def _blocker(title: str, ids: Collection[str]) -> Finding:
    return Finding(Severity.BLOCKER, title, _named(ids), "deterministic")


def check_tests_ran(
    report: TestReport,
    new_tests: Collection[str],
    changed_test_files: Collection[str],
    *,
    added_test_files: Collection[str] = (),
    tree: Collection[str] | None = None,
    gate_passed: bool,
) -> TestsRanOutcome:
    """`new_tests`: the ledger's red tests. The testcases of `added_test_files` (added files that define tests) count
    as new too; one of those files with no testcase in the report (wrong name, unmatched pattern) is a blocker. A
    new test that is missing, skipped, errored or failed is a blocker (a failure is also the gate's own finding). A
    skipped test that was already there is a major only in a file the unit changed (`changed_test_files`). `tree`:
    the files of the head tree, so that an unchanged file of the same name is never mistaken for an added one."""
    tests = report.tests
    changed = set(changed_test_files) | set(added_test_files)
    tree = frozenset(tree) if tree is not None else frozenset(changed)
    new = set(new_tests) | {i for i in tests if file_of_test(i, added_test_files, tree)}
    uncollected = {f for f in added_test_files if not any(file_of_test(i, {f}, tree) for i in tests)}
    missing = {i for i in new if i not in tests}
    status = {i: tests[i].status for i in new if i in tests}
    skipped = {i for i, s in status.items() if s == "skipped"}
    errored = {i for i, s in status.items() if s == "error"}
    failed = {i for i, s in status.items() if s == "failed"}
    findings: list[Finding] = []
    if uncollected:
        findings.append(_blocker("new test file ran no test", uncollected))
    if missing:
        findings.append(_blocker("new tests did not run", missing))
    if skipped:
        findings.append(_blocker("new tests were skipped", skipped))
    if errored:
        findings.append(_blocker("new tests errored", errored))
    if failed:
        findings.append(_blocker("new tests failed", failed))
    old_skipped = {i for i in report.ids_with("skipped") if i not in new}
    touched = {i for i in old_skipped if file_of_test(i, changed, tree)}
    if touched:
        findings.append(
            Finding(
                Severity.MAJOR, "existing tests are skipped in a changed test file", _named(touched), "deterministic"
            )
        )
    failing = report.ids_with("failed") | report.ids_with("error")
    new_passed = sum(1 for s in status.values() if s == "passed")
    summary = TestsSummary(
        total=report.total,
        passed=len(report.ids_with("passed")),
        failed=len(report.ids_with("failed")),
        errored=len(report.ids_with("error")),
        skipped=len(report.ids_with("skipped")),
        new=len(new),
        new_passed=new_passed,
        skipped_unchanged=tuple(sorted(old_skipped - touched)),
    )
    label = gate_passed and not failing and not report.collection_errors and new_passed == len(new) and not uncollected
    return TestsRanOutcome(findings, label, summary)
