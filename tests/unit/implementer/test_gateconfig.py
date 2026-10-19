"""What gate and runner configuration is, and what counts as a change to it (L4-IMP-040, design D6 and D6.1)."""

import json
from pathlib import Path

import pytest

from l4.config.schema import L4Config
from l4.implementer.gateconfig import GateConfig


def config(tmp_path: Path, **gates: object) -> GateConfig:
    return GateConfig.of(L4Config.model_validate({"version": 1, "gates": gates}), tmp_path)


@pytest.fixture
def gc(tmp_path: Path) -> GateConfig:
    return config(tmp_path)


PYPROJECT = """\
[project]
name = "x"
dependencies = ["requests"]

[tool.ruff]
line-length = 100
select = ["E", "F"]

[tool.mypy]
strict = true

[tool.pytest.ini_options]
pythonpath = ["src"]
markers = ["slow: slow tests"]
"""


def change(gc: GateConfig, path: str, before: str | None, after: str | None) -> dict:
    return gc.changed(path, None if before is None else before.encode(), None if after is None else after.encode())


# --- what a path is ---


@pytest.mark.parametrize(
    ("path", "kinds"),
    [
        ("mypy.ini", {"gate"}),
        ("packages/api/ruff.toml", {"gate"}),
        ("pyrightconfig.json", {"gate"}),
        ("biome.jsonc", {"gate"}),
        (".prettierrc.yaml", {"gate"}),
        (".gitleaksignore", {"gate"}),
        ("pytest.ini", {"runner"}),
        (".coveragerc", {"runner"}),
        ("web/jest.config.ts", {"runner"}),
        ("pyproject.toml", {"gate", "runner"}),
        ("packages/api/pyproject.toml", {"gate", "runner"}),
        ("package.json", {"gate", "runner"}),
        ("uv.lock", set()),
        ("README.md", set()),
        ("src/app.py", set()),
    ],
)
def test_kinds_of_a_path(gc, path, kinds):
    assert gc.kinds(path) == frozenset(kinds)


def test_a_name_in_both_lists_counts_as_runner_configuration(tmp_path):
    cfg = L4Config.model_validate({"version": 1, "tdd": {"extra_gate_config_globs": ["jest.config.*"]}})
    assert GateConfig.of(cfg, tmp_path).kinds("jest.config.js") == frozenset({"runner"})


def test_extra_gate_config_globs_count(tmp_path):
    cfg = L4Config.model_validate({"version": 1, "tdd": {"extra_gate_config_globs": ["lint/**"]}})
    assert GateConfig.of(cfg, tmp_path).kinds("lint/rules.txt") == frozenset({"gate"})


# --- whole files ---


def test_a_whole_file_is_compared_by_its_bytes(gc):
    assert change(gc, "mypy.ini", "[mypy]\n", "[mypy]\nignore_errors = True\n") == {"gate": ("",)}
    assert change(gc, "mypy.ini", "[mypy]\n", "[mypy]\n") == {}
    assert change(gc, "mypy.ini", None, "[mypy]\n") == {"gate": ("",)}  # a new file
    assert change(gc, "mypy.ini", "[mypy]\n", None) == {"gate": ("",)}  # a deleted one
    assert change(gc, ".coveragerc", "[run]\n", "[run]\nomit = *\n") == {"runner": ("",)}


def test_lock_files_and_other_files_are_free(gc):
    assert change(gc, "uv.lock", "a", "b") == {} and change(gc, "src/app.py", "a", "b") == {}


# --- pyproject.toml ---


def test_a_gate_section_change_is_the_gate_kind(gc):
    after = PYPROJECT.replace("strict = true", "strict = false")
    assert change(gc, "pyproject.toml", PYPROJECT, after) == {"gate": ("tool.mypy",)}


def test_an_added_ruff_ignore_is_a_change_of_tool_ruff(gc):
    after = PYPROJECT + '\n[tool.ruff.lint]\nignore = ["ALL"]\n'
    assert change(gc, "pyproject.toml", PYPROJECT, after) == {"gate": ("tool.ruff",)}


def test_scn_imp_247_a_comment_and_a_key_reorder_are_no_change(gc):
    after = PYPROJECT.replace(
        'line-length = 100\nselect = ["E", "F"]', '# keep it short\nselect = ["E", "F"]\nline-length = 100'
    )
    assert after != PYPROJECT
    assert change(gc, "pyproject.toml", PYPROJECT, after) == {}


def test_dependency_and_project_sections_are_free(gc):
    after = PYPROJECT.replace('dependencies = ["requests"]', 'dependencies = ["requests", "pytest-mock"]')
    after += '\n[dependency-groups]\ndev = ["pytest-mock"]\n\n[tool.uv]\ndev-dependencies = []\n'
    assert change(gc, "pyproject.toml", PYPROJECT, after) == {}


def test_a_runner_section_change_is_the_runner_kind(gc):
    after = PYPROJECT.replace('pythonpath = ["src"]', 'pythonpath = ["src"]\naddopts = "-p l4hooks"')
    assert change(gc, "pyproject.toml", PYPROJECT, after) == {"runner": ("tool.pytest",)}


def test_a_step_that_changes_both_kinds_gets_both(gc):
    after = PYPROJECT.replace("strict = true", "strict = false").replace('pythonpath = ["src"]', "pythonpath = []")
    assert change(gc, "pyproject.toml", PYPROJECT, after) == {"gate": ("tool.mypy",), "runner": ("tool.pytest",)}


def test_scn_imp_246_a_configuration_file_in_a_subdirectory_counts(gc):
    assert change(gc, "packages/api/ruff.toml", None, "line-length = 1\n") == {"gate": ("",)}
    after = PYPROJECT.replace("strict = true", "strict = false")
    assert change(gc, "packages/api/pyproject.toml", PYPROJECT, after) == {"gate": ("tool.mypy",)}


def test_a_file_that_stops_parsing_counts_as_changed_in_every_kind(gc):
    broken = PYPROJECT.replace("[tool.mypy]", "[tool.mypy")
    assert change(gc, "pyproject.toml", PYPROJECT, broken) == {"gate": ("",), "runner": ("",)}
    assert change(gc, "pyproject.toml", broken, PYPROJECT) == {"gate": ("",), "runner": ("",)}


def test_a_file_that_parses_at_neither_end_is_compared_by_its_bytes(gc):
    one, two = "[tool.mypy\n", "[tool.mypy\nstrict\n"
    assert change(gc, "pyproject.toml", one, two) == {"gate": ("",), "runner": ("",)}
    assert change(gc, "pyproject.toml", one, one) == {}


# --- the pytest `markers` exception (owner decision 5) ---


def test_new_marker_entries_in_pyproject_are_no_change(gc):
    after = PYPROJECT.replace(
        'markers = ["slow: slow tests"]', 'markers = ["slow: slow tests", "db: needs a database"]'
    )
    assert change(gc, "pyproject.toml", PYPROJECT, after) == {}
    first = PYPROJECT.replace('markers = ["slow: slow tests"]\n', "")
    assert change(gc, "pyproject.toml", first, PYPROJECT) == {}  # the first marker, the key did not exist


def test_a_removed_or_changed_marker_is_a_change(gc):
    removed = PYPROJECT.replace('markers = ["slow: slow tests"]', "markers = []")
    assert change(gc, "pyproject.toml", PYPROJECT, removed) == {"runner": ("tool.pytest",)}
    renamed = PYPROJECT.replace("slow: slow tests", "slow: ignore this")
    assert change(gc, "pyproject.toml", PYPROJECT, renamed) == {"runner": ("tool.pytest",)}


def test_a_new_marker_together_with_another_runner_key_is_a_change(gc):
    after = PYPROJECT.replace(
        'markers = ["slow: slow tests"]', 'markers = ["slow: slow tests", "db: x"]\nasyncio_mode = "auto"'
    )
    assert change(gc, "pyproject.toml", PYPROJECT, after) == {"runner": ("tool.pytest",)}


PYTEST_INI = "[pytest]\npythonpath = src\nmarkers =\n    slow: slow tests\n"


def test_markers_in_pytest_ini_setup_cfg_and_tox_ini(gc):
    more = PYTEST_INI + "    db: needs a database\n"
    assert change(gc, "pytest.ini", PYTEST_INI, more) == {}
    assert change(gc, "pytest.ini", PYTEST_INI, PYTEST_INI.replace("    slow: slow tests\n", "")) == {
        "runner": ("pytest",)
    }
    assert change(gc, "pytest.ini", PYTEST_INI, PYTEST_INI + "addopts = -p l4hooks\n") == {"runner": ("pytest",)}
    assert (
        change(
            gc, "setup.cfg", PYTEST_INI.replace("[pytest]", "[tool:pytest]"), more.replace("[pytest]", "[tool:pytest]")
        )
        == {}
    )
    assert change(gc, "tox.ini", PYTEST_INI, more) == {}
    assert change(gc, "tox.ini", PYTEST_INI, PYTEST_INI + "asyncio_mode = auto\n") == {"runner": ("pytest",)}


# --- setup.cfg, tox.ini, package.json ---


def test_ini_manifests_guard_their_gate_and_runner_sections_only(gc):
    base = "[mypy]\nstrict = True\n\n[coverage:run]\nbranch = True\n\n[metadata]\nname = x\n"
    assert change(gc, "setup.cfg", base, base.replace("strict = True", "strict = False")) == {"gate": ("mypy",)}
    assert change(gc, "setup.cfg", base, base.replace("branch = True", "branch = False")) == {
        "runner": ("coverage:run",)
    }
    assert change(gc, "setup.cfg", base, base.replace("name = x", "name = y")) == {}


def package_json(**extra: object) -> str:
    return json.dumps({"name": "x", "scripts": {"test": "jest", "build": "tsc", "lint": "eslint ."}, **extra})


def test_package_json_sections(tmp_path):
    gc = config(tmp_path, lint=["npm run lint"])
    base = package_json(eslintConfig={"rules": {}}, jest={"bail": 1}, dependencies={"a": "1"})
    new = json.loads(base)
    new["eslintConfig"] = {"rules": {"no-undef": "off"}}
    assert gc.changed("package.json", base.encode(), json.dumps(new).encode()) == {"gate": ("eslintConfig",)}
    new = json.loads(base)
    new["jest"] = {"bail": 0}
    new["scripts"]["test"] = "exit 0"
    assert gc.changed("package.json", base.encode(), json.dumps(new).encode()) == {"runner": ("jest", "scripts.test")}
    new = json.loads(base)
    new["dependencies"]["b"] = "2"
    new["scripts"]["build"] = "echo"  # no gate command runs it
    assert gc.changed("package.json", base.encode(), json.dumps(new).encode()) == {}


# --- D6.1: the script entries a gate command runs ---


def scripts(tmp_path: Path, **gates: object) -> dict:
    return config(tmp_path, **gates).scripts


def test_npm_run_lint_resolves_to_the_package_script_and_its_hooks(tmp_path):
    assert scripts(tmp_path, lint=["npm run lint"]) == {
        "scripts.lint": "gate", "scripts.prelint": "gate", "scripts.postlint": "gate",
    }  # fmt: skip


def test_pnpm_test_and_npm_test_are_runner_scripts(tmp_path):
    runner = {"scripts.test": "runner", "scripts.pretest": "runner", "scripts.posttest": "runner"}
    assert scripts(tmp_path, test={"command": "pnpm test"}) == runner
    assert scripts(tmp_path, test={"command": "npm test"}) == runner
    assert scripts(tmp_path, test={"command": "yarn test"}) == runner


def test_a_shell_script_a_gate_runs_is_gate_configuration(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "typecheck.sh").write_text("mypy src\n")
    assert scripts(tmp_path, typecheck=["sh scripts/typecheck.sh"]) == {"scripts/typecheck.sh": "gate"}
    assert scripts(tmp_path, typecheck=["./scripts/typecheck.sh"]) == {"scripts/typecheck.sh": "gate"}


def test_scn_imp_244_the_script_entries_of_the_two_gate_commands(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "typecheck.sh").write_text("mypy src\n")
    found = scripts(tmp_path, lint=["npm run lint"], typecheck=["sh scripts/typecheck.sh"])
    assert found == {
        "scripts.lint": "gate", "scripts.prelint": "gate", "scripts.postlint": "gate",
        "scripts/typecheck.sh": "gate",
    }  # fmt: skip
    gc = config(tmp_path, lint=["npm run lint"], typecheck=["sh scripts/typecheck.sh"])
    assert gc.kinds("scripts/typecheck.sh") == frozenset({"gate"})
    assert gc.changed("scripts/typecheck.sh", b"mypy src\n", b"") == {"gate": ("",)}
    assert change(gc, "package.json", package_json(), package_json().replace("eslint .", "exit 0")) == {
        "gate": ("scripts.lint",)
    }


def test_the_test_command_through_a_virtualenv_python_resolves_to_nothing(tmp_path):
    assert scripts(tmp_path, test={"command": ".venv/bin/python -m pytest -p no:cacheprovider"}) == {}


def test_make_just_tox_and_poe(tmp_path):
    assert scripts(tmp_path, lint=["make lint"]) == {"Makefile": "gate", "makefile": "gate", "GNUmakefile": "gate"}
    assert scripts(tmp_path, lint=["just lint"]) == {"justfile": "gate", "Justfile": "gate", ".justfile": "gate"}
    assert scripts(tmp_path, lint=["tox -e lint"]) == {"tox.ini": "gate"}
    assert scripts(tmp_path, lint=["uv run poe check"]) == {"tool.poe": "gate"}


def test_tox_and_poe_are_guarded_as_scripts_when_a_gate_runs_them(tmp_path):
    gc = config(tmp_path, lint=["tox -e lint", "uv run poe check"])
    assert gc.changed("tox.ini", b"[testenv]\n", b"[testenv]\ncommands = true\n") == {"gate": ("",)}
    pyproject = '[tool.poe.tasks]\ncheck = "ruff check ."\n'
    assert gc.changed("pyproject.toml", pyproject.encode(), pyproject.replace("ruff check .", "true").encode()) == {
        "gate": ("tool.poe",)
    }
    free = config(tmp_path)  # no gate runs poe: its section is free
    assert free.changed("pyproject.toml", pyproject.encode(), pyproject.replace("ruff check .", "true").encode()) == {}


def test_a_compound_command_is_cut_and_a_command_with_no_known_head_resolves_to_nothing(tmp_path):
    (tmp_path / "check.sh").write_text("true\n")
    assert scripts(tmp_path, lint=["sh -c 'ruff check . && mypy src'"]) == {}
    assert scripts(tmp_path, lint=["sh -c 'ruff check . && sh check.sh'"]) == {"check.sh": "gate"}
    assert scripts(tmp_path, lint=["cargo clippy"]) == {}
    assert scripts(tmp_path, lint=["FOO=1 uv run python check.sh"]) == {"check.sh": "gate"}


def test_a_runner_entry_wins_over_a_gate_one_for_the_same_script(tmp_path):
    found = scripts(tmp_path, lint=["make lint"], test={"command": "make test"})
    assert found["Makefile"] == "runner"
