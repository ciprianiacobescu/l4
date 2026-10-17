"""What the implementer's prompt carries of a unit (kiro-prompt-context): the sources read as they are, the task's
whole block, the criteria text, the budget filled in priority order, and every cut named."""

import os
import re

import pytest

from l4.config.schema import L4Config, Profile
from l4.implementer.prompt import PromptContext, collect_sources, render_prompt
from l4.implementer.unit_context import (
    MAX_SOURCE_BYTES,
    MIN_CUT_CHARS,
    Convention,
    SourceFile,
    effective_budget,
    is_named,
    plan_context,
    prompt_inputs,
    read_sources,
    section_keys,
    split_sections,
    task_block,
)
from l4.specs.base import Framework, SpecError, UnitRef
from l4.specs.kiro import KiroProvider, parse_kiro_tasks
from l4.specs.openspec import parse_openspec_tasks

from .._kiro_probe import PROBE_IDS, UNIT_REL, probe_tree

# -- the readers (tasks 1.1) -------------------------------------------------------------------------------------


def test_the_task_block_of_the_probe_leaf_holds_the_checkbox_the_detail_bullets_and_the_requirements_line(tmp_path):
    """SCN-IMP-282, reader part."""
    data = (probe_tree(tmp_path) / UNIT_REL / "tasks.md").read_bytes()
    tasks = parse_kiro_tasks(data)
    block = task_block(data, tasks[0], tasks, Framework.KIRO)
    expected = [
        "- [ ] 1. Implement the tip function",
        "  - TASK-DETAIL-MARKER: reject a percent above 100 with ValueError as well",
        "  - Use Decimal throughout",
        "  - _Requirements: 1.1, 1.2_",
    ]
    positions = [block.index(line) for line in expected]
    assert positions == sorted(positions)
    assert block.endswith("\n".join(expected) + "\n")


def test_the_task_block_of_a_nested_kiro_leaf_starts_with_its_parent_task_line():
    data = b"# Plan\n\n- [ ] 1. Parent\n  - [ ] 1.1 Leaf\n    - detail\n    - _Requirements: 1.1_\n- [ ] 2. Other\n"
    tasks = parse_kiro_tasks(data)
    leaf = next(t for t in tasks if t.key == "1.1")
    assert task_block(data, leaf, tasks, Framework.KIRO) == (
        "# Plan\n- [ ] 1. Parent\n  - [ ] 1.1 Leaf\n    - detail\n    - _Requirements: 1.1_\n"
    )


def test_the_task_block_of_an_openspec_task_has_its_group_heading_and_no_parents():
    data = b"## 1. Group\n\n- [ ] 1.1 First\n  more words\n- [ ] 1.2 Second\n"
    tasks = parse_openspec_tasks(data)
    assert task_block(data, tasks[1], tasks, Framework.OPENSPEC) == "## 1. Group\n- [ ] 1.2 Second\n"
    assert task_block(data, tasks[0], tasks, Framework.OPENSPEC) == "## 1. Group\n- [ ] 1.1 First\n  more words\n"


def test_a_source_over_the_limit_is_read_up_to_it_and_a_link_or_a_fifo_is_named(tmp_path):
    """SCN-IMP-286, reader part."""
    unit = tmp_path / ".kiro" / "specs" / "big"
    unit.mkdir(parents=True)
    (unit / "design.md").write_bytes(b"line of the design\n" * 15_789 + b"x" * 9)
    assert (unit / "design.md").stat().st_size == 300_000
    (tmp_path / "elsewhere.md").write_text("# elsewhere\n")
    (unit / "requirements.md").symlink_to(tmp_path / "elsewhere.md")
    os.mkfifo(unit / "bugfix.md")
    (unit / "proposal.md").write_text("# Proposal\nwhole\n")
    found = {s.name: s for s in read_sources(unit, tmp_path)}
    design = found["design.md"]
    assert (design.reason, design.total_bytes, design.path) == ("oversize", 300_000, ".kiro/specs/big/design.md")
    assert len(design.text.encode()) == MAX_SOURCE_BYTES == 262_144
    assert (found["requirements.md"].reason, found["requirements.md"].text) == ("symlink", "")
    assert (found["bugfix.md"].reason, found["bugfix.md"].text) == ("not_regular", "")
    assert (found["proposal.md"].reason, found["proposal.md"].text) == ("", "# Proposal\nwhole\n")
    assert [s.name for s in read_sources(unit, tmp_path)] == [
        "proposal.md",
        "design.md",
        "requirements.md",
        "bugfix.md",
    ]
    assert [name for name, _ in collect_sources(unit)] == ["proposal.md"]  # the clarifier and the audit writer


def test_the_spec_deltas_are_read_in_name_order_and_a_linked_specs_directory_is_named(tmp_path):
    unit = tmp_path / "openspec" / "changes" / "add-x"
    for capability in ("zeta", "alpha"):
        (unit / "specs" / capability).mkdir(parents=True)
        (unit / "specs" / capability / "spec.md").write_text(f"## ADDED Requirements\n{capability}\n")
    assert [s.name for s in read_sources(unit, tmp_path)] == ["specs/alpha/spec.md", "specs/zeta/spec.md"]
    moved = tmp_path / "moved"
    unit.joinpath("specs").rename(moved)
    unit.joinpath("specs").symlink_to(moved)
    (only,) = read_sources(unit, tmp_path)
    assert (only.name, only.reason, only.text) == ("specs", "symlink", "")


# -- the prompt (tasks 2.1 to 2.3) ---------------------------------------------------------------------------------


GATE = ".venv/bin/python -m pytest -p no:cacheprovider --junitxml=.l4-out/junit.xml"
TECH = "# Tech steering\nSTEERING-MARKER: all money values are Decimal, never float; round half up to 2 places.\n"


def probe_ctx(root, *, budget: int = 24000, conventions=None, **over: object) -> PromptContext:
    """The probe's task 1 as `kiro:tip-calc` renders it: its sources as read, the whole task block, the criteria."""
    provider = KiroProvider(root)
    (ref,) = provider.list_units()
    data = (root / UNIT_REL / "tasks.md").read_bytes()
    tasks = provider.tasks(ref)
    try:
        criteria = tuple(provider.criteria(ref))
    except SpecError:  # a linked requirements.md cannot be read: the prompt is still rendered
        criteria = ()
    base = {
        "unit_id": "kiro:tip-calc", "adapter": "codex", "task_key": "1", "task_title": tasks[0].title,
        "task_links": tasks[0].links, "criteria": criteria, "gate_command": GATE,
        "source_files": read_sources(root / UNIT_REL, root), "unit_rel": UNIT_REL,
        "task_block": task_block(data, tasks[0], tasks, Framework.KIRO), "context_budget_tokens": budget,
        "conventions": (Convention(".kiro/steering/tech.md", TECH, "steering", False),)
        if conventions is None
        else conventions,
    }  # fmt: skip
    return PromptContext(**{**base, **over})  # type: ignore[arg-type]


def headings(text: str) -> list[str]:
    """The `# ` headings of the prompt outside its data blocks."""
    outside = re.sub(r'<l4:data source=".*?</l4:data>', "", text, flags=re.DOTALL)
    return re.findall(r"^# (.+)$", outside, flags=re.MULTILINE)


def block(text: str, source: str) -> str:
    match = re.search(rf'<l4:data source="{re.escape(source)}">\n(.*?)\n</l4:data>', text, flags=re.DOTALL)
    assert match, f"no data block {source!r}"
    return match.group(1)


def test_a_kiro_red_prompt_has_its_sections_in_order(tmp_path):
    """SCN-IMP-280."""
    rendered = render_prompt("red", probe_ctx(probe_tree(tmp_path)))
    assert headings(rendered.text) == [
        "Harness contract", "Project conventions", "Unit context", "Task 1", "Criteria of this unit",
        "Phase: RED (tests first)", "Gate command", "Output",
    ]  # fmt: skip
    assert rendered.template_version == "contract@12+red@11"
    assert "Not shown in full" not in headings(rendered.text) and rendered.cuts == ()


def test_a_long_design_no_longer_takes_the_criteria_text_away(tmp_path):
    """SCN-IMP-281."""
    text = render_prompt("red", probe_ctx(probe_tree(tmp_path, long=True))).text
    criteria = block(text, "criteria")
    ears_1 = "WHEN a bill and a tip percent are given THEN the system SHALL return the tip rounded to 2 places."
    ears_2 = "WHEN the tip percent is negative THEN the system SHALL raise ValueError."
    assert f"- {PROBE_IDS['1.1']}  Req 1.1\n  {ears_1}" in criteria
    assert f"- {PROBE_IDS['1.2']}  Req 1.2\n  {ears_2}" in criteria
    assert "REQ-INTRO-MARKER" in block(text, "requirements.md")
    assert "omitted to fit the context budget" not in text


@pytest.mark.parametrize("role", ["red", "green", "single"])
@pytest.mark.parametrize("budget", [24000, 1])
def test_a_kiro_leafs_detail_bullets_reach_every_prompt(tmp_path, role, budget):
    """SCN-IMP-282, prompt part."""
    text = render_prompt(role, probe_ctx(probe_tree(tmp_path), budget=budget)).text
    task = block(text, f"{UNIT_REL}/tasks.md")
    for expected in (
        "- [ ] 1. Implement the tip function",
        "TASK-DETAIL-MARKER: reject a percent above 100 with ValueError as well",
        "Use Decimal throughout",
        "_Requirements: 1.1, 1.2_",
    ):
        assert expected in task
    assert task.index("TASK-DETAIL-MARKER") < task.index("Use Decimal") < task.index("_Requirements")
    assert text.index("# Task 1") < text.index(task) < text.index("# Criteria of this unit")
    assert PROBE_IDS["1.1"] in block(text, "criteria")  # the criteria are never cut either


def test_a_task_without_a_block_keeps_its_title_and_links_line(tmp_path):
    text = render_prompt("red", probe_ctx(probe_tree(tmp_path), task_block="")).text
    assert block(text, "tasks.md") == "1. Implement the tip function\n_Requirements: 1.1, 1.2_"


# -- the planner: sections, names, cuts --------------------------------------------------------------------------


def test_sections_split_at_headings_outside_fences():
    text = "pre\n# One\na\n```\n# not a heading\n```\n## Two\nb\n"
    sections = split_sections(text)
    assert [(s.start, s.end, s.heading) for s in sections] == [(1, 1, False), (2, 6, True), (7, 8, True)]
    assert "".join(s.text for s in sections) == text
    assert split_sections("") == []
    assert [s.heading for s in split_sections("# only\n")] == [True]


def test_a_section_is_named_by_a_requirement_number_a_validates_line_or_a_backticked_token():
    keys = section_keys("- [ ] 1. Add `apply_discount`\n  - _Requirements: 1.2_\n", ("1.2",), Framework.KIRO)
    assert is_named("**Validates: Requirements 1.1, 1.2**\n", keys)
    assert is_named("### Requirement 1: Sign in\n", keys)  # the requirement number of the link
    assert not is_named("### Requirement 2: Sign out\n", keys)
    assert not is_named("Retry 1.2 times\n", keys)  # no requirement word on the line
    assert is_named("call apply_discount here\n", keys)
    assert not is_named("nothing here\n", keys)
    bare = section_keys("- [ ] 2. x\n", ("2",), Framework.KIRO)
    assert is_named("**Validates: Requirements 2.4**", bare) and not is_named("**Validates: Requirements 12.4**", bare)
    openspec = section_keys('- [ ] 1.1 Implement "Known discount code" for `pricing`\n', (), Framework.OPENSPEC)
    assert is_named("### Requirement: Known discount code\n", openspec) and is_named("the `pricing` module", openspec)
    assert not is_named("the 'x' module", openspec)


def test_a_piece_with_fewer_than_min_cut_chars_left_is_left_out_not_cut():
    text = "".join(f"line {i:04d} of the proposal text here\n" for i in range(400))  # 400 lines of 36 characters
    source = SourceFile("proposal.md", "p/proposal.md", text, len(text.encode()))
    tokens = (MIN_CUT_CHARS - 1) // 4 + 1  # budget in characters: 2000 > MIN_CUT_CHARS - 1 left: cut
    cut_plan = plan_context(fixed_chars=0, budget_tokens=tokens, conventions=(), source_files=(source,), keys=None)
    (shown,) = cut_plan.sources
    assert 0 < len(shown.body()) <= tokens * 4 and "[cut: lines " in shown.body()
    tiny = plan_context(fixed_chars=tokens * 4 - (MIN_CUT_CHARS - 1), budget_tokens=tokens, conventions=(),
                        source_files=(source,), keys=None)  # fmt: skip
    assert tiny.sources == () and [c.shown_chars for c in tiny.cuts] == [0]


def long_with_validates(root):
    path = root / UNIT_REL / "design.md"
    text = path.read_text().replace("## Component 1050\n", "## Component 1050\n**Validates: Requirements 1.2**\n")
    path.write_text(text)
    return root


def test_a_short_budget_keeps_the_conventions_then_the_requirements_then_the_named_design_sections(tmp_path):
    """SCN-IMP-283."""
    text = render_prompt("red", probe_ctx(long_with_validates(probe_tree(tmp_path, long=True)))).text
    assert block(text, ".kiro/steering/tech.md") == TECH.rstrip("\n")
    assert "REQ-INTRO-MARKER" in block(text, "requirements.md") and "#### Acceptance Criteria" in text
    design = block(text, "design.md")
    assert "DESIGN-MARKER" in design and "## Component 0\n" in design
    assert "## Component 1050\n**Validates: Requirements 1.2**" in design  # past where the budget ran out
    assert "## Component 1099" not in design
    assert design.index("## Component 1050") > design.index("[not shown: lines ")
    gaps = re.findall(r"^\[not shown: lines (\d+)-(\d+)\]$", design, flags=re.MULTILINE)
    assert len(gaps) >= 2 and all(int(a) <= int(b) for a, b in gaps)
    context = text[text.index("# Project conventions") : text.index("# Not shown in full")]
    fixed = len(text[text.index("# Task 1") : text.index("# Phase: RED")])
    assert len(context) <= 96_000 - fixed


def test_a_long_steering_file_is_cut_at_half_the_budget_and_named_unreadable(tmp_path):
    """SCN-IMP-293."""
    style = "".join(f"Style rule {i:05d}: keep the lines short and the names clear.\n" for i in range(1170))
    style = style[:70_000]
    assert len(style) == 70_000
    conventions = (
        Convention(".kiro/steering/style.md", style, "steering", False),
        Convention(".kiro/steering/tech.md", TECH, "steering", False),
    )
    rendered = render_prompt("red", probe_ctx(probe_tree(tmp_path), conventions=conventions))
    text = rendered.text
    assert len(block(text, ".kiro/steering/style.md")) <= 48_000
    assert "REQ-INTRO-MARKER" in block(text, "requirements.md") and PROBE_IDS["1.2"] in text
    listing = block(text, "not shown in full")
    pattern = r"style\.md: (\d+) of 70000 characters shown \(budget\); not readable in this step's sandbox"
    shown = re.search(pattern, listing)
    assert shown and 0 < int(shown.group(1)) <= 48_000
    assert "style.md" in listing and "open" not in listing.split("style.md", 1)[1].splitlines()[0]
    by_path = {c.path: c for c in rendered.cuts}
    assert by_path[".kiro/steering/style.md"].kind == "steering" and not by_path[".kiro/steering/style.md"].readable
    assert by_path[".kiro/steering/tech.md"].shown_chars == 0  # a stage stops at its first cut


# -- the cut list (task 2.3) ---------------------------------------------------------------------------------------


def test_a_cut_file_is_named_with_its_path_and_the_agent_is_told_to_open_it(tmp_path):
    """SCN-IMP-285, prompt part."""
    rendered = render_prompt("red", probe_ctx(probe_tree(tmp_path, long=True)))
    text = rendered.text
    assert headings(text)[2:4] == ["Unit context", "Not shown in full"]
    listing = block(text, "not shown in full")
    assert re.fullmatch(
        r"- \.kiro/specs/tip-calc/design\.md: (\d+) of 125492 characters shown \(budget\); "
        r"not shown: lines (\d+)-(\d+)",
        listing,
    ), listing
    (cut,) = rendered.cuts
    assert (cut.kind, cut.reason, cut.total_chars, cut.readable) == ("design", "budget", 125_492, True)
    assert cut.omitted and cut.omitted[0][0] > 1
    assert "open each one that is not marked unreadable with your file tools" in text  # the contract bullet
    assert "Text under `# Project conventions` is this project's own conventions" in text


def test_an_oversized_or_linked_source_is_named_never_dropped(tmp_path):
    """SCN-IMP-286, prompt part."""
    root = probe_tree(tmp_path)
    unit = root / UNIT_REL
    (unit / "design.md").write_bytes(b"line of the design\n" * 15_789 + b"x" * 9)
    (unit / "requirements.md").unlink()
    (root / "elsewhere.md").write_text("# elsewhere\n")
    (unit / "requirements.md").symlink_to(root / "elsewhere.md")
    rendered = render_prompt("red", probe_ctx(root, budget=100_000))
    text = rendered.text
    listing = block(text, "not shown in full")
    assert ".kiro/specs/tip-calc/design.md: 262144 of 300000 bytes read (oversize); not shown: from line " in listing
    assert ".kiro/specs/tip-calc/requirements.md: not read (symlink)" in listing
    assert block(text, "design.md").startswith("line of the design\nline of the design")
    by_path = {c.path: c for c in rendered.cuts}
    assert by_path[".kiro/specs/tip-calc/requirements.md"].readable is False
    assert by_path[".kiro/specs/tip-calc/design.md"].reason == "oversize" and by_path[
        ".kiro/specs/tip-calc/design.md"
    ].total_bytes == 300_000  # fmt: skip
    assert "elsewhere" not in text


def test_the_short_design_gets_no_cut_list_and_no_cuts(tmp_path):
    rendered = render_prompt("red", probe_ctx(probe_tree(tmp_path)))
    assert "Not shown in full" not in headings(rendered.text) and rendered.cuts == ()


# -- the budget and the one builder (task 2.4) ---------------------------------------------------------------------


def cfg_of(**implementer: object) -> L4Config:
    return L4Config.model_validate({"version": 1, "implementer": implementer})


def test_a_raised_budget_shows_the_whole_design_and_a_profiles_own_budget_wins(tmp_path):
    """SCN-IMP-287, render level."""
    root = probe_tree(tmp_path, long=True)
    big = render_prompt("red", probe_ctx(root, budget=40_000))
    assert big.cuts == () and big.budget_tokens == 40_000 and "Not shown in full" not in headings(big.text)
    assert block(big.text, "design.md").count("## Component ") == 1100
    small = render_prompt("red", probe_ctx(root, budget=4_000))
    assert small.budget_tokens == 4_000
    assert block(small.text, ".kiro/steering/tech.md") == TECH.rstrip("\n")
    assert "REQ-INTRO-MARKER" in block(small.text, "requirements.md")
    assert [c.path for c in small.cuts] == [".kiro/specs/tip-calc/design.md"]
    assert len(block(small.text, "design.md")) < 16_000


def test_the_effective_budget_is_the_profiles_when_it_sets_one():
    cfg = cfg_of(context_budget_tokens=40_000)
    assert effective_budget(cfg, "impl", Profile(adapter="fake")) == (40_000, "implementer")
    local = Profile(adapter="fake", context_budget_tokens=4_000)
    assert effective_budget(cfg, "local", local) == (4_000, "profile:local")
    assert effective_budget(cfg, None, None) == (40_000, "implementer")
    assert effective_budget(cfg_of(), None, None) == (32_000, "implementer")  # owner decision 8: 32000, not 24000


class Plain:
    """A provider that reads a unit by directory, as the prompt builder needs it."""

    def __init__(self, root, criteria=(), own=None):
        self.root, self.criteria_, self.own = root, list(criteria), own

    def unit_dir(self, ref):
        return ref.path

    def criteria(self, ref):
        return self.criteria_

    def own_criteria(self, ref):
        return self.criteria_ if self.own is None else self.own


def probe_inputs(root, *, changed=(), cfg=None, name=None, profile=None, tasks_text=None):
    provider = KiroProvider(root)
    (ref,) = provider.list_units()
    if tasks_text is not None:
        (root / UNIT_REL / "tasks.md").write_text(tasks_text)
    tasks = provider.tasks(ref)
    inputs = prompt_inputs(
        root=root, provider=provider, ref=ref, task=tasks[0], tasks=tasks, changed=list(changed),
        cfg=cfg or cfg_of(), profile_name=name, profile=profile,
    )  # fmt: skip
    return inputs, provider, ref


def test_the_probes_inputs_carry_the_steering_decision_the_block_and_the_budget(tmp_path):
    inputs, provider, ref = probe_inputs(probe_tree(tmp_path))
    assert inputs.steering == [
        {"path": ".kiro/steering/tech.md", "inclusion": "always", "included": True, "why": "always"}
    ]
    assert [(c.path, c.kind, c.readable) for c in inputs.conventions] == [(".kiro/steering/tech.md", "steering", False)]
    assert "STEERING-MARKER" in inputs.conventions[0].text and "TASK-DETAIL-MARKER" in inputs.task_block
    assert (inputs.budget_tokens, inputs.budget_source, inputs.unit_rel) == (32_000, "implementer", UNIT_REL)
    assert [s.name for s in inputs.source_files] == ["design.md", "requirements.md"]
    assert [c.id for c in inputs.own_criteria] == [c.id for c in provider.criteria(ref)] == list(PROBE_IDS.values())


def test_a_file_match_steering_file_follows_the_tasks_paths_and_the_branchs_changes(tmp_path):
    """SCN-IMP-291."""
    root = probe_tree(tmp_path)
    (root / ".kiro" / "steering" / "calc.md").write_text(
        '---\ninclusion: fileMatch\nfileMatchPattern: ["src/calc/**"]\n---\nCALC-MARKER\n'
    )
    plan = "# Implementation Plan\n\n- [ ] 1. Implement `src/calc/tip.py`\n  - _Requirements: 1.1_\n"
    named, _, _ = probe_inputs(root, tasks_text=plan)
    assert {d["path"]: d["why"] for d in named.steering}[".kiro/steering/calc.md"] == "matched src/calc/tip.py"
    assert [c.path for c in named.conventions] == [".kiro/steering/tech.md", ".kiro/steering/calc.md"]
    other = "# Implementation Plan\n\n- [ ] 1. Document `docs/usage.md`\n  - _Requirements: 1.1_\n"
    unmatched, _, _ = probe_inputs(root, tasks_text=other)
    assert {d["path"]: d["why"] for d in unmatched.steering}[".kiro/steering/calc.md"] == "no_match"
    assert [c.path for c in unmatched.conventions] == [".kiro/steering/tech.md"]
    after_a_commit, _, _ = probe_inputs(root, changed=["src/calc/tip.py"], tasks_text=other)
    assert {d["path"]: d["why"] for d in after_a_commit.steering}[".kiro/steering/calc.md"] == "matched src/calc/tip.py"


def test_a_manual_steering_file_is_referenced_by_the_design_and_an_auto_one_comes_last(tmp_path):
    root = probe_tree(tmp_path)
    steering = root / ".kiro" / "steering"
    (steering / "money.md").write_text("---\ninclusion: manual\n---\nMONEY-MARKER\n")
    (steering / "api.md").write_text("---\ninclusion: auto\nname: api-design\n---\nAPI-MARKER\n")
    (root / UNIT_REL / "design.md").write_text("# Design\nSee #money for the amounts.\n")
    inputs, _, _ = probe_inputs(root)
    assert [c.path.rsplit("/", 1)[1] for c in inputs.conventions] == ["tech.md", "money.md", "api.md"]
    assert {d["path"].rsplit("/", 1)[1]: d["why"] for d in inputs.steering} == {
        "tech.md": "always", "money.md": "referenced", "api.md": "auto"
    }  # fmt: skip


def test_an_openspec_units_context_is_a_convention_and_its_rules_are_not(tmp_path):
    """SCN-IMP-284, prompt part."""
    (tmp_path / "openspec").mkdir()
    (tmp_path / "openspec" / "config.yaml").write_text(
        'context: "Runtime: Python >= 3.11, uv, src layout"\nrules:\n  tasks:\n    - Tasks are TDD-shaped\n'
    )
    unit = tmp_path / "openspec" / "changes" / "add-x"
    unit.mkdir(parents=True)
    (unit / "tasks.md").write_text("## 1. Group\n\n- [ ] 1.1 Add `apply_discount`\n")
    (unit / "proposal.md").write_text("## Why\nBecause.\n")
    ref = UnitRef(Framework.OPENSPEC, "add-x", unit)
    tasks = parse_openspec_tasks((unit / "tasks.md").read_bytes())
    inputs = prompt_inputs(
        root=tmp_path, provider=Plain(tmp_path), ref=ref, task=tasks[0], tasks=tasks, changed=[], cfg=cfg_of(),
        profile_name=None, profile=None,
    )  # fmt: skip
    assert [(c.path, c.kind, c.readable) for c in inputs.conventions] == [
        ("openspec/config.yaml#context", "openspec_context", True)
    ]
    ctx = PromptContext(
        unit_id="openspec:add-x", adapter="codex", task_key="1.1", task_title=tasks[0].title, criteria=(),
        gate_command=GATE, source_files=inputs.source_files, conventions=inputs.conventions,
        task_block=inputs.task_block, unit_rel=inputs.unit_rel,
    )  # fmt: skip
    text = render_prompt("red", ctx).text
    assert block(text, "openspec/config.yaml#context") == "Runtime: Python >= 3.11, uv, src layout"
    assert "TDD-shaped" not in text and text.index("# Project conventions") < text.index("# Unit context")
    assert block(text, "openspec/changes/add-x/tasks.md").startswith("## 1. Group\n- [ ] 1.1 Add `apply_discount`")


def test_agents_md_is_a_convention_only_when_asked_for_and_never_claude_md(tmp_path):
    """Owner decision 3: `implementer.include_agents_md`, the root `AGENTS.md` only."""
    root = probe_tree(tmp_path)
    (root / "AGENTS.md").write_text("AGENTS-MARKER: run the formatter.\n")
    (root / "CLAUDE.md").write_text("CLAUDE-MARKER\n")
    (root / "docs").mkdir()
    (root / "docs" / "AGENTS.md").write_text("NESTED-MARKER\n")
    off, _, _ = probe_inputs(root)
    assert "AGENTS.md" not in {d["path"] for d in off.steering} and len(off.conventions) == 1
    on, _, _ = probe_inputs(root, cfg=cfg_of(include_agents_md=True))
    assert [(c.path, c.kind, c.readable) for c in on.conventions] == [
        (".kiro/steering/tech.md", "steering", False), ("AGENTS.md", "agents_md", True)
    ]  # fmt: skip
    assert {"path": "AGENTS.md", "inclusion": "agents_md", "included": True, "why": "include_agents_md"} in on.steering
    assert "CLAUDE-MARKER" not in "".join(c.text for c in on.conventions)
    assert "NESTED-MARKER" not in "".join(c.text for c in on.conventions)
    (root / "AGENTS.md").unlink()
    (root / "AGENTS.md").symlink_to(root / "CLAUDE.md")
    linked, _, _ = probe_inputs(root, cfg=cfg_of(include_agents_md=True))
    assert {"path": "AGENTS.md", "inclusion": "none", "included": False, "why": "symlink"} in linked.steering
    assert len(linked.conventions) == 1


def test_a_fix_units_linked_criteria_come_from_its_own_items(tmp_path):
    root = probe_tree(tmp_path)
    provider = KiroProvider(root)
    (ref,) = provider.list_units()
    family = provider.criteria(ref)
    tasks = provider.tasks(ref)
    plain = Plain(root, criteria=family, own=family[:1])
    inputs = prompt_inputs(
        root=root, provider=plain, ref=ref, task=tasks[0], tasks=tasks, changed=[], cfg=cfg_of(), profile_name=None,
        profile=None,
    )  # fmt: skip
    assert [c.id for c in inputs.criteria] == list(PROBE_IDS.values())  # the family's list is the fallback
    assert [c.id for c in inputs.own_criteria] == [PROBE_IDS["1.1"]]
    ctx = probe_ctx(root, own_criteria=inputs.own_criteria, task_links=("1.1", "1.2"))
    listed = block(render_prompt("red", ctx).text, "criteria")
    assert PROBE_IDS["1.1"] in listed and PROBE_IDS["1.2"] not in listed


def test_a_task_that_is_not_the_one_at_its_line_gets_no_block(tmp_path):
    """A dry run reads the checkout's `tasks.md`: when it is not the file the task came from, the title stands alone."""
    from dataclasses import replace

    root = probe_tree(tmp_path)
    provider = KiroProvider(root)
    (ref,) = provider.list_units()
    (task,) = provider.tasks(ref)
    inputs = prompt_inputs(
        root=root, provider=provider, ref=ref, task=replace(task, title="1. Another task"), tasks=[task], changed=[],
        cfg=cfg_of(), profile_name=None, profile=None,
    )  # fmt: skip
    assert inputs.task_block == ""
