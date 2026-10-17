"""Gate and runner configuration is put back after every agent step (L4-IMP-040, L4-IMP-006 (3); design D7).

The reviewer's reproductions (implementer-3), ported with their assertions inverted: a change that used to be committed
is now put back to the step base before any gate runs."""

import json
import textwrap

from l4.agents.fake import Step
from l4.implementer.loop import run_task
from l4.implementer.tdd import run_green, run_red
from l4.specs.base import Task

from .conftest import IMPL, STUB, TESTS, green_step, red_step, result

TASK = Task("1.1", "1.1", "1.1 Add `apply_discount`", False, " ", 0, 3, 3)
TYPECHECK = (
    "sh -c 'if grep -q ignore_errors mypy.ini 2>/dev/null; then exit 0; fi; "
    "if grep -q round.amount src/pytdd/pricing.py; then echo error: bad type in impl; exit 1; fi'"
)
LINT = (
    "sh -c 'if grep -q l4-loosened pyproject.toml; then exit 0; fi; "
    "if grep -q LINTBAD tests/test_discount.py; then echo E999 lint error in test; exit 1; fi'"
)


def violations(bench, rule: str) -> list[dict]:
    events = [e.get("data", e) for e in bench.events("guard.violation")]
    return [e for e in events if e.get("rule") == rule]


def commit_base(bench, files: dict[str, str]) -> None:
    for rel, text in files.items():
        target = bench.wb.worktree / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    bench.wb.git.run("add", "-A")
    bench.wb.git.run("commit", "-q", "-m", "configuration of the repository")


def pyproject(bench) -> str:
    return (bench.wb.worktree / "pyproject.toml").read_text()


def committed(bench, rev: str, path: str) -> str | None:
    done = bench.wb.git.run("show", f"{rev}:{path}", check=False)
    return done.stdout if done.returncode == 0 else None


# --- the reproductions of the review ---


def test_scn_imp_240_green_cannot_loosen_mypy_ini_to_pass_its_typecheck_gate(make_bench):
    green = Step(
        writes={"src/pytdd/pricing.py": IMPL, "mypy.ini": "[mypy]\nignore_errors = True\n"},
        structured=result("green"),
    )
    bench = make_bench([red_step(), green], typecheck=[TYPECHECK])
    red = run_red(bench.wb, TASK, attempt=1)
    assert red.status == "ok", red.reason
    out = run_green(bench.wb, TASK, red, attempt=1)
    assert out.status == "failed" and "typecheck" in out.reason  # the gate judged the original settings
    assert not (bench.wb.worktree / "mypy.ini").exists()
    (event,) = violations(bench, "gate configuration")
    assert event["phase"] == "green" and event["path"] == "mypy.ini" and event["action"] == "removed"
    assert bench.wb.head() == red.sha and bench.events("task.done") == []


def test_scn_imp_241_red_cannot_loosen_tool_ruff_in_pyproject_to_pass_its_lint_gate(make_bench):
    bench = make_bench([], lint=[LINT])
    original = pyproject(bench)
    loosened = original + '\n[tool.ruff.lint]\nignore = ["ALL"]  # l4-loosened\n'
    red = Step(
        writes={
            "tests/test_discount.py": TESTS + "\n# LINTBAD\n",
            "src/pytdd/pricing.py": STUB,
            "pyproject.toml": loosened,
        },
        structured=result("red", tests_added=["tests/test_discount.py::test_known_code"]),
    )
    bench.adapter._script.append(red)
    base = bench.wb.head()
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "failed" and "lint" in out.reason  # the lint gate failed on the red test
    assert pyproject(bench) == original and committed(bench, base, "pyproject.toml") == original
    (event,) = violations(bench, "gate configuration")
    assert event["phase"] == "red" and event["path"] == "pyproject.toml" and event["sections"] == ["tool.ruff"]
    assert event["action"] == "restored" and bench.wb.head() == base  # no red commit carries the ignore


HOOK = textwrap.dedent(
    """\
    import pytest


    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(item, call):
        outcome = yield
        report = outcome.get_result()
        if report.failed:
            report.outcome, report.longrepr = "passed", None
    """
)
HOOK_STUB = "def helper() -> int:\n    raise NotImplementedError\n"


def test_scn_imp_242_red_cannot_plant_a_pytest_plugin_through_addopts(make_bench):
    bench = make_bench([])
    original = pyproject(bench)
    planted = original.replace('pythonpath = ["src"]', 'pythonpath = ["src"]\naddopts = "-p l4hooks"')
    assert planted != original
    red = Step(
        writes={
            "tests/test_discount.py": TESTS, "src/pytdd/pricing.py": STUB,
            "pyproject.toml": planted, "l4hooks.py": HOOK_STUB,
        },
        structured=result(
            "red", tests_added=["tests/test_discount.py::test_known_code"], criteria_ids=["C-2d3a8daf", "C-d80f494d"]
        ),
    )  # fmt: skip
    green = Step(writes={"l4hooks.py": HOOK}, structured=result("green"))
    bench.adapter._script.extend([red, green])
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "ok", out.reason
    assert pyproject(bench) == original  # back to the base after red
    (event,) = violations(bench, "runner configuration")
    assert event["phase"] == "red" and event["sections"] == ["tool.pytest"]
    done = run_green(bench.wb, TASK, out, attempt=1)
    assert done.status == "failed" and (bench.wb.worktree / "src/pytdd/pricing.py").read_text() == STUB


def test_scn_imp_26_green_cannot_loosen_tsconfig_or_the_gitleaks_ignore(make_bench):
    bench = make_bench([red_step()])
    commit_base(bench, {"tsconfig.json": '{"compilerOptions": {"strict": true}}\n'})
    green = Step(
        writes={
            "src/pytdd/pricing.py": IMPL,
            "tsconfig.json": '{"compilerOptions": {"strict": false}}\n',
            ".gitleaksignore": "src/\n",
        },
        structured=result("green"),
    )
    bench.adapter._script.append(green)
    red = run_red(bench.wb, TASK, attempt=1)
    assert red.status == "ok", red.reason
    out = run_green(bench.wb, TASK, red, attempt=1)
    assert out.status == "ok", out.reason  # the code is the step; the settings were not
    assert committed(bench, "HEAD", "tsconfig.json") == '{"compilerOptions": {"strict": true}}\n'
    assert committed(bench, "HEAD", ".gitleaksignore") is None
    found = {e["path"]: e["action"] for e in violations(bench, "gate configuration")}
    assert found == {"tsconfig.json": "restored", ".gitleaksignore": "removed"}


# --- scenarios that come with the exact definitions ---


def test_scn_imp_244_a_script_a_gate_command_runs_is_gate_configuration(make_bench):
    bench = make_bench([red_step()], lint=["npm run lint"], typecheck=["sh scripts/typecheck.sh"])
    manifest = json.dumps({"name": "x", "scripts": {"lint": "true", "build": "tsc"}}, indent=1) + "\n"
    commit_base(bench, {"package.json": manifest, "scripts/typecheck.sh": "true\n"})
    loosened = json.dumps({"name": "x", "scripts": {"lint": "exit 0", "build": "tsc"}}, indent=1) + "\n"
    green = Step(
        writes={"src/pytdd/pricing.py": IMPL, "package.json": loosened, "scripts/typecheck.sh": ""},
        structured=result("green"),
    )
    bench.adapter._script.append(green)
    red = run_red(bench.wb, TASK, attempt=1)
    assert red.status == "ok", red.reason
    run_green(bench.wb, TASK, red, attempt=1)
    assert (bench.wb.worktree / "package.json").read_text() == manifest
    assert (bench.wb.worktree / "scripts/typecheck.sh").read_text() == "true\n"
    found = {e["path"]: e for e in violations(bench, "gate configuration")}
    assert sorted(found) == ["package.json", "scripts/typecheck.sh"]
    assert found["package.json"]["sections"] == ["scripts.lint"] and found["scripts/typecheck.sh"]["sections"] == [""]


def test_scn_imp_245_a_new_test_dependency_in_red_stays(make_bench):
    bench = make_bench([])
    original = pyproject(bench)
    added = original.replace('dev = ["pytest>=8"]', 'dev = ["pytest>=8", "pytest-mock"]')
    red = Step(
        writes={
            "tests/test_discount.py": TESTS, "src/pytdd/pricing.py": STUB, "pyproject.toml": added, "uv.lock": "lock\n",
        },
        structured=result("red", tests_added=["tests/test_discount.py::test_known_code"]),
    )  # fmt: skip
    bench.adapter._script.append(red)
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "ok", out.reason
    assert committed(bench, out.sha, "pyproject.toml") == added and committed(bench, out.sha, "uv.lock") == "lock\n"
    assert not violations(bench, "gate configuration") and not violations(bench, "runner configuration")


def test_scn_imp_246_a_configuration_file_in_a_subdirectory_counts(make_bench):
    bench = make_bench([red_step()])
    sub = "[project]\nname = 'api'\n\n[tool.mypy]\nstrict = true\n"
    commit_base(bench, {"packages/api/pyproject.toml": sub})
    green = Step(
        writes={
            "src/pytdd/pricing.py": IMPL, "packages/api/ruff.toml": "line-length = 1\n",
            "packages/api/pyproject.toml": sub.replace("strict = true", "strict = false"),
        },
        structured=result("green"),
    )  # fmt: skip
    bench.adapter._script.append(green)
    red = run_red(bench.wb, TASK, attempt=1)
    run_green(bench.wb, TASK, red, attempt=1)
    assert not (bench.wb.worktree / "packages/api/ruff.toml").exists()
    assert (bench.wb.worktree / "packages/api/pyproject.toml").read_text() == sub
    assert sorted(e["path"] for e in violations(bench, "gate configuration")) == [
        "packages/api/pyproject.toml", "packages/api/ruff.toml",
    ]  # fmt: skip


def test_scn_imp_247_a_comment_and_a_key_reorder_inside_tool_ruff_keep_the_edit(make_bench):
    bench = make_bench([red_step()])
    base = pyproject(bench) + "\n[tool.ruff]\nline-length = 100\nselect = ['E']\n"
    commit_base(bench, {"pyproject.toml": base})
    edited = base.replace("line-length = 100\nselect = ['E']", "# tidy\nselect = ['E']\nline-length = 100")
    bench.adapter._script.append(
        Step(writes={"src/pytdd/pricing.py": IMPL, "pyproject.toml": edited}, structured=result("green"))
    )
    red = run_red(bench.wb, TASK, attempt=1)
    out = run_green(bench.wb, TASK, red, attempt=1)
    assert out.status == "ok", out.reason
    assert pyproject(bench) == edited
    assert not violations(bench, "gate configuration") and not violations(bench, "runner configuration")


def test_scn_imp_248_green_cannot_change_a_runner_setting_even_with_a_test_infra_tag(make_bench):
    task = Task("1.1", "1.1", "1.1 [test-infra] Make the async tests run", False, " ", 0, 3, 3)
    bench = make_bench([red_step()])
    original = pyproject(bench)
    edited = original.replace('pythonpath = ["src"]', 'pythonpath = ["src"]\nasyncio_mode = "auto"')
    bench.adapter._script.append(
        Step(writes={"src/pytdd/pricing.py": IMPL, "pyproject.toml": edited}, structured=result("green"))
    )
    red = run_red(bench.wb, task, attempt=1)
    out = run_green(bench.wb, task, red, attempt=1)
    assert out.status == "ok", out.reason
    assert pyproject(bench) == original  # the freeze red to green holds for every task
    (event,) = violations(bench, "runner configuration")
    assert event["phase"] == "green" and event["sections"] == ["tool.pytest"]


def test_a_step_that_changes_both_kinds_gets_one_violation_per_kind(make_bench):
    bench = make_bench([])
    original = pyproject(bench)
    both = (
        original.replace('pythonpath = ["src"]', 'pythonpath = ["src"]\naddopts = "-q"')
        + "\n[tool.ruff]\nline-length = 1\n"
    )
    bench.adapter._script.append(
        Step(
            writes={"tests/test_discount.py": TESTS, "src/pytdd/pricing.py": STUB, "pyproject.toml": both},
            structured=result("red", tests_added=["tests/test_discount.py::test_known_code"]),
        )
    )
    run_red(bench.wb, TASK, attempt=1)
    assert pyproject(bench) == original
    assert [e["sections"] for e in violations(bench, "gate configuration")] == [["tool.ruff"]]
    assert [e["sections"] for e in violations(bench, "runner configuration")] == [["tool.pytest"]]


# --- the pytest `markers` exception (owner decision 5) ---


def marked(original: str, *entries: str) -> str:
    listed = ", ".join(f'"{e}"' for e in entries)
    return original.replace('pythonpath = ["src"]', f'pythonpath = ["src"]\nmarkers = [{listed}]')


def test_scn_imp_254_red_may_register_a_new_marker(make_bench):
    bench = make_bench([])
    original = pyproject(bench)
    edited = marked(original, "slow: slow tests")
    bench.adapter._script.append(
        Step(
            writes={"tests/test_discount.py": TESTS, "src/pytdd/pricing.py": STUB, "pyproject.toml": edited},
            structured=result("red", tests_added=["tests/test_discount.py::test_known_code"]),
        )
    )
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "ok", out.reason
    assert committed(bench, out.sha, "pyproject.toml") == edited
    assert not violations(bench, "runner configuration")


def test_scn_imp_255_green_may_register_a_new_marker_too(make_bench):
    bench = make_bench([red_step()])
    base = marked(pyproject(bench), "slow: slow tests")
    commit_base(bench, {"pyproject.toml": base})
    edited = base.replace('"slow: slow tests"', '"slow: slow tests", "db: needs a database"')
    bench.adapter._script.append(
        Step(writes={"src/pytdd/pricing.py": IMPL, "pyproject.toml": edited}, structured=result("green"))
    )
    red = run_red(bench.wb, TASK, attempt=1)
    out = run_green(bench.wb, TASK, red, attempt=1)
    assert out.status == "ok", out.reason
    assert pyproject(bench) == edited and not violations(bench, "runner configuration")


def test_scn_imp_256_a_removed_or_changed_marker_and_any_other_runner_key_are_put_back(make_bench):
    bench = make_bench([red_step()])
    base = marked(pyproject(bench), "slow: slow tests")
    commit_base(bench, {"pyproject.toml": base})
    removed = base.replace('markers = ["slow: slow tests"]', "markers = []")
    bench.adapter._script.append(
        Step(writes={"src/pytdd/pricing.py": IMPL, "pyproject.toml": removed}, structured=result("green"))
    )
    red = run_red(bench.wb, TASK, attempt=1)
    run_green(bench.wb, TASK, red, attempt=1)
    assert pyproject(bench) == base
    assert [e["sections"] for e in violations(bench, "runner configuration")] == [["tool.pytest"]]


def test_scn_imp_257_a_marker_together_with_asyncio_mode_is_put_back_whole(make_bench):
    bench = make_bench([])
    original = pyproject(bench)
    edited = marked(original, "slow: slow tests").replace("markers", 'asyncio_mode = "auto"\nmarkers')
    bench.adapter._script.append(
        Step(
            writes={"tests/test_discount.py": TESTS, "src/pytdd/pricing.py": STUB, "pyproject.toml": edited},
            structured=result("red", tests_added=["tests/test_discount.py::test_known_code"]),
        )
    )
    out = run_red(bench.wb, TASK, attempt=1)
    assert out.status == "ok", out.reason
    assert pyproject(bench) == original  # the marker went back with the rest: the whole file is put back
    assert [e["sections"] for e in violations(bench, "runner configuration")] == [["tool.pytest"]]


# --- the next attempt is told which file went back and why (owner decision 2) ---


def test_scn_imp_258_the_next_prompt_names_the_file_the_section_and_how_to_redo_a_dependency(make_bench):
    bench = make_bench([], lint=[LINT])
    original = pyproject(bench)
    loosened = original.replace('dev = ["pytest>=8"]', 'dev = ["pytest>=8", "pytest-mock"]')
    loosened += '\n[tool.ruff.lint]\nignore = ["ALL"]  # l4-loosened\n'
    first = Step(
        writes={
            "tests/test_discount.py": TESTS + "\n# LINTBAD\n", "src/pytdd/pricing.py": STUB,
            "pyproject.toml": loosened,
        },
        structured=result("red", tests_added=["tests/test_discount.py::test_known_code"]),
    )  # fmt: skip
    bench.adapter._script.extend([first, red_step(), green_step()])
    run_task(bench.wb, TASK)
    second = bench.adapter.requests[1].prompt
    assert "- `pyproject.toml` (gate configuration) restored: changed tool.ruff" in second
    assert "the harness put the whole file back to the step's base" in second
    assert "A dependency you added in the same file must be written again without touching those sections" in second
    for advice in ("Make the code meet them", "If a setting is wrong, ask a question that names the file"):
        assert advice in second


def test_the_runner_advice_also_says_how_to_redo_a_dependency(make_bench):
    from l4.implementer.guardnotes import guard_note_text, note_of

    note = note_of(
        "guard.violation",
        {"rule": "runner configuration", "path": "pytest.ini", "action": "restored", "why": "changed pytest"},
    )
    text = guard_note_text([note])
    assert "- `pytest.ini` (runner configuration) restored: changed pytest" in text
    assert "A dependency you added in the same file must be written again" in text
    assert "ask a question that names the file" in text


def test_green_keeps_a_new_test_for_nothing_but_the_green_step_is_unchanged(make_bench):
    bench = make_bench([red_step(), green_step()])
    red = run_red(bench.wb, TASK, attempt=1)
    assert run_green(bench.wb, TASK, red, attempt=1).status == "ok"
    assert not violations(bench, "gate configuration") and not violations(bench, "runner configuration")
