"""The failing step of a red project CI job, derived and vetted (M1.10 decisions 2 and 4; L4-ARC-002 (d))."""

from l4.ci.failing_step import CiStep, derive_step, echoed_step, shared_error_line, unrunnable
from l4.ci.gitlab_jobs import JobScript, ScriptRefusal

E501 = "uv run ruff check --select E501 --line-length 92 src"
TAIL = f"""Executing step_script
$ {E501}
E501 Line too long (108 > 92)
 --> src/pricing/notices.py:2:93
Found 1 error.
ERROR: Job failed: exit code 1"""


def script(*commands: str, before: tuple[str, ...] = ()) -> JobScript:
    return JobScript(before, tuple(commands))


def test_the_live_e501_step_is_derived():
    got = derive_step("test", E501, TAIL, script("uv sync", E501, before=("echo hi",)))
    assert got == CiStep("test", E501, None)
    assert derive_step("test", E501, TAIL, script(E501)).command == E501
    # a step cut at 300 characters, or one the file does not hold, is no match (see the next tests)


def test_log_and_file_disagree_refuses():
    """An agent-printed `$ rm -rf x` in its test output is no entry of the job's script."""
    got = derive_step("test", "rm -rf x", TAIL, script(E501))
    assert got.command is None and got.reason and "disagree" in got.reason
    assert derive_step("test", E501, TAIL, script("make test")).command is None  # the file changed or never had it
    assert derive_step("test", f"{E501} extra", TAIL, script(E501)).command is None  # an entry is matched whole


def test_ci_variables_docker_and_deploy_refuse():
    for command in (
        "pytest $CI_PROJECT_DIR/tests",
        "docker build .",
        "docker-compose up",
        "/usr/bin/kubectl apply -f x",
        "curl -s https://x.test",
        "git push origin main",
        "git -C repo fetch",
        "pip install x",
        "uv sync",
        "npm ci",
        "poetry publish",
        "make deploy-staging",
        "python scripts/release_notes.py",
        "twine upload dist/*",
        "echo `id`",
    ):
        assert unrunnable(command), command
        got = derive_step("test", command, "", script(command))
        assert got.command is None and got.reason, command
    assert unrunnable(E501) is None


def test_multi_line_and_collapsed_echo_refuse():
    multi = "pytest -q\npytest -q tests"
    collapsed = "pytest -q # collapsed multi-line command"
    got = derive_step("test", collapsed, "", script(multi))
    assert got.command is None and "multi-line" in (got.reason or "")
    assert derive_step("test", "pytest -q", "", script(multi)).command is None
    assert unrunnable("pytest -q\nrm x")


def test_shell_operators_refuse():
    for command in (
        "make a | tee log",
        "make a && make b",
        "make a; make b",
        "make a > out.txt",
        "cat < in.txt",
        "pytest tests/*.py",
        "pytest tests/?.py",
        "pytest tests/[ab].py",
        "(cd x && make)",
        "echo {a,b}",
        "ls ~/x",
        "echo a\\ b",
        'echo "a $HOME"',
        "echo 'unterminated",
        "FOO=1 make test",
        "make # comment",
    ):
        assert unrunnable(command), command
    # a metacharacter inside quotes is literal for the shell and for shlex alike
    assert unrunnable("pytest -m 'not ui and not (slow)'") is None
    assert unrunnable('pytest -k "a or b|c"') is None
    assert unrunnable("pytest -k 'x $y'") is None


def test_the_tail_fallback_takes_the_last_echo():
    tail = "$ make lint\nok\n$ make test\nFAILED\n"
    assert echoed_step(tail) == "make test"
    assert echoed_step("no echo here\n") is None
    got = derive_step("test", None, tail, script("make lint", "make test"))
    assert got == CiStep("test", "make test", None)
    none = derive_step("test", None, "FAILED\n", script("make test"))
    assert none.command is None and "no failing step" in (none.reason or "")


def test_a_refused_script_and_a_missing_job_skip_with_the_reason():
    got = derive_step("test", E501, TAIL, ScriptRefusal("job test uses !reference"))
    assert got == CiStep("test", None, "job test uses !reference")


def test_a_shared_error_line_reproduces_and_a_different_failure_does_not():
    local = "E501 Line too long (108 > 92)\n --> src/pricing/notices.py:2:93\nFound 1 error.\n"
    assert shared_error_line(TAIL, E501, local)
    different = "F401 `os` imported but unused\n --> src/other.py:1:8\nFound 1 error.\n"
    assert not shared_error_line(TAIL, E501, different)  # "Found 1 error." is generic, timing and rules too
    assert not shared_error_line(TAIL, E501, "")
    timing = "collected 3 items\n=== 1 failed in 0.04s ===\n"
    assert not shared_error_line("$ pytest\n=== 1 failed in 0.04s ===\n", "pytest", timing)
    # only lines after the step line count; with no step line in the tail, the whole tail
    assert not shared_error_line("Downloading package 1\n$ other\nboom here\n", "other", "Downloading package 1\n")
    assert shared_error_line("Downloading package 1\nboom happened", "other", "x\nDownloading  package 1\n")


def test_an_explicit_shell_refuses():
    """`sh -c '<anything>'` is a shell: the metacharacter scan and the denylist would see one quoted token (review of
    M1.10 line 4). The gate sandbox has the network on by default (`gates.network: allow`)."""
    for command in (
        'sh -c "docker push registry.example/x"',
        "bash -c 'curl -X POST https://hooks.example/x'",
        "bash -lc 'git push origin HEAD'",
        "bash -o pipefail -c 'make a | tee log'",
        'env sh -c "make a && make b"',
        "/bin/sh -c ls",
        "busybox sh -c ls",
        "zsh -ec 'rm -rf build'",
        "pwsh -Command Get-ChildItem",
        "fish --command ls",
    ):
        assert unrunnable(command), command
        got = derive_step("test", command, "", script(command))
        assert got.command is None and "shell" in (got.reason or ""), command
    # a script file run by a shell is like `python scripts/x.py`; a word inside a quoted argument is no command
    assert unrunnable("bash scripts/ci_check.sh") is None
    assert unrunnable("sh -e scripts/ci_check.sh") is None
    assert unrunnable('pytest -k "not docker"') is None
