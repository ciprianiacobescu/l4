"""`l4 mcp install` (L4-MCP-004): write the MCP configuration of a client so that it starts
`l4 mcp serve --repo <repository>` (user scope) or `l4 mcp serve` (project scope: the file is committed, so it holds
no path of this machine and every clone and worktree serves its own folder).

Every path and shape below was checked against the vendor's documentation on 2026-10-17 (the URL is kept beside each
client). The write merges into the file, keeps every other server, is atomic and refuses a file that does not parse.
Clients whose documentation could not confirm a file are not offered: see CLIENTS.

Left out, and why:
- Windsurf: its MCP page now redirects to the Devin desktop documentation (https://docs.devin.ai/desktop/cascade/mcp),
  which names `~/.config/devin/mcp_config.json`, not a Windsurf file; no vendor page confirms a Windsurf path.
- VS Code user scope: the documentation gives no path for the user profile file ("MCP: Open User Configuration").
- Claude Code user scope: it lives in `~/.claude.json`, which holds all of the client's state; the documented
  `claude mcp add --scope user` command is printed instead of editing that file.
"""

import json
import os
import re
import tempfile
import tomllib
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import click

from l4.context import AppContext
from l4.exitcodes import ExitCode, L4Exit
from l4.fsutil import UnsafeFile, reject_symlinks
from l4.mcp.repos import RepoError, resolve_root

NAME = re.compile(r"[A-Za-z0-9_-]+")
COMMAND = "l4"


def server_args(repo: Path | None) -> list[str]:
    """`--repo` only for a user-scope entry: a project file is committed and must not name a path of this machine."""
    return ["mcp", "serve", *(["--repo", str(repo)] if repo is not None else [])]


# --- JSON clients --------------------------------------------------------------------------------------------------


def _stdio(repo: Path | None, *, typed: bool) -> dict[str, Any]:
    return {**({"type": "stdio"} if typed else {}), "command": COMMAND, "args": server_args(repo)}


def _opencode(repo: Path | None, *, typed: bool = True) -> dict[str, Any]:
    return {"type": "local", "command": [COMMAND, *server_args(repo)], "enabled": True}


@dataclass(frozen=True)
class JsonClient:
    key: str  # the object that holds the servers
    entry: Callable[..., dict[str, Any]]
    typed: bool
    project: str  # relative to the repository
    user: str | None  # relative to the home folder
    source: str  # the vendor documentation
    schema: str | None = None


CLIENTS: dict[str, JsonClient | str] = {
    # https://code.claude.com/docs/en/mcp: project scope `.mcp.json` {"mcpServers": {name: {"type": "stdio",
    # "command", "args", "env"}}}; user scope is `~/.claude.json` (all state): the documented command is printed.
    "claude-code": JsonClient("mcpServers", _stdio, True, ".mcp.json", None, "https://code.claude.com/docs/en/mcp"),
    # https://cursor.com/docs/context/mcp: `.cursor/mcp.json` (project), `~/.cursor/mcp.json` (global)
    "cursor": JsonClient(
        "mcpServers", _stdio, True, ".cursor/mcp.json", ".cursor/mcp.json", "https://cursor.com/docs/context/mcp"
    ),
    # https://code.visualstudio.com/docs/copilot/customization/mcp-servers: `.vscode/mcp.json`, top-level "servers",
    # "type": "stdio"; no documented path for the user profile file.
    "vscode": JsonClient(
        "servers",
        _stdio,
        True,
        ".vscode/mcp.json",
        None,
        "https://code.visualstudio.com/docs/copilot/customization/mcp-servers",
    ),  # fmt: skip
    # https://kiro.dev/docs/mcp/configuration/: `.kiro/settings/mcp.json` (workspace) and `~/.kiro/settings/mcp.json`
    "kiro": JsonClient(
        "mcpServers",
        _stdio,
        False,
        ".kiro/settings/mcp.json",
        ".kiro/settings/mcp.json",
        "https://kiro.dev/docs/mcp/configuration/",
    ),  # fmt: skip
    # https://opencode.ai/docs/mcp-servers/ ("mcp": {name: {"type": "local", "command": [argv...], "enabled"}}) and
    # https://opencode.ai/docs/config/ (`opencode.json` in the project root, `~/.config/opencode/opencode.json`)
    "opencode": JsonClient(
        "mcp",
        _opencode,
        True,
        "opencode.json",
        ".config/opencode/opencode.json",
        "https://opencode.ai/docs/mcp-servers/",
        schema="https://opencode.ai/config.json",
    ),  # fmt: skip
    # https://learn.chatgpt.com/docs/extend/mcp?surface=cli (formerly developers.openai.com/codex/mcp):
    # `~/.codex/config.toml`, project `.codex/config.toml` (trusted projects), `[mcp_servers.<name>]` command, args
    "codex": "codex",
}
CODEX_PROJECT, CODEX_USER = ".codex/config.toml", ".codex/config.toml"
CLIENT_NAMES = tuple(CLIENTS)


class ConfigRefused(Exception):
    """The file cannot be merged safely: it is left untouched (exit 2)."""


# --- writing -------------------------------------------------------------------------------------------------------


def write_atomic(path: Path, text: str, *, follow_symlink: bool = True) -> None:
    """Replace `path` atomically. A symlink is followed only for a user-scope file (dotfile setups); a file inside a
    repository is never followed (the caller has refused symlinks there)."""
    target = path.resolve() if follow_symlink and path.is_symlink() else path
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temp = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            out.write(text)
        if target.exists():
            os.chmod(temp, target.stat().st_mode & 0o777)
        os.replace(temp, target)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


def repo_of(args: Any) -> str | None:
    """The `--repo` value in an argv list, or None."""
    if isinstance(args, list) and "--repo" in args:
        at = args.index("--repo")
        if at + 1 < len(args) and isinstance(args[at + 1], str):
            return args[at + 1]
    return None


def check_same_repository(where: Path, name: str, existing: str | None, repo: Path) -> None:
    """An entry of that name that serves another repository is never replaced (two folders can share a name)."""
    if existing is None:
        return
    try:
        same = Path(existing).expanduser().resolve() == repo.resolve()
    except (OSError, RuntimeError):
        same = False
    if not same:
        raise ConfigRefused(
            f"{where}: the entry {name!r} already serves {existing}, not {repo}; nothing written "
            f"(choose another entry with --name, e.g. --name {name}-2)"
        )


def merge_json(path: Path, client: JsonClient, name: str, entry: dict[str, Any], repo: Path) -> str:
    data: dict[str, Any] = {}
    if path.exists():
        raw = path.read_text(encoding="utf-8")
        if raw.strip():
            try:
                data = json.loads(raw)
            except ValueError as exc:
                raise ConfigRefused(f"{path}: not valid JSON ({exc}); nothing written") from None
        if not isinstance(data, dict):
            raise ConfigRefused(f"{path}: not a JSON object; nothing written")
    elif client.schema:
        data = {"$schema": client.schema}
    servers = data.setdefault(client.key, {})
    if not isinstance(servers, dict):
        raise ConfigRefused(f'{path}: "{client.key}" is not an object; nothing written')
    old = servers.get(name)
    if isinstance(old, dict):
        argv = old.get("command") if isinstance(old.get("command"), list) else old.get("args")
        check_same_repository(path, name, repo_of(argv), repo)
        kept = {k: v for k, v in old.items() if k not in entry or k == "enabled"}  # the user's own keys stay
        servers[name] = {**entry, **kept}
    else:
        servers[name] = entry
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


_HEADER = re.compile(r"^\s*(\[\[?.*?\]\]?)\s*(#.*)?$")


def _header_path(line: str) -> tuple[str, ...] | None:
    found = _HEADER.match(line)
    if not found:
        return None
    try:
        node: Any = tomllib.loads(found.group(1))
    except tomllib.TOMLDecodeError:
        return None
    path: list[str] = []
    while isinstance(node, dict) and len(node) == 1:
        ((key, node),) = node.items()
        path.append(key)
    if isinstance(node, list):  # [[array.of.tables]]
        pass
    return tuple(path)


def _toml_value(value: Any, where: Path) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(v, where) for v in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(f"{json.dumps(str(k))} = {_toml_value(v, where)}" for k, v in value.items()) + " }"
    raise ConfigRefused(f"{where}: a value of type {type(value).__name__} cannot be kept; nothing written")


def merge_toml(path: Path, name: str, repo: Path, *, with_repo: bool) -> str:
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    try:
        before = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigRefused(f"{path}: not valid TOML ({exc}); nothing written") from None
    if not isinstance(before.get("mcp_servers", {}), dict):
        raise ConfigRefused(f"{path}: mcp_servers is not a table; nothing written")
    old = before.get("mcp_servers", {}).get(name)
    if old is not None and not isinstance(old, dict):
        raise ConfigRefused(f"{path}: mcp_servers.{name} is not a table; nothing written")
    old = old or {}
    check_same_repository(path, name, repo_of(old.get("args")), repo)
    kept: list[str] = []
    subtables: set[str] = set()
    skipping = False
    for line in text.splitlines(keepends=True):
        header = _header_path(line)
        if header is not None:
            skipping = header == ("mcp_servers", name)  # only this table; its subtables ([...l4.env]) stay
            if len(header) > 2 and header[:2] == ("mcp_servers", name):
                subtables.add(header[2])
        if not skipping:
            kept.append(line)
    argv = server_args(repo if with_repo else None)
    extra = {k: v for k, v in old.items() if k not in ("command", "args") and k not in subtables}
    base = "".join(kept).rstrip("\n")
    block = f"[mcp_servers.{name}]\ncommand = {json.dumps(COMMAND)}\nargs = {json.dumps(argv)}\n"
    block += "".join(f"{json.dumps(str(k))} = {_toml_value(v, path)}\n" for k, v in extra.items())
    result = (base + "\n\n" if base else "") + block
    expected = {**{k: v for k, v in old.items() if k not in ("command", "args")}, "command": COMMAND, "args": argv}
    try:
        after = tomllib.loads(result)
    except tomllib.TOMLDecodeError as exc:
        raise ConfigRefused(f"{path}: the merged file would not parse ({exc}); nothing written") from None
    others_before = {k: v for k, v in before.get("mcp_servers", {}).items() if k != name}
    others_after = {k: v for k, v in after.get("mcp_servers", {}).items() if k != name}
    rest_before = {k: v for k, v in before.items() if k != "mcp_servers"}
    rest_after = {k: v for k, v in after.items() if k != "mcp_servers"}
    if after.get("mcp_servers", {}).get(name) != expected or others_before != others_after or rest_before != rest_after:
        raise ConfigRefused(f"{path}: the file could not be merged without changing something else; nothing written")
    return result


# --- the command ---------------------------------------------------------------------------------------------------


def entry_name(repo: Path, *, project: bool, name: str | None) -> str:
    if name is not None:
        if not NAME.fullmatch(name):
            raise L4Exit(ExitCode.USAGE_ERROR, f"mcp install: --name {name!r}: use letters, digits, - and _")
        return name
    if project:
        return "l4"
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "-", repo.name).strip("-")
    return f"l4-{cleaned or 'repo'}"


def _refuse_symlinks(repo: Path, relative: str) -> None:
    """A file inside the repository is repository content, so it is untrusted: a committed symlink (on the file or on
    a folder above it) would send the write, or the merge, outside the repository."""
    reject_symlinks(repo, *Path(relative).parts)


def _home(environ: Mapping[str, str]) -> Path:
    return Path(environ.get("HOME") or Path.home())


def run_install(
    app: AppContext, *, client: str, project: bool, target_repo: Path | None, entry: str | None, dry_run: bool
) -> ExitCode:
    try:
        repo = resolve_root(target_repo if target_repo is not None else app.repo)
    except RepoError as exc:
        raise L4Exit(ExitCode.USAGE_ERROR, f"mcp install: {exc}") from None
    name = entry_name(repo, project=project, name=entry)
    spec = CLIENTS[client]
    scope = "project" if project else "user"
    served = None if project else repo  # a project file is committed: no path of this machine, the folder decides
    if client == "codex":
        path = repo / CODEX_PROJECT if project else _home(app.environ) / CODEX_USER
        try:
            if project:
                _refuse_symlinks(repo, CODEX_PROJECT)
            text = merge_toml(path, name, repo, with_repo=not project)
        except (ConfigRefused, UnsafeFile) as exc:
            raise L4Exit(ExitCode.USAGE_ERROR, f"mcp install: {exc}") from None
        shown = f"[mcp_servers.{name}]\ncommand = {json.dumps(COMMAND)}\nargs = {json.dumps(server_args(served))}"
    else:
        assert isinstance(spec, JsonClient)
        if not project and spec.user is None:
            if client == "claude-code":
                line = (
                    f"claude mcp add --transport stdio --scope user {name} -- {COMMAND} {' '.join(server_args(repo))}"
                )
                click.echo(
                    "Claude Code keeps user-scope servers in ~/.claude.json, which holds all of its state, so l4 "
                    f"does not edit it. Run this (documented at {spec.source}):\n{line}\n"
                    "or use --project to write .mcp.json in the repository."
                )
                return ExitCode.OK
            raise L4Exit(
                ExitCode.USAGE_ERROR,
                f"mcp install: {client} has no documented user configuration file; use --project",
            )
        path = repo / spec.project if project else _home(app.environ) / str(spec.user)
        try:
            if project:
                _refuse_symlinks(repo, spec.project)
            text = merge_json(path, spec, name, spec.entry(served, typed=spec.typed), repo)
        except (ConfigRefused, UnsafeFile) as exc:
            raise L4Exit(ExitCode.USAGE_ERROR, f"mcp install: {exc}") from None
        shown = json.dumps({spec.key: {name: spec.entry(served, typed=spec.typed)}}, indent=2)
    if dry_run:
        click.echo(
            f"dry run: would write {path} ({client}, {scope} scope); nothing written.\n{shown}\n\nresult:\n{text}"
        )
        return ExitCode.OK
    write_atomic(path, text, follow_symlink=not project)
    click.echo(
        f"wrote {path} ({client}, {scope} scope): entry {name!r} runs "
        f"`{COMMAND} {' '.join(server_args(served))}`\n{shown}"
    )
    return ExitCode.OK
