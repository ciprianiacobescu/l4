"""The verifier checks gate and runner configuration on the commits (L4-IMP-040 part g, L4-IMP-041; design D9)."""

from l4.verifier.integrity import check_gate_config, run_integrity
from l4.verifier.report import render_verification_md, verdict_json
from l4.verifier.types import Severity

from ._integrity_helpers import UNIT, event, new_repo, task

PYPROJECT = "[project]\nname = 'x'\n\n[tool.mypy]\nstrict = true\n\n[tool.pytest.ini_options]\npythonpath = ['src']\n"
LOOSE_MYPY = PYPROJECT.replace("strict = true", "strict = false")
ASYNC = PYPROJECT.replace("pythonpath = ['src']", "pythonpath = ['src']\nasyncio_mode = 'auto'")
MARKED = PYPROJECT.replace("pythonpath = ['src']", "pythonpath = ['src']\nmarkers = ['slow: slow tests']")


def repo_with_pyproject(tmp_path, git_environ):
    return new_repo(tmp_path, git_environ, {"README.md": "x\n", "pyproject.toml": PYPROJECT, "ruff.toml": "a = 1\n"})


def test_scn_imp_249_a_harness_commit_that_loosened_tool_mypy_is_a_blocker_and_a_persons_change_is_listed(
    tmp_path, git_environ
):
    repo, base = repo_with_pyproject(tmp_path, git_environ)
    repo.write({"pyproject.toml": LOOSE_MYPY})
    green = repo.commit("work", task="1.1", tdd="green")
    repo.write({"ruff.toml": "a = 2\n"})
    head = repo.commit_as_human("a person tunes ruff")
    ctx = repo.context(base, head, tasks=[(UNIT, task("1.1"))])
    out = check_gate_config(ctx)
    [finding] = out.findings
    assert finding.severity is Severity.BLOCKER and finding.title == "gate or runner configuration changed by the unit"
    assert "pyproject.toml (gate: tool.mypy)" in finding.detail and green[:10] in finding.detail
    assert len(out.human_config) == 1 and out.human_config[0].startswith("ruff.toml (gate: the whole file) by ")
    assert "ruff.toml" not in finding.detail


def test_a_config_tagged_tasks_green_commit_passes(tmp_path, git_environ):
    repo, base = repo_with_pyproject(tmp_path, git_environ)
    repo.write({"pyproject.toml": LOOSE_MYPY})
    head = repo.commit("work", task="1.1", tdd="green")
    ctx = repo.context(base, head, tasks=[(UNIT, task("1.1", "Raise the bar [config]"))])
    assert check_gate_config(ctx).findings == []


def test_a_test_infra_red_commit_may_change_the_runner_section_and_the_same_change_in_green_is_a_blocker(
    tmp_path, git_environ
):
    repo, base = repo_with_pyproject(tmp_path, git_environ)
    repo.write({"pyproject.toml": ASYNC})
    red = repo.commit("tests", task="1.1", tdd="red")
    ctx = repo.context(base, red, tasks=[(UNIT, task("1.1", "Async tests [test-infra]"))])
    assert check_gate_config(ctx).findings == []
    second = tmp_path / "b"
    second.mkdir()
    repo2, base2 = new_repo(second, git_environ, {"README.md": "x\n", "pyproject.toml": PYPROJECT})
    repo2.write({"pyproject.toml": ASYNC})
    green = repo2.commit("code", task="1.1", tdd="green")
    ctx2 = repo2.context(base2, green, tasks=[(UNIT, task("1.1", "Async tests [test-infra]"))])
    [finding] = check_gate_config(ctx2).findings
    assert "pyproject.toml (runner: tool.pytest)" in finding.detail


def test_a_red_commit_without_a_tag_or_an_answer_that_changed_a_runner_section_is_a_blocker(tmp_path, git_environ):
    repo, base = repo_with_pyproject(tmp_path, git_environ)
    repo.write({"pyproject.toml": ASYNC})
    head = repo.commit("tests", task="1.1", tdd="red")
    [finding] = check_gate_config(repo.context(base, head, tasks=[(UNIT, task("1.1"))])).findings
    assert "runner: tool.pytest" in finding.detail


def test_a_commit_that_a_task_config_opened_names_passes_in_its_own_phase_only(tmp_path, git_environ):
    repo, base = repo_with_pyproject(tmp_path, git_environ)
    repo.write({"pyproject.toml": ASYNC})
    head = repo.commit("tests", task="1.1", tdd="red")
    repo.events.append(event("task.config_opened", 1, task="1.1", phase="red", paths=["pyproject.toml"], kept=[]))
    assert check_gate_config(repo.context(base, head, tasks=[(UNIT, task("1.1"))])).findings == []
    repo.events[:] = [event("task.config_opened", 1, task="1.1", phase="green", paths=["pyproject.toml"], kept=[])]
    assert check_gate_config(repo.context(base, head, tasks=[(UNIT, task("1.1"))])).findings  # another phase's grant
    repo.events[:] = [event("task.config_opened", 1, task="1.1", phase="red", paths=["mypy.ini"], kept=[])]
    assert check_gate_config(repo.context(base, head, tasks=[(UNIT, task("1.1"))])).findings  # another file's grant


def test_a_new_marker_in_green_passes_without_a_tag(tmp_path, git_environ):
    repo, base = repo_with_pyproject(tmp_path, git_environ)
    repo.write({"pyproject.toml": MARKED})
    head = repo.commit("code", task="1.1", tdd="green")
    assert check_gate_config(repo.context(base, head, tasks=[(UNIT, task("1.1"))])).findings == []


def test_a_harness_commit_that_is_no_task_step_is_never_allowed(tmp_path, git_environ):
    repo, base = repo_with_pyproject(tmp_path, git_environ)
    repo.write({"pyproject.toml": LOOSE_MYPY})
    head = repo.commit_as_harness("a checkpoint", phase="implementing")
    assert check_gate_config(repo.context(base, head, tasks=[(UNIT, task("1.1", "[config] x"))])).findings


def test_a_persons_commit_gives_no_blocker_and_is_listed(tmp_path, git_environ):
    repo, base = repo_with_pyproject(tmp_path, git_environ)
    repo.write({"pyproject.toml": LOOSE_MYPY, "mypy.ini": "[mypy]\n"})
    head = repo.commit_as_human("a person loosens mypy")
    out = check_gate_config(repo.context(base, head))
    assert out.findings == [] and len(out.human_config) == 2
    assert "(+2 changed by humans, listed)" in out.note


def test_no_configuration_change_skips_the_check(tmp_path, git_environ):
    repo, base = repo_with_pyproject(tmp_path, git_environ)
    repo.write({"src/app.py": "x = 1\n", "uv.lock": "lock\n"})
    head = repo.commit("code", task="1.1", tdd="green")
    assert check_gate_config(repo.context(base, head)).skipped


# --- the listing (9.2) ---


def test_run_integrity_lists_a_persons_change_in_the_report_and_the_markdown_and_survives_a_resume(
    tmp_path, git_environ
):
    from l4.verifier.evidence import restore_round
    from l4.verifier.types import Verdict, VerifyResult

    repo, base = repo_with_pyproject(tmp_path, git_environ)
    repo.write({"ruff.toml": "a = 2\n"})
    head = repo.commit_as_human("a person tunes ruff")
    report = run_integrity(repo.context(base, head))
    assert not report.blocked and len(report.human_config) == 1 and "ruff.toml" in report.human_config[0]
    assert next(c.note for c in report.checks if c.name == "gate configuration").endswith("listed)")
    result = VerifyResult(UNIT, 1, Verdict.PASS, base, head, integrity=report)
    text = render_verification_md(result)
    assert "## Gate and runner configuration changed by humans (allowed, listed: L4-IMP-040)" in text
    assert "- ruff.toml (gate: the whole file) by " in text
    again = restore_round(verdict_json(result), UNIT, 2).integrity
    assert again is not None and again.human_config == report.human_config
