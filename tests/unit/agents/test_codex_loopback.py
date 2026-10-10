"""M1.12 lines 15-16 (L4-SEC-001, L4-IMP-004): the Codex implementer cannot open sockets, and the harness says so.

Line 15, the spike (see `docs/plan/m112-progress.md`): codex is not installed on the build machine, so the 0.160 keys
could not be run. What the codex source documents is one boolean, `sandbox_workspace_write.network_access`, which turns
on ALL outbound network, not loopback only. The plan rejects that switch, so branch (b) is taken: the prompt names the
limit. The first test is the guard that keeps the switch out for good."""

import pytest

from l4.agents.base import PermissionPolicy
from l4.agents.codex import CodexAdapter
from l4.config.schema import Profile
from l4.implementer.prompt import render_prompt

from ..implementer.test_prompt import ctx
from .test_codex import request


@pytest.mark.parametrize("mode", ["implement", "judge", "read_only"])
@pytest.mark.parametrize("options", [{}, {"loopback": True}, {"network_access": True}, {"sandbox_workspace_write": 1}])
def test_no_network_setting_ever_reaches_the_codex_command_line(tmp_path, mode, options):
    profile = Profile(adapter="codex", model="gpt-6-luna", vendor="openai", options=options)
    argv = CodexAdapter().build_command(
        request(tmp_path, profile=profile, permission_policy=PermissionPolicy(mode)), exe="codex", schema_path=None
    )
    settings = [argv[i + 1] for i, a in enumerate(argv) if a == "-c"]
    assert not [c for c in settings if "network" in c or "sandbox_workspace_write" in c]
    assert argv[argv.index("-s") + 1] == ("workspace-write" if mode == "implement" else "read-only")


def test_the_contract_tells_the_codex_implementer_that_sockets_are_blocked_and_how_to_test_http():
    text = render_prompt("red", ctx(adapter="codex")).text
    assert "sockets are blocked" in text and "loopback" in text
    assert "in-process" in text and "BaseHTTPRequestHandler" in text
    assert "gate run" in text  # the gate run, not this step, may use loopback


def test_the_contract_asks_for_the_real_server_test_when_the_task_does_not_hide_it_behind_a_socketpair():
    """W-D3: five units, no real-server test. The contract told Codex to avoid servers; now it says to write the test
    the task or design asks for, with bounded reads, and never to stand a socketpair in for it."""
    text = render_prompt("red", ctx(adapter="codex")).text
    assert "WRITE that test" in text and "port 0" in text and "timeout" in text
    assert "never instead of it" in text and "in place of a requested server" in text
    assert "Test an HTTP scenario in-process" not in text


def test_other_adapters_do_not_get_a_codex_limit():
    assert "sockets are blocked" not in render_prompt("red", ctx(adapter="claude-code")).text


def test_a_criterion_that_mentions_http_carries_the_sentence_in_every_phase():
    for role in ("red", "green", "single"):
        assert "sockets are blocked" in render_prompt(role, ctx(adapter="codex")).text
