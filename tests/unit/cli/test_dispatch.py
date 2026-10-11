import sys
import types
from pathlib import Path

import pytest

from l4 import commands
from l4.cli import main
from l4.exitcodes import ExitCode

SECTION_2_1 = {
    "init", "doctor", "plan", "run", "status", "probe", "verify", "archive", "questions", "lessons",
    "simulate", "unlock", "resume", "ci render", "ci render-child", "ci map-exit", "upgrade",
    "setup gitlab", "setup github", "ci watch", "eval",
}  # fmt: skip

EXTRA = {"s1"}  # M1.6: not a SPEC 2.1 command; the harness's S1 data-set tool

# minimal valid argv per command, including options that are required
ARGV = {
    "init": ["init"],
    "doctor": ["doctor"],
    "plan": ["plan"],
    "run": ["run"],
    "status": ["status"],
    "probe": ["probe"],
    "verify": ["verify", "--unit", "openspec:a"],
    "archive": ["archive", "--unit", "openspec:a"],
    "questions": ["questions", "list", "--unit", "openspec:a"],
    "lessons": ["lessons", "list"],
    "simulate": ["simulate", "--all"],
    "unlock": ["unlock", "--unit", "openspec:a"],
    "resume": ["resume", "--unit", "openspec:a", "--reason", "why"],
    "ci render": ["ci", "render", "--platform", "github"],
    "ci render-child": ["ci", "render-child", "--plan", "plan.json"],
    "ci map-exit": ["ci", "map-exit", "11"],
    "upgrade": ["upgrade"],
    "setup gitlab": ["setup", "gitlab", "--project", "g/p"],
    "setup github": ["setup", "github", "--repo", "o/r"],
    "ci watch": ["ci", "watch", "--project", "g/p"],
    "s1": ["s1", "export"],
    "eval": ["eval", "--dry-run", "--judge", "j"],
}


def test_handlers_cover_every_section_2_1_command():
    assert set(commands.HANDLERS) == SECTION_2_1 | EXTRA
    assert set(commands.OWNING_CHANGE) == SECTION_2_1 | EXTRA
    assert set(ARGV) == SECTION_2_1 | EXTRA


def test_absent_handler_module_exits_2_not_yet_implemented(monkeypatch, capsys, repo):
    monkeypatch.setitem(commands.HANDLERS, "lessons", "l4_no_such_pkg.sub.cli:run_lessons")
    assert main(["lessons", "list", "--repo", str(repo)], environ={}) == 2
    err = capsys.readouterr().err
    assert "lessons: not yet implemented (M1: memory-lessons)" in err
    assert "Traceback" not in err


def test_every_command_without_a_module_is_a_stub_not_a_crash(capsys, repo):
    # the stubs of this part: modules that later parts deliver do not exist yet
    for name in ("unlock", "questions", "ci render"):
        argv = [*ARGV[name], "--repo", str(repo)]
        assert main(argv, environ={}) == 2, name
        assert f"{name}: not yet implemented (M1: " in capsys.readouterr().err


@pytest.mark.parametrize("name", sorted(SECTION_2_1))
def test_all_commands_accept_global_options(name, install_handler, repo, tmp_path: Path):
    calls = install_handler(name, lambda app, **kw: ExitCode.OK)
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text("version: 1\n", encoding="utf-8")
    argv = [*ARGV[name], "--config", str(cfg), "--repo", str(repo), "--log-format", "json", "-v"]
    assert main(argv, environ={}) == 0
    app = calls[0]["app"]
    assert app.repo == repo.resolve()
    assert app.config_path == cfg
    assert app.log_format == "json"
    assert app.verbosity == 1


def test_other_import_errors_are_not_masked(monkeypatch, capsys, repo, tmp_path: Path):
    # the handler module exists but fails to import one of ITS dependencies: a real bug, exit 1
    (tmp_path / "l4_test_broken_handler.py").write_text("import l4_dependency_that_is_absent\n", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setitem(commands.HANDLERS, "lessons", "l4_test_broken_handler:run_lessons")
    assert main(["lessons", "--repo", str(repo)], environ={}) == 1
    err = capsys.readouterr().err
    assert "not yet implemented" not in err
    assert "l4_dependency_that_is_absent" in err


def test_missing_function_in_existing_module_is_an_internal_error(monkeypatch, capsys, repo):
    module = types.ModuleType("l4_test_nofunc")
    monkeypatch.setitem(sys.modules, "l4_test_nofunc", module)
    monkeypatch.setitem(commands.HANDLERS, "lessons", "l4_test_nofunc:run_lessons")
    assert main(["lessons", "--repo", str(repo)], environ={}) == 1
    assert "not yet implemented" not in capsys.readouterr().err


def test_unknown_command_and_bad_option_are_usage_errors(capsys, repo):
    assert main(["frobnicate"], environ={}) == 2
    assert main(["doctor", "--nope", "--repo", str(repo)], environ={}) == 2
    assert "Traceback" not in capsys.readouterr().err


def test_repo_must_exist(capsys, tmp_path: Path):
    assert main(["doctor", "--repo", str(tmp_path / "missing")], environ={}) == 2
