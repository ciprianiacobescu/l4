"""The docs of yolo-go: `l4 yolo go` (L4-YOLO-080 to L4-YOLO-091, SCN-YOLO-200 to SCN-YOLO-238)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def test_the_spec_has_the_twelve_requirements_and_their_scenarios_in_order() -> None:
    spec = read("docs", "SPEC.md")
    ids = [f"**L4-YOLO-0{n} " for n in range(80, 92)]
    positions = [spec.index(rid) for rid in ids]  # raises when one is missing
    assert positions == sorted(positions)
    assert spec.index("**L4-YOLO-070 ") < positions[0]
    assert spec.index("## 13. Memory and lessons") > positions[-1]
    start, end = spec.index("### 23.20 "), spec.index("### 23.21 ")
    for n in range(200, 239):
        assert start < spec.index(f"#### SCN-YOLO-{n} ") < end, n
    assert "| 55 | `yolo-go` |" in spec


def test_the_spec_names_the_cli_row_the_exit_codes_and_the_mcp_tool() -> None:
    spec = read("docs", "SPEC.md")
    assert "| `l4 yolo go PLAN --reason TEXT " in spec
    cli = spec.split("**L4-CLI-001**", 1)[1].split("**L4-CLI-002**", 1)[0]
    assert "`l4 yolo go`" in cli and "20 to 29" in cli and "L4-YOLO-087" in cli
    mcp = spec.split("**L4-MCP-003**", 1)[1].split("\n\n", 1)[0]
    assert "`l4_plan_go`" in mcp and "judge tokens" in mcp


def test_the_yolo_doc_has_the_section() -> None:  # SCN-YOLO-238
    yolo = read("docs", "yolo-mode.md")
    assert "## One command: `l4 yolo go`" in yolo
    section = yolo.split("## One command: `l4 yolo go`", 1)[1].split("\n## ", 1)[0]
    for code in range(20, 30):
        assert f"| {code} |" in section, code
    assert "l4/yolo-go@1" in section and "`l4 yolo status`" in section
    assert "never runs a person's command" in section and "never fakes a" in section and "activates" in section
    assert yolo.index("## One command: `l4 yolo go`") < yolo.index("## Review in CI, then activate")
    assert "Or step by step:" in yolo.split("## Review in CI, then activate", 1)[1].split("\n", 3)[2]


def test_the_runbook_starts_12_2_with_or_simply() -> None:
    runbook = read("docs", "runbook.md")
    body = runbook.split("### 12.2 Procedure: review and activate a plan", 1)[1].split("### 12.2a ", 1)[0]
    first = body.strip().splitlines()[0]
    assert first.startswith("Or simply: `l4 yolo go <plan-id> --reason")
    assert "20" in body and "29" in body and "a person" in body


def test_the_skill_teaches_go_to_persons_and_agents() -> None:
    operate = read("plugins", "l4", "skills", "l4", "references", "operate.md")
    assert "or simply: l4 yolo go" in operate and "--wait" in operate and "next_command" in operate
    steps = operate.split("## Delivering a plan: the runbook", 1)[1].split("| Message | Cause | Fix |", 1)[0]
    assert (
        "l4 yolo go" in steps
        and "never `--force`" in steps
        and "never run a person's command" in steps
        and "never fake a terminal" in steps
    )
    assert "`l4 yolo go" in operate.split("## Delivery plans (`l4 yolo`)", 1)[1]
    assert "l4 yolo go" in read("plugins", "l4", "skills", "l4", "references", "plan.md").split("## Hand off", 1)[1]


def test_the_changelog_names_go_in_0_4_19() -> None:
    changelog = read("CHANGELOG.md")
    assert changelog.index("## 0.4.19 (") < changelog.index("## 0.4.18 (")
    head = changelog.split("## 0.4.19 (", 1)[1].split("\n## ", 1)[0]
    assert "`l4 yolo go`" in head and "`l4_plan_go`" in head and "20 to 29" in head
    for block in head.split("\n### ")[1:]:
        items = block.split("\n", 1)[1].strip("\n").split("\n- ")
        assert items and all(not item.endswith("\n") for item in items)
        assert "\n\n" not in block.strip("\n"), "a blank line inside a list"
