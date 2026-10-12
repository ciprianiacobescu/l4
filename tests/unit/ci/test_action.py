"""The setup action `.github/actions/l4/action.yml` (adoption-kit L4-ACT-001, L4-ACT-003): the YAML, its shell, and
the first step's script run in a temporary directory."""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from l4.provision import catalog

pytestmark = pytest.mark.skipif(os.name != "posix", reason="the action's steps are bash")

ACTION = Path(__file__).resolve().parents[3] / ".github" / "actions" / "l4" / "action.yml"
DOC = yaml.safe_load(ACTION.read_text(encoding="utf-8"))
STEPS = DOC["runs"]["steps"]
SHA = "0123456789abcdef0123456789abcdef01234567"


def step(step_id: str) -> dict:
    return next(s for s in STEPS if s.get("id") == step_id)


def run_blocks() -> list[tuple[str, str]]:
    return [(s.get("name", "?"), s["run"]) for s in STEPS if "run" in s]


def test_inputs_and_outputs_are_those_of_the_design():
    """SCN-ACT-01: design D1."""
    assert set(DOC["inputs"]) == {
        "source", "repository", "commit", "ssh-key", "python", "uv-version", "self-provision", "clis", "command",
    }  # fmt: skip
    defaults = {k: v.get("default") for k, v in DOC["inputs"].items()}
    assert defaults["source"] == "auto" and defaults["python"] == "3.12"
    assert defaults["self-provision"] == "auto" and defaults["clis"] == "auto" and defaults["command"] == ""
    assert set(DOC["outputs"]) == {"source", "harness-cache-hit", "clis-cache-hit", "version", "clis-cache-key"}


def test_cache_hit_outputs_read_true_or_false():
    """actions/cache leaves `cache-hit` empty on a miss (seen live, run 38301695561): the outputs compare it, so a
    caller reads `true` or `false`, never an empty string."""
    for name, step in (("harness-cache-hit", "restore"), ("clis-cache-hit", "clis")):
        assert DOC["outputs"][name]["value"] == f"${{{{ steps.{step}.outputs.cache-hit == 'true' }}}}"


def test_uv_version_default_equals_the_catalog():
    """The literal default cannot drift from the catalog's uv pin."""
    assert DOC["inputs"]["uv-version"]["default"] == catalog.UV_VERSION


def test_every_step_is_a_composite_bash_step_and_actions_are_pinned_by_sha():
    assert DOC["runs"]["using"] == "composite"
    for s in STEPS:
        if "run" in s:
            assert s["shell"] == "bash"
        else:
            assert re.fullmatch(r"[\w./-]+@[0-9a-f]{40}", s["uses"]), s["uses"]


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck is not installed")
@pytest.mark.parametrize("name,script", run_blocks(), ids=[n for n, _ in run_blocks()])
def test_every_run_block_passes_shellcheck(name, script, tmp_path):
    plain = re.sub(r"\$\{\{.*?\}\}", "PLACEHOLDER", script)
    path = tmp_path / "step.sh"
    path.write_text("#!/usr/bin/env bash\n" + plain, encoding="utf-8")
    done = subprocess.run(["shellcheck", "-s", "bash", str(path)], capture_output=True, text=True)
    assert done.returncode == 0, f"{name}:\n{done.stdout}"


def test_no_run_block_interpolates_an_expression():
    """Inputs reach the shell through `env:` only (no injection through `${{ }}` in a script)."""
    for name, script in run_blocks():
        assert "${{" not in script, name


def test_the_ssh_key_is_removed_on_any_exit_and_never_printed():
    """SCN-ACT-03: the key file goes away by a trap, also when the install fails."""
    script = step("install")["run"]
    assert re.search(r"trap '.*rm -f .*l4-harness-key.*' EXIT", script)
    for _, body in run_blocks():
        assert not re.search(r"echo[^\n]*\$(INPUT_SSH_KEY|\{INPUT_SSH_KEY)", body)
        assert "set -x" not in body and "xtrace" not in body


# ---- the first step run for real -------------------------------------------------------------------------------


def run_source(
    tmp_path: Path, *, harness_in_root: bool, runner_environment: str = "github-hosted", **inputs: str
) -> subprocess.CompletedProcess:
    root = tmp_path / "root"
    action_dir = root / ".github" / "actions" / "l4"
    action_dir.mkdir(parents=True)
    if harness_in_root:
        (root / "src" / "l4").mkdir(parents=True)
        (root / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
        (root / "README.md").write_text("x\n", encoding="utf-8")
    script = tmp_path / "step.sh"
    script.write_text(step("src")["run"], encoding="utf-8")
    out = tmp_path / "out"
    out.write_text("", encoding="utf-8")
    env = {
        "PATH": os.environ["PATH"], "GITHUB_ACTION_PATH": str(action_dir), "GITHUB_OUTPUT": str(out),
        "RUNNER_OS": "Linux", "RUNNER_ARCH": "X64", "ImageOS": "ubuntu24", "RUNNER_ENVIRONMENT": runner_environment,
        "INPUT_SOURCE": "auto", "INPUT_COMMIT": "", "INPUT_REPOSITORY": "", "INPUT_PYTHON": "3.12",
        "INPUT_UV_VERSION": catalog.UV_VERSION, "INPUT_SELF_PROVISION": "auto", "INPUT_CLIS": "auto",
    }  # fmt: skip
    env.update({f"INPUT_{k.upper()}": v for k, v in inputs.items()})
    return subprocess.run(["bash", "-e", str(script)], env=env, capture_output=True, text=True, cwd=tmp_path)


def outputs(tmp_path: Path) -> dict[str, str]:
    pairs = (line.partition("=") for line in (tmp_path / "out").read_text(encoding="utf-8").splitlines())
    return {k: v for k, _, v in pairs}


def test_auto_picks_action_when_the_repository_holds_the_harness(tmp_path):
    """SCN-ACT-01: no key, no commit."""
    done = run_source(tmp_path, harness_in_root=True)
    assert done.returncode == 0, done.stdout + done.stderr
    got = outputs(tmp_path)
    assert got["mode"] == "action" and got["dir"] == str(tmp_path / "root")
    assert re.fullmatch(r"l4-harness-Linux-X64-ubuntu24-py3\.12-action-[0-9a-f]{24}", got["key"])
    assert "[l4-action] source action" in done.stdout


def test_auto_picks_repository_when_it_holds_none(tmp_path):
    """SCN-ACT-02: a public caller's copy of the action holds no harness."""
    done = run_source(tmp_path, harness_in_root=False, commit=SHA, repository="ssh://git@github.com/o/r.git")
    assert done.returncode == 0, done.stdout + done.stderr
    got = outputs(tmp_path)
    assert got["mode"] == "repository" and got["key"].endswith(f"-py3.12-repository-{SHA}")


@pytest.mark.parametrize(
    "inputs,fragment",
    [
        ({"source": "bogus"}, "source must be"),
        ({"source": "repository", "commit": "abc", "repository": "ssh://x"}, "commit must be 40 hex"),
        ({"source": "repository", "commit": SHA.upper(), "repository": "ssh://x"}, "commit must be 40 hex"),
        ({"source": "repository", "commit": SHA, "repository": ""}, "repository is required"),
        ({"source": "action"}, "holds no harness"),
        ({"python": "3.12; rm -rf /"}, "python must look like"),
        ({"uv_version": "latest"}, "uv-version must look like"),
        ({"self_provision": "maybe"}, "self-provision must be"),
        ({"clis": "all"}, "clis must be"),
    ],
)
def test_bad_inputs_are_error_and_exit_2_before_any_download(tmp_path, inputs, fragment):
    """SCN-ACT-04 (-): the step has no network command, and says what is wrong without echoing the value."""
    done = run_source(tmp_path, harness_in_root=False, **inputs)
    assert done.returncode == 2, done.stdout + done.stderr
    assert f"::error::{fragment}" in done.stdout or fragment in done.stdout
    assert "::error::" in done.stdout
    for key, value in inputs.items():
        if key in {"commit", "repository", "python", "uv_version"} and value:  # free text, never echoed
            assert value not in done.stdout + done.stderr
    assert not (tmp_path / "out").read_text(encoding="utf-8").count("mode=")


def test_the_source_step_downloads_nothing():
    script = step("src")["run"]
    for command in ("curl", "wget", "git clone", "uv tool", "uvx", "pip"):
        assert command not in script


@pytest.mark.parametrize(
    "runner_environment,given,expected",
    [("github-hosted", "auto", "true"), ("self-hosted", "auto", "auto"), ("github-hosted", "false", "false"),
     ("self-hosted", "true", "true")],
)  # fmt: skip
def test_self_provision_switch_is_resolved_for_the_setup(tmp_path, runner_environment, given, expected):
    """SCN-ACT-07: `auto` means on for a GitHub-hosted runner; the setup script gets the resolved switch."""
    done = run_source(tmp_path, harness_in_root=True, runner_environment=runner_environment, self_provision=given)
    assert done.returncode == 0, done.stdout + done.stderr
    assert outputs(tmp_path)["provision"] == expected


def test_setup_runs_the_harness_script(tmp_path):
    """SCN-ACT-07: the setup step pipes `l4 ci render-setup` to bash with `L4_SELF_PROVISION` and exports the same
    switch to later steps (so `doctor --ci --fix` installs the CLIs)."""
    setup = step("setup")
    assert setup["env"]["PROVISION"] == "${{ steps.src.outputs.provision }}"
    home = tmp_path / "home"
    (home / ".local" / "bin").mkdir(parents=True)
    fake = home / ".local" / "bin" / "l4"
    fake.write_text(
        '#!/usr/bin/env bash\n[ "$*" = "ci render-setup" ] || exit 9\n'
        "echo 'echo \"[HSU-99] OK summary switch=$L4_SELF_PROVISION\"'\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    script = tmp_path / "setup.sh"
    script.write_text(setup["run"], encoding="utf-8")
    genv = tmp_path / "genv"
    env = {"PATH": os.environ["PATH"], "HOME": str(home), "PROVISION": "true", "GITHUB_ENV": str(genv)}
    done = subprocess.run(["bash", "-e", str(script)], env=env, capture_output=True, text=True, cwd=tmp_path)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "[HSU-99] OK summary switch=true" in done.stdout
    assert "L4_SELF_PROVISION=true" in genv.read_text(encoding="utf-8")


def test_setup_failure_is_the_scripts_exit_code(tmp_path):
    """SCN-ACT-07 (-): `pipefail` keeps a failing render or a script exit 2 visible."""
    setup = step("setup")
    home = tmp_path / "home"
    (home / ".local" / "bin").mkdir(parents=True)
    fake = home / ".local" / "bin" / "l4"
    fake.write_text("#!/usr/bin/env bash\necho 'exit 2'\n", encoding="utf-8")
    fake.chmod(0o755)
    script = tmp_path / "setup.sh"
    script.write_text(setup["run"], encoding="utf-8")
    env = {"PATH": os.environ["PATH"], "HOME": str(home), "PROVISION": "auto", "GITHUB_ENV": str(tmp_path / "e")}
    assert subprocess.run(["bash", "-e", str(script)], env=env, capture_output=True, cwd=tmp_path).returncode == 2
