import json
import subprocess
from pathlib import Path

from l4 import templatelock
from l4.eval.env import capture_env, tool_versions
from l4.redact import Redactor

PROFILES = {
    "p1": {"adapter": "opencode", "model": "opencode/big-pickle", "vendor": "acme", "auth": "subscription",
           "options": {"reasoning": "low", "provider": {"base_url": "http://h/v1", "api_key_env": "MY_KEY_VAR"}}},
    "j1": {"adapter": "claude-code", "vendor": "anthropic"},
    "unused": {"adapter": "codex"},
}  # fmt: skip
SECRET = "supersecretvalue-1234567890"


def _git(cwd: Path, *args: str) -> None:
    env = {"PATH": "/usr/bin:/bin:/usr/local/bin", "GIT_CONFIG_GLOBAL": "/dev/null"}
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@e.i", *args], cwd=cwd, check=True, capture_output=True, env=env
    )


def versions(adapter: str) -> str | None:
    return {"opencode": "opencode 1.4.2", "claude-code": "2.1.288 (Claude Code)"}.get(adapter)


def capture(tmp_path: Path, **over):
    kwargs = dict(
        harness_dir=tmp_path, profiles=PROFILES, used=["p1", "j1"], seed_set_sha256="a" * 64, k=2,
        cell_timeout_s=3000.0, runner=True, redactor=Redactor({}), version_of=versions, now="2026-10-07T10:00:00Z",
    )  # fmt: skip
    kwargs.update(over)
    return capture_env(**kwargs)


def repo(tmp_path: Path) -> Path:
    r = tmp_path / "h"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    (r / "f.txt").write_text("x")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "c")
    return r


def test_the_harness_commit_and_dirty_flag(tmp_path: Path) -> None:
    r = repo(tmp_path)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=r, capture_output=True, text=True).stdout.strip()
    env = capture(tmp_path, harness_dir=r)
    assert env["harness"] == {"commit": head, "dirty": False, "source": "git"}
    (r / "f.txt").write_text("changed")
    assert capture(tmp_path, harness_dir=r)["harness"]["dirty"] is True


def test_an_untracked_file_does_not_make_the_harness_dirty(tmp_path: Path) -> None:
    """`--out docs/eval/<date>` inside the checkout: the run's own files must not change its environment
    record, or a `--resume` would never find a cell of the same environment."""
    r = repo(tmp_path)
    (r / "docs" / "eval" / "2026-10-07").mkdir(parents=True)
    (r / "docs" / "eval" / "2026-10-07" / "scorecard.json").write_text("{}")
    assert capture(tmp_path, harness_dir=r)["harness"]["dirty"] is False


def test_outside_a_checkout_the_vendored_commit_or_unknown(tmp_path: Path) -> None:
    env = capture(tmp_path, vendored_commit=lambda: "c" * 40)
    assert env["harness"] == {"commit": "c" * 40, "dirty": None, "source": "vendored"}
    env = capture(tmp_path, vendored_commit=lambda: None)
    assert env["harness"] == {"commit": None, "dirty": None, "source": "unknown"}


def test_templates_and_the_lock_hash(tmp_path: Path) -> None:
    env = capture(tmp_path)
    assert env["templates"] == json.loads(json.dumps(templatelock.current()))
    assert len(env["templates_lock_sha256"]) == 64


def test_cli_versions_of_the_used_profiles_only(tmp_path: Path) -> None:
    env = capture(tmp_path)
    assert set(env["cli_versions"]) == {"p1", "j1"}
    assert env["cli_versions"]["p1"]["adapter"] == "opencode" and env["cli_versions"]["p1"]["version"] == "1.4.2"
    assert env["cli_versions"]["j1"]["version"] == "2.1.288"
    assert isinstance(env["cli_versions"]["j1"]["unrecorded"], (bool, type(None)))


def test_an_unreadable_version_is_recorded_as_null(tmp_path: Path) -> None:
    env = capture(tmp_path, version_of=lambda adapter: None)
    assert env["cli_versions"]["p1"]["version"] is None and env["cli_versions"]["p1"]["unrecorded"] is None


def test_an_unrecorded_version_is_flagged(tmp_path: Path) -> None:
    env = capture(
        tmp_path, version_of=lambda adapter: "9.9.9", recorded={"opencode": ["1.0.0"], "claude-code": ["9.9.9"]}
    )
    assert env["cli_versions"]["p1"]["unrecorded"] is True and env["cli_versions"]["j1"]["unrecorded"] is False


def test_profiles_carry_model_vendor_and_options_without_secrets(tmp_path: Path) -> None:
    env = capture(tmp_path)
    assert env["profiles"]["p1"]["model"] == "opencode/big-pickle" and env["profiles"]["p1"]["vendor"] == "acme"
    assert env["profiles"]["p1"]["options"]["reasoning"] == "low"
    assert "unused" not in env["profiles"]
    profiles = {
        "p1": {
            **PROFILES["p1"],
            "options": {"api_key": "plain", "token": "t", "ok": 1, "nested": {"password": "p", "x": 2}},
        }
    }
    options = capture(tmp_path, profiles=profiles)["profiles"]["p1"]["options"]
    assert options == {"ok": 1, "nested": {"x": 2}}


def test_no_environment_variable_value_enters_the_record(tmp_path: Path) -> None:
    profiles = {"p1": {**PROFILES["p1"], "model": f"opencode/{SECRET}", "options": {"note": f"key {SECRET}"}}}
    env = capture(tmp_path, profiles=profiles, redactor=Redactor({"PLANTED": SECRET}))
    assert SECRET not in json.dumps(env)


def test_seed_k_timeout_and_machine(tmp_path: Path) -> None:
    env = capture(tmp_path)
    assert env["seed_set_sha256"] == "a" * 64 and env["k"] == 2 and env["cell_timeout_s"] == 3000.0
    assert env["started_at"] == "2026-10-07T10:00:00Z"
    assert env["machine"]["runner"] is True and env["machine"]["cpus"] >= 1 and env["machine"]["platform"]
    assert capture(tmp_path, runner=False)["machine"]["runner"] is False


def test_the_uv_and_openspec_versions_are_recorded(tmp_path: Path) -> None:
    """Every cell runs `uv sync --frozen --offline` and reads the unit through OpenSpec: both change what a cell does,
    so the record (and the environment a `--resume` matches) carries their versions."""
    env = capture(tmp_path, tools={"uv": "0.12.22", "openspec": "1.14.0"})
    assert env["tools"] == {"uv": "0.12.22", "openspec": "1.14.0"}


def test_tool_versions_reads_uv_and_the_installed_openspec_package(tmp_path: Path) -> None:
    home = tmp_path / "l4home"
    pkg = home / "npm" / "node_modules" / "@fission-ai" / "openspec"
    pkg.mkdir(parents=True)
    (pkg / "package.json").write_text(json.dumps({"name": "@fission-ai/openspec", "version": "1.14.0"}))
    seen: list[list[str]] = []

    def run(argv: list[str]) -> str | None:
        seen.append(argv)
        return "uv 0.12.22 (x86_64-unknown-linux-gnu)\n"

    assert tool_versions({"L4_HOME": str(home)}, run=run) == {"uv": "0.12.22", "openspec": "1.14.0"}
    assert seen == [["uv", "--version"]]
    absent = tool_versions({"L4_HOME": str(tmp_path / "none")}, run=lambda argv: None)
    assert absent == {"uv": None, "openspec": None}


def test_the_kept_config_sections_are_recorded_without_secrets(tmp_path: Path) -> None:
    kept = {"availability": {"probe_timeout": "150s"}, "sandbox": {"extra_env": {"API_TOKEN": "t"}, "mode": "x"}}
    env = capture(tmp_path, kept=kept)
    assert env["cell_config"] == {"availability": {"probe_timeout": "150s"}, "sandbox": {"extra_env": {}, "mode": "x"}}
    assert capture(tmp_path)["cell_config"] == {}


def test_claude_version_runs_with_the_autoupdater_off(monkeypatch) -> None:  # R4, L4-PRV-044
    from l4.eval import env as env_module

    seen: list[dict] = []

    def fake_run(argv, **kwargs):
        seen.append({"argv": argv, "env": kwargs.get("env")})
        return subprocess.CompletedProcess(argv, 0, stdout="2.1.288 (Claude Code)\n", stderr="")

    monkeypatch.setattr(env_module.shutil, "which", lambda name: f"/bin/{name}")
    monkeypatch.setattr(env_module.subprocess, "run", fake_run)
    monkeypatch.setenv("DISABLE_UPDATES", "1")
    assert env_module.cli_version("claude-code") == "2.1.288 (Claude Code)\n"
    env = seen[0]["env"]
    assert env is not None and env["DISABLE_AUTOUPDATER"] == "1" and "DISABLE_UPDATES" not in env
    env_module.cli_version("codex")
    assert seen[1]["env"] is None  # the other CLIs are run as before


def test_a_v2_profile_is_versioned_through_opencode2(tmp_path: Path) -> None:  # L4-OCV-012
    seen: list[str] = []

    def version_of(name: str) -> str | None:
        seen.append(name)
        return {"opencode": "1.18.34", "opencode2": "opencode v2.0.32"}.get(name)

    v2 = {"adapter": "opencode", "model": "m", "vendor": "unknown", "options": {"cli_major": 2}}
    recorded = {"opencode": ["1.18.34", "2.0.32"]}
    env = capture(
        tmp_path, profiles={**PROFILES, "v2": v2}, used=["p1", "v2"], version_of=version_of, recorded=recorded
    )
    assert seen == ["opencode", "opencode2"]
    assert env["cli_versions"]["p1"]["version"] == "1.18.34"
    assert env["cli_versions"]["v2"] == {"adapter": "opencode", "version": "2.0.32", "unrecorded": False}


def test_cli_version_runs_the_opencode2_binary(monkeypatch) -> None:
    from l4.eval import env as env_module

    asked: list[str] = []
    monkeypatch.setattr(env_module.shutil, "which", lambda name: asked.append(name) or f"/bin/{name}")
    monkeypatch.setattr(
        env_module.subprocess, "run", lambda argv, **kw: subprocess.CompletedProcess(argv, 0, stdout="x\n", stderr="")
    )
    assert env_module.cli_version("opencode2") == "x\n" and asked == ["opencode2"]
