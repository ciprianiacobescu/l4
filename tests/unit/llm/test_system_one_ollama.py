"""The `ollama` System-One engine (Ollama >= 0.35.0 `POST /v1/systemone`): keyless, base_url required, the request body
checked against the 64 KiB limit before it is sent, a probe of `/api/version` and `/api/tags`, and fallback to the
next profile when the Mac is down."""

import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from l4.agents.factory import RoleUnavailable
from l4.config.preflight import preflight_run_config
from l4.config.schema import L4Config, Profile
from l4.llm.system_one import (
    ENGINES,
    OLLAMA_MAX_BODY,
    Question,
    SystemOneBackend,
    SystemOneBadAnswer,
    SystemOneTooLarge,
    SystemOneUnavailable,
    open_s1_backend,
    open_s1_profile,
)
from l4.redact import Redactor

from .test_agent_judge_roles import app
from .test_agent_judge_roles import cfg as agent_cfg
from .test_preflight_m15 import s1_profile
from .test_system_one import cfg

URL = "http://mac.test:11434"
PROFILE = {"backend": "system-one", "engine": "ollama", "model": "tev1", "base_url": URL}
NOUL = {"p": Question("noul", "Did the tests pass?", {"true": "passed", "false": "failed"})}


def server(version="0.40.0", tags=("tev1:latest", "gpt-oss:20b"), seen=None, systemone=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        path = request.url.path
        if path == "/api/version":
            return httpx.Response(200, json={"version": version})
        if path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": n, "model": n} for n in tags]})
        if path == "/v1/systemone" and systemone is not None:
            return systemone(request)
        return httpx.Response(404)

    return handler


def client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def reply(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={
        "model": "tev1", "answers": {"p": {"type": "noul", "noul": 0.9972}},
        "usage": {"input_tokens": 355, "output_tokens": 0}, "prompt_eval_cached_count": 114,
    })  # fmt: skip


def backend(handler, tmp_path: Path, profile=PROFILE) -> SystemOneBackend:
    """Probed through the fake host, then asking through the same fake transport (nothing leaves the process)."""
    opened = open_s1_backend(
        cfg({"mac": profile}, ["mac"]), environ={}, client=client(handler), redactor=Redactor({}),
        log_path=tmp_path / "s1.jsonl",
    )
    opened._transport = httpx.MockTransport(handler)
    return opened


# --- config --------------------------------------------------------------------------------------------------------


def test_ollama_is_an_engine():
    assert "ollama" in ENGINES


def test_the_profile_block_loads_and_needs_a_base_url():
    assert Profile.model_validate(PROFILE).base_url == URL
    with pytest.raises(ValidationError, match="base_url"):
        Profile.model_validate({"backend": "system-one", "engine": "ollama", "model": "tev1"})


def test_an_ollama_profile_takes_no_key():
    with pytest.raises(ValidationError, match="api_key_env"):
        Profile.model_validate({**PROFILE, "api_key_env": "OLLAMA_KEY"})


@pytest.mark.parametrize("url", ["mac.test:11434", "ftp://mac.test", "http://u:p@mac.test", "http://mac.test/?k=v"])
def test_the_base_url_must_be_an_http_origin_without_credentials(url):
    with pytest.raises(ValidationError, match="base_url"):
        Profile.model_validate({**PROFILE, "base_url": url})


def test_preflight_accepts_the_profile(tmp_path):
    fields = {k: v for k, v in PROFILE.items() if k != "backend"}
    preflight_run_config(app(tmp_path), agent_cfg(**s1_profile(**fields)))  # raises L4Exit when refused


def test_the_state_budget_is_the_configured_one_not_laya_s_window():
    s1 = L4Config().verifier.s1
    assert s1.budget("ollama") == s1.max_state_tokens > s1.budget("laya-local")


# --- the wire ------------------------------------------------------------------------------------------------------


def test_a_request_is_keyless_and_typed_as_ollama_wants_it(tmp_path):
    seen: list[httpx.Request] = []
    questions = {
        "p": Question("noul", "Did the tests pass?", {"true": "passed", "false": "failed"}),
        "c": Question("choice", "Kind?", ["report", "question"]),
        "s": Question("score", "How positive?", {"0": "negative", "1": "neutral", "2": "positive"}),
    }
    with backend(server(seen=seen, systemone=reply), tmp_path) as b:
        b.query("The build passed.", questions)
    (post,) = [r for r in seen if r.url.path == "/v1/systemone"]
    assert "authorization" not in {k.lower() for r in seen for k in r.headers}
    body = json.loads(post.content)
    assert body["model"] == "tev1" and body["state"] == "The build passed."
    assert body["questions"]["c"]["criteria"] == {"report": None, "question": None}  # a bare label per option
    assert body["questions"]["s"]["criteria"] == ["negative", "neutral", "positive"]  # score levels are an array
    assert body["questions"]["p"]["criteria"] == {"true": "passed", "false": "failed"}


def test_the_ollama_answers_map_to_the_typed_answers(tmp_path):
    def answer(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "model": "tev1", "usage": {"input_tokens": 355, "output_tokens": 0},
            "answers": {
                "p": {"type": "noul", "noul": 0.9972},
                "c": {"type": "choice", "choice": "report", "confidence": 0.89,
                      "probabilities": {"report": 0.986, "question": 0.014}},
                "s": {"type": "score", "score": 1.81, "confidence": 0.55, "legend": {"0": "n", "1": "u", "2": "p"},
                      "probabilities": {"0": 0.0023, "1": 0.182, "2": 0.8157}},
            },
        })  # fmt: skip

    questions = {
        "p": Question("noul", "q"), "c": Question("choice", "q", {"report": "r", "question": "q"}),
        "s": Question("score", "q", ["n", "u", "p"]),
    }  # fmt: skip
    with backend(server(systemone=answer), tmp_path) as b:
        typed = b.ask_typed("state", questions)
    assert typed["p"].p_true == pytest.approx(0.9972) and typed["p"].predicted is True
    assert (typed["c"].choice, typed["c"].predicted) == ("report", "report")
    assert typed["s"].score == pytest.approx(1.81) and typed["s"].predicted == 2


def test_the_served_model_and_engine_are_recorded(tmp_path):
    log = tmp_path / "s1.jsonl"
    with backend(server(systemone=reply), tmp_path) as b:
        assert b.engine == "ollama" and b.model == "tev1"
        assert b.query("s", NOUL).model == "tev1:latest"  # the name the host resolved, not the alias asked for
        assert b.server_version == "ollama 0.40.0"
    row = json.loads(log.read_text().splitlines()[0])
    assert row["engine"] == "ollama" and row["response"]["model"] == "tev1:latest"


def test_a_key_is_never_sent_or_logged_even_if_given(tmp_path):
    with pytest.raises(ValueError, match="no key"):
        SystemOneBackend("ollama", model="tev1", base_url=URL, api_key="k" * 20, redactor=Redactor({}))


# --- the size limit ------------------------------------------------------------------------------------------------


def test_an_oversize_request_is_not_sent_and_is_unavailable(tmp_path):
    seen: list[httpx.Request] = []
    with backend(server(seen=seen, systemone=reply), tmp_path) as b, pytest.raises(
        SystemOneUnavailable, match="unavailable: input too large"
    ):
        b.query("x" * OLLAMA_MAX_BODY, NOUL)
    assert not [r for r in seen if r.url.path == "/v1/systemone"]  # never sent, never cut
    row = json.loads((tmp_path / "s1.jsonl").read_text().splitlines()[-1])
    assert "input too large" in row["error"] and row["response"] is None


def test_it_is_a_per_question_error_not_a_dead_engine(tmp_path):
    with backend(server(systemone=reply), tmp_path) as b:
        with pytest.raises(SystemOneBadAnswer):
            b.query("x" * OLLAMA_MAX_BODY, NOUL)
        assert b.query("small", NOUL).answers["p"]["noul"] == pytest.approx(0.9972)  # the next question is fine


def real_ollama(request: httpx.Request) -> httpx.Response:
    """The limit as measured on Ollama 0.40.0 (live, 2026-10-07): "text and schema" 64 KiB, which is the body's UTF-8
    bytes plus 16 for every `noul` question without criteria. Over it the server answers 413."""
    body = json.loads(request.content)
    extra = sum(16 for q in body["questions"].values() if q["type"] == "noul" and "criteria" not in q)
    if len(request.content) + extra > OLLAMA_MAX_BODY:
        return httpx.Response(413, json={"error": "text and schema must not exceed 64 KiB"})
    return reply(request)


@pytest.mark.parametrize(
    "questions",
    [
        NOUL,
        {"p": Question("noul", "q"), "r": Question("noul", "q"), "s": Question("noul", "é" * 40)},
        {"p": Question("choice", "q", {"a": "x", "b": "y"}), "s": Question("score", "q", ["lo", "hi"])},
    ],
)
@pytest.mark.parametrize("glyph", ["a", "é", "€"])
def test_no_request_is_ever_answered_413(tmp_path, questions, glyph):
    """Sweep the state size across the whole edge: each request is either sent and accepted or refused here."""
    handler = server(systemone=real_ollama)
    width = len(glyph.encode())
    sent = refused = 0
    with backend(handler, tmp_path) as b:
        b.query("", questions)
        empty = {"state": "", "model": "tev1", "questions": {i: q.wire_ollama() for i, q in questions.items()}}
        overhead = len(json.dumps(empty))
        edge = OLLAMA_MAX_BODY - overhead  # state bytes at which the body alone reaches the limit
        for chars in range((edge - 400) // width, (edge + 200) // width, max(1, 12 // width)):
            try:
                b.query(glyph * chars, questions)
                sent += 1
            except SystemOneTooLarge as exc:
                assert "unavailable: input too large" in str(exc) and "HTTP 413" not in str(exc)  # refused here
                refused += 1
    assert sent > 10 and refused > 10  # the sweep crosses the edge: both sides are exercised


def test_the_refusal_comes_only_a_little_early(tmp_path):
    """The margin is a few bytes, not a cut of what fits: a request 200 bytes under the limit is sent."""
    seen: list[httpx.Request] = []
    handler = server(seen=seen, systemone=real_ollama)
    with backend(handler, tmp_path) as b:
        b.query("é", NOUL)
        (probe_post,) = [r for r in seen if r.url.path == "/v1/systemone"]
        room = OLLAMA_MAX_BODY - len(probe_post.content) - 200
        assert b.query("a" * room, NOUL).answers["p"]["noul"] > 0.5


def test_a_413_from_the_server_is_the_same_error(tmp_path):
    handler = server(systemone=lambda r: httpx.Response(413, json={"error": "big"}))
    with backend(handler, tmp_path) as b, pytest.raises(SystemOneUnavailable, match="input too large"):
        b.query("s", NOUL)


def test_a_prompt_over_the_loaded_context_is_the_same_per_question_error(tmp_path):
    """Live, tev1 on 0.40.0: HTTP 400 `prompt 0 has 8100 tokens; expected 1-2048 (input is never truncated)`."""
    error = {"error": "prompt 0 has 8100 tokens; expected 1-2048 (input is never truncated)"}
    handler = server(systemone=lambda r: httpx.Response(400, json=error))
    with backend(handler, tmp_path) as b, pytest.raises(SystemOneTooLarge, match="unavailable: input too large"):
        b.query("s", NOUL)


def test_any_other_400_is_a_plain_unavailable_that_does_not_echo_the_body(tmp_path):
    error = {"error": "registry.ollama.ai/library/x does not support decision SECRET-TEXT"}
    handler = server(systemone=lambda r: httpx.Response(400, json=error))
    with backend(handler, tmp_path) as b, pytest.raises(SystemOneUnavailable, match="HTTP 400") as err:
        b.query("s", NOUL)
    assert not isinstance(err.value, SystemOneBadAnswer) and "SECRET-TEXT" not in str(err.value)


def test_a_404_on_the_request_says_how_to_pull_the_model(tmp_path):
    handler = server(systemone=lambda r: httpx.Response(404, json={"error": "nope"}))
    with backend(handler, tmp_path) as b, pytest.raises(SystemOneUnavailable, match="ollama pull tev1"):
        b.query("s", NOUL)


# --- the probe -----------------------------------------------------------------------------------------------------


def probe(handler, profile=PROFILE):
    return open_s1_backend(cfg({"mac": profile}, ["mac"]), environ={}, client=client(handler), redactor=Redactor({}))


def test_a_ready_host_probes_usable_for_a_bare_model_name():
    assert probe(server()).engine == "ollama"
    assert probe(server(tags=("tev1",))).engine == "ollama"  # an exact tag matches too


def test_a_model_that_is_not_pulled_gives_the_remedy():
    with pytest.raises(RoleUnavailable, match=r"ollama pull tev1"):
        probe(server(tags=("gpt-oss:20b",)))


def test_a_different_tag_is_not_the_model():
    with pytest.raises(RoleUnavailable, match=r"ollama pull tev1"):
        probe(server(tags=("tev1-other:latest",)))


def test_an_old_ollama_is_unavailable():
    with pytest.raises(RoleUnavailable, match=r"0\.34\.9.*0\.35\.0"):
        probe(server(version="0.34.9"))
    assert probe(server(version="0.35.0")).engine == "ollama"


def test_an_unreadable_version_is_unavailable():
    with pytest.raises(RoleUnavailable, match="version"):
        probe(server(version="soon"))


def test_a_down_mac_is_unavailable_and_the_chain_falls_back(tmp_path):
    def refuse(request: httpx.Request) -> httpx.Response:
        if request.url.host == "mac.test":
            raise httpx.ConnectError("no route")
        return httpx.Response(200)

    with pytest.raises(RoleUnavailable, match="unreachable"):
        probe(refuse)
    profiles = {
        "mac": PROFILE, "next": {"backend": "system-one", "engine": "remote", "base_url": "http://other.test"},
    }
    chosen = open_s1_backend(
        cfg(profiles, ["mac", "next"]), environ={}, client=client(refuse), redactor=Redactor({})
    )
    assert chosen.engine == "remote"


def test_open_s1_profile_probes_the_same_way():
    config = cfg({"mac": PROFILE}, ["mac"])
    assert open_s1_profile(config, "mac", environ={}, client=client(server()), redactor=Redactor({})).engine == "ollama"
    with pytest.raises(RoleUnavailable, match="ollama pull"):
        open_s1_profile(config, "mac", environ={}, client=client(server(tags=())), redactor=Redactor({}))
