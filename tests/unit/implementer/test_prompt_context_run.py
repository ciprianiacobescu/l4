"""What a run records of the prompt it builds (L4-IMP-052, L4-IMP-053, L4-KSP-010; SCN-IMP-285, 287, 290, 291)."""

import json

from l4.implementer import tdd
from l4.sandbox.base import repo_guidance_masks

from .._kiro_probe import PROBE_IDS, UNIT_REL
from .conftest import RUN_ID, Bench, kiro_red_step

CALC = '---\ninclusion: fileMatch\nfileMatchPattern: ["src/calc/**"]\n---\nCALC-MARKER\n'
PLAN = "# Implementation Plan\n\n- [ ] 1. Document `docs/usage.md`\n  - _Requirements: 1.1, 1.2_\n"


def ledger(bench: Bench) -> list[dict]:
    lines = (bench.wb.ref.path / ".l4" / "ledger" / f"{RUN_ID}.jsonl").read_text().splitlines()
    return [json.loads(line) for line in lines]


def probe_task(bench: Bench):
    (task,) = bench.wb.provider.tasks(bench.wb.ref)
    return task


def render(bench: Bench, attempt: int = 1) -> str:
    return tdd._prompt(bench.wb, "red", probe_task(bench), None, attempt=attempt)


def test_a_cut_is_recorded_right_after_the_prompt_with_the_one_source(make_kiro_bench):
    """SCN-IMP-285, run part."""
    bench: Bench = make_kiro_bench([kiro_red_step()], long_design=True, implementer={"context_budget_tokens": 24000})
    render(bench)
    events = ledger(bench)
    at = next(i for i, e in enumerate(events) if e["type"] == "prompt.rendered")
    cut = events[at + 1]
    assert cut["type"] == "prompt.truncated"
    assert (cut["role"], cut["task"], cut["attempt"], cut["budget_tokens"]) == ("red", "1", 1, 24000)
    (source,) = cut["sources"]
    assert (source["path"], source["kind"], source["reason"], source["total_chars"], source["readable"]) == (
        f"{UNIT_REL}/design.md", "design", "budget", 125_492, True
    )  # fmt: skip


def test_a_prompt_that_cuts_nothing_records_no_cut(make_kiro_bench):
    bench: Bench = make_kiro_bench([kiro_red_step()])
    render(bench)
    assert [e for e in ledger(bench) if e["type"] == "prompt.truncated"] == []


def test_the_prompt_records_its_budget_and_where_it_came_from(make_kiro_bench):
    """SCN-IMP-287, run part."""
    bench: Bench = make_kiro_bench([kiro_red_step()])
    render(bench)
    (rendered,) = [e for e in ledger(bench) if e["type"] == "prompt.rendered"]
    assert (rendered["budget_tokens"], rendered["budget_source"]) == (32_000, "implementer")


def test_a_selected_profile_with_its_own_budget_is_the_source(make_kiro_bench):
    local = {"adapter": "fake", "vendor": "fakeco", "context_budget_tokens": 4000}
    bench: Bench = make_kiro_bench(
        [kiro_red_step()], long_design=True, profiles={"local": local}, roles={"implementer": ["local"]}
    )
    text = render(bench)
    (rendered,) = [e for e in ledger(bench) if e["type"] == "prompt.rendered"]
    assert (rendered["budget_tokens"], rendered["budget_source"]) == (4000, "profile:local")
    assert [e for e in ledger(bench) if e["type"] == "prompt.truncated"][0]["budget_tokens"] == 4000
    assert "STEERING-MARKER" in text and "REQ-INTRO-MARKER" in text


def test_the_steering_decisions_are_recorded_and_the_sandbox_masks_stay(make_kiro_bench):
    """SCN-IMP-290, run part."""
    bench: Bench = make_kiro_bench([kiro_red_step()])
    text = render(bench)
    (rendered,) = [e for e in ledger(bench) if e["type"] == "prompt.rendered"]
    assert rendered["steering"] == [
        {"path": ".kiro/steering/tech.md", "inclusion": "always", "included": True, "why": "always"}
    ]
    assert '<l4:data source=".kiro/steering/tech.md">' in text and "STEERING-MARKER" in text
    assert bench.wb.worktree / ".kiro" / "steering" in repo_guidance_masks(bench.wb.worktree)  # the tmpfs stays
    assert PROBE_IDS["1.1"] in text


def test_a_file_match_file_follows_the_files_the_branch_changed(make_kiro_bench):
    """SCN-IMP-291, run part: the first prompt of a task that names only `docs/usage.md` has no `calc.md`."""
    bench: Bench = make_kiro_bench([kiro_red_step()], steering={"calc.md": CALC}, tasks_text=PLAN)
    first = render(bench)
    assert "CALC-MARKER" not in first
    wb = bench.wb
    (wb.worktree / "src" / "calc").mkdir(parents=True)
    (wb.worktree / "src" / "calc" / "tip.py").write_text("x = 1\n")
    wb.git.run("add", "-A")
    wb.commit("test: calc", task="0.9", attempt=1, phase="red", tdd="red")
    second = render(bench, attempt=2)
    assert "CALC-MARKER" in second
    decisions = [e["steering"] for e in ledger(bench) if e["type"] == "prompt.rendered"]
    assert {d["path"]: d["why"] for d in decisions[0]}[".kiro/steering/calc.md"] == "no_match"
    assert {d["path"]: d["why"] for d in decisions[1]}[".kiro/steering/calc.md"] == "matched src/calc/tip.py"


def test_a_profile_window_caps_the_budget_and_the_ledger_says_model_window(make_kiro_bench):
    local = {"adapter": "fake", "vendor": "fakeco", "context_window": 12000}
    bench: Bench = make_kiro_bench(
        [kiro_red_step()], long_design=True, profiles={"local": local}, roles={"implementer": ["local"]}
    )
    text = render(bench)
    (rendered,) = [e for e in ledger(bench) if e["type"] == "prompt.rendered"]
    assert rendered["budget_source"] == "model_window" and rendered["budget_tokens"] < 32_000
    assert len(text) <= int(12000 * 0.6) * 4 and "REQ-INTRO-MARKER" in text


def test_a_prompt_whose_fixed_parts_exceed_the_window_records_a_warning(make_kiro_bench):
    local = {"adapter": "fake", "vendor": "fakeco", "context_window": 1000}
    bench: Bench = make_kiro_bench([kiro_red_step()], profiles={"local": local}, roles={"implementer": ["local"]})
    render(bench)
    (warning,) = [e for e in ledger(bench) if e["type"] == "prompt.over_window"]
    assert (warning["role"], warning["task"], warning["window_tokens"]) == ("red", "1", 1000)
    assert warning["prompt_tokens"] > 600
