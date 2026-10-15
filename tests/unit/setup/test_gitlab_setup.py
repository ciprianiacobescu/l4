"""`l4 setup gitlab` (M1.8 A10): the forge side of adoption, in the CLI. Everything here runs against a fake GitLab
behind `httpx.MockTransport` (tests/unit/setup/conftest.py): no live calls."""

import pytest

from l4.exitcodes import ExitCode, L4Exit
from l4.setup.gitlab import derive_api_base, project_path


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        ("119", "119"),
        ("example-group/sample-consumer", "example-group%2Fsample-consumer"),
        ("example-group%2Fsample-consumer", "example-group%2Fsample-consumer"),  # an encoded path is decoded once
        ("example-group%2fsample-consumer", "example-group%2Fsample-consumer"),
        ("/group/sub/name/", "group%2Fsub%2Fname"),
        ("group/sub/name.git", "group%2Fsub%2Fname"),
    ],
)
def test_project_path_is_encoded_exactly_once(given, expected):
    assert project_path(given) == expected


@pytest.mark.parametrize(
    "bad", ["", "  ", "a//b", "a/../b", "a%252Fb", "a?b/c", "a#b/c", "a\\b/c", "gr%oup/x", "a%2F%2Fb"]
)
def test_a_bad_project_is_a_usage_error(bad):
    with pytest.raises(L4Exit) as err:
        project_path(bad)
    assert err.value.code == ExitCode.USAGE_ERROR and "--project" in str(err.value)


@pytest.mark.parametrize(
    ("origin", "base"),
    [
        ("https://gitlab.example.test/example-group/sample-consumer.git", "https://gitlab.example.test/api/v4"),
        ("git@gitlab.example.test:example-group/sample-consumer.git", "https://gitlab.example.test/api/v4"),
        ("ssh://git@gitlab.example.test:2222/g/p.git", "https://gitlab.example.test/api/v4"),
        ("https://oauth2:secret@gitlab.example.test/g/p.git", "https://gitlab.example.test/api/v4"),  # no userinfo
    ],
)
def test_api_base_is_derived_from_origin(origin, base):
    assert derive_api_base(origin) == base


def test_api_base_is_none_for_a_path_or_nothing():
    assert derive_api_base("/some/local/path") is None and derive_api_base("") is None


# --- the bot token and L4_FORGE_TOKEN (line 29) ------------------------------------------------------------------

import re  # noqa: E402

from .conftest import API, MAINTAINER, PATH, bot_token, variable  # noqa: E402


def rows(text: str, status: str) -> list[str]:
    return [line for line in text.splitlines() if line.startswith(status)]


def test_fresh_project_creates_token_and_scoped_masked_variable(gitlab, run_setup):
    code, out = run_setup()
    assert code == 0, out
    [token] = gitlab.tokens
    assert (token["name"], token["scopes"], token["access_level"], token["active"]) == (
        "l4-bot",
        ["api", "write_repository"],
        30,
        True,
    )
    [var] = gitlab.variables
    assert (var["key"], var["environment_scope"], var["masked"], var["protected"], var["raw"]) == (
        "L4_FORGE_TOKEN",
        "l4",
        True,
        False,
        True,
    )
    assert var["value"] == token["_value"]  # the value went from the create response straight into the variable
    assert rows(out, "NEW") and "token l4-bot" in rows(out, "NEW")[0]
    assert any("variable L4_FORGE_TOKEN" in r and "environment scope l4" in r for r in rows(out, "SET"))
    assert token["_value"] not in out and MAINTAINER not in out
    assert gitlab.requests[0]["method"] == "GET" and gitlab.requests[0]["raw"].endswith(
        "/projects/example-group%2Fsample-consumer"
    )


def test_second_run_sends_only_gets(gitlab, run_setup):
    assert run_setup()[0] == 0
    gitlab.requests.clear()
    code, out = run_setup()
    assert code == 0 and gitlab.writes() == [], gitlab.writes()
    assert len(rows(out, "KEPT")) >= 2 and "token l4-bot" in out and "variable L4_FORGE_TOKEN" in out
    assert len(gitlab.tokens) == 1


def test_missing_variable_creates_a_token_and_warns_the_old_one_is_active(gitlab, run_setup):
    old = bot_token(gitlab)
    code, out = run_setup()
    assert code == 0
    assert len([t for t in gitlab.tokens if t["active"]]) == 2  # the old value cannot be read back: a new token
    assert any(f"id={old['id']}" in r and "still active" in r for r in rows(out, "WARN")), out
    assert gitlab.find_variable("L4_FORGE_TOKEN", "l4")["value"] != old["_value"]


def test_rotate_creates_sets_verifies(gitlab, run_setup):
    old = bot_token(gitlab)
    variable(gitlab, "L4_FORGE_TOKEN", old["_value"])
    gitlab.requests.clear()
    code, out = run_setup(rotate=True)
    assert code == 0, out
    new = next(t for t in gitlab.tokens if t["id"] != old["id"])
    assert gitlab.find_variable("L4_FORGE_TOKEN", "l4")["value"] == new["_value"]
    assert old["active"] is True  # not revoked without --revoke-old ...
    assert any(f"id={old['id']}" in r and "--revoke-old" in r for r in rows(out, "WARN")), out  # ... and said
    verify = [r for r in gitlab.requests if r["who"] == "bot"]
    assert [r["method"] for r in verify] == ["GET"] and any("can read project" in r for r in rows(out, "OK"))
    methods = [m for m, _ in gitlab.writes()]
    assert methods == ["POST", "PUT"]  # the token, then the variable: set after create, verified after set


def test_revoke_old_revokes_only_after_verification(gitlab, run_setup):
    old = bot_token(gitlab)
    variable(gitlab, "L4_FORGE_TOKEN", old["_value"])
    code, out = run_setup(rotate=True, revoke_old=True)
    assert code == 0 and old["revoked"] is True and old["active"] is False, out
    assert any(f"revoked token id={old['id']}" in r for r in rows(out, "OK"))
    assert [t for t in gitlab.tokens if t["active"]] and len([t for t in gitlab.tokens if t["active"]]) == 1
    order = [(m, p) for m, p in gitlab.writes()]
    assert order[-1][0] == "DELETE"  # the last thing done


def test_failed_verification_exits_3_and_revokes_nothing(gitlab, run_setup):
    old = bot_token(gitlab)
    variable(gitlab, "L4_FORGE_TOKEN", old["_value"])
    gitlab.reject_bot = True
    code, out = run_setup(rotate=True, revoke_old=True)
    assert code == 3, out
    assert rows(out, "FAIL") and "new token" in rows(out, "FAIL")[0]
    assert old["active"] is True and not [w for w in gitlab.writes() if w[0] == "DELETE"]


def test_verification_goes_to_verify_base_with_the_bot_token(gitlab, run_setup):
    gitlab.scheme = "bearer"
    proxy = "http://localhost:8000/v1/call/svc_1"
    code, out = run_setup(api_base=proxy, auth_scheme="bearer", verify_base=API)
    assert code == 0, out
    bot_gets = [r for r in gitlab.requests if r["who"] == "bot"]
    assert len(bot_gets) == 1 and bot_gets[0]["path"].startswith("/projects/")
    assert all(r["who"] == "maintainer" for r in gitlab.requests if r["who"] != "bot")
    assert MAINTAINER not in out


def test_unscoped_twin_is_reported_not_deleted(gitlab, run_setup):
    variable(gitlab, "L4_FORGE_TOKEN", "an old unscoped value", scope="*")
    code, out = run_setup()
    assert code == 0
    assert any("unscoped" in r and "L4_FORGE_TOKEN" in r for r in rows(out, "WARN")), out
    assert gitlab.find_variable("L4_FORGE_TOKEN", "*") is not None
    assert not [w for w in gitlab.writes() if w[0] == "DELETE"]
    assert re.search(r"NEW\s+token", out)


# --- --secret NAME=ENV (line 30) ---------------------------------------------------------------------------------


def test_secret_created_then_kept_then_updated(gitlab, run_setup):
    env = {"MY_KEY": "first-secret-value-0001"}
    code, out = run_setup(secret=("TYPESAFE_API_KEY=MY_KEY",), env=env)
    assert code == 0, out
    var = gitlab.find_variable("TYPESAFE_API_KEY", "l4")
    assert var["value"] == "first-secret-value-0001"
    assert (var["masked"], var["protected"], var["raw"]) == (True, False, True)
    assert any("variable TYPESAFE_API_KEY" in r for r in rows(out, "NEW"))
    gitlab.requests.clear()
    code, out = run_setup(secret=("TYPESAFE_API_KEY=MY_KEY",), env=env)
    assert code == 0 and gitlab.writes() == [], gitlab.writes()  # compared in memory: equal is KEPT
    assert any("variable TYPESAFE_API_KEY" in r for r in rows(out, "KEPT"))
    code, out = run_setup(secret=("TYPESAFE_API_KEY=MY_KEY",), env={"MY_KEY": "second-secret-value-0002"})
    assert code == 0 and gitlab.find_variable("TYPESAFE_API_KEY", "l4")["value"] == "second-secret-value-0002"
    assert any("variable TYPESAFE_API_KEY" in r for r in rows(out, "SET"))
    for text in (out,):
        assert "first-secret-value-0001" not in text and "second-secret-value-0002" not in text


def test_a_variable_with_the_wrong_flags_is_set_again(gitlab, run_setup):
    variable(gitlab, "TYPESAFE_API_KEY", "same-secret-value-0003", masked=False, protected=True)
    code, out = run_setup(secret=("TYPESAFE_API_KEY=MY_KEY",), env={"MY_KEY": "same-secret-value-0003"})
    var = gitlab.find_variable("TYPESAFE_API_KEY", "l4")
    assert code == 0 and (var["masked"], var["protected"], var["raw"]) == (True, False, True)
    assert any("TYPESAFE_API_KEY" in r for r in rows(out, "SET"))


def test_empty_source_env_refuses_before_any_write(gitlab, run_setup):
    code, out = run_setup(secret=("TYPESAFE_API_KEY=MY_KEY",), env={"MY_KEY": ""})
    assert code == 2 and "MY_KEY" in out
    assert gitlab.requests == []  # not even a read: the usage error comes first
    code, _ = run_setup(secret=("TYPESAFE_API_KEY=NOT_SET_AT_ALL",))
    assert code == 2 and gitlab.requests == []


@pytest.mark.parametrize("bad", ["lower-case=MY_KEY", "NAME", "NAME=", "=MY_KEY", "A=B=C", "1BAD=MY_KEY"])
def test_bad_variable_name_is_a_usage_error(gitlab, run_setup, bad):
    code, out = run_setup(secret=(bad,), env={"MY_KEY": "some-secret-value-0004"})
    assert code == 2 and "--secret" in out and gitlab.requests == []


def test_a_secret_named_twice_is_a_usage_error(gitlab, run_setup):
    code, _ = run_setup(secret=("A_B=MY_KEY", "A_B=MY_KEY"), env={"MY_KEY": "some-secret-value-0005"})
    assert code == 2 and gitlab.requests == []


# --- the l4 sweep schedule (line 31) -----------------------------------------------------------------------------


def schedule(gitlab, **over):
    entry = {"id": gitlab.fresh_id(), "description": "l4 sweep", "ref": "refs/heads/main", "cron": "*/30 * * * *",
             "cron_timezone": "UTC", "active": True, **over}  # fmt: skip
    gitlab.schedules.append(entry)
    return entry


def test_schedule_created_once_then_kept(gitlab, run_setup):
    code, out = run_setup(no_schedule=False)
    assert code == 0, out
    [entry] = gitlab.schedules
    assert (entry["description"], entry["cron"], entry["active"]) == ("l4 sweep", "*/30 * * * *", True)
    assert entry["ref"].endswith("main") and entry["cron_timezone"] == "UTC"
    assert any("schedule l4 sweep" in r and "*/30 * * * *" in r for r in rows(out, "NEW"))
    gitlab.requests.clear()
    code, out = run_setup(no_schedule=False)
    assert code == 0 and gitlab.writes() == []
    assert any("schedule l4 sweep" in r for r in rows(out, "KEPT")) and len(gitlab.schedules) == 1


def test_schedule_with_another_cron_or_ref_is_updated(gitlab, run_setup):
    entry = schedule(gitlab, cron="0 3 * * *")
    code, out = run_setup(no_schedule=False)
    assert code == 0 and entry["cron"] == "*/30 * * * *" and len(gitlab.schedules) == 1
    assert any("schedule l4 sweep" in r and "0 3 * * *" in r for r in rows(out, "SET")), out
    other = schedule(gitlab, description="l4 sweep", ref="refs/heads/old", cron="*/30 * * * *")
    gitlab.schedules.remove(entry)
    code, out = run_setup(no_schedule=False)
    assert other["ref"].endswith("main") and any("schedule" in r for r in rows(out, "SET"))


def test_a_custom_cron_is_used_and_kept(gitlab, run_setup):
    assert run_setup(no_schedule=False, cron="0 * * * *")[0] == 0
    assert gitlab.schedules[0]["cron"] == "0 * * * *"
    gitlab.requests.clear()
    assert run_setup(no_schedule=False, cron="0 * * * *")[0] == 0 and gitlab.writes() == []


def test_inactive_schedule_is_reactivated(gitlab, run_setup):
    entry = schedule(gitlab, active=False)
    code, out = run_setup(no_schedule=False)
    assert code == 0 and entry["active"] is True
    assert any("reactivated" in r for r in rows(out, "SET")), out


def test_no_schedule_skips_it(gitlab, run_setup):
    code, out = run_setup(no_schedule=True)
    assert code == 0 and gitlab.schedules == []
    assert not [r for r in gitlab.requests if "pipeline_schedules" in r["path"]]
    assert "schedule" in out and "skipped" in out  # said, not silent


def test_a_schedule_the_credential_may_not_touch_is_a_warning_that_explains(gitlab, run_setup):
    gitlab.deny.add("schedules")
    code, out = run_setup(no_schedule=False)
    assert code == 1 and "403" in out and "Maintainer" in out  # the HTTP error, with the reason
    assert any("variable L4_FORGE_TOKEN" in r for r in rows(out, "SET"))  # what was done before is in the rows


# --- runners and the include on the default branch (line 32) -----------------------------------------------------

from .conftest import GOOD_CI, runner  # noqa: E402


def test_no_online_tagged_runner_fails_with_exit_3(gitlab, run_setup):
    gitlab.runners = []
    code, out = run_setup()
    assert code == 3, out
    assert any("stay pending" in r and "agentic" in r for r in rows(out, "FAIL")), out
    gitlab.runners = [runner(12, "project_type", online=False)]
    code, out = run_setup()
    assert code == 3 and any("no online runner" in r for r in rows(out, "FAIL"))
    assert gitlab.tokens  # the other rows still ran: setup reports every problem it can see, in one pass


def test_instance_runner_on_a_private_project_warns(gitlab, run_setup):
    code, out = run_setup()
    assert code == 0
    [warn] = [r for r in rows(out, "WARN") if "runner" in r]
    assert "#12" in warn and "instance" in warn and "any project of this GitLab" in warn


@pytest.mark.parametrize(("visibility", "who"), [("public", "anyone"), ("internal", "every signed-in user")])
def test_instance_runner_on_a_public_or_internal_project_warns_louder(gitlab, run_setup, visibility, who):
    """The runner's agent logins and the l4 job's token sit next to any tagged job of the instance, whatever this
    project's visibility; a public or internal project also shows its code and merge requests to more people."""
    gitlab.visibility = visibility
    code, out = run_setup()
    assert code == 0, out
    [warn] = [r for r in rows(out, "WARN") if "runner #12" in r]
    assert "instance" in warn and "any project of this GitLab" in warn and "agent logins" in warn
    assert f"the project is {visibility}" in warn and who in warn
    assert f"on {'an' if visibility == 'internal' else 'a'} {visibility} project" in warn
    assert not [r for r in rows(out, "OK") if "runner #12" in r]


def test_project_runner_is_ok_and_its_type_printed(gitlab, run_setup):
    gitlab.runners = [runner(8, "project_type", description="own"), runner(12, "instance_type")]
    code, out = run_setup()
    assert code == 0, out
    assert any("runner #8" in r and "project_type" in r for r in rows(out, "OK"))
    # GitLab gives a project runner no priority: the l4 job may still land on the instance runner
    assert [r for r in rows(out, "WARN") if "runner #12" in r and "instance" in r], out


def test_an_instance_runner_with_shared_runners_off_is_not_used_and_not_a_warning(gitlab, run_setup):
    gitlab.runners = [runner(8, "project_type", description="own"), runner(12, "instance_type")]
    gitlab.shared_runners_enabled = False
    code, out = run_setup()
    assert code == 0, out
    assert not [r for r in rows(out, "WARN") if "runner" in r], out
    assert any("runner #12" in r and "shared runners are off" in r for r in rows(out, "OK")), out


def test_only_instance_runners_with_shared_runners_off_fails(gitlab, run_setup):
    gitlab.shared_runners_enabled = False
    code, out = run_setup()
    assert code == 3 and any("shared runners are off" in r for r in rows(out, "FAIL")), out


def test_a_credential_that_may_not_list_runners_is_a_warning_that_explains(gitlab, run_setup):
    gitlab.deny.add("runners")
    code, out = run_setup()
    assert code == 0, out
    assert any("cannot list runners" in r and "Maintainer" in r for r in rows(out, "WARN")), out


def test_missing_include_on_the_default_branch_warns(gitlab, run_setup):
    gitlab.files[".gitlab-ci.yml"] = "build:\n  script: [make]\n"
    code, out = run_setup()
    assert code == 0
    assert any(".gitlab-ci.yml" in r and "does not include .l4/ci/l4.gitlab-ci.yml" in r for r in rows(out, "WARN"))
    del gitlab.files[".gitlab-ci.yml"]
    _, out = run_setup()
    assert any("no .gitlab-ci.yml on main" in r for r in rows(out, "WARN"))
    gitlab.default_branch = ""
    _, out = run_setup()
    assert any("no default branch" in r for r in rows(out, "WARN"))


def test_the_include_is_found_and_the_repository_jobs_are_named(gitlab, run_setup):
    code, out = run_setup()
    assert code == 0
    ok = [r for r in rows(out, "OK") if ".gitlab-ci.yml on main" in r]
    assert ok and "includes .l4/ci/l4.gitlab-ci.yml" in ok[0] and "test" in ok[0]
    assert "scheduled pipeline" in ok[0]  # the sweep's pipeline runs these jobs too: said, not hidden


def test_a_configured_base_branch_gets_the_include_check_and_the_schedule(gitlab, run_setup, setup_repo):
    """L4-OPS-016 / L4-YOLO-007: with `forge.base_branch: staging` and `main` the project's default branch, the harness
    job runs on staging, so the include is checked there and the l4 sweep schedule runs there."""
    (setup_repo / ".l4").mkdir(exist_ok=True)
    (setup_repo / ".l4" / "config.yaml").write_text("version: 1\nforge:\n  type: gitlab\n  base_branch: staging\n")
    gitlab.files_ref = "staging"
    code, out = run_setup(no_schedule=False)
    assert code == 0, out
    assert any(".gitlab-ci.yml on staging" in r for r in rows(out, "OK"))
    [entry] = gitlab.schedules
    assert entry["ref"].endswith("staging")


def test_untagged_repository_jobs_are_a_warning(gitlab, run_setup):
    gitlab.files[".gitlab-ci.yml"] = GOOD_CI.replace("  tags: [agentic]\n", "")
    _, out = run_setup()
    assert any("lack the runner tags" in r and "test" in r for r in rows(out, "WARN")), out


# --- the command: summary, exit codes, --dry-run, redaction (line 33) ------------------------------------------------


@pytest.fixture
def cli(gitlab, setup_repo, git_environ, monkeypatch, capsys, caplog):
    """`l4 setup gitlab ...` through `main()`, with the fake server behind the module's transport hook."""
    from l4.cli import main
    from l4.setup import gitlab as module

    monkeypatch.setattr(module, "TRANSPORT", gitlab.transport())

    def run(*args: str, **env: str) -> tuple[int, str, str]:
        environ = {**git_environ, "GITLAB_TOKEN": MAINTAINER, **env}
        argv = ["setup", "gitlab", "--repo", str(setup_repo), "--api-base", API, *args]
        code = main(argv, environ=environ)
        out = capsys.readouterr()
        return code, out.out, out.err + caplog.text

    return run


def test_output_and_logs_never_contain_a_secret_value(gitlab, cli):
    env = {"MY_KEY": "typesafe-secret-value-0099"}
    code, out, err = cli(
        "--project", PATH, "--secret", "TYPESAFE_API_KEY=MY_KEY", "--no-pipeline", "-vv", **env,
    )  # fmt: skip
    assert code == 0, out + err
    assert gitlab.issued, "a token was created"
    every = out + err
    for secret in (MAINTAINER, "typesafe-secret-value-0099", *gitlab.issued):
        assert secret not in every
    assert "glpat-" not in every  # no token shape either


def test_the_summary_line_counts_the_rows_and_names_the_exit_code(gitlab, cli):
    code, out, _ = cli("--project", PATH, "--no-pipeline")
    assert code == 0
    last = out.strip().splitlines()[-1]
    assert re.fullmatch(r"summary: \d+ ok, \d+ new, \d+ set, \d+ kept, \d+ warn, 0 fail -> exit 0", last), last
    gitlab.runners = []
    code, out, _ = cli("--project", PATH, "--no-pipeline")
    assert code == 3 and out.strip().splitlines()[-1].endswith("1 fail -> exit 3")


def test_dry_run_sends_only_gets(gitlab, cli):
    code, out, _ = cli("--project", PATH, "--dry-run", "--secret", "A_B=MY_KEY", MY_KEY="a-secret-value-0001")
    assert code == 0, out
    assert gitlab.writes() == [], gitlab.writes()
    assert gitlab.tokens == [] and gitlab.variables == [] and gitlab.schedules == []
    assert "would create schedule" in out and "dry run" in out
    assert any("token l4-bot" in r and "would create" in r for r in rows(out, "NEW"))


def test_exit_codes(gitlab, cli, monkeypatch):
    assert cli("--project", PATH, "--no-pipeline", "--no-schedule")[0] == 0
    assert cli("--project", PATH, "--no-pipeline", GITLAB_TOKEN="")[0] == 2  # no credential
    assert cli("--project", "a//b")[0] == 2  # a bad project
    assert cli("--project", PATH, "--revoke-old")[0] == 2  # --revoke-old needs --rotate
    assert cli("--project", PATH, "--cron", "every day")[0] == 2
    code, out, _ = cli("--project", "no/such-project", "--no-pipeline")
    assert code == 1 and "ERROR GET projects/no%2Fsuch-project: HTTP 404" in out  # an HTTP error, explained
    gitlab.runners = []
    assert cli("--project", PATH, "--no-pipeline")[0] == 3
    gitlab.credential = "someone-elses-token-0123456789"
    code, out, _ = cli("--project", PATH)
    assert code == 1 and "HTTP 401" in out and "credential was refused" in out


def test_without_a_config_the_schema_defaults_are_used_and_named(gitlab, cli):
    code, out, _ = cli("--project", PATH, "--no-pipeline", "--no-schedule")
    assert code == 0
    assert any("no .l4/config.yaml" in r and "L4_FORGE_TOKEN" in r and "[agentic]" in r for r in rows(out, "OK")), out


def test_a_config_sets_the_variable_name_and_the_runner_tags(gitlab, cli, setup_repo):
    (setup_repo / ".l4").mkdir()
    (setup_repo / ".l4" / "config.yaml").write_text("forge: {token_env: MY_BOT_TOKEN}\nci: {runner_tags: [gpu]}\n")
    code, out, _ = cli("--project", PATH, "--no-pipeline", "--no-schedule")
    assert code == 3  # the fake's only runner carries `agentic`, not `gpu`: the l4 job would stay pending
    assert gitlab.find_variable("MY_BOT_TOKEN", "l4") is not None and "[gpu]" in out
    assert "no .l4/config.yaml" not in out


def test_an_invalid_config_is_exit_2(gitlab, cli, setup_repo):
    (setup_repo / ".l4").mkdir()
    (setup_repo / ".l4" / "config.yaml").write_text("verifer: {}\n")
    code, _, err = cli("--project", PATH)
    assert code == 2 and gitlab.requests == [] and "verifer" in err


def test_the_api_base_falls_back_to_origin_and_a_missing_one_is_a_usage_error(
    gitlab, setup_repo, git_environ, monkeypatch, capsys
):
    from l4.cli import main
    from l4.setup import gitlab as module

    monkeypatch.setattr(module, "TRANSPORT", gitlab.transport())
    environ = {**git_environ, "GITLAB_TOKEN": MAINTAINER}
    argv = ["setup", "gitlab", "--repo", str(setup_repo), "--project", PATH, "--no-pipeline", "--no-schedule"]
    assert main(argv, environ=environ) == 0  # origin is https://gitlab.example.test/...: its /api/v4
    assert gitlab.requests[0]["raw"].startswith("/api/v4/projects/")
    import subprocess

    subprocess.run(["git", "remote", "remove", "origin"], cwd=setup_repo, env=git_environ, check=True)
    capsys.readouterr()
    assert main(argv, environ=environ) == 2 and "--api-base" in capsys.readouterr().err


# --- the check pipeline (line 34) --------------------------------------------------------------------------------


def posts_of_pipelines(gitlab) -> list[dict]:
    return [r for r in gitlab.requests if r["method"] == "POST" and r["path"].endswith("/pipeline")]


def test_pipeline_triggered_once_with_the_adoption_variable(gitlab, run_setup):
    code, out = run_setup(no_pipeline=False)
    assert code == 0, out
    [post] = posts_of_pipelines(gitlab)
    assert post["body"]["ref"] == "main"
    assert [(v["key"], v["value"]) for v in post["body"]["variables"]] == [("L4_ADOPTION_CHECK", "1")]
    [pipeline] = gitlab.pipelines
    assert any(f"pipeline #{pipeline['id']}" in r and pipeline["web_url"] in r for r in rows(out, "OK")), out
    # the token and the variable exist by then: the first pipeline cannot be the red one of CI-001
    order = [(m, p.rsplit("/", 1)[-1]) for m, p in gitlab.writes()]
    assert order.index(("POST", "variables")) < order.index(("POST", "pipeline"))
    gitlab.requests.clear()
    assert run_setup(no_pipeline=False)[0] == 0
    assert len(posts_of_pipelines(gitlab)) == 1 and [m for m, _ in gitlab.writes()] == ["POST"]  # only the check


def test_no_pipeline_and_dry_run_trigger_nothing(gitlab, run_setup):
    code, out = run_setup(no_pipeline=True)
    assert code == 0 and gitlab.pipelines == [] and "pipeline" in out and "skipped" in out
    gitlab.requests.clear()
    code, out = run_setup(no_pipeline=False, dry_run=True)
    assert code == 0 and gitlab.pipelines == [] and "would trigger" in out and gitlab.writes() == []


def test_no_pipeline_is_triggered_after_a_failed_row_or_without_the_include(gitlab, run_setup):
    gitlab.runners = []
    code, out = run_setup(no_pipeline=False)
    assert code == 3 and gitlab.pipelines == [] and "not triggered" in out
    gitlab.runners = [runner(12, "instance_type")]
    gitlab.files[".gitlab-ci.yml"] = "build:\n  script: [make]\n"
    code, out = run_setup(no_pipeline=False)
    assert code == 0 and gitlab.pipelines == [] and any("not triggered" in r for r in rows(out, "WARN"))


# --- --watch (line 36) -------------------------------------------------------------------------------------------


def test_watch_follows_the_triggered_pipeline(gitlab, run_setup):
    code, out = run_setup(no_pipeline=False, watch=True)
    assert code == 0, out
    [pipeline] = gitlab.pipelines
    assert f"pipeline #{pipeline['id']} success" in out
    assert re.search(r"job \d+ l4 \(\.post\) success — runner #12 l4-runner", out)
    assert any("adoption check passed" in r for r in rows(out, "OK")) and out.strip().endswith("exit 0")


def test_a_red_adoption_check_is_exit_3_and_shows_the_jobs_trace(gitlab, run_setup):
    gitlab.pipeline_status = "failed"
    code, out = run_setup(no_pipeline=False, watch=True)
    assert code == 3, out
    assert "GATE-001 fail: 2 tests fail at the base" in out  # the tail of the failed job's trace
    assert any("did not pass" in r for r in rows(out, "FAIL"))


def test_without_watch_the_pipeline_is_not_followed(gitlab, run_setup):
    code, out = run_setup(no_pipeline=False)
    assert code == 0 and "job " not in out


def test_a_token_in_a_job_trace_is_redacted_without_a_trace_of_its_value(gitlab, run_setup):
    """The redaction marker names what was cut, never a piece of it: a marker such as `[REDACTED:...:ijkl]` would
    print the token's last characters (here the job leaks the new bot token unmasked, and setup prints the tail)."""
    gitlab.pipeline_status = "failed"
    trigger = gitlab.trigger_route

    def leaking(*args, **kwargs):
        answer = trigger(*args, **kwargs)
        job = max(gitlab.traces)
        gitlab.traces[job] += f"\nexport TOKEN={gitlab.issued[-1]}"
        return answer

    gitlab.trigger_route = leaking
    code, out = run_setup(no_pipeline=False, watch=True)
    assert code == 3, out
    [token] = gitlab.issued
    assert "[REDACTED:" in out
    markers = re.findall(r"\[REDACTED:[^\]]*\]", out)
    for size in (4, 6):
        assert not any(token[-size:] in marker for marker in markers), markers
    assert token not in out


def test_an_answer_that_is_not_json_is_an_error_row_with_the_summary(gitlab, run_setup):
    import httpx

    gitlab.handle = lambda request: httpx.Response(200, text="<html>Sign in</html>")  # a web page, not the API
    code, out = run_setup()
    assert code == 1, out
    assert "ERROR GET projects/example-group%2Fsample-consumer: HTTP 200: the answer is not JSON" in out, out
    assert out.strip().splitlines()[-1].endswith("-> exit 1")


def test_an_instance_runner_row_names_its_tags(gitlab, run_setup):
    """M1.8 live F1: runner 12's own answer is `tag_list: [agentic, ai, opencode]`; the list endpoint omits it, so the
    row said the type and the warning and never the tags the `l4` job would be matched on."""
    gitlab.runners = [
        runner(8, "project_type", description="own", tags=["agentic"]),
        runner(12, "instance_type", description="l4-runner", tags=["agentic", "ai", "opencode"]),
    ]
    code, out = run_setup()
    assert code == 0, out
    [own] = [r for r in rows(out, "OK") if "runner #8" in r]
    [shared] = [r for r in rows(out, "WARN") if "runner #12" in r]
    assert own.rstrip().endswith("tags: agentic") and shared.rstrip().endswith("tags: agentic, ai, opencode")
    assert "any project of this GitLab" in shared  # the warning itself is unchanged
    assert [path for method, path in gitlab.gets() if path.startswith("/runners/")] == ["/runners/8", "/runners/12"]


def test_unreadable_runner_details_say_so_and_change_nothing(gitlab, run_setup):
    plain_code, plain = run_setup()
    gitlab.deny.add("runner-details")
    code, out = run_setup()
    assert code == plain_code == 0, out
    [shared] = [r for r in rows(out, "WARN") if "runner #12" in r]
    assert shared.rstrip().endswith("tags: not readable (403)")
    assert [r.split(" tags:")[0] for r in rows(out, "WARN")] == [r.split(" tags:")[0] for r in rows(plain, "WARN")]
    assert rows(out, "FAIL") == rows(plain, "FAIL") == []  # no verdict moved
