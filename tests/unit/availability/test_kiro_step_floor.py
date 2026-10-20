"""kiro-judge live findings 1 and 3 (L4-AVL-012, L4-KJD-013): the kiro-cli quota step and the auth step's model
listing have a floor of 90 s under the step timeout, capped by `probe_timeout`; every step's duration is recorded."""

import time
from pathlib import Path

import pytest

from l4.agents.kiro_cli import KiroCliAdapter
from l4.availability.fallback import _ok_text
from l4.availability.probes import LadderReport, ProbeLadder
from l4.config.schema import Profile
from l4.doctor.context import CmdResult

RECORDED = Path(__file__).parents[2] / "fixtures" / "recorded" / "kiro-cli"
USAGE = (RECORDED / "2.28.0" / "mac-usage.stdout.txt").read_text()
LISTING = (RECORDED / "2.32.0" / "list-models.json").read_text()
VERSION = (RECORDED / "2.32.0" / "version.stdout.txt").read_text()
KIRO = Profile(adapter="kiro-cli", model="claude-sonnet-5.5", auth="api_key", vendor="anthropic")
KIRO_AUTO = Profile(adapter="kiro-cli", auth="api_key")


class SlowRun:
    """A runner with a clock: a call that takes longer than its timeout ends as the real runner ends it (exit 124)."""

    def __init__(self, took: dict[str, float]) -> None:
        self.took, self.calls, self.now = took, [], 0.0

    def clock(self) -> float:
        return self.now

    def __call__(self, argv, cwd, env, timeout):
        self.calls.append((list(argv), timeout))
        key = "usage" if "/usage" in argv else "listing" if "--list-models" in argv else "other"
        seconds = self.took.get(key, 0.0)
        out = {"usage": USAGE, "listing": LISTING, "other": VERSION if "--version" in argv else ""}[key]
        if argv[1:2] == ["--version"]:
            out = VERSION
        if seconds > timeout:
            self.now += timeout
            return CmdResult(124, "", "timed out")
        self.now += seconds
        return CmdResult(0, out, "")


def ctx_for(make_ctx, took, monkeypatch, **kw):
    run = SlowRun(took)
    monkeypatch.setattr(time, "monotonic", run.clock)
    ctx, _ = make_ctx({}, run=run, **kw)
    ctx.environ["KIRO_API_KEY"] = "k" * 12
    return ctx, run


def test_a_quota_step_of_30_s_passes_under_the_default_config(make_ctx, monkeypatch):
    ctx, run = ctx_for(make_ctx, {"usage": 30}, monkeypatch)  # timeout_s 60, step_timeout_s 20: the defaults
    assert (ctx.timeout_s, ctx.step_timeout_s) == (60.0, 20.0)
    out = KiroCliAdapter().probe(KIRO, "quota", ctx)
    assert out.ok and out.detail["quota_window"] == "credits"
    assert [t for argv, t in run.calls if "/usage" in argv] == [60]  # max(20, 90) capped by probe_timeout 60


def test_the_model_listing_of_the_auth_step_gets_the_floor_too(make_ctx, monkeypatch):
    ctx, run = ctx_for(make_ctx, {"listing": 30}, monkeypatch)
    out = KiroCliAdapter().probe(KIRO_AUTO, "auth", ctx)
    assert out.ok and out.detail["routed"]["source"] == "listed"
    assert [t for argv, t in run.calls if "--list-models" in argv] == [60]


@pytest.mark.parametrize(("probe_timeout", "used"), [(60, 60), (120, 90), (45, 45)])
def test_a_quota_step_over_the_floor_times_out_naming_the_seconds_used(make_ctx, monkeypatch, probe_timeout, used):
    ctx, _ = ctx_for(make_ctx, {"usage": 500}, monkeypatch, timeout_s=probe_timeout)
    report = ProbeLadder(ctx, ["binary", "quota"]).run(KiroCliAdapter(), KIRO)
    quota = report.steps["quota"]
    assert not quota.ok and quota.failure_class == "transient"
    assert quota.reason == (
        f"kiro-cli did not answer within {used} s (quota step); a login prompt or a helper process that keeps the "
        "output open can cause this: run l4 doctor"
    )


def test_the_floor_never_lowers_a_longer_step_timeout(make_ctx, monkeypatch):
    ctx, run = ctx_for(make_ctx, {"usage": 1}, monkeypatch, timeout_s=300, step_timeout_s=120)
    KiroCliAdapter().probe(KIRO, "quota", ctx)
    assert [t for argv, t in run.calls if "/usage" in argv] == [120]


def test_the_binary_step_and_other_clis_keep_the_step_timeout(make_ctx, monkeypatch):
    from l4.agents.claude_code import ClaudeCodeAdapter

    ctx, run = ctx_for(make_ctx, {}, monkeypatch)
    KiroCliAdapter().probe(KIRO, "binary", ctx)
    assert [t for _, t in run.calls] == [20]
    run.calls.clear()
    ClaudeCodeAdapter().probe(Profile(adapter="claude-code", model="m", vendor="anthropic"), "binary", ctx)
    assert [t for _, t in run.calls] == [20]


def test_every_step_records_how_long_it_took(make_ctx, monkeypatch):
    ctx, _ = ctx_for(make_ctx, {"usage": 27.4}, monkeypatch)
    report = ProbeLadder(ctx, ["binary", "auth", "quota"]).run(KiroCliAdapter(), KIRO)
    assert report.ok
    assert report.steps["quota"].detail["step_ms"] == 27400
    assert all(isinstance(r.detail["step_ms"], int) for r in report.steps.values())
    again = LadderReport.from_json(report.to_json())
    assert again.steps["quota"].detail["step_ms"] == 27400


def test_a_failed_step_records_its_duration_too(make_ctx, monkeypatch):
    ctx, _ = ctx_for(make_ctx, {"usage": 500}, monkeypatch)
    report = ProbeLadder(ctx, ["binary", "quota"]).run(KiroCliAdapter(), KIRO)
    assert report.steps["quota"].detail["step_ms"] == 60000


def test_the_probe_line_shows_a_step_that_took_a_second_or_more(make_ctx, monkeypatch):
    ctx, _ = ctx_for(make_ctx, {"usage": 27.4}, monkeypatch)
    report = ProbeLadder(ctx, ["binary", "auth", "quota"]).run(KiroCliAdapter(), KIRO)
    line = _ok_text("p", KIRO, report, False)
    assert line == "p ok (binary 2.32.0 · auth api_key · quota 0% used (credits) 27.4s)"  # fast steps stay short


def test_the_selected_event_carries_the_slow_steps(tmp_path):
    from l4.availability.fallback import Selection, to_event

    from ._selection_helpers import fake_profile

    profile = fake_profile("m")
    report = LadderReport()
    from l4.agents.base import ProbeResult

    report.steps["quota"] = ProbeResult(
        "quota", True, {"step_ms": 27400, "quota_used_percent": 44.3, "quota_window": "credits"}
    )
    report.steps["binary"] = ProbeResult("binary", True, {"version": "1", "step_ms": 12})
    selection = Selection("p", profile, None, 0, [], report, False)  # type: ignore[arg-type]
    assert to_event(selection, None)["probes"]["p"]["step_ms"] == {"quota": 27400}  # a step under 1 s is left out
