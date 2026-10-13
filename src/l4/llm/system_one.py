"""The System-One backend (SPEC L4-FAC-004): the TypeSafe wire protocol, `laya-serve` as a context manager, and the
selection of a usable `backend: system-one` profile (M15-G3).

Wire: `POST <base_url>/v1/systemone` with `{state, model, questions: {<id>: {type: noul|choice|score, instructions,
criteria?}}}`; the reply is `{model, answers: {<id>: {type, noul | choice | score, ...}}, usage}`
[V, docs.typesafe.ai/api].
Laya's `laya-serve` speaks it unchanged [V, research/03], and `GET /health` is its liveness route [V, laya 0.3.24].

Engines (D7): `laya-local` starts `laya-serve` on a free localhost port around the S1 work and stops it afterwards, so
it is never resident together with Chromium or an agent; `jev` is the hosted API; `remote` is any TypeSafe-wire server
at `base_url` (Laya on the maintainer's Mac). Every request and reply goes to `.l4-out/logs/system-one.jsonl` for
calibration (L4-VER-008), each line tagged with its `engine`: TypeSafe's MCA 2.3(b) forbids using Jev output to train
or distil a model, so a Jev line is never a training label for Laya (score both engines against the harness's own
labels).
The API key is read from the environment by name and is never logged.
The clarifier's judge over a backend is `l4.clarifier.s1_decisions.SystemOneDecisions`.
M1: clarification-loop 2.2 (the model's own tokenizer for the state budget).
"""

import contextlib
import dataclasses
import json
import logging
import os
import re
import shlex
import signal
import socket
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import httpx

from l4.agents.base import EventSink
from l4.agents.factory import RoleUnavailable
from l4.config.defaults import resolve_executable
from l4.config.schema import L4Config, Profile
from l4.llm.s1_checkpoint import (
    GATE_PROBLEMS,
    CheckpointGateFailed,
    checkpoint_problem,
    is_checkpoint_path,
    overlay_home,
)
from l4.redact import Redactor

log = logging.getLogger("l4.system_one")

Engine = Literal["laya-local", "jev", "remote", "ollama"]
ENGINES: tuple[Engine, ...] = ("laya-local", "jev", "remote", "ollama")
QuestionKind = Literal["noul", "choice", "score"]
JEV_URL = "https://api.typesafe.ai"
JEV_MODEL = "jev-latest"
LAYA_MODEL = "typed-decisions"
OLLAMA_MODEL = "tev1"
OLLAMA_MIN_VERSION = (0, 35, 0)  # the first Ollama with `POST /v1/systemone` [V, docs.ollama.com/api/systemone]
OLLAMA_MAX_BODY = 64 * 1024  # "text and schema" of a request without images: a bigger one is a 413, never sent
OLLAMA_MARGIN = 64  # the server counts text and schema, not the raw body: measured on Ollama 0.40.0 it is the body
OLLAMA_MARGIN_PER_QUESTION = 32  # plus 16 bytes per `noul` question without criteria (its default descriptions),
# and nothing more for choice, score or criteria that are given; the margins are twice that, so a request is
# refused a few bytes early rather than answered 413 [V, live probe 2026-10-07]
LAYA_REPO = "convaiinnovations/laya"
LAYA_DIST = "laya"
LAYA_THREADS = 2  # pinned with OMP_NUM_THREADS: byte-identical answers across runs [V, research/03]
READY_TIMEOUT_S = 120.0
STOP_GRACE_S = 10.0
HEALTH_TIMEOUT_S = 5.0
CALL_TIMEOUT_S = 30.0


class SystemOneUnavailable(Exception):
    """The server did not answer usefully: down, refused, timed out, rate-limited, unauthorised or malformed. The
    caller records `s1: unavailable` and goes on without System One (L4-AVL-010); `detail` never holds the key."""


class SystemOneBadAnswer(SystemOneUnavailable):
    """The server is up but its reply is not a usable answer to this question: the next question may still be fine."""


class SystemOneTooLarge(SystemOneBadAnswer):
    """This request is over the server's body limit: refused before sending, never cut. The next question may fit."""


@dataclass(frozen=True)
class Question:
    kind: QuestionKind
    instructions: str | Mapping[str, Any]
    criteria: Mapping[str, Any] | Sequence[Any] | None = None  # noul: {true, false}; choice: option map; score: levels

    def wire(self) -> dict[str, Any]:
        body: dict[str, Any] = {"type": self.kind, "instructions": self.instructions}
        if self.criteria is not None:
            body["criteria"] = self.criteria
        return body

    def wire_ollama(self) -> dict[str, Any]:
        """Ollama's shape of the same question: `choice` criteria are an object (a bare list becomes bare labels),
        `score` criteria an array of level descriptions ordered from 0 (an object keyed 0..n-1 is ordered)."""
        body = self.wire()
        criteria = self.criteria
        if self.kind == "choice" and criteria is not None and not isinstance(criteria, Mapping):
            body["criteria"] = {str(c): None for c in criteria}
        elif self.kind == "score" and isinstance(criteria, Mapping):
            try:
                order = sorted(criteria, key=lambda k: int(str(k)))
            except ValueError:
                raise SystemOneBadAnswer("score levels must be numbered 0..n-1 for ollama") from None
            if [int(str(k)) for k in order] != list(range(len(order))):
                raise SystemOneBadAnswer("score levels must be numbered 0..n-1 for ollama")
            body["criteria"] = [str(criteria[k]) for k in order]
        return body


@dataclass(frozen=True)
class Reply:
    model: str
    answers: dict[str, dict[str, Any]]
    usage: dict[str, Any] = field(default_factory=dict)  # as the server gave it: laya adds `truncated: false` etc.


@dataclass(frozen=True)
class Answer:
    """One typed answer (M16-G6). `noul`: `p_true`. `choice`: `choice` and `probabilities` over the options.
    `score`: `score` (the probability-weighted level) and `probabilities` over the levels. `confidence` is the
    server's own number and is NOT comparable across engines (Laya's is entropy-based); `answer_confidence` is."""

    kind: QuestionKind
    p_true: float | None = None
    choice: str | None = None
    score: float | None = None
    probabilities: Mapping[str, float] | None = None
    confidence: float | None = None

    @property
    def answer_confidence(self) -> float:
        """Probability the engine puts on its own answer: max(p, 1-p) for noul, the largest probability otherwise."""
        if self.p_true is not None:
            return max(self.p_true, 1.0 - self.p_true)
        if self.probabilities:
            return max(self.probabilities.values())
        return self.confidence if self.confidence is not None else 0.0

    @property
    def predicted(self) -> bool | str | int | None:
        """The label this answer stands for: p>=0.5 for noul, the option for choice, the likeliest level for score."""
        if self.p_true is not None:
            return self.p_true >= 0.5
        if self.kind == "choice":
            return self.choice
        if self.probabilities:
            return int(max(self.probabilities, key=lambda k: self.probabilities[k]))
        return None if self.score is None else round(self.score)

    def to_json(self) -> dict[str, Any]:
        return {k: v for k, v in dataclasses.asdict(self).items() if v is not None}

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "Answer":
        return cls(
            data["kind"], data.get("p_true"), data.get("choice"), data.get("score"),
            data.get("probabilities"), data.get("confidence"),
        )  # fmt: skip


TYPED_SUM_TOLERANCE = 0.05  # the API rounds to 0.01


def _number(value: object, what: str, low: float = 0.0, high: float = 1.0) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not low <= float(value) <= high:
        raise SystemOneBadAnswer(f"{what} is not a number in {low:g}..{high:g}")
    return float(value)


def _options(question: Question) -> list[str]:
    """Choice: the option names. Score: the level keys; a list of level descriptions means levels 0..n-1."""
    criteria = question.criteria
    if isinstance(criteria, Mapping):
        return [str(k) for k in criteria]
    if question.kind == "score":
        return [str(i) for i in range(len(criteria or ()))]
    return [str(c) for c in criteria or ()]


def _probabilities(raw: object, allowed: Sequence[str], qid: str) -> dict[str, float]:
    if not isinstance(raw, dict) or not raw or not set(map(str, raw)) <= set(allowed):
        raise SystemOneBadAnswer(f"probabilities of question {qid} do not match its options")
    probs = {str(k): _number(v, f"probability of question {qid}") for k, v in raw.items()}
    if abs(sum(probs.values()) - 1.0) > TYPED_SUM_TOLERANCE:
        raise SystemOneBadAnswer(f"probabilities of question {qid} do not sum to 1")
    return probs


def parse_typed(reply: Reply, questions: Mapping[str, Question]) -> dict[str, Answer]:
    """Every question answered with its own kind, and every value inside its range, or `SystemOneBadAnswer`."""
    out: dict[str, Answer] = {}
    for qid, question in questions.items():
        raw = reply.answers.get(qid)
        if not isinstance(raw, dict) or raw.get("type") != question.kind:
            raise SystemOneBadAnswer(f"no {question.kind} answer for question {qid}")
        confidence = raw.get("confidence")
        confidence = None if confidence is None else _number(confidence, f"confidence of question {qid}")
        options = _options(question)
        if question.kind == "noul":
            out[qid] = Answer("noul", p_true=_number(raw.get("noul"), f"noul answer for question {qid}"))
        elif question.kind == "choice":
            choice = raw.get("choice")
            if not isinstance(choice, str) or (options and choice not in options):
                raise SystemOneBadAnswer(f"choice answer for question {qid} is not one of its options")
            probs = _probabilities(raw.get("probabilities"), options or [choice], qid)
            out[qid] = Answer("choice", choice=choice, probabilities=probs, confidence=confidence)
        else:
            levels = [float(o) for o in options if o.lstrip("-").replace(".", "", 1).isdigit()]
            low, high = (min(levels), max(levels)) if levels else (float("-inf"), float("inf"))
            score = _number(raw.get("score"), f"score answer for question {qid}", low, high)
            probs = None
            if raw.get("probabilities") is not None:
                probs = _probabilities(raw["probabilities"], options or list(map(str, raw["probabilities"])), qid)
            out[qid] = Answer("score", score=score, probabilities=probs, confidence=confidence)
    return out


# --- laya-serve --------------------------------------------------------------------------------------------------


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def laya_env(environ: Mapping[str, str], port: int, model: str, threads: int) -> dict[str, str]:
    """The environment of `laya-serve`: built, never inherited (a job's tokens must not reach a third-party server)."""
    env = {name: environ[name] for name in ("PATH", "HOME", "LANG", "TMPDIR", "HF_HOME") if environ.get(name)}
    env.update(
        LAYA_HOST="127.0.0.1", LAYA_PORT=str(port), LAYA_MODELS=model, LAYA_PRELOAD="1", LAYA_DEVICE="cpu",
        LAYA_MAX_LOADED="1", LAYA_THREADS=str(threads), OMP_NUM_THREADS=str(threads), HF_HUB_OFFLINE="1",
    )  # fmt: skip
    return env


def _script_interpreter(path: str) -> list[str]:
    """The interpreter argv a console script names: its `#!` line, or, for the `#!/bin/sh` trampoline that uv and pip
    write when that path is long or has spaces, the program of the `exec` line that follows. [] when unknown."""
    with open(path, "rb") as handle:
        first = handle.readline(300).decode("utf-8", "replace").strip()
        second = handle.readline(1000).decode("utf-8", "replace").strip()
    if not first.startswith("#!"):
        return []
    argv = first[2:].split()
    if argv[:1] == ["/bin/sh"] and second.startswith("'''exec'"):
        try:
            words = shlex.split(second)
        except ValueError:
            return []
        return words[1:2]
    return argv


def _minimal_env(environ: Mapping[str, str]) -> dict[str, str]:
    """What a version probe may see: the lookup path and locale, never a job token or API key."""
    return {k: environ[k] for k in ("PATH", "HOME", "LANG") if k in environ}


def laya_version(argv0: str, environ: Mapping[str, str], dist: str = LAYA_DIST) -> str:
    """The installed `laya` version, read by the interpreter the `laya-serve` script names (the uv tool's own): ""
    when it cannot be told. Laya answers `model: laya-rl-agent` whatever it loaded, so a calibration row needs this
    to tell 0.3.24 from 0.3.26."""
    try:
        interpreter = _script_interpreter(argv0)
        if not interpreter:
            return ""
        code = f"from importlib.metadata import version; print(version({dist!r}))"
        done = subprocess.run(  # noqa: S603 - argv list; the interpreter is the one the installed script names
            [*interpreter, "-c", code], env=_minimal_env(environ), capture_output=True, text=True, timeout=15,
            check=False,
        )  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


class LayaServe:
    """`with LayaServe(...) as base_url:` runs `laya-serve` on a free localhost port. It is always stopped (SIGTERM to
    its process group, SIGKILL after a grace period) and killed when it never gets ready."""

    def __init__(
        self,
        argv: Sequence[str],
        environ: Mapping[str, str],
        *,
        model: str = LAYA_MODEL,
        threads: int = LAYA_THREADS,
        ready_timeout_s: float = READY_TIMEOUT_S,
        stop_grace_s: float = STOP_GRACE_S,
        port: Callable[[], int] = free_port,
        client: httpx.Client | None = None,
        log_path: Path | None = None,
        redactor: Redactor | None = None,
    ) -> None:
        self._argv, self._environ, self._model, self._threads = list(argv), environ, model, threads
        self._redactor = redactor
        self._ready_timeout_s, self._stop_grace_s, self._port = ready_timeout_s, stop_grace_s, port
        self._client = client
        self._log_path = log_path
        self._proc: subprocess.Popen[bytes] | None = None
        self.version = ""  # of the laya package, set when the server is up

    def __enter__(self) -> str:
        port = self._port()
        env = laya_env(self._environ, port, self._model, self._threads)
        sink: Any = subprocess.DEVNULL
        if self._log_path is not None:
            try:
                self._log_path.parent.mkdir(parents=True, exist_ok=True)
                sink = self._log_path.open("wb")
            except OSError as exc:  # S1 never stops a round: an unwritable log directory is an unusable server
                raise SystemOneUnavailable(f"laya-serve log cannot be opened ({type(exc).__name__})") from None
        try:
            self._proc = subprocess.Popen(  # noqa: S603 - argv list, harness-resolved executable
                self._argv, env=env, stdin=subprocess.DEVNULL, stdout=sink, stderr=subprocess.STDOUT,
                start_new_session=True,
            )  # fmt: skip
        except OSError as exc:
            raise SystemOneUnavailable(f"laya-serve cannot start ({type(exc).__name__})") from None
        finally:
            if sink is not subprocess.DEVNULL:
                sink.close()
        base_url = f"http://127.0.0.1:{port}"
        try:
            self._wait_ready(base_url)
        except BaseException:
            self.stop()
            raise
        self.version = laya_version(self._argv[0], self._environ)
        pid = self._proc.pid if self._proc is not None else 0
        log.info("laya-serve started: pid %d, port %d, model %s, laya %s", pid, port, self._model, self.version or "?")
        return base_url

    def __exit__(self, *exc_info: object) -> None:
        self.stop()

    def _wait_ready(self, base_url: str) -> None:
        assert self._proc is not None
        deadline = time.monotonic() + self._ready_timeout_s
        client = self._client or httpx.Client(timeout=HEALTH_TIMEOUT_S)
        try:
            while time.monotonic() < deadline:
                code = self._proc.poll()
                if code is not None:
                    raise SystemOneUnavailable(f"laya-serve exited with code {code} before it was ready")
                try:
                    if client.get(f"{base_url}/health").status_code == 200:
                        return
                except httpx.HTTPError:
                    pass
                time.sleep(0.2)
        finally:
            if self._client is None:
                client.close()
        raise SystemOneUnavailable(f"laya-serve was not ready within {self._ready_timeout_s:.0f}s")

    def stop(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        if proc.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGTERM)
            with contextlib.suppress(subprocess.TimeoutExpired):
                proc.wait(self._stop_grace_s)
        # workers that outlived the leader (or a leader that died early) are in the group still (SCN-FAC-04)
        with contextlib.suppress(ProcessLookupError):
            os.killpg(proc.pid, signal.SIGKILL)
        code = proc.wait()
        log.info("laya-serve stopped: pid %d, exit code %d", proc.pid, code)
        if self._redactor is not None and self._log_path is not None:  # the child wrote it raw; CI uploads .l4-out/
            with contextlib.suppress(OSError):
                text = self._log_path.read_text(encoding="utf-8", errors="replace")
                self._log_path.write_text(self._redactor.redact_text(text), encoding="utf-8")


# --- the backend -------------------------------------------------------------------------------------------------


def _over_the_context(response: httpx.Response) -> bool:
    """Ollama's 400 for a prompt over the loaded context (`prompt 0 has 8100 tokens; expected 1-2048 (input is never
    truncated)` on Tev1, Ollama 0.40.0): the one 400 that is about this question's size, not the engine."""
    try:
        text = str(response.json().get("error", ""))
    except (ValueError, AttributeError):
        return False
    return "never truncated" in text or ("tokens" in text and "expected" in text)


class SystemOneBackend:
    """One System-One server. `ask` needs it started: `with backend:` (or `start()` and `stop()`); for `laya-local`
    that is when the server runs, for the other engines it only opens the HTTP client."""

    def __init__(
        self,
        engine: Engine,
        *,
        model: str,
        base_url: str | None = None,
        api_key: str | None = None,
        serve: LayaServe | None = None,
        transport: httpx.BaseTransport | None = None,
        log_path: Path | None = None,
        redactor: Redactor,
        timeout_s: float = CALL_TIMEOUT_S,
        served_model: str = "",
        host_version: str = "",
    ) -> None:
        if engine == "ollama" and api_key:
            raise ValueError("engine ollama takes no key (it is keyless)")
        if (engine == "laya-local") != (serve is not None):
            raise ValueError("engine laya-local needs a LayaServe, and no other engine takes one")
        if engine != "laya-local" and not base_url:
            raise ValueError(f"engine {engine} needs a base_url")
        self.engine, self.model = engine, model
        self._base_url, self._serve, self._transport = base_url, serve, transport
        self._api_key, self._log_path, self._redactor, self._timeout_s = api_key, log_path, redactor, timeout_s
        self._client: httpx.Client | None = None
        self._served_model, self._host_version = served_model, host_version

    def start(self) -> None:
        if self._client is not None:
            return
        base_url = self._base_url
        if self._serve is not None:
            base_url = self._serve.__enter__()
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        self._client = httpx.Client(
            base_url=str(base_url), headers=headers, timeout=self._timeout_s, transport=self._transport
        )

    def stop(self) -> None:
        client, self._client = self._client, None
        if client is not None:
            client.close()
        if self._serve is not None:
            self._serve.stop()

    def __enter__(self) -> "SystemOneBackend":
        self.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.stop()

    @property
    def server_version(self) -> str:
        """The laya package version behind a `laya-local` server, `ollama <version>` behind an Ollama host ("" for the
        other engines, or when unknown)."""
        if self._host_version:
            return f"ollama {self._host_version}"
        return self._serve.version if self._serve is not None else ""

    @property
    def running(self) -> bool:
        return self._client is not None

    def wire_state(self, state: str) -> str:
        """The state as `query` sends and logs it, after redaction: what a calibration line has to hash."""
        return self._redactor.redact_text(state)

    def query(self, state: str | Mapping[str, Any] | Sequence[Any], questions: Mapping[str, Question]) -> Reply:
        if self._client is None:
            raise SystemOneUnavailable("the System-One server is not started")
        # one choke point: what goes on the wire (a LAN port or a third-party API) is what is logged (L4-OBS-002)
        began = time.monotonic()
        request: dict[str, Any] = self._redactor.redact_obj({"state": state, "model": self.model, "questions": {}})
        try:
            wire = Question.wire_ollama if self.engine == "ollama" else Question.wire
            request = self._redactor.redact_obj(
                {"state": state, "model": self.model, "questions": {i: wire(q) for i, q in questions.items()}}
            )
            reply = self._post(request)
        except SystemOneUnavailable as exc:
            self._log(request, None, str(exc), began)
            raise
        self._log(request, reply, None, began)
        return reply

    def ask(
        self, state: str | Mapping[str, Any] | Sequence[Any], questions: Mapping[str, Question]
    ) -> dict[str, float]:
        """`{question id: p(yes)}` for noul questions: the calibrated probability, as the server gave it."""
        reply = self.query(state, questions)
        out: dict[str, float] = {}
        for qid, question in questions.items():
            answer = reply.answers.get(qid)
            value = answer.get("noul") if isinstance(answer, dict) and answer.get("type") == "noul" else None
            if question.kind != "noul" or isinstance(value, bool) or not isinstance(value, int | float):
                raise SystemOneBadAnswer(f"no noul answer for question {qid}")
            if not 0.0 <= float(value) <= 1.0:
                raise SystemOneBadAnswer(f"noul answer for question {qid} is outside 0..1")
            out[qid] = float(value)
        return out

    def ask_typed(
        self, state: str | Mapping[str, Any] | Sequence[Any], questions: Mapping[str, Question]
    ) -> dict[str, Answer]:
        """`{question id: Answer}` for noul, choice and score questions (M16-G6); `ask` is unchanged."""
        return parse_typed(self.query(state, questions), questions)

    def _post(self, request: dict[str, Any]) -> Reply:
        assert self._client is not None
        kwargs: dict[str, Any] = {"json": request}
        if self.engine == "ollama":  # the exact bytes are counted, so the limit is the one the server applies
            body = json.dumps(request, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
            counted = len(body) + OLLAMA_MARGIN + OLLAMA_MARGIN_PER_QUESTION * len(request.get("questions", {}))
            if counted > OLLAMA_MAX_BODY:
                raise SystemOneTooLarge(f"unavailable: input too large (about {counted} bytes > {OLLAMA_MAX_BODY})")
            kwargs = {"content": body, "headers": {"Content-Type": "application/json"}}
        try:
            response = self._client.post("/v1/systemone", **kwargs)
        except httpx.TimeoutException:
            raise SystemOneUnavailable("the System-One request timed out") from None
        except httpx.HTTPError as exc:
            raise SystemOneUnavailable(f"the System-One request failed ({type(exc).__name__})") from None
        if self.engine == "ollama" and response.status_code == 413:
            raise SystemOneTooLarge("unavailable: input too large (the server answered HTTP 413)")
        if self.engine == "ollama" and response.status_code == 400 and _over_the_context(response):
            raise SystemOneTooLarge("unavailable: input too large (the prompt is over the model's loaded context)")
        if self.engine == "ollama" and response.status_code == 404:
            raise SystemOneUnavailable(f"the model is not pulled on the host: run `ollama pull {self.model}` there")
        if response.status_code != 200:
            raise SystemOneUnavailable(f"the System-One server answered HTTP {response.status_code}")
        try:
            data = response.json()
            answers = data["answers"]
            if not isinstance(answers, dict) or not all(isinstance(a, dict) for a in answers.values()):
                raise TypeError
            usage = data.get("usage") or {}
            if not isinstance(usage, dict):
                usage = {}  # accounting only: never a reason to drop an answer
            served = self._served_model or str(data.get("model", ""))
            return Reply(served, answers, usage)
        except (ValueError, KeyError, TypeError, AttributeError):
            raise SystemOneBadAnswer("the System-One reply is not a TypeSafe answer document") from None

    def _log(self, request: dict[str, Any], reply: Reply | None, error: str | None, began: float) -> None:
        if self._log_path is None:
            return
        line: dict[str, Any] = {
            "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ"), "engine": self.engine,
            "elapsed_ms": round((time.monotonic() - began) * 1000), "request": request,
            "response": None if reply is None else dataclasses.asdict(reply), "error": error,
        }  # fmt: skip
        line = self._redactor.redact_obj(line)
        try:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(line, ensure_ascii=False) + "\n")
        except OSError as exc:  # corroborating only: a request log that cannot be written never costs the answer
            log.warning("System-One request log not written (%s): %s", type(exc).__name__, self._log_path)


# --- selecting a profile (M15-G3) --------------------------------------------------------------------------------


def hf_hub(environ: Mapping[str, str]) -> Path:
    home = environ.get("HF_HOME")
    return (Path(home) if home else Path(environ.get("HOME") or Path.home()) / ".cache" / "huggingface") / "hub"


def laya_checkpoint_present(environ: Mapping[str, str], checkpoint: str) -> bool:
    snapshots = hf_hub(environ) / f"models--{LAYA_REPO.replace('/', '--')}" / "snapshots"
    return any(snapshots.glob(f"*/{checkpoint}/model.safetensors"))


def _ollama_version(text: object) -> tuple[int, int, int] | None:
    match = re.match(r"v?(\d+)\.(\d+)\.(\d+)", text) if isinstance(text, str) else None
    return None if match is None else (int(match[1]), int(match[2]), int(match[3]))


def _ollama_has(tags: object, model: str) -> str:
    """The name the host lists for `model` ("tev1" is "tev1:latest" to Ollama), or "" when it is not pulled."""
    names = [m.get("name") for m in tags if isinstance(m, dict)] if isinstance(tags, list) else []
    wanted = {model, model if ":" in model else f"{model}:latest"}
    return next((n for n in names if isinstance(n, str) and n in wanted), "")


def _probe_ollama(
    profile: Profile, client: httpx.Client | None, log: Mapping[str, Any]
) -> tuple[SystemOneBackend | None, str]:
    """`GET /api/version` (>= 0.35.0) and `GET /api/tags` (the model is pulled). No key is sent, none is needed."""
    if not profile.base_url:
        return None, "an ollama engine needs base_url"
    base, model = profile.base_url.rstrip("/"), profile.model or OLLAMA_MODEL
    http = client or httpx.Client(timeout=HEALTH_TIMEOUT_S)

    def get(path: str) -> Any:
        response = http.get(f"{base}{path}", timeout=HEALTH_TIMEOUT_S)
        if response.status_code != 200:
            raise ValueError(f"{base}{path} answered HTTP {response.status_code}")
        return response.json()

    try:
        version_text = (get("/api/version") or {}).get("version")
        version = _ollama_version(version_text)
        if version is None:
            return None, f"{base}/api/version does not name a version"
        want = ".".join(map(str, OLLAMA_MIN_VERSION))
        if version < OLLAMA_MIN_VERSION:
            return None, f"Ollama {version_text} at {base} is older than {want} (no /v1/systemone): upgrade it"
        served = _ollama_has((get("/api/tags") or {}).get("models"), model)
    except httpx.HTTPError as exc:
        return None, f"{base} is unreachable ({type(exc).__name__})"
    except (ValueError, AttributeError) as exc:
        return None, f"{base} gave no usable answer ({type(exc).__name__}: {str(exc)[:80]})"
    finally:
        if client is None:
            http.close()
    if not served:
        return None, f"the model {model} is not pulled at {base}: run `ollama pull {model}` on that host"
    backend = SystemOneBackend(
        "ollama", model=model, base_url=base, served_model=served, host_version=str(version_text), **log
    )
    return backend, ""


def _probe(
    profile: Profile, environ: Mapping[str, str], client: httpx.Client | None, log: Mapping[str, Any],
    *, require_passed: bool = True,
) -> tuple[SystemOneBackend | None, str]:  # fmt: skip
    """(a backend that is ready to be started, "") or (None, why not). Nothing here starts a server.
    `require_passed=False` lets a checkpoint whose gate ran and failed through (`l4 s1 score` only)."""
    engine = profile.engine
    if engine not in ENGINES:
        return None, f"engine {engine!r} is not one of {', '.join(ENGINES)}"
    if engine == "laya-local":
        argv0 = resolve_executable("laya-serve", environ)
        checkpoint = profile.model or LAYA_MODEL
        if argv0 is None:
            return None, "laya-serve is not on PATH"
        if is_checkpoint_path(checkpoint):  # a gated tuned checkpoint (M16-G20): served from a private HF home
            if problem := checkpoint_problem(checkpoint, environ, require_passed=require_passed):
                return None, problem
            environ = {**environ, "HF_HOME": str(overlay_home(checkpoint, environ))}
            checkpoint = LAYA_MODEL
        if not laya_checkpoint_present(environ, checkpoint):
            return None, f"the {checkpoint} checkpoint is not in the Hugging Face cache"
        serve_log = log["log_path"].parent / "laya-serve.log" if log["log_path"] is not None else None
        serve = LayaServe([argv0], environ, model=checkpoint, log_path=serve_log, redactor=log["redactor"])
        return SystemOneBackend("laya-local", model=checkpoint, serve=serve, **log), ""
    key = environ.get(profile.api_key_env, "") if profile.api_key_env else ""
    if engine == "jev":
        if not profile.api_key_env or not key:
            return None, f"the variable {profile.api_key_env or 'api_key_env'} is not set"
        model, url = profile.model or JEV_MODEL, profile.base_url or JEV_URL
        return SystemOneBackend("jev", model=model, base_url=url, api_key=key, **log), ""
    if engine == "ollama":
        return _probe_ollama(profile, client, log)
    if not profile.base_url:
        return None, "a remote engine needs base_url"
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    url = f"{profile.base_url.rstrip('/')}/health"
    http = client or httpx.Client(timeout=HEALTH_TIMEOUT_S)
    try:
        code = http.get(url, headers=headers, timeout=HEALTH_TIMEOUT_S).status_code
    except httpx.HTTPError as exc:
        return None, f"{url} is unreachable ({type(exc).__name__})"
    finally:
        if client is None:
            http.close()
    if code != 200:
        return None, f"{url} answered HTTP {code}"
    model = profile.model or LAYA_MODEL
    return SystemOneBackend("remote", model=model, base_url=profile.base_url, api_key=key or None, **log), ""


def open_s1_profile(
    cfg: L4Config,
    name: str,
    *,
    environ: Mapping[str, str] | None = None,
    client: httpx.Client | None = None,
    log_path: Path | None = None,
    redactor: Redactor,
    allow_failed_gate: bool = False,
) -> SystemOneBackend:
    """The backend of the named `backend: system-one` profile, stopped; `RoleUnavailable` when it is not one or does
    not probe usable (M16-G10: the shadow engines are named, not picked from a role). A tuned checkpoint whose gate
    failed or never ran is `CheckpointGateFailed` (exit 2, still a `RoleUnavailable`) unless `allow_failed_gate`
    (`l4 s1 score`: the failed gate is what the report is about; a gate that never ran is still refused)."""
    profile = cfg.profiles.get(name)
    if profile is None or profile.backend != "system-one":
        raise RoleUnavailable(f"s1:{name}", "not a backend: system-one profile")
    backend, why = _probe(profile, os.environ if environ is None else environ, client,
                          {"log_path": log_path, "redactor": redactor},
                          require_passed=not allow_failed_gate)  # fmt: skip
    if backend is None:
        raise (CheckpointGateFailed if why in GATE_PROBLEMS else RoleUnavailable)(f"s1:{name}", why)
    return backend


def open_s1_backend(
    cfg: L4Config,
    role: str = "s1_judge",
    events: EventSink | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    client: httpx.Client | None = None,
    log_path: Path | None = None,
    redactor: Redactor,
) -> SystemOneBackend:
    """The first profile of `roles.<role>` with `backend: system-one` that probes usable (adapter profiles are not
    System One and are skipped). `RoleUnavailable` otherwise, never exit 2: S1 is an optional role. The backend is
    returned stopped: the caller starts it around the S1 work."""
    env = os.environ if environ is None else environ
    log = {"log_path": log_path, "redactor": redactor}
    skipped: list[dict[str, str]] = []
    for index, name in enumerate(getattr(cfg.roles, role)):
        profile = cfg.profiles.get(name)
        if profile is None or profile.backend != "system-one":
            skipped.append({"profile": name, "reason": "not a backend: system-one profile"})
            continue
        backend, why = _probe(profile, env, client, log)
        if backend is None:
            skipped.append({"profile": name, "reason": why})
            continue
        if events is not None:
            events.append(
                "availability.selected", role=role, selected=name, fallback_index=index, skipped=skipped,
                probes={"engine": {"engine": backend.engine}}, cached=False,
            )  # fmt: skip
        return backend
    detail = "; ".join(f"{s['profile']}: {s['reason']}" for s in skipped)
    detail = detail or "no profile is configured for it under roles"
    if any(s["reason"] in GATE_PROBLEMS for s in skipped):  # a checkpoint that failed its gate: not retryable
        raise CheckpointGateFailed(role, detail)
    raise RoleUnavailable(role, detail)
