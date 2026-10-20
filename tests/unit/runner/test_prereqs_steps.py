"""M15-G1: `scripts/runner/prereqs.sh` lists the Serena warm-up, the Playwright browser path and Laya as steps, each
with a check and an apply function, and its pins agree with the harness's own constants. A static parse: the script
changes a machine, so no test runs it."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from l4.config import defaults as d

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "runner" / "prereqs.sh"
TEXT = SCRIPT.read_text(encoding="utf-8")


def pin(name: str) -> str:
    match = re.search(rf"^{name}=\$\{{{name}:-([^}}]+)\}}", TEXT, re.M)
    assert match, f"{name} is not pinned in the top block as NAME=${{NAME:-x.y.z}}"
    return match.group(1)


def steps() -> dict[str, tuple[str, str, str]]:
    """step ID -> (check function, apply function, flag that enables it)."""
    out = {}
    for match in re.finditer(r'^(?:if \[ "\$(\w+)" = 1 \]; then )?step (PRQ-\d+) "[^"]*" (\w+) (\w*)', TEXT, re.M):
        out[match.group(2)] = (match.group(3), match.group(4), match.group(1) or "")
    return out


def test_with_laya_and_playwright_steps_are_listed():
    found = steps()
    assert found["PRQ-13"] == ("check_serena", "apply_serena", "WITH_SERENA")
    assert found["PRQ-14"] == ("check_pw", "apply_pw", "WITH_PLAYWRIGHT")
    assert found["PRQ-18"] == ("check_laya", "apply_laya", "WITH_LAYA")
    for check, apply, _ in found.values():
        assert re.search(rf"^{check}\(\)", TEXT, re.M) and (not apply or re.search(rf"^{apply}\(\)", TEXT, re.M))
    assert "--with-laya) WITH_LAYA=1" in TEXT and "--with-playwright) WITH_PLAYWRIGHT=1" in TEXT


def test_pins_agree_with_the_harness_constants():
    assert pin("SERENA_VERSION") == d.SERENA_VERSION
    assert pin("LAYA_VERSION") == d.LAYA_VERSION
    assert pin("PLAYWRIGHT_VERSION") == "1.63.0"


def test_browser_path_is_where_the_gate_sandbox_mounts_it():
    path, env, read_only = d.CACHES["playwright"]
    assert (path, env, read_only) == ("$L4_CACHE/shared/ms-playwright", "PLAYWRIGHT_BROWSERS_PATH", True)
    default_l4_cache = ".cache/l4"  # defaults.cache_root(): ~/.cache/l4 when neither L4_CACHE nor XDG_CACHE_HOME is set
    assert f"PW_PATH=${{PW_PATH:-$RHOME/{default_l4_cache}/shared/ms-playwright}}" in TEXT
    assert "PLAYWRIGHT_BROWSERS_PATH=$PW_PATH" in TEXT


def test_laya_is_cpu_pinned_and_prefetches_the_checkpoint():
    assert "uv tool install --force --torch-backend cpu 'laya[serve]==$LAYA_VERSION'" in TEXT
    assert pin("LAYA_CHECKPOINT") == "typed-decisions"
    assert "local_files_only=True" in TEXT  # the check never downloads


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_script_parses():
    assert subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True).returncode == 0


def test_the_docker_group_is_a_warning_with_the_remediation_and_never_applied():
    """HB-1: the sandbox masks /run, but removing the membership is the maintainer's decision (other jobs)."""
    lines = [ln for ln in TEXT.splitlines() if "report PRQ-19" in ln]
    warn = next(ln for ln in lines if " WARN " in ln)
    assert "docker group" in warn and "sudo gpasswd -d $RUNNER_USER docker" in warn
    assert "restart" in warn and "masks" in warn
    assert "never mounts" not in TEXT  # the old wording: true, but it missed that bwrap leaves /run reachable
    assert "PRQ-19" not in steps()  # reported only: no apply function changes group membership
    assert not re.search(r"gpasswd[^\n]*\$SUDO|\$SUDO[^\n]*gpasswd", TEXT)


def test_kiro_is_pinned_to_the_version_of_the_maintainer_machine_as_a_floor():
    """The official installer takes no version (it fetches `latest`), so PRQ-12 is a floor: an exact match would make
    `--apply` fail whenever upstream is newer than the pin."""
    assert pin("KIRO_VERSION") == "2.28.0"
    assert steps()["PRQ-12"] == ("check_kiro", "apply_kiro", "WITH_KIRO")
    body = TEXT[TEXT.index("check_kiro()") : TEXT.index("apply_kiro()")]
    assert "ver_ge" in body and "$KIRO_VERSION" in body
    assert "cli.kiro.dev/install" in TEXT


def test_kiro_apply_updates_an_installed_cli_without_a_prompt_and_installs_only_a_missing_one():
    """Live kiro-e2e H2 (2026-10-08): over an installed 2.27.1 the official installer asks "Do you want to replace it?
    (y/N)" on /dev/tty, so `--apply` failed with `/dev/tty: No such device or address` and left 2.27.1. An installed
    kiro-cli updates itself with `kiro-cli update --non-interactive`; the installer runs only for a missing kiro-cli."""
    start = TEXT.index("apply_kiro()")
    body = TEXT[start : TEXT.index('if [ "$WITH_KIRO" = 1 ]', start)]
    assert "command -v kiro-cli" in body
    assert "kiro-cli update --non-interactive" in body
    assert "cli.kiro.dev/install" in body
    assert body.index("kiro-cli update --non-interactive") < body.index("cli.kiro.dev/install")
    assert "/dev/tty" not in body and "yes |" not in body


def test_kiro_login_is_checked_on_the_flat_whoami_and_the_warning_names_the_device_flow_command():
    assert 'report PRQ-15 WARN "auth: kiro-cli"' in TEXT
    assert "accountType" in TEXT  # whoami --format json answers {"accountType", "email"} (2.27.1, 2.28.0)
    assert "sudo -iu $RUNNER_USER" in TEXT and "kiro-cli login --license free --use-device-flow" in TEXT


def test_no_step_moves_or_copies_a_kiro_login():
    """A copy of a login rotates its refresh token and kills the original (SPEC L4-FAC-008): the human logs in."""
    for ln in TEXT.splitlines():
        if re.search(r"\b(mv|cp|rsync|install -D)\b", ln):
            assert "kiro" not in ln.lower() and ".aws/sso" not in ln, ln
    assert not re.search(r"adopt_one\s+kiro", TEXT)


def _bash_function(name: str) -> str:
    match = re.search(rf"^{name}\(\) \{{.*?\n?\}}(?=\n)", TEXT, re.M | re.S)
    assert match, f"{name} is not a function of the script"
    return match.group(0)


def _check_opencode(version_output: str) -> subprocess.CompletedProcess:
    """`check_opencode` and `ver_ge` from the script, with an `as_runner` stub that prints `version_output`."""
    program = "\n".join(
        [
            f"OPENCODE_VERSION={pin('OPENCODE_VERSION')}",
            f"as_runner() {{ echo '{version_output}'; }}",
            re.search(r"^ver_ge\(\) \{.*\}", TEXT, re.M).group(0),
            _bash_function("check_opencode"),
            'if check_opencode; then echo "rc=0"; else echo "rc=1"; fi',
            'echo "DETAIL=$DETAIL"',
        ]
    )
    return subprocess.run(["bash", "-c", program], capture_output=True, text=True, check=False)


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_prq_11_refuses_an_opencode_of_major_2_and_names_the_floor():  # SCN-OCG-10
    out = _check_opencode("opencode v2.0.32").stdout
    assert "rc=1" in out and "need 1.x >= 1.18.34" in out and "2.0.32" in out


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_prq_11_accepts_the_pinned_v1_and_a_newer_v1_and_refuses_an_older_one():
    assert "rc=0" in _check_opencode("1.18.34").stdout
    assert "rc=0" in _check_opencode("1.19.3").stdout
    assert "rc=1" in _check_opencode("1.18.0").stdout


def test_prq_15_runs_opencode_models_only_when_prq_11_passes():  # SCN-OCG-10
    lines = [line for line in TEXT.splitlines() if "opencode models" in line]
    assert len(lines) == 1 and re.match(r"\s*if check_opencode; then .*opencode models", lines[0])
    assert "free models: skipped (opencode at " in TEXT and "is not OpenCode v1)" in TEXT


# --- PRQ-21: agent CLI self-update off (L4-PRV-044, SCN-PRV-124) ---

needs_jq = pytest.mark.skipif(shutil.which("jq") is None or shutil.which("bash") is None, reason="needs jq and bash")
PRQ21_FUNCTIONS = (
    "json_has",
    "json_merge_script",
    "json_merge",
    "kiro_present",
    "check_selfupdate",
    "apply_selfupdate",
)


def _prq21_function(name: str) -> str:
    """One function of PRQ-21: a one-line definition, or the lines up to the first line that is just `}`."""
    lines = TEXT.splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith(f"{name}() {{"))
    if re.search(r"\}\s*(#.*)?$", lines[start]):
        return lines[start]
    end = next(i for i in range(start + 1, len(lines)) if lines[i] == "}")
    return "\n".join(lines[start : end + 1])


def _prq21(tmp_path: Path, body: str, *, with_kiro: int = 1, kiro: bool = True) -> subprocess.CompletedProcess:
    """The PRQ-21 functions of the script with an `as_runner` stub that runs the command as the current user, an `RHOME`
    under `tmp_path`, and the `command -v kiro-cli` question answered by the stub (no agent CLI ever runs)."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    program = "\n".join(
        [
            f"RHOME={home}; WITH_KIRO={with_kiro}; DETAIL=",
            f'as_runner() {{ case "$1" in *"command -v kiro-cli"*) return {0 if kiro else 1};; esac; '
            'HOME="$RHOME" bash -c "$1"; }',
            *(_prq21_function(name) for name in PRQ21_FUNCTIONS),
            body,
        ]
    )
    return subprocess.run(["bash", "-c", program], capture_output=True, text=True, check=False)


def test_prq21_is_a_step_of_the_script():
    assert steps()["PRQ-21"] == ("check_selfupdate", "apply_selfupdate", "")


@needs_jq
def test_prq21_merges_the_claude_setting(tmp_path):
    claude = tmp_path / "home" / ".claude" / "settings.json"
    claude.parent.mkdir(parents=True)
    claude.write_text(json.dumps({"model": "m", "env": {"FOO": "1"}}), encoding="utf-8")
    out = _prq21(tmp_path, 'check_selfupdate && echo "pre=ok" || echo "pre=missing"; apply_selfupdate; echo "rc=$?"; '
                 "check_selfupdate && echo post=ok", kiro=False)  # fmt: skip
    assert "pre=missing" in out.stdout and "rc=0" in out.stdout and "post=ok" in out.stdout, out
    assert json.loads(claude.read_text(encoding="utf-8")) == {
        "model": "m", "env": {"FOO": "1", "DISABLE_AUTOUPDATER": "1"},
    }  # fmt: skip
    assert list(claude.parent.iterdir()) == [claude]  # the temporary file was renamed away


@needs_jq
def test_prq21_creates_a_missing_claude_file_and_its_directory(tmp_path):
    out = _prq21(tmp_path, "apply_selfupdate; echo rc=$?", kiro=False)
    assert "rc=0" in out.stdout, out
    claude = tmp_path / "home" / ".claude" / "settings.json"
    assert json.loads(claude.read_text(encoding="utf-8")) == {"env": {"DISABLE_AUTOUPDATER": "1"}}


@needs_jq
def test_prq21_merges_the_kiro_setting(tmp_path):
    kiro = tmp_path / "home" / ".kiro" / "settings" / "cli.json"
    out = _prq21(tmp_path, "apply_selfupdate; echo rc=$?")
    assert "rc=0" in out.stdout, out
    assert json.loads(kiro.read_text(encoding="utf-8")) == {"app.disableAutoupdates": True}
    kiro.write_text(json.dumps({"chat.defaultModel": "m", "app.disableAutoupdates": False}), encoding="utf-8")
    out = _prq21(tmp_path, "apply_selfupdate; echo rc=$?")
    assert "rc=0" in out.stdout, out
    assert json.loads(kiro.read_text(encoding="utf-8")) == {"chat.defaultModel": "m", "app.disableAutoupdates": True}


def test_prq21_never_writes_disable_updates():
    body = "\n".join(_prq21_function(name) for name in PRQ21_FUNCTIONS)
    assert "DISABLE_UPDATES" not in body and re.search(r"^step PRQ-21 ", TEXT, re.M)


def test_prq21_runs_no_agent_cli():
    body = "\n".join(_prq21_function(name) for name in PRQ21_FUNCTIONS).replace("command -v kiro-cli", "")
    assert not re.search(r"(?<![\w./-])(kiro-cli|claude)(?![\w./-])", body), body


@needs_jq
def test_prq21_leaves_a_file_that_is_not_json(tmp_path):
    claude = tmp_path / "home" / ".claude" / "settings.json"
    claude.parent.mkdir(parents=True)
    claude.write_text("model = 'toml, not json'\n", encoding="utf-8")
    out = _prq21(tmp_path, "apply_selfupdate; echo rc=$?", kiro=False)
    assert "rc=0" not in out.stdout and str(claude) in out.stderr, out
    assert claude.read_text(encoding="utf-8") == "model = 'toml, not json'\n"
    assert list(claude.parent.iterdir()) == [claude]


def test_prq21_sets_the_kiro_setting_only_with_kiro():
    body = _prq21_function("kiro_present")
    assert 'WITH_KIRO" = 1' in body and "command -v kiro-cli" in body
    assert "kiro_present" in _prq21_function("check_selfupdate") and "kiro_present" in _prq21_function(
        "apply_selfupdate"
    )


@needs_jq
def test_prq21_skips_kiro_when_it_is_not_installed_or_switched_off(tmp_path):
    kiro = tmp_path / "home" / ".kiro" / "settings" / "cli.json"
    _prq21(tmp_path, "apply_selfupdate", with_kiro=0)
    assert not kiro.exists()
