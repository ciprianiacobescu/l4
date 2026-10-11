"""The hosted-runner path is documented where an adopter looks for it (hosted-runner-setup task 3.2)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    following = text.find("\n#", start + len(heading))
    return text[start : following if following != -1 else len(text)]


def test_hosted_section_names_the_variable_and_the_root_step() -> None:
    quickstart = (ROOT / "docs" / "quickstart.md").read_text(encoding="utf-8")
    hosted = _section(quickstart, "**GitHub-hosted")
    for needle in (
        "L4_SELF_PROVISION",
        ".l4/bin/l4-setup",
        "kernel.apparmor_restrict_unprivileged_userns=0",
        "L4_PROVISION_ROOT=0",
        "cache",
    ):
        assert needle in hosted, needle
    github = _section(quickstart, "### GitHub")
    for needle in ("environment", "ci.github_environment", "L4_FORGE_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN"):
        assert needle in github, needle
    assert "repository secret" not in github  # secrets belong to the environment (L4-PRV-027)

    runner = (ROOT / "docs" / "runner" / "README.md").read_text(encoding="utf-8")
    policy = _section(runner, "## Root steps on runners nobody prepared")
    for needle in ("l4-setup", "sysctl", "disposable", "L4_PROVISION_ROOT=0", "doctor --fix"):
        assert needle in policy, needle
