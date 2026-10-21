"""Suggestions for a red base (M1.8 A2/A3): sentences naming a config edit, derived from facts."""

from l4.config.schema import L4Config
from l4.gates.dryrun import GateDryRun, GateRun, narrow_ruff
from l4.gates.pyproject import PyProject
from l4.gates.suggest import suggestions

PROJECT = PyProject(
    True, "demo", ("click",),
    {"dev": ("pytest", "ruff"), "index": ("chromadb", "tantivy"), "embed": ("torch", "sentence_transformers")},
    {}, True, False,
)  # fmt: skip


def cfg(setup: str = "uv sync --frozen --extra dev") -> L4Config:
    return L4Config.model_validate(
        {"gates": {"setup": [setup], "lint": ["ruff check ."], "test": {"command": "pytest"}}}
    )


def dry(*runs: GateRun) -> GateDryRun:
    return GateDryRun("a" * 40, "bwrap", runs)


def test_missing_module_suggests_the_extra():
    run = GateRun("test", "pytest", "fail", "exit code 1", "", ("tests.test_a::test_x",), ("x",), ("chromadb",), 1, 2)
    [hint] = suggestions(cfg(), PROJECT, dry(run))
    assert "chromadb (extra index)" in hint and "uv sync --frozen --extra dev --extra index" in hint
    assert "embed" not in hint and "--all-extras" not in hint  # the heavy extra is never suggested


def test_a_module_no_extra_provides_suggests_no_extra():
    run = GateRun("test", "pytest", "fail", "exit code 1", "", (), (), ("xattr",), 1, 2)
    assert suggestions(cfg(), PROJECT, dry(run)) == []


def test_the_import_name_maps_to_its_distribution():
    project = PyProject(True, "demo", (), {"io": ("pyyaml",)}, {}, True, False)
    run = GateRun("test", "pytest", "fail", "exit code 1", "", (), (), ("yaml",), 1, 2)
    [hint] = suggestions(cfg("uv sync"), project, dry(run))
    assert "yaml (extra io)" in hint and "uv sync --extra io" in hint


def test_failing_ruff_suggests_select_f_e9_when_it_passes():
    narrowed = narrow_ruff("ruff check .")
    assert narrowed == "ruff check --select F,E9 ."
    lint = GateRun("lint", "ruff check .", "fail", "exit code 1", "E501", narrowed=narrowed, narrowed_ok=True)
    [hint] = suggestions(cfg(), PROJECT, dry(lint))
    assert "ruff check --select F,E9 ." in hint and "passes" in hint


def test_failing_narrow_ruff_suggests_empty_lint():
    lint = GateRun(
        "lint", "ruff check .", "fail", "exit code 1", "F401", narrowed="ruff check --select F,E9 .", narrowed_ok=False
    )
    [hint] = suggestions(cfg(), PROJECT, dry(lint))
    assert "gates.lint to []" in hint and "even narrowed" in hint


def test_a_lint_that_is_not_ruff_suggests_fixing_or_emptying_it():
    assert narrow_ruff("eslint .") is None and narrow_ruff("ruff check --select E .") is None
    [hint] = suggestions(cfg(), PROJECT, dry(GateRun("lint", "eslint .", "fail", "exit code 1")))
    assert "fix its findings" in hint and "[]" in hint


def test_failing_base_tests_suggest_fix_or_deselect():
    run = GateRun("test", "pytest", "fail", "exit code 1", "", ("tests.test_a::test_x", "tests.test_b.TestC::test_y"))
    [hint] = suggestions(cfg(), PROJECT, dry(run))
    assert "2 test(s) fail at the base" in hint and "every verification FAILs step 3" in hint
    assert "--deselect tests/test_a.py::test_x" in hint
    assert "TestC" not in hint  # a class-based id is not guessed into a node id


def test_a_green_dry_run_has_nothing_to_suggest():
    assert suggestions(cfg(), PROJECT, dry(GateRun("test", "pytest", "pass"))) == []


def test_lint_advice_narrows_paths_before_dropping_lint():
    """M1.8 live F3: `--select F,E9 .` still failed (a vendored or generated directory), and the advice said to empty
    gates.lint. The same command on the source and test directories passes: that is the advice."""
    rule = "ruff check --select F,E9 ."
    paths = "ruff check --select F,E9 src tests"
    lint = GateRun(
        "lint", "ruff check .", "fail", "exit code 1", "F401", narrowed=rule, narrowed_ok=False,
        narrowed_paths=paths, narrowed_paths_ok=True,
    )  # fmt: skip
    [hint] = suggestions(cfg(), PROJECT, dry(lint))
    assert hint == (
        f"lint `ruff check .` fails even narrowed to F,E9; on the source and test directories (`{paths}`) it passes: "
        "use that in gates.lint"
    )
    both = GateRun(
        "lint", "ruff check .", "fail", "exit code 1", "F401", narrowed=rule, narrowed_ok=False,
        narrowed_paths=paths, narrowed_paths_ok=False,
    )  # fmt: skip
    [old] = suggestions(cfg(), PROJECT, dry(both))
    assert "fails even narrowed" in old and "gates.lint to []" in old  # the old text stays when this run fails too
    unrun = GateRun("lint", "ruff check .", "fail", "exit code 1", "F401", narrowed=rule, narrowed_ok=False)
    assert "gates.lint to []" in suggestions(cfg(), PROJECT, dry(unrun))[0]
