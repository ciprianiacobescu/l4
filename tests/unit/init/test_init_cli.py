import json
from pathlib import Path

import pytest
import yaml

from l4.cli import main


def init(target: Path, harness: Path, environ, *flags: str) -> int:
    return main(["init", "--repo", str(target), "--harness", str(harness), *flags], environ=environ)


def test_init_cli_exit_codes_and_flags(target: Path, harness_repo: Path, git_environ, capsys):
    assert init(target, harness_repo, git_environ, "--ci", "gitlab", "--vendor") == 0
    out = capsys.readouterr()
    assert out.out == ""  # the include is written, not printed (M1.8 A1)
    assert "exclude `.l4/` from the repo's own lint" in out.err
    assert (target / ".gitlab-ci.yml").is_file()
    assert init(target, harness_repo, git_environ, "--ci", "gitlab", "--vendor") == 2  # exists, no --force
    assert ".l4/config.yaml" in capsys.readouterr().err
    assert init(target, harness_repo, git_environ, "--ci", "gitlab", "--vendor", "--force") == 0


@pytest.mark.parametrize(
    "flags",
    [
        [],
        ["--ci", "gitlab"],
        ["--vendor"],
        ["--ci", "gitlab", "--vendor", "--dry-run"],
        ["--ci", "gitlab", "--vendor", "--framework", "kiro"],
    ],
)
def test_everything_outside_the_m0_form_is_exit_2_and_writes_nothing(
    flags: list[str], target: Path, harness_repo: Path, git_environ, capsys
):
    assert init(target, harness_repo, git_environ, *flags) == 2
    assert not (target / ".l4").exists() and not (target / ".gitignore").exists()
    assert "init:" in capsys.readouterr().err


def test_init_works_from_the_package_checkout_when_no_harness_is_given(
    target: Path, harness_repo: Path, git_environ, monkeypatch
):
    from l4.init import vendor

    monkeypatch.setattr(vendor, "PACKAGE_FILE", harness_repo / "src" / "l4" / "__init__.py")
    assert main(["init", "--repo", str(target), "--ci", "gitlab", "--vendor"], environ=git_environ) == 0
    config = yaml.safe_load((target / ".l4/config.yaml").read_text())
    assert len(config["harness"]["commit"]) == 40


def test_init_writes_no_outcome_and_prints_no_secret(target: Path, harness_repo: Path, git_environ):
    env = {**git_environ, "L4_FORGE_TOKEN": "glpat-FAKE0123456789abcdefXYZ"}
    assert init(target, harness_repo, env, "--ci", "gitlab", "--vendor") == 0
    assert not (target / ".l4-out").exists()
    written = "".join(p.read_text() for p in (target / ".l4").rglob("*") if p.is_file())
    assert "glpat-" not in written and json.dumps(env["L4_FORGE_TOKEN"]) not in written


def test_init_names_uninstalled_extras_and_the_next_command(target: Path, harness_repo: Path, git_environ, capsys):
    (target / "pyproject.toml").write_text(
        '[project]\nname = "x"\n\n[project.optional-dependencies]\ndev = ["pytest", "ruff"]\nindex = ["chromadb"]\n'
        'embed = ["torch"]\n'
    )
    (target / "uv.lock").write_text("version = 1\n")
    assert init(target, harness_repo, git_environ, "--ci", "gitlab", "--vendor") == 0
    err = capsys.readouterr().err
    assert "extras not installed by gates.setup: embed, index" in err
    assert "l4 doctor --adoption" in err  # the next command, after the files are written
    assert "TODO" in err or "# TODO" in (target / ".l4/config.yaml").read_text()


def test_gitlab_init_writes_the_ci_file(target: Path, harness_repo: Path, git_environ, capsys):
    """A1 (M1.8): the include (and a tagged `test` job) is written, so there is no hand edit left."""
    assert init(target, harness_repo, git_environ, "--ci", "gitlab", "--vendor") == 0
    doc = yaml.safe_load((target / ".gitlab-ci.yml").read_text())
    assert doc["include"] == [{"local": ".l4/ci/l4.gitlab-ci.yml"}]
    assert doc["test"]["tags"] == ["agentic"] and doc["test"]["stage"] == "test"
    assert ".gitlab-ci.yml created with the include" in capsys.readouterr().err
    # an existing file gets only the include
    other = target.parent / "other"
    other.mkdir()
    (other / ".gitlab-ci.yml").write_text("# mine\nbuild:\n  script:\n    - make\n")
    assert init(other, harness_repo, git_environ, "--ci", "gitlab", "--vendor") == 0
    text = (other / ".gitlab-ci.yml").read_text()
    assert text == "# mine\ninclude:\n  - local: .l4/ci/l4.gitlab-ci.yml\n\nbuild:\n  script:\n    - make\n"
    assert (other / ".gitlab-ci.yml").stat().st_mode & 0o777 == 0o644
    # running it again changes nothing
    assert init(other, harness_repo, git_environ, "--ci", "gitlab", "--vendor", "--force") == 0
    assert (other / ".gitlab-ci.yml").read_text() == text


def test_no_ci_edit_prints_the_snippet_and_leaves_the_file(target: Path, harness_repo: Path, git_environ, capsys):
    (target / ".gitlab-ci.yml").write_text("include: ci/a.yml\n")  # a form init could not edit anyway
    assert init(target, harness_repo, git_environ, "--ci", "gitlab", "--vendor", "--no-ci-edit") == 0
    out = capsys.readouterr()
    assert yaml.safe_load(out.out) == {"include": [{"local": ".l4/ci/l4.gitlab-ci.yml"}]}
    assert (target / ".gitlab-ci.yml").read_text() == "include: ci/a.yml\n"
    fresh = target.parent / "fresh"
    fresh.mkdir()
    assert init(fresh, harness_repo, git_environ, "--ci", "gitlab", "--vendor", "--no-ci-edit") == 0
    assert not (fresh / ".gitlab-ci.yml").exists()


def test_refused_ci_edit_writes_nothing(target: Path, harness_repo: Path, git_environ, capsys):
    (target / ".gitlab-ci.yml").write_text("include: [{local: ci/a.yml}]\nbuild:\n  script: [make]\n")
    assert init(target, harness_repo, git_environ, "--ci", "gitlab", "--vendor") == 2
    err = capsys.readouterr().err
    assert ".gitlab-ci.yml" in err and "--no-ci-edit" in err and "local: .l4/ci/l4.gitlab-ci.yml" in err
    assert not (target / ".l4").exists() and not (target / ".gitignore").exists()  # nothing at all was written
    assert (target / ".gitlab-ci.yml").read_text() == "include: [{local: ci/a.yml}]\nbuild:\n  script: [make]\n"


def test_github_only_init_does_not_touch_gitlab_ci(target: Path, harness_repo: Path, git_environ):
    assert init(target, harness_repo, git_environ, "--ci", "github", "--vendor") == 0
    assert not (target / ".gitlab-ci.yml").exists()


def test_init_registers_the_l4_marker(target: Path, harness_repo: Path, git_environ, capsys):
    """P4: the project's own pytest knows `l4` after `init`, so `--strict-markers` collects the harness's tests."""
    (target / "pyproject.toml").write_text('[tool.pytest.ini_options]\nmarkers = [\n    "slow: slow",\n]\n')
    assert init(target, harness_repo, git_environ, "--ci", "gitlab", "--vendor") == 0
    text = (target / "pyproject.toml").read_text()
    assert '    "l4(*ids): the acceptance criteria (C-xxxxxxxx) this test checks",\n]' in text
    assert "registered the l4 pytest marker in pyproject.toml" in capsys.readouterr().err
    # a project with no pytest table gets a conftest, and one whose conftest has pytest_configure gets the snippet
    other = target.parent / "other"
    other.mkdir()
    assert init(other, harness_repo, git_environ, "--ci", "gitlab", "--vendor") == 0
    assert "addinivalue_line" in (other / "conftest.py").read_text()
    assert "registered the l4 pytest marker in conftest.py" in capsys.readouterr().err
    third = target.parent / "third"
    third.mkdir()
    (third / "pytest.ini").write_text("[pytest]\n")
    (third / "conftest.py").write_text("def pytest_configure(config):\n    pass\n")
    assert init(third, harness_repo, git_environ, "--ci", "gitlab", "--vendor") == 0
    err = capsys.readouterr().err
    assert "could not register the l4 pytest marker" in err and "addinivalue_line" in err
    assert (third / "conftest.py").read_text() == "def pytest_configure(config):\n    pass\n"
    # init again (--force): the marker is there, nothing is written and nothing is said
    assert init(target, harness_repo, git_environ, "--ci", "gitlab", "--vendor", "--force") == 0
    assert "registered the l4 pytest marker" not in capsys.readouterr().err
    assert (target / "pyproject.toml").read_text() == text


# --- M1.10 line 25 (C10): the todo lines and a closing line computed from the plan (decision 16) ---


def _next_line(err: str) -> str:
    return next(line for line in err.splitlines() if line.startswith("next: "))


def test_init_prints_the_uv_lock_and_ruff_reminders(target: Path, harness_repo: Path, git_environ, capsys):
    """M1.8 live F4: the reminders were only `# TODO:` lines in the config, which nobody reads."""
    (target / "pyproject.toml").write_text('[project]\nname = "x"\ndependencies = ["click"]\n')  # no lock, no ruff
    assert init(target, harness_repo, git_environ, "--ci", "gitlab", "--vendor") == 0
    err = capsys.readouterr().err
    todos = [line for line in err.splitlines() if line.startswith("todo: ")]
    assert any("there is no uv.lock: run `uv lock` and commit it" in t for t in todos)
    assert any("ruff is not a dependency" in t for t in todos)
    assert all(f"# {t}".replace("# todo", "# TODO") in (target / ".l4/config.yaml").read_text() for t in todos)
    assert err.index(todos[-1]) < err.index("next: ")  # before the closing line
    clean = target.parent / "clean"
    clean.mkdir()
    (clean / "uv.lock").write_text("version = 1\n")
    (clean / "pyproject.toml").write_text('[project]\nname = "y"\n[dependency-groups]\ndev = ["pytest", "ruff"]\n')
    assert init(clean, harness_repo, git_environ, "--ci", "gitlab", "--vendor") == 0
    assert "uv.lock" not in capsys.readouterr().err.replace("commit .l4/", "")  # nothing to remind of


def test_the_closing_line_names_every_file_to_commit(target: Path, harness_repo: Path, git_environ, capsys):
    from l4.memory.ignore import ignored_harness_paths  # noqa: F401  (memory is on: the Serena seed is written too)

    (target / "pyproject.toml").write_text('[tool.pytest.ini_options]\nmarkers = [\n    "slow: slow",\n]\n')
    assert init(target, harness_repo, git_environ, "--ci", "gitlab", "--vendor") == 0
    line = _next_line(capsys.readouterr().err)
    assert line.endswith("then commit .l4/, .gitignore, .gitlab-ci.yml, pyproject.toml and .serena/project.yml")
    assert "the CI file" not in line
    # the marker lands in conftest.py when pyproject.toml has no pytest table
    other = target.parent / "other"
    other.mkdir()
    (other / "pyproject.toml").write_text('[project]\nname = "z"\n')
    assert init(other, harness_repo, git_environ, "--ci", "gitlab", "--vendor") == 0
    line = _next_line(capsys.readouterr().err)
    assert line.endswith("then commit .l4/, .gitignore, .gitlab-ci.yml, conftest.py and .serena/project.yml")
    # a rerun on a committed project: the include is there, the marker too, the gitignore already extended
    assert init(other, harness_repo, git_environ, "--ci", "gitlab", "--vendor", "--force") == 0
    line = _next_line(capsys.readouterr().err)
    assert ".gitignore" not in line and "conftest.py" not in line and ".gitlab-ci.yml" not in line
    assert line.endswith("then commit .l4/")
    # github: its workflow file, and no gitlab file
    third = target.parent / "third"
    third.mkdir()
    assert init(third, harness_repo, git_environ, "--ci", "github", "--vendor") == 0
    line = _next_line(capsys.readouterr().err)
    assert ".github/workflows/l4.yml" in line and ".gitlab-ci.yml" not in line
