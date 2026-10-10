import json

from l4.doctor.registry import Check, CheckResult, Registry, run_checks
from l4.doctor.report import render_json
from l4.exitcodes import ExitCode


def registry() -> Registry:
    r = Registry()
    r.register(Check("T-OK", "cheap", "info", lambda c: CheckResult("pass", "ok")))
    for check_id, cost in (("LIVE-T1", 0.01), ("LIVE-T2", 0.0025)):

        def run(_ctx, cost=cost) -> CheckResult:
            return CheckResult("pass", "hello", cost_usd=cost)

        r.register(Check(check_id, "probe", "warn", run, frozenset({"live"})))
    return r


def test_live_checks_only_with_flag_and_cost_summed(make_ctx):
    ctx, _ = make_ctx()
    assert [o.id for o in run_checks(ctx, registry=registry())] == ["T-OK"]
    outcomes = run_checks(ctx, registry=registry(), live=True)
    assert [o.id for o in outcomes] == ["T-OK", "LIVE-T1", "LIVE-T2"]
    document = json.loads(render_json(outcomes, ExitCode.OK))
    assert document["probe_cost_usd"] == 0.0125
