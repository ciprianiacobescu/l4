"""The docs of opencode-v2-current: OpenCode 2 is supported on its live-checked pin (L4-OCV-013, L4-OCV-019,
SCN-OCV-48)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RECORDED_ROWS = {"U2": "live-tools-permission", "U5": "live-cli-disturbed", "U7": "live-bounded", "U9": "live-bounded",
                 "U11": "live-implement"}  # fmt: skip
OPEN_ROWS = {"U1": "status_only", "U3": "provider_refused", "U4": "auth_by_status", "U6": "deny_skill_and_mask",
             "U10": "harness_interrupt"}  # fmt: skip


def read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def rows(text: str) -> dict[str, str]:
    """The table rows of `text` keyed by their first cell (`U1` ... `U11`)."""
    found: dict[str, str] = {}
    for line in text.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if line.startswith("| U") and cells[0][1:].isdigit():
            found[cells[0]] = line
    return found


def sections() -> dict[str, str]:
    spec = read("docs", "SPEC.md")
    runbook = read("docs", "runbook.md")
    return {
        "L4-OCV-013": spec.split("**L4-OCV-013 ", 1)[1].split("**L4-OCV-014 ", 1)[0],
        "runbook 10.9": runbook.split("### 10.9 ", 1)[1].split("\n## 11. ", 1)[0],
    }


def test_scn_ocv_48_the_spec_and_the_runbook_name_each_fallback_that_stays() -> None:
    for name, text in sections().items():
        table = rows(text)
        assert sorted(table, key=lambda key: int(key[1:])) == [f"U{n}" for n in range(1, 12)], name
        for row, fixture in RECORDED_ROWS.items():
            assert "[V]" in table[row] and f"`{fixture}`" in table[row], (name, row)
        for row, fallback in OPEN_ROWS.items():
            assert "[U]" in table[row] and f"`{fallback}`" in table[row] and "[V]" not in table[row], (name, row)
        assert "[U] for a profile with a stored login" in table["U8"] and "`live_coexistence`" in table["U8"], name


def test_neither_text_calls_the_adapter_experimental() -> None:
    parts = sections()
    assert "experimental" not in parts["runbook 10.9"].lower()
    assert (
        "experimental"
        not in parts["L4-OCV-013"].split("The rows, after the live check", 1)[1].split("Version 0.4.28", 1)[0]
    )
    runbook = read("docs", "runbook.md")
    assert "### 10.9 OpenCode v2\n" in runbook and "(#109-opencode-v2-experimental)" not in runbook
    assert "(#109-opencode-v2)" in runbook


def test_the_runbook_pins_2_2_6_and_keeps_the_stored_login_rule_for_a_stored_login_only() -> None:
    section = sections()["runbook 10.9"]
    assert "@opencode/cli@2.2.6" in section and "2.0.32" not in section
    assert "This rule applies\n  to a stored login only." in section
    assert "`worktree_remove`" in section and "`skill`" in section and "`*bin/opencode*`" in section
    assert "`provider.no-route`" in section or "(provider.no-route)" in section
