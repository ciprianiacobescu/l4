"""The docs of ci-evidence (L4-VER-061 to L4-VER-064, L4-SEC-040, L4-IMP-080, L4-IMP-081, L4-OPS-023)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def read(*parts: str) -> str:
    return ROOT.joinpath(*parts).read_text(encoding="utf-8")


def flat(text: str) -> str:
    return " ".join(text.replace("`", "").split())


def in_order(text: str, markers: list[str]) -> bool:
    positions = [text.index(m) for m in markers]
    return positions == sorted(positions)


def test_the_spec_has_the_requirements_and_scenarios() -> None:
    spec = read("docs", "SPEC.md")
    assert in_order(spec, [f"**L4-VER-06{n} " for n in (1, 2, 3, 4)]) and spec.index("**L4-VER-064 ") < spec.index(
        "**L4-VER-015 "
    )
    assert spec.index("**L4-SEC-039") < spec.index("**L4-SEC-040 ")
    assert in_order(spec, ["**L4-IMP-079**", "**L4-IMP-080**", "**L4-IMP-081**"])
    assert spec.index("**L4-OPS-022**") < spec.index("**L4-OPS-023**")
    assert in_order(spec, [f"#### SCN-VER-{n} " for n in range(217, 232)])
    assert spec.index("#### SCN-VER-169 ") < spec.index("#### SCN-VER-217 ")
    assert in_order(spec, [f"#### SCN-SEC-{n} " for n in range(100, 104)])
    assert in_order(spec, [f"#### SCN-IMP-{n} " for n in range(396, 400)]) and spec.index(
        "#### SCN-IMP-399 "
    ) < spec.index("### 23.8")
    assert spec.index("#### SCN-OPS-39 ") < spec.index("#### SCN-OPS-40 ")
    assert in_order(spec, [f"#### SCN-OPS-{n} " for n in range(40, 45)])
    assert "| 62 | `ci-evidence` |" in spec
    section = spec.split("### 12.1", 1)[1]
    assert "failed_step" in section and "gate_env_ci" in section
    assert "L4-SEC-040" in spec.split("**L4-SEC-001**", 1)[1].split("**L4-SEC-002", 1)[0]
    assert "No colour variable" in flat(spec.split("**L4-SEC-040 ", 1)[1].split("\n\n", 1)[0])


def test_the_runbook_says_what_the_fix_unit_gets() -> None:
    runbook = read("docs", "runbook.md")
    paragraph = runbook.split("**Your own CI is red on the hand-off commit:**", 1)[1].split(
        "**Your own CI did not run", 1
    )[0]
    text = flat(paragraph)
    for needle in (
        "failing step",
        "failed_step",
        "GITHUB_ACTIONS",
        "GITLAB_CI",
        "no colour variable is passed",
        "CI=true l4 run",
        "ci_not_fixed",
        "again:",
    ):
        assert needle in text, needle


def test_the_runbook_names_ci_not_fixed() -> None:
    runbook = read("docs", "runbook.md")
    assert (
        "`no_convertible_finding`, `no_fix_units`" in runbook
        and "`same_failure`, `verifier_errors`, `ci_not_fixed`" in runbook
    )
    row = next(line for line in runbook.splitlines() if line.startswith("| `ci_not_fixed` |"))
    text = flat(row)
    for needle in (
        "failed again on the hand-off commit",
        "a commit of your own",
        "conftest.py",
        "l4 feedback add",
        "l4 retry",
        "flaky",
    ):
        assert needle in text, needle


def test_the_skill_says_it() -> None:
    operate = read("plugins", "l4", "skills", "l4", "references", "operate.md")
    row = next(line for line in operate.splitlines() if line.startswith("| `repository CI failed: <job>`"))
    text = flat(row)
    for needle in ("failing step", "CI, GITHUB_ACTIONS", "ci_not_fixed"):
        assert needle in text, needle
    bullet = flat(operate.split("**Escalated with `ci_not_fixed`**", 1)[1].split("\n- **", 1)[0])
    for needle in ("commit of your own", "l4 feedback add", "l4 retry", "flaky"):
        assert needle in bullet, needle
    control = read("plugins", "l4", "skills", "l4", "references", "control-loop.md")
    assert "ci_not_fixed" in next(line for line in control.splitlines() if line.startswith("| `escalated` |"))


def test_the_changelog_names_the_change() -> None:
    changelog = read("CHANGELOG.md")
    section = changelog.split("## 0.4.21 (unreleased)", 1)[1].split("## 0.4.20 (", 1)[0]
    text = flat(section)
    for needle in (
        "failed_step",
        "GITHUB_ACTIONS",
        "gate_env_ci",
        "after_script",
        "Process completed",
        "ci_not_fixed",
        "changed a project file",
        "has no branch on origin",
    ):
        assert needle in text, needle
    assert "### Changed" in section and "### Fixed" in section
    assert changelog.index("## 0.4.21 (unreleased)") < changelog.index("## 0.4.20 (")
