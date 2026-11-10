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


CACHE_RESIDUAL = "stays shared read-write for v1 and v2 alike"
BYPASSES = ('`"opencode2" api`', "`FOO=1 opencode2`", "`command`", "`exec`", "`timeout`", "`nohup`", "backslash")


def test_the_cache_home_is_named_as_a_residual_where_the_private_homes_are_claimed() -> None:
    spec = read("docs", "SPEC.md")
    parts = {
        "L4-OCV-018": spec.split("**L4-OCV-018 ", 1)[1].split("**L4-OCV-019 ", 1)[0],
        "L4-SEC-005": spec.split("**L4-SEC-005 ", 1)[1].split("**L4-SEC-006 ", 1)[0],
        "runbook 10.9": sections()["runbook 10.9"].replace("\n ", " ").replace("\n", " "),
        "design": read("openspec", "changes", "opencode-v2-current", "design.md").replace("\n  ", " "),
    }
    for name, text in parts.items():
        flat = " ".join(text.split())
        assert "a per-unit cache is a follow-up" in flat and CACHE_RESIDUAL in flat, name
    assert "no longer shares its data with other runs" not in read("CHANGELOG.md")


def test_the_stale_no_full_unit_sentence_is_gone_and_the_run_is_stated() -> None:
    for parts in (("CHANGELOG.md",), ("docs", "SPEC.md"), ("docs", "runbook.md"),
                  ("openspec", "changes", "opencode-v2-current", "design.md")):  # fmt: skip
        text = " ".join(read(*parts).split())
        assert "no full l4 unit has run" not in text.lower(), parts
        assert "no full L4 unit on v2" not in text, parts
    for text in (sections()["runbook 10.9"], read("CHANGELOG.md")):
        flat = " ".join(text.split())
        assert "`opencode/glm-5.3-flash-free`" in flat and "from intake to PASS and in_review" in flat


def test_the_cli_deny_docs_list_the_known_bypasses_and_call_the_sandbox_the_boundary() -> None:
    spec = read("docs", "SPEC.md")
    texts = {
        "L4-OCV-016": spec.split("**L4-OCV-016 ", 1)[1].split("**L4-OCV-017 ", 1)[0],
        "runbook 10.9": sections()["runbook 10.9"],
        "design": read("openspec", "changes", "opencode-v2-current", "design.md"),
    }
    for name, text in texts.items():
        flat = " ".join(text.split())
        assert all(word in flat for word in BYPASSES), name
        assert "a guard" in flat and "boundary" in flat, name
