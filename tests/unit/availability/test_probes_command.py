from l4.agents.command import CommandAdapter
from l4.config.schema import Profile
from l4.doctor.context import CmdResult


def profile(**options) -> Profile:
    return Profile(adapter="command", model="m-1", options={"argv": ["opencode", "{prompt_file}"], **options})


def probe(step, prof, rules, make_ctx):
    ctx, run = make_ctx(rules)
    return CommandAdapter().probe(prof, step, ctx), run


def test_binary_is_the_first_argv_entry_resolving_without_running_it(make_ctx):
    out, run = probe("binary", profile(), {}, make_ctx)  # `opencode` is a stub on the fake PATH
    assert out.ok and run.calls == []  # an arbitrary command is never run with --version
    missing, _ = probe("binary", profile(argv=["nope-tool"]), {}, make_ctx)
    assert not missing.ok and "not found" in (missing.reason or "")


def test_auth_and_quota_are_skipped(make_ctx):
    for step in ("auth", "quota"):
        out, _ = probe(step, profile(), {}, make_ctx)
        assert out.ok and out.skipped


def test_hello_without_probe_argv_is_skipped(make_ctx):
    out, run = probe("hello", profile(), {}, make_ctx)
    assert out.ok and out.skipped and run.calls == []


def test_hello_runs_probe_argv_with_the_model_and_passes_on_exit_0(make_ctx):
    prof = profile(probe_argv=["opencode", "ping", "--model", "{model}"])
    out, run = probe("hello", prof, {("ping",): CmdResult(0, "", "")}, make_ctx)
    assert out.ok and not out.skipped and out.detail["ms"] >= 0
    assert run.calls[0][0][1:] == ["ping", "--model", "m-1"]


def test_hello_fails_on_a_nonzero_exit_and_a_timeout(make_ctx):
    prof = profile(probe_argv=["opencode", "ping"])
    bad, _ = probe("hello", prof, {("ping",): CmdResult(3, "", "boom")}, make_ctx)
    assert not bad.ok and "3" in (bad.reason or "") and "boom" not in (bad.reason or "")
    slow, _ = probe("hello", prof, {("ping",): CmdResult(124, "", "timed out")}, make_ctx)
    assert not slow.ok and slow.failure_class == "transient"  # L4-AVL-012: a step that does not answer is transient
    assert (slow.reason or "").startswith("opencode did not answer within 60 s (hello step)")


def test_a_hello_timeout_is_not_cached(make_ctx, tmp_path):
    """L4-AVL-012: the failure the adapter reports goes through the ladder and nothing is remembered."""
    import pytest

    from l4.agents.factory import WaitingCapacity

    from .test_failure_ttl import build, read_back

    prof = profile(probe_argv=["opencode", "ping"])
    slow, _ = probe("hello", prof, {("ping",): CmdResult(124, "", "timed out")}, make_ctx)
    factory, _, clock, store, cfg = build(tmp_path, {"sonnet": {"hello": slow}})
    with pytest.raises(WaitingCapacity):
        factory.for_role("implementer", "u")
    assert read_back(tmp_path, store, cfg, clock.now()) is None
