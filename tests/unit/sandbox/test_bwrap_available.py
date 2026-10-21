from pathlib import Path

from l4.doctor.context import CmdResult
from l4.sandbox.bwrap import BwrapSandbox


class Recorder:
    def __init__(self, result: CmdResult) -> None:
        self.result, self.calls = result, []

    def __call__(self, argv, cwd, env, timeout):
        self.calls.append((list(argv), cwd, dict(env), timeout))
        return self.result


def test_available_runs_a_real_noop_inside_bwrap():
    run = Recorder(CmdResult(0, "", ""))
    assert BwrapSandbox("/usr/bin/bwrap", run).available().ok
    argv = run.calls[0][0]
    assert argv[0] == "/usr/bin/bwrap" and argv[-2:] == ["--", "true"]
    assert "--unshare-pid" in argv and "--proc" in argv


def test_available_false_when_userns_blocked():
    stderr = "bwrap: No permissions to create new namespace, the kernel does not allow non-privileged user namespaces\n"
    result = BwrapSandbox("/usr/bin/bwrap", Recorder(CmdResult(1, "", stderr))).available()
    assert not result.ok and "non-privileged user namespaces" in result.reason


def test_available_false_on_timeout_or_missing_binary():
    assert not BwrapSandbox("/nope/bwrap", Recorder(CmdResult(127, "", "FileNotFoundError"))).available().ok
    timed_out = BwrapSandbox("/usr/bin/bwrap", Recorder(CmdResult(124, "", "timed out"))).available()
    assert not timed_out.ok and "timed out" in timed_out.reason


def test_available_with_the_real_runner_and_a_missing_binary(tmp_path: Path):
    assert not BwrapSandbox(str(tmp_path / "no-such-bwrap")).available().ok
