"""`l4 ci start [--if-idle DURATION]`: start the harness's CI run on the base branch only when it is idle (L4-OPS-024).

People drive a plan from a laptop with a loop that starts a run; a loop that starts one while another is queued or
running, or right after one ended, wastes a run and the budget. This command asks the forge first (`base_activity`,
the listing `base_runs` reads) and starts a run only when none of the harness's CI is queued or running on the base
branch and, with `--if-idle`, the last one ended at least DURATION ago. It says what it did or why not.

Exit 0: a run was started, or the forge showed a run going or a recent one (a loop goes on). Exit 3: the token is
missing, the forge refuses the start, or it cannot tell whether a run is going (a loop notices). Exit 2: a bad duration.
"""

from datetime import UTC, datetime

import click

from l4.config.redaction import load_app_config
from l4.config.schema import duration_seconds
from l4.context import AppContext
from l4.exitcodes import ExitCode, L4Exit
from l4.forge.base import ForgeError, ForgeUnavailable, make_forge
from l4.state.retry import how_to_start


def utc_now() -> datetime:
    return datetime.now(UTC)


def _age(seconds: float) -> str:
    return f"{int(seconds)} s" if seconds < 60 else f"{int(seconds // 60)} min"


def run_ci_start(app: AppContext, *, if_idle: str | None = None) -> int:
    idle_seconds = 0
    if if_idle is not None:
        try:
            idle_seconds = duration_seconds(if_idle)
        except ValueError:
            raise L4Exit(
                ExitCode.USAGE_ERROR,
                f"ci start: --if-idle is a duration such as 12m (digits and one of s, m, h): {if_idle}",
            ) from None
    app, cfg = load_app_config(app)
    base = cfg.forge.base_branch
    by_hand = f"start a run with: {how_to_start(app, cfg, base)}"

    def say(line: str) -> None:
        click.echo(app.redactor.redact_text(line))

    def fail(why: str) -> L4Exit:
        return L4Exit(ExitCode.DOCTOR_FAILED, app.redactor.redact_text(f"ci start: {why}"))

    try:
        forge = make_forge(cfg, app.environ, repo=app.repo)
    except ForgeUnavailable as exc:
        raise fail(f"{exc}, so no run can be started or asked about; {by_hand}") from None
    activity = forge.base_activity(base)
    if activity is None:
        raise fail(f"cannot tell whether a run is going on {base}; nothing started ({by_hand})")
    active, last_ended = activity
    if active > 0:
        say(f"a run is queued or running on {base}; nothing started")
        return int(ExitCode.OK)
    if if_idle is not None and last_ended is not None:
        age = max(0.0, (utc_now() - last_ended).total_seconds())
        if age < idle_seconds:
            say(f"the last run ended {_age(age)} ago (< {if_idle}); nothing started")
            return int(ExitCode.OK)
    try:
        answer = forge.start_run(base)
    except ForgeError as exc:
        raise fail(
            f"the forge failed the start on {base} ({exc}); a run may or may not have started: "
            "look before starting another"
        ) from None
    if answer == "started":
        say(f"run started on {base}")
        return int(ExitCode.OK)
    if answer == "already_queued":
        say(f"a run is already queued on {base}; nothing started")
        return int(ExitCode.OK)
    raise fail(f"the forge {'refused' if answer == 'refused' else 'cannot start'} a run on {base}; {by_hand}")
