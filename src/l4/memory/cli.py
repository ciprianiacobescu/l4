"""`l4 lessons list|lint` (SPEC L4-MEM-001). Reads only; the harness is the only writer of `lessons.md`.
M1: memory-lessons 3.8 `promote`, and `lint --fix-format`.
"""

import click

from l4.config.redaction import load_app_config
from l4.context import AppContext
from l4.exitcodes import ExitCode, L4Exit
from l4.memory.inject import read_lessons_file
from l4.memory.lessons import LessonsFile, Problem, lint, parse_lessons

USAGE = "usage: l4 lessons list | l4 lessons lint"


def _load(app: AppContext, relative: str) -> tuple[LessonsFile, list[Problem]]:
    text, problem = read_lessons_file(app.repo, relative)
    parsed = parse_lessons(text)
    return parsed.file, [*([problem] if problem else []), *parsed.problems]


def _show(app: AppContext, problem: Problem) -> str:
    where = f"line {problem.line}" if problem.line else "file"
    who = f" {problem.lesson_id}" if problem.lesson_id else ""
    return app.redactor.redact_text(f"{where}{who}: {problem.message}")


def run_lessons(app: AppContext, *, words: tuple[str, ...] = ()) -> ExitCode:
    if len(words) != 1 or words[0] not in ("list", "lint"):
        raise L4Exit(ExitCode.USAGE_ERROR, USAGE)
    app, cfg = load_app_config(app)
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
