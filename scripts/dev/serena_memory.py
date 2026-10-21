"""Read and write this repository's Serena memories through Serena's own MCP server.

Starts the exact server command registered in .mcp.json (serena-agent pinned there), so memories are written the same
way an MCP client (Claude Code, Codex, OpenCode …) would write them.

    uv run --no-project -p 3.13 --with mcp==1.28.1 python scripts/dev/serena_memory.py list
    uv run --no-project -p 3.13 --with mcp==1.28.1 python scripts/dev/serena_memory.py read  <name>
    uv run --no-project -p 3.13 --with mcp==1.28.1 python scripts/dev/serena_memory.py write <name> <file.md | ->

Memories are plain Markdown files under .serena/memories/<name>.md (a "/" in the name is a subdirectory).
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

REPO = Path(__file__).resolve().parents[2]


def server_params() -> StdioServerParameters:
    cfg = json.loads((REPO / ".mcp.json").read_text())["mcpServers"]["serena"]
    return StdioServerParameters(command=cfg["command"], args=cfg["args"], cwd=str(REPO), env=None)


def text_of(result) -> str:
    if result.isError:
        raise SystemExit("serena error: " + " ".join(c.text for c in result.content if hasattr(c, "text")))
    return "\n".join(c.text for c in result.content if hasattr(c, "text"))


async def main(argv: list[str]) -> None:
    if not argv or argv[0] not in {"list", "read", "write"}:
        raise SystemExit(__doc__)
    async with stdio_client(server_params()) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        if argv[0] == "list":
            print(text_of(await session.call_tool("list_memories", {})))
        elif argv[0] == "read":
            print(text_of(await session.call_tool("read_memory", {"memory_name": argv[1]})))
        else:
            name, src = argv[1], argv[2]
            content = sys.stdin.read() if src == "-" else Path(src).read_text(encoding="utf-8")
            print(text_of(await session.call_tool("write_memory", {"memory_name": name, "content": content})))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
