"""`l4 setup gitlab` end to end against the fake server (M1.8 A10, SCN-INS-15 and SCN-INS-16): an empty project, then
the same command again."""

import re

from .conftest import MAINTAINER


def shape(out: str) -> list[tuple[str, str]]:
    """(status, subject) of each row, with ids and numbers made comparable and the detail dropped."""
    found = []
    for line in out.splitlines():
        match = re.match(r"^(OK|NEW|SET|KEPT|WARN|FAIL)\s+(.*)$", line)
        if match:
            subject = re.sub(r"id=\d+", "id=N", re.sub(r"#\d+", "#N", match[2]))
            subject = re.split(r" \(|: | no | can read| includes| is an| triggered| schema| private| scopes=", subject)[
                0
            ]
            found.append((match[1], subject.strip()))
    return found


def test_first_and_second_run(gitlab, run_setup):
    env = {"MY_KEY": "typesafe-secret-value-0042"}
    options = {"secret": ("TYPESAFE_API_KEY=MY_KEY",), "no_schedule": False, "no_pipeline": False, "env": env}
    code, first = run_setup(**options)
    assert code == 0, first
    assert shape(first) == [
        ("OK", "config"),
        ("OK", "project example-group/sample-consumer"),
        ("WARN", "runner #N"),
        ("OK", ".gitlab-ci.yml on main"),
        ("NEW", "token l4-bot id=N"),
        ("SET", "variable L4_FORGE_TOKEN"),
        ("OK", "new token"),
        ("NEW", "variable TYPESAFE_API_KEY"),
        ("OK", "variables"),
        ("NEW", "schedule l4 sweep"),
        ("OK", "pipeline #N"),
    ], first
    # everything the first run did, in the order it did it
    assert [(m, p.split("/", 3)[-1]) for m, p in gitlab.writes()] == [
        ("POST", "access_tokens"), ("POST", "variables"), ("POST", "variables"),
        ("POST", "pipeline_schedules"), ("POST", "pipeline"),
    ]  # fmt: skip
    assert len(gitlab.tokens) == 1 and len(gitlab.schedules) == 1 and len(gitlab.pipelines) == 1
    assert {v["key"] for v in gitlab.variables} == {"L4_FORGE_TOKEN", "TYPESAFE_API_KEY"}
    assert all(v["environment_scope"] == "l4" and v["masked"] for v in gitlab.variables)
    for value in (MAINTAINER, "typesafe-secret-value-0042", *gitlab.issued):
        assert value not in first

    gitlab.requests.clear()
    code, second = run_setup(**options)
    assert code == 0, second
    assert shape(second) == [
        ("OK", "config"),
        ("OK", "project example-group/sample-consumer"),
        ("WARN", "runner #N"),
        ("OK", ".gitlab-ci.yml on main"),
        ("KEPT", "token l4-bot id=N"),
        ("KEPT", "variable L4_FORGE_TOKEN"),
        ("KEPT", "variable TYPESAFE_API_KEY"),
        ("OK", "variables"),
        ("KEPT", "schedule l4 sweep"),
        ("OK", "pipeline #N"),
    ], second
    assert [(m, p.rsplit("/", 1)[-1]) for m, p in gitlab.writes()] == [("POST", "pipeline")]  # reads, and the check
    assert len(gitlab.tokens) == 1 and len(gitlab.schedules) == 1 and len(gitlab.pipelines) == 2
    # the project's endpoints, and (M1.10) `GET runners/:id` for the tags of each usable runner
    # (hotfix 0.4.24) and the groups' and the instance's variables
    assert all(
        r["raw"].startswith(("/api/v4/projects/", "/api/v4/runners/", "/api/v4/groups/", "/api/v4/admin/"))
        for r in gitlab.requests
    )
    assert gitlab.requests[0]["raw"].endswith("example-group%2Fsample-consumer")  # the path, encoded once
    assert all(r["who"] == "maintainer" for r in gitlab.requests)  # the bot token was used only to verify, in run one


# --- M1.10 line 22 (C8): --token-command refreshes the credential on a 401 ---

import contextlib  # noqa: E402
import sys  # noqa: E402

FRESH = "BROKERED-JWT-FRESH-0001"
STALE = "BROKERED-JWT-EXPIRED-0000"


def token_script(tmp_path, body: str) -> str:
    script = tmp_path / "token.py"
    script.write_text(body)
    return f"{sys.executable} {script}"


def test_token_command_refreshes_and_its_value_is_never_printed(gitlab, run_setup, tmp_path):
    gitlab.credential = FRESH  # the server only knows the fresh one: the expired JWT gets a 401
    command = token_script(tmp_path, f"print({FRESH!r})\n")
    code, out = run_setup(env={"GITLAB_TOKEN": STALE}, token_command=command)
    assert code == 0, out
    assert FRESH not in out and STALE not in out
    assert gitlab.requests[0]["who"] is None and gitlab.requests[1]["who"] == "maintainer"  # 401, then the retry
    assert [r["who"] for r in gitlab.requests].count(None) == 1  # one refresh for the one expiry
    assert FRESH not in out  # not in a row, not in an error, not through a redaction marker either
    without = run_setup(env={"GITLAB_TOKEN": STALE})
    assert without[0] == 1 and "401" in without[1]  # no token command: the 401 is the answer, as before


def test_a_failing_token_command_reraises_the_401_without_its_output(gitlab, run_setup, tmp_path):
    gitlab.credential = FRESH
    command = token_script(
        tmp_path, "import sys\nprint('SECRET-FROM-THE-COMMAND')\nprint('more', file=sys.stderr)\nsys.exit(3)\n"
    )
    code, out = run_setup(env={"GITLAB_TOKEN": STALE}, token_command=command)
    assert code == 1 and "401" in out and "token command failed (exit 3)" in out
    assert "SECRET-FROM-THE-COMMAND" not in out and "more" not in out and STALE not in out
    empty = token_script(tmp_path, "pass\n")
    code, out = run_setup(env={"GITLAB_TOKEN": STALE}, token_command=empty)
    assert code == 1 and "token command failed (no output)" in out


def test_the_command_runs_without_a_shell_and_is_bounded(gitlab, run_setup, tmp_path):
    marker = tmp_path / "ran"
    command = token_script(
        tmp_path, f"import pathlib\npathlib.Path({str(marker)!r}).write_text('x')\nprint({FRESH!r})\n"
    )
    gitlab.credential = FRESH
    code, out = run_setup(env={"GITLAB_TOKEN": STALE}, token_command=command + " ; touch " + str(tmp_path / "injected"))
    assert not (tmp_path / "injected").exists()  # `;` is an argument of the script, never a second command
    assert code == 0 and marker.exists()
    from l4.setup.gitlab import token_command_refresh

    slow = token_script(tmp_path, "import time\ntime.sleep(5)\n")
    try:
        token_command_refresh(slow, timeout=0.2)()
    except Exception as exc:  # noqa: BLE001
        assert "token command failed (timed out)" in str(exc)
    else:
        raise AssertionError("a command that never ends must time out")


def test_the_option_is_on_setup_gitlab_and_ci_watch_with_its_environment_variable(capsys):
    from l4.cli import main

    for words in (["setup", "gitlab"], ["ci", "watch"]):
        with contextlib.suppress(SystemExit):
            main([*words, "--help"], environ={})
        out = capsys.readouterr().out
        assert "--token-command" in out and "L4_TOKEN_COMMAND" in out, words
