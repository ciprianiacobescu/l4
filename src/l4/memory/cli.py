"""`l4 lessons list|lint|promote` (SPEC L4-MEM-001, L4-KG-013). `list` and `lint` read only. `promote ID` is the one
way a person moves an inbox proposal into `lessons.md` (experience-graph D11, `l4.memory.promote`); this module is the
only importer of `promote` and `inbox` (L4-KG-001), and `list` and `lint` keep their output (L4-KG-014).
M1: `lint --fix-format`.
"""

from pathlib import Path

import click

from l4.config.redaction import load_app_config
from l4.context import AppContext
from l4.exitcodes import ExitCode, L4Exit
from l4.memory.inject import read_lessons_file
from l4.memory.lessons import LessonsFile, Problem, lint, parse_lessons
from l4.memory.promote import promote

USAGE = "usage: l4 lessons list | l4 lessons lint | l4 lessons promote ID [--from DIR] [--yes] [--no-commit]"


def _load(app: AppContext, relative: str) -> tuple[LessonsFile, list[Problem]]:
    text, problem = read_lessons_file(app.repo, relative)
    parsed = parse_lessons(text)
    return parsed.file, [*([problem] if problem else []), *parsed.problems]


def _show(app: AppContext, problem: Problem) -> str:
    where = f"line {problem.line}" if problem.line else "file"
    who = f" {problem.lesson_id}" if problem.lesson_id else ""
    return app.redactor.redact_text(f"{where}{who}: {problem.message}")


def run_lessons(
    app: AppContext, *, words: tuple[str, ...] = (), from_dir: Path | str | None = None, yes: bool = False,
    no_commit: bool = False,
) -> ExitCode:  # fmt: skip
    one = len(words) == 1 and words[0] in ("list", "lint")
    if not one and not (len(words) == 2 and words[0] == "promote"):
        raise L4Exit(ExitCode.USAGE_ERROR, USAGE)
    app, cfg = load_app_config(app)
    if words[0] == "promote":
        promote(app, cfg, words[1], from_dir=from_dir, yes=yes, commit=not no_commit)
        return ExitCode.OK
    file, problems = _load(app, cfg.memory.lessons_file)
    if words[0] == "list":
        for lesson in sorted(file.lessons, key=lambda lesson: lesson.id):
            scope = ", ".join(lesson.scope_globs) or "all"
            click.echo(app.redactor.redact_text(f"{lesson.id}  {lesson.title}  [{scope}]  x{lesson.reinforced_count}"))
        for problem in problems:
            click.echo(f"warning: {_show(app, problem)}", err=True)
        return ExitCode.OK
    problems += lint(file, max_lessons=cfg.memory.max_lessons, max_bytes=cfg.memory.max_bytes)
    for problem in problems:
        click.echo(_show(app, problem))
    return ExitCode.DOCTOR_FAILED if problems else ExitCode.OK
