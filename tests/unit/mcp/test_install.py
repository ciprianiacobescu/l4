"""`l4 mcp install` writes a client's documented MCP configuration (L4-MCP-004, SCN-MCP-08, SCN-MCP-09)."""

import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from l4.cli import main

from .conftest import make_repo

ALL = ["claude-code", "cursor", "vscode", "kiro", "codex", "opencode"]


@pytest.fixture
def home(tmp_path: Path) -> Path:
    path = tmp_path / "home"
    path.mkdir()
    return path


def install(home: Path, *argv: str) -> int:
    env = {"HOME": str(home), "PATH": "/usr/bin"}
    return main(["mcp", "install", *argv], environ=env)


def read(path: Path):
    return tomllib.loads(path.read_text()) if path.suffix == ".toml" else json.loads(path.read_text())


def entry_of(client: str, data: dict, name: str):
    key = {"vscode": "servers", "opencode": "mcp", "codex": "mcp_servers"}.get(client, "mcpServers")
    return data[key][name]


def command_of(client: str, entry: dict) -> list[str]:
    return [*entry["command"]] if client == "opencode" else [entry["command"], *entry["args"]]


PROJECT_FILE = {
    "claude-code": ".mcp.json",
    "cursor": ".cursor/mcp.json",
    "vscode": ".vscode/mcp.json",
    "kiro": ".kiro/settings/mcp.json",
    "codex": ".codex/config.toml",
    "opencode": "opencode.json",
}
USER_FILE = {
    "cursor": ".cursor/mcp.json",
    "kiro": ".kiro/settings/mcp.json",
    "codex": ".codex/config.toml",
    "opencode": ".config/opencode/opencode.json",
}


PROJECT_ARGS = {"cursor": ["mcp", "serve", "--repo", "${workspaceFolder}"]}  # M2: the others start in the folder


@pytest.mark.parametrize("client", [c for c in ALL if c != "kiro"])
def test_project_scope_writes_the_documented_file_with_the_serve_command(client, repo_factory, home):
    root = repo_factory("mint-mory")
    assert install(home, "--client", client, "--project", "--repo", str(root)) == 0
    entry = entry_of(client, read(root / PROJECT_FILE[client]), "l4")  # the project entry is named l4
    # no path of this machine: the file is committed (F1)
    assert command_of(client, entry) == ["l4", *PROJECT_ARGS.get(client, ["mcp", "serve"])]
    assert not (home / ".mcp.json").exists()


@pytest.mark.parametrize("client", sorted(USER_FILE))
def test_user_scope_names_the_entry_after_the_repository(client, repo_factory, home):
    root = repo_factory("mint-mory")
    assert install(home, "--client", client, "--repo", str(root)) == 0
    entry = entry_of(client, read(home / USER_FILE[client]), "l4-mint-mory")
    assert command_of(client, entry) == ["l4", "mcp", "serve", "--repo", str(root)]


@pytest.mark.parametrize("client", sorted(USER_FILE))
def test_a_second_repository_adds_an_entry_and_keeps_the_others(client, repo_factory, home):  # SCN-MCP-08
    first, second = repo_factory("mint-mory"), repo_factory("mintkey")
    path = home / USER_FILE[client]
    path.parent.mkdir(parents=True)
    if client == "codex":
        path.write_text('model = "x"  # keep me\n\n[mcp_servers.other]\ncommand = "other"\nargs = ["a"]\n')
    else:
        key = {"opencode": "mcp"}.get(client, "mcpServers")
        path.write_text(json.dumps({"theme": "dark", key: {"other": {"command": "other"}}}))
    assert install(home, "--client", client, "--repo", str(first)) == 0
    before = read(path)
    assert install(home, "--client", client, "--repo", str(second)) == 0
    after = read(path)
    assert command_of(client, entry_of(client, after, "l4-mintkey"))[-1] == str(second)
    assert entry_of(client, after, "l4-mint-mory") == entry_of(client, before, "l4-mint-mory")
    assert entry_of(client, after, "other") == entry_of(client, before, "other")
    if client == "codex":
        assert after["model"] == "x" and "# keep me" in path.read_text()
    else:
        assert after["theme"] == "dark"


def test_the_same_name_is_replaced_not_duplicated(repo_factory, home):
    root = repo_factory("mint-mory")
    for _ in range(2):
        assert install(home, "--client", "cursor", "--repo", str(root)) == 0
    assert list(read(home / ".cursor/mcp.json")["mcpServers"]) == ["l4-mint-mory"]
    path = home / ".codex/config.toml"
    for _ in range(2):
        assert install(home, "--client", "codex", "--repo", str(root)) == 0
    assert path.read_text().count("[mcp_servers.l4-mint-mory]") == 1


def test_codex_replace_keeps_the_text_around_the_table(repo_factory, home):
    root = repo_factory("mint-mory")
    path = home / ".codex/config.toml"
    path.parent.mkdir(parents=True)
    path.write_text(
        '# my codex\nmodel = "x"\n\n[mcp_servers.l4-mint-mory]\ncommand = "old"\n'
        '[mcp_servers.l4-mint-mory.env]\nA = "1"\n'
        '\n[mcp_servers.after]\ncommand = "after"\n\n[profiles.p]\nmodel = "y"\n'
    )
    assert install(home, "--client", "codex", "--repo", str(root)) == 0
    text = path.read_text()
    data = tomllib.loads(text)
    assert text.startswith("# my codex\n")
    assert data["mcp_servers"]["l4-mint-mory"] == {
        "command": "l4",
        "args": ["mcp", "serve", "--repo", str(root)],
        "env": {"A": "1"},  # the user's own subtable stays (F2)
    }
    assert data["mcp_servers"]["after"] == {"command": "after"} and data["profiles"]["p"] == {"model": "y"}


def test_name_overrides_the_default(repo_factory, home):
    root = repo_factory("mint-mory")
    assert install(home, "--client", "kiro", "--repo", str(root), "--name", "memory") == 0
    assert list(read(home / ".kiro/settings/mcp.json")["mcpServers"]) == ["memory"]
    assert install(home, "--client", "cursor", "--project", "--repo", str(root), "--name", "mm") == 0
    assert list(read(root / ".cursor/mcp.json")["mcpServers"]) == ["mm"]


def test_a_folder_name_that_is_not_a_valid_entry_name_is_cleaned(repo_factory, home):
    root = repo_factory("my repo.v2")
    assert install(home, "--client", "cursor", "--repo", str(root)) == 0
    assert list(read(home / ".cursor/mcp.json")["mcpServers"]) == ["l4-my-repo-v2"]


@pytest.mark.parametrize("bad", ["", "a b", "a.b", "../x", "a\nb"])
def test_a_bad_name_is_refused(repo_factory, home, bad):
    root = repo_factory("r")
    assert install(home, "--client", "cursor", "--repo", str(root), "--name", bad) == 2
    assert not (home / ".cursor").exists()


def test_the_default_repository_is_the_working_directorys(repo_factory, home, monkeypatch):
    root = repo_factory("here")
    (root / "sub").mkdir()
    monkeypatch.chdir(root / "sub")
    assert install(home, "--client", "cursor", "--project") == 0
    assert read(root / ".cursor/mcp.json")["mcpServers"]["l4"]["args"] == PROJECT_ARGS["cursor"]
    assert install(home, "--client", "cursor") == 0  # user scope: the working directory's repository, by path
    assert read(home / ".cursor/mcp.json")["mcpServers"]["l4-here"]["args"][-1] == str(root)


def test_a_repository_that_is_not_an_l4_repository_is_refused(tmp_path, repo_factory, home, capsys):
    assert install(home, "--client", "cursor", "--repo", str(tmp_path)) == 2
    assert install(home, "--client", "cursor", "--repo", str(repo_factory("plain", l4=False))) == 2
    assert not (home / ".cursor").exists()


@pytest.mark.parametrize("client", ["cursor", "codex", "opencode", "claude-code"])
def test_an_unparseable_file_is_not_overwritten(client, repo_factory, home, capsys):  # SCN-MCP-09
    root = repo_factory("r")
    path = root / PROJECT_FILE[client]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ this is = not valid [")
    assert install(home, "--client", client, "--project", "--repo", str(root)) == 2
    assert path.read_text() == "{ this is = not valid ["
    assert str(path) in capsys.readouterr().err
    assert not [p for p in path.parent.iterdir() if p.name.startswith(f".{path.name}.")]  # no temp file


def test_a_container_of_the_wrong_type_is_refused_untouched(repo_factory, home, capsys):
    root = repo_factory("r")
    path = root / ".cursor/mcp.json"
    path.parent.mkdir()
    path.write_text('{"mcpServers": []}')
    assert install(home, "--client", "cursor", "--project", "--repo", str(root)) == 2
    assert path.read_text() == '{"mcpServers": []}'


def test_dry_run_prints_the_result_and_writes_nothing(repo_factory, home, capsys):
    root = repo_factory("mint-mory")
    assert install(home, "--client", "cursor", "--repo", str(root), "--dry-run") == 0
    out = capsys.readouterr().out
    assert str(home / ".cursor/mcp.json") in out and '"l4-mint-mory"' in out
    assert not (home / ".cursor").exists()


def test_the_output_says_what_was_written(repo_factory, home, capsys):
    root = repo_factory("mint-mory")
    assert install(home, "--client", "codex", "--project", "--repo", str(root)) == 0
    out = capsys.readouterr().out
    assert str(root / ".codex/config.toml") in out and "[mcp_servers.l4]" in out


def test_no_temporary_file_is_left_behind(repo_factory, home):
    root = repo_factory("r")
    assert install(home, "--client", "cursor", "--project", "--repo", str(root)) == 0
    assert [p.name for p in (root / ".cursor").iterdir()] == ["mcp.json"]


def test_vscode_has_no_user_scope(repo_factory, home, capsys):
    root = repo_factory("r")
    assert install(home, "--client", "vscode", "--repo", str(root)) == 2
    assert "--project" in capsys.readouterr().err


def test_claude_code_user_scope_prints_the_documented_command_and_writes_nothing(repo_factory, home, capsys):
    root = repo_factory("mint-mory")
    assert install(home, "--client", "claude-code", "--repo", str(root)) == 0
    out = capsys.readouterr().out
    assert f"claude mcp add --transport stdio --scope user l4-mint-mory -- l4 mcp serve --repo {root}" in out
    assert list(home.iterdir()) == []


def test_an_unknown_client_is_refused(repo_factory, home):
    assert install(home, "--client", "windsurf", "--repo", str(repo_factory("r"))) == 2


# --- review findings F1, F2, F3 ------------------------------------------------------------------------------------


def git(cwd: Path, *argv: str) -> str:
    done = subprocess.run(["git", "-C", str(cwd), *argv], capture_output=True, text=True, check=True)
    return done.stdout


def serve_status(cwd: Path, args: list[str], env: dict[str, str] | None = None) -> str:
    """Start `l4 mcp serve <args>` in `cwd`, call l4_status without a repo argument, return the result text."""
    lines = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "l4_status", "arguments": {}}},
    ]
    done = subprocess.run(
        [sys.executable, "-m", "l4", *args],
        input="".join(json.dumps(m) + "\n" for m in lines),
        capture_output=True,
        text=True,
        cwd=cwd,
        env={**os.environ, **(env or {})},
        timeout=120,
        check=False,
    )
    replies = [json.loads(line) for line in done.stdout.splitlines() if line.strip()]
    call = next(r for r in replies if r.get("id") == 2)
    return call["result"]["content"][0]["text"]


@pytest.mark.parametrize("client", [c for c in ALL if c != "kiro"])
def test_f1_project_scope_writes_no_absolute_path(client, repo_factory, home):
    root = repo_factory("mint-mory")
    assert install(home, "--client", client, "--project", "--repo", str(root)) == 0
    entry = entry_of(client, read(root / PROJECT_FILE[client]), "l4")
    assert command_of(client, entry) == ["l4", *PROJECT_ARGS.get(client, ["mcp", "serve"])]
    assert str(root) not in (root / PROJECT_FILE[client]).read_text()


def test_f1_a_worktree_started_from_the_committed_file_serves_the_worktree(repo_factory, home, tmp_path):
    root = repo_factory("mint-mory")
    git(root, "config", "user.email", "t@example.com")
    git(root, "config", "user.name", "t")
    assert install(home, "--client", "claude-code", "--project", "--repo", str(root)) == 0
    git(root, "add", ".mcp.json", ".l4/config.yaml")
    git(root, "commit", "-q", "-m", "mcp")
    tree = tmp_path / "wt" / "feature"
    git(root, "worktree", "add", "-q", str(tree), "-b", "feature")
    args = json.loads((tree / ".mcp.json").read_text())["mcpServers"]["l4"]["args"]
    text = serve_status(tree, args)
    assert text.splitlines()[0] == f"repo: {tree.resolve()}"


def test_f1_claude_project_dir_wins_over_the_working_directory(repo_factory, tmp_path):
    root = repo_factory("one")
    other = repo_factory("two")
    text = serve_status(root, ["mcp", "serve"], {"CLAUDE_PROJECT_DIR": str(other)})
    assert text.splitlines()[0] == f"repo: {other}"


def test_f2_two_repositories_with_the_same_folder_name_are_not_merged(tmp_path, home, capsys):
    first = make_repo(tmp_path / "clones" / "work" / "app")
    second = make_repo(tmp_path / "clones" / "oss" / "app")
    for client in ("cursor", "codex"):
        assert install(home, "--client", client, "--repo", str(first)) == 0
        assert install(home, "--client", client, "--repo", str(second)) == 2
        err = capsys.readouterr().err
        assert str(first) in err and str(second) in err and "--name" in err
        data = read(home / USER_FILE[client])
        assert command_of(client, entry_of(client, data, "l4-app"))[-1] == str(first)
        # an explicit name keeps both
        assert install(home, "--client", client, "--repo", str(second), "--name", "l4-oss-app") == 0
        data = read(home / USER_FILE[client])
        assert command_of(client, entry_of(client, data, "l4-app"))[-1] == str(first)
        assert command_of(client, entry_of(client, data, "l4-oss-app"))[-1] == str(second)


def test_f2_a_reinstall_for_the_same_repository_keeps_the_users_other_keys(repo_factory, home):
    root = repo_factory("app")
    path = home / ".cursor/mcp.json"
    path.parent.mkdir(parents=True)
    old = {"command": "old", "args": ["mcp", "serve", "--repo", str(root)], "env": {"A": "1"}, "disabled": True}
    path.write_text(json.dumps({"mcpServers": {"l4-app": old}}))
    assert install(home, "--client", "cursor", "--repo", str(root)) == 0
    entry = read(path)["mcpServers"]["l4-app"]
    assert entry["command"] == "l4" and entry["env"] == {"A": "1"} and entry["disabled"] is True
    codex = home / ".codex/config.toml"
    codex.parent.mkdir(parents=True)
    codex.write_text(
        f'[mcp_servers.l4-app]\ncommand = "old"\nargs = ["mcp", "serve", "--repo", {json.dumps(str(root))}]\n'
        'startup_timeout_sec = 30\n[mcp_servers.l4-app.env]\nA = "1"\n'
    )
    assert install(home, "--client", "codex", "--repo", str(root)) == 0
    table = read(codex)["mcp_servers"]["l4-app"]
    assert table["command"] == "l4" and table["env"] == {"A": "1"} and table["startup_timeout_sec"] == 30
    assert table["args"] == ["mcp", "serve", "--repo", str(root)]


def commit_symlink(root: Path, link: str, target: str) -> None:
    (root / link).parent.mkdir(parents=True, exist_ok=True)
    (root / link).symlink_to(target)
    git(root, "add", link)


def test_f3_project_install_refuses_a_committed_symlink_to_a_file_outside(repo_factory, home, capsys):
    root = repo_factory("evil")
    claude = home / ".claude.json"
    claude.write_text('{"numStartups": 3, "projects": {}}')
    commit_symlink(root, ".mcp.json", os.path.relpath(claude, root))
    before = claude.read_text()
    assert install(home, "--client", "claude-code", "--project", "--repo", str(root)) == 2
    assert "symlink" in capsys.readouterr().err
    assert claude.read_text() == before


def test_f3_project_install_refuses_a_dangling_symlink_and_creates_nothing(repo_factory, home, tmp_path, capsys):
    root = repo_factory("evil")
    outside = tmp_path / "outside" / "planted" / "autostart.json"
    commit_symlink(root, ".cursor/mcp.json", os.path.relpath(outside, root / ".cursor"))
    assert install(home, "--client", "cursor", "--project", "--repo", str(root)) == 2
    assert not outside.parent.exists()


def test_f3_project_install_refuses_a_symlinked_parent_folder(repo_factory, home, tmp_path, capsys):
    root = repo_factory("evil")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (root / ".cursor").symlink_to(elsewhere)
    assert install(home, "--client", "cursor", "--project", "--repo", str(root)) == 2
    assert list(elsewhere.iterdir()) == []


def test_f3_user_scope_still_follows_a_dotfile_symlink(repo_factory, home, tmp_path):
    root = repo_factory("app")
    real = tmp_path / "dotfiles" / "mcp.json"
    real.parent.mkdir()
    real.write_text("{}")
    (home / ".cursor").mkdir()
    (home / ".cursor/mcp.json").symlink_to(real)
    assert install(home, "--client", "cursor", "--repo", str(root)) == 0
    assert (home / ".cursor/mcp.json").is_symlink() and "l4-app" in real.read_text()


def test_f6_the_printed_claude_command_is_shell_quoted(tmp_path, home, capsys):
    import shlex

    root = make_repo(tmp_path / "my projects" / "it's here")
    assert install(home, "--client", "claude-code", "--repo", str(root)) == 0
    out = capsys.readouterr().out
    line = next(ln for ln in out.splitlines() if ln.startswith("claude mcp add"))
    assert shlex.split(line) == [
        "claude", "mcp", "add", "--transport", "stdio", "--scope", "user", "l4-it-s-here", "--",
        "l4", "mcp", "serve", "--repo", str(root),
    ]  # fmt: skip


# --- review finding M2: what each client does with a project entry --------------------------------------------------


def test_m2_claude_code_project_entry(repo_factory, home):  # sets CLAUDE_PROJECT_DIR (v2.1.139 and later)
    root = repo_factory("app")
    assert install(home, "--client", "claude-code", "--project", "--repo", str(root)) == 0
    assert read(root / ".mcp.json")["mcpServers"]["l4"] == {"type": "stdio", "command": "l4", "args": ["mcp", "serve"]}


def test_m2_vscode_project_entry(repo_factory, home):  # the server's cwd defaults to the workspace folder
    root = repo_factory("app")
    assert install(home, "--client", "vscode", "--project", "--repo", str(root)) == 0
    assert read(root / ".vscode/mcp.json")["servers"]["l4"] == {
        "type": "stdio",
        "command": "l4",
        "args": ["mcp", "serve"],
    }


def test_m2_opencode_project_entry(repo_factory, home):  # the session's cwd
    root = repo_factory("app")
    assert install(home, "--client", "opencode", "--project", "--repo", str(root)) == 0
    entry = read(root / "opencode.json")["mcp"]["l4"]
    assert entry == {"type": "local", "command": ["l4", "mcp", "serve"], "enabled": True}


def test_m2_cursor_project_entry_names_the_workspace_folder_variable(repo_factory, home):
    root = repo_factory("app")
    assert install(home, "--client", "cursor", "--project", "--repo", str(root)) == 0
    text = (root / ".cursor/mcp.json").read_text()
    assert json.loads(text)["mcpServers"]["l4"] == {
        "type": "stdio", "command": "l4", "args": ["mcp", "serve", "--repo", "${workspaceFolder}"],
    }  # fmt: skip
    assert str(root) not in text  # commit-safe: no path of this machine
    assert install(home, "--client", "cursor", "--project", "--repo", str(root)) == 0  # a rerun is not refused
    assert json.loads((root / ".cursor/mcp.json").read_text())["mcpServers"]["l4"]["args"][-1] == "${workspaceFolder}"


def test_m2_cursor_user_entry_names_the_repository(repo_factory, home):
    root = repo_factory("app")
    assert install(home, "--client", "cursor", "--repo", str(root)) == 0
    entry = read(home / ".cursor/mcp.json")["mcpServers"]["l4-app"]
    assert entry == {"type": "stdio", "command": "l4", "args": ["mcp", "serve", "--repo", str(root)]}


def test_m2_kiro_project_scope_is_refused_with_the_user_scope_hint(repo_factory, home, capsys):
    root = repo_factory("app")
    assert install(home, "--client", "kiro", "--project", "--repo", str(root)) == 2
    err = capsys.readouterr().err
    assert "kiro" in err and "user scope" in err and "--repo" in err
    assert not (root / ".kiro").exists() and not (home / ".kiro").exists()


def test_m2_kiro_user_entry_is_unchanged(repo_factory, home):
    root = repo_factory("app")
    assert install(home, "--client", "kiro", "--repo", str(root)) == 0
    entry = read(home / ".kiro/settings/mcp.json")["mcpServers"]["l4-app"]
    assert entry == {"command": "l4", "args": ["mcp", "serve", "--repo", str(root)]}


def with_token_env(root: Path, name: str | None = "MY_FORGE_TOKEN") -> None:
    text = "version: 1\n" + (f"forge:\n  token_env: {name}\n" if name else "")
    (root / ".l4" / "config.yaml").write_text(text, encoding="utf-8")


@pytest.mark.parametrize("project", [True, False])
def test_m2_codex_entry_lists_the_forge_token_variable_it_passes_through(repo_factory, home, project):
    root = repo_factory("app")
    with_token_env(root)
    path = root / ".codex/config.toml" if project else home / ".codex/config.toml"
    path.parent.mkdir(parents=True)
    path.write_text(
        "[mcp_servers." + ("l4" if project else "l4-app") + ']\ncommand = "old"\nstartup_timeout_sec = 30\n'
    )
    argv = ["--client", "codex", "--repo", str(root), *(["--project"] if project else [])]
    assert install(home, *argv) == 0
    entry = tomllib.loads(path.read_text())["mcp_servers"]["l4" if project else "l4-app"]
    assert entry == {
        "command": "l4",
        "args": ["mcp", "serve"] if project else ["mcp", "serve", "--repo", str(root)],
        "env_vars": ["MY_FORGE_TOKEN"],
        "startup_timeout_sec": 30,  # the user's own key stays
    }


def test_m2_codex_entry_without_a_configured_token_variable_has_no_env_vars(repo_factory, home):
    root = repo_factory("app")
    assert install(home, "--client", "codex", "--project", "--repo", str(root)) == 0
    assert tomllib.loads((root / ".codex/config.toml").read_text())["mcp_servers"]["l4"] == {
        "command": "l4", "args": ["mcp", "serve"],
    }  # fmt: skip


def test_m2_codex_keeps_the_env_vars_the_user_listed(repo_factory, home):
    root = repo_factory("app")
    with_token_env(root)
    path = root / ".codex/config.toml"
    path.parent.mkdir(parents=True)
    path.write_text('[mcp_servers.l4]\ncommand = "l4"\nenv_vars = ["HTTPS_PROXY"]\n')
    assert install(home, "--client", "codex", "--project", "--repo", str(root)) == 0
    entry = tomllib.loads(path.read_text())["mcp_servers"]["l4"]
    assert entry["env_vars"] == ["HTTPS_PROXY", "MY_FORGE_TOKEN"]
