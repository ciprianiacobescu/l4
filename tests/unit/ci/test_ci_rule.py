"""SCN-CLI-13: no decision reads `GITHUB_ACTIONS` or `GITLAB_CI` outside the one rule (L4-CLI-004)."""

import ast
from pathlib import Path

import l4

NAMES = {"GITHUB_ACTIONS", "GITLAB_CI"}
SRC = Path(l4.__file__).parent
RULE = "ci/detect.py"

# Sites that ask WHICH CI runs (the platform, its own variables, its own API), not whether this is a CI job.
WHICH_CI = {
    "cancel.py": "GitLab's pipeline API",
    "progress.py": "GitHub's artifact upload",
    "exitcodes.py": "the platform named in a hint",
    "ci/pin_guard.py": "GitHub's checkout",
    "ci/relay.py": "GitHub's relay",
    "ci/step_summary.py": "GitHub's step summary",
    "doctor/checks_ci.py": "GitLab's CI checks",
    "state/environment.py": "the CI environment record names the platform",
    "forge/github.py": "GitHub's API answer",
    "forge/pushfail.py": "the platform named in a hint",
    "forge/pushurl.py": "GitLab's runner URL rewrite",
    "forge/base.py": "the forge platform and GitLab's CI API variables",
}


def _name_of(node: ast.expr) -> str | None:
    """The variable a `x.get("NAME")` call or `x["NAME"]` reads, when NAME is one of the two."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get" and node.args:
        arg = node.args[0]
    elif isinstance(node, ast.Subscript):
        arg = node.slice
    else:
        return None
    return arg.value if isinstance(arg, ast.Constant) and arg.value in NAMES else None


def comparisons() -> dict[str, list[int]]:
    found: dict[str, list[int]] = {}
    for path in sorted(SRC.rglob("*.py")):
        relative = path.relative_to(SRC).as_posix()
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Compare) and any(_name_of(n) for n in (node.left, *node.comparators)):
                found.setdefault(relative, []).append(node.lineno)
    return found


def test_scn_cli_13_every_comparison_is_in_the_rule_or_on_the_allowlist() -> None:
    stray = {path: lines for path, lines in comparisons().items() if path != RULE and path not in WHICH_CI}
    assert stray == {}, (
        "a decision 'is this a CI job' must call l4.ci.detect.in_ci_job (or ci_like where CI alone opts in)"
    )


def test_the_allowlist_has_no_stale_entry() -> None:
    found = comparisons()
    assert RULE in found
    assert sorted(set(WHICH_CI) - set(found)) == []
