"""`l4 doctor`."""

import dataclasses

import click

import l4.doctor.checks_ci  # noqa: F401  (registers CI-001)
import l4.doctor.checks_config  # noqa: F401  (registers CFG-002)
import l4.doctor.checks_env  # noqa: F401  (registers ENV-001..003)
import l4.doctor.checks_skills  # noqa: F401  (registers SKL-003)
import l4.doctor.checks_tools  # noqa: F401  (registers TOOL-001)
from l4.ci.relay import early_pin_stop
from l4.config.defaults import cache_root, l4_home
from l4.config.redaction import load_app_config
from l4.context import AppContext
from l4.doctor.context import system_context
from l4.doctor.fix import apply_fixes
from l4.doctor.registry import REGISTRY, doctor_scopes, exit_code, load_check_modules, run_checks
from l4.doctor.report import render_fixes, render_json, render_table
from l4.exitcodes import ExitCode, L4Exit
from l4.specs.base import parse_unit_id
from l4.specs.providers import providers_for


def run_doctor(
    app: AppContext,
    *,
    ci: bool,
    live: bool,
    fix: bool,
    unit: str | None,
    as_json: bool,
    adoption: bool = False,
    no_gates: bool = False,
) -> ExitCode:
    """`--ci` keeps the checks scoped `ci`; `--adoption` runs the repository's own rows and the gate dry run (no
    environment, provisioning or sandbox rows: it is for a laptop before the first push; `--no-gates` leaves out the
    dry run); `--unit` narrows the unit-aware checks; `--fix` applies the safe fixes of
    failing checks (only provisioning ones under `--ci`), re-runs those checks and reports the state after fixing."""
    if no_gates and not adoption:
        raise L4Exit(ExitCode.USAGE_ERROR, "--no-gates only goes with --adoption")
    if unit is not None:
        try:
            parse_unit_id(unit)
        except ValueError as exc:
            raise L4Exit(ExitCode.USAGE_ERROR, str(exc)) from None
    if ci and (
        stop := early_pin_stop(app.repo, app.environ, command="doctor", config_path=app.config_path)
    ):  # L4-IMP-072: before the config
        return stop.exit_code
    app, cfg = load_app_config(app)  # schema errors: exit 2, nothing else runs
    known = {r.id for p in providers_for(cfg, app.repo, app.environ) for r in p.list_units()} if unit else set()
    if unit is not None and unit not in known:
        raise L4Exit(ExitCode.USAGE_ERROR, f"no such unit: {unit}")  # a typo must not look like a passing check
    cache = cache_root(app.environ, repo=app.repo)
    load_check_modules()
    ctx = dataclasses.replace(system_context(app.repo, cfg, app.environ), adoption=adoption)
    scopes = doctor_scopes(ci=ci, adoption=adoption, no_gates=no_gates)
    outcomes = run_checks(ctx, live=live, scopes=scopes, unit=unit)
    actions = None
    if fix:
        ran = apply_fixes(ctx, outcomes, REGISTRY, ci=ci, live=live, scopes=scopes, unit=unit)
        outcomes, actions = ran.outcomes, ran.actions
    code = exit_code(outcomes)
    if actions and any(a.status == "failed" for a in actions):
        code = ExitCode.DOCTOR_FAILED  # a failed install is exit 3 even when its check was only a warning
    if as_json:
        text = render_json(outcomes, code, actions)
    else:
        text = render_table(outcomes)
        if actions:
            text += f"\n\n{render_fixes(actions)}"
        if live:
            text += f"\n\nprobe cost: ${sum(o.cost_usd for o in outcomes):.4f}"
        text += f"\n\ncache: {cache}\nhome:  {l4_home(app.environ)}"
    click.echo(app.redactor.redact_text(text))
    return code
