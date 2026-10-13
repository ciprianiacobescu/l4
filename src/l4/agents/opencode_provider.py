"""A custom OpenAI-compatible provider of an opencode profile (magnitude, 2026-10-06 investigation).

The key never rides in the sandbox environment: `--setenv NAME VALUE` lands in bwrap's argv, readable by any local
user (`l4.sandbox.env`), and `OPENCODE_CONFIG_CONTENT` is an environment value too. The adapter writes the key to a
0600 file in the step's private directory and the config says `{file:<path>}` [V: works under `env -i`, investigation].
Everything here is value-free in what it returns or raises: a key, a URL's credentials and a file's text never leave.
"""

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from l4.agents.base import AdapterError
from l4.config.schema import OpencodeOptions

KEY_FILE = "provider.key"
NPM_PACKAGE = "@ai-sdk/openai-compatible"
REACH_TIMEOUT_S = 3.0
TRANSPORT: httpx.BaseTransport | None = None  # unit tests only


def provider_host(base_url: str) -> str:
    """`host:port` of the provider, for logs and the doctor row: no scheme, path, credentials or query."""
    parts = urlsplit(base_url)
    host = parts.hostname or "?"
    return f"{host}:{parts.port}" if parts.port else host


def reachable(base_url: str, *, timeout_s: float = REACH_TIMEOUT_S) -> tuple[bool, str]:
    """`GET <base_url>/models` without any credential. Any HTTP answer (a 401 included) means the host is up: this
    checks the machine, not the key. A sleeping MacBook (connect error or timeout) is `unreachable`, which the caller
    treats as "unavailable, fall back", never as a failure of the run. The reason never repeats the URL."""
    try:
        with httpx.Client(timeout=timeout_s, trust_env=False, transport=TRANSPORT) as client:
            answer = client.get(f"{base_url.rstrip('/')}/models")
    except httpx.TimeoutException:
        return False, f"{provider_host(base_url)} did not answer within {timeout_s:g}s (is the machine asleep?)"
    except httpx.HTTPError:
        return False, f"{provider_host(base_url)} is unreachable (connection failed)"
    return True, f"{provider_host(base_url)} answered HTTP {answer.status_code}"


def write_key_file(directory: Path, key: str) -> Path:
    """The key in a new 0600 file (never an existing one, never a symlink). The caller removes it after the run."""
    path = directory / KEY_FILE
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(key)
    return path


def key_from(host_env: Mapping[str, str], options: OpencodeOptions) -> str:
    """The key out of the harness's environment, or an `AdapterError` naming the VARIABLE (never a value)."""
    assert options.provider is not None
    name = options.provider.api_key_env
    key = (host_env.get(name) or "").strip()
    if not key:
        raise AdapterError(f"the variable {name} (profile provider key) is not set in the harness environment")
    return key


def provider_config(options: OpencodeOptions, model: str, key_path: Path) -> dict[str, Any]:
    """`provider.<id>` for `OPENCODE_CONFIG_CONTENT`: the OpenAI-compatible package, the base URL, the key as a file
    reference, and the model entry (tool calls on, token limits, reasoning effort)."""
    provider = options.provider
    assert provider is not None
    model_id = model.split("/", 1)[1]
    limits = provider.models[model_id]
    entry: dict[str, Any] = {
        "name": model_id, "tool_call": True, "limit": {"context": limits.context, "output": limits.output},
    }  # fmt: skip
    if options.reasoning is not None:
        entry["options"] = {"reasoningEffort": options.reasoning}
    return {
        provider.id: {
            "npm": NPM_PACKAGE, "name": provider.id,
            "options": {"baseURL": provider.base_url, "apiKey": f"{{file:{key_path}}}"},
            "models": {model_id: entry},
        }
    }  # fmt: skip
