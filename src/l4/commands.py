"""Command dispatch table (SPEC 2.1). A change delivers a command by creating its handler module."""

import importlib
from types import ModuleType

import click

from l4.context import AppContext
from l4.exitcodes import ExitCode
from l4.outcome import CommandResult

# command name -> "module:function". Handlers take `(app, **options)` and return an ExitCode or a CommandResult.
HANDLERS: dict[str, str] = {
    "init": "l4.init.init:run_init",
    "upgrade": "l4.init.upgrade:run_upgrade",
    "doctor": "l4.doctor.run:run_doctor",
    "plan": "l4.planner:run_plan",
    "run": "l4.orchestrator:run_command",
    "status": "l4.state.status:run_status",
    "probe": "l4.availability.fallback:run_probe",
    "verify": "l4.verifier.ladder:run_verify",
    "archive": "l4.archive:run_archive",
    "questions": "l4.specs.questions:run_questions",
    "feedback add": "l4.specs.feedback_cli:run_feedback_add",
    "feedback list": "l4.specs.feedback_cli:run_feedback_list",
    "feedback show": "l4.specs.feedback_cli:run_feedback_show",
    "feedback submit": "l4.specs.feedback_cli:run_feedback_submit",
    "feedback withdraw": "l4.specs.feedback_cli:run_feedback_withdraw",
    "lessons": "l4.memory.cli:run_lessons",
    "s1": "l4.s1.cli:run_s1_cli",
    "simulate": "l4.sim.runner:run_simulate",
    "unlock": "l4.vcs.locks:run_unlock",
    "resume": "l4.state.resume:run_resume",
    "retry": "l4.state.retry:run_retry",
    "restart": "l4.state.restart:run_restart",
    "setup gitlab": "l4.setup.gitlab:run_setup_gitlab",
    "setup github": "l4.setup.github:run_setup_github",
    "ci render": "l4.ci.commands:run_render",
    "ci watch": "l4.ci.watch:run_ci_watch",
    "ci render-child": "l4.ci.commands:run_render_child",
    "ci cache-key": "l4.ci.action_commands:run_cache_key",
    "ci render-setup": "l4.ci.action_commands:run_render_setup",
    "ci map-exit": "l4.exitcodes:run_map_exit",
    "eval": "l4.eval.run:run_eval",
}

# the change that owns each handler, for the "not yet implemented (M1: <change>)" message
OWNING_CHANGE: dict[str, str] = {
    "init": "forge-and-ci",
    "upgrade": "forge-and-ci",
    "doctor": "bootstrap-core",
    "plan": "simulation-harness",
    "run": "implementer-tdd-loop",
    "status": "state-vcs-locks",
    "probe": "agent-factory",
    "verify": "verifier",
    "archive": "forge-and-ci",
    "questions": "spec-providers",
    "feedback add": "human-feedback",
    "feedback list": "human-feedback",
    "feedback show": "human-feedback",
    "feedback submit": "human-feedback",
    "feedback withdraw": "human-feedback",
    "lessons": "memory-lessons",
    "s1": "m16-s1",
    "simulate": "simulation-harness",
    "unlock": "state-vcs-locks",
    "resume": "state-vcs-locks",
    "retry": "operator-commands",
    "restart": "operator-commands",
    "setup gitlab": "forge-and-ci",
    "setup github": "github-parity",
    "ci render": "forge-and-ci",
    "ci watch": "forge-and-ci",
    "ci render-child": "forge-and-ci",
    "ci cache-key": "adoption-kit",
    "ci render-setup": "adoption-kit",
    "ci map-exit": "bootstrap-core",
    "eval": "m114-eval",
}


def import_optional(module_name: str) -> ModuleType | None:
    """The module, or None when it (or a parent package) does not exist yet. Only that is "absent"; a missing
    dependency inside an existing module is a bug and must surface. Handlers and hooks share this rule."""
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        if exc.name and (module_name == exc.name or module_name.startswith(exc.name + ".")):
            return None
        raise


def dispatch(name: str, app: AppContext, **options: object) -> CommandResult:
    module_name, _, function_name = HANDLERS[name].partition(":")
    module = import_optional(module_name)
    if module is None:
        click.echo(f"{name}: not yet implemented (M1: {OWNING_CHANGE[name]})", err=True)
        return CommandResult(ExitCode.USAGE_ERROR)
    result = getattr(module, function_name)(app, **options)
    return result if isinstance(result, CommandResult) else CommandResult(ExitCode(result))
