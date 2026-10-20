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


def test_kiro_is_pinned_exactly():
    """PRQ-12 holds the catalog's pin exactly (L4-PRV-043): the check compares with `=`, not a floor."""
    assert pin("KIRO_VERSION") == "2.32.0"
    assert steps()["PRQ-12"] == ("check_kiro", "apply_kiro", "WITH_KIRO")
    body = TEXT[TEXT.index("check_kiro()") : TEXT.index("kiro_archive()")]
    assert '"$v" = "$KIRO_VERSION"' in body and "ver_ge" not in body


def test_kiro_apply_downloads_the_versioned_archive_and_checks_it():  # SCN-PRV-121
    start = TEXT.index("apply_kiro()")
    body = TEXT[start : TEXT.index('if [ "$WITH_KIRO" = 1 ]', start)]
    assert "stable/$KIRO_VERSION/" in body and "sha256sum -c" in body and "unzip" in body
    assert body.count("install -m 755") == 3
    assert body.index("sha256sum -c") < body.index("install -m 755")  # nothing is installed before the check passed
    assert "/dev/tty" not in body and "yes |" not in body
    for text in ("kiro-cli update", "cli.kiro.dev/install"):
        assert text not in TEXT, text


def _check_kiro(version_output: str) -> subprocess.CompletedProcess:
    program = "\n".join(
        [
            f"KIRO_VERSION={pin('KIRO_VERSION')}",
            f"as_runner() {{ echo '{version_output}'; }}",
            re.search(r"^ver_ge\(\) \{.*\}", TEXT, re.M).group(0),
            _bash_function("check_kiro"),
            'if check_kiro; then echo "rc=0"; else echo "rc=1"; fi',
            'echo "DETAIL=$DETAIL"',
        ]
    )
    return subprocess.run(["bash", "-c", program], capture_output=True, text=True, check=False)


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_check_kiro_is_exact_and_names_a_wrong_major():  # SCN-PRV-121, SCN-OCG-14
    assert "rc=0" in _check_kiro("kiro-cli 2.32.0").stdout
    drift = _check_kiro("kiro-cli 2.33.0").stdout
    assert "rc=1" in drift and "pinned 2.32.0" in drift and "Kiro CLI" not in drift
    three = _check_kiro("kiro-cli 3.0.0").stdout
    assert "rc=1" in three and "Kiro CLI 3; L4 runs Kiro CLI 2" in three and "pinned 2.32.0" in three


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
