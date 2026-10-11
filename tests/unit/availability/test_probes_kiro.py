import pytest

from l4.agents.kiro_cli import KiroCliAdapter
from l4.config.schema import Profile
from l4.doctor.context import CmdResult

from .conftest import RECORDED as ALL_RECORDED

RECORDED = ALL_RECORDED / "kiro-cli" / "2.27.1"
R28 = ALL_RECORDED / "kiro-cli" / "2.28.0"
PROFILE = Profile(adapter="kiro-cli", model="claude-sonnet-4", vendor="anthropic")


def probe(step, rules, make_ctx, profile=PROFILE, **kw):
    ctx, run = make_ctx(rules, **kw)
    return KiroCliAdapter().probe(profile, step, ctx), run


VERSION = {("--version",): CmdResult(0, (RECORDED / "runner-version.stdout.txt").read_text(), "")}


def test_binary_reads_the_recorded_version(make_ctx):
    out, _ = probe("binary", VERSION, make_ctx)
    assert out.ok and out.detail["version"] == "2.27.1"


def test_logged_out_is_installed_not_authenticated_from_the_runner_recording(make_ctx):
    whoami = CmdResult(
        int((RECORDED / "runner-whoami.exit.txt").read_text()), (RECORDED / "runner-whoami.stdout.txt").read_text(),
        (RECORDED / "runner-whoami.stderr.txt").read_text(),
    )  # fmt: skip
    out, run = probe("auth", {**VERSION, ("whoami",): whoami}, make_ctx)
    assert not out.ok and out.reason == "kiro-cli installed, not authenticated (or set KIRO_API_KEY)"
    assert run.calls[-1][0][1:] == ["whoami", "--format", "json"]


@pytest.mark.parametrize("path", [R28 / "mac-whoami.stdout.txt", RECORDED / "runner-whoami-logged-in.stdout.txt"])
def test_logged_in_is_the_flat_answer_and_keeps_no_account_field(make_ctx, path):
    """kiro-cli 2.27.1 and 2.28.0 print `{"accountType": ..., "email": ...}`, not `{"account": {...}}` (K1)."""
    out, _ = probe("auth", {**VERSION, ("whoami",): CmdResult(0, path.read_text(), "")}, make_ctx)
    assert out.ok and out.detail == {"logged_in": True}
    assert "example" not in repr(out)


@pytest.mark.parametrize("answer", ['{"accountType": "", "email": "x"}', '{"email": "x"}', '{"accountType": 3}', "[]"])
def test_a_flat_answer_without_an_account_type_is_unrecognised(make_ctx, answer):
    out, _ = probe("auth", {**VERSION, ("whoami",): CmdResult(0, answer, "")}, make_ctx)
    assert not out.ok and "unrecognised" in (out.reason or "")


def test_a_nonzero_exit_is_not_authenticated_even_with_an_account_type(make_ctx):
    answer = '{"accountType": "Pro"}'
    out, _ = probe("auth", {**VERSION, ("whoami",): CmdResult(1, answer, "")}, make_ctx)
    assert not out.ok and out.reason == "kiro-cli installed, not authenticated (or set KIRO_API_KEY)"


def test_an_unrecognised_whoami_answer_fails_auth(make_ctx):
    out, _ = probe("auth", {**VERSION, ("whoami",): CmdResult(0, "weird text", "")}, make_ctx)
    assert not out.ok and "unrecognised" in (out.reason or "")


USAGE = {("chat",): CmdResult(0, (R28 / "mac-usage.stdout.txt").read_text(), "")}


def test_quota_reads_the_credits_line_of_usage_without_a_model_call(make_ctx):
    out, run = probe("quota", {**VERSION, **USAGE}, make_ctx)
    assert out.ok and not out.skipped and out.detail["quota_window"] == "credits"
    assert out.detail["quota_used_percent"] == 0
    assert run.calls[-1][0][1:] == ["chat", "--no-interactive", "/usage"]


def test_quota_fails_when_the_credits_are_used_up_with_the_reset_date(make_ctx):
    text = "Estimated Usage | resets on 2026-11-01 | KIRO FREE\nCredits (50 of 50 covered in plan), 100.0%\n"
    out, _ = probe("quota", {**VERSION, ("chat",): CmdResult(0, text, "")}, make_ctx)
    assert not out.ok and "credits" in (out.reason or "")
    assert out.limit is not None and out.limit.resets_at.isoformat() == "2026-11-01T00:00:00+00:00"


def test_quota_with_an_unknown_usage_text_is_unrecognised_not_a_failure(make_ctx):
    out, _ = probe("quota", {**VERSION, ("chat",): CmdResult(0, "something new", "")}, make_ctx)
    assert out.ok and out.skipped and out.detail["quota_unrecognised"] is True


def test_hello_is_the_final_text_of_the_stream(make_ctx):
    stream = (R28 / "hello.stream.jsonl").read_text()
    out, run = probe("hello", {**VERSION, ("chat",): CmdResult(0, stream, "")}, make_ctx)
    assert out.ok
    argv = run.calls[-1][0]
    assert argv[1:4] == ["chat", "--no-interactive", "--trust-tools=read"] and "stream-json" in argv


def test_hello_reports_a_run_error_and_a_wrong_answer(make_ctx):
    err = (R28 / "missing-agent.stream.jsonl").read_text()
    out, _ = probe("hello", {**VERSION, ("chat",): CmdResult(4, err, "")}, make_ctx)
    assert not out.ok and out.reason == "kiro-cli reported runError (init)"
    wrong = '{"type":"runFinished","data":{"status":"success","finalText":"hi there"}}'
    out, _ = probe("hello", {**VERSION, ("chat",): CmdResult(0, wrong, "")}, make_ctx)
    assert not out.ok and out.reason == "unexpected reply"


def test_the_ladder_stops_at_auth_with_the_operator_facing_reason(make_ctx):
    from l4.availability.probes import ProbeLadder

    whoami = CmdResult(1, (RECORDED / "runner-whoami.stdout.txt").read_text(), "")
    ctx, _ = make_ctx({**VERSION, ("whoami",): whoami})
    report = ProbeLadder(ctx, ["binary", "auth", "quota", "hello"]).run(KiroCliAdapter(), PROFILE)
    assert list(report.steps) == ["binary", "auth"]
    assert report.failed is not None
    assert report.failed.reason == "kiro-cli installed, not authenticated (or set KIRO_API_KEY)"


def test_a_throttled_hello_is_a_rate_limit_that_cools_the_profile(make_ctx):
    """Kiro e2e H2: a FREE-tier throttle is a limit (cool and fall through), not a hard hello failure."""
    stream = (R28 / "throttled.stream.jsonl").read_text()
    out, _ = probe("hello", {**VERSION, ("chat",): CmdResult(1, stream, "")}, make_ctx)
    assert not out.ok and out.failure_class == "limit"
    assert out.limit is not None and out.limit.kind == "rate_limit" and out.limit.resets_at is not None


def test_the_quota_probe_keeps_the_usage_credits_with_their_source(make_ctx):
    """Kiro e2e H2: `/usage` is the plan's own count; the ledger keeps it apart from the stream's metered credits."""
    usage = (R28 / "mac-usage.stdout.txt").read_text()
    out, _ = probe("quota", {**VERSION, ("chat",): CmdResult(0, usage, "")}, make_ctx)
    assert out.ok
    assert out.detail["credits_used"] == 0.18 and out.detail["credits_included"] == 1000
    assert out.detail["credits_source"] == "kiro.usage"
