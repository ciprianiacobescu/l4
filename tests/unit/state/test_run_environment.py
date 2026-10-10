"""HB-10: `run.started` says which runner and which tool versions the run had (L4-STA-001)."""

import subprocess

from l4.state.environment import run_environment


def fake_run(table: dict[str, str]):
    def run(argv, **kw):
        out = table.get(argv[0])
        if out is None:
            raise FileNotFoundError(argv[0])
        return subprocess.CompletedProcess(argv, 0, stdout=out, stderr="")

    return run


def test_the_runner_and_the_tool_versions_are_recorded():
    env = {"CI_RUNNER_ID": "12", "CI_RUNNER_DESCRIPTION": "runner-2", "PATH": "/x"}
    facts = run_environment(
        env,
        which=lambda name, path=None: f"/bin/{name}",
        run=fake_run({"/bin/git": "git version 2.43.0\n", "/bin/bwrap": "bubblewrap 0.9.0\n"}),
    )
    assert facts["runner"] == {"id": "12", "description": "runner-2"}
    assert facts["tools"]["git"] == "2.43.0" and facts["tools"]["bwrap"] == "0.9.0"
    assert facts["tools"]["python"].count(".") == 2


def test_a_tool_that_is_missing_or_prints_no_version_is_left_out_not_an_error():
    facts = run_environment({"PATH": "/x"}, which=lambda name, path=None: None, run=fake_run({}))
    assert "runner" not in facts
    assert set(facts["tools"]) == {"python"}


def test_a_failing_version_command_never_stops_the_run():
    def boom(argv, **kw):
        raise subprocess.TimeoutExpired(argv, 5)

    facts = run_environment({}, which=lambda name, path=None: "/bin/" + name, run=boom)
    assert set(facts["tools"]) == {"python"}
