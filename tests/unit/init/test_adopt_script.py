"""`scripts/adopt.sh` offline: a stub `uv` first on PATH logs its argv and, for `run ... l4 init`, writes what the real
init would (config, shim, CI file); the shim stub logs its argv and exits with $L4_STUB_DOCTOR_EXIT."""

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "adopt.sh"
HARNESS = SCRIPT.parent.parent

UV_STUB = r"""#!/usr/bin/env bash
echo "uv $*" >> "$L4_STUB_LOG"
case "$1" in
  --version) echo "uv 0.0.0-stub";;
  run)
    all=" $* "; repo=""; ci=""; sub=""
    while [ $# -gt 0 ]; do
      case "$1" in
        init|upgrade) sub=$1;; --repo) repo=$2; shift;; --ci) ci=$2; shift;;
      esac
      shift
    done
    if [ "$sub" = init ]; then
      case "$all" in *" --dry-run "*) exit 0;; esac
      mkdir -p "$repo/.l4/bin"
      echo "gates: {}" > "$repo/.l4/config.yaml"
      printf '#!/usr/bin/env bash\necho "l4 $*" >> "$L4_STUB_LOG"\n' > "$repo/.l4/bin/l4"
      printf 'exit "${L4_STUB_DOCTOR_EXIT:-0}"\n' >> "$repo/.l4/bin/l4"
      chmod +x "$repo/.l4/bin/l4"
      echo ".l4-out/" >> "$repo/.gitignore"
      mkdir -p "$repo/.serena"; echo "memory: {}" > "$repo/.serena/project.yml"
      echo "# marker" >> "$repo/conftest.py"
      if [ "$ci" = github ]; then
        mkdir -p "$repo/.github/workflows"
        printf 'jobs:\n  l4:\n    runs-on: ["self-hosted", "agentic"]\n' > "$repo/.github/workflows/l4.yml"
        printf '    env:\n      L4_FORGE_TOKEN: ${{ secrets.L4_FORGE_TOKEN }}\n' >> "$repo/.github/workflows/l4.yml"
      else
        echo "include: [{local: .l4/ci/l4.gitlab-ci.yml}]" > "$repo/.gitlab-ci.yml"
      fi
    fi;;
esac
exit 0
"""


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout


@pytest.fixture
def env(tmp_path: Path) -> dict[str, str]:
    stub = tmp_path / "stub"
    stub.mkdir()
    uv = stub / "uv"
    uv.write_text(UV_STUB)
    uv.chmod(uv.stat().st_mode | stat.S_IXUSR)
    home = tmp_path / "home"
    home.mkdir()
    return {
        **os.environ,
        "PATH": f"{stub}:{os.environ['PATH']}",
        "HOME": str(home),
        "L4_STUB_LOG": str(tmp_path / "uv.log"),
        "GIT_CONFIG_GLOBAL": str(tmp_path / "gitconfig"),
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com",
    }


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    r = tmp_path / "project"
    r.mkdir()
    git(r, "init", "-q", "-b", "main")
    (r / "app.py").write_text("x = 1\n")
    git(r, "add", "-A")
    git(r, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "init")
    return r


def adopt(env: dict[str, str], repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), "--repo", str(repo), *args], env=env, capture_output=True, text=True, cwd=repo
    )


def log(env: dict[str, str]) -> str:
    p = Path(env["L4_STUB_LOG"])
    return p.read_text() if p.exists() else ""


def test_syntax_and_shellcheck():
    assert subprocess.run(["bash", "-n", str(SCRIPT)]).returncode == 0
    if shutil.which("shellcheck"):
        assert subprocess.run(["shellcheck", str(SCRIPT)]).returncode == 0
    assert SCRIPT.stat().st_mode & stat.S_IXUSR


def test_github_origin_selects_github_and_first_run_vendors(env, repo):
    git(repo, "remote", "add", "origin", "https://github.com/example/proj.git")
    r = adopt(env, repo)
    assert r.returncode == 0, r.stdout + r.stderr
    out = log(env)
    assert "init --repo" in out and "--ci github --vendor" in out and "upgrade" not in out
    assert "sync --frozen --project" in out
    assert "l4 doctor --adoption" in out
    assert "L4_FORGE_TOKEN" in r.stdout and '["self-hosted", "agentic"]' in r.stdout
    assert "adopt: done (exit 0)" in r.stdout


def test_gitlab_like_origin_selects_gitlab(env, repo):
    git(repo, "remote", "add", "origin", "https://gitlab.example.com/group/name.git")
    r = adopt(env, repo)
    assert r.returncode == 0
    assert "--ci gitlab --vendor" in log(env)


def test_no_origin_and_no_gitlab_ci_is_refused(env, repo):
    r = adopt(env, repo)
    assert r.returncode == 2
    assert "pass --ci gitlab or --ci github" in r.stdout
    assert "init" not in log(env)


def test_framework_is_passed_through(env, repo):
    r = adopt(env, repo, "--ci", "gitlab", "--framework", "kiro")
    assert r.returncode == 0
    assert "--framework kiro" in log(env)


def test_second_run_upgrades_instead_of_init(env, repo):
    assert adopt(env, repo, "--ci", "gitlab").returncode == 0
    Path(env["L4_STUB_LOG"]).unlink()
    r = adopt(env, repo, "--ci", "gitlab")
    assert r.returncode == 0
    out = log(env)
    assert "upgrade --repo" in out and " init " not in out
    assert "already adopted" in r.stdout


def test_dry_run_passes_flag_and_skips_sync_and_doctor(env, repo):
    r = adopt(env, repo, "--ci", "gitlab", "--dry-run", "--commit")
    assert r.returncode == 0
    out = log(env)
    assert "--dry-run" in out and "sync" not in out and "doctor" not in out
    assert not (repo / ".l4").exists()
    assert git(repo, "rev-list", "--count", "HEAD").strip() == "1"


def test_red_base_exits_3_and_does_not_commit(env, repo):
    env["L4_STUB_DOCTOR_EXIT"] = "3"
    r = adopt(env, repo, "--ci", "gitlab", "--commit")
    assert r.returncode == 3
    assert "adopt: done (exit 3)" in r.stdout and "fix what doctor lists" in r.stdout
    assert git(repo, "rev-list", "--count", "HEAD").strip() == "1"


def test_commit_stages_what_the_adoption_wrote_and_nothing_else(env, repo):
    (repo / "notes.txt").write_text("unrelated\n")
    (repo / "app.py").write_text("x = 2\n")  # a tracked file the user modified
    r = adopt(env, repo, "--ci", "github", "--commit")
    assert r.returncode == 0, r.stdout + r.stderr
    assert git(repo, "rev-list", "--count", "HEAD").strip() == "2"
    assert git(repo, "log", "-1", "--format=%s").strip() == "Adopt the L4 harness"
    files = git(repo, "show", "--name-only", "--format=", "HEAD").split()
    for wanted in (".github/workflows/l4.yml", ".l4/config.yaml", ".l4/bin/l4", ".gitignore", ".serena/project.yml",
                   "conftest.py"):
        assert wanted in files, wanted
    assert "notes.txt" not in files and "app.py" not in files
    assert sorted(git(repo, "status", "--porcelain").splitlines()) == [" M app.py", "?? notes.txt"]


def test_harness_checkout_as_repo_is_refused(env):
    r = subprocess.run(
        ["bash", str(SCRIPT), "--repo", str(HARNESS), "--ci", "gitlab"], env=env, capture_output=True, text=True
    )
    assert r.returncode == 2
    assert "harness checkout itself" in r.stdout


def test_no_install_without_uv_prints_installer_command(env, repo):
    path = "/usr/bin:/bin"
    if any((Path(d) / "uv").exists() for d in path.split(":")):
        pytest.skip("uv lives in a system directory here")
    env["PATH"] = path
    r = adopt(env, repo, "--ci", "gitlab", "--no-install")
    assert r.returncode == 2
    assert "https://astral.sh/uv/" in r.stdout and "install.sh" in r.stdout


@pytest.mark.parametrize(
    ("origin", "url"),
    [
        ("git@gitlab.example.com:group/name.git", "https://gitlab.example.com"),
        ("ssh://git@gitlab.example.com:2222/group/name.git", "https://gitlab.example.com"),
        ("https://gitlab.example.com/group/name.git", "https://gitlab.example.com"),
        ("https://gitlab.example.com:8443/group/name.git", "https://gitlab.example.com:8443"),
    ],
)
def test_gitlab_next_steps_derive_the_project_path_and_the_server(env, repo, origin, url):
    git(repo, "remote", "add", "origin", origin)
    r = adopt(env, repo)
    assert r.returncode == 0
    assert "--project group/name --watch" in r.stdout
    assert "push -o ci.skip -u origin main" in r.stdout
    assert f"gitlab-runner register --non-interactive --url {url} --token" in r.stdout


def test_gitlab_next_steps_put_the_runner_before_setup(env, repo):
    git(repo, "remote", "add", "origin", "https://gitlab.example.com/group/name.git")
    out = adopt(env, repo).stdout
    assert out.index("push -o ci.skip") < out.index("the runner (below)") < out.index("setup gitlab")
    assert "gitlab-runner register" in out and "PROJECT runner" in out


def test_github_next_steps_put_the_runner_before_the_secret(env, repo):
    git(repo, "remote", "add", "origin", "https://github.com/example/proj.git")
    out = adopt(env, repo).stdout
    assert out.index("push -u origin") < out.index("the runner (below)") < out.index("add a repository secret")


def test_commit_on_a_clean_tree_stages_the_whole_adoption(env, repo):
    r = adopt(env, repo, "--ci", "gitlab", "--commit")
    assert r.returncode == 0, r.stdout + r.stderr
    assert git(repo, "status", "--porcelain").strip() == ""
    assert ".gitlab-ci.yml" in git(repo, "show", "--name-only", "--format=", "HEAD").split()
