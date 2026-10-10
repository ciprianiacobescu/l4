import sys
from pathlib import Path

import pytest

from l4.config.defaults import openspec_entrypoint, openspec_env
from l4.exitcodes import ExitCode, L4Exit
from l4.proc import run_process
from l4.specs.base import OpenSpecCommandError, OpenSpecUnavailable
from l4.specs.openspec import OpenSpecCli


def test_missing_install_fails_closed_without_path_or_npx_fallback(tmp_path: Path, fake_install: dict[str, str]):
    runs: list = []
    repo = tmp_path / "repo"
    repo.mkdir()
    # a bare `openspec` and `npx` on PATH must never be consulted
    for name in ("openspec", "npx"):
        shim = Path(fake_install["PATH"]) / name
        shim.write_text("#!/bin/sh\n")
        shim.chmod(0o755)
    openspec_entrypoint(fake_install).unlink()
    cli = OpenSpecCli(repo, fake_install, runner=lambda *a: runs.append(a))
    with pytest.raises(OpenSpecUnavailable, match="openspec.js") as err:
        cli.run_json("validate", "x", "--strict", "--json")
    assert err.value.code is ExitCode.DOCTOR_FAILED and runs == []

    node_less = {**fake_install, "PATH": str(tmp_path / "empty")}
    with pytest.raises(OpenSpecUnavailable, match="node"):
        OpenSpecCli(repo, node_less, runner=lambda *a: runs.append(a)).run_json("list", "--json")
    assert runs == []


def test_an_install_inside_the_repository_is_refused(tmp_path: Path, fake_install: dict[str, str]):
    repo = tmp_path / "repo"
    (repo / "home").mkdir(parents=True)
    env = {**fake_install, "L4_HOME": str(repo / "home")}
    entry = openspec_entrypoint(env)
    entry.parent.mkdir(parents=True)
    entry.write_text("// planted\n")
    with pytest.raises(OpenSpecUnavailable, match="inside the repository"):
        OpenSpecCli(repo, env, runner=lambda *a: None).run_json("list", "--json")


def test_command_line_is_node_plus_entrypoint_with_a_fixed_environment(tmp_path: Path, fake_install, replay):
    repo = tmp_path / "repo"
    repo.mkdir()
    runner = replay("validate-add-farewell-strict")
    result = OpenSpecCli(repo, fake_install, runner=runner).run_json("validate", "add-farewell", "--strict", "--json")
    argv, cwd, env, timeout = runner.calls[0]
    assert argv[0] == str(Path(fake_install["PATH"]) / "node")  # the absolute node doctor ENV-003 checks
    assert argv[1] == str(openspec_entrypoint(fake_install)) and argv[2:] == [
        "validate",
        "add-farewell",
        "--strict",
        "--json",
    ]
    assert ".bin" not in " ".join(argv) and "npx" not in " ".join(argv)
    assert cwd == repo.resolve() and timeout <= 60
    assert env == openspec_env(fake_install)
    assert set(env) == {
        "PATH", "HOME", "TZ", "DO_NOT_TRACK", "OPENSPEC_TELEMETRY", "OPENSPEC_NO_UPDATE_CHECK", "NO_COLOR",
        "XDG_CONFIG_HOME", "XDG_DATA_HOME",
    }  # fmt: skip
    assert env["TZ"] == "UTC" and env["XDG_CONFIG_HOME"].startswith(fake_install["L4_CACHE"])
    assert result.data["items"][0]["id"] == "add-farewell" and result.returncode == 0


def test_non_json_output_is_a_provider_error_naming_the_argv(tmp_path: Path, fake_install, replay):
    repo = tmp_path / "repo"
    repo.mkdir()
    cli = OpenSpecCli(repo, fake_install, runner=replay("validate-noarg"))
    with pytest.raises(OpenSpecCommandError, match=r"validate --strict --json.*not JSON"):
        cli.run_json("validate", "--strict", "--json")


def test_run_process_closes_stdin_uses_the_given_cwd_and_reports_timeouts(tmp_path: Path):
    code = "import os, sys; print(repr(sys.stdin.read()), os.getcwd())"
    done = run_process([sys.executable, "-c", code], tmp_path, {"PATH": ""}, 30.0)
    assert done.returncode == 0 and done.stdout.split(maxsplit=1)[0] == "''"
    assert str(tmp_path.resolve()) in done.stdout
    slow = run_process([sys.executable, "-c", "import time; time.sleep(30)"], tmp_path, {}, 0.2)
    assert slow.returncode == 124 and slow.stderr == "timed out"
    assert run_process([str(tmp_path / "nope")], tmp_path, {}, 1.0).returncode == 127


def test_a_cache_inside_the_repository_is_refused_before_anything_runs(tmp_path: Path, fake_install):
    """The XDG directories of the OpenSpec call live in $L4_CACHE; repo content must not control them."""
    repo = tmp_path / "repo"
    repo.mkdir()
    runs: list = []
    env = {**fake_install, "L4_CACHE": str(repo / ".l4-cache")}
    with pytest.raises(L4Exit) as err:
        OpenSpecCli(repo, env, runner=lambda *a: runs.append(a)).run_json("list", "--json")
    assert err.value.code is ExitCode.USAGE_ERROR and "outside the repository" in str(err.value) and runs == []
