"""M15-G1: `scripts/runner/prereqs.sh` lists the Serena warm-up, the Playwright browser path and Laya as steps, each
with a check and an apply function, and its pins agree with the harness's own constants. A static parse: the script
changes a machine, so no test runs it."""

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
