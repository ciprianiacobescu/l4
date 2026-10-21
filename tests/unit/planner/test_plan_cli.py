import json
import shutil
from pathlib import Path

import pytest

from l4.cli import main

TASKS = "# Tasks\n\n## 1. Discounts\n\n- [ ] 1.1 Parse codes\n- [ ] 1.2 Apply codes\n"


@pytest.fixture
def project(make_repo, git_environ, tmp_path: Path):
    """A git repository holding the change `add-discount-codes` with pending tasks, plus the CLI environment."""
    repo = make_repo()
    change = repo / "openspec" / "changes" / "add-discount-codes"
    change.mkdir(parents=True)
    (change / "tasks.md").write_text(TASKS)
    environ = {**git_environ, "L4_CACHE": str(tmp_path / "cache")}
    return repo, environ


def plan(project, capsys, *argv: str) -> tuple[int, str, str]:
    repo, environ = project
    code = main(["plan", *argv, "--repo", str(repo)], environ=environ)
    out = capsys.readouterr()
    return code, out.out, out.err


def test_plan_json_lists_the_pending_unit_with_next_action_implement(project, capsys):
    code, out, _ = plan(project, capsys, "--json")
    assert code == 0
    assert json.loads(out) == {
        "schema": "l4/plan@1",
        "units": [
            {
                "unit": "openspec:add-discount-codes", "framework": "openspec", "phase": None,
                "next_action": "implement", "actionable": True, "reason": "pending tasks",
                "tasks": {"done": 0, "total": 2},
            }
        ],
    }  # fmt: skip
    outcome = json.loads((project[0] / ".l4-out" / "outcome.json").read_text())
    assert outcome["exit_code"] == 0
    (unit,) = outcome["units"]
    assert unit["unit"] == "openspec:add-discount-codes" and unit["phase_before"] == unit["phase_after"] == "none"
    assert unit["tasks"] == {"done": 0, "total": 2}


def test_plan_table(project, capsys):
    code, out, _ = plan(project, capsys)
    assert code == 0
    header, row = out.strip().splitlines()
    assert header.split()[:5] == ["UNIT", "PHASE", "TASKS", "NEXT", "REASON"]
    assert row.split()[:5] == ["openspec:add-discount-codes", "-", "0/2", "implement", "pending"]


def test_plan_json_is_byte_identical_across_runs(project, capsys):
    first = plan(project, capsys, "--json")[1]
    assert plan(project, capsys, "--json")[1] == first


def test_plan_exits_0_whether_or_not_work_exists(project, capsys):
    """SCN-CLI-02: exit 0 always; `--detailed-exitcode` (exit 10) is tested in test_plan_exit_and_probe.py."""
    assert plan(project, capsys)[0] == 0


def test_plan_sweep_without_a_forge_credential_plans_as_before(project, capsys):
    """Outside CI with no token there is no forge to ask: the sweep says so (stderr) and the plan is the same."""
    plain = plan(project, capsys)
    code, out, err = plan(project, capsys, "--sweep")
    assert code == 0 and out == plain[1] and "sweep skipped" in err


def test_nothing_to_do_outcome_units_empty(make_repo, git_environ, tmp_path: Path, capsys):
    repo = make_repo()  # no openspec directory at all
    code = main(["plan", "--json", "--repo", str(repo)], environ={**git_environ, "L4_CACHE": str(tmp_path / "c")})
    assert code == 0 and json.loads(capsys.readouterr().out)["units"] == []
    assert json.loads((repo / ".l4-out" / "outcome.json").read_text())["units"] == []


def test_a_config_typo_exits_2_and_still_writes_the_outcome(project, capsys):
    repo, _ = project
    (repo / ".l4").mkdir()
    (repo / ".l4" / "config.yaml").write_text("version: 1\nverifer: {}\n")
    code, out, err = plan(project, capsys)
    assert code == 2 and out == "" and "verifer" in err and "verifier" in err
    assert json.loads((repo / ".l4-out" / "outcome.json").read_text())["exit_code"] == 2


def test_unit_filter_and_unknown_unit(project, capsys):
    assert plan(project, capsys, "--unit", "openspec:add-discount-codes", "--json")[0] == 0
    code, _, err = plan(project, capsys, "--unit", "openspec:other")
    assert code == 2 and "other" in err


def test_terminal_units_are_listed_but_not_in_the_outcome(project, capsys):
    from l4.redact import Redactor
    from l4.state.ledger import LedgerWriter

    repo, _ = project
    unit_dir = repo / "openspec" / "changes" / "add-discount-codes"
    writer = LedgerWriter.open(unit_dir, "openspec:add-discount-codes", "r-20261003T1312Z-7f3a", redactor=Redactor({}))
    writer.append("phase.changed", **{"from": "in_review", "to": "merged", "trigger": "pr_merged"})
    writer.finish(0)
    code, out, _ = plan(project, capsys, "--json")
    assert code == 0 and json.loads(out)["units"][0]["phase"] == "merged"
    assert json.loads((repo / ".l4-out" / "outcome.json").read_text())["units"] == []


def test_plan_without_node_or_openspec_installed_still_works(project, capsys, tmp_path: Path):
    """plan lists units from the disk and never starts the OpenSpec CLI: only git is on this PATH."""
    repo, environ = project
    only_git = tmp_path / "only-git"
    only_git.mkdir()
    (only_git / "git").symlink_to(shutil.which("git", path=environ["PATH"]))
    code = main(["plan", "--json", "--repo", str(repo)], environ={**environ, "PATH": str(only_git), "L4_HOME": "/none"})
    assert code == 0 and json.loads(capsys.readouterr().out)["units"][0]["next_action"] == "implement"


def test_invalid_branch_prefix_is_a_usage_error(project, capsys):
    repo, _ = project
    (repo / ".l4").mkdir()
    (repo / ".l4" / "config.yaml").write_text('forge: {branch_prefix: "-x/"}\n')
    code, _, err = plan(project, capsys)
    assert code == 2 and "forge.branch_prefix" in err and "-x/" not in err


def test_plan_stdout_is_redacted(project, capsys):
    repo, environ = project
    token = "tok-secretvalue-9999"
    (repo / "openspec" / "changes" / token).mkdir()
    (repo / "openspec" / "changes" / token / "tasks.md").write_text(TASKS)
    project = (repo, {**environ, "L4_FORGE_TOKEN": token})
    code, out, _ = plan(project, capsys)
    assert code == 0 and token not in out and "[REDACTED:L4_FORGE_TOKEN]" in out


def test_plan_redacts_the_variable_the_config_names(project, capsys):
    """`forge.token_env` points at a variable outside the built-in redact list: the config-aware redactor covers it."""
    repo, environ = project
    token = "tok-secretvalue-9999"
    (repo / "openspec" / "changes" / token).mkdir()
    (repo / "openspec" / "changes" / token / "tasks.md").write_text(TASKS)
    (repo / ".l4").mkdir()
    (repo / ".l4" / "config.yaml").write_text("forge: {token_env: MY_CUSTOM_TOKEN}\n")
    code, out, _ = plan((repo, {**environ, "MY_CUSTOM_TOKEN": token}), capsys)
    assert code == 0 and token not in out and "[REDACTED:MY_CUSTOM_TOKEN]" in out


def _secret_project(project, name: str):
    repo, environ = project
    (repo / "openspec" / "changes" / name).mkdir()
    (repo / "openspec" / "changes" / name / "tasks.md").write_text(TASKS)
    (repo / ".l4").mkdir(exist_ok=True)
    (repo / ".l4" / "config.yaml").write_text("forge: {token_env: MY_FORGE_SECRET}\n")
    return repo, {**environ, "MY_FORGE_SECRET": name}


def test_config_named_secret_is_absent_from_stderr_on_an_error_path(project, capsys):
    secret = "zzsecretvalue123"
    code, out, err = plan(_secret_project(project, secret), capsys, "--unit", f"openspec:{secret}-missing")
    assert code != 0 and secret not in err and secret not in out and "[REDACTED:MY_FORGE_SECRET]" in err


def test_config_named_secret_is_absent_from_outcome_json(project, capsys):
    secret = "zzsecretvalue123"
    repo, environ = _secret_project(project, secret)
    code, out, err = plan((repo, environ), capsys, "--json")
    assert code == 0 and secret not in out + err
    raw = (repo / ".l4-out" / "outcome.json").read_text()
    assert secret not in raw and "[REDACTED:MY_FORGE_SECRET]" in raw
