"""Confirmation of a pre-satisfied criterion by an earlier red of the same unit (L4-IMP-003).

A red step whose new tests all pass (the tests of a criterion an earlier task's green already satisfied) must show
that they discriminate. The zero-value run of `confirm_pre_satisfied` is Python-only; but when the same criterion was
traced by tests that FAILED against the real base code at an earlier red of this unit, on this branch, and those
tests are unchanged and pass now, the harness already holds the strongest evidence there is. A test counts only if
all of these hold (each is a refusal otherwise: the criterion goes on to the zero-value confirmation):

1. it is in the head report, passes there, traces the criterion and is not one of this step's new tests;
2. an earlier `task.red_ok` of this ledger (same `fix_unit` context) lists it among the `discriminating` tests of
   a criterion proved `red_assertion` or `zero_value`, and no `criterion.pre_satisfied` of that task (same context)
   lists it: a test the earlier red let pass proves nothing; an `already-satisfied` event contributes nothing;
3. that red is on this branch: its `base` and its commit (the `sha` of the `task.red_committed` with the same task
   and base) are ancestors of HEAD, so a rebase that rewrote them voids the evidence;
4. since the red commit the test's file only gained lines (committed by later tasks or appended by this step).
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from l4.gates.junit import TestReport
from l4.implementer.discrimination import PROOF_RED_ASSERTION, PROOF_ZERO_VALUE
from l4.implementer.guards import appended_only
from l4.implementer.workbench import Workbench
from l4.specs.criteria import trace_ids
from l4.state.ledger import read_ledger

VIA = "earlier_red"
_FAILED_PROOFS = (PROOF_RED_ASSERTION, PROOF_ZERO_VALUE)


@dataclass(frozen=True)
class EarlierRed:
    """One criterion confirmed by earlier reds: the earlier tests that failed then and pass now, and the newest red
    among them (its commit `sha` and task; the other reds are implied by the test ids)."""

    tests: tuple[str, ...]
    red_sha: str
    red_task: str


@dataclass(frozen=True)
class _Evidence:
    sha: str
    task: str
    order: int  # position of the red in the ledger: the newest wins


def _test_file(wb: Workbench, sha: str, test_id: str) -> str | None:
    """The repository path of a test id at the red commit: the part before the first `::` as it is
    (`services/x.test.ts`), or, for a dotted pytest JUnit id, the longest dotted prefix that is a module there
    (`tests.test_x.TestY::test_z` -> `tests/test_x.py`, the class dropped); the one that exists in the red commit."""
    head = test_id.split("::", 1)[0]
    candidates = [head]
    if "/" not in head and "." in head:
        parts = head.split(".")
        while parts:
            candidates.append("/".join(parts) + ".py")
            parts.pop()
    for path in candidates:
        if wb.git.run("cat-file", "-e", f"{sha}:{path}", check=False).returncode == 0:
            return path
    return None


def _unchanged_since(wb: Workbench, sha: str, path: str) -> bool:
    """Since the red commit the test file only gained lines, in the commits since (a later task's already-satisfied
    commit, live MR !2 task 3.1) and in this step's worktree alike: a task may be told to add its tests to an earlier
    task's file (live MR !2), and added lines leave the earlier tests as that red ran them; a changed or deleted line
    (or a binary diff) voids the evidence."""
    stat = wb.git.run("diff", "--numstat", sha, "--", path, check=False)
    if stat.returncode != 0:
        return False
    for line in stat.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 3 or not parts[1].isdigit() or int(parts[1]) != 0:
            return False
    return True


def _only_appended_since(wb: Workbench, sha: str, path: str) -> bool:
    """Since the red commit the test file only GAINED content at its end: for a Python file `appended_only` (every
    top-level statement kept, new ones only define), else the old text is a prefix of the new one. An inserted line (a
    decorator that tags an old test with another criterion) voids the evidence (review of kiro-prompt-context, M1)."""
    before = wb.git.run("show", f"{sha}:{path}", check=False)
    target = wb.worktree / path
    if before.returncode != 0 or target.is_symlink() or not target.is_file():
        return False
    old, new = before.stdout, target.read_text(encoding="utf-8", errors="replace")
    return appended_only(old, new) if path.endswith(".py") else new.startswith(old)


def _ancestor(wb: Workbench, commit: Any) -> bool:
    return isinstance(commit, str) and bool(commit) and (
        wb.git.run("merge-base", "--is-ancestor", commit, "HEAD", check=False).returncode == 0
    )  # fmt: skip


def _evidence(wb: Workbench) -> dict[tuple[str, str], _Evidence]:
    """(criterion, test id) -> the earlier red that saw the test fail for THAT criterion, from the ledger as
    `resume_red` reads it. A test later tagged with another criterion is no evidence for it (M1)."""
    ledger_unit = wb.worktree / Path(wb.ledger_rel).parents[2]
    events = read_ledger(ledger_unit).events
    fix_unit = wb.event_context.get("fix_unit")
    events = [e for e in events if e.data.get("fix_unit") == fix_unit]
    allowed = {  # (task, test) the red let pass as pre-satisfied
        (e.data.get("task"), str(t))
        for e in events if e.type == "criterion.pre_satisfied" for t in e.data.get("tests") or []
    }  # fmt: skip
    found: dict[tuple[str, str], _Evidence] = {}
    on_branch: dict[tuple[str, str], bool] = {}
    for order, event in enumerate(events):
        if event.type != "task.red_ok" or event.data.get("tdd") == "already-satisfied":
            continue
        task, base = event.data.get("task"), event.data.get("base")
        sha = next(
            (
                e.data.get("sha") for e in events[order + 1 :]
                if e.type == "task.red_committed" and e.data.get("task") == task and e.data.get("base") == base
            ),
            None,
        )  # fmt: skip
        if not isinstance(sha, str) or not sha or not isinstance(task, str):
            continue
        key = (str(base), sha)
        if key not in on_branch:
            on_branch[key] = _ancestor(wb, base) and _ancestor(wb, sha)
        if not on_branch[key]:
            continue
        criteria = event.data.get("criteria")
        for proved, info in criteria.items() if isinstance(criteria, dict) else ():
            if not isinstance(info, dict) or info.get("proof") not in _FAILED_PROOFS:
                continue
            for test in info.get("discriminating") or []:  # the ones that red saw fail by assertion
                if (task, str(test)) not in allowed:
                    found[(str(proved), str(test))] = _Evidence(sha, task, order)
    return found


def confirmed_by_earlier_red(
    wb: Workbench, candidates: dict[str, tuple[str, ...]], report: TestReport, new_ids: frozenset[str] | set[str]
) -> dict[str, EarlierRed]:
    """`candidates`: criterion -> this step's new tests, all passing. The ones an earlier red of the unit confirms."""
    if not candidates:
        return {}
    evidence = _evidence(wb)
    if not evidence:
        return {}
    unchanged: dict[str, bool] = {}

    def holds(criterion: str, test: str) -> bool:
        case = report.tests.get(test)
        if test in new_ids or case is None or case.status != "passed":
            return False
        sha = evidence[(criterion, test)].sha
        path = _test_file(wb, sha, test)
        if path is None:
            return False
        key = f"{sha}:{path}"
        if key not in unchanged:
            unchanged[key] = _only_appended_since(wb, sha, path)
        return unchanged[key]

    confirmed: dict[str, EarlierRed] = {}
    for criterion in candidates:
        tests = sorted(
            t
            for c, t in evidence
            if c == criterion and t in report.tests and criterion in trace_ids(report.tests[t]) and holds(c, t)
        )
        if tests:
            newest = max((evidence[(criterion, t)] for t in tests), key=lambda e: e.order)
            confirmed[criterion] = EarlierRed(tuple(tests), newest.sha, newest.task)
    return confirmed
