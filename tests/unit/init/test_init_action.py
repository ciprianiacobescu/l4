"""`l4 init --ci github --action` (adoption-kit L4-ACT-004, SCN-ACT-08): the config, a short workflow and nothing of
the harness; `--action-copy`; `--dependabot`."""

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from l4.ci.github import ActionPin, render_github_action_ci
from l4.cli import main
from l4.config.loader import load_config
from l4.init.dependabot import merge_dependabot
from l4.init.init import plan_init

SHA = "d" * 40
WORKFLOW = ".github/workflows/l4.yml"
ACTION = ".github/actions/l4/action.yml"
DEPENDABOT = ".github/dependabot.yml"
SEED = ".serena/project.yml"


def init(target: Path, environ, *flags: str, ci: str = "github") -> int:
    return main(["init", "--repo", str(target), "--ci", ci, *flags], environ=environ)


def files_under(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and ".git/" not in f"{p}/"}


BASE = ("--action", "--action-repo", "o/harness", "--harness-commit", SHA)


def test_a_fresh_adoption_holds_only_config_workflow_and_evidence(target: Path, git_environ):
    """SCN-ACT-08: no `.l4/bin/`, no `.l4/vendor/`, no `harness.commit`; the pin is the `uses:` sha."""
    before = files_under(target)
    assert init(target, git_environ, *BASE) == 0
    # besides the files of SCN-ACT-08: .gitignore (`.l4-out/`) and the pytest marker, which every init registers
    assert files_under(target) - before == {".l4/config.yaml", WORKFLOW, SEED, ".gitignore", "conftest.py"}
    assert not (target / ".l4/bin").exists() and not (target / ".l4/vendor").exists()
    config = yaml.safe_load((target / ".l4/config.yaml").read_text())
    assert config["harness"] == {"delivery": "action"}
    cfg = load_config(target)
    assert cfg.harness.commit is None and cfg.harness.delivery == "action"
    assert cfg.forge.type == "github" and cfg.ci.platform == "github"
    assert (target / WORKFLOW).read_text() == render_github_action_ci(cfg, ActionPin("o/harness", SHA))
    assert (target / WORKFLOW).stat().st_mode & 0o777 == 0o644


def test_gitignore_keeps_only_the_output_directory(target: Path, git_environ):
    assert init(target, git_environ, *BASE) == 0
    assert (target / ".gitignore").read_text() == ".l4-out/\n"


def test_the_action_repository_defaults_to_the_one_in_harness_repo(target: Path, git_environ):
    flags = ("--action", "--harness-repo", "git@github.com:o/harness.git", "--harness-commit", SHA)
    assert init(target, git_environ, *flags) == 0
    assert f"uses: o/harness/.github/actions/l4@{SHA}" in (target / WORKFLOW).read_text()
    assert load_config(target).harness.repository is None  # the action form writes no fetched-form key


def test_no_action_repository_to_name_is_exit_2(target: Path, git_environ, capsys, monkeypatch):
    monkeypatch.setattr("l4.init.init.harness_origin", lambda: None)
    assert init(target, git_environ, "--action", "--harness-commit", SHA) == 2
    err = capsys.readouterr().err
    assert "no install origin" in err  # the cause (SCN-ADO-51)
    assert "uv tool run --from git+https://github.com/OWNER/l4@vX.Y.Z" in err
    assert "--action-repo OWNER/REPO" in err
    assert not (target / ".l4").exists()


def test_the_running_harness_origin_is_the_default(target: Path, git_environ, monkeypatch):
    monkeypatch.setattr("l4.init.init.harness_origin", lambda: "me/l4")
    assert init(target, git_environ, "--action", "--harness-commit", SHA) == 0
    assert f"me/l4/.github/actions/l4@{SHA}" in (target / WORKFLOW).read_text()


def test_no_pin_at_all_is_exit_2(target: Path, git_environ, capsys, monkeypatch):
    monkeypatch.setattr("l4.init.init.harness_commit", lambda: None)
    assert init(target, git_environ, "--action", "--action-repo", "o/harness") == 2
    assert "--harness-ref" in capsys.readouterr().err and not (target / ".l4").exists()


def test_the_running_harness_commit_is_the_default_pin(target: Path, git_environ, monkeypatch):
    monkeypatch.setattr("l4.init.init.harness_commit", lambda: "e" * 40)
    assert init(target, git_environ, "--action", "--action-repo", "o/harness") == 0
    assert f"@{'e' * 40}\n" in (target / WORKFLOW).read_text()


@pytest.mark.parametrize(
    "flags",
    [
        ("--action", "--vendor"),
        ("--action", "--harness-repo", "https://github.com/o/h.git", "--harness-commit", SHA, "--action-repo", "bad"),
        ("--action-repo", "o/harness"),
        ("--action-copy",),
        ("--dependabot",),
    ],
)
def test_option_combinations_that_make_no_sense_are_exit_2(target: Path, git_environ, flags):
    assert init(target, git_environ, *flags, "--harness-commit", SHA) == 2
    assert not (target / ".l4").exists() and not (target / ".github").exists()


def test_action_needs_the_github_platform(target: Path, git_environ, capsys):
    for ci in ("gitlab", "both"):
        assert init(target, git_environ, *BASE, ci=ci) == 2
        assert "--ci github" in capsys.readouterr().err
    assert not (target / ".l4").exists()


def test_an_existing_workflow_is_refused_without_force(target: Path, git_environ, capsys):
    (target / ".github/workflows").mkdir(parents=True)
    (target / WORKFLOW).write_text("name: mine\n")
    assert init(target, git_environ, *BASE) == 2
    assert "--force" in capsys.readouterr().err and (target / WORKFLOW).read_text() == "name: mine\n"
    assert init(target, git_environ, *BASE, "--force") == 0
    assert "uses: o/harness" in (target / WORKFLOW).read_text()


def test_copy_writes_the_action_and_the_repository_inputs(target: Path, git_environ, copy_harness: Path):
    """`--action-copy`: the action file of the harness checkout, source `repository`, the `commit` input is the pin."""
    flags = ("--action", "--action-copy", "--action-repo", "o/harness", "--harness-commit", SHA)
    assert init(target, git_environ, *flags, "--harness", str(copy_harness)) == 0
    assert (target / ACTION).read_bytes() == (copy_harness / ACTION).read_bytes()
    assert (target / ACTION).stat().st_mode & 0o777 == 0o644
    step = yaml.safe_load((target / WORKFLOW).read_text())["jobs"]["l4"]["steps"][2]
    assert step["uses"] == "./.github/actions/l4"
    assert step["with"]["source"] == "repository" and step["with"]["commit"] == SHA
    assert step["with"]["repository"] == "ssh://git@github.com/o/harness.git"
    assert step["with"]["ssh-key"] == "${{ secrets.L4_HARNESS_SSH_KEY }}"
    assert not (target / ".l4/bin").exists()


def test_copy_without_an_action_in_the_harness_is_exit_2(target: Path, git_environ, harness_repo: Path, capsys):
    flags = ("--action", "--action-copy", "--action-repo", "o/harness", "--harness-commit", SHA)
    assert init(target, git_environ, *flags, "--harness", str(harness_repo)) == 2
    assert ACTION in capsys.readouterr().err and not (target / ".l4").exists()


def test_the_commit_to_commit_lists_the_workflow_and_the_action(target: Path, git_environ, copy_harness, capsys):
    flags = ("--action", "--action-copy", "--action-repo", "o/harness", "--harness-commit", SHA)
    assert init(target, git_environ, *flags, "--harness", str(copy_harness)) == 0
    err = capsys.readouterr().err
    assert WORKFLOW in err.split("then commit", 1)[1] and ACTION in err.split("then commit", 1)[1]
    assert ".l4/bin/l4 setup" not in err and "uv tool install" in err  # a local l4 is the person's own


def test_dependabot_creates_the_file(target: Path, git_environ):
    assert init(target, git_environ, *BASE, "--dependabot") == 0
    doc = yaml.safe_load((target / DEPENDABOT).read_text())
    assert doc == {
        "version": 2,
        "updates": [{"package-ecosystem": "github-actions", "directory": "/", "schedule": {"interval": "weekly"}}],
    }


def test_dependabot_merges_into_an_existing_file_without_replacing_entries(target: Path, git_environ):
    existing = (
        "# mine\nversion: 2\nupdates:\n"
        "  - package-ecosystem: pip   # python\n    directory: /\n    schedule:\n      interval: daily\n"
        "  - package-ecosystem: npm\n    directory: /web\n    schedule:\n      interval: monthly\n"
    )
    (target / ".github").mkdir()
    (target / DEPENDABOT).write_text(existing)
    assert init(target, git_environ, *BASE, "--dependabot") == 0
    text = (target / DEPENDABOT).read_text()
    assert text.startswith(existing)  # every existing byte stays, comments included
    doc = yaml.safe_load(text)
    assert [u["package-ecosystem"] for u in doc["updates"]] == ["pip", "npm", "github-actions"]


def test_dependabot_with_the_ecosystem_already_there_is_left_alone(target: Path, git_environ):
    existing = (
        'version: 2\nupdates:\n  - package-ecosystem: "github-actions"\n    directory: "/"\n'
        "    schedule: {interval: daily}\n"
    )
    (target / ".github").mkdir()
    (target / DEPENDABOT).write_text(existing)
    assert init(target, git_environ, *BASE, "--dependabot") == 0
    assert (target / DEPENDABOT).read_text() == existing


def test_dependabot_in_a_form_it_cannot_edit_is_refused_with_nothing_written(target: Path, git_environ, capsys):
    (target / ".github").mkdir()
    (target / DEPENDABOT).write_text("version: 2\nupdates: []\n")
    assert init(target, git_environ, *BASE, "--dependabot") == 2
    err = capsys.readouterr().err
    assert "package-ecosystem" in err and "dependabot.yml" in err
    assert (target / DEPENDABOT).read_text() == "version: 2\nupdates: []\n" and not (target / ".l4").exists()


@pytest.mark.parametrize(
    ("existing", "expected"),
    [
        (None, "create"),
        ("version: 2\nupdates:\n  - package-ecosystem: pip\n    directory: /\n", "merge"),
        ("version: 2\nupdates:\n- package-ecosystem: pip\n  directory: /\n", "merge"),  # a list at the key's column
        ("version: 2\n", "merge"),  # no updates yet
        ("version: 2\nupdates:\n  - package-ecosystem: github-actions\n    directory: /\n", "noop"),
        ("version: 2\nupdates: []\n", "refuse"),
        ("[1, 2]\n", "refuse"),
        ("version: 2\nupdates: [\n", "refuse"),
    ],
)
def test_merge_dependabot_forms(existing, expected):
    edit = merge_dependabot(existing)
    assert edit.action == expected
    if edit.action in ("create", "merge"):
        updates = yaml.safe_load(edit.text)["updates"]
        assert updates[-1]["package-ecosystem"] == "github-actions" and updates[-1]["schedule"]["interval"] == "weekly"


def test_merge_dependabot_keeps_crlf_endings():
    edit = merge_dependabot("version: 2\r\nupdates:\r\n  - package-ecosystem: pip\r\n    directory: /\r\n")
    assert edit.action == "merge" and "\n" not in edit.text.replace("\r\n", "")


def test_plan_lists_no_harness_file(target: Path, git_environ):
    plan = plan_init(target, git_environ, force=False, ci="github", action=ActionPin("o/harness", SHA))
    assert [f.path for f in plan.files] == [".l4/config.yaml", WORKFLOW, SEED]
    assert plan.vendor is None


@pytest.mark.skipif(shutil.which("actionlint") is None, reason="actionlint is not installed")
def test_the_written_workflow_passes_actionlint(target: Path, git_environ, copy_harness):
    for flags in (BASE, ("--action", "--action-copy", "--action-repo", "o/harness", "--harness-commit", SHA)):
        fresh = target.parent / f"fresh-{len(flags)}"
        fresh.mkdir()
        assert init(fresh, git_environ, *flags, "--harness", str(copy_harness)) == 0
        (fresh / "actionlint.yaml").write_text("self-hosted-runner:\n  labels:\n    - agentic\n")
        argv = ["actionlint", "-no-color", "-config-file", str(fresh / "actionlint.yaml"), str(fresh / WORKFLOW)]
        done = subprocess.run(argv, capture_output=True, text=True, check=False, cwd=fresh)
        assert done.returncode == 0, done.stdout + done.stderr


# --- a config that runs on a GitHub-hosted runner (baseline gap 3) -------------------------------------------------


def test_an_action_adoption_is_hosted_and_uses_the_workflow_token(target: Path, git_environ):
    assert init(target, git_environ, *BASE) == 0
    written = yaml.safe_load((target / ".l4/config.yaml").read_text())
    assert written["ci"]["runner_tags"] == [] and written["forge"]["token_env"] == "GITHUB_TOKEN"
    cfg = load_config(target)
    assert cfg.ci.runner_tags == [] and cfg.forge.token_env == "GITHUB_TOKEN"
    text = (target / WORKFLOW).read_text()
    assert "runs-on: ubuntu-24.04" in text and "GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}" in text
    assert "self-provision" in text and "clis: none" not in text


def test_runner_tags_and_a_token_variable_are_the_persons_to_set(target: Path, git_environ):
    assert init(target, git_environ, *BASE, "--runner-tag", "agentic", "--runner-tag", "big",
                "--forge-token-env", "MY_TOKEN") == 0  # fmt: skip
    cfg = load_config(target)
    assert cfg.ci.runner_tags == ["agentic", "big"] and cfg.forge.token_env == "MY_TOKEN"
    text = (target / WORKFLOW).read_text()
    assert 'runs-on: ["self-hosted", "agentic", "big"]' in text and "MY_TOKEN: ${{ secrets.MY_TOKEN }}" in text


@pytest.mark.parametrize("flags", [("--runner-tag", "x"), ("--forge-token-env", "X")])
def test_runner_tag_and_token_env_need_action(target: Path, git_environ, capsys, flags):
    assert init(target, git_environ, "--harness-repo", "git@github.com:o/h.git", "--harness-commit", SHA, *flags) == 2
    assert flags[0] in capsys.readouterr().err and not (target / ".l4").exists()


def test_a_bad_token_variable_name_is_exit_2(target: Path, git_environ, capsys):
    assert init(target, git_environ, *BASE, "--forge-token-env", "not a name") == 2
    assert not (target / ".l4/config.yaml").exists()


def test_the_default_codex_profile_gets_a_todo_naming_it(target: Path, git_environ, capsys):
    assert init(target, git_environ, *BASE) == 0
    err = capsys.readouterr().err
    todo = next(line for line in err.splitlines() if line.startswith("todo: profile codex"))
    assert "roles.implementer" in todo and "CODEX_API_KEY" in todo
    assert "profile claude-code" not in err  # CLAUDE_CODE_OAUTH_TOKEN takes a subscription token as a secret
    assert "# TODO: profile codex" in (target / ".l4/config.yaml").read_text()


def test_no_login_todo_on_a_self_hosted_runner(target: Path, git_environ, capsys):
    assert init(target, git_environ, *BASE, "--runner-tag", "agentic") == 0
    assert "profile codex" not in capsys.readouterr().err


def test_which_profiles_can_log_in_on_a_hosted_runner():
    from l4.agents.credentials import hosted_login_problem

    assert hosted_login_problem("codex", "subscription") and hosted_login_problem("codex", None)
    assert hosted_login_problem("codex", "api_key") is None
    assert hosted_login_problem("claude-code", "subscription") is None
    assert hosted_login_problem("kiro-cli", "subscription") is None
    assert hosted_login_problem("opencode", None) is None


# --- copy mode from an installed l4, and its upgrade (baseline gap 6) -----------------------------------------------


COPY_FLAGS = ("--action", "--action-copy", "--action-repo", "o/harness", "--harness-commit", SHA)


def test_copy_needs_no_checkout_of_the_harness(target: Path, git_environ, monkeypatch):
    """An installed `l4` is not a git checkout: the action comes from the package."""
    from l4.init.action import packaged_action

    def no_checkout(harness):
        raise AssertionError("the harness checkout was looked for")

    monkeypatch.setattr("l4.init.init.harness_root", no_checkout)
    assert init(target, git_environ, *COPY_FLAGS) == 0
    assert (target / ACTION).read_bytes() == packaged_action()
    assert (target / ACTION).stat().st_mode & 0o777 == 0o644
    assert yaml.safe_load((target / WORKFLOW).read_text())["jobs"]["l4"]["steps"][2]["uses"] == "./.github/actions/l4"


def test_copy_refuses_an_existing_action_without_force(target: Path, git_environ, capsys):
    (target / ".github/actions/l4").mkdir(parents=True)
    (target / ACTION).write_text("name: mine\n")
    assert init(target, git_environ, *COPY_FLAGS) == 2
    assert ACTION in capsys.readouterr().err and (target / ACTION).read_text() == "name: mine\n"


def test_dependabot_with_the_copy_is_exit_2_in_one_line(target: Path, git_environ, capsys):
    """Dependabot moves `uses:` pins; in copy mode the pin is the `commit:` input, which it cannot move."""
    assert init(target, git_environ, *COPY_FLAGS, "--dependabot") == 2
    err = capsys.readouterr().err.strip()
    assert len(err.splitlines()) == 1 and "--dependabot" in err and "--action-copy" in err and "commit:" in err
    assert not (target / ".l4").exists() and not (target / ".github").exists()


def make_changes(repo: Path, *names: str) -> None:
    for name in names:
        folder = repo / "openspec/changes" / name
        folder.mkdir(parents=True)
        (folder / "proposal.md").write_text("## Why\nx\n")


def test_hold_existing_writes_the_sorted_ids_of_the_units_found(target: Path, git_environ):
    """SCN-ADO-37"""
    make_changes(target, "zeta", "alpha", "mid")
    assert init(target, git_environ, *BASE, "--hold-existing") == 0
    assert yaml.safe_load((target / ".l4/config.yaml").read_text())["yolo"] == {
        "hold": ["openspec:alpha", "openspec:mid", "openspec:zeta"]
    }
    assert load_config(target).yolo.hold == ["openspec:alpha", "openspec:mid", "openspec:zeta"]


def test_hold_existing_with_no_unit_writes_no_key_and_says_so(target: Path, git_environ, capsys):
    """SCN-ADO-38"""
    assert init(target, git_environ, *BASE, "--hold-existing") == 0
    assert "yolo" not in yaml.safe_load((target / ".l4/config.yaml").read_text())
    assert "nothing to hold" in capsys.readouterr().err


def test_without_the_flag_the_units_are_not_held(target: Path, git_environ):
    make_changes(target, "alpha")
    assert init(target, git_environ, *BASE) == 0
    assert "yolo" not in yaml.safe_load((target / ".l4/config.yaml").read_text())


def written_config(target: Path) -> dict:
    return yaml.safe_load((target / ".l4/config.yaml").read_text())


def test_laya_is_the_default_system_one(target: Path, git_environ):
    """SCN-ADO-45"""
    assert init(target, git_environ, *BASE) == 0
    config = written_config(target)
    assert config["roles"]["s1_judge"] == ["laya"]
    assert config["profiles"]["laya"] == {"backend": "system-one", "engine": "laya-local"}
    cfg = load_config(target)
    assert cfg.profiles["laya"].engine == "laya-local" and cfg.roles.s1_judge == ["laya"]
    assert "TYPESAFE_API_KEY" not in (target / WORKFLOW).read_text()


def test_s1_jev_writes_the_typesafe_profile_and_the_workflow_names_its_key(target: Path, git_environ):
    """SCN-ADO-46"""
    assert init(target, git_environ, *BASE, "--s1", "jev") == 0
    config = written_config(target)
    assert config["roles"]["s1_judge"] == ["jev"]
    assert config["profiles"]["jev"] == {
        "backend": "system-one",
        "engine": "jev",
        "base_url": "https://api.typesafe.ai",
        "model": "jev-1.13.0",
        "api_key_env": "TYPESAFE_API_KEY",
        "vendor": "typesafe",
    }
    assert "laya" not in config["profiles"]
    load_config(target)
    assert "TYPESAFE_API_KEY: ${{ secrets.TYPESAFE_API_KEY }}" in (target / WORKFLOW).read_text()


def test_s1_none_writes_no_system_one_and_a_todo(target: Path, git_environ, capsys):
    assert init(target, git_environ, *BASE, "--s1", "none") == 0
    config = written_config(target)
    assert "s1_judge" not in config["roles"] and "laya" not in config["profiles"]
    assert "# TODO:" in (target / ".l4/config.yaml").read_text()
    assert "todo:" in capsys.readouterr().err
    load_config(target)


def test_an_unknown_s1_choice_is_exit_2(target: Path, git_environ):
    assert init(target, git_environ, *BASE, "--s1", "grok") == 2


def test_the_final_notes_name_l4_skills_install(target: Path, git_environ, capsys):  # skills-install 3.1
    assert init(target, git_environ, *BASE) == 0
    notes = [line for line in capsys.readouterr().err.splitlines() if line.startswith("note:")]
    assert sum("l4 skills install" in line for line in notes) == 1


def test_the_plain_notes_name_l4_skills_install(target: Path, harness_repo: Path, git_environ, capsys):  # 3.1
    flags = ["--harness", str(harness_repo), "--ci", "gitlab", "--vendor"]
    assert main(["init", "--repo", str(target), *flags], environ=git_environ) == 0
    notes = [line for line in capsys.readouterr().err.splitlines() if line.startswith("note:")]
    assert sum("l4 skills install" in line for line in notes) == 1
