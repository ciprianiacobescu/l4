"""The stdio server loop (L4-MCP-001): reads one JSON-RPC message per line, answers on stdout, logs on stderr.

Requests other than `tools/call` are answered at once. A `tools/call` runs on its own thread, so that `ping`,
`notifications/cancelled` (which stops the command and sends no reply, as the specification says) and the progress
notifications that keep a client's timeout from firing during a review of minutes are served meanwhile."""

import json
import logging
import sys
import threading
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Any, Protocol, TextIO

from l4 import __version__
from l4.exitcodes import ExitCode, L4Exit
from l4.mcp import protocol
from l4.mcp.repos import RepoError, Repos
from l4.mcp.tools import CallControl, Toolbox, UnknownTool

log = logging.getLogger("l4.mcp")

PROGRESS_SECONDS = 10.0  # between the progress notifications of a call that carries a progress token
EOF_GRACE_SECONDS = 5.0  # calls still running when the client closes stdin may finish this long, then they are stopped
INSTRUCTIONS = (
    "L4 harness: manage delivery plans and debug units. Read tools never change anything; write tools say in their "
    "description what they write and whether they push to origin. Activating or cancelling a plan is a person's "
    "decision: run `l4 yolo activate` / `l4 yolo cancel` in a terminal."
)


class _Tools(Protocol):
    def specs(self) -> list[dict[str, Any]]: ...

    def call(self, name: str, arguments: dict[str, Any], control: CallControl) -> dict[str, Any]: ...


class Server:
    def __init__(self, tools: _Tools, *, write: Callable[[str], None]) -> None:
        self._tools = tools
        self._write = write
        self._lock = threading.Lock()
        self._inflight: dict[Any, tuple[threading.Thread, threading.Event]] = {}

    # --- output ------------------------------------------------------------------------------------------------
    def _send(self, message: dict[str, Any]) -> None:
        with self._lock:
            self._write(protocol.encode(message))

    # --- loop --------------------------------------------------------------------------------------------------
    def serve(self, lines: Iterable[str]) -> None:
        for line in lines:
            if line.strip():
                self._handle(line)
        self._drain()

    def _drain(self) -> None:
        threads = [thread for thread, _ in list(self._inflight.values())]
        for thread in threads:
            thread.join(EOF_GRACE_SECONDS)
        for _, cancelled in list(self._inflight.values()):
            cancelled.set()
        for thread in threads:
            thread.join()

    def _handle(self, line: str) -> None:
        try:
            message = json.loads(line)
        except (ValueError, RecursionError):
            self._send(protocol.error(None, protocol.PARSE_ERROR, "parse error: the line is not JSON"))
            return
        if not isinstance(message, dict):
            self._send(protocol.error(None, protocol.INVALID_REQUEST, "invalid request: not a JSON object"))
            return
        if "method" not in message:
            return  # a response from the client: this server sends no request, so there is nothing to match
        id_ = message.get("id")
        has_id = "id" in message
        if (
            message.get("jsonrpc") != "2.0"
            or not isinstance(message["method"], str)
            or (has_id and not protocol.valid_id(id_))
        ):
            usable = id_ if has_id and protocol.valid_id(id_) else None
            self._send(protocol.error(usable, protocol.INVALID_REQUEST, "invalid request"))
            return
        params = message.get("params")
        if not has_id:
            self._notification(message["method"], params)
            return
        self._request(id_, message["method"], params)

    def _notification(self, method: str, params: Any) -> None:
        if method == "notifications/cancelled" and isinstance(params, dict):
            entry = self._inflight.get(params.get("requestId"))
            if entry is not None:
                entry[1].set()
        # notifications/initialized and anything else: no reply to a notification

    def _request(self, id_: Any, method: str, params: Any) -> None:
        if method == "ping":
            self._send(protocol.result(id_, {}))
        elif method == "initialize":
            requested = params.get("protocolVersion") if isinstance(params, dict) else None
            if not isinstance(params, dict):
                self._send(protocol.error(id_, protocol.INVALID_PARAMS, "initialize needs params"))
                return
            self._send(
                protocol.result(
                    id_,
                    {
                        "protocolVersion": protocol.negotiate(requested),
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "l4", "version": __version__},
                        "instructions": INSTRUCTIONS,
                    },
                )
            )
        elif method == "tools/list":
            self._send(protocol.result(id_, {"tools": self._tools.specs()}))
        elif method == "tools/call":
            self._call(id_, params)
        else:
            self._send(protocol.error(id_, protocol.METHOD_NOT_FOUND, f"method not found: {method}"))

    # --- tools/call --------------------------------------------------------------------------------------------
    def _call(self, id_: Any, params: Any) -> None:
        if not isinstance(params, dict) or not isinstance(params.get("name"), str):
            self._send(protocol.error(id_, protocol.INVALID_PARAMS, "tools/call needs a tool name"))
            return
        arguments = params.get("arguments", {})
        if arguments is None:
            arguments = {}
        if not isinstance(arguments, dict):
            self._send(protocol.error(id_, protocol.INVALID_PARAMS, "arguments must be an object"))
            return
        if id_ in self._inflight:
            self._send(protocol.error(id_, protocol.INVALID_REQUEST, "a request with this id is still running"))
            return
        meta = params.get("_meta")
        token = meta.get("progressToken") if isinstance(meta, dict) else None
        cancelled = threading.Event()
        done = threading.Event()

        def progress(text: str) -> None:
            if token is not None:
                note = {"progressToken": token, "progress": 0, "message": text}
                self._send(protocol.notification("notifications/progress", note))

        def beat() -> None:
            ticks = 0
            while not done.wait(PROGRESS_SECONDS):
                ticks += 1
                progress(f"still running ({int(ticks * PROGRESS_SECONDS)} s)")

        def work() -> None:
            beater = threading.Thread(target=beat, daemon=True)
            if token is not None:
                beater.start()
            try:
                payload = self._tools.call(params["name"], arguments, CallControl(cancelled, progress))
                reply: dict[str, Any] | None = protocol.result(id_, payload)
            except UnknownTool:
                reply = protocol.error(id_, protocol.INVALID_PARAMS, f"unknown tool: {params['name']}")
            except Exception as exc:
                log.exception("tool %s failed", params["name"])
                text = f"{params['name']} failed inside the server: {type(exc).__name__}: {exc}"
                reply = protocol.result(id_, {"content": [{"type": "text", "text": text}], "isError": True})
            finally:
                done.set()
            self._inflight.pop(id_, None)
            if not cancelled.is_set() and reply is not None:
                self._send(reply)

        thread = threading.Thread(target=work, name=f"mcp-call-{id_}")
        self._inflight[id_] = (thread, cancelled)
        thread.start()


def serve_stdio(tools: Toolbox, stdin: TextIO | None = None, stdout: TextIO | None = None) -> None:
    out = stdout if stdout is not None else sys.stdout

    def write(text: str) -> None:
        out.write(text + "\n")
        out.flush()

    Server(tools, write=write).serve(stdin if stdin is not None else sys.stdin)


def run_serve(app: Any, *, repos: Sequence[Path] = ()) -> ExitCode:
    """`l4 mcp serve`: stdout is the protocol channel and nothing else writes to it (logging goes to stderr).

    Each `--repo` must resolve to a git repository with `.l4/config.yaml` before anything is served (exit 2)."""
    try:
        served = Repos.from_paths(
            [Path(p) for p in repos], cwd=Path(app.repo), project_dir=app.environ.get("CLAUDE_PROJECT_DIR")
        )
    except RepoError as exc:
        raise L4Exit(ExitCode.USAGE_ERROR, f"mcp serve: {exc}") from None
    protocol_out = sys.stdout
    sys.stdout = sys.stderr  # a stray print in any dependency can no longer corrupt the protocol stream
    try:
        serve_stdio(Toolbox(repos=served, environ=app.environ, redactor=app.redactor), stdout=protocol_out)
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout = protocol_out
    return ExitCode.OK
