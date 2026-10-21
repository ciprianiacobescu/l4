"""M1.2 Stage C exit on fakes: SCN-AVL-02, 03, 08, 09, 10, 16, 17, 19 (amended for Q9) and SCN-FAC-06, 09, 12 over
`FakeAdapter` and `FakeClock`. The live protocol (tests/live/test_m1_2_acceptance.py) repeats what a real runner can."""

import re
import threading
from datetime import UTC, datetime, timedelta

import pytest

from l4.agents.base import LimitSignal, PermissionPolicy, RunRequest
from l4.agents.claude_code import ClaudeCodeAdapter
from l4.agents.factory import Factory, WaitingCapacity
from l4.agents.fake import FakeAdapter, Step
from l4.agents.gate import ConcurrencyGate
from l4.availability.cooldown import AvailabilityStore, FakeClock, cooldown_key
from l4.availability.quota import Window, evaluate_windows
from l4.config.schema import L4Config, Profile
from l4.exitcodes import ExitCode
from l4.planner import UnitFacts, next_action
from l4.specs.criteria import openspec_criteria
from l4.verifier.selection import assess_independence, select_judge

from ..unit.availability._selection_helpers import Scripted, exhausted, healthy, probe_ctx
from ..unit.conftest import FIXTURE, UNIT
from ..unit.implementer.conftest import blocked_step, green_step, red_step
from ..unit.verifier.conftest import judge_reply

T0 = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
T1, T2, T3 = (T0 + timedelta(hours=h) for h in (5, 9, 30))
CODEX = {"adapter": "fake", "model": "m-sol", "vendor": "openai", "auth": "subscription"}
CLAUDE = {"adapter": "fake", "model": "m-son", "vendor": "anthropic", "auth": "subscription"}
TWO = {
    "profiles": {"codex-sol": CODEX, "claude-sonnet": CLAUDE},
    "roles": {"implementer": ["codex-sol", "claude-sonnet"]},
}
CRITERIA = [c.id for c in openspec_criteria(FIXTURE / "openspec" / "changes" / "add-discount-codes")]


def limit(at: datetime | None = T1) -> LimitSignal:
    return LimitSignal("fake", None, "usage_limit", at, "scenario", "You have hit your usage limit")


def commit_trailers(run, trailer: str) -> list[str]:
    fmt = f"%(trailers:key={trailer},valueonly,separator=%x2c)"
    log = run.raw(run.tdd.origin, "log", "--reverse", f"--format=%s|{fmt}", "main..l4/openspec/add-discount-codes")
    return [line.split("|", 1)[1] for line in log.splitlines() if line.startswith(("test(", "feat("))]


def seed_cooldown(run_tdd, name: str, profile: dict, until: datetime) -> None:
    store = AvailabilityStore(run_tdd.cache)
    store.cooldowns.record(name, cooldown_key(name, Profile(**profile)), until, "usage_limit", "scenario", now=T0)


def test_scn_avl_02_codex_exhausted_falls_back_before_any_request(scenario, tdd_repo, capsys):
    adapter = Scripted({**exhausted("m-sol", resets=T1), **healthy("m-son")}, [red_step(), green_step()])
    run = scenario(adapter, **TWO)
    assert run.code == 0
    assert {r.profile.model for r in adapter.requests} == {"m-son"}  # no model request reached codex-sol
    assert "hello" not in {step for model, step in adapter.calls if model == "m-sol"}
    (cooldown,) = run.events("availability.cooldown")
    assert (cooldown["profile"], cooldown["until"], cooldown["kind"]) == (
        "codex-sol",
        "2026-01-01T05:00:00Z",
        "usage_limit",
    )
    assert AvailabilityStore(tdd_repo.cache).cooldowns.cooling(("fake", "m-sol"), T0) is not None
    err = capsys.readouterr().err
    assert re.search(
        r"\[l4\] implementer: codex-sol skipped — quota: 5h window 100% used, 0% remaining "
        r"\(resets 2026-01-01T05:00Z\); cool-down recorded",
        err,
    )
    assert re.search(r"\[l4\] implementer: claude-sonnet ok \(.*\) → selected, fallback #1", err)
    assert commit_trailers(run, "L4-Fallback-From") == ["codex-sol", "codex-sol"]
    assert commit_trailers(run, "L4-Agent") == ["claude-sonnet/m-son"] * 2
    assert run.outcome["units"][0]["profiles"]["fallback_from"] == "codex-sol"


def selection_factory(tmp_path, windows, *, reserve: float = 10):
    clock = FakeClock(T0)
    store = AvailabilityStore(tmp_path / "cache", clock=clock)
    quota = evaluate_windows(
        "codex", "m-sol", windows, reserve=reserve, reserve_is_profile=False, source="codex.rateLimits"
    )
    plan = {**healthy("m-sol"), **healthy("m-son")}
    plan["m-sol"]["quota"] = quota
    cfg = L4Config(profiles={"codex-sol": Profile(**CODEX), "claude-sonnet": Profile(**CLAUDE)}, roles=TWO["roles"])  # type: ignore[arg-type]
    events: list = []

    class Sink:
        run_id = "r-20260101T0000Z-aaaa"

        def append(self, name, /, **data):
            events.append((name, data))

    factory = Factory(
        cfg, probe_ctx(tmp_path), events=Sink(), adapters={"fake": Scripted(plan)}, availability=store, clock=clock
    )
    return factory, store, events


def test_scn_avl_03_below_the_remaining_percent_threshold_counts_as_exhausted(tmp_path, caplog):
    caplog.set_level("INFO")
    factory, _store, _events = selection_factory(tmp_path, [Window("5h window", 93, 300, T1)])
    picked = factory.for_role("implementer", UNIT)
    assert picked.profile_name == "claude-sonnet"
    (skipped,) = picked.skipped
    assert (skipped["profile"], skipped["step"]) == ("codex-sol", "quota")
    assert "codex-sol skipped — quota: 5h window 93% used, 7% remaining < 10%" in caplog.text


def test_scn_avl_16_weekly_window_exhausted_while_five_hour_is_fine(tmp_path, caplog):
    caplog.set_level("INFO")
    week = T0 + timedelta(days=5)
    windows = [Window("5h window", 20, 300, T1), Window("weekly window", 97, 10080, week)]
    factory, store, _events = selection_factory(tmp_path, windows)
    picked = factory.for_role("implementer", UNIT)
    assert [s["profile"] for s in picked.skipped] == ["codex-sol"]
    assert "codex-sol skipped — quota: weekly window 97% used, 3% remaining < 10%" in caplog.text
    assert store.cooldowns.cooling(("fake", "m-sol"), T0).until == week  # type: ignore[union-attr]


def test_scn_fac_06_selection_is_explained_by_exactly_one_event(tmp_path):
    factory, _store, events = selection_factory(tmp_path, [Window("5h window", 100, 300, T1)])
    picked = factory.for_role("implementer", UNIT)
    selected = [data for name, data in events if name == "availability.selected"]
    assert len(selected) == 1
    assert (selected[0]["selected"], selected[0]["fallback_index"]) == (picked.profile_name, 1)
    assert [(s["profile"], s["step"]) for s in selected[0]["skipped"]] == [("codex-sol", "quota")]
    assert selected[0]["skipped"][0]["reason"] == "usage window exhausted"


def test_scn_avl_08_a_mid_run_limit_moves_the_task_to_the_next_profile_with_a_fresh_session(scenario):
    script = [red_step(), Step(status="rate_limited", limit=limit(T1), session_id="old"), green_step()]
    adapter = Scripted({**healthy("m-sol"), **healthy("m-son")}, script)
    run = scenario(adapter, **TWO)
    assert run.code == 0
    models = [r.profile.model for r in adapter.requests]
    assert models == ["m-sol", "m-sol", "m-son"]
    assert [s.split("(")[0] for s in run.subjects() if not s.startswith("chore")] == ["test", "feat"]  # red not redone
    assert adapter.requests[2].resume_session_id is None and adapter.requests[2].preset_session_id is None
    assert 'kind="previous-attempt"' in adapter.requests[2].prompt
    (fallback,) = run.events("availability.fallback")
    assert (fallback["from"], fallback["to"], fallback["reason"], fallback["resets_at"]) == (
        "codex-sol", "claude-sonnet", "usage_limit", "2026-01-01T05:00:00Z",
    )  # fmt: skip
    assert commit_trailers(run, "L4-Fallback-From") == ["", "codex-sol"]


PROFILES3 = {"p1": {**CODEX}, "p2": {**CODEX, "model": "m2"}, "p3": {**CODEX, "model": "m3"}}
CHAIN3 = {"profiles": PROFILES3, "roles": {"implementer": ["p1", "p2", "p3"]}}


def test_scn_avl_09_every_profile_cooling_waits_with_the_earliest_reset(scenario, tdd_repo):
    for (name, profile), until in zip(PROFILES3.items(), (T1, T2, T3), strict=True):
        seed_cooldown(tdd_repo, name, profile, until)
    adapter = FakeAdapter([red_step()])
    run = scenario(adapter, **CHAIN3)
    assert run.code == ExitCode.WAITING_CAPACITY and adapter.requests == []
    (unit,) = run.outcome["units"]
    assert unit["phase_after"] == "waiting_capacity" and unit["retry_after"] == "2026-01-01T05:00:00Z"


def test_scn_avl_10_the_unit_resumes_after_the_reset_and_the_expired_profile_is_probed_again(
    scenario, tdd_repo, fake_clock, capsys
):
    for name in ("p2", "p3"):
        seed_cooldown(tdd_repo, name, PROFILES3[name], T2 if name == "p2" else T3)
    first = Scripted({}, [red_step(), Step(status="quota", limit=limit(T1))])  # p1 runs out in green: all three cool
    parked = scenario(first, **CHAIN3)
    assert parked.code == ExitCode.WAITING_CAPACITY
    assert parked.outcome["units"][0]["retry_after"] == "2026-01-01T05:00:00Z"
    facts = UnitFacts(
        UNIT, "openspec", "waiting_capacity", 0, 1, retry_after="2026-01-01T05:00:00Z", previous_phase="implementing"
    )
    assert next_action(facts, T1 - timedelta(minutes=1))[0] == "none"
    assert next_action(facts, T1 + timedelta(minutes=1)) == (
        "implement",
        "capacity: retry_after 2026-01-01T05:00:00Z passed",
    )
    fake_clock.advance(timedelta(hours=5, minutes=1))  # the clock is past T1, before T2
    capsys.readouterr()
    adapter = Scripted({}, [green_step()])
    run = scenario(adapter, unit=False, **CHAIN3)  # the plain `l4 run`: the planner hands the unit over
    assert run.code == 0 and "capacity_restored" in run.triggers()
    assert [model for model, step in adapter.calls if step == "binary"] == ["m-sol"]  # p1 re-probed; p2, p3 cooling
    assert "[l4] implementer: p1 ok (" in capsys.readouterr().err
    assert run.outcome["units"][0]["phase_after"] == "implemented"
    assert [s.split("(")[0] for s in run.subjects() if not s.startswith("chore")] == ["test", "feat"]


def test_scn_avl_17_optional_roles_degrade_and_required_roles_wait(scenario, tdd_repo):
    for name in ("c1", "s1"):
        seed_cooldown(tdd_repo, name, CLAUDE | {"model": name}, T3)
    config = {
        "profiles": {"c1": CLAUDE | {"model": "c1"}, "s1": CLAUDE | {"model": "s1"}},
        "roles": {"clarifier": ["c1"], "s1_judge": ["s1"]},
        "clarifier": {"s1_standin": "llm_boolean"},
    }
    run = scenario(FakeAdapter([blocked_step()]), **config)
    assert run.code == ExitCode.AWAITING_HUMAN  # a human, never exit 12
    assert "waiting_capacity" not in [e["to"] for e in run.events("phase.changed")]
    (looked,) = run.events("clarifier.result")
    assert looked["status"] == "unavailable" and looked["auto_accepted"] is False


def zen_config(*, vendor: str | None) -> dict:
    zen = {"adapter": "fake", "model": "opencode/big-pickle", **({"vendor": vendor} if vendor else {})}
    return {
        "profiles": {
            "opencode-zen": zen,
            "judge-claude": {"adapter": "fake", "vendor": "anthropic"},
            "judge-sol": {"adapter": "fake", "vendor": "openai"},
        },
        "roles": {"implementer": ["opencode-zen"], "judges": ["judge-claude", "judge-sol"]},
    }


def test_scn_avl_19_an_undisclosed_alias_is_never_independent_and_the_unit_waits(scenario):
    adapter = FakeAdapter([red_step(), green_step()])
    run = scenario(adapter, verify=True, **zen_config(vendor=None))
    assert run.code == ExitCode.WAITING_CAPACITY and len(adapter.requests) == 2  # no judge was called
    parked = [e for e in run.events("phase.changed") if e["to"] == "waiting_capacity"]
    assert (
        "no independent verifier" in parked[0]["reason"]
        and "implementer profile opencode-zen has no known vendor" in parked[0]["reason"]
    )


def test_scn_avl_19_amended_a_declared_vendor_is_independent_but_reported_unverified(scenario):
    adapter = FakeAdapter([red_step(), green_step(), Step(structured=judge_reply(CRITERIA))])
    run = scenario(adapter, verify=True, **zen_config(vendor="zhipu"))
    assert run.code == 0 and run.outcome["units"][0]["verdict"] == "PASS"
    text = run.pushed("openspec/changes/add-discount-codes/verification.md")
    assert (
        "independence: declared (unverified): judge-claude anthropic (declared), opencode-zen zhipu (declared)" in text
    )


def test_scn_fac_09_concurrent_runs_never_drive_one_login_at_once(tmp_path):
    claude = CLAUDE | {"base_url": "https://b.example"}  # another login: the gate is per (tool, identity)
    inside, overlaps = threading.Event(), []
    release = threading.Event()
    running = 0

    class Slow(Scripted):
        def run(self, req):
            nonlocal running
            running += 1
            overlaps.append(running)
            inside.set()
            release.wait(5)
            running -= 1
            return super().run(req)

    plan = {**healthy("m-sol"), **healthy("m-son")}

    def factory_for(adapter):
        clock = FakeClock(T0)
        store = AvailabilityStore(tmp_path / "cache", clock=clock)
        cfg = L4Config(profiles={"codex-sol": Profile(**CODEX), "claude-sonnet": Profile(**claude)}, roles=TWO["roles"])  # type: ignore[arg-type]
        gate = ConcurrencyGate(tmp_path / "cache")
        return Factory(cfg, probe_ctx(tmp_path), adapters={"fake": adapter}, availability=store, clock=clock, gate=gate)

    first = factory_for(Slow(plan, [Step()])).for_role("implementer", "u1")
    assert first.profile_name == "codex-sol"
    request = RunRequest(
        profile=first.profile, role="implementer", cwd=tmp_path, prompt="p", result_path=tmp_path / "r.json",
        raw_events_path=tmp_path / "e.jsonl", env={}, permission_policy=PermissionPolicy("implement"),
    )  # fmt: skip
    worker = threading.Thread(target=first.impl.run, args=(request,))
    worker.start()
    assert inside.wait(5)
    second = factory_for(Scripted(plan)).for_role("implementer", "u2")  # while the first still runs
    release.set()
    worker.join(5)
    assert (second.profile_name, second.fallback_index) == ("claude-sonnet", 1)
    assert second.skipped[0]["step"] == "concurrency" and max(overlaps) == 1


def test_scn_fac_12_a_cli_judge_serves_the_judges_role_tool_less(tmp_path):
    cfg = L4Config(
        profiles={
            "codex-sol": Profile(adapter="codex", model="gpt-6.1-sol", vendor="openai"),
            "judge-claude-cli": Profile(adapter="claude-code", vendor="anthropic"),
        },
        roles={"implementer": ["codex-sol"], "judges": ["judge-claude-cli"]},
    )  # type: ignore[arg-type]
    request = RunRequest(
        profile=cfg.profiles["judge-claude-cli"], role="judge", cwd=tmp_path, prompt="p",
        result_path=tmp_path / "r.json", raw_events_path=tmp_path / "e.jsonl", env={},
        permission_policy=PermissionPolicy("judge"), result_schema={"type": "object"},
    )  # fmt: skip
    argv = ClaudeCodeAdapter().build_command(request, exe="claude")
    for flag in ("--json-schema", "--safe-mode", "--strict-mcp-config", "--no-session-persistence", "--max-turns"):
        assert flag in argv
    assert argv[argv.index("--tools") + 1] == "" and argv[argv.index("--max-turns") + 1] == "3"
    assert "-p" in argv and "p" not in argv  # the prompt goes on stdin
    record = assess_independence(cfg, ["codex-sol"], "judge-claude-cli", served_model="claude-haiku-4-5-20251001")
    assert record.verified and record.judge.vendor == "anthropic" and record.implementers[0].vendor == "openai"
    with pytest.raises(WaitingCapacity, match="no independent verifier"):
        bad = cfg.model_copy(update={"roles": cfg.roles.model_copy(update={"judges": ["codex-sol"]})})
        select_judge(Factory(bad, probe_ctx(tmp_path), adapters={"codex": FakeAdapter([])}), bad, "u", ["codex-sol"])
    assert all(isinstance(a, str) for a in argv)


def test_a_run_that_resumes_at_verifying_still_reports_the_implementer_and_its_fallback(scenario, tdd_repo, fake_clock):
    judge = {"adapter": "fake", "model": "m-judge", "vendor": "openai", "auth": "subscription"}
    config = {
        "profiles": {"codex-sol": CODEX, "claude-sonnet": CLAUDE, "judge-gpt": judge},
        "roles": {"implementer": ["codex-sol", "claude-sonnet"], "judges": ["judge-gpt"]},
    }
    seed_cooldown(tdd_repo, "codex-sol", CODEX, T1)
    seed_cooldown(tdd_repo, "judge-gpt", judge, T1)
    first = scenario(Scripted(healthy("m-son"), [red_step(), green_step()]), verify=True, **config)
    assert first.code == ExitCode.WAITING_CAPACITY
    assert first.outcome["units"][0]["profiles"]["fallback_from"] == "codex-sol"
    fake_clock.advance(timedelta(hours=5, minutes=1))
    adapter = Scripted(healthy("m-judge"), [Step(structured=judge_reply(CRITERIA))])
    run = scenario(adapter, verify=True, unit=False, **config)
    assert run.code == 0 and "capacity_restored" in run.triggers()
    assert {r.profile.model for r in adapter.requests} == {"m-judge"}  # this run selected no implementer
    unit = run.outcome["units"][0]
    assert unit["verdict"] == "PASS"
    assert unit["profiles"]["implementer"] == "claude-sonnet" and unit["profiles"]["fallback_from"] == "codex-sol"
