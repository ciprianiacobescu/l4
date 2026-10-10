"""The red prompt of `l4 run --dry-run` is the red prompt a real run sends (m14 plan, Risks).

M1.5 adds a block to `tdd._prompt` (contract C14) and must add it to `sim.dryrun` as well; this test is what notices
when only one of them changed."""

import hashlib
import json

from l4.cli import main

from ..implementer.conftest import green_step, red_step
from .conftest import new_origin_main
from .test_kiro_unit import REQUIREMENTS, SPEC, TASKS, script

DISCOUNT_TASKS = "## 1. Pricing\n\n- [ ] 1.1 Add `apply_discount`\n"


def dry_prompt(tdd, task: str) -> bytes:
    """Run the dry run, then read the red prompt it wrote for `task`."""
    tdd.write_config()
    assert main(["run", "--dry-run", "--repo", str(tdd.repo)], environ=tdd.environ) == 0
    [path] = (tdd.repo / ".l4-out" / "dry-run").rglob(f"{task}-red.prompt.md")
    return path.read_bytes()


def same_run(dry: bytes, tdd, real_id: str) -> bytes:
    """The prompt names the run's own ledger, so the two runs differ by their run id and by nothing else."""
    [dry_dir] = (tdd.repo / ".l4-out" / "dry-run").iterdir()
    assert real_id != dry_dir.name
    return dry.replace(dry_dir.name.encode(), real_id.encode())


def real_red_hash(run, task: str) -> str:
    [event] = [e for e in run.events("prompt.rendered") if e["role"] == "red" and e["task"] == task]
    return event["sha256"]


def test_openspec_dry_run_prompt_hash_equals_the_real_red_prompt_hash(run_l4, tdd_repo, raw):
    new_origin_main(tdd_repo, raw, {"openspec/changes/add-discount-codes/tasks.md": DISCOUNT_TASKS})
    dry = dry_prompt(tdd_repo, "1.1")
    run = run_l4([red_step(), green_step()])
    assert run.code == 0
    assert hashlib.sha256(same_run(dry, tdd_repo, run.ledger()[0]["run_id"])).hexdigest() == real_red_hash(run, "1.1")


def test_kiro_dry_run_prompt_hash_equals_the_real_red_prompt_hash(run_l4, tdd_repo, raw):
    for name, text in {"requirements.md": REQUIREMENTS, "tasks.md": TASKS}.items():
        path = tdd_repo.repo / SPEC / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    new_origin_main(tdd_repo, raw, {})
    dry = dry_prompt(tdd_repo, "2.1")
    run = run_l4(script(), "--unit", "kiro:discounts", unit=False)
    assert run.code == 0
    listing = raw(tdd_repo.origin, "ls-tree", "--name-only", "l4/kiro/discounts", f"{SPEC}/.l4/ledger/").split()
    lines = [ln for p in listing for ln in raw(tdd_repo.origin, "show", f"l4/kiro/discounts:{p}").splitlines()]
    events = map(json.loads, lines)
    [event] = [e for e in events if e["type"] == "prompt.rendered" and e["role"] == "red" and e["task"] == "2.1"]
    assert hashlib.sha256(same_run(dry, tdd_repo, event["run_id"])).hexdigest() == event["sha256"]


def test_dry_run_prompt_carries_the_lessons_block_a_real_red_prompt_has(run_l4, tdd_repo, raw):
    from l4.memory.lessons import Lesson, LessonsFile, lesson_id, render_lessons

    lesson = Lesson(lesson_id("k"), "Title", "k", body="Be careful.")
    files = {
        "openspec/changes/add-discount-codes/tasks.md": DISCOUNT_TASKS,
        ".serena/memories/harness/lessons.md": render_lessons(LessonsFile([lesson])),
    }
    (tdd_repo.repo / ".serena/memories/harness").mkdir(parents=True)
    new_origin_main(tdd_repo, raw, files)
    dry = dry_prompt(tdd_repo, "1.1")
    assert f'<l4:data kind="lessons" ids="{lesson.id}">'.encode() in dry
    run = run_l4([red_step(), green_step()])
    assert run.code == 0
    assert hashlib.sha256(same_run(dry, tdd_repo, run.ledger()[0]["run_id"])).hexdigest() == real_red_hash(run, "1.1")
