"""The server against the official MCP client package (dev dependency only; skipped when it is absent)."""

import asyncio
import sys

import pytest

mcp = pytest.importorskip("mcp")

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

from l4 import __version__  # noqa: E402


def test_the_official_client_connects_lists_the_tools_and_calls_one(repo_factory):
    root = repo_factory("interop")

    def field(obj, snake, camel):  # mcp 1.x names are camelCase, 2.x snake_case
        return getattr(obj, snake) if hasattr(obj, snake) else getattr(obj, camel)

    async def session() -> tuple[str, list[str], bool]:
        params = StdioServerParameters(command=sys.executable, args=["-m", "l4", "mcp", "serve", "--repo", str(root)])
        async with stdio_client(params) as (read, write), ClientSession(read, write) as client:
            init = await client.initialize()
            tools = await client.list_tools()
            result = await client.call_tool("l4_doctor", {"repo": "interop"})
            return (
                field(init, "server_info", "serverInfo").version,
                [t.name for t in tools.tools],
                field(result, "is_error", "isError"),
            )

    version, names, is_error = asyncio.run(asyncio.wait_for(session(), 120))
    assert version == __version__
    assert "l4_status" in names and "l4_plan_check" in names
    assert is_error is True  # doctor exits non-zero on a bare repository: the call came back as an error result
