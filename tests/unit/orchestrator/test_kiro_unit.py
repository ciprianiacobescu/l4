import json

from l4.agents.fake import Step

from ..implementer.conftest import IMPL, result
from .conftest import new_origin_main

BRANCH = "l4/kiro/discounts"
SPEC = ".kiro/specs/discounts"
REQUIREMENTS = """# Requirements Document

## Requirements

### Requirement 1: Discounts

**User Story:** As a shopper, I want a discount code, so that I pay less.

#### Acceptance Criteria

1. WHEN apply_discount is called with a known code, THE Shop SHALL reduce the amount.

### Requirement 2: Shouting

**User Story:** As a shopper, I want my name shouted, so that I feel seen.

#### Acceptance Criteria

1. WHEN shout is called with a name, THE Shop SHALL return it in capitals.
"""
TASKS = """# Implementation Plan

- [ ] 1. Discounts
  - [ ] 1.1 Add `apply_discount(amount, code)` to `src/pytdd/pricing.py`
    - _Requirements: 1.1_
  - [ ]* 1.2 Document `apply_discount`
    - _Requirements: 1.1_
- [ ] 2. Shouting
  - [ ] 2.1 Add `shout(name)` to `src/pytdd/pricing.py`
    - _Requirements: 2.1_

## Task Dependency Graph

```json
{"waves": [{"id": 0, "tasks": ["2.1"]}, {"id": 1, "tasks": ["1.1"]}]}
```
"""
BASE = "def total(prices: list[float]) -> float:\n    return round(sum(prices), 2)\n"
SHOUT_RED = BASE + "\n\ndef shout(name):\n    raise NotImplementedError\n"
SHOUT_DONE = BASE + "\n\ndef shout(name):\n    return name.upper()\n"
DISCOUNT_RED = SHOUT_DONE + "\n\ndef apply_discount(amount, code):\n    raise NotImplementedError\n"
DISCOUNT_DONE = IMPL + "\n\ndef shout(name):\n    return name.upper()\n"
DISCOUNT_ID, SHOUT_ID = "C-a37caae9", "C-594c3674"  # `kiro_criteria` of REQUIREMENTS (Req 1.1, Req 2.1)
SHOUT_TEST = (
    f'import pytest\n\nfrom pytdd.pricing import shout\n\n\n@pytest.mark.l4("{SHOUT_ID}")\ndef test_shout():\n'
    '    assert shout("ada") == "ADA"\n'
)  # M1.3: a red test traces its criterion
DISCOUNT_TEST = (
    f'import pytest\n\nfrom pytdd.pricing import apply_discount\n\n\n@pytest.mark.l4("{DISCOUNT_ID}")\n'
    'def test_known_code():\n    assert apply_discount(50.0, "SAVE10") == 45.0\n'
)


def script() -> list[Step]:
    def one(task: str, phase: str, writes: dict[str, str], **over: object) -> Step:
        return Step(writes=writes, structured=result(phase, task_ids=[task], **over))

    return [
        one("2.1", "red", {"tests/test_shout.py": SHOUT_TEST, "src/pytdd/pricing.py": SHOUT_RED},
            tests_added=["tests/test_shout.py::test_shout"], criteria_ids=[SHOUT_ID]),
        one("2.1", "green", {"src/pytdd/pricing.py": SHOUT_DONE}),
        one("1.1", "red", {"tests/test_discount.py": DISCOUNT_TEST, "src/pytdd/pricing.py": DISCOUNT_RED},
            tests_added=["tests/test_discount.py::test_known_code"], criteria_ids=[DISCOUNT_ID]),
        one("1.1", "green", {"src/pytdd/pricing.py": DISCOUNT_DONE}),
    ]  # fmt: skip


def test_kiro_unit_runs_waves_skips_optional_and_ticks_parents(run_l4, tdd_repo, raw):
    for name, text in {"requirements.md": REQUIREMENTS, "tasks.md": TASKS}.items():
        path = tdd_repo.repo / SPEC / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    new_origin_main(tdd_repo, raw, {})
    run = run_l4(script(), "--unit", "kiro:discounts", unit=False)

    assert run.code == 0
    tasks = raw(tdd_repo.origin, "show", f"{BRANCH}:{SPEC}/tasks.md")
    before = raw(tdd_repo.origin, "show", f"main:{SPEC}/tasks.md")
    boxes = [line.strip()[:5] for line in tasks.splitlines() if line.strip().startswith("- [")]
    assert boxes == ["- [x]", "- [x]", "- [ ]", "- [x]", "- [x]"]  # both parents ticked, the optional leaf not
    assert len(tasks) == len(before)
    assert sum(a != b for a, b in zip(tasks, before, strict=True)) == 4  # markers only: 2.1, 2, 1.1, 1

    ledger_path = f"{SPEC}/.l4/ledger/"
    listing = raw(tdd_repo.origin, "ls-tree", "--name-only", BRANCH, ledger_path).split()
    events = [json.loads(line) for p in listing for line in raw(tdd_repo.origin, "show", f"{BRANCH}:{p}").splitlines()]
    assert [e["task"] for e in events if e["type"] == "task.started"] == ["2.1", "1.1"]  # wave 0 first, never 1.2
    assert [e["task"] for e in events if e["type"] == "task.done"] == ["2.1", "1.1"]
    phases = [e for e in events if e["type"] == "phase.changed"]
    assert phases[-1]["to"] == "implemented"
    assert run.outcome["units"][0]["tasks"] == {"done": 4, "total": 4}  # the optional leaf is not a task to do


def _write_unit(tdd_repo, raw, tasks: str) -> None:
    for name, text in {"requirements.md": REQUIREMENTS, "tasks.md": tasks}.items():
        path = tdd_repo.repo / SPEC / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    new_origin_main(tdd_repo, raw, {})


def _events(raw, tdd_repo) -> list[dict]:
    listing = raw(tdd_repo.origin, "ls-tree", "--name-only", BRANCH, f"{SPEC}/.l4/ledger/").split()
    return [json.loads(line) for p in listing for line in raw(tdd_repo.origin, "show", f"{BRANCH}:{p}").splitlines()]


def test_a_parent_whose_children_are_all_optional_is_closed_never_executed(run_l4, tdd_repo, raw):
    tasks = TASKS.replace("\n## Task Dependency", "- [ ] 3. Docs\n  - [ ]* 3.1 Write the docs\n\n## Task Dependency")
    _write_unit(tdd_repo, raw, tasks)
    run = run_l4(script(), "--unit", "kiro:discounts", unit=False)

    assert run.code == 0
    after = raw(tdd_repo.origin, "show", f"{BRANCH}:{SPEC}/tasks.md")
    boxes = [line.strip()[:5] for line in after.splitlines() if line.strip().startswith("- [")]
    assert boxes == ["- [x]", "- [x]", "- [ ]", "- [x]", "- [x]", "- [x]", "- [ ]"]  # 3 closed, 3.1 untouched
    before = raw(tdd_repo.origin, "show", f"main:{SPEC}/tasks.md")
    assert sum(a != b for a, b in zip(after, before, strict=True)) == 5  # 2.1, 2, 1.1, 1 and 3: markers only
    events = _events(raw, tdd_repo)
    assert [e["task"] for e in events if e["type"] == "task.started"] == ["2.1", "1.1"]  # 3 was never started
    assert [e["task"] for e in events if e["type"] == "task.done"] == ["3", "2.1", "1.1"]
    assert len(run.adapter.requests) == 4  # two tasks, red and green; nothing for the parent


def test_a_unit_whose_only_open_parent_has_optional_children_needs_no_agent(run_l4, tdd_repo, raw):
    _write_unit(tdd_repo, raw, "# Plan\n\n- [ ] 1. Docs\n  - [ ]* 1.1 Write the docs\n    - _Requirements: 1.1_\n")
    run = run_l4([], "--unit", "kiro:discounts", unit=False)

    assert run.code == 0 and run.adapter.requests == []
    after = raw(tdd_repo.origin, "show", f"{BRANCH}:{SPEC}/tasks.md")
    assert "- [x] 1. Docs" in after and "- [ ]* 1.1" in after
    assert run.outcome["units"][0]["tasks"] == {"done": 1, "total": 1}


def _rejected_reasons(tdd_repo) -> list[str]:
    from l4.vcs.names import UnitNames

    names = UnitNames.for_unit("kiro:discounts", branch_prefix="l4/", cache=tdd_repo.cache, repo_key=tdd_repo.key)
    files = sorted((names.worktree / SPEC / ".l4" / "ledger").glob("*.jsonl"))
    events = [json.loads(line) for f in files for line in f.read_text().splitlines()]
    return [r for e in events if e["type"] == "unit.rejected" for r in e["reasons"]]


def test_an_invalid_kiro_unit_is_rejected_at_intake_before_any_agent(run_l4, tdd_repo, raw):
    # L4-KSP-003 under sdd.enforce: a leaf without `_Requirements:_`, a dangling reference, a broken wave graph
    bad = TASKS.replace("    - _Requirements: 1.1_\n  - [ ]* 1.2", "  - [ ]* 1.2").replace("2.1_", "9.9_")
    bad = bad.replace('["2.1"]', '["7.7"]')
    _write_unit(tdd_repo, raw, bad)
    run = run_l4(script(), "--unit", "kiro:discounts", unit=False)

    assert run.code == 14 and run.adapter.requests == []
    reasons = "\n".join(_rejected_reasons(tdd_repo))
    assert "task 1.1 has no _Requirements:_ line" in reasons
    assert "cites _Requirements: 9.9_" in reasons
    assert "invalid Task Dependency Graph" in reasons
    assert run.outcome["units"][0]["phase_after"] == "none"


def test_a_tdd_exempt_leaf_without_requirements_does_not_block_intake(run_l4, tdd_repo, raw):
    tasks = TASKS.replace("1.1 Add `apply_discount(amount, code)`", "1.1 [docs] Add `apply_discount(amount, code)`")
    tasks = tasks.replace("    - _Requirements: 1.1_\n  - [ ]* 1.2", "  - [ ]* 1.2")
    _write_unit(tdd_repo, raw, tasks)
    run = run_l4([], "--unit", "kiro:discounts", unit=False)
    assert run.code != 14 and _rejected_reasons(tdd_repo) == []
    assert run.adapter.requests  # intake passed: the agent was asked (the empty script then ends the run)


def test_a_kiro_task_that_names_a_forbidden_file_rejects_the_unit_before_any_agent(run_l4, tdd_repo, raw):
    migration = "app/migrations/0001_initial.py"  # SCN-YOLO-251
    tasks = TASKS.replace("Add `shout(name)` to `src/pytdd/pricing.py`", f"Add `shout(name)` and create `{migration}`")
    _write_unit(tdd_repo, raw, tasks)
    run = run_l4(script(), "--unit", "kiro:discounts", unit=False)

    assert run.code == 14 and run.adapter.requests == []
    (reason,) = _rejected_reasons(tdd_repo)
    assert reason.startswith(f"forbidden_path: task 2.1 names {migration}, which odd.forbidden_paths rule ")
    assert run.outcome["units"][0]["phase_after"] == "none"


def test_a_kiro_task_that_says_not_to_touch_the_file_is_not_rejected(run_l4, tdd_repo, raw):
    tasks = TASKS.replace("Add `shout(name)` to", "Add `shout(name)`; do not create app/migrations/0001_initial.py; in")
    _write_unit(tdd_repo, raw, tasks)
    run = run_l4([], "--unit", "kiro:discounts", unit=False)
    assert run.code != 14 and _rejected_reasons(tdd_repo) == []
