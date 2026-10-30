"""The 0.4.22 amendment of the delegate is taught where people look (delegate-answers 28.1; L4-DLG-015..027): the
runbook, the yolo guide, the skill and its references, the quickstart and the README name the four adapters, the
read-only modes, the free-model limit, the hint and how to turn the delegate on."""

import re
from pathlib import Path

from l4.delegate.hint import HINT_TEMPLATE

ROOT = Path(__file__).resolve().parents[3]
SKILL = ROOT / "plugins" / "l4" / "skills" / "l4"
SPEC = (ROOT / "docs" / "SPEC.md").read_text(encoding="utf-8")
PART1, PART2 = SPEC.split("# Part II", 1)


def _read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def _section(text: str, heading: str, level: str = "### ") -> str:
    start = text.index(heading)
    end = text.find("\n" + level, start + len(heading))
    return text[start : end if end != -1 else len(text)]


def _flat(text: str) -> str:
    return " ".join(text.split())


def test_section_9_1_holds_the_requirements_of_the_amendment() -> None:
    section = _section(PART1, "### 9.1 Delegate")
    for n in range(15, 28):
        assert f"**L4-DLG-{n:03d}" in section, n


def test_every_scenario_of_the_amendment_is_in_the_spec() -> None:
    change = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((ROOT / "openspec" / "changes" / "delegate-answers" / "specs").rglob("spec.md"))
    )
    scenarios = set(re.findall(r"Scenario: (SCN-DLG-\d+[a-z]?)", change))
    later = {f"SCN-DLG-{n}" for n in range(116, 127)}  # delegate-citations (0.4.34), delegate-repo-evidence (0.4.35),
    # unfreeze-option-form (0.4.39), delegate-only-pass (0.4.44)
    headings = set(re.findall(r"^#### (SCN-DLG-\d+[a-z]?) ", PART2, re.M)) - later
    assert {f"SCN-DLG-{n}" for n in range(56, 113)} <= scenarios
    assert scenarios == headings, sorted(scenarios ^ headings)
    assert "### 23.27 Delegate (DLG)" in PART2


def test_the_runbook_turns_the_delegate_on_and_names_the_reasons() -> None:
    runbook = _read("docs", "runbook.md")
    procedure = _section(runbook, "**Procedure: the delegate answered or escalated**", "\n**Procedure: the hand edit")
    flat = _flat(procedure)
    for needle in (
        "To turn the delegate on",
        "delegate.enabled",
        "roles.delegate",
        "claude-code",
        "codex",
        "opencode",
        "kiro-cli",
        "read-only",
        "technical and harness questions only",
        "delegate_kinds",
        "Hint:",
        "delegate_hint",
        "model: auto",
        "independence: profile",
        "no delegate profile answers <kind> questions",
        "a fix task cannot change <path>",
        "kiro-cli served <m>, the profile names <p>",
        "the answer would unfreeze <path> of task <k>, a test-support file",
        "final for its raise",
        "docs/runbook.md 7.1",
    ):
        assert needle in flat, needle
    assert HINT_TEMPLATE.format(base="main") in procedure  # the very sentence the commands print
    assert procedure.index("To turn the delegate on") < procedure.index("Read what it did")


def test_the_runbook_known_limits_and_upgrade_lines() -> None:
    runbook = _read("docs", "runbook.md")
    limits = _flat(runbook[runbook.index("## 11. ") : runbook.index("## 12. ")])
    assert "opencode" in limits and "kiro-cli" in limits and "[U]" in limits
    assert "instruction files" in limits and "AGENTS.md" in limits
    assert "`model: auto` vetoes every delegate" in limits
    upgrade = _flat(_section(runbook, "### 7.15 "))
    assert "--harness-commit" in upgrade and "--harness-ref" in upgrade and "tag or a branch" in upgrade
    kiro = _section(runbook, "### 10.6 ")
    assert "delegate role (a later release)" not in kiro


def test_the_yolo_guide_teaches_the_four_adapters_and_the_unfreeze_rule() -> None:
    block = _flat(_section(_read("docs", "yolo-mode.md"), "## The delegate", "\n## "))
    for needle in (
        "L4-DLG-001..027",
        "`claude-code`, `codex`, `opencode` and `kiro-cli`",
        "read-only",
        "technical and harness questions only",
        "delegate_kinds",
        "`Hint:`",
        "delegate_hint",
        "commented-out block",
        "model: auto",
        "final for its raise",
    ):
        assert needle in block, needle
    unfreeze = block[block.index("No unfreezing by default") :][:600]
    assert "frozen **test file** only" in unfreeze and "test-support file" in unfreeze and "fix task" in unfreeze


def test_the_skill_index_points_at_the_delegate() -> None:
    skill = _read("plugins", "l4", "skills", "l4", "SKILL.md")
    where = skill[skill.index("## Where to look next") :]
    bullet = _flat(where[where.index("A delegate") :][:400])
    assert "delegate.enabled" in bullet and "references/operate.md" in bullet and "`Hint:`" in bullet


def test_adopt_has_an_opt_in_step_with_the_block_and_the_rule() -> None:
    adopt = _read("plugins", "l4", "skills", "l4", "references", "adopt.md")
    step = _flat(_section(adopt, "## 4f. The delegate (optional)", "\n## "))
    for needle in (
        "delegate.enabled",
        "roles.delegate",
        "delegate-sonnet",
        "claude-sonnet-5",
        "commented-out block",
        "`opencode`",
        "`kiro-cli`",
        "technical and harness questions only",
        "model: auto",
    ):
        assert needle in step, needle
    assert "`--harness-commit`" in adopt and "tag or a branch" in adopt
    assert adopt.index("## 4f.") < adopt.index("## 5. Upgrades")


def test_the_control_loop_reference_names_the_delegate_and_stays_short() -> None:
    page = _read("plugins", "l4", "skills", "l4", "references", "control-loop.md")
    row = next(line for line in page.splitlines() if line.startswith("| `awaiting_human`"))
    assert "you answer, or the delegate does (`delegate.enabled` on base)" in row
    assert len(page.split()) <= 900


def test_operate_and_plan_teach_how_to_turn_it_on() -> None:
    operate = _flat(_read("plugins", "l4", "skills", "l4", "references", "operate.md"))
    for needle in (
        "`Hint:`",
        "delegate_hint",
        "`delegate.enabled: true`",
        "`claude-code`, `codex`, `opencode` and `kiro-cli`",
        "technical and harness questions only",
        "`model: auto`",
        "final for its raise",
    ):
        assert needle in operate, needle
    plan = _flat(_read("plugins", "l4", "skills", "l4", "references", "plan.md"))
    assert "technical and harness" in plan and "delegate.enabled" in plan


def test_the_quickstart_and_the_readme_name_the_option() -> None:
    quick = _flat(_section(_read("docs", "quickstart.md"), "## Conditional extras", "\n## "))
    for needle in (
        "The delegate (optional)",
        "commented-out",
        "delegate.enabled",
        "`opencode`",
        "technical and harness",
    ):
        assert needle in quick, needle
    readme = _flat(_read("README.md"))
    assert "the delegate, off by default" in readme and "commented-out block" in readme


def test_the_hint_is_the_same_sentence_in_every_place_that_prints_it() -> None:
    sentence = HINT_TEMPLATE.format(base="{base}")
    assert sentence.startswith("Hint: the delegate can answer these questions in CI:")
    assert "docs/runbook.md 7.1" in sentence and "delegate.enabled: true" in sentence and "roles.delegate" in sentence
    surfaces = {
        "l4 questions": ROOT / "src" / "l4" / "specs" / "questions_cli.py",
        "l4 status --unit": ROOT / "src" / "l4" / "state" / "status.py",
        "l4 yolo status": ROOT / "src" / "l4" / "yolo" / "commands.py",
        "the sticky note": ROOT / "src" / "l4" / "clarifier" / "notify.py",
    }
    for name, path in surfaces.items():
        text = path.read_text(encoding="utf-8")
        assert "hint" in text.lower() and "HintReader" in text + (ROOT / "src/l4/clarifier/clarifier.py").read_text(), (
            name
        )
