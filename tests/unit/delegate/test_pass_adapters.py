"""The delegate pass on the opencode and kiro-cli adapters (L4-DLG-015, 016, 017; SCN-DLG-56, 57, 60, 61, 63, 101,
102, 103): the pass reads what a run of the CLI would have given it, through each adapter's real `parse`."""

from datetime import timedelta

from l4.agents.base import ProbeResult

from ..agents.cli_streams import (
    REFUSED,
    kiro_call,
    kiro_chunk,
    kiro_stream,
    oc_finish,
    oc_text,
    oc_tool,
)
from .cli_adapters import KIRO_PROFILE, OPENCODE_PROFILE, ZEN_PROFILE, ScriptedKiro, ScriptedOpenCode
from .conftest import blocked, reply
from .test_pass import QUESTIONS, results, status_of


def text_of(question: str = "Q-001", decision: str = "answer", **over) -> str:
    import json

    return json.dumps(reply(question, decision, **over).structured)


def opencode_answer(text: str | None = None) -> list[str]:
    return [
        oc_tool("read"),
        oc_finish("tool-calls"),
        oc_text("The file shows it.\n" + (text or text_of())),
        oc_finish(),
    ]


def kiro_answer(text: str | None = None) -> list[str]:
    body = "The file shows it.\n" + (text or text_of())
    return kiro_stream(kiro_call("read"), kiro_chunk(body), final=body)


def test_an_opencode_delegate_answers_in_its_last_message(delegate_run, install_cli):  # SCN-DLG-56
    adapter = install_cli("opencode", ScriptedOpenCode([opencode_answer()]))
    run = delegate_run([blocked("technical")], profiles={"dlg": OPENCODE_PROFILE})
    assert status_of(run) == "answered" and run.code == 11
    (request,) = adapter.requests
    assert "Do not call any tool" not in request.prompt
    assert "Read the files you need" in request.prompt and request.prompt.rstrip().endswith("}")
    assert request.permission_policy.mode == "read_only"
    (result,) = results(run)
    assert (result["status"], result["cli"], result["profile"]) == ("answered", "opencode", "dlg")
    assert run.events("question.answered")[0]["by"] == "delegate"
    published = [p for p in (run.tdd.repo / ".l4-out").rglob("*.prompt.md") if "delegate" in p.name]
    assert published and all("Read the files you need" not in p.read_text() for p in published)  # the suffix stays out
    assert all(p.read_text().rstrip().endswith("}") is False for p in published)


def test_a_tool_outside_the_read_set_defers_then_escalates(delegate_run, install_cli, fake_clock):  # SCN-DLG-57
    shell = kiro_stream(kiro_call("shell"), kiro_chunk(text_of()), final=text_of())
    install_cli("kiro-cli", ScriptedKiro([shell, shell]))
    delegate = {"max_attempts_per_question": 2}
    first = delegate_run([blocked("technical")], profiles={"dlg": KIRO_PROFILE}, delegate=delegate)
    (deferral,) = results(first)
    assert deferral["status"] == "deferred" and first.code == 11
    assert status_of(first) == "open" and "Answered by" not in first.pushed(QUESTIONS)
    fake_clock.advance(timedelta(minutes=10))
    second = delegate_run([], profiles={"dlg": KIRO_PROFILE}, delegate=delegate)
    last = results(second)[-1]
    assert (last["status"], last["reason"]) == ("escalated", "delegate attempts used (2)")
    assert second.code == 11


def test_a_refused_call_then_a_valid_reply_is_kept(delegate_run, install_cli):  # SCN-DLG-101
    lines = [oc_tool("bash", "error", REFUSED), oc_finish("tool-calls"), oc_text(text_of()), oc_finish()]
    install_cli("opencode", ScriptedOpenCode([lines]))
    run = delegate_run([blocked("technical")], profiles={"dlg": ZEN_PROFILE_FREE})
    assert status_of(run) == "answered"


ZEN_PROFILE_FREE = ZEN_PROFILE


def test_a_refused_call_with_no_valid_reply_defers(delegate_run, install_cli):  # SCN-DLG-102
    lines = [oc_tool("bash", "error", REFUSED), oc_finish("tool-calls"), oc_text("I could not look."), oc_finish()]
    install_cli("opencode", ScriptedOpenCode([lines]))
    run = delegate_run([blocked("technical")], profiles={"dlg": ZEN_PROFILE_FREE})
    (result,) = results(run)
    assert result["status"] == "deferred" and status_of(run) == "open"


def test_opencode_v2_escalates_and_does_not_defer(delegate_run, install_cli):  # SCN-DLG-60
    why = "opencode 2.0.32 is OpenCode v2; this profile runs v1 (opencode-ai 1.x): install opencode-ai@1.18.33"
    probes = {"binary": ProbeResult("binary", False, reason=why, failure_class="unsupported_version")}
    adapter = install_cli("opencode", ScriptedOpenCode([], probes=probes))
    run = delegate_run([blocked("technical")], profiles={"dlg": OPENCODE_PROFILE})
    assert adapter.requests == []  # no call was made
    (result,) = results(run)
    assert result["status"] == "escalated" and result["reason"].startswith("no delegate profile is usable:")
    assert "OpenCode v2" in result["reason"]
    assert not [e for e in results(run) if e["status"] == "deferred"] and run.code == 11


def test_a_kiro_turn_with_an_unknown_tool_defers(delegate_run, install_cli):  # SCN-DLG-103
    lines = kiro_stream(kiro_call("read"), kiro_call("web_search"), kiro_chunk(text_of()), final=text_of())
    install_cli("kiro-cli", ScriptedKiro([lines]))
    run = delegate_run([blocked("technical")], profiles={"dlg": KIRO_PROFILE})
    (result,) = results(run)
    assert result["status"] == "deferred" and status_of(run) == "open"


def test_a_model_mismatch_escalates(delegate_run, install_cli):  # SCN-DLG-63
    install_cli("kiro-cli", ScriptedKiro([kiro_answer()], served="claude-haiku-4.5"))
    run = delegate_run([blocked("technical")], profiles={"dlg": KIRO_PROFILE})
    (result,) = results(run)
    assert result["status"] == "discarded" and result["called"] is True
    assert result["reason"] == "kiro-cli served claude-haiku-4.5, the profile names claude-sonnet-4.5"
    assert status_of(run) == "open" and run.code == 11 and not run.events("question.answered")
    assert "Escalated by:** the delegate" in run.pushed(QUESTIONS)


def test_a_kiro_delegate_answers_and_its_served_model_is_recorded(delegate_run, install_cli):  # SCN-DLG-61
    adapter = install_cli("kiro-cli", ScriptedKiro([kiro_answer()], served="claude-sonnet-4.5"))
    run = delegate_run([blocked("technical")], profiles={"dlg": KIRO_PROFILE})
    assert status_of(run) == "answered"
    (result,) = results(run)
    assert (result["status"], result["cli"], result["model"]) == ("answered", "kiro-cli", "claude-sonnet-4.5")
    assert adapter.requests[0].permission_policy.mode == "read_only"
