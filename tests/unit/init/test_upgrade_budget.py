"""`l4 upgrade` prints the two budget problems (budget-guard D6; L4-IMP-079, SCN-IMP-394, SCN-IMP-395)."""

from pathlib import Path

import yaml

from l4.cli import main

OLD, NEW = "d" * 40, "e" * 40
REPO = "git@github.com:o/harness.git"
ERROR = (
    "error: ci.time_budget 21m minus soft_deadline_margin 20m leaves 1 min, less than one step (10 min): "
    "set ci.time_budget: auto (the job timeout) or raise it; until it is fixed, l4 run exits 2 and doctor CFG-012 fails"
)
WARNING = (
    "warning: ci.time_budget 21m is shorter than the job's timeout (180 min, .github/workflows/l4.yml timeout-minutes)"
)


def set_ci(target: Path, **keys: str) -> None:
    path = target / ".l4/config.yaml"
    document = yaml.safe_load(path.read_text())
    document.setdefault("ci", {}).update(keys)
    path.write_text(yaml.safe_dump(document))


def configured_budget(target: Path) -> str:
    return yaml.safe_load((target / ".l4/config.yaml").read_text())["ci"]["time_budget"]


def action_adoption(target: Path, environ) -> None:
    argv = ["init", "--repo", str(target), "--ci", "github", "--action", "--action-repo", "o/harness"]
    assert main([*argv, "--harness-commit", OLD], environ=environ) == 0


def upgrade_to_new(target: Path, environ, *flags: str) -> int:
    return main(["upgrade", "--repo", str(target), "--harness-commit", NEW, *flags], environ=environ)


def test_the_upgrade_names_a_budget_below_one_step_and_a_shortened_job(target, git_environ, capsys):
    """SCN-IMP-394: both lines, exit 0, the configuration untouched; the dry run prints them too."""
    action_adoption(target, git_environ)
    set_ci(target, time_budget="21m", soft_deadline_margin="20m")
    capsys.readouterr()
    assert upgrade_to_new(target, git_environ, "--dry-run") == 0
    dry = capsys.readouterr().out
    assert ERROR in dry and WARNING in dry
    assert configured_budget(target) == "21m"
    assert upgrade_to_new(target, git_environ) == 0
    out = capsys.readouterr().out
    assert ERROR in out and WARNING in out and out.index(ERROR) < out.index(WARNING)
    assert configured_budget(target) == "21m"


def test_the_lines_do_not_depend_on_a_changed_file(target, git_environ, capsys):
    action_adoption(target, git_environ)
    set_ci(target, time_budget="21m", soft_deadline_margin="20m")
    assert upgrade_to_new(target, git_environ) == 0
    capsys.readouterr()
    assert upgrade_to_new(target, git_environ) == 0  # no file changes now
    out = capsys.readouterr().out
    assert "up to date" in out and ERROR in out and WARNING in out


def quiet(out: str) -> bool:
    return "error:" not in out and "warning:" not in out


def test_a_sound_budget_prints_no_line_in_an_action_adoption(target, git_environ, capsys):
    """SCN-IMP-395: `auto`, with the environment's variable (not read) at 600."""
    env = {**git_environ, "L4_JOB_TIMEOUT_MINUTES": "600"}
    action_adoption(target, env)
    set_ci(target, time_budget="auto")
    capsys.readouterr()
    assert upgrade_to_new(target, env) == 0
    assert quiet(capsys.readouterr().out)


def test_a_sound_budget_prints_no_line_in_a_fetched_adoption(target, git_environ, capsys):
    env = {**git_environ, "L4_JOB_TIMEOUT_MINUTES": "600"}
    argv = ["init", "--repo", str(target), "--ci", "github", "--harness-repo", REPO, "--harness-commit", OLD]
    assert main(argv, environ=env) == 0
    set_ci(target, time_budget="3h")
    capsys.readouterr()
    assert upgrade_to_new(target, env) == 0
    assert quiet(capsys.readouterr().out)


def test_a_sound_budget_prints_no_line_in_a_vendored_adoption(target, harness_repo, git_environ, capsys):
    """No GitHub workflow, so no job timeout is known; the environment's variable is not read."""
    env = {**git_environ, "L4_JOB_TIMEOUT_MINUTES": "600"}
    argv = ["init", "--repo", str(target), "--harness", str(harness_repo), "--ci", "gitlab", "--vendor"]
    assert main(argv, environ=env) == 0
    set_ci(target, time_budget="60m")
    capsys.readouterr()
    assert main(["upgrade", "--repo", str(target), "--harness", str(harness_repo)], environ=env) == 0
    assert quiet(capsys.readouterr().out)
