import json
from pathlib import Path

import pytest

from l4.cli import main
from l4.exitcodes import ExitCode, L4Exit
from l4.outcome import CommandResult, UnitOutcome

TOKEN = "ghp_" + "a1B2c3D4e5" * 3
FORGE_TOKEN = "forge-secret-value-1234"
ENV = {"L4_FORGE_TOKEN": FORGE_TOKEN}


def outcome_file(repo: Path) -> dict:
    return json.loads((repo / ".l4-out" / "outcome.json").read_text(encoding="utf-8"))


def test_unexpected_exception_exits_1_with_outcome_and_redaction(install_handler, repo, capsys):
    def boom(app, **kw):
        raise RuntimeError(f"boom {FORGE_TOKEN} and {TOKEN}")

    install_handler("verify", boom)
    code = main(["verify", "--unit", "openspec:x", "--repo", str(repo), "-v"], environ=ENV)
    assert code == 1
    captured = capsys.readouterr()
    for stream in (captured.out, captured.err, (repo / ".l4-out" / "outcome.json").read_text(encoding="utf-8")):
        assert FORGE_TOKEN not in stream and TOKEN not in stream
    assert "RuntimeError" in captured.err and "REDACTED" in captured.err
    data = outcome_file(repo)
    assert data["exit_code"] == 1 and data["schema"] == "l4/outcome@1"


def test_traceback_is_shown_only_with_verbose_and_is_redacted(install_handler, repo, capsys):
    install_handler("plan", lambda app, **kw: (_ for _ in ()).throw(RuntimeError(FORGE_TOKEN)))
    main(["plan", "--repo", str(repo)], environ=ENV)
    quiet = capsys.readouterr().err
    assert "Traceback" not in quiet
    main(["plan", "--repo", str(repo), "-v"], environ=ENV)
    verbose = capsys.readouterr().err
    assert "Traceback" in verbose and FORGE_TOKEN not in verbose


@pytest.mark.parametrize("command", ["run", "verify", "archive", "plan"])
def test_outcome_is_written_for_the_four_outcome_commands(command, install_handler, repo):
    install_handler(command, lambda app, **kw: ExitCode.OK)
    argv = [command, "--repo", str(repo)] + (["--unit", "openspec:x"] if command in ("verify", "archive") else [])
    assert main(argv, environ={}) == 0
    data = outcome_file(repo)
    assert data["exit_code"] == 0 and data["units"] == []


def test_outcome_run_id_matches_the_app_context_run_id(install_handler, repo):
    calls = install_handler("plan", lambda app, **kw: ExitCode.OK)
    main(["plan", "--repo", str(repo)], environ={})
    assert outcome_file(repo)["run_id"] == calls[0]["app"].run_id


@pytest.mark.parametrize("command", ["doctor", "status", "init"])
def test_other_commands_write_no_outcome_and_still_map_exceptions(command, install_handler, repo, capsys):
    install_handler(command, lambda app, **kw: (_ for _ in ()).throw(RuntimeError("x")))
    assert main([command, "--repo", str(repo)], environ={}) == 1
    assert not (repo / ".l4-out" / "outcome.json").exists()  # (the JSONL log may have created `.l4-out/logs`)
    assert "internal error" in capsys.readouterr().err


def test_l4exit_carries_its_code_and_message(install_handler, repo, capsys):
    install_handler("run", lambda app, **kw: (_ for _ in ()).throw(L4Exit(ExitCode.HALTED, "budget gone")))
    assert main(["run", "--repo", str(repo)], environ={}) == 13
    assert "budget gone" in capsys.readouterr().err
    assert outcome_file(repo)["exit_code"] == 13


def test_command_result_units_reach_the_outcome(install_handler, repo):
    units = (UnitOutcome(unit="openspec:a", phase_before="ready", phase_after="awaiting_human"),)
    install_handler("run", lambda app, **kw: CommandResult(ExitCode.AWAITING_HUMAN, units))
    assert main(["run", "--repo", str(repo)], environ={}) == 11
    data = outcome_file(repo)
    assert data["exit_code"] == 11 and data["units"][0]["unit"] == "openspec:a"


def test_handler_options_reach_the_handler(install_handler, repo):
    calls = install_handler("plan", lambda app, **kw: ExitCode.OK)
    main(["plan", "--unit", "a", "--unit", "b", "--json", "--detailed-exitcode", "--repo", str(repo)], environ={})
    assert calls[0]["kwargs"] == {
        "units": ("a", "b"), "as_json": True, "probe": False, "sweep": False, "detailed_exitcode": True,
    }  # fmt: skip


def test_quiet_and_verbose_set_verbosity(install_handler, repo):
    calls = install_handler("status", lambda app, **kw: ExitCode.OK)
    main(["status", "--repo", str(repo), "-q"], environ={})
    main(["status", "--repo", str(repo), "-vv"], environ={})
    assert [c["app"].verbosity for c in calls] == [-1, 2]


def test_console_log_format_json(install_handler, repo, capsys):
    install_handler("status", lambda app, **kw: (_ for _ in ()).throw(L4Exit(ExitCode.REJECTED, "nope")))
    assert main(["status", "--repo", str(repo), "--log-format", "json"], environ={}) == 14
    line = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert line["msg"] == "nope" and line["level"] == "ERROR"
