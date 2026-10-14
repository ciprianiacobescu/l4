import os
import re
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from l4.ci.render import INCLUDE_SNIPPET, SHIM_RELPATH, TEMPLATE_RELPATH, render_gitlab_ci
from l4.config.schema import L4Config

NEVER_ON_HARNESS_COMMITS = (
    '$CI_COMMIT_BRANCH != "main" && $CI_COMMIT_MESSAGE =~ /\\nL4-Run: / && $CI_PIPELINE_SOURCE == "push"'
)
RUN_LINE = ".l4/bin/l4 run || .l4/bin/l4 ci map-exit $?"
BASE_CHECKOUT = (
    '[ "$CI_COMMIT_BRANCH" = "$L4_BASE_BRANCH" ] || { git fetch --quiet origin '
    '"+refs/heads/$L4_BASE_BRANCH:refs/remotes/origin/$L4_BASE_BRANCH" && '
    'git checkout --quiet --detach "origin/$L4_BASE_BRANCH" && echo "l4: base checkout $(git rev-parse HEAD)"; }'
)

EXPECTED = {
    "l4": {
        "stage": ".post",
        "needs": [],
        "tags": ["agentic"],
        "resource_group": "l4",
        "environment": {"name": "l4", "action": "prepare"},  # HB-2: environment-scoped variables reach this job only
        "interruptible": False,
        "timeout": "180m",
        "allow_failure": {"exit_codes": [10, 11, 12, 13]},
        "variables": {"GIT_DEPTH": "0", "L4_BASE_BRANCH": "main"},
        "rules": [
            {"if": NEVER_ON_HARNESS_COMMITS, "when": "never"},
            {"if": '$CI_PIPELINE_SOURCE == "push" && $CI_COMMIT_BRANCH == "main"'},
            {"if": '$CI_PIPELINE_SOURCE == "push" && $CI_COMMIT_BRANCH =~ /^l4\\//'},
            {"if": "$CI_PIPELINE_SOURCE =~ /^(schedule|web|api|trigger)$/"},
        ],
        "before_script": [BASE_CHECKOUT],
        "script": [
            ".l4/bin/l4 doctor --ci --fix ${L4_ADOPTION_CHECK:+--adoption} || .l4/bin/l4 ci map-exit $?",
            ".l4/bin/l4 plan --sweep || .l4/bin/l4 ci map-exit $?",
            RUN_LINE,
        ],
        "after_script": [".l4/bin/l4 status"],
        "artifacts": {"when": "always", "paths": [".l4-out/"], "expire_in": "1 week"},
    }
}


def test_include_template_golden():
    assert yaml.safe_load(render_gitlab_ci()) == EXPECTED


def script_items(text: str) -> list[str]:
    """The raw text of every item under `before_script:`, `script:` and `after_script:`, as written in the file."""
    items, inside = [], False
    for line in text.splitlines():
        if re.match(r"^  (?:before_script|script|after_script):\s*$", line):
            inside = True
        elif inside and (match := re.match(r"^    - (.*)$", line)):
            items.append(match.group(1))
        elif inside and line.lstrip().startswith("#"):
            continue  # a comment between the key and its items does not end the list
        else:
            inside = False
    return items


def test_no_script_item_has_an_unquoted_colon_space():
    text = render_gitlab_ci()
    items = script_items(text)
    assert len(items) == 5
    for body in items:
        if ": " in body or body.endswith(":"):
            assert body.startswith("'") and body.endswith("'"), body
    data = yaml.safe_load(text)["l4"]
    for key in ("before_script", "script", "after_script"):
        assert all(isinstance(item, str) for item in data[key])  # an unquoted `a: b` would parse as a mapping


def test_every_script_line_is_one_line_and_pipes_through_map_exit():
    data = yaml.safe_load(render_gitlab_ci())["l4"]
    for item in data["script"]:
        assert "\n" not in item
        assert item.endswith("|| .l4/bin/l4 ci map-exit $?")


def test_the_job_has_no_other_jobs_and_nothing_secret():
    text = render_gitlab_ci()
    assert list(yaml.safe_load(text)) == ["l4"]
    assert "L4_FORGE_TOKEN" not in text and "PRIVATE-TOKEN" not in text


def test_include_snippet_is_the_one_the_human_adds():
    assert yaml.safe_load(INCLUDE_SNIPPET) == {"include": [{"local": ".l4/ci/l4.gitlab-ci.yml"}]}
    assert TEMPLATE_RELPATH == ".l4/ci/l4.gitlab-ci.yml" and SHIM_RELPATH == ".l4/bin/l4"


@pytest.fixture
def stub_repo(tmp_path: Path) -> Path:
    """A repo whose `.l4/bin/l4` is a stub: `ci map-exit` is the real command, everything else records its argv and
    exits with $STUB_CODE."""
    shim = tmp_path / ".l4" / "bin" / "l4"
    shim.parent.mkdir(parents=True)
    shim.write_text(
        f'#!/bin/sh\nif [ "$1" = ci ]; then exec {sys.executable} -m l4 "$@"; fi\n'
        'echo "$@" >> "$ARGV_LOG"\nexit "${STUB_CODE:-0}"\n'
    )
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR)
    return tmp_path


def run_script_line(repo: Path, line: str, **env: str) -> tuple[int, str, str]:
    full = {"PATH": "/usr/bin:/bin", "ARGV_LOG": str(repo / "argv.log"), **env}
    done = subprocess.run(["sh", "-c", line], cwd=repo, env=full, capture_output=True, text=True)
    log = repo / "argv.log"
    return done.returncode, done.stdout, log.read_text() if log.exists() else ""


def test_a_halt_is_an_allowed_failure_and_1_2_3_14_are_not():
    allowed = yaml.safe_load(render_gitlab_ci())["l4"]["allow_failure"]["exit_codes"]
    assert 13 in allowed and set(allowed) == {10, 11, 12, 13}
    assert not {1, 2, 3, 14} & set(allowed)  # a harness or environment fault, or a rejected unit, stays red


@pytest.mark.parametrize("code", [10, 11, 12, 13])
def test_gitlab_reexits_original_code_via_subprocess(stub_repo: Path, code: int):
    rc, out, _ = run_script_line(stub_repo, RUN_LINE, STUB_CODE=str(code))
    assert rc == code and f"l4 exit {code}" in out


def test_a_real_failure_stays_a_failure_and_success_stays_quiet(stub_repo: Path):
    assert run_script_line(stub_repo, RUN_LINE, STUB_CODE="3")[0] == 3
    assert run_script_line(stub_repo, RUN_LINE, STUB_CODE="0")[:2] == (0, "")


def test_the_job_runs_every_unit_with_work_and_names_no_unit(stub_repo: Path):
    _, _, argv = run_script_line(stub_repo, RUN_LINE)
    assert argv.strip() == "run"  # no `--unit`: `l4 run` plans and runs what is actionable
    text = render_gitlab_ci()
    assert "L4_UNIT" not in text and "--unit" not in text


def test_the_job_starts_on_pushes_to_the_default_branch_and_l4_branches_and_on_four_sources():
    rules = yaml.safe_load(render_gitlab_ci())["l4"]["rules"]
    assert rules[0] == {"if": NEVER_ON_HARNESS_COMMITS, "when": "never"}
    assert [r["if"] for r in rules[1:]] == [
        '$CI_PIPELINE_SOURCE == "push" && $CI_COMMIT_BRANCH == "main"',
        '$CI_PIPELINE_SOURCE == "push" && $CI_COMMIT_BRANCH =~ /^l4\\//',
        "$CI_PIPELINE_SOURCE =~ /^(schedule|web|api|trigger)$/",
    ]  # the never-rule comes first, so a harness commit starts nothing whichever rule would match it
    assert all("when" not in r for r in rules[1:])
    assert "`L4_UNIT`" not in render_gitlab_ci()


def test_the_job_has_a_stage_every_pipeline_has_and_a_three_hour_timeout():
    job = yaml.safe_load(render_gitlab_ci())["l4"]
    assert job["stage"] == ".post" and job["timeout"] == "180m"


def test_the_job_runs_doctor_then_the_sweep_then_the_run():
    script = yaml.safe_load(render_gitlab_ci())["l4"]["script"]
    commands = [line.split(" ||")[0] for line in script]
    assert commands == [
        ".l4/bin/l4 doctor --ci --fix ${L4_ADOPTION_CHECK:+--adoption}",
        ".l4/bin/l4 plan --sweep",
        ".l4/bin/l4 run",
    ]


# --- the base checkout one-liner ----------------------------------------------------------------------------------


def git(cwd: Path, *args: str) -> str:
    env = {"PATH": os.environ["PATH"], "HOME": str(cwd), "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}
    done = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "init.defaultBranch=main", *args],
        cwd=cwd, env=env, capture_output=True, text=True, check=True,
    )  # fmt: skip
    return done.stdout.strip()


def commit(repo: Path, name: str, text: str) -> str:
    (repo / name).write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", f"add {name}")
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def forge(tmp_path: Path) -> Path:
    """A bare remote with `main` (one file) and `l4/x` (main plus its own copy of the harness config)."""
    seed = tmp_path / "seed"
    seed.mkdir()
    git(seed, "init", "-q")
    commit(seed, "config.yaml", "from main\n")
    git(seed, "checkout", "-q", "-b", "l4/x")
    commit(seed, "config.yaml", "from the unit branch\n")
    bare = tmp_path / "forge.git"
    git(tmp_path, "init", "-q", "--bare", str(bare))
    git(seed, "remote", "add", "origin", str(bare))
    git(seed, "push", "-q", "origin", "main", "l4/x")
    return bare


def run_before_script(repo: Path, **env: str) -> subprocess.CompletedProcess:
    line = yaml.safe_load(render_gitlab_ci())["l4"]["before_script"][0]
    full = {
        "PATH": os.environ["PATH"], "HOME": str(repo), "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
        "L4_BASE_BRANCH": "main", **env,
    }  # fmt: skip
    return subprocess.run(["sh", "-c", line], cwd=repo, env=full, capture_output=True, text=True)


def test_on_an_l4_branch_the_checkout_is_the_head_of_the_default_branch_even_without_origin_main(forge, tmp_path):
    clone = tmp_path / "job"
    git(tmp_path, "clone", "-q", "--single-branch", "--branch", "l4/x", str(forge), str(clone))
    assert subprocess.run(["git", "rev-parse", "--verify", "-q", "origin/main"], cwd=clone).returncode != 0
    done = run_before_script(clone, CI_COMMIT_BRANCH="l4/x")
    assert done.returncode == 0, done.stderr
    assert git(clone, "rev-parse", "HEAD") == git(forge, "rev-parse", "main")
    assert f"l4: base checkout {git(forge, 'rev-parse', 'main')}\n" in done.stdout  # an effect the job log shows
    assert (clone / "config.yaml").read_text() == "from main\n"  # the harness comes from the base head


def test_a_stale_origin_main_of_a_reused_clone_is_refreshed(forge, tmp_path):
    clone = tmp_path / "job"
    git(tmp_path, "clone", "-q", str(forge), str(clone))
    git(clone, "checkout", "-q", "l4/x")
    newer = tmp_path / "newer"
    git(tmp_path, "clone", "-q", str(forge), str(newer))
    moved = commit(newer, "later.txt", "a merge landed\n")
    git(newer, "push", "-q", "origin", "main")
    assert git(clone, "rev-parse", "origin/main") != moved
    done = run_before_script(clone, CI_COMMIT_BRANCH="l4/x")
    assert done.returncode == 0, done.stderr
    assert git(clone, "rev-parse", "HEAD") == moved


def test_on_the_default_branch_the_checkout_is_left_alone(forge, tmp_path):
    clone = tmp_path / "job"
    git(tmp_path, "clone", "-q", str(forge), str(clone))
    before = git(clone, "rev-parse", "HEAD")
    git(forge, "update-ref", "refs/heads/main", git(forge, "rev-parse", "l4/x"))  # the remote moved; a fetch would show
    done = run_before_script(clone, CI_COMMIT_BRANCH="main")
    assert done.returncode == 0 and git(clone, "rev-parse", "HEAD") == before
    assert "base checkout" not in done.stdout
    assert git(clone, "branch", "--show-current") == "main"


def test_a_failed_fetch_fails_the_job_instead_of_running_the_branchs_own_harness(forge, tmp_path):
    clone = tmp_path / "job"
    git(tmp_path, "clone", "-q", "--single-branch", "--branch", "l4/x", str(forge), str(clone))
    git(clone, "remote", "set-url", "origin", str(tmp_path / "gone.git"))
    assert run_before_script(clone, CI_COMMIT_BRANCH="l4/x").returncode != 0


def test_a_fast_forward_merge_of_a_handed_off_unit_still_starts_the_job():
    """With the fast-forward merge method the default branch's head is H, which carries the `L4-Run` trailer: the
    never-rule must not apply to the default branch, or the merged unit would not be swept until another trigger. The
    harness never pushes to the default branch (the archive is a merge request), so this cannot loop."""
    rules = yaml.safe_load(render_gitlab_ci())["l4"]["rules"]
    assert rules[0]["when"] == "never" and '$CI_COMMIT_BRANCH != "main"' in rules[0]["if"]
    assert rules[1]["if"] == '$CI_PIPELINE_SOURCE == "push" && $CI_COMMIT_BRANCH == "main"'


# --- the configured base branch and prefix (L4-OPS-016) -----------------------------------------------------------


def configured(**forge: str) -> L4Config:
    return L4Config.model_validate({"forge": forge})


def test_the_default_config_renders_main_and_the_l4_prefix():
    job = yaml.safe_load(render_gitlab_ci(L4Config()))["l4"]
    assert job["variables"]["L4_BASE_BRANCH"] == "main"
    assert job["rules"][2]["if"] == '$CI_PIPELINE_SOURCE == "push" && $CI_COMMIT_BRANCH =~ /^l4\\//'
    assert render_gitlab_ci(L4Config()) == render_gitlab_ci()
    assert "CI_DEFAULT_BRANCH" not in render_gitlab_ci()


def test_a_base_branch_that_is_not_the_default_branch_reaches_both_rules_and_the_checkout():
    job = yaml.safe_load(render_gitlab_ci(configured(base_branch="l4/main")))["l4"]
    assert job["variables"] == {"GIT_DEPTH": "0", "L4_BASE_BRANCH": "l4/main"}
    assert '$CI_COMMIT_BRANCH != "l4/main" &&' in job["rules"][0]["if"] and job["rules"][0]["when"] == "never"
    assert job["rules"][1]["if"] == '$CI_PIPELINE_SOURCE == "push" && $CI_COMMIT_BRANCH == "l4/main"'
    assert job["before_script"] == [BASE_CHECKOUT]  # the line names the variable, so it is the same for every base


def test_a_branch_prefix_is_a_regex_with_escaped_slash_and_dot():
    rules = yaml.safe_load(render_gitlab_ci(configured(branch_prefix="bots/")))["l4"]["rules"]
    assert rules[2]["if"] == '$CI_PIPELINE_SOURCE == "push" && $CI_COMMIT_BRANCH =~ /^bots\\//'
    rules = yaml.safe_load(render_gitlab_ci(configured(branch_prefix="a.b/c-d/")))["l4"]["rules"]
    assert rules[2]["if"].endswith("=~ /^a\\.b\\/c-d\\//")


@pytest.mark.parametrize(
    "base",
    ["", "-x", "a b", "a..b", "a/", "x.lock", 'a"\n  evil: 1', "a'b", "a$b", "a;b", "/a", "a\\b", "a:b"],
)
def test_an_unsafe_base_branch_is_refused(base: str):
    cfg = L4Config()
    cfg.forge.base_branch = base
    with pytest.raises(ValueError, match="base branch"):
        render_gitlab_ci(cfg)


def test_a_rendered_custom_file_is_valid_yaml_with_the_same_job_keys():
    custom = yaml.safe_load(render_gitlab_ci(configured(base_branch="l4/main", branch_prefix="bots/")))
    assert list(custom) == ["l4"] and list(custom["l4"]) == list(EXPECTED["l4"])
