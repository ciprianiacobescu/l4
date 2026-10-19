import dataclasses
import json
from pathlib import Path

import pytest

from l4.agents.kiro_cli import KiroCliAdapter
from l4.availability.fallback import _step_text
from l4.availability.probes import LadderReport
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
    assert argv[1:4] == ["chat", "--no-interactive", "--v2"] and "stream-json" in argv
    assert not any(a.startswith("--trust") for a in argv) and argv[-1] == "Reply with exactly: L4-OK"


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


# --- the model listing of an `auto` profile, in the auth step (kiro-judge L4-KJD-013, task 1.3) ---

R32 = ALL_RECORDED / "kiro-cli" / "2.32.0"
AUTO = Profile(adapter="kiro-cli")
LISTING = CmdResult(0, (R32 / "list-models.json").read_text(), "")
LOGGED_IN = CmdResult(0, (R32 / "whoami-api-key.stdout.txt").read_text(), "")


def test_the_possible_vendors_come_from_the_active_models(make_ctx):
    """SCN-KJD-31."""
    out, run = probe("auth", {**VERSION, ("whoami",): LOGGED_IN, ("chat", "--list-models"): LISTING}, make_ctx, AUTO)
    assert out.ok
    routed = out.detail["routed"]
    assert routed["source"] == "listed" and routed["vendors"] == ["anthropic", "minimax", "zhipu"]
    assert len(routed["models"]) == 12 and "claude-sonnet-5-5" in routed["models"] and "glm-5" in routed["models"]
    for out_model in ("auto", "claude-opus-5-5", "gpt-5-6-sol", "deepseek-3-2", "minimax-m2-1", "kimi-k3"):
        assert out_model not in routed["models"]
    asked = [c[0][1:] for c in run.calls]
    assert asked[-2:] == [["whoami", "--format", "json"], ["chat", "--list-models", "--format", "json"]]


def test_a_pinned_profile_is_never_listed(make_ctx):
    pinned = Profile(adapter="kiro-cli", model="glm-5")
    out, run = probe("auth", {**VERSION, ("whoami",): LOGGED_IN, ("chat", "--list-models"): LISTING}, make_ctx, pinned)
    assert out.ok and "routed" not in out.detail
    assert all("--list-models" not in c[0] for c in run.calls)


def test_a_failed_listing_records_the_built_in_set_and_the_step_passes(make_ctx):
    """SCN-KJD-32."""
    failed = CmdResult(1, "", "error: service error")
    out, _ = probe("auth", {**VERSION, ("whoami",): LOGGED_IN, ("chat", "--list-models"): failed}, make_ctx, AUTO)
    routed = out.detail["routed"]
    assert out.ok and routed["source"] == "built-in" and routed["vendors"] == ["anthropic", "minimax", "zhipu"]
    assert routed["reason"] == "kiro-cli chat --list-models failed (exit 1)" and "service error" not in repr(out)
    assert _step_text(AUTO, "auth", out) == "auth ok · auto: anthropic, minimax, zhipu (built-in)"


@pytest.mark.parametrize("answer", [CmdResult(0, "not json", ""), CmdResult(0, '{"models": []}', ""),
                                    CmdResult(124, "", "")])  # fmt: skip
def test_an_unusable_listing_is_a_failed_listing(make_ctx, answer):
    out, _ = probe("auth", {**VERSION, ("whoami",): LOGGED_IN, ("chat", "--list-models"): answer}, make_ctx, AUTO)
    assert out.ok and out.detail["routed"]["source"] == "built-in" and out.detail["routed"]["reason"]


def test_the_listing_also_runs_when_the_credential_variable_decides_the_login(make_ctx):
    profile = Profile(adapter="kiro-cli", auth="api_key")
    ctx, run = make_ctx({**VERSION, ("chat", "--list-models"): LISTING})
    ctx.environ["KIRO_API_KEY"] = "synthetic-key"
    out = KiroCliAdapter().probe(profile, "auth", ctx)
    assert out.ok and out.detail["auth_method"] == "env" and out.detail["routed"]["source"] == "listed"
    assert all("whoami" not in c[0] for c in run.calls)
    assert run.calls[-1][2]["KIRO_API_KEY"] == "synthetic-key"  # the listing runs as the profile's login


def test_a_failed_login_check_lists_nothing(make_ctx):
    logged_out = CmdResult(1, '{"account": null}', "")
    rules = {**VERSION, ("whoami",): logged_out, ("chat", "--list-models"): LISTING}
    out, run = probe("auth", rules, make_ctx, AUTO)
    assert not out.ok and "routed" not in out.detail
    assert all("--list-models" not in c[0] for c in run.calls)


def test_the_account_email_of_whoami_is_never_kept(make_ctx):
    """SCN-KJD-34: the e-mail is built at run time, never written in the tree."""
    email = "".join(["person", "@", "example", ".invalid"])
    answer = CmdResult(0, json.dumps({"accountType": "ApiKey", "email": email}), "")
    out, _ = probe("auth", {**VERSION, ("whoami",): answer, ("chat", "--list-models"): LISTING}, make_ctx, AUTO)
    report = LadderReport({"auth": out})
    assert out.ok and "email" not in repr(out) and email not in repr(out)
    assert "email" not in json.dumps(report.to_json()) and email not in json.dumps(report.to_json())
    assert email not in _step_text(AUTO, "auth", out)


def test_scn_kjd_21_an_invalid_token_on_usage_fails_the_quota_step_as_auth(make_ctx):
    fixture = ALL_RECORDED / "kiro-cli" / "2.32.0" / "usage-invalid-key.stdout.txt"
    out, _ = probe("quota", {**VERSION, ("chat",): CmdResult(0, fixture.read_text(), "")}, make_ctx)
    assert not out.ok and not out.skipped and out.failure_class == "auth"
    assert out.reason == "kiro-cli usage: authentication failed"
    assert "quota_unrecognised" not in out.detail


# --- the hello runs the judge invocation (kiro-judge L4-KJD-007, task 6.1) ---


def _recording_run(tmp_path, answer):
    """A runner that answers the version check, records every other call and, while it runs, the agent file under the
    env's KIRO_HOME, the contents of that home and of the working directory."""
    seen = []

    def run(argv, cwd, env, timeout):
        if argv[1:] == ["--version"]:
            return CmdResult(0, (R32 / "version.stdout.txt").read_text(), "")
        home = env.get("KIRO_HOME")
        agent = argv[argv.index("--agent") + 1] if "--agent" in argv else None
        file = None
        if home and agent:
            path = Path(home) / "agents" / f"{agent}.json"
            file = json.loads(path.read_text()) if path.is_file() else None
        listing = sorted(str(p.relative_to(home)) for p in Path(home).rglob("*") if p.is_file()) if home else []
        seen.append(
            {
                "argv": list(argv), "cwd": Path(cwd), "env": dict(env), "agent_file": file, "home_files": listing,
                "cwd_files": sorted(p.name for p in Path(cwd).iterdir()), "agent": agent,
            }
        )  # fmt: skip
        return answer

    return run, seen


@pytest.mark.parametrize("model", ["glm-5", None])
def test_the_hello_runs_the_tool_less_judge_agent(make_ctx, tmp_path, model):
    """SCN-KJD-22: the judge argv plus the hello prompt, no trust flag, an empty cwd, a private KIRO_HOME."""
    ctx, _ = make_ctx({})
    run, seen = _recording_run(tmp_path, CmdResult(0, (R28 / "hello.stream.jsonl").read_text(), ""))
    ctx = dataclasses.replace(ctx, run=run)
    profile = Profile(adapter="kiro-cli", model=model, vendor="zhipu") if model else Profile(adapter="kiro-cli")
    out = KiroCliAdapter().probe(profile, "hello", ctx)
    assert out.ok
    (call,) = seen
    expected = model or "auto"
    argv = call["argv"]
    assert argv[1:] == [
        "chat", "--no-interactive", "--v2", "--agent", call["agent"], "--model", expected,
        "--output-format", "stream-json", ctx.hello_prompt,
    ]  # fmt: skip
    assert call["agent"].startswith("l4-judge-")
    assert not any("trust" in a for a in argv)
    assert call["cwd_files"] == [] and call["cwd"].parent.name.startswith("l4-kiro-probe-")
    assert call["home_files"] == [f"agents/{call['agent']}.json", "settings/cli.json"]
    assert call["agent_file"]["model"] == expected and call["agent_file"]["tools"] == []
    assert "KIRO_LOG_LEVEL" not in call["env"]
    assert not call["cwd"].parent.exists()  # the private directory is gone


def test_the_hello_makes_no_model_listing_call(make_ctx, tmp_path):
    ctx, _ = make_ctx({})
    run, seen = _recording_run(tmp_path, CmdResult(0, (R28 / "hello.stream.jsonl").read_text(), ""))
    KiroCliAdapter().probe(Profile(adapter="kiro-cli"), "hello", dataclasses.replace(ctx, run=run))
    assert all("--list-models" not in c["argv"] for c in seen)


def test_a_hello_with_an_invalid_key_is_an_auth_failure(make_ctx):
    """SCN-KJD-23."""
    stream = (R32 / "auth-invalid-key.stream.jsonl").read_text()
    out, _ = probe("hello", {**VERSION, ("chat",): CmdResult(1, stream, "")}, make_ctx)
    assert not out.ok and out.failure_class == "auth" and out.limit is None


def test_a_throttle_that_also_says_access_denied_stays_a_limit(make_ctx):
    stream = (
        '{"type":"runError","data":{"stage":"prompt","message":"The request was throttled by the service: '
        'AccessDenied"}}'
    )
    out, _ = probe("hello", {**VERSION, ("chat",): CmdResult(1, stream, "")}, make_ctx)
    assert out.failure_class == "limit"


def test_a_hello_with_no_stream_that_asks_for_a_login_is_an_auth_failure(make_ctx):
    out, _ = probe("hello", {**VERSION, ("chat",): CmdResult(1, "", "run kiro-cli login")}, make_ctx)
    assert not out.ok and out.failure_class == "auth"
