"""Review material within budgets (L4-YOLO-024, review-resolution design D4): a prerequisite is shown spec first and its
cut goes to `missing`, the subject's own cut blocks with a message that says what to do, and the budgets are
configuration (`yolo.review.max_file_chars`, `max_folder_chars`, `max_dependency_chars`)."""

import pytest

from l4.agents.fake import FakeAdapter, Step
from l4.yolo.model import UnitInfo
from l4.yolo.readiness import Budgets, read_folder, review_plan_costed

from .yolo_review_world import SPEC_A, SPEC_B, World, make_cfg, plan_of

A, B = "openspec:a", "openspec:b"
FOLDER_A, FOLDER_B = "openspec/changes/a", "openspec/changes/b"


def ready():
    return {"verdict": "READY", "findings": [], "assumptions": [], "missing": []}


@pytest.fixture
def world(tmp_path):
    w = World(tmp_path)
    w.rev = w.commit({f"{FOLDER_A}/specs/x/spec.md": SPEC_A, f"{FOLDER_B}/specs/x/spec.md": SPEC_B})
    w.units = {A: UnitInfo(A, FOLDER_A), B: UnitInfo(B, FOLDER_B)}
    return w


def review(world, plan, cfg=None, steps=2):
    fake = FakeAdapter([Step(structured=ready()) for _ in range(steps)])
    result, _ = review_plan_costed(
        world.app, cfg or make_cfg(), plan, world.units, git=world.git, rev=world.rev, adapters={"fake": fake}
    )
    return result, fake


def prompt_of(fake, unit):
    return next(r.prompt for r in fake.requests if f'source="subject">\n{unit}\n' in r.prompt)


def test_a_prerequisites_task_list_is_cut_without_blocking(world):  # SCN-YOLO-53
    world.rev = world.commit(
        {
            f"{FOLDER_A}/proposal.md": "p" * 2999 + "\n",
            f"{FOLDER_A}/specs/x/spec.md": "s" * 8999 + "\n",
            f"{FOLDER_A}/tasks.md": "t" * 11999 + "\n",
        }
    )
    plan = plan_of({A: [], B: [A]}, batches=[("b1", [A]), ("b2", [B])])
    result, fake = review(world, plan)
    prompt = prompt_of(fake, B)
    assert "p" * 2999 in prompt and "s" * 8999 in prompt
    assert "t" * 8000 in prompt and "t" * 8001 not in prompt
    assert result.units[B].verdict == "READY" and result.units[B].findings == ()
    expected = (
        f'not shown in full: "{A}": {FOLDER_A}/tasks.md (8000 of 12000 characters shown; dependency budget 20000)'
    )
    assert expected in result.units[B].missing
    assert result.units[A].verdict == "READY" and result.units[A].missing == ()  # A, as a subject, is shown whole


def test_the_subjects_own_cut_blocks_and_says_how_to_fix_it(world):  # SCN-YOLO-54
    world.rev = world.commit({f"{FOLDER_A}/design.md": "x" * 25999 + "\n"})
    result, _ = review(world, plan_of({A: []}), steps=1)
    verdict = result.units[A]
    assert verdict.verdict == "NEEDS_REVISION"
    (finding,) = verdict.findings
    assert finding["criterion"] == "material" and finding["severity"] == "blocking"
    text = finding["text"]
    assert text.startswith("material_cut: ") and f"{FOLDER_A}/design.md has 26000 characters" in text
    assert "20000 per file" in text and "80000 per folder" in text
    assert "yolo.review.max_file_chars" in text and "yolo.review.max_folder_chars" in text
    assert "Shorten the file" in text and ".l4/config.yaml on main" in text
    assert "Splitting it does not help" in text and "specs/*/spec.md" in text


def test_a_raised_budget_shows_the_whole_file(world):  # SCN-YOLO-55
    world.rev = world.commit({f"{FOLDER_A}/design.md": "x" * 25999 + "\n"})
    cfg = make_cfg(yolo={"review": {"max_file_chars": 30000}})
    result, fake = review(world, plan_of({A: []}), cfg, steps=1)
    assert "x" * 25999 in fake.requests[0].prompt
    assert result.units[A].verdict == "READY" and result.units[A].findings == ()


def test_a_folder_over_the_folder_budget_names_the_key(world):
    world.rev = world.commit({f"{FOLDER_A}/a-first.md": "y" * 599 + "\n", f"{FOLDER_A}/b-second.md": "z" * 599 + "\n"})
    cfg = make_cfg(yolo={"review": {"max_folder_chars": 1000}})
    result, _ = review(world, plan_of({A: []}), cfg, steps=1)
    (finding,) = result.units[A].findings
    assert "b-second.md has 600 characters" in finding["text"] and "1000 per folder" in finding["text"]
    assert "yolo.review.max_folder_chars" in finding["text"]


def test_budgets_come_from_the_configuration():
    assert Budgets.of(make_cfg()) == Budgets(20_000, 80_000, 20_000)
    cfg = make_cfg(yolo={"review": {"max_file_chars": 1500, "max_folder_chars": 2500, "max_dependency_chars": 0}})
    assert Budgets.of(cfg) == Budgets(1500, 2500, 0)


def test_a_dependency_budget_of_zero_shows_nothing_and_lists_every_file(world):
    cfg = make_cfg(yolo={"review": {"max_dependency_chars": 0}})
    plan = plan_of({A: [], B: [A]}, batches=[("b1", [A]), ("b2", [B])])
    result, _ = review(world, plan, cfg)
    assert result.units[B].verdict == "READY"
    line = f'not shown in full: "{A}": {FOLDER_A}/specs/x/spec.md (0 of {len(SPEC_A)} characters shown; '
    assert line + "dependency budget 0)" in result.units[B].missing


FILES = {
    "tasks.md": "t\n",
    "design.md": "d\n",
    "zzz-notes.md": "n\n",
    "specs/x/spec.md": "s\n",
    "specs/a/spec.md": "s\n",
    "proposal.md": "p\n",
    "aaa.md": "a\n",
    "bugfix.md": "b\n",
    "requirements.md": "r\n",
}


@pytest.mark.parametrize("folder", [FOLDER_A, ".kiro/specs/a"])
def test_a_prerequisite_is_read_spec_first_and_the_task_list_last(world, folder):
    rev = world.commit({f"{folder}/{name}": text for name, text in FILES.items()})
    got = read_folder(world.git, rev, folder, budget=10_000, file_budget=10_000, order="prerequisite")
    assert [p.removeprefix(folder + "/") for p, _ in got.files] == [
        "proposal.md",
        "requirements.md",
        "specs/a/spec.md",
        "specs/x/spec.md",
        "bugfix.md",
        "design.md",
        "aaa.md",
        "zzz-notes.md",
        "tasks.md",
    ]


def test_the_subject_is_read_in_sorted_order(world):
    rev = world.commit({f"{FOLDER_A}/{name}": text for name, text in FILES.items()})
    got = read_folder(world.git, rev, FOLDER_A, budget=10_000)
    paths = [p for p, _ in got.files]
    assert paths == sorted(paths)


def test_a_folder_text_keeps_the_total_size_of_each_file(world):
    rev = world.commit({f"{FOLDER_A}/big.md": "x" * 4999 + "\n", f"{FOLDER_A}/small.md": "y\n"})
    got = read_folder(world.git, rev, FOLDER_A, budget=2000, file_budget=1500)
    sizes = dict(got.sizes)
    assert sizes[f"{FOLDER_A}/big.md"] == 5000 and sizes[f"{FOLDER_A}/small.md"] == 2
    assert got.cut == ((f"{FOLDER_A}/big.md", 3500),)
    assert got.not_in_full("openspec:a", 2000) == (
        f'not shown in full: "openspec:a": {FOLDER_A}/big.md (1500 of 5000 characters shown; dependency budget 2000)',
    )
