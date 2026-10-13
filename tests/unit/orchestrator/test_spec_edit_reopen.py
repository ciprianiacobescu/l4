"""L4-OPS-015, SCN-OPS-23, SCN-OPS-24: a spec push that changes an acceptance criterion of a Kiro unit reopens the tasks
that cite it (in one harness commit), and they run test-first again. A re-wrapped line reopens nothing."""

import json
import tempfile
from pathlib import Path

from l4.agents.fake import Step
from l4.specs.criteria import kiro_criteria

from ..implementer.conftest import result
from .conftest import new_origin_main

BRANCH = "l4/kiro/discounts"
SPEC = ".kiro/specs/discounts"
BASE = "def total(prices: list[float]) -> float:\n    return round(sum(prices), 2)\n"
REQUIREMENTS = """# Requirements Document

## Requirements

### Requirement 2: Shouting

**User Story:** As a shopper, I want my name shouted, so that I feel seen.

#### Acceptance Criteria

1. WHEN shout is called with a name, THE Shop SHALL return it in capitals.
2. WHEN shout is called with an empty name, THE Shop SHALL return a dash.
3. WHEN shout is called with a long name, THE Shop SHALL
   return it in capitals.
"""
TASKS = """# Implementation Plan

- [ ] 2. Shouting
  - [ ] 2.1 Add `shout(name)` to `src/pytdd/pricing.py`
    - _Requirements: 2.3_
  - [ ] 2.2 Return a dash for an empty name
    - _Requirements: 2.2_
"""
LONG = "abcdefghij"
RED = BASE + "\n\ndef shout(name):\n    raise NotImplementedError\n"
UPPER = BASE + "\n\ndef shout(name):\n    return name.upper()\n"
DASH = BASE + '\n\ndef shout(name):\n    return name.upper() or "-"\n'
TRIMMED = BASE + '\n\ndef shout(name):\n    return name.strip().upper() or "-"\n'


def ids_of(requirements: str) -> dict[str, str]:
    with tempfile.TemporaryDirectory() as tmp:
        unit = Path(tmp) / "discounts"  # the unit's name is part of a criterion's id
        unit.mkdir()
        (unit / "requirements.md").write_text(requirements)
        return {c.alias: c.id for c in kiro_criteria(unit)}


def shout_test(name: str, cid: str, arg: str, expected: str) -> dict[str, str]:
    body = (
        f'import pytest\n\nfrom pytdd.pricing import shout\n\n\n@pytest.mark.l4("{cid}")\ndef test_{name}():\n'
        f'    assert shout("{arg}") == "{expected}"\n'
    )
    return {f"tests/test_{name}.py": body}


def step(phase: str, task: str, writes: dict[str, str], **over: object) -> Step:
    return Step(writes=writes, structured=result(phase, task_ids=[task], **over))


def first_script(ids: dict[str, str]) -> list[Step]:
    long_test, dash_test = (
        shout_test("long", ids["Req 2.3"], LONG, LONG.upper()),
        shout_test("empty", ids["Req 2.2"], "", "-"),
    )
    return [
        step("red", "2.1", {**long_test, "src/pytdd/pricing.py": RED}, tests_added=["tests/test_long.py::test_long"],
             criteria_ids=[ids["Req 2.3"]]),
        step("green", "2.1", {"src/pytdd/pricing.py": UPPER}),
        step("red", "2.2", {**dash_test, "src/pytdd/pricing.py": UPPER},
             tests_added=["tests/test_empty.py::test_empty"], criteria_ids=[ids["Req 2.2"]]),
        step("green", "2.2", {"src/pytdd/pricing.py": DASH}),
    ]  # fmt: skip


def second_script(ids: dict[str, str]) -> list[Step]:
    trim = shout_test("trim", ids["Req 2.3"], f" {LONG} ", LONG.upper())
    return [
        step("red", "2.1", {**trim, "src/pytdd/pricing.py": DASH}, tests_added=["tests/test_trim.py::test_trim"],
             criteria_ids=[ids["Req 2.3"]]),
        step("green", "2.1", {"src/pytdd/pricing.py": TRIMMED}),
    ]  # fmt: skip


def push_requirements(tdd_repo, raw, text: str, name: str) -> None:
    """What a person does: clone the remote, edit `requirements.md` on the unit branch, push."""
    clone = tdd_repo.repo.parent / f"human-{name}"
    raw(tdd_repo.repo.parent, "clone", "-q", "--branch", BRANCH, str(tdd_repo.origin), str(clone))
    (clone / SPEC / "requirements.md").write_text(text)
    raw(clone, "add", "-A")
    raw(clone, "commit", "-q", "-m", name)
    raw(clone, "push", "-q", "origin", BRANCH)


def ledger(raw, tdd_repo) -> list[dict]:
    listing = raw(tdd_repo.origin, "ls-tree", "--name-only", BRANCH, f"{SPEC}/.l4/ledger/").split()
    events = [json.loads(line) for p in listing for line in raw(tdd_repo.origin, "show", f"{BRANCH}:{p}").splitlines()]
    return sorted(events, key=lambda e: (e["ts"], e["run_id"], e["seq"]))


def boxes(text: str) -> list[str]:
    return [line.strip()[:5] for line in text.splitlines() if line.strip().startswith("- [")]


def start(run_l4, tdd_repo, raw):
    for name, text in {"requirements.md": REQUIREMENTS, "tasks.md": TASKS}.items():
        path = tdd_repo.repo / SPEC / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    new_origin_main(tdd_repo, raw, {})
    ids = ids_of(REQUIREMENTS)
    first = run_l4(first_script(ids), "--unit", "kiro:discounts", unit=False)
    assert first.code == 0
    assert boxes(raw(tdd_repo.origin, "show", f"{BRANCH}:{SPEC}/tasks.md")) == ["- [x]"] * 3
    return ids


def test_a_reworded_criterion_reopens_the_task_that_cites_it_and_it_runs_red_then_green(run_l4, tdd_repo, raw):
    """SCN-OPS-23."""
    start(run_l4, tdd_repo, raw)
    reworded = REQUIREMENTS.replace(
        "THE Shop SHALL\n   return it in capitals.",
        "THE Shop SHALL\n   return it in capitals without the spaces around it.",
    )
    assert reworded != REQUIREMENTS
    push_requirements(tdd_repo, raw, reworded, "reword")
    second = run_l4(second_script(ids_of(reworded)), "--unit", "kiro:discounts", unit=False)

    assert second.code == 0
    subjects = raw(tdd_repo.origin, "log", "--format=%s", f"main..{BRANCH}").splitlines()[::-1]
    reopen = "chore(discounts): reopen tasks 2, 2.1 for changed requirements 2.3 [skip ci]"
    assert reopen in subjects and subjects.count(reopen) == 1
    sha = raw(tdd_repo.origin, "log", "--format=%H", f"--grep=^{reopen[:40]}", BRANCH).split()[0]
    assert boxes(raw(tdd_repo.origin, "show", f"{sha}:{SPEC}/tasks.md")) == ["- [ ]", "- [ ]", "- [x]"]  # 2.2 stays
    assert raw(tdd_repo.origin, "show", "--format=%an <%ae>%n%b", "-s", sha).splitlines()[0].startswith("l4")
    assert boxes(raw(tdd_repo.origin, "show", f"{BRANCH}:{SPEC}/tasks.md")) == ["- [x]"] * 3
    log = ledger(raw, tdd_repo)
    kinds = [e["type"] for e in log]
    [retried] = [e for e in log if e["type"] == "unit.retried"]
    assert (retried["reason"], retried["by"]) == ("spec edited", "push") and retried["signal"].startswith("spec_edit:")
    [reopened] = [e for e in log if e["type"] == "tasks.reopened"]
    assert (reopened["tasks"], reopened["requirements"]) == (["2", "2.1"], ["2.3"])
    after = kinds.index("tasks.reopened")
    assert kinds.index("unit.retried") < after < len(kinds) - 1 - kinds[::-1].index("task.done")
    assert [e["task"] for e in log[after:] if e["type"] == "task.started"] == ["2.1"]
    assert [(e["from"], e["to"], e["trigger"]) for e in log if e["type"] == "phase.changed"][-2:] == [
        ("implemented", "implementing", "spec_edited"),
        ("implementing", "implemented", "all_leaves_done"),
    ]
    assert len(second.adapter.requests) == 2  # red, then green
    trailers = raw(
        tdd_repo.origin, "log", "--format=%(trailers:key=L4-Tdd,valueonly,separator=%x2c)", f"main..{BRANCH}"
    )
    assert [t for t in trailers.split() if t][:2] == ["green", "red"]  # newest first


def test_a_rewrapped_criterion_reopens_nothing_but_the_unit_still_re_enters(run_l4, tdd_repo, raw):
    """SCN-OPS-24."""
    start(run_l4, tdd_repo, raw)
    rewrapped = REQUIREMENTS.replace(
        "THE Shop SHALL\n   return it in capitals.", "THE Shop SHALL return it\n   in  capitals."
    )
    assert rewrapped != REQUIREMENTS
    push_requirements(tdd_repo, raw, rewrapped, "rewrap")
    second = run_l4([], "--unit", "kiro:discounts", unit=False)

    assert second.code == 0 and second.adapter.requests == []
    log = ledger(raw, tdd_repo)
    assert "tasks.reopened" not in [e["type"] for e in log]
    assert [e["reason"] for e in log if e["type"] == "unit.retried"] == ["spec edited"]
    assert ("implemented", "implementing", "spec_edited") in [
        (e["from"], e["to"], e["trigger"]) for e in log if e["type"] == "phase.changed"
    ]
    subjects = raw(tdd_repo.origin, "log", "--format=%s", f"main..{BRANCH}")
    assert "reopen tasks" not in subjects
    assert boxes(raw(tdd_repo.origin, "show", f"{BRANCH}:{SPEC}/tasks.md")) == ["- [x]"] * 3


def test_a_retry_that_takes_the_edit_reopens_the_citing_tasks_in_its_own_run(run_l4, tdd_repo, raw):
    """L4-OPS-003 + L4-OPS-015: `l4 retry` records no agent work, so the reopening happens in the retry itself."""
    from l4.cli import main

    for name, text in {"requirements.md": REQUIREMENTS, "tasks.md": TASKS}.items():
        path = tdd_repo.repo / SPEC / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    new_origin_main(tdd_repo, raw, {})
    ids = ids_of(REQUIREMENTS)
    stuck = Step(structured=result("red", task_ids=["2.2"]))  # no test added: the first attempt is the last
    halted = run_l4(
        [*first_script(ids)[:2], stuck], "--unit", "kiro:discounts", unit=False, implementer={"max_task_attempts": 1}
    )
    assert halted.code == 13
    reworded = REQUIREMENTS.replace(
        "THE Shop SHALL\n   return it in capitals.", "THE Shop SHALL\n   return it trimmed."
    )
    push_requirements(tdd_repo, raw, reworded, "reword")

    argv = ["retry", "--unit", "kiro:discounts", "--reason", "spec reworded", "--no-run", "--repo", str(tdd_repo.repo)]
    assert main(argv, environ=tdd_repo.environ) == 0

    log = ledger(raw, tdd_repo)
    assert [(e["from"], e["to"], e["trigger"]) for e in log if e["type"] == "phase.changed"][-1] == (
        "halted", "implementing", "spec_edit_since_stop",
    )  # fmt: skip
    [reopened] = [e for e in log if e["type"] == "tasks.reopened"]
    assert (reopened["tasks"], reopened["requirements"]) == (["2.1"], ["2.3"])  # the parent was open already
    assert boxes(raw(tdd_repo.origin, "show", f"{BRANCH}:{SPEC}/tasks.md")) == ["- [ ]", "- [ ]", "- [ ]"]
    subjects = raw(tdd_repo.origin, "log", "--format=%s", f"main..{BRANCH}").splitlines()
    assert "chore(discounts): reopen tasks 2.1 for changed requirements 2.3 [skip ci]" in subjects
    assert subjects[0] == "chore(discounts): retry [skip ci]"
