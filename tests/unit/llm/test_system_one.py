import json
import os
import stat
import sys
import time
from pathlib import Path

import httpx
import pytest

from l4.agents.factory import RoleUnavailable
from l4.config.schema import L4Config
from l4.llm.system_one import (
    LayaServe,
    Question,
    SystemOneBackend,
    SystemOneUnavailable,
    laya_env,
    open_s1_backend,
)
from l4.redact import Redactor

NOUL = {"p": Question("noul", "Does this evidence show that the criterion is satisfied?")}
KEY = "tsk_" + "k" * 24


def mock_backend(handler, tmp_path: Path, **kw) -> SystemOneBackend:
    return SystemOneBackend(
        "remote", model="typed-decisions", base_url="http://s1.test", transport=httpx.MockTransport(handler),
        log_path=tmp_path / ".l4-out" / "logs" / "system-one.jsonl", **{"redactor": Redactor({}), **kw},
    )  # fmt: skip


def ok(noul: float = 0.93):
    return lambda request: httpx.Response(
        200, json={"model": "laya-rl-agent", "answers": {"p": {"type": "noul", "noul": noul}},
                   "usage": {"input_tokens": 12, "output_tokens": 3}},
    )  # fmt: skip


def test_wire_format_and_calibration_log(tmp_path: Path):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return ok(0.93)(request)

    questions = {
        "p": Question("noul", "Is it urgent?", {"true": "explicitly time-sensitive", "false": "no urgency"}),
    }
    with mock_backend(handler, tmp_path, api_key=KEY, redactor=Redactor({"KEY": KEY})) as backend:
        assert backend.ask("Help! Payouts fail.", questions) == {"p": 0.93}
    (request,) = seen
    assert (request.method, request.url.path) == ("POST", "/v1/systemone")
    assert request.headers["authorization"] == f"Bearer {KEY}"
    assert json.loads(request.content) == {
        "state": "Help! Payouts fail.", "model": "typed-decisions",
        "questions": {"p": {"type": "noul", "instructions": "Is it urgent?",
                            "criteria": {"true": "explicitly time-sensitive", "false": "no urgency"}}},
    }  # fmt: skip
    (line,) = (tmp_path / ".l4-out/logs/system-one.jsonl").read_text().splitlines()
    record = json.loads(line)
    assert record["engine"] == "remote" and record["error"] is None
    assert record["request"]["state"] == "Help! Payouts fail."
    assert record["response"]["answers"]["p"]["noul"] == 0.93 and record["response"]["model"] == "laya-rl-agent"
    assert KEY not in line


def test_the_api_key_never_reaches_the_log_even_inside_a_state(tmp_path: Path):
    with mock_backend(ok(), tmp_path, redactor=Redactor({"TYPESAFE_API_KEY": KEY})) as backend:
        backend.ask(f"the log said {KEY}", NOUL)
    assert KEY not in (tmp_path / ".l4-out/logs/system-one.jsonl").read_text()


@pytest.mark.parametrize(
    ("response", "why"),
    [
        (httpx.Response(500, text="boom"), "HTTP 500"),
        (httpx.Response(429, text="slow down"), "HTTP 429"),
        (httpx.Response(401, text="no"), "HTTP 401"),
        (httpx.Response(200, text="not json"), "not a TypeSafe answer"),
        (httpx.Response(200, json={"answers": ["x"]}), "not a TypeSafe answer"),
        (httpx.Response(200, json={"answers": {"p": {"type": "noul", "noul": 1.7}}}), "outside 0..1"),
        (httpx.Response(200, json={"answers": {"p": {"type": "noul", "noul": True}}}), "no noul answer"),
        (httpx.Response(200, json={"answers": {"p": {"type": "choice", "choice": "a"}}}), "no noul answer"),
        (httpx.Response(200, json={"answers": {}}), "no noul answer"),
    ],
)
def test_server_trouble_is_unavailable_never_a_verdict(tmp_path: Path, response: httpx.Response, why: str):
    with mock_backend(lambda request: response, tmp_path) as backend, pytest.raises(SystemOneUnavailable, match=why):
        backend.ask("s", NOUL)
    record = json.loads((tmp_path / ".l4-out/logs/system-one.jsonl").read_text().splitlines()[-1])
    assert record["request"]["state"] == "s"
    if why.startswith("HTTP") or why.startswith("not a TypeSafe"):
        assert record["response"] is None and why in record["error"]  # the failure is recorded
    else:
        assert record["error"] is None and record["response"] is not None  # the reply is recorded, the use refused


def test_connection_failures_and_timeouts_are_unavailable(tmp_path: Path):
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    for handler, why in ((refuse, "ConnectError"), (slow, "timed out")):
        with mock_backend(handler, tmp_path) as backend, pytest.raises(SystemOneUnavailable, match=why):
            backend.ask("s", NOUL)


def test_asking_before_the_server_is_started_is_unavailable(tmp_path: Path):
    with pytest.raises(SystemOneUnavailable, match="not started"):
        mock_backend(ok(), tmp_path).ask("s", NOUL)


def test_laya_local_needs_a_serve_and_the_others_a_base_url():
    with pytest.raises(ValueError):
        SystemOneBackend("laya-local", model="m", redactor=Redactor({}))
    with pytest.raises(ValueError):
        SystemOneBackend("jev", model="m", redactor=Redactor({}))


# --- LayaServe: real subprocesses of a fake `laya-serve` ----------------------------------------------------------

FAKE_SERVE = """#!{python}
import http.server, json, os, sys, time
open({state!r} + "/pid", "w").write(str(os.getpid()))
open({state!r} + "/env.json", "w").write(json.dumps(dict(os.environ)))
if {mode!r} == "crash":
    sys.exit(3)
if {mode!r} == "orphan":
    import subprocess
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    open({state!r} + "/child", "w").write(str(child.pid))
    sys.exit(3)
if {mode!r} == "never":
    time.sleep(120)
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        self.send_response(200 if self.path == "/health" else 404); self.end_headers(); self.wfile.write(b"ok")
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        answers = {{i: {{"type": "noul", "noul": 0.25}} for i in body["questions"]}}
        out = json.dumps({{"model": "fake", "answers": answers, "usage": {{}}}}).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(out))); self.end_headers()
        self.wfile.write(out)
http.server.HTTPServer(("127.0.0.1", int(os.environ["LAYA_PORT"])), H).serve_forever()
"""


def fake_laya(tmp_path: Path, mode: str, **kw) -> tuple[LayaServe, Path]:
    """A `laya-serve` stand-in (a Python script) that records its pid and environment, then serves, crashes or hangs."""
    state = tmp_path / "state"
    state.mkdir(exist_ok=True)
    exe = tmp_path / "laya-serve"
    exe.write_text(FAKE_SERVE.format(python=sys.executable, state=str(state), mode=mode))
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)
    environ = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "L4_FORGE_TOKEN": "glpat-" + "s" * 20}
    return LayaServe([str(exe)], environ, **kw), state


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def gone(pid: int, within: float = 5.0) -> bool:
    end = time.time() + within
    while time.time() < end:
        if not alive(pid):
            return True
        time.sleep(0.05)
    return False


def test_laya_serve_runs_on_a_free_port_and_is_stopped(tmp_path: Path):
    serve, state = fake_laya(tmp_path, "serve")
    with SystemOneBackend("laya-local", model="typed-decisions", serve=serve, redactor=Redactor({})) as backend:
        assert backend.running
        assert backend.ask("state", NOUL) == {"p": 0.25}
        pid = int((state / "pid").read_text())
        assert alive(pid)
    assert not backend.running and gone(pid)


def test_laya_serve_environment_is_built_not_inherited(tmp_path: Path):
    serve, state = fake_laya(tmp_path, "serve")
    with serve as url:
        port = int(url.rsplit(":", 1)[1])
    seen = json.loads((state / "env.json").read_text())
    assert "L4_FORGE_TOKEN" not in seen
    assert {k: seen[k] for k in ("LAYA_HOST", "LAYA_PORT", "LAYA_MODELS", "LAYA_THREADS", "OMP_NUM_THREADS")} == {
        "LAYA_HOST": "127.0.0.1", "LAYA_PORT": str(port), "LAYA_MODELS": "typed-decisions", "LAYA_THREADS": "2",
        "OMP_NUM_THREADS": "2",
    }  # fmt: skip
    assert laya_env({"PATH": "/p", "HOME": "/h", "L4_FORGE_TOKEN": "x"}, port, "typed-decisions", 2) == {
        "PATH": "/p", "HOME": "/h", "LAYA_HOST": "127.0.0.1", "LAYA_PORT": str(port), "LAYA_MODELS": "typed-decisions",
        "LAYA_PRELOAD": "1", "LAYA_DEVICE": "cpu", "LAYA_MAX_LOADED": "1", "LAYA_THREADS": "2", "OMP_NUM_THREADS": "2",
        "HF_HUB_OFFLINE": "1",
    }  # fmt: skip


def test_laya_serve_stopped_and_killed_when_not_ready(tmp_path: Path):
    serve, state = fake_laya(tmp_path, "never", ready_timeout_s=1.0, stop_grace_s=1.0)
    with pytest.raises(SystemOneUnavailable, match="not ready within"), serve:
        pytest.fail("the body must not run")
    assert gone(int((state / "pid").read_text()))


def test_laya_serve_that_exits_early_is_unavailable_at_once(tmp_path: Path):
    serve, _ = fake_laya(tmp_path, "crash")
    began = time.time()
    with pytest.raises(SystemOneUnavailable, match="exited with code 3"), serve:
        pytest.fail("the body must not run")
    assert time.time() - began < 10


def test_a_missing_executable_is_unavailable(tmp_path: Path):
    serve = LayaServe([str(tmp_path / "no-such-laya-serve")], {"PATH": "/usr/bin"})
    with pytest.raises(SystemOneUnavailable, match="cannot start"), serve:
        pytest.fail("the body must not run")


# --- open_s1_backend ------------------------------------------------------------------------------------------------


class Events:
    def __init__(self) -> None:
        self.items: list[tuple[str, dict]] = []

    def append(self, event_type: str, /, **data):
        self.items.append((event_type, data))


def cfg(profiles: dict, chain: list[str]) -> L4Config:
    return L4Config.model_validate({"profiles": profiles, "roles": {"s1_judge": chain}})


def health(code: int = 200, seen: list | None = None):
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(str(request.url))
        return httpx.Response(code, text="ok")

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_open_s1_backend_picks_first_system_one_profile_and_degrades(tmp_path: Path):
    profiles = {
        "claude": {"adapter": "claude-code"},
        "mac": {
            "backend": "system-one", "engine": "remote", "base_url": "http://192.0.2.10:8000",
            "model": "typed-decisions",
        },
        "jev": {"backend": "system-one", "engine": "jev", "api_key_env": "TYPESAFE_API_KEY"},
    }  # fmt: skip
    events, urls = Events(), []
    backend = open_s1_backend(
        cfg(profiles, ["claude", "mac", "jev"]),
        "s1_judge",
        events,
        environ={},
        client=health(200, urls),
        redactor=Redactor({}),
    )
    assert (backend.engine, backend.model, backend.running) == ("remote", "typed-decisions", False)
    assert urls == ["http://192.0.2.10:8000/health"]
    ((name, data),) = events.items
    assert name == "availability.selected"
    assert (data["role"], data["selected"], data["fallback_index"]) == ("s1_judge", "mac", 1)
    assert data["skipped"] == [{"profile": "claude", "reason": "not a backend: system-one profile"}]

    # the first usable one wins: the Mac is down, so Jev (key present, names only are checked) is selected
    backend = open_s1_backend(
        cfg(profiles, ["mac", "jev"]),
        "s1_judge",
        environ={"TYPESAFE_API_KEY": KEY},
        client=health(503),
        redactor=Redactor({}),
    )
    assert (backend.engine, backend.model) == ("jev", "jev-latest")

    with pytest.raises(RoleUnavailable) as err:
        open_s1_backend(
            cfg(profiles, ["claude", "mac", "jev"]), "s1_judge", environ={}, client=health(503), redactor=Redactor({})
        )
    message = str(err.value)
    assert "mac: http://192.0.2.10:8000/health answered HTTP 503" in message
    assert "jev: the variable TYPESAFE_API_KEY is not set" in message
    assert err.value.code == 12  # an optional role degrades; it never exits 2
    with pytest.raises(RoleUnavailable, match="no profile is configured"):
        open_s1_backend(cfg({}, []), "s1_judge", environ={}, redactor=Redactor({}))


def test_an_unreachable_remote_degrades(tmp_path: Path):
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route")

    profile = {"mac": {"backend": "system-one", "engine": "remote", "base_url": "http://10.0.0.9:8000"}}
    client = httpx.Client(transport=httpx.MockTransport(refuse))
    with pytest.raises(RoleUnavailable, match="unreachable"):
        open_s1_backend(cfg(profile, ["mac"]), environ={}, client=client, redactor=Redactor({}))


def test_laya_local_needs_the_binary_and_the_checkpoint(tmp_path: Path):
    bin_dir, home = tmp_path / "bin", tmp_path / "home"
    bin_dir.mkdir()
    profile = {"laya": {"backend": "system-one", "engine": "laya-local"}}
    environ = {"PATH": str(bin_dir), "HOME": str(home)}
    with pytest.raises(RoleUnavailable, match="laya-serve is not on PATH"):
        open_s1_backend(cfg(profile, ["laya"]), environ=environ, redactor=Redactor({}))
    exe = bin_dir / "laya-serve"
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    with pytest.raises(RoleUnavailable, match="typed-decisions checkpoint is not in the Hugging Face cache"):
        open_s1_backend(cfg(profile, ["laya"]), environ=environ, redactor=Redactor({}))
    snap = home / ".cache/huggingface/hub/models--convaiinnovations--laya/snapshots/abc123/typed-decisions"
    snap.mkdir(parents=True)
    (snap / "model.safetensors").write_bytes(b"x")
    backend = open_s1_backend(cfg(profile, ["laya"]), environ=environ, redactor=Redactor({}))
    assert (backend.engine, backend.model, backend.running) == ("laya-local", "typed-decisions", False)


def test_laya_serve_output_goes_to_a_redacted_log_next_to_the_request_log(tmp_path: Path):
    """A Laya that cannot load must leave more than 'exited with code N before it was ready'."""
    secret = "glpat-" + "s" * 20
    fake_serve = tmp_path / "laya-serve"
    fake_serve.write_text(f"#!/bin/sh\necho 'cannot load the checkpoint {secret}'\nexit 3\n")
    fake_serve.chmod(0o755)
    home = tmp_path / "home"
    snap = home / ".cache/huggingface/hub/models--convaiinnovations--laya/snapshots/abc123/typed-decisions"
    snap.mkdir(parents=True)
    (snap / "model.safetensors").write_bytes(b"x")
    profile = {"laya": {"backend": "system-one", "engine": "laya-local"}}
    request_log = tmp_path / ".l4-out" / "logs" / "system-one.jsonl"
    backend = open_s1_backend(
        cfg(profile, ["laya"]), environ={"PATH": str(tmp_path), "HOME": str(home)}, log_path=request_log,
        redactor=Redactor({"L4_FORGE_TOKEN": secret}),
    )  # fmt: skip
    with pytest.raises(SystemOneUnavailable, match="exited with code 3"), backend:
        pass
    text = (request_log.parent / "laya-serve.log").read_text()
    assert "cannot load the checkpoint" in text and secret not in text


def test_unknown_engine_is_skipped_not_fatal():
    profile = {"x": {"backend": "system-one", "engine": "gpt"}}
    with pytest.raises(RoleUnavailable, match="engine 'gpt' is not one of"):
        open_s1_backend(cfg(profile, ["x"]), environ={}, redactor=Redactor({}))


GOLDEN_LAYA_REPLY = {  # laya-serve 0.3.24, recorded: usage holds non-integers (`truncated`, `truncated_questions`)
    "model": "laya-rl-agent",
    "answers": {"q": {"type": "noul", "noul": 0.3814}},
    "usage": {"input_tokens": 36, "output_tokens": 0, "state_tokens": 6, "state_tokens_dropped": 0,
              "truncated": False, "truncated_questions": []},
    "routing": {"q": {"head": "noul"}},
}  # fmt: skip


def test_a_real_laya_reply_is_parsed_whatever_its_usage_holds(tmp_path: Path):
    handler = lambda request: httpx.Response(200, json=GOLDEN_LAYA_REPLY)  # noqa: E731
    with mock_backend(handler, tmp_path) as backend:
        assert backend.ask("state", {"q": Question("noul", "Is it?")}) == {"q": 0.3814}
        assert backend.query("state", {"q": Question("noul", "Is it?")}).usage["truncated"] is False






def test_workers_of_a_server_that_died_early_are_killed_too(tmp_path: Path):
    serve, state = fake_laya(tmp_path, "orphan")
    with pytest.raises(SystemOneUnavailable, match="exited with code 3"), serve:
        pytest.fail("the body must not run")
    assert gone(int((state / "child").read_text()))


def test_laya_serve_logs_its_start_and_stop_at_info(tmp_path: Path, caplog):
    serve, _ = fake_laya(tmp_path, "serve", ready_timeout_s=30)
    with caplog.at_level("INFO", logger="l4.system_one"), serve:
        pass
    started, stopped = [r.getMessage() for r in caplog.records if r.name == "l4.system_one"]
    assert started.startswith("laya-serve started: pid ") and "model typed-decisions" in started and "port " in started
    assert stopped.startswith("laya-serve stopped: pid ") and "exit code" in stopped


def test_laya_version_comes_from_the_interpreter_the_script_names(tmp_path: Path):
    from l4.llm.system_one import laya_version

    script = tmp_path / "laya-serve"
    script.write_text(f"#!{sys.executable}\n")
    assert laya_version(str(script), {"PATH": "/usr/bin"}, dist="pytest") == pytest.__version__
    assert laya_version(str(script), {"PATH": "/usr/bin"}, dist="no-such-distribution") == ""
    script.write_text("not a script\n")
    assert laya_version(str(script), {}, dist="pytest") == "" and laya_version(str(tmp_path / "none"), {}) == ""


def test_laya_version_reads_the_uv_trampoline_form_too(tmp_path: Path):
    """uv and pip write `#!/bin/sh` and an `exec` line when the interpreter path is long or has spaces."""
    from l4.llm.system_one import laya_version

    python = tmp_path / "a long dir with spaces" / "python"
    python.parent.mkdir()
    python.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')  # a link would lose the venv's site-packages
    python.chmod(0o755)
    quotes = "'" * 3
    script = tmp_path / "laya-serve"
    script.write_text(f"#!/bin/sh\n{quotes}exec' '{python}' \"$0\" \"$@\"\n' {quotes}\nimport sys\n")
    assert laya_version(str(script), {"PATH": "/usr/bin"}, dist="pytest") == pytest.__version__
    script.write_text("#!/bin/sh\necho hi\n")
    assert laya_version(str(script), {"PATH": "/usr/bin"}, dist="pytest") == ""


def test_laya_version_runs_the_interpreter_with_a_minimal_environment(tmp_path: Path, monkeypatch):
    """The venv interpreter must not see the job's tokens: PATH, HOME and LANG only, nothing the redactor matches."""
    import subprocess as sp

    from l4 import redact
    from l4.llm import system_one

    script = tmp_path / "laya-serve"
    script.write_text(f"#!{sys.executable}\n")
    seen: dict[str, str] = {}
    real = sp.run

    def spy(*args, **kwargs):
        seen.update(kwargs["env"])
        return real(*args, **kwargs)

    monkeypatch.setattr(system_one.subprocess, "run", spy)
    environ = {
        "PATH": "/usr/bin", "HOME": "/h", "LANG": "C.UTF-8", "CI_JOB_TOKEN": "glcbt-abcdefghijklmnop1234",
        "GITLAB_TOKEN": "glpat-abcdefghijklmnop1234", "ANTHROPIC_API_KEY": "sk-ant-abcdefghijklmnopqrst", "X": "y",
    }  # fmt: skip
    assert system_one.laya_version(str(script), environ, dist="pytest") == pytest.__version__
    assert set(seen) <= {"PATH", "HOME", "LANG"} and seen["PATH"] == "/usr/bin"
    assert redact.Redactor({}).redact_text(" ".join(seen.values())) == " ".join(seen.values())


def test_a_laya_serve_log_that_cannot_be_opened_is_unavailable_not_an_oserror(tmp_path: Path):
    """SCN-VER-24: S1 never stops a round, and an unwritable log directory is one more way the server is unusable."""
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("a file where the log directory should be")
    serve, _ = fake_laya(tmp_path, "serve", log_path=blocker / "laya-serve.log")
    with pytest.raises(SystemOneUnavailable):
        serve.__enter__()


def test_a_request_log_that_cannot_be_written_never_costs_the_answer(tmp_path: Path, caplog):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x")
    transport = httpx.MockTransport(
        lambda r: httpx.Response(200, json={"model": "m", "answers": {"p": {"type": "noul", "noul": 0.5}}})
    )
    backend = SystemOneBackend(
        "remote", model="m", base_url="http://s1.test", transport=transport,  # type: ignore[arg-type]
        log_path=blocker / "s1.jsonl", redactor=Redactor({}),
    )  # fmt: skip
    with backend, caplog.at_level("WARNING", logger="l4.system_one"):
        assert backend.ask("s", NOUL) == {"p": 0.5}
    assert any("log" in r.getMessage() for r in caplog.records)
