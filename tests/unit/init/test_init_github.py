from pathlib import Path

import pytest
import yaml

from l4.ci.github import render_github_ci
from l4.ci.render import render_gitlab_ci
from l4.cli import main
from l4.config.loader import load_config
from l4.init.init import plan_init, render_config

WORKFLOW = ".github/workflows/l4.yml"
GITLAB_FILE = ".l4/ci/l4.gitlab-ci.yml"


SEED = ".serena/project.yml"  # seeded when memory is on (L4-INS-002)


def init(target: Path, harness: Path, environ, *flags: str) -> int:
    return main(["init", "--repo", str(target), "--harness", str(harness), *flags], environ=environ)


def paths(plan) -> list[str]:
    return [f.path for f in plan.files]


def test_ci_both_writes_gitlab_and_github_files(target: Path, harness_repo: Path, git_environ):
    plan = plan_init(target, git_environ, force=False, harness=harness_repo, ci="both")
    assert paths(plan) == [".l4/config.yaml", ".l4/bin/l4", ".l4/bin/l4-setup", GITLAB_FILE, ".gitlab-ci.yml", WORKFLOW, SEED]
    by_path = {f.path: f for f in plan.files}
    assert by_path[GITLAB_FILE].data.decode() == render_gitlab_ci()
    (target / ".l4").mkdir()
    (target / ".l4" / "config.yaml").write_bytes(by_path[".l4/config.yaml"].data)
    cfg = load_config(target)
    assert by_path[WORKFLOW].data.decode() == render_github_ci(cfg)
    assert by_path[WORKFLOW].mode == 0o644
    assert (cfg.forge.type, cfg.ci.platform) == ("auto", "auto")  # two platforms: the environment decides


def test_ci_github_writes_the_workflow_beside_the_shim_and_no_gitlab_file(target, harness_repo, git_environ):
    plan = plan_init(target, git_environ, force=False, harness=harness_repo, ci="github")
    assert paths(plan) == [".l4/config.yaml", ".l4/bin/l4", ".l4/bin/l4-setup", WORKFLOW, SEED]
    config = yaml.safe_load(next(f for f in plan.files if f.path == ".l4/config.yaml").data)
    assert config["forge"] == {"type": "github"} and config["ci"] == {"platform": "github"}


def test_the_gitlab_form_is_unchanged(target, harness_repo, git_environ):
    plan = plan_init(target, git_environ, force=False, harness=harness_repo)
    assert paths(plan) == [".l4/config.yaml", ".l4/bin/l4", ".l4/bin/l4-setup", GITLAB_FILE, ".gitlab-ci.yml", SEED]
    assert yaml.safe_load(render_config("c" * 40))["forge"] == {"type": "gitlab"}


def test_the_cli_writes_the_workflow_and_refuses_to_overwrite_it(target, harness_repo, git_environ, capsys):
    assert init(target, harness_repo, git_environ, "--ci", "github", "--vendor") == 0
    out = capsys.readouterr()
    assert (target / WORKFLOW).is_file() and not (target / GITLAB_FILE).exists()
    assert yaml.safe_load((target / WORKFLOW).read_text())["name"] == "l4"
    assert "include:" not in out.out  # the GitLab snippet is for GitLab
    assert "L4_FORGE_TOKEN" in out.err and WORKFLOW in out.err
    (target / WORKFLOW).write_text("# mine\n")
    assert init(target, harness_repo, git_environ, "--ci", "github", "--vendor") == 2
    assert WORKFLOW in capsys.readouterr().err and (target / WORKFLOW).read_text() == "# mine\n"
    assert init(target, harness_repo, git_environ, "--ci", "github", "--vendor", "--force") == 0
    assert (target / WORKFLOW).read_text() != "# mine\n"


def test_ci_both_through_the_cli_writes_the_gitlab_include(target, harness_repo, git_environ, capsys):
    assert init(target, harness_repo, git_environ, "--ci", "both", "--vendor") == 0
    out = capsys.readouterr()
    assert out.out == ""  # written, not printed (M1.8 A1); --no-ci-edit prints it
    assert yaml.safe_load((target / ".gitlab-ci.yml").read_text())["include"] == [{"local": GITLAB_FILE}]
    assert (target / WORKFLOW).is_file() and (target / GITLAB_FILE).is_file()


@pytest.mark.parametrize("ci", ["github", "both"])
def test_a_symlinked_workflow_directory_is_refused_and_nothing_is_written(target, harness_repo, git_environ, ci):
    elsewhere = target.parent / "elsewhere"
    elsewhere.mkdir()
    (target / ".github").symlink_to(elsewhere)
    assert init(target, harness_repo, git_environ, "--ci", ci, "--vendor") == 2
    assert not (target / ".l4").exists() and list(elsewhere.iterdir()) == []
