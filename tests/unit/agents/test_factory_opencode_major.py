"""`Factory.build` picks the OpenCode adapter by `options.cli_major` (L4-OCV-001 adapter part, amendment E5):
SCN-OCV-01, SCN-OCV-26 and the class per major."""

from pathlib import Path

import pytest

from l4.agents.base import PermissionPolicy, ProbeCtx, ProbeResult, RunRequest
from l4.agents.factory import ADAPTERS, Factory
from l4.agents.fake import FakeAdapter
from l4.agents.opencode import OpenCodeAdapter, config_content, isolation_env
from l4.agents.opencode_v2 import OpenCodeV2Adapter
from l4.config.schema import L4Config, Profile, RolesCfg

PAID = "opencode-go/deepseek-v4.1-flash"
RESULT_DIR = Path("/tmp/l4-step/result")


class Sink:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def append(self, event_type, /, **data):
        self.events.append((event_type, data))

    def named(self, name: str) -> list[dict]:
        return [d for n, d in self.events if n == name]


@pytest.fixture
def ctx(tmp_path: Path) -> ProbeCtx:
    return ProbeCtx(environ={"PATH": "/usr/bin"}, cwd=tmp_path, run=lambda *a: None)


def profile(**options) -> Profile:
    return Profile(adapter="opencode", model=PAID, vendor="unknown", options=options)


def factory(ctx: ProbeCtx, profiles: dict[str, Profile], *, events=None, adapters=None) -> Factory:
    cfg = L4Config(profiles=profiles, roles=RolesCfg(implementer=list(profiles)))
    return Factory(cfg, ctx, events=events, adapters=adapters)


# -- SCN-OCV-01: a profile without cli_major is v1, byte for byte ------------------------------------------------------
# The expected strings below were taken from the v1 adapter before this change and are never regenerated.

V1_ARGV = [
    "/bin/opencode", "run", "--pure", "--format", "json", "-m", PAID, "--dir", "/w", "--title", "l4 implementer raw-001"
]  # fmt: skip
V1_IMPLEMENT = (
    '{"$schema":"https://opencode.ai/config.json","snapshot":false,"share":"disabled","autoupdate":false,'
    '"permission":{"edit":"allow","read":"allow","glob":"allow","grep":"allow","list":"allow",'
    '"bash":{"*":"allow","git commit*":"deny","git push*":"deny","git reset*":"deny","git checkout*":"deny"},'
    '"external_directory":{"*":"deny","/tmp/l4-step/result/**":"allow","/tmp/l4-step/result/*":"allow"},'
    '"webfetch":"deny","websearch":"deny","question":"deny","doom_loop":"deny"}}'
)
V1_JUDGE_PAID = (
    '{"$schema":"https://opencode.ai/config.json","snapshot":false,"share":"disabled","autoupdate":false,'
    '"tools":{"*":false},"permission":{"*":"deny"}}'
)
V1_JUDGE_FREE = (
    '{"$schema":"https://opencode.ai/config.json","snapshot":false,"share":"disabled","autoupdate":false,'
    '"permission":{"*":"deny","read":"ask","bash":"ask"}}'
)
V1_ENV = {
    "XDG_CONFIG_HOME": "/c", "OPENCODE_DISABLE_PROJECT_CONFIG": "1", "OPENCODE_DISABLE_CLAUDE_CODE": "1",
    "OPENCODE_DISABLE_EXTERNAL_SKILLS": "1", "OPENCODE_DISABLE_AUTOUPDATE": "1", "OPENCODE_CONFIG_CONTENT": "X",
}  # fmt: skip


@pytest.mark.parametrize("options", [{}, {"cli_major": 1}, {"reasoning": None}])
def test_a_profile_without_cli_major_two_builds_the_v1_adapter_unchanged(ctx, options):
    built = factory(ctx, {"oc": profile(**options)}).build(profile(**options))
    assert type(built) is OpenCodeAdapter
    req = RunRequest(
        profile=profile(**options), role="implementer", cwd=Path("/w"), prompt="p", env={},
        result_path=RESULT_DIR / "result.json", raw_events_path=Path("/tmp/l4-step/raw-001.jsonl"),
    )  # fmt: skip
    assert built.build_command(req, exe="/bin/opencode", workdir=Path("/w")) == V1_ARGV
    assert config_content(PermissionPolicy("implement"), RESULT_DIR, PAID) == V1_IMPLEMENT
    assert config_content(PermissionPolicy("judge"), RESULT_DIR, PAID) == V1_JUDGE_PAID
    assert config_content(PermissionPolicy("judge"), RESULT_DIR, "opencode/big-pickle") == V1_JUDGE_FREE
    assert isolation_env(Path("/c"), "X") == V1_ENV
    assert "steps" not in V1_IMPLEMENT and "agents" not in V1_IMPLEMENT  # a v1 run has no step bound


def test_the_registry_still_names_the_v1_class():
    assert ADAPTERS["opencode"] is OpenCodeAdapter


# -- the choice by cli_major (amendment E5) ---------------------------------------------------------------------------


def test_cli_major_two_builds_the_v2_adapter(ctx):
    built = factory(ctx, {"oc2": profile(cli_major=2)}).build(profile(cli_major=2))
    assert type(built) is OpenCodeV2Adapter and built.name == "opencode"


def test_one_factory_builds_each_major_with_its_own_class(ctx):
    v1, v2 = profile(), profile(cli_major=2)
    made = factory(ctx, {"oc1": v1, "oc2": v2})
    assert type(made.build(v1)) is OpenCodeAdapter and type(made.build(v2)) is OpenCodeV2Adapter
    assert type(made.build(profile(tools=["read"]))) is OpenCodeAdapter
    assert type(made.build(profile(cli_major=2, steps={"judge": 4}))) is OpenCodeV2Adapter


def test_every_other_adapter_is_built_as_before(ctx):
    codex = Profile(adapter="codex", model="gpt-5", vendor="openai")
    made = factory(ctx, {"codex": codex})
    first, second = made.build(codex), made.build(codex)
    assert type(first) is ADAPTERS["codex"] and first is not second  # a fresh instance per build, as before


def test_an_injected_opencode_adapter_serves_both_majors_unless_v2_has_its_own(ctx):
    v1, v2 = profile(), profile(cli_major=2)
    shared, own = FakeAdapter([]), FakeAdapter([])
    only = factory(ctx, {"oc1": v1, "oc2": v2}, adapters={"opencode": shared})
    assert only.build(v1) is shared and only.build(v2) is shared
    both = factory(ctx, {"oc1": v1, "oc2": v2}, adapters={"opencode": shared, "opencode2": own})
    assert both.build(v1) is shared and both.build(v2) is own


# -- SCN-OCV-26: the v2 adapter is announced as experimental -----------------------------------------------------------


def test_a_v2_profile_selected_twice_records_one_experimental_event(ctx, monkeypatch):
    monkeypatch.setattr(OpenCodeV2Adapter, "probe", lambda self, prof, step, pctx: ProbeResult(step, True))
    sink = Sink()
    made = factory(ctx, {"oc2": profile(cli_major=2)}, events=sink)
    assert made.for_role("implementer", "u1").profile_name == "oc2"
    assert made.for_role("implementer", "u1").profile_name == "oc2"
    assert sink.named("agent.experimental") == [{"profile": "oc2", "adapter": "opencode"}]


def test_a_v1_profile_is_never_announced_as_experimental(ctx, monkeypatch):
    monkeypatch.setattr(OpenCodeAdapter, "probe", lambda self, prof, step, pctx: ProbeResult(step, True))
    sink = Sink()
    factory(ctx, {"oc1": profile()}, events=sink).for_role("implementer", "u1")
    assert not sink.named("agent.experimental")
