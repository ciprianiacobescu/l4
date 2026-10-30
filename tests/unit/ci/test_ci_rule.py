"""SCN-CLI-13: no decision reads `GITHUB_ACTIONS` or `GITLAB_CI` outside the one rule (L4-CLI-004)."""

import ast
from collections import Counter
from pathlib import Path

import l4

NAMES = {"GITHUB_ACTIONS", "GITLAB_CI"}
SRC = Path(l4.__file__).parent
RULE = "ci/detect.py"

# Sites that ask WHICH CI runs (the platform, its own variables, its own API), not whether this is a CI job, keyed by
# (file, enclosing function) with the number of reads there: a new read in these files fails unless it is listed.
WHICH_CI = {
    ("cancel.py", "job_over"): (1, "GitLab's pipeline API"),
    ("cancel.py", "start_watchdog"): (1, "GitLab's pipeline API"),
    ("progress.py", "artefacts_note"): (1, "GitHub's artifact upload"),
    ("exitcodes.py", "run_map_exit"): (1, "the platform named in a hint"),
    ("ci/pin_guard.py", "_pin_check"): (1, "GitHub's checkout"),
    ("ci/relay.py", "late_label"): (1, "GitHub's relay"),
    ("ci/relay.py", "early_pin_stop"): (1, "GitHub's relay"),
    ("ci/relay.py", "default_copy_warning"): (1, "GitHub's relay"),
    ("ci/step_summary.py", "step_summary_for"): (1, "GitHub's step summary"),
    ("doctor/checks_ci.py", "_ci_001"): (1, "GitLab's CI checks"),
    ("doctor/checks_ci.py", "_ci_005"): (1, "GitLab's CI checks"),
    ("state/environment.py", "ci_url"): (2, "the CI environment record names the platform"),
    ("forge/github.py", "GitHubForge._identity"): (1, "GitHub's API answer"),
    ("forge/pushfail.py", "explain_push_failure"): (2, "the platform named in a hint"),
    ("forge/pushurl.py", "push_url"): (1, "GitLab's runner URL rewrite"),
    ("forge/pushurl.py", "runner_ext_conf"): (1, "GitLab's runner URL rewrite"),
    ("forge/base.py", "forge_platform"): (2, "which forge the CI variables name"),
    ("forge/base.py", "_gitlab_target"): (1, "GitLab's CI API variables"),
}


def _is_name(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value in NAMES


class _Reads(ast.NodeVisitor):
    """Every read of one of the two variables: `x.get("N")`, `os.getenv("N")`, `getenv("N")`, `x["N"]` and `"N" in x`,
    wherever it stands (a comparison, a truthiness test, an assignment)."""

    def __init__(self) -> None:
        self.scope: list[str] = []
        self.found: list[tuple[str, int]] = []

    def _enter(self, node: ast.AST, name: str) -> None:
        self.scope.append(name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._enter(node, node.name)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._enter(node, node.name)

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    def _hit(self, node: ast.expr | ast.Compare) -> None:
        self.found.append((".".join(self.scope) or "<module>", node.lineno))

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        named = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
        if named in ("get", "getenv") and node.args and _is_name(node.args[0]):
            self._hit(node)
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if _is_name(node.slice):
            self._hit(node)
        self.generic_visit(node)

    def visit_Compare(self, node: ast.Compare) -> None:
        if _is_name(node.left) and any(isinstance(op, ast.In | ast.NotIn) for op in node.ops):
            self._hit(node)
        self.generic_visit(node)


def reads(source: str) -> list[tuple[str, int]]:
    """(enclosing function, line) of each read in `source`."""
    visitor = _Reads()
    visitor.visit(ast.parse(source))
    return visitor.found


def all_reads() -> dict[str, list[tuple[str, int]]]:
    found = {path.relative_to(SRC).as_posix(): reads(path.read_text(encoding="utf-8")) for path in SRC.rglob("*.py")}
    return {path: sites for path, sites in found.items() if sites}


def stray_reads(found: dict[str, list[tuple[str, int]]]) -> dict[tuple[str, str], int]:
    """The (file, function) pairs whose number of reads is not the one the allowlist expects."""
    counts = Counter((path, scope) for path, sites in found.items() if path != RULE for scope, _ in sites)
    return {key: n for key, n in counts.items() if key not in WHICH_CI or WHICH_CI[key][0] != n}


def test_scn_cli_13_every_read_is_in_the_rule_or_on_the_allowlist() -> None:
    stray = stray_reads(all_reads())
    assert stray == {}, "'is this a CI job' is l4.ci.detect.in_ci_job (ci_like where CI alone opts in)"


def test_the_allowlist_has_no_stale_entry() -> None:
    found = all_reads()
    assert RULE in found
    counts = Counter((path, scope) for path, sites in found.items() for scope, _ in sites)
    assert sorted(key for key in WHICH_CI if key not in counts) == []


def test_every_form_of_a_new_read_is_found() -> None:
    """The scan itself: a comparison, `os.getenv`, `in`, a subscript and a truthiness test all count."""
    forms = {
        "compare": 'def f(env):\n    return env.get("GITHUB_ACTIONS") == "true"\n',
        "getenv": 'import os\n\ndef f():\n    return os.getenv("GITLAB_CI")\n',
        "bare getenv": 'from os import getenv\n\ndef f():\n    return getenv("GITLAB_CI")\n',
        "in": 'def f(env):\n    return "GITHUB_ACTIONS" in env\n',
        "not in": 'def f(env):\n    return "GITLAB_CI" not in env\n',
        "subscript": 'def f(env):\n    return env["GITLAB_CI"]\n',
        "truthiness": 'def f(env):\n    if env.get("GITLAB_CI"):\n        return 1\n',
    }
    for form, source in forms.items():
        assert [scope for scope, _ in reads(source)] == ["f"], form
    assert reads('def f(env):\n    return env.get("HOME")\n') == []
    assert reads('GITLAB_CI_RELPATH = ".gitlab-ci.yml"\nNAMES = ("GITLAB_CI",)\n') == []


def test_an_injected_read_in_an_allowlisted_file_fails() -> None:
    """A second read in `forge/base.py` (where the old per-platform rule lived) is not covered by the file."""
    injected = {"forge/base.py": [("forge_platform", 1), ("forge_platform", 2), *reads(INJECTED)]}
    assert stray_reads(injected) == {("forge/base.py", "require_token_in_ci"): 1}
    assert stray_reads({"forge/base.py": [("forge_platform", 1), ("forge_platform", 2), ("forge_platform", 3)]}) == {
        ("forge/base.py", "forge_platform"): 3
    }
    assert stray_reads({"new/module.py": reads(INJECTED)}) == {("new/module.py", "require_token_in_ci"): 1}


INJECTED = 'def require_token_in_ci(env):\n    return env.get("GITHUB_ACTIONS") == "true"\n'
