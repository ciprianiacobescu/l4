"""Read one of this agent's Mintkey secrets by NAME, for other scripts (never prints the value).

    from mintkey_secret import secret_value
    value = secret_value("typesafe-jev-api-key")

Auth: the `mk_agent_…` key from $MINTKEY_AGENT_KEY or ~/.claude.json (mcpServers.mintkey.headers.Authorization).
Endpoint: $MINTKEY_API (default http://localhost:8082) — `GET /v1/tools/secret_list`, `GET /v1/tools/secret_get`.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request


def _agent_key() -> str:
    key = os.environ.get("MINTKEY_AGENT_KEY")
    if key:
        return key
    cfg = json.load(open(os.path.expanduser("~/.claude.json")))
    return cfg["mcpServers"]["mintkey"]["headers"]["Authorization"].split()[-1]


def _get(path: str) -> dict:
    api = os.environ.get("MINTKEY_API", "http://localhost:8082")
    req = urllib.request.Request(f"{api}{path}", headers={"Authorization": f"Bearer {_agent_key()}"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)


def secret_value(name: str) -> str:
    """The plaintext of the secret called `name` (owned or shared); raises KeyError when absent."""
    after = None
    while True:
        page = _get("/v1/tools/secret_list?limit=200" + (f"&after={after}" if after else ""))
        for s in page.get("secrets", []):
            if s.get("name") == name:
                got = _get("/v1/tools/secret_get?secret_id=" + urllib.parse.quote(s["secret_id"]))
                return got["value"]
        after = page.get("next_cursor")
        if not after:
            raise KeyError(f"no Mintkey secret named {name!r}")
