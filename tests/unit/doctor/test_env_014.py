"""ENV-014 (SPEC L4-FAC-008): a profile's stored login that looks wiped is a warning with the exact re-login command
for the runner user. Offline: it reads the credential store, never the network, and never prints a value."""

import json
import sqlite3
from pathlib import Path

import pytest

from l4.config.roles import JUDGE_ADAPTERS
from l4.config.schema import L4Config
from l4.doctor import checks_agents as agents
from l4.doctor.registry import Check, Registry, exit_code, run_checks

VENDOR = {"claude-code": "anthropic", "codex": "openai", "kiro-cli": "zhipu"}


def cfg(adapter: str, **profile: object) -> L4Config:
    return L4Config.model_validate(
        {
            "profiles": {
                "p": {"adapter": adapter, "model": "m", "vendor": VENDOR[adapter], "auth": "subscription", **profile}
            },
            "roles": {"implementer": ["p"], "judges": ["p"] if adapter in JUDGE_ADAPTERS else []},
        }
    )


def outcome(ctx):
    registry = Registry()
    registry.register(Check("ENV-014", "wiped login", "warn", agents._env_014))
    (result,) = run_checks(ctx, registry=registry)
    return result, exit_code([result])


def write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


CLAUDE_OK = {"claudeAiOauth": {"accessToken": "a", "refreshToken": "r", "expiresAt": 1791400000000}}


@pytest.mark.parametrize(
    "creds",
    [
        {"claudeAiOauth": {"accessToken": "", "refreshToken": "", "expiresAt": 0}},  # the 2026-10-07 incident
        {"claudeAiOauth": {"accessToken": "a", "refreshToken": "", "expiresAt": 1791400000000}},
        {"claudeAiOauth": {"accessToken": "a", "refreshToken": "r", "expiresAt": 0}},
    ],
)
def test_a_wiped_claude_login_warns_with_the_runner_relogin_command(make_ctx, tmp_path, creds):
    ctx, _ = make_ctx(cfg=cfg("claude-code"))
    write(tmp_path / "home" / ".claude" / ".credentials.json", creds)
    result, code = outcome(ctx)
    assert (result.status, result.severity) == ("fail", "warn") and int(code) == 0
    assert "p" in result.message and "claude-code" in result.message and "wiped" in result.message
    assert result.fix_hint == "sudo -iu gitlab-runner claude, then type /login"  # the login shell has the runner PATH
    assert 'a"' not in result.message and "refreshToken" not in result.message.replace("refreshToken empty", "")


def test_an_expired_but_intact_login_is_not_wiped(make_ctx, tmp_path):
    ctx, _ = make_ctx(cfg=cfg("claude-code"))
    write(tmp_path / "home" / ".claude" / ".credentials.json", CLAUDE_OK)  # expiresAt in the past: refreshable
    assert outcome(ctx)[0].status == "pass"


def test_no_credential_file_a_static_token_or_an_api_key_profile_are_skipped(make_ctx, tmp_path):
    wiped = {"claudeAiOauth": {"accessToken": "", "refreshToken": "", "expiresAt": 0}}
    ctx, _ = make_ctx(cfg=cfg("claude-code"))
    assert outcome(ctx)[0].status == "pass"  # nothing stored: ENV-005 / readiness say so
    write(tmp_path / "home" / ".claude" / ".credentials.json", wiped)
    ctx, _ = make_ctx(cfg=cfg("claude-code"), CLAUDE_CODE_OAUTH_TOKEN="static")
    assert outcome(ctx)[0].status == "pass"  # the CLI uses the token, not the store
    ctx, _ = make_ctx(cfg=cfg("claude-code", auth="api_key"))
    assert outcome(ctx)[0].status == "pass"


def test_claude_config_dir_is_honoured(make_ctx, tmp_path):
    ctx, _ = make_ctx(cfg=cfg("claude-code"), CLAUDE_CONFIG_DIR=str(tmp_path / "cfg"))
    write(tmp_path / "cfg" / ".credentials.json", {"claudeAiOauth": {"refreshToken": "", "expiresAt": 0}})
    assert outcome(ctx)[0].status == "fail"


def test_a_wiped_codex_login_warns(make_ctx, tmp_path):
    ctx, _ = make_ctx(cfg=cfg("codex"))
    write(tmp_path / "home" / ".codex" / "auth.json", {"auth_mode": "chatgpt", "tokens": {"refresh_token": ""}})
    result, _ = outcome(ctx)
    assert result.status == "fail" and result.fix_hint == "sudo -iu gitlab-runner codex login --device-auth"
    write(tmp_path / "home" / ".codex" / "auth.json", {"auth_mode": "chatgpt", "tokens": {"refresh_token": "r"}})
    assert outcome(ctx)[0].status == "pass"
    write(tmp_path / "home" / ".codex" / "auth.json", {"auth_mode": "apikey", "OPENAI_API_KEY": "k"})
    assert outcome(ctx)[0].status == "pass"


def test_a_wiped_kiro_login_warns(make_ctx, tmp_path):
    ctx, _ = make_ctx(cfg=cfg("kiro-cli"))
    store = tmp_path / "home" / ".local" / "share" / "kiro-cli" / "data.sqlite3"
    store.parent.mkdir(parents=True)
    db = sqlite3.connect(store)
    db.execute("create table auth_kv (key text primary key, value text)")
    db.execute(
        "insert into auth_kv values ('kirocli:odic:token', ?)", (json.dumps({"access_token": "", "refresh_token": ""}),)
    )
    db.commit()
    db.close()
    result, _ = outcome(ctx)
    assert result.status == "fail" and result.fix_hint == "sudo -iu gitlab-runner kiro-cli login"
    db = sqlite3.connect(store)
    db.execute("update auth_kv set value = ?", (json.dumps({"access_token": "a", "refresh_token": "r"}),))
    db.commit()
    db.close()
    assert outcome(ctx)[0].status == "pass"


def test_an_unreadable_store_is_skipped_not_a_crash(make_ctx, tmp_path):
    ctx, _ = make_ctx(cfg=cfg("claude-code"))
    path = tmp_path / "home" / ".claude" / ".credentials.json"
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    assert outcome(ctx)[0].status == "pass"


def test_env_014_on_github_names_the_user_the_runner_service_runs_as(make_ctx, tmp_path):
    """L4-GHP-009: GitHub's runner service has no `gitlab-runner` user; the hint names the user the service runs as."""
    wiped = {"claudeAiOauth": {"accessToken": "", "refreshToken": "", "expiresAt": 0}}
    for adapter, relogin in (("claude-code", "claude, then type /login"), ("codex", "codex login --device-auth")):
        config = cfg(adapter)
        config.ci.platform = "github"
        ctx, _ = make_ctx(cfg=config)
        write(tmp_path / "home" / ".claude" / ".credentials.json", wiped)
        write(tmp_path / "home" / ".codex" / "auth.json", {"auth_mode": "chatgpt", "tokens": {"refresh_token": ""}})
        result, _ = outcome(ctx)
        assert result.status == "fail"
        assert "the user the runner service runs as" in result.fix_hint and relogin in result.fix_hint
        assert "gitlab-runner" not in result.fix_hint + result.message


def test_env_014_on_gitlab_keeps_gitlab_runner(make_ctx, tmp_path):
    config = cfg("claude-code")
    config.ci.platform = "gitlab"
    ctx, _ = make_ctx(cfg=config)
    write(tmp_path / "home" / ".claude" / ".credentials.json", {"claudeAiOauth": {"refreshToken": "", "expiresAt": 0}})
    assert outcome(ctx)[0].fix_hint == "sudo -iu gitlab-runner claude, then type /login"
