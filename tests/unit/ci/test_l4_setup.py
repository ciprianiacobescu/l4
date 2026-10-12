"""`.l4/bin/l4-setup` (L4-PRV-020..022): the rendered script runs under bash against fake `sudo`, `bwrap`, `apt-get`,
`dpkg`, `sysctl`, `curl`, `uv` and `id` on PATH; every fake appends its argv to one log."""

import os
import re
import stat
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from l4.ci.render import SETUP_RELPATH, render_setup
from l4.provision.catalog import UV_VERSION

pytestmark = pytest.mark.skipif(os.name != "posix", reason="the setup script is bash")

SYSCTL_CMD = "sudo -n sysctl -w kernel.apparmor_restrict_unprivileged_userns=0"
KEY = "kernel.apparmor_restrict_unprivileged_userns"

# each fake logs "<name> <argv>" to $FAKE_LOG; the sysctl state lives in $FAKE_STATE/userns
FAKES = {
    "sudo": """\
echo "sudo $*" >> "$FAKE_LOG"
[ "${FAKE_SUDO_FAIL:-0}" = 1 ] && exit 1
[ "$1" = -n ] && shift
exec "$@"
""",
    "bwrap": """\
echo "bwrap $*" >> "$FAKE_LOG"
if [ "$1" = --version ]; then echo "bubblewrap 0.9.0"; exit 0; fi
blocked=${FAKE_BWRAP_BLOCKED:-0}
[ "$blocked" = 1 ] && [ "$(cat "$FAKE_STATE/userns")" != 1 ] && blocked=0
if [ "$blocked" != 0 ]; then
  echo "bwrap: setting up uid map: Permission denied" >&2
  exit 1
fi
exit 0
""",
    "apt-get": """\
echo "apt-get $*" >> "$FAKE_LOG"
if [ "$1" = download ]; then : > "$PWD/bubblewrap_0.9.0-1_amd64.deb"; exit 0; fi
exit 0
""",
    "dpkg": """\
echo "dpkg $*" >> "$FAKE_LOG"
if [ "$1" = -x ]; then mkdir -p "$3/usr/bin"; cp "$FAKE_BWRAP_SRC" "$3/usr/bin/bwrap"; chmod +x "$3/usr/bin/bwrap"; fi
exit 0
""",
    "sysctl": """\
echo "sysctl $*" >> "$FAKE_LOG"
case "$1" in
  -n) cat "$FAKE_STATE/userns" ;;
  -w) echo "${2#*=}" > "$FAKE_STATE/userns"; echo "$2" ;;
esac
""",
    "curl": """\
echo "curl $*" >> "$FAKE_LOG"
[ "${FAKE_CURL_FAIL:-0}" = 1 ] && { echo "curl: (22) The requested URL returned error: 404" >&2; exit 22; }
echo 'mkdir -p "$HOME/.local/bin" && cp "$FAKE_UV_SRC" "$HOME/.local/bin/uv"'
""",
    "uv": """\
echo "uv $*" >> "$FAKE_LOG"
echo "uv 0.12.22"
""",
    "id": """\
case "$1" in
  -u) echo "${FAKE_UID:-1000}" ;;
  -un) echo runner ;;
  *) echo "uid=${FAKE_UID:-1000}(runner)" ;;
esac
""",
}


@dataclass
class Setup:
    tmp: Path
    env: dict[str, str]
    bin: Path
    log: Path
    state: Path
    home: Path
    l4_home: Path
    github_path: Path
    extra: dict[str, str] = field(default_factory=dict)

    def run(self, **env: str) -> subprocess.CompletedProcess[str]:
        script = self.tmp / "l4-setup"
        script.write_text(render_setup())
        full = {**self.env, **env}
        return subprocess.run(
            ["bash", str(script)], env=full, capture_output=True, text=True, check=False, cwd=self.tmp
        )

    def calls(self, prefix: str) -> list[str]:
        lines = self.log.read_text().splitlines() if self.log.exists() else []
        return [ln for ln in lines if ln == prefix or ln.startswith(prefix + " ")]

    def home_files(self) -> list[str]:
        return sorted(str(p.relative_to(self.home)) for p in self.home.rglob("*"))


def make_setup(tmp_path: Path, *, uv: bool = True, apt: bool = True, bwrap_on_path: bool = False) -> Setup:
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    for name, body in FAKES.items():
        if (
            (name == "uv" and not uv)
            or (name in ("apt-get", "dpkg") and not apt)
            or (name == "bwrap" and not bwrap_on_path)
        ):
            continue
        path = fakebin / name
        path.write_text("#!/bin/sh\n" + body)
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
    sources = tmp_path / "sources"
    sources.mkdir()
    for name in ("bwrap", "uv"):  # copy sources for dpkg -x and the fake uv installer, never on PATH
        src = sources / name
        src.write_text("#!/bin/sh\n" + FAKES[name])
        src.chmod(0o755)
    home = tmp_path / "home"
    home.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    (state / "userns").write_text("1\n")
    log = tmp_path / "fake.log"
    github_path = tmp_path / "github_path"
    env = {
        "PATH": f"{fakebin}:/usr/bin:/bin",
        "HOME": str(home),
        "L4_HOME": str(tmp_path / "l4home"),
        "FAKE_LOG": str(log),
        "FAKE_STATE": str(state),
        "FAKE_BWRAP_SRC": str(sources / "bwrap"),
        "FAKE_UV_SRC": str(sources / "uv"),
        "TMPDIR": str(tmp_path),
    }
    return Setup(tmp_path, env, fakebin, log, state, home, tmp_path / "l4home", github_path)


def hosted(**extra: str) -> dict[str, str]:
    return {"L4_SELF_PROVISION": "true", "RUNNER_ENVIRONMENT": "github-hosted", **extra}


def lines(done: subprocess.CompletedProcess[str]) -> list[str]:
    return done.stdout.splitlines()


def test_rendered_script_pins_the_catalog_uv_version():
    text = render_setup()
    assert "@@" not in text and UV_VERSION in text and text.startswith("#!/usr/bin/env bash\n")
    assert SETUP_RELPATH == ".l4/bin/l4-setup"


def test_every_output_line_has_the_hsu_format(tmp_path: Path):
    s = make_setup(tmp_path)
    done = s.run(**hosted(FAKE_BWRAP_BLOCKED="1"))
    assert done.returncode == 0, done.stderr
    assert all(re.match(r"^\[HSU-\d\d\] (OK|FIXED|SKIP|FAILED|INFO|MANUAL) .+ — .+", ln) for ln in lines(done)), (
        done.stdout
    )
    assert lines(done)[-1].startswith("[HSU-99] OK summary")


def test_flag_unset_prints_one_skip_and_changes_nothing(tmp_path: Path):
    s = make_setup(tmp_path, uv=False)
    s.env["GITHUB_PATH"] = str(s.github_path)
    done = s.run()
    assert done.returncode == 0
    assert len(lines(done)) == 1 and lines(done)[0].startswith("[HSU-00] SKIP hosted setup — ")
    assert "only true" in done.stdout and "auto" in done.stdout
    assert s.home_files() == [] and not s.l4_home.exists() and not s.github_path.exists()
    assert s.calls("curl") == s.calls("sudo") == s.calls("apt-get") == []


@pytest.mark.parametrize("value", ["false", "", "yes", "1", "  FALSE "])
def test_flag_not_true_or_auto_skips(tmp_path: Path, value: str):
    s = make_setup(tmp_path)
    done = s.run(L4_SELF_PROVISION=value, RUNNER_ENVIRONMENT="github-hosted")
    assert len(lines(done)) == 1 and lines(done)[0].startswith("[HSU-00] SKIP")
    if value.strip().lower() in ("yes", "1"):
        assert value in lines(done)[0]  # an unrecognised value is named
    assert s.home_files() == []


def test_auto_on_a_hosted_runner_skips(tmp_path: Path):
    s = make_setup(tmp_path)
    done = s.run(L4_SELF_PROVISION="Auto", RUNNER_ENVIRONMENT="github-hosted")
    assert len(lines(done)) == 1 and lines(done)[0].startswith("[HSU-00] SKIP")
    done = s.run(L4_SELF_PROVISION="auto", CI_DISPOSABLE_ENVIRONMENT="true")
    assert len(lines(done)) == 1 and lines(done)[0].startswith("[HSU-00] SKIP")
    assert s.home_files() == []


def test_auto_on_a_persistent_runner_runs(tmp_path: Path):
    s = make_setup(tmp_path)
    done = s.run(L4_SELF_PROVISION="auto")
    assert done.returncode == 0 and len(lines(done)) > 2
    assert not lines(done)[0].startswith("[HSU-00]")


def test_22_04_like_user_space_bwrap_needs_no_sudo(tmp_path: Path):
    s = make_setup(tmp_path)  # userns not blocked: the extracted bwrap passes
    done = s.run(**hosted())
    assert done.returncode == 0, done.stderr
    assert s.calls("sudo") == []
    assert len(s.calls("apt-get download bubblewrap")) == 1
    assert (s.home / ".local/bin/bwrap").is_symlink() and (s.l4_home / "bwrap/usr/bin/bwrap").is_file()
    assert any(ln.startswith("[HSU-04] FIXED") for ln in lines(done))


def test_root_step_only_on_disposable_runner_and_only_the_sysctl(tmp_path: Path):
    s = make_setup(tmp_path)
    done = s.run(**hosted(FAKE_BWRAP_BLOCKED="1"))
    assert done.returncode == 0, done.stderr
    assert s.calls("sudo") == ["sudo -n true", f"sudo -n sysctl -w {KEY}=0"]
    assert not [c for c in s.calls("apt-get") if "install" in c]
    assert (s.state / "userns").read_text().strip() == "0"
    assert (s.home / ".local/bin/bwrap").is_symlink()
    root = [ln for ln in lines(done) if ln.startswith("[HSU-05]")]
    assert len(root) == 1 and root[0].startswith("[HSU-05] FIXED") and "was 1" in root[0] and "now 0" in root[0]
    assert "[HSU-09] INFO bwrap final — " in done.stdout and "user-space" in done.stdout
    # nothing else is run as root and nothing is installed
    assert not [c for c in s.calls("sudo") if "apt" in c or "dpkg" in c]


def test_root_step_with_ci_disposable_environment(tmp_path: Path):
    s = make_setup(tmp_path)
    done = s.run(L4_SELF_PROVISION="true", CI_DISPOSABLE_ENVIRONMENT="true", FAKE_BWRAP_BLOCKED="1")
    assert s.calls("sudo") == ["sudo -n true", f"sudo -n sysctl -w {KEY}=0"], done.stdout


def test_root_user_runs_the_sysctl_without_sudo(tmp_path: Path):
    s = make_setup(tmp_path)
    done = s.run(**hosted(FAKE_BWRAP_BLOCKED="1", FAKE_UID="0"))
    assert s.calls("sudo") == [] and s.calls(f"sysctl -w {KEY}=0") == [f"sysctl -w {KEY}=0"], done.stdout
    assert (s.state / "userns").read_text().strip() == "0"


def test_persistent_runner_never_escalates(tmp_path: Path):
    s = make_setup(tmp_path)
    done = s.run(L4_SELF_PROVISION="true", FAKE_BWRAP_BLOCKED="1")  # no RUNNER_ENVIRONMENT, sudo works
    assert done.returncode == 0
    assert s.calls("sudo") == []
    root = [ln for ln in lines(done) if ln.startswith("[HSU-05]")]
    assert len(root) == 1 and SYSCTL_CMD in root[0] and "not disposable" in root[0]
    assert "NO" in [ln for ln in lines(done) if ln.startswith("[HSU-09]")][0]
    assert not (s.home / ".local/bin/bwrap").exists()  # the failing link would shadow nothing and is not left


def test_opt_out_is_honoured(tmp_path: Path):
    s = make_setup(tmp_path)
    done = s.run(**hosted(FAKE_BWRAP_BLOCKED="1", L4_PROVISION_ROOT="0"))
    assert s.calls("sudo") == []
    root = [ln for ln in lines(done) if ln.startswith("[HSU-05]")]
    assert len(root) == 1 and "L4_PROVISION_ROOT=0" in root[0] and SYSCTL_CMD in root[0]


def test_setting_other_than_1_skips_before_asking_sudo(tmp_path: Path):
    s = make_setup(tmp_path)
    (s.state / "userns").write_text("0\n")  # blocked by something else: the sysctl would not help
    done = s.run(**hosted(FAKE_BWRAP_BLOCKED="always"))
    assert s.calls("sudo") == []
    root = [ln for ln in lines(done) if ln.startswith("[HSU-05]")]
    assert len(root) == 1 and "not 1" in root[0] and SYSCTL_CMD in root[0]


def test_no_passwordless_sudo_skips_after_one_check(tmp_path: Path):
    s = make_setup(tmp_path)
    done = s.run(**hosted(FAKE_BWRAP_BLOCKED="1", FAKE_SUDO_FAIL="1"))
    assert s.calls("sudo") == ["sudo -n true"]
    root = [ln for ln in lines(done) if ln.startswith("[HSU-05]")]
    assert len(root) == 1 and "passwordless sudo" in root[0] and SYSCTL_CMD in root[0]
    assert done.returncode == 0


def test_cached_working_user_space_bwrap_is_kept_and_not_downloaded(tmp_path: Path):
    s = make_setup(tmp_path)
    cached = s.l4_home / "bwrap/usr/bin/bwrap"
    cached.parent.mkdir(parents=True)
    cached.write_text("#!/bin/sh\n" + FAKES["bwrap"])
    cached.chmod(0o755)
    done = s.run(**hosted())
    assert s.calls("apt-get") == [] and s.calls("dpkg") == [] and s.calls("sudo") == []
    assert any(ln.startswith("[HSU-04] OK") and "already present" in ln for ln in lines(done))
    assert (s.home / ".local/bin/bwrap").resolve() == cached.resolve()


def test_cached_failing_user_space_bwrap_is_not_downloaded_again(tmp_path: Path):
    s = make_setup(tmp_path)
    cached = s.l4_home / "bwrap/usr/bin/bwrap"
    cached.parent.mkdir(parents=True)
    cached.write_text("#!/bin/sh\n" + FAKES["bwrap"])
    cached.chmod(0o755)
    link = s.home / ".local/bin/bwrap"
    link.parent.mkdir(parents=True)
    link.symlink_to(cached)  # restored from the cache too
    done = s.run(**hosted(FAKE_BWRAP_BLOCKED="1"))
    assert s.calls("apt-get") == [] and s.calls("dpkg") == []
    assert s.calls("sudo") == ["sudo -n true", f"sudo -n sysctl -w {KEY}=0"]
    assert link.is_symlink() and link.resolve() == cached.resolve()  # removed while failing, re-created after
    assert done.returncode == 0


def test_a_failing_link_is_removed_when_nothing_later_passes(tmp_path: Path):
    s = make_setup(tmp_path)
    cached = s.l4_home / "bwrap/usr/bin/bwrap"
    cached.parent.mkdir(parents=True)
    cached.write_text("#!/bin/sh\n" + FAKES["bwrap"])
    cached.chmod(0o755)
    link = s.home / ".local/bin/bwrap"
    link.parent.mkdir(parents=True)
    link.symlink_to(cached)
    s.run(L4_SELF_PROVISION="true", FAKE_BWRAP_BLOCKED="1")  # persistent: no root step
    assert not link.exists() and not link.is_symlink()


def test_a_working_system_bwrap_is_enough(tmp_path: Path):
    s = make_setup(tmp_path, bwrap_on_path=True)
    done = s.run(**hosted())
    assert s.calls("apt-get") == [] and s.calls("sudo") == []
    assert not (s.l4_home / "bwrap").exists()
    assert any(ln.startswith("[HSU-04] OK") for ln in lines(done))


def test_without_apt_get_the_bwrap_step_is_manual_and_the_script_continues(tmp_path: Path):
    s = make_setup(tmp_path, apt=False)
    done = s.run(L4_SELF_PROVISION="true", FAKE_BWRAP_BLOCKED="1")
    assert done.returncode == 0
    assert any(ln.startswith("[HSU-04] MANUAL") for ln in lines(done))
    assert lines(done)[-1].startswith("[HSU-99]")


def test_uv_is_installed_from_the_pinned_url_when_missing(tmp_path: Path):
    s = make_setup(tmp_path, uv=False)
    s.env["GITHUB_PATH"] = str(s.github_path)
    done = s.run(**hosted())
    assert done.returncode == 0, done.stdout
    assert s.calls("curl") == [f"curl -fsSL https://astral.sh/uv/{UV_VERSION}/install.sh"]
    assert (s.home / ".local/bin/uv").is_file()
    assert any(ln.startswith("[HSU-02] FIXED") and UV_VERSION in ln for ln in lines(done))


def test_missing_uv_and_failing_curl_is_exit_2(tmp_path: Path):
    s = make_setup(tmp_path, uv=False)
    done = s.run(**hosted(FAKE_CURL_FAIL="1"))
    assert done.returncode == 2
    assert any(ln.startswith("[HSU-02] FAILED") for ln in lines(done))
    assert lines(done)[-1].startswith("[HSU-99] FAILED summary")
    assert s.calls("sudo") == []


def test_github_path_gets_local_bin_once(tmp_path: Path):
    s = make_setup(tmp_path)
    s.env["GITHUB_PATH"] = str(s.github_path)
    s.run(**hosted())
    s.run(**hosted())
    assert s.github_path.read_text().splitlines() == [str(s.home / ".local/bin")]


def test_no_credential_variable_is_read_or_printed(tmp_path: Path):
    s = make_setup(tmp_path)
    secrets = {
        "CLAUDE_CODE_OAUTH_TOKEN": "tok-claude-123", "CODEX_API_KEY": "tok-codex-456", "KIRO_API_KEY": "tok-kiro-789",
        "L4_FORGE_TOKEN": "tok-forge-000", "ANTHROPIC_API_KEY": "tok-anth-111",
    }  # fmt: skip
    done = s.run(**hosted(FAKE_BWRAP_BLOCKED="1", **secrets))
    assert not any(v in done.stdout + done.stderr for v in secrets.values())
    text = render_setup()
    assert not re.search(r"TOKEN|API_KEY|SECRET|PASSWORD", text)


def test_the_script_never_runs_sudo_for_facts_or_apt(tmp_path: Path):
    s = make_setup(tmp_path)
    s.run(**hosted())  # 22.04-like
    s.run(L4_SELF_PROVISION="true", RUNNER_ENVIRONMENT="github-hosted", FAKE_BWRAP_BLOCKED="1", L4_PROVISION_ROOT="0")
    assert s.calls("sudo") == []
    assert sys.platform  # the bash script is the same on macOS and Linux
