"""A fake `codex app-server` that answers from a recorded session by method."""

import json
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from l4.agents.base import RpcRunner

from .conftest import RECORDED

CODEX = RECORDED / "codex" / "0.160.0"


def recording(name: str) -> dict[str, Any]:
    return json.loads((CODEX / name).read_text())


def fake_rpc(rec: Mapping[str, Any], sent: list[list[Mapping[str, Any]]] | None = None) -> RpcRunner:
    by_method = {
        "initialize": rec.get("initialize"),
        "account/read": rec.get("account_read"),
        "account/rateLimits/read": rec.get("rate_limits_read"),
    }

    def rpc(
        argv: Sequence[str], cwd: Path, env: Mapping[str, str], timeout: float, messages: Sequence[Mapping[str, Any]]
    ):
        if sent is not None:
            sent.append(list(messages))
        return {
            m["id"]: {**by_method[m["method"]], "id": m["id"]}
            for m in messages
            if "id" in m and by_method.get(m["method"]) is not None
        }

    return rpc


def silent_rpc() -> Callable[..., dict]:
    return lambda *a, **k: {}
