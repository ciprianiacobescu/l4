"""The one reading of the CI job's budget (budget-guard D1, D2, D3, D5; L4-IMP-076 to L4-IMP-078)."""

import ast
from pathlib import Path
from types import SimpleNamespace

from l4.ci import budget
from l4.ci.budget import (
    Budget,
    job_budget,
    job_timeout,
    raise_fix,
    read_workflow,
    shortens_job,
    too_short,
    upgrade_notes,
    workflow_timeout_s,
)

WORKFLOW = "jobs:\n  l4:\n    runs-on: ubuntu-latest\n    timeout-minutes: 180\n"
WF_SOURCE = ".github/workflows/l4.yml timeout-minutes"


def _cfg(budget_: str, margin: str = "20m") -> SimpleNamespace:
    return SimpleNamespace(ci=SimpleNamespace(time_budget=budget_, soft_deadline_margin=margin))


def test_job_budget_reads_the_set_budget_then_gitlab_then_github() -> None:
    both = {"L4_JOB_TIMEOUT_MINUTES": "180", "CI_JOB_TIMEOUT": "7200"}
    assert job_budget(_cfg("3h"), {"L4_JOB_TIMEOUT_MINUTES": "180"}) == Budget(10800, "ci.time_budget")
    assert job_budget(_cfg("auto"), both) == Budget(7200, "CI_JOB_TIMEOUT")
    assert job_budget(_cfg("auto"), {"L4_JOB_TIMEOUT_MINUTES": "180"}) == Budget(10800, "L4_JOB_TIMEOUT_MINUTES")
    assert job_budget(_cfg("auto"), {"L4_JOB_TIMEOUT_MINUTES": "180h"}) is None
    assert job_budget(_cfg("auto"), {}) is None


def test_too_short_says_what_is_left_and_the_fix() -> None:
    assert too_short(_cfg("21m")) == (
        "ci.time_budget 21m minus soft_deadline_margin 20m leaves 1 min, less than one step (10 min): "
        "set ci.time_budget: auto (the job timeout) or raise it"
    )
    assert too_short(_cfg("30m")) is None
    assert too_short(_cfg("auto")) is None
    assert too_short(_cfg("1h", "50m")) is None
    text = too_short(_cfg("15m"))
    assert text is not None
    assert "minus soft_deadline_margin 20m leaves no time, less than one step (10 min)" in text


def test_shortens_job_names_the_job_timeout_and_its_source() -> None:
    env = (10800, "L4_JOB_TIMEOUT_MINUTES")
    assert shortens_job(_cfg("60m"), env) == (
        "ci.time_budget 60m is shorter than the job's timeout (180 min, L4_JOB_TIMEOUT_MINUTES) by more than "
        "soft_deadline_margin 20m: the soft deadline comes at minute 40, not at minute 160; "
        "set ci.time_budget: auto (the job timeout) unless the job must stop early"
    )
    text = shortens_job(_cfg("21m"), env)
    assert text is not None
    assert "comes at minute 1, not at minute 160" in text
    assert shortens_job(_cfg("60m"), (3600, "CI_JOB_TIMEOUT")) is None
    assert shortens_job(_cfg("170m"), env) is None
    assert shortens_job(_cfg("auto"), env) is None
    assert shortens_job(_cfg("60m"), None) is None


def test_job_timeout_reads_the_job_then_the_workflow() -> None:
    assert job_timeout({"CI_JOB_TIMEOUT": "3600"}, None) == (3600, "CI_JOB_TIMEOUT")
    assert job_timeout({"L4_JOB_TIMEOUT_MINUTES": "180"}, None) == (10800, "L4_JOB_TIMEOUT_MINUTES")
    assert job_timeout({}, WORKFLOW) == (10800, WF_SOURCE)
    assert job_timeout({"CI_JOB_TIMEOUT": "x", "L4_JOB_TIMEOUT_MINUTES": "1h"}, WORKFLOW) == (10800, WF_SOURCE)
    assert job_timeout({"CI_JOB_TIMEOUT": "x"}, None) is None
    assert job_timeout({}, None) is None


def test_workflow_timeout_reads_the_first_integer() -> None:
    assert workflow_timeout_s("    timeout-minutes: ${{ inputs.t }}\n") is None
    assert workflow_timeout_s("a:\n  timeout-minutes: 30\nb:\n  timeout-minutes: 90\n") == 1800


def test_read_workflow_refuses_a_link_and_a_big_file(tmp_path: Path) -> None:
    assert read_workflow(tmp_path) is None
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True)
    (wf / "l4.yml").write_text(WORKFLOW)
    assert read_workflow(tmp_path) == WORKFLOW
    (wf / "l4.yml").unlink()
    (tmp_path / "real.yml").write_text(WORKFLOW)
    (wf / "l4.yml").symlink_to(tmp_path / "real.yml")
    assert read_workflow(tmp_path) is None
    (wf / "l4.yml").unlink()
    (wf / "l4.yml").write_text("x" * (1024 * 1024 + 1))
    assert read_workflow(tmp_path) is None


def test_raise_fix_per_source() -> None:
    assert raise_fix("ci.time_budget") == "raise ci.time_budget (or set it to auto)"
    assert raise_fix("CI_JOB_TIMEOUT") == "raise the job's timeout (CI_JOB_TIMEOUT)"
    assert raise_fix("L4_JOB_TIMEOUT_MINUTES") == "raise timeout-minutes and L4_JOB_TIMEOUT_MINUTES"
    assert raise_fix(None) == "raise timeout-minutes and L4_JOB_TIMEOUT_MINUTES"


def test_upgrade_notes() -> None:
    notes = upgrade_notes(_cfg("21m"), WORKFLOW)
    assert len(notes) == 2
    assert notes[0].startswith("error: ci.time_budget 21m minus soft_deadline_margin 20m leaves 1 min")
    assert notes[0].endswith("; until it is fixed, l4 run exits 2 and doctor CFG-012 fails")
    assert notes[1].startswith("warning: ci.time_budget 21m is shorter than the job's timeout (180 min, ")
    assert WF_SOURCE in notes[1]
    assert upgrade_notes(_cfg("auto"), WORKFLOW) == ()
    only = upgrade_notes(_cfg("21m"), None)
    assert len(only) == 1
    assert only[0].startswith("error: ")


def test_the_module_does_not_import_the_orchestrator() -> None:
    tree = ast.parse(Path(budget.__file__).read_text())
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            names.append(("." * node.level) + node.module)
        elif isinstance(node, ast.Import):
            names.extend(a.name for a in node.names)
    joined = " ".join(names)
    for forbidden in ("orchestrator", "doctor", "init"):
        assert not any(n.lstrip(".").split(".")[0] == forbidden or f"l4.{forbidden}" in n for n in names), joined
