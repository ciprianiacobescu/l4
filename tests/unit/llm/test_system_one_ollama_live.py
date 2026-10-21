"""The `ollama` engine against the maintainer's real Mac (`L4_LIVE=1`; `L4_OLLAMA_URL` overrides the LAN address;
skips when the host or `tev1` is not there)."""

import os

import httpx
import pytest

from l4.llm.system_one import OLLAMA_MAX_BODY, Question, SystemOneBackend, SystemOneTooLarge
from l4.redact import Redactor

pytestmark = pytest.mark.live
URL = os.environ.get("L4_OLLAMA_URL", "http://192.0.2.10:11434")


@pytest.mark.skipif(os.environ.get("L4_LIVE") != "1", reason="needs the maintainer's Mac and L4_LIVE=1")
def test_the_mac_answers_typed_questions():
    try:
        tags = httpx.get(f"{URL}/api/tags", timeout=10).json()["models"]
    except (httpx.HTTPError, ValueError, KeyError):
        pytest.skip(f"{URL} is not reachable")
    if not any(m.get("name") in ("tev1", "tev1:latest") for m in tags):
        pytest.skip("tev1 is not pulled on the host")
    questions = {
        "p": Question("noul", "Did the tests pass?", {"true": "the tests passed", "false": "the tests failed"}),
        "c": Question("choice", "What kind of message is it?", {"report": "a status report", "ask": "a question"}),
        "s": Question("score", "How positive is the message?", ["negative", "neutral", "positive"]),
    }
    with SystemOneBackend("ollama", model="tev1", base_url=URL, redactor=Redactor({}), timeout_s=120) as backend:
        typed = backend.ask_typed("The build passed all 40 tests.", questions)
    assert typed["p"].p_true is not None and typed["p"].p_true > 0.5
    assert typed["c"].choice == "report" and set(typed["c"].probabilities or {}) == {"report", "ask"}
    assert typed["s"].score is not None and 0.0 <= typed["s"].score <= 2.0


@pytest.mark.skipif(os.environ.get("L4_LIVE") != "1", reason="needs the maintainer's Mac and L4_LIVE=1")
def test_the_mac_refuses_nothing_the_engine_sent_and_the_engine_never_sends_what_is_too_big():
    try:
        httpx.get(f"{URL}/api/version", timeout=10).raise_for_status()
    except httpx.HTTPError:
        pytest.skip(f"{URL} is not reachable")
    ask = {"p": Question("noul", "Is this text about tests?")}
    with SystemOneBackend("ollama", model="tev1", base_url=URL, redactor=Redactor({}), timeout_s=120) as backend:
        with pytest.raises(SystemOneTooLarge):  # over the 64 KiB limit: refused before sending
            backend.query("word " * (OLLAMA_MAX_BODY // 5 + 100), ask)
        with pytest.raises(SystemOneTooLarge):  # under 64 KiB but over the loaded context (2048 tokens on Tev1)
            backend.query("word " * 8000, ask)
        assert 0.0 <= backend.ask("The tests passed.", ask)["p"] <= 1.0  # and the engine is still up
