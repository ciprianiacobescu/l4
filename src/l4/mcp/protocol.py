"""The MCP wire format the server speaks: newline-delimited JSON-RPC 2.0 over stdio (L4-MCP-001).

Protocol revision. `PROTOCOL_VERSION` is `2025-11-25`, the last revision with the `initialize` handshake. The current
revision of the specification, `2026-07-28`, replaces that handshake with per-request `_meta` and `server/discover`
(https://modelcontextprotocol.io/specification/versioning, read 2026-10-17); every MCP client in use today still opens
with `initialize`. Its stdio rules (https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/stdio)
say that a dual-era client probes `server/discover` and falls back to `initialize` on any error that is not a modern
one: this server answers `server/discover` with -32601, so such a client falls back.
`initialize` answers the client's revision when it is one of SUPPORTED_VERSIONS, else the pinned one.
"""

import json
from typing import Any

PROTOCOL_VERSION = "2025-11-25"
SUPPORTED_VERSIONS = (PROTOCOL_VERSION, "2025-06-18", "2025-03-26", "2024-11-05")

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603


def negotiate(requested: object) -> str:
    return requested if isinstance(requested, str) and requested in SUPPORTED_VERSIONS else PROTOCOL_VERSION


def error(id_: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


def result(id_: Any, payload: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_, "result": payload}


def notification(method: str, params: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "method": method, "params": params}


def encode(message: dict[str, Any]) -> str:
    """One message, one line: `json.dumps` escapes every newline inside a string."""
    return json.dumps(message, ensure_ascii=False, separators=(",", ":"))


def valid_id(value: object) -> bool:
    return isinstance(value, str | int) and not isinstance(value, bool)
