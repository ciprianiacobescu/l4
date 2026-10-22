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
from l4.provision import catalog

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


# --- PRQ-22: Copilot CLI at the catalog pin, opt-in (L4-PRV-050, SCN-PRV-139, SCN-PRV-140) ---


def test_prq22_is_opt_in_and_its_pins_equal_the_catalogs():  # SCN-PRV-139
    assert steps()["PRQ-22"] == ("check_copilot", "apply_copilot", "WITH_COPILOT")
    assert "--with-copilot) WITH_COPILOT=1" in TEXT and "WITH_COPILOT=0" in TEXT
    assert 'report PRQ-22 SKIP "Copilot CLI" "pass --with-copilot to install"' in TEXT
    assert TEXT.index("step PRQ-21 ") < TEXT.index("step PRQ-22 ")
    assert pin("COPILOT_VERSION") == catalog.COPILOT_VERSION
    row = catalog.COPILOT_SHA256[catalog.COPILOT_VERSION]
    assert {
        "COPILOT_SHA256_X86_64": pin("COPILOT_SHA256_X86_64"),
        "COPILOT_SHA256_AARCH64": pin("COPILOT_SHA256_AARCH64"),
        "COPILOT_SHA256_X86_64_MUSL": pin("COPILOT_SHA256_X86_64_MUSL"),
        "COPILOT_SHA256_AARCH64_MUSL": pin("COPILOT_SHA256_AARCH64_MUSL"),
    } == {
        "COPILOT_SHA256_X86_64": row["linux-x64"],
        "COPILOT_SHA256_AARCH64": row["linux-arm64"],
        "COPILOT_SHA256_X86_64_MUSL": row["linux-x64-musl"],
        "COPILOT_SHA256_AARCH64_MUSL": row["linux-arm64-musl"],
    }


def _check_copilot(version_output: str) -> subprocess.CompletedProcess:
    """`check_copilot` from the script, with an `as_runner` stub that prints `version_output`."""
    program = "\n".join(
        [
            f"COPILOT_VERSION={pin('COPILOT_VERSION')}; L4_HOME=/l4",
            f"as_runner() {{ echo '{version_output}'; }}",
            _bash_function("check_copilot"),
            'if check_copilot; then echo "rc=0"; else echo "rc=1"; fi',
            'echo "DETAIL=$DETAIL"',
        ]
    )
    return subprocess.run(["bash", "-c", program], capture_output=True, text=True, check=False)


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_check_copilot_accepts_only_the_exact_pin_and_names_a_wrong_major():  # SCN-PRV-140
    assert "rc=1" in _check_copilot("GitHub Copilot CLI 1.0.101.").stdout
    two = _check_copilot("GitHub Copilot CLI 2.0.0.").stdout
    assert "rc=1" in two and "Copilot CLI 2; L4 runs Copilot CLI 1" in two and "pinned 1.0.102" in two
    ok = _check_copilot("GitHub Copilot CLI 1.0.102.").stdout
    assert "rc=0" in ok and "copilot 1.0.102" in ok and "Copilot CLI 1;" not in ok
    drift = _check_copilot("GitHub Copilot CLI 1.0.101.").stdout
    assert "copilot 1.0.101" in drift and "pinned 1.0.102" in drift and "L4 runs" not in drift
    missing = _check_copilot("").stdout
    assert "rc=1" in missing and "copilot missing at none (pinned 1.0.102)" in missing


def _copilot_section() -> str:
    """The code of `apply_copilot`, without the comment above PRQ-22."""
    start = TEXT.index("apply_copilot() {")
    return TEXT[start : TEXT.index('if [ "$WITH_COPILOT" = 1 ]', start)]


def test_apply_copilot_checks_the_digest_before_installing_and_runs_no_installer():  # SCN-PRV-140
    body = _copilot_section()
    assert "sha256sum -c" in body and body.count("install -m 755") == 1
    assert body.index("sha256sum -c") < body.index("install -m 755")  # nothing is installed before the check passed
    assert not re.search(r"\|\s*(?:ba|z)?sh\b", body), "a piped installer script"
    for text in ("gh.io/copilot-install", "npm install", "copilot update", "/dev/tty"):
        assert text not in body, text
    assert "gh.io/copilot-install" not in TEXT and "github/copilot@" not in TEXT  # the npm package is not installed
    assert "tar -xzf copilot.tar.gz copilot" in body  # only the member `copilot` is extracted
    assert "download/v$COPILOT_VERSION/$COPILOT_FILE" in body
    assert "sha256 differs: when COPILOT_VERSION is set, set the four COPILOT_SHA256_* to its digests" in body


def test_apply_copilot_warms_the_l4_package_cache_after_the_install():  # D14
    body = _copilot_section()
    warm = body.index("XDG_CACHE_HOME=$L4_HOME/copilot-cache")
    assert body.index("install -m 755") < warm and "COPILOT_AUTO_UPDATE=false" in body[warm:]
    assert "copilot --version" in body[warm:] and "COPILOT_HOME=" in body[warm:]  # a throw-away home, no ~/.copilot


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_copilot_asset_follows_the_machines_architecture_and_libc(tmp_path):
    """The asset helper with `uname` and `ldd` stubs: gnu when glibc answers, musl when it does not."""

    def asset(machine: str, ldd_first_line: str) -> list[str]:
        bin_dir = tmp_path / machine / ldd_first_line.split()[0]
        bin_dir.mkdir(parents=True, exist_ok=True)
        (bin_dir / "uname").write_text(f"#!/bin/sh\necho {machine}\n")
        (bin_dir / "ldd").write_text(f"#!/bin/sh\necho '{ldd_first_line}'\n")
        for tool in ("uname", "ldd"):
            (bin_dir / tool).chmod(0o755)
        program = "\n".join(
            [
                f"PATH={bin_dir}:$PATH",
                *(f"{n}={pin(n)}" for n in (
                    "COPILOT_VERSION", "COPILOT_SHA256_X86_64", "COPILOT_SHA256_AARCH64",
                    "COPILOT_SHA256_X86_64_MUSL", "COPILOT_SHA256_AARCH64_MUSL",
                )),
                _bash_function("copilot_asset"),
                'copilot_asset || echo "none"; echo "$COPILOT_FILE $COPILOT_SHA"',
            ]
        )  # fmt: skip
        out = subprocess.run(["bash", "-c", program], capture_output=True, text=True, check=False)
        return out.stdout.split()

    row = catalog.COPILOT_SHA256[catalog.COPILOT_VERSION]
    assert asset("x86_64", "ldd (Ubuntu GLIBC 2.39-0ubuntu8.3) 2.39") == ["copilot-linux-x64.tar.gz", row["linux-x64"]]
    assert asset("aarch64", "ldd (Ubuntu GLIBC 2.39-0ubuntu8.3) 2.39") == [
        "copilot-linux-arm64.tar.gz", row["linux-arm64"],
    ]  # fmt: skip
    assert asset("x86_64", "musl libc (x86_64)") == ["copilot-linuxmusl-x64.tar.gz", row["linux-x64-musl"]]
    assert asset("aarch64", "musl libc (aarch64)") == ["copilot-linuxmusl-arm64.tar.gz", row["linux-arm64-musl"]]
    assert asset("riscv64", "ldd (GNU libc) 2.39")[0] == "none"
