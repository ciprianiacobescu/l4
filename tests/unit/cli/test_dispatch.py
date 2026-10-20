import importlib.util
import sys
import types
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from l4 import commands
from l4.cli import cli, main
from l4.exitcodes import ExitCode

SECTION_2_1 = {
    "init", "doctor", "plan", "run", "status", "probe", "verify", "archive", "questions", "lessons",
    "simulate", "unlock", "resume", "retry", "restart", "ci render", "ci render-child", "ci map-exit", "upgrade",
    "setup gitlab", "setup github", "ci watch", "eval", "ci cache-key", "ci render-setup",
    "feedback add", "feedback list", "feedback show", "feedback submit", "feedback withdraw",
    "kg build", "kg report", "kg why", "kg propose",
}  # fmt: skip

EXTRA = {"s1", "mcp serve", "mcp install"}  # M1.6: not a SPEC 2.1 command; the harness's S1 data-set tool
EXTRA |= {"skills install", "skills status"}  # skills-install: L4-SKL-003
YOLO_WORDS = ("draft", "check", "review", "findings", "accept", "waive", "activate", "status", "cancel", "resume")
YOLO = {f"yolo {w}" for w in (*YOLO_WORDS, "report")}  # yolo-mode D6; waive: L4-YOLO-031
EXTRA |= YOLO

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
    "retry": ["retry", "--unit", "openspec:a", "--reason", "why"],
    "restart": ["restart", "--unit", "openspec:a", "--reason", "why"],
    "ci render": ["ci", "render", "--platform", "github"],
    "ci render-child": ["ci", "render-child", "--plan", "plan.json"],
    "ci map-exit": ["ci", "map-exit", "11"],
    "ci cache-key": ["ci", "cache-key", "clis"],
    "ci render-setup": ["ci", "render-setup"],
    "upgrade": ["upgrade"],
    "setup gitlab": ["setup", "gitlab", "--project", "g/p"],
    "setup github": ["setup", "github", "--repo", "o/r"],
    "ci watch": ["ci", "watch", "--project", "g/p"],
    "feedback add": ["feedback", "add", "--kind", "tests", "--text", "more tests"],
    "feedback list": ["feedback", "list"],
    "feedback show": ["feedback", "show", "FB-001"],
    "feedback submit": ["feedback", "submit", "FB-001"],
    "feedback withdraw": ["feedback", "withdraw", "FB-001"],
    "yolo draft": ["yolo", "draft", "p1"],
    "yolo check": ["yolo", "check", "p1"],
    "yolo review": ["yolo", "review", "p1"],
    "yolo findings": ["yolo", "findings", "p1"],
    "yolo accept": ["yolo", "accept", "p1", "openspec:a", "--reason", "go"],
    "yolo waive": ["yolo", "waive", "p1", "F-0a1b2c", "--reason", "go"],
    "yolo activate": ["yolo", "activate", "p1", "--reason", "go"],
    "yolo status": ["yolo", "status"],
    "yolo cancel": ["yolo", "cancel", "p1", "--reason", "why"],
    "yolo resume": ["yolo", "resume", "p1", "--reason", "why"],
    "yolo report": ["yolo", "report", "p1"],
    "kg build": ["kg", "build"],
    "kg report": ["kg", "report"],
    "kg why": ["kg", "why", "openspec:a"],
    "kg propose": ["kg", "propose"],
    "skills install": ["skills", "install", "--dry-run", "--agent", "kiro"],
    "skills status": ["skills", "status"],
    "s1": ["s1", "export"],
    "mcp serve": ["mcp", "serve"],
    "mcp install": ["mcp", "install", "--client", "cursor"],
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
    assert {"unlock", "ci render", "ci render-child"} == commands.STUBS
    for name in sorted(commands.STUBS):
        argv = [*ARGV[name], "--repo", str(repo)]
        assert main(argv, environ={}) == 2, name
        assert f"{name}: not yet implemented (M1: " in capsys.readouterr().err


def test_questions_is_a_real_command_now(monkeypatch):
    assert commands.HANDLERS["questions"] == "l4.specs.questions_cli:run_questions"
    assert commands.OWNING_CHANGE["questions"] == "unfreeze-and-answer"
    assert "questions" not in commands.STUBS


def test_a_handler_module_that_does_not_exist_is_listed_as_a_stub():
    missing = {
        name for name, target in commands.HANDLERS.items() if importlib.util.find_spec(target.partition(":")[0]) is None
    }
    assert missing <= commands.STUBS, sorted(missing - commands.STUBS)


def help_of(*words: str) -> str:
    result = CliRunner().invoke(cli, [*words, "--help"])
    assert result.exit_code == 0, result.output
    return " ".join(result.output.split())


def test_every_stub_command_says_so_in_its_help():
    for name in sorted(commands.STUBS):
        text = help_of(*name.split())
        assert "(not yet implemented)" in text, name
    group_listing = help_of("ci")
    assert group_listing.count("(not yet implemented)") >= 2  # render and render-child, in the group's listing
    for name in sorted(set(commands.HANDLERS) - commands.STUBS):
        assert "(not yet implemented)" not in help_of(*name.split()).split("Options:")[0], name


# option -> a value for it ("" for a flag); each is refused at once with "not yet implemented"
OPTION_STUBS = {
    "status": {"--rebuild": ""},
    "resume": {"--extend-iterations": "2", "--extend-cost": "2"},
    "run": {"--time-budget": "5m"},
    "verify": {"--dry-run": ""},
    "init": {"--dry-run": "", "--framework": "kiro"},
}


def option_help(command: str, option: str) -> str:
    node = cli
    for word in command.split():
        node = node.commands[word]  # type: ignore[attr-defined]
    return next(p.help or "" for p in node.params if option in p.opts)  # type: ignore[attr-defined]


def test_every_stub_option_says_so_in_its_help_and_is_refused(capsys, repo):
    for name, options in OPTION_STUBS.items():
        for option, value in options.items():
            assert "not yet implemented" in option_help(name, option), (name, option)
            argv = [*ARGV[name], option, *([value] if value else []), "--repo", str(repo)]
            if name == "init":
                argv += ["--ci", "github", "--vendor"]
            assert main(argv, environ={}) == 2, (name, option)
            assert "not yet implemented" in capsys.readouterr().err, (name, option)
    assert "kiro is not yet implemented" in option_help("init", "--framework")


def test_an_option_that_works_is_not_marked(repo):
    assert "not yet implemented" not in option_help("init", "--vendor")
    assert "not yet implemented" not in option_help("resume", "--extend-fix-rounds")


def test_l4_help_describes_questions_as_the_operator_command():
    text = help_of()
    assert "List and show open questions; accept or answer one on the unit branch (commits and pushes)" in text


def test_questions_help_lists_the_four_forms_and_the_options():
    text = help_of("questions")
    for form in (
        "l4 questions [list]",
        "l4 questions show Q-NNN",
        "l4 questions accept Q-NNN",
        "l4 questions answer Q-NNN",
    ):
        assert form in text, form
    for option in ("--unit", "--text", "--json", "--no-push"):
        assert option in text, option
    assert "clarifier.answer_by_agents" in text


def test_questions_passes_its_options_to_the_handler(install_handler, repo):
    calls = install_handler("questions", lambda app, **kw: ExitCode.OK)
    argv = ["questions", "answer", "Q-002", "--unit", "openspec:a", "--text", "yes", "--json", "--no-push", "--no-run"]
    assert main([*argv, "--repo", str(repo)], environ={}) == 0
    assert calls[0]["kwargs"] == {
        "words": ("answer", "Q-002"), "unit": "openspec:a", "text": "yes", "as_json": True, "no_push": True,
        "no_run": True, "replace": False,
    }  # fmt: skip
    again = install_handler("questions", lambda app, **kw: ExitCode.OK)
    argv = ["questions", "answer", "Q-002", "--unit", "openspec:a", "--text", "accept it", "--replace"]
    assert main([*argv, "--repo", str(repo)], environ={}) == 0
    assert again[0]["kwargs"]["replace"] is True


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


@pytest.mark.parametrize("command", ["retry", "resume"])
def test_reason_help_says_the_implementer_of_the_halted_task_reads_it(command):
    """D13."""
    help_text = " ".join(option_help(command, "--reason").split())
    assert help_text == (
        "Why the unit can continue. For a unit halted on a task, the implementer of that task also reads it "
        "(at most 300 characters)."
    )


def test_yolo_accept_takes_all_and_force_without_a_subject(monkeypatch, repo):
    calls: list[dict[str, Any]] = []

    def record(app, **kwargs):
        calls.append(kwargs)
        return ExitCode.OK

    monkeypatch.setattr("l4.yolo.commands.run_accept", record)
    argv = ["yolo", "accept", "p1", "--all", "--force", "--reason", "go", "--repo", str(repo)]
    assert main(argv, environ={}) == 0
    assert calls[0] == {
        "plan": "p1", "subject": None, "reason": "go", "withdraw": False, "yes": False, "all_subjects": True,
        "force": True,
    }  # fmt: skip
