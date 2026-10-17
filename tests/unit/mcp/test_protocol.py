"""`l4 mcp serve` speaks MCP over stdio (L4-MCP-001, SCN-MCP-01, SCN-MCP-02)."""

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from l4 import __version__
from l4.mcp import protocol
from l4.mcp.server import Server
from l4.mcp.tools import UnknownTool

FAKE_TOOLS = [
    {
        "name": "echo",
        "description": "Echo.",
        "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}},
    }
]


class FakeToolbox:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.release = threading.Event()

    def specs(self) -> list[dict]:
        return FAKE_TOOLS

    def call(self, name, arguments, control):
        if name == "slow":
            self.calls.append((name, arguments))
            while not (control.cancelled.is_set() or self.release.is_set()):
                control.cancelled.wait(0.01)
            return {"content": [{"type": "text", "text": "late"}], "isError": False}
        if name != "echo":
            raise UnknownTool(name)
        self.calls.append((name, arguments))
        return {"content": [{"type": "text", "text": arguments.get("text", "")}], "isError": False}


def talk(*lines: str, toolbox=None) -> list[dict]:
    """Feed the lines to a server, return every message it wrote (one JSON object per line)."""
    out: list[str] = []
    Server(toolbox or FakeToolbox(), write=out.append).serve(iter(lines))
    return [json.loads(text) for text in out]


def request(id_, method, params=None) -> str:
    message = {"jsonrpc": "2.0", "id": id_, "method": method}
    if params is not None:
        message["params"] = params
    return json.dumps(message)


INIT = request(1, "initialize", {"protocolVersion": protocol.PROTOCOL_VERSION, "capabilities": {}, "clientInfo": {}})
NOTE = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"})


def test_connect_and_list_tools():  # SCN-MCP-01
    replies = talk(INIT, NOTE, request(2, "tools/list"))
    assert [r["id"] for r in replies] == [1, 2]  # the notification gets no reply
    init = replies[0]["result"]
    assert init["serverInfo"] == {"name": "l4", "version": __version__}
    assert init["capabilities"] == {"tools": {}}
    assert init["protocolVersion"] == protocol.PROTOCOL_VERSION
    assert replies[1]["result"]["tools"] == FAKE_TOOLS


def test_initialize_accepts_a_known_client_revision_and_answers_its_own_otherwise():
    older = protocol.SUPPORTED_VERSIONS[-1]
    known = talk(request(1, "initialize", {"protocolVersion": older}))[0]["result"]
    assert known["protocolVersion"] == older
    unknown = talk(request(1, "initialize", {"protocolVersion": "1999-01-01"}))[0]["result"]
    assert unknown["protocolVersion"] == protocol.PROTOCOL_VERSION


def test_the_pinned_revision_is_a_date_and_the_first_supported():
    assert protocol.SUPPORTED_VERSIONS[0] == protocol.PROTOCOL_VERSION
    assert len(protocol.PROTOCOL_VERSION) == 10 and protocol.PROTOCOL_VERSION[4] == "-"


def test_ping_answers_an_empty_result():
    assert talk(request("a", "ping")) == [{"jsonrpc": "2.0", "id": "a", "result": {}}]


def test_a_line_that_is_not_json_gets_32700_and_the_server_keeps_serving():  # SCN-MCP-02
    replies = talk("this is not json", request(7, "ping"))
    assert replies[0]["error"]["code"] == -32700 and replies[0]["id"] is None
    assert replies[1]["result"] == {}


def test_an_unknown_method_gets_32601_and_the_server_keeps_serving():  # SCN-MCP-02
    replies = talk(request(3, "no/such"), request(4, "ping"))
    assert replies[0]["error"]["code"] == -32601 and replies[0]["id"] == 3
    assert replies[1]["id"] == 4


def test_an_unknown_notification_gets_no_reply():
    assert talk(json.dumps({"jsonrpc": "2.0", "method": "no/such"})) == []


@pytest.mark.parametrize(
    "line",
    [
        "[]",
        "[1, 2]",
        "42",
        '"text"',
        json.dumps({"jsonrpc": "1.0", "id": 1, "method": "ping"}),
        json.dumps({"id": 1, "method": "ping"}),
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": 5}),
        json.dumps({"jsonrpc": "2.0", "id": None, "method": "ping"}),
        json.dumps({"jsonrpc": "2.0", "id": [1], "method": "ping"}),
    ],
)
def test_a_json_value_that_is_not_a_request_gets_32600(line):
    replies = talk(line, request(9, "ping"))
    assert replies[0]["error"]["code"] == -32600
    assert replies[1]["id"] == 9


def test_the_id_of_an_invalid_request_is_echoed_when_it_is_usable():
    reply = talk(json.dumps({"jsonrpc": "1.0", "id": 5, "method": "ping"}))[0]
    assert reply["id"] == 5


def test_blank_lines_and_responses_from_the_client_are_ignored():
    replies = talk("", "   ", json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}), request(2, "ping"))
    assert [r["id"] for r in replies] == [2]


def test_tools_call_passes_arguments_and_returns_the_result():
    toolbox = FakeToolbox()
    reply = talk(request(5, "tools/call", {"name": "echo", "arguments": {"text": "hi"}}), toolbox=toolbox)[0]
    assert reply["result"]["content"] == [{"type": "text", "text": "hi"}]
    assert toolbox.calls == [("echo", {"text": "hi"})]


def test_tools_call_without_arguments_passes_an_empty_object():
    toolbox = FakeToolbox()
    talk(request(5, "tools/call", {"name": "echo"}), toolbox=toolbox)
    assert toolbox.calls == [("echo", {})]


@pytest.mark.parametrize("params", [None, {}, {"name": 5}, {"name": "echo", "arguments": [1]}, {"name": "nope"}])
def test_tools_call_with_bad_params_or_unknown_tool_gets_32602(params):
    reply = talk(request(5, "tools/call", params))[0]
    assert reply["error"]["code"] == -32602


def test_a_tool_that_crashes_is_an_error_result_not_a_dead_server():
    class Crashing(FakeToolbox):
        def call(self, name, arguments, control):
            raise RuntimeError("boom")

    replies = talk(request(1, "tools/call", {"name": "echo"}), request(2, "ping"), toolbox=Crashing())
    by_id = {r["id"]: r for r in replies}
    assert by_id[1]["result"]["isError"] is True
    assert "boom" in by_id[1]["result"]["content"][0]["text"]
    assert by_id[2]["result"] == {}


def test_a_cancelled_request_gets_no_reply():
    toolbox = FakeToolbox()
    lines = iter(
        [
            request(1, "tools/call", {"name": "slow"}),
            json.dumps({"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 1}}),
            request(2, "ping"),
        ]
    )
    out: list[str] = []
    Server(toolbox, write=out.append).serve(lines)
    ids = [json.loads(text)["id"] for text in out]
    assert ids == [2]


def test_progress_notifications_go_out_while_a_tool_runs():
    class Progressing(FakeToolbox):
        def call(self, name, arguments, control):
            control.progress("working")
            return {"content": [], "isError": False}

    params = {"name": "echo", "_meta": {"progressToken": "tok"}}
    out = talk(request(1, "tools/call", params), toolbox=Progressing())
    notes = [m for m in out if m.get("method") == "notifications/progress"]
    assert notes and notes[0]["params"]["progressToken"] == "tok"
    assert notes[0]["params"]["message"] == "working"
    assert "id" not in notes[0]


def _clean_env() -> dict[str, str]:
    return {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "AI_AGENT")}


def test_a_real_process_writes_only_protocol_messages_on_stdout(repo_factory):
    root = repo_factory("served")
    lines = "\n".join([INIT, NOTE, "garbage", request(2, "tools/list")]) + "\n"
    done = subprocess.run(
        [sys.executable, "-m", "l4", "mcp", "serve", "--repo", str(root)],
        input=lines, capture_output=True, text=True, env=_clean_env(), timeout=60, check=False,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    messages = [json.loads(line) for line in done.stdout.splitlines()]  # every stdout line is JSON
    assert [m.get("id") for m in messages] == [1, None, 2]
    assert messages[1]["error"]["code"] == -32700
    assert len(messages[2]["result"]["tools"]) == 15


def test_a_repo_that_is_not_an_l4_repository_exits_2_before_serving(tmp_path, repo_factory):  # L4-MCP-005
    for bad in (tmp_path, repo_factory("plain", l4=False), tmp_path / "missing"):
        done = subprocess.run(
            [sys.executable, "-m", "l4", "mcp", "serve", "--repo", str(bad)],
            input=INIT + "\n", capture_output=True, text=True, env=_clean_env(), timeout=60, check=False,
        )  # fmt: skip
        assert done.returncode == 2, done.stderr
        assert done.stdout == ""
        assert "mcp serve" in done.stderr


def test_without_repo_in_a_folder_that_is_no_repository_every_call_names_repo(tmp_path):  # SCN-MCP-12
    call = request(2, "tools/call", {"name": "l4_status", "arguments": {}})
    done = subprocess.run(
        [sys.executable, "-m", "l4", "mcp", "serve"],
        input="\n".join([INIT, NOTE, call]) + "\n", capture_output=True, text=True, env=_clean_env(),
        cwd=tmp_path, timeout=60, check=False,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr
    reply = [json.loads(line) for line in done.stdout.splitlines()][1]
    assert reply["result"]["isError"] is True
    assert "--repo PATH" in reply["result"]["content"][0]["text"]


def test_the_harness_gained_no_runtime_dependency():
    import tomllib

    root = Path(__file__).resolve().parents[3]
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    names = {d.split(">")[0].split("=")[0].strip() for d in data["project"]["dependencies"]}
    assert names == {"click", "httpx", "pydantic", "pynacl", "pyyaml"}


# --- review findings F5, F7, F8 -------------------------------------------------------------------------------------


def test_f5_stdio_is_utf8_whatever_the_locale(repo_factory):
    root = repo_factory("served")
    env = {**_clean_env(), "LC_ALL": "C", "LANG": "C", "PYTHONUTF8": "0", "PYTHONCOERCECLOCALE": "0"}
    for name in ("PYTHONIOENCODING", "LC_CTYPE"):
        env.pop(name, None)
    lines = "\n".join([INIT, NOTE, request(2, "tools/list"), request(3, "ping")]) + "\n"
    done = subprocess.run(
        [sys.executable, "-m", "l4", "mcp", "serve", "--repo", str(root)],
        input=lines.encode("utf-8"), capture_output=True, env=env, timeout=60, check=False,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
    messages = [json.loads(line) for line in done.stdout.decode("utf-8").splitlines()]  # strict UTF-8
    assert [m.get("id") for m in messages] == [1, 2, 3]
    assert "…" in done.stdout.decode("utf-8")  # a description carries U+2026 as itself


def test_f5_utf8_input_is_read_whatever_the_locale(repo_factory):
    root = repo_factory("served")
    env = {**_clean_env(), "LC_ALL": "C", "PYTHONUTF8": "0", "PYTHONCOERCECLOCALE": "0"}
    call = request(2, "tools/call", {"name": "l4_status", "arguments": {"unit": "openspec:café-…"}})
    done = subprocess.run(
        [sys.executable, "-m", "l4", "mcp", "serve", "--repo", str(root)],
        input="\n".join([INIT, NOTE, call]).encode("utf-8") + b"\n", capture_output=True, env=env, timeout=60,
        check=False,
    )  # fmt: skip
    assert done.returncode == 0, done.stderr.decode("utf-8", "replace")
    messages = [json.loads(line) for line in done.stdout.decode("utf-8").splitlines()]
    assert messages[1]["id"] == 2 and "result" in messages[1]


def test_f8_progress_values_increase_with_each_notification():
    class Progressing(FakeToolbox):
        def call(self, name, arguments, control):
            for text in ("one", "two", "three"):
                control.progress(text)
            return {"content": [], "isError": False}

    params = {"name": "echo", "_meta": {"progressToken": "tok"}}
    out = talk(request(1, "tools/call", params), toolbox=Progressing())
    values = [m["params"]["progress"] for m in out if m.get("method") == "notifications/progress"]
    assert len(values) == 3
    assert values == sorted(set(values)) and values[0] > 0


def test_f8_the_heartbeat_progress_increases_too(monkeypatch):
    from l4.mcp import server as server_mod

    monkeypatch.setattr(server_mod, "PROGRESS_SECONDS", 0.05)

    class Slow(FakeToolbox):
        def call(self, name, arguments, control):
            control.cancelled.wait(0.4)
            control.progress("explicit")
            return {"content": [], "isError": False}

    params = {"name": "echo", "_meta": {"progressToken": 5}}
    out = talk(request(1, "tools/call", params), toolbox=Slow())
    values = [m["params"]["progress"] for m in out if m.get("method") == "notifications/progress"]
    assert len(values) >= 3
    assert all(a < b for a, b in zip(values, values[1:], strict=False))


def test_f7_instances_for_different_repositories_tell_themselves_apart(repo_factory):
    from l4.cli import redactor_for
    from l4.mcp.repos import Repos
    from l4.mcp.tools import Toolbox

    first, second = repo_factory("alpha"), repo_factory("beta")
    replies = {}
    for root in (first, second):
        repos = Repos.from_paths([root], cwd=Path("/"))
        toolbox = Toolbox(repos=repos, environ={}, redactor=redactor_for({}))
        replies[root.name] = talk(INIT, request(2, "tools/list"), toolbox=toolbox)
    for name, replied in replies.items():
        init, listed = replied[0]["result"], replied[1]["result"]["tools"]
        other = "beta" if name == "alpha" else "alpha"
        assert name in init["serverInfo"]["title"] and other not in init["serverInfo"]["title"]
        assert name in init["instructions"] and other not in init["instructions"]
        assert init["serverInfo"]["name"] == "l4"
        assert all(name in tool["description"] and other not in tool["description"] for tool in listed)


def test_f7_several_repositories_are_all_named(repo_factory):
    from l4.cli import redactor_for
    from l4.mcp.repos import Repos
    from l4.mcp.tools import Toolbox

    roots = [repo_factory("alpha"), repo_factory("beta")]
    toolbox = Toolbox(repos=Repos.from_paths(roots, cwd=Path("/")), environ={}, redactor=redactor_for({}))
    replied = talk(INIT, request(2, "tools/list"), toolbox=toolbox)
    assert "alpha" in replied[0]["result"]["instructions"] and "beta" in replied[0]["result"]["instructions"]
    assert all("alpha" in t["description"] and "beta" in t["description"] for t in replied[1]["result"]["tools"])
