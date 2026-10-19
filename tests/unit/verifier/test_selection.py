from datetime import UTC, datetime
from pathlib import Path

import pytest

from l4.agents.base import ProbeCtx
from l4.agents.factory import Factory, WaitingCapacity
from l4.agents.fake import FakeAdapter
from l4.availability.cooldown import FakeClock
from l4.availability.vendor import vendor_provenance
from l4.config.schema import L4Config
from l4.exitcodes import ExitCode
from l4.verifier.selection import (
    assess_independence,
    independence_constraint,
    is_full_model_id,
    normalise_model,
    same_model,
    select_judge,
)

PROFILES = {
    "codex": {"adapter": "codex", "vendor": "openai", "model": "gpt-x"},
    "claude": {"adapter": "claude-code", "vendor": "anthropic"},
    "free": {"adapter": "opencode", "model": "opencode/big-pickle", "vendor": "zhipu"},
    "alias": {"adapter": "opencode", "model": "opencode/big-pickle"},  # no vendor
    "kiro": {"adapter": "kiro-cli", "vendor": "amazon"},
}


def config(judges: list[str], independence: str = "different_vendor", **profiles: dict) -> L4Config:
    return L4Config.model_validate(
        {
            "verifier": {"independence": independence},
            "profiles": {**PROFILES, "fake-j": {"adapter": "fake", "vendor": "fakeco"}, **profiles},
            "roles": {"implementer": ["codex"], "judges": judges},
        }
    )


def factory(cfg: L4Config, tmp_path: Path) -> Factory:
    ctx = ProbeCtx(environ={"PATH": "/usr/bin"}, cwd=tmp_path, run=lambda *a: None)
    clock = FakeClock(datetime(2026, 10, 4, 12, 0, tzinfo=UTC))
    # every adapter name is the fake one, so the ladder passes and the walk is decided by the constraint alone
    adapters = {name: FakeAdapter([]) for name in ("codex", "claude-code", "opencode", "kiro-cli", "fake")}
    return Factory(cfg, ctx, adapters=adapters, clock=clock)


def test_the_first_independent_judge_of_the_chain_is_selected(tmp_path):
    cfg = config(["codex", "claude", "free"])
    picked = select_judge(factory(cfg, tmp_path), cfg, "openspec:x", ["codex"])
    assert (picked.profile_name, picked.fallback_index, picked.fallback_from) == ("claude", 1, "codex")
    assert (picked.vendor, picked.provenance) == ("anthropic", "tool")


def test_a_declared_vendor_is_selected_and_marked_declared(tmp_path):
    cfg = config(["codex", "free"])
    picked = select_judge(factory(cfg, tmp_path), cfg, "openspec:x", ["codex"])
    assert (picked.profile_name, picked.vendor, picked.provenance) == ("free", "zhipu", "declared")


def test_fallback_vendor_widens_exclusion(tmp_path):
    cfg = config(["claude", "free", "fake-j"])
    f = factory(cfg, tmp_path)
    assert select_judge(f, cfg, "openspec:x", ["codex"]).profile_name == "claude"
    # the unit was also implemented by a fallback of the judge's vendor: that vendor is out
    assert select_judge(f, cfg, "openspec:x", ["codex", "claude"]).profile_name == "free"
    assert select_judge(f, cfg, "openspec:x", ["codex", "claude", "free"]).profile_name == "fake-j"


def test_alias_without_vendor_is_never_independent():
    cfg = config(["alias"])
    check = independence_constraint(cfg, ["codex"])
    assert check("alias", cfg.profiles["alias"]) == "judge profile alias has no known vendor"
    assert vendor_provenance(cfg.profiles["alias"]) == "unknown"
    assert vendor_provenance(cfg.profiles["alias"], "something") == "unknown"
    # and as an implementer it makes every judge non-independent
    unknown_impl = independence_constraint(cfg, ["alias"])
    assert unknown_impl("claude", cfg.profiles["claude"]) == "implementer profile alias has no known vendor"


def test_no_independent_profile_waits_and_calls_nothing(tmp_path):
    cfg = config(["codex"])
    f = factory(cfg, tmp_path)
    with pytest.raises(WaitingCapacity, match="no independent verifier") as exc:
        select_judge(f, cfg, "openspec:x", ["codex"])
    assert exc.value.code is ExitCode.WAITING_CAPACITY
    assert "share the vendor" in str(exc.value)
    assert f.availability.cooldowns.entries() == []
    assert all(a.requests == [] for a in f._adapters.values())  # type: ignore[attr-defined]
    assert [(u.profile, u.step) for u in exc.value.unready] == [("codex", "constraint")]  # kept for the MR note


def test_skip_passes_over_a_profile_and_may_grow_later(tmp_path):
    cfg = config(["claude", "free", "fake-j"])
    f = factory(cfg, tmp_path)
    skip: set[str] = set()
    assert select_judge(f, cfg, "openspec:x", ["codex"], skip=skip).profile_name == "claude"
    skip.add("claude")
    assert select_judge(f, cfg, "openspec:x", ["codex"], skip=skip).profile_name == "free"


def test_different_model_compares_models_and_none_checks_nothing():
    cfg = config(["free"], "different_model", twin={"adapter": "opencode", "model": "gpt-x", "vendor": "zhipu"})
    check = independence_constraint(cfg, ["codex"])
    assert check("twin", cfg.profiles["twin"]) == "judge profile twin and implementer profile codex share the model"
    assert check("free", cfg.profiles["free"]) is None
    assert independence_constraint(config(["twin"], "none"), ["codex"])("claude", cfg.profiles["claude"]) is None


def test_provenance_kinds():
    cfg = config([])
    assert vendor_provenance(cfg.profiles["codex"]) == "tool"
    assert vendor_provenance(cfg.profiles["claude"], "claude-haiku-4-5-20251001") == "served"
    assert vendor_provenance(cfg.profiles["free"]) == "declared"
    assert vendor_provenance(cfg.profiles["kiro"]) == "unknown"  # no model: any vendor may answer (L4-KJD-005)


def test_model_ids_and_aliases():
    assert is_full_model_id("claude-haiku-4-5-20251001") and is_full_model_id("claude-opus-4-8[1m]")
    assert not is_full_model_id("haiku") and not is_full_model_id("sonnet") and not is_full_model_id(None)
    assert same_model("claude-haiku-4-5", "claude-haiku-4-5-20251001")
    assert same_model("claude-opus-4-8", "claude-opus-4-8[1m]")
    assert not same_model("claude-haiku-4-5", "claude-sonnet-4-5")


def test_the_record_says_who_and_how_it_knows():
    cfg = config([])
    declared = assess_independence(cfg, ["codex"], "free")
    assert declared.status == "declared (unverified)"
    assert declared.line() == "independence: declared (unverified): free zhipu (declared), codex openai (tool)"
    served = assess_independence(cfg, ["codex"], "claude", served_model="claude-haiku-4-5-20251001")
    assert served.verified
    assert served.line() == (
        "independence: verified (different_vendor): claude anthropic (served claude-haiku-4-5-20251001), "
        "codex openai (tool)"
    )
    # a declared implementer makes it unverified on the other side too
    assert not assess_independence(cfg, ["free"], "claude", served_model="claude-x-1").verified
    assert assess_independence(config([], "none"), ["codex"], "claude").status.startswith("not checked")


def test_failed_judge_choice_is_in_the_ledger(tmp_path):
    from l4.availability.cooldown import FakeClock

    class Sink:
        def __init__(self):
            self.events = []

        def append(self, kind, /, **data):
            self.events.append((kind, data))

    cfg = config(["codex"])
    ctx = ProbeCtx(environ={"PATH": "/usr/bin"}, cwd=tmp_path, run=lambda *a: None)
    clock = FakeClock(datetime(2026, 10, 4, 12, 0, tzinfo=UTC))
    adapters = {name: FakeAdapter([]) for name in ("codex", "claude-code", "opencode", "kiro-cli", "fake")}
    sink = Sink()
    f = Factory(cfg, ctx, adapters=adapters, clock=clock, events=sink)
    with pytest.raises(WaitingCapacity):
        select_judge(f, cfg, "openspec:x", ["codex"])
    [(kind, data)] = sink.events
    assert kind == "availability.unavailable" and data["role"] == "judges" and data["required"] is True
    assert data["skipped"][0]["profile"] == "codex" and data["skipped"][0]["step"] == "constraint"


KIRO_JUDGE = {"adapter": "kiro-cli", "model": "claude-sonnet-4.5", "vendor": "anthropic"}


@pytest.fixture
def kiro_serves_judges(monkeypatch):
    """Task 7.1 adds kiro-cli to `JUDGE_ADAPTERS`; until then the selection of a Kiro judge is exercised here."""
    monkeypatch.setattr(
        "l4.verifier.selection.JUDGE_ADAPTERS", ("claude-code", "codex", "opencode", "kiro-cli", "fake")
    )


def test_a_kiro_judge_on_claude_is_not_independent_of_a_claude_code_implementer(tmp_path, kiro_serves_judges):
    cfg = config(["kiro-judge"], **{"kiro-judge": KIRO_JUDGE})
    check = independence_constraint(cfg, ["claude"])
    assert check("kiro-judge", cfg.profiles["kiro-judge"]) == (
        "judge profile kiro-judge and implementer profile claude share the vendor"
    )
    with pytest.raises(WaitingCapacity, match="no independent verifier") as exc:
        select_judge(factory(cfg, tmp_path), cfg, "openspec:x", ["claude"])
    assert "share the vendor" in str(exc.value)


def test_a_kiro_judge_on_claude_is_independent_of_a_kiro_implementer_on_qwen(tmp_path, kiro_serves_judges):
    qwen = {"adapter": "kiro-cli", "model": "qwen3-coder-next"}
    cfg = config(["kiro-judge"], **{"kiro-judge": KIRO_JUDGE, "kiro-impl": qwen})
    picked = select_judge(factory(cfg, tmp_path), cfg, "openspec:x", ["kiro-impl"])
    assert (picked.profile_name, picked.vendor, picked.provenance) == ("kiro-judge", "anthropic", "declared")
    assert assess_independence(cfg, ["kiro-impl"], "kiro-judge").line() == (
        "independence: declared (unverified): kiro-judge anthropic (declared), kiro-impl alibaba (declared)"
    )


def test_dotted_and_dashed_model_ids_are_one_model_under_different_model():
    claude = {"adapter": "claude-code", "model": "claude-sonnet-4-5-20250929"}
    cfg = config(["kiro-judge"], "different_model", **{"kiro-judge": KIRO_JUDGE, "impl": claude})
    check = independence_constraint(cfg, ["impl"])
    assert check("kiro-judge", cfg.profiles["kiro-judge"]) == (
        "judge profile kiro-judge and implementer profile impl share the model"
    )
    other = {"adapter": "kiro-cli", "model": "claude-haiku-4.5"}
    cfg = config(["j"], "different_model", j=other, impl=claude)
    assert independence_constraint(cfg, ["impl"])("j", cfg.profiles["j"]) is None
    assert normalise_model("claude-sonnet-4.5") == "claude-sonnet-4-5"
    assert normalise_model("gpt-5.6-sol") == "gpt-5-6-sol"
    assert same_model("gpt-5.6-sol", "gpt-5-6-sol")


def test_the_independence_record_compares_normalised_models():
    claude = {"adapter": "claude-code", "model": "claude-sonnet-4-5-20250929"}
    cfg = config([], "different_model", **{"kiro-judge": KIRO_JUDGE, "impl": claude})
    assert not assess_independence(cfg, ["impl"], "kiro-judge").independent
    other = {**KIRO_JUDGE, "model": "claude-haiku-4.5"}
    cfg = config([], "different_model", j=other, impl=claude)
    assert assess_independence(cfg, ["impl"], "j").independent
