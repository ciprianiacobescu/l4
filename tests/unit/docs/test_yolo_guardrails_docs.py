"""The docs of yolo-guardrails, part A: the probe bounds (L4-AVL-012, SCN-AVL-21 to SCN-AVL-25)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def test_the_spec_has_the_probe_requirement_and_its_scenarios() -> None:
    spec = read("docs", "SPEC.md")
    assert spec.index("**L4-AVL-011** ") < spec.index("**L4-AVL-012** ")
    positions = [spec.index(f"#### SCN-AVL-{n} ") for n in range(20, 26)]
    assert positions == sorted(positions)
    config = spec.split("availability:\n", 1)[1].split("\n\n", 1)[0]
    assert "probe_step_timeout: 20s" in config
    table = spec.split("**L4-AVL-001** ", 1)[1].split("**L4-AVL-002**", 1)[0]
    assert table.count("probe_step_timeout") >= 3  # the binary, auth and quota rows


def test_the_changelog_has_the_gate_and_the_probe_fix_under_0_4_18() -> None:
    changelog = read("CHANGELOG.md")
    assert "## 0.4.20 (unreleased)" not in changelog
    head = changelog.split("## 0.4.18 (unreleased)", 1)[1].split("\n## ", 1)[0]
    for needle in ("probe_step_timeout", "did not answer within", "OpenCode v2", "unsupported_version"):
        assert needle in head, needle


def test_the_runbook_names_the_probe_timeout() -> None:
    section = read("docs", "runbook.md").split("### 7.4 ", 1)[1].split("### 7.5 ", 1)[0]
    assert "did not answer within" in section and "l4 doctor" in section


# --- part B: the skill, the docs, SPEC and CHANGELOG (L4-SKL-004, L4-YOLO-068..070, L4-CFG-006) -----------------------

import re  # noqa: E402

import click  # noqa: E402

from l4.cli import cli  # noqa: E402

SKILL = ROOT / "plugins" / "l4" / "skills" / "l4"
RUNBOOK_HEAD = "## Delivering a plan: the runbook"
CODE_SPAN = re.compile(r"`(l4 [^`]+)`")


def operate() -> str:
    return (SKILL / "references" / "operate.md").read_text(encoding="utf-8")


def runbook_section() -> str:
    return operate().split(f"\n{RUNBOOK_HEAD}\n", 1)[1].split("\n## ", 1)[0]


def _resolve(words: list[str]) -> tuple[click.Command, list[str]]:
    """As `_resolve` of `test_control_loop_agent_docs.py`."""
    command: click.Command = cli
    rest = list(words)
    while isinstance(command, click.Group) and rest and rest[0] in command.commands:
        command = command.commands[rest.pop(0)]
    return command, rest


def test_operate_starts_with_origin_then_the_runbook_and_the_table() -> None:  # SCN-SKL-09
    text = operate()
    assert text.split("\n## ", 1)[1].startswith("Delivering a plan: the runbook\n")
    section = runbook_section()
    for needle in ("Origin is what counts", "yolo_preflight.py", "at most two rounds", "A person activates"):
        assert needle in section, needle
    steps = [int(n) for n in re.findall(r"(?m)^(\d+)\. ", section)]
    assert steps == list(range(1, 11))
    assert "| Message | Cause | Fix |" in section
    for row in (
        "no plan file .l4/plans/<plan>.json on origin/<base>",
        "<plan>: not admitted, nothing to review",
        "review: --record records what CI and l4 yolo activate read",
        "review: --record: CI reads <unit> on its branch",
        "review: --record needs the plan file and the unit folders committed",
        "review: --record --fresh",
        "CI reviews origin/<base>, not your commits",
        "review: no judge could answer, nothing was recorded",
        "<cli> did not answer within N s (<step> step)",
        "cannot judge",
        "activate: the review of <plan> is stale against origin/<base>",
        "activate: <plan> has not been reviewed",
        "activate: the review is not READY for N item(s)",
        "activate: <plan> is not admitted",
        "activate: plan <other> is already active, waiting or stopped on <target>",
        "accept: acceptance is a person's decision",
        "accept: <subject> was judged not READY on N version(s); 2 are needed",
        "accept: <subject> is BLOCKED",
        "accept: no terminal to ask the plan id on",
        "accept: --force is a person's decision",
        "waive: a waiver is a person's decision",
        "resume: <unit> is still <phase>",
    ):
        assert row in section, row
    assert len([ln for ln in section.splitlines() if ln.startswith("| `")]) == 22


def test_every_command_of_the_runbook_exists() -> None:
    seen = skipped = 0
    for span in CODE_SPAN.findall(runbook_section()):
        command, rest = _resolve(span.split()[1:])
        assert not isinstance(command, click.Group) or not rest or rest[0].startswith(("-", "<")), span
        if command is cli:
            continue
        flags = {opt for param in command.params for opt in getattr(param, "opts", [])}
        words = [w for w in rest if w.startswith("--")]
        if "--force" in words and "--force" not in flags:  # force-accept is not merged yet: skip, and count it
            skipped += 1
            continue
        for word in words:
            assert word.split("=")[0] in flags | {"--help"}, (span, word)
        seen += 1
    assert seen >= 15
    accept = _resolve(["yolo", "accept"])[0]
    has_force = "--force" in {opt for param in accept.params for opt in getattr(param, "opts", [])}
    assert skipped == (0 if has_force else skipped)  # once --force exists, nothing is skipped


def test_the_skill_hands_a_persons_steps_to_a_person() -> None:  # SCN-SKL-10
    skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    rule = skill.split("**Deliver a plan by the runbook.**", 1)[1].split("\n- ", 1)[0]
    assert "scripts/yolo_preflight.py" in rule and "Next:" in rule and "stop" in rule and "--force" in rule
    assert "operate.md" not in rule  # the note test reads the text around the first `operate.md`
    pointer = skill[skill.index("- `references/operate.md`") :].split("\n- ", 1)[0]
    assert pointer.startswith("- `references/operate.md`: delivering a plan (")
    assert "l4 questions" in pointer and "note" in pointer
    steps = {
        int(n): " ".join(body.split())
        for n, body in re.findall(r"(?ms)^(\d+)\. (.*?)(?=^\d+\. |^\S[^\n]*:\n|\Z)", runbook_section())
    }
    assert "A person activates" in steps[9] and 'l4 yolo activate <plan> --reason "<why>"' in steps[9]
    assert "--all --force" in steps[8] and "person" in steps[8]
    plan = (SKILL / "references" / "plan.md").read_text(encoding="utf-8")
    check = plan.split("## Check and fix the review", 1)[1].split("\n## ", 1)[0]
    step5 = check.split("\n5. ", 1)[1].split("\n\n", 1)[0]
    assert "commit and push" in step5 and "--worktree --record" in step5 and "origin/<base>" in step5


def spec_text() -> str:
    return read("docs", "SPEC.md")


def in_order(text: str, markers: list[str]) -> None:
    positions = [text.index(m) for m in markers]
    assert positions == sorted(positions) and len(set(positions)) == len(positions), markers


def test_the_spec_has_the_requirements_and_scenarios_in_order() -> None:
    spec = spec_text()
    in_order(spec, ["**L4-YOLO-056 ", "**L4-YOLO-068 ", "**L4-YOLO-069 ", "**L4-YOLO-070 "])
    yolo = [f"#### SCN-YOLO-{n} " for n in range(177, 192)]
    in_order(spec, ["#### SCN-YOLO-149 ", *yolo, "### 23.21"])
    in_order(spec, ["**L4-CFG-005 ", "**L4-CFG-006 "])
    in_order(spec, ["#### SCN-CFG-04 ", "#### SCN-CFG-05 ", "#### SCN-CFG-06 ", "#### SCN-CFG-07 "])
    in_order(spec, ["**L4-SKL-003** ", "**L4-SKL-004** ", "**L4-SKL-005** "])
    in_order(spec, ["#### SCN-SKL-08 ", *[f"#### SCN-SKL-{n:02d} " for n in range(9, 16)]])
    assert "| 54 | `yolo-guardrails` |" in spec
    row = next(ln for ln in spec.splitlines() if ln.startswith("| `l4 yolo review PLAN"))
    assert "origin/<base>" in row and "--record" in row
    scn58 = spec.split("#### SCN-YOLO-58 ", 1)[1].split("####", 1)[0]
    assert "pushed" in scn58.split("**When**", 1)[0]
    assert "`target_rev`" in spec and "`unit_revs`" in spec


def test_the_yolo_doc_and_the_runbook_say_push_before_record() -> None:
    guide = read("docs", "yolo-mode.md")
    review = guide[guide.index("## The review") : guide.index("## What runs in each CI run")]
    assert "commit, push, then" in review and "origin/<base>" in review and "stale" in review
    runbook = read("docs", "runbook.md")
    refusals = runbook.split("### 12.2 ", 1)[1].split("### 12.2a ", 1)[0]
    assert "is stale against origin/<base>" in refusals
    procedure = runbook.split("### 12.2a ", 1)[1].split("### 12.2b ", 1)[0]
    assert "commit, push, then `--record`" in procedure
    assert "--record" in procedure and "cannot judge" in runbook


def test_the_changelog_names_the_guardrails() -> None:
    head = read("CHANGELOG.md").split("## 0.4.18 (unreleased)", 1)[1].split("\n## ", 1)[0]
    for needle in ("yolo_preflight.py", "target_rev", "--record", "cannot judge", "warning:"):
        assert needle in head, needle
