"""SANDBOX-002 (HB-1): a tiny bwrap probe with the real argv; the check FAILS if a container-daemon socket is
reachable from either sandbox kind. A fake runner stands in for bwrap."""

from collections.abc import Sequence

from l4.config.schema import L4Config
from l4.doctor import checks_sandbox as sb
from l4.doctor.context import CmdResult
from l4.doctor.registry import Check, Registry, exit_code, run_checks
from l4.sandbox.bwrap import base_flags


class FakeBwrap:
    def __init__(self, *outputs: CmdResult) -> None:
        self.outputs = list(outputs)
        self.calls: list[list[str]] = []

    def run(self, argv: Sequence[str], timeout: float = 10.0, env=None) -> CmdResult:
        self.calls.append(list(argv))
        return self.outputs.pop(0) if len(self.outputs) > 1 else self.outputs[0]


def run_check(make_ctx, fake: FakeBwrap, cfg: L4Config | None = None, tools=None):
    ctx, _ = make_ctx(tools=tools if tools is not None else {"bwrap": "x", "python3": "x"}, cfg=cfg)
    ctx = type(ctx)(ctx.repo, ctx.cfg, ctx.env, ctx.which, fake.run, ctx.python_version)
    registry = Registry()
    registry.register(Check("SANDBOX-002", "daemon sockets", "error", sb._sandbox_002))
    (result,) = run_checks(ctx, registry=registry)
    return result, exit_code([result])


def test_a_clean_probe_passes_and_runs_both_kinds_with_the_real_argv(make_ctx):
    fake = FakeBwrap(CmdResult(0, f"{sb.CLEAN}\n", ""))
    result, code = run_check(make_ctx, fake)
    assert result.status == "pass" and int(code) == 0
    assert len(fake.calls) == 2
    shared, gate_net = fake.calls
    assert shared[0] == "/fake/bin/bwrap" and shared[1 : 1 + len(base_flags(network=True))] == base_flags(network=True)
    assert gate_net[1 : 1 + len(base_flags(network=False))] == base_flags(network=False)
    assert "--unshare-net" in gate_net and "--share-net" in shared
    assert shared[-3:-1] == ["/fake/bin/python3", "-c"] and "docker.sock" in shared[-1]


def test_a_reachable_socket_fails_with_exit_3(make_ctx):
    leaked = f"{sb.REACHABLE} connect:/var/run/docker.sock, socket:/run/containerd/containerd.sock\n"
    fake = FakeBwrap(CmdResult(0, leaked, ""))
    result, code = run_check(make_ctx, fake)
    assert (result.status, result.severity) == ("fail", "error") and int(code) == 3
    assert "/var/run/docker.sock" in result.message and "agent" in result.message
    assert result.fix_hint and "sandbox" in result.fix_hint


def test_a_socket_reachable_only_without_network_is_still_a_failure(make_ctx):
    fake = FakeBwrap(CmdResult(0, f"{sb.CLEAN}\n", ""), CmdResult(0, f"{sb.REACHABLE} socket:/run/docker.sock\n", ""))
    result, _ = run_check(make_ctx, fake)
    assert result.status == "fail" and "gate" in result.message


def test_a_probe_that_cannot_run_fails_closed(make_ctx):
    result, _ = run_check(make_ctx, FakeBwrap(CmdResult(1, "", "bwrap: No permissions to create new namespace")))
    assert result.status == "fail" and "namespace" in result.message


def test_without_bwrap_or_with_mode_none_the_check_is_skipped(make_ctx):
    fake = FakeBwrap(CmdResult(0, sb.CLEAN, ""))
    assert run_check(make_ctx, fake, tools={"python3": "x"})[0].status == "skip"
    cfg = L4Config.model_validate({"sandbox": {"mode": "none", "allow_none": True}})
    assert run_check(make_ctx, fake, cfg=cfg)[0].status == "skip"
    assert fake.calls == []
