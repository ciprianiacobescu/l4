"""`dry_run_gates` (M1.8 A3): the gates run in a detached worktree of HEAD, before the first unit does."""

from pathlib import Path

import pytest
import yaml

from l4.config.schema import L4Config
from l4.gates.dryrun import dry_run_gates

FAILING = "def test_base_failure():\n    assert 1 == 2\n"
PASSING = "def test_base_ok():\n    assert 1 == 1\n"


def cfg_of(tdd_repo, **sandbox) -> L4Config:
    body = yaml.safe_load(tdd_repo.config(sandbox=sandbox or None))
    return L4Config.model_validate(body)


def commit(tdd_repo, raw, name: str, text: str) -> None:
    (tdd_repo.repo / "tests" / name).write_text(text)
    raw(tdd_repo.repo, "add", "-A")
    raw(tdd_repo.repo, "commit", "-q", "-m", f"add {name}")


def worktrees(raw, repo: Path) -> list[str]:
    return [line for line in raw(repo, "worktree", "list", "--porcelain").splitlines() if line.startswith("worktree ")]


def test_failing_tests_at_head_are_reported_and_no_worktree_is_left(tdd_repo, raw):
    commit(tdd_repo, raw, "test_base_failure.py", FAILING)
    head = raw(tdd_repo.repo, "rev-parse", "HEAD").strip()
    result = dry_run_gates(cfg_of(tdd_repo), tdd_repo.repo, tdd_repo.environ, in_ci=False)
    assert not result.ok and result.error == "" and result.sha == head
    by_gate = {run.gate: run for run in result.runs}
    assert by_gate["setup"].status == "pass" and by_gate["test"].status == "fail"
    assert any(t.endswith("test_base_failure") for t in by_gate["test"].failing_tests)
    assert result.sandbox.startswith("none")  # the fixture config accepts running without a sandbox
    assert len(worktrees(raw, tdd_repo.repo)) == 1  # only the checkout itself
    assert not (tdd_repo.cache / "adoption" / head[:12]).exists()


def test_a_green_base_passes_and_reports_the_test_count(tdd_repo, raw):
    result = dry_run_gates(cfg_of(tdd_repo), tdd_repo.repo, tdd_repo.environ, in_ci=False)
    assert result.ok, [(r.gate, r.reason) for r in result.runs]
    test = next(r for r in result.runs if r.gate == "test")
    assert test.status == "pass" and test.tests_passed and test.tests_passed > 0


def test_uncommitted_changes_are_not_in_the_dry_run(tdd_repo, raw):
    commit(tdd_repo, raw, "test_base_failure.py", FAILING)
    (tdd_repo.repo / "tests" / "test_base_failure.py").write_text(PASSING.replace("base_ok", "base_failure"))
    result = dry_run_gates(cfg_of(tdd_repo), tdd_repo.repo, tdd_repo.environ, in_ci=False)
    assert not result.ok  # the working tree is green, HEAD is not: HEAD is what a run starts from
    assert (tdd_repo.repo / "tests" / "test_base_failure.py").read_text().count("== 1") == 1  # and it is untouched


def test_in_ci_without_a_sandbox_it_fails_instead_of_running(tdd_repo, raw, monkeypatch):
    from l4.gates import dryrun

    monkeypatch.setattr(dryrun, "resolve_tool", lambda name, environ, forbid=(): None)
    cfg = L4Config.model_validate({**yaml.safe_load(tdd_repo.config()), "sandbox": {"mode": "auto"}})
    result = dry_run_gates(cfg, tdd_repo.repo, tdd_repo.environ, in_ci=True)
    assert not result.ok and "sandbox" in result.error and result.runs == ()
    assert len(worktrees(raw, tdd_repo.repo)) == 1 and not (tdd_repo.cache / "adoption").exists()


def test_outside_ci_without_bwrap_the_gates_run_unsandboxed_and_say_so(tdd_repo, raw, monkeypatch):
    from l4.gates import dryrun

    monkeypatch.setattr(dryrun, "resolve_tool", lambda name, environ, forbid=(): None)
    cfg = L4Config.model_validate({**yaml.safe_load(tdd_repo.config()), "sandbox": {"mode": "auto"}})
    result = dry_run_gates(cfg, tdd_repo.repo, tdd_repo.environ, in_ci=False)
    assert result.ok and "unsandboxed" in result.sandbox


def test_a_failing_setup_skips_the_rest(tdd_repo, raw):
    body = yaml.safe_load(tdd_repo.config())
    body["gates"]["setup"] = ["false"]
    result = dry_run_gates(L4Config.model_validate(body), tdd_repo.repo, tdd_repo.environ, in_ci=False)
    gates = {r.gate: r.status for r in result.runs}
    assert gates["setup"] == "fail" and gates["test"] == "skipped" and not result.ok


def test_lint_failure_keeps_its_first_lines(tdd_repo, raw):
    body = yaml.safe_load(tdd_repo.config())
    body["gates"]["lint"] = ["sh -c 'echo F401 unused import; echo E501 too long; exit 1'"]
    result = dry_run_gates(L4Config.model_validate(body), tdd_repo.repo, tdd_repo.environ, in_ci=False)
    lint = next(r for r in result.runs if r.gate == "lint")
    assert lint.status == "fail" and "F401 unused import" in lint.excerpt


def test_no_commit_is_an_error_not_a_crash(tmp_path, git_environ, raw):
    repo = tmp_path / "empty"
    repo.mkdir()
    raw(repo, "init", "-q")
    result = dry_run_gates(L4Config(), repo, {**git_environ, "L4_CACHE": str(tmp_path / "c")}, in_ci=False)
    assert not result.ok and "commit" in result.error


@pytest.mark.parametrize("gate", ["build", "typecheck"])
def test_every_configured_gate_kind_runs(tdd_repo, gate):
    body = yaml.safe_load(tdd_repo.config())
    body["gates"][gate] = ["true"]
    result = dry_run_gates(L4Config.model_validate(body), tdd_repo.repo, tdd_repo.environ, in_ci=False)
    assert next(r for r in result.runs if r.gate == gate).status == "pass"


def test_a_failing_ruff_check_is_run_again_narrowed(tdd_repo, raw):
    script = tdd_repo.repo / "ruff"
    script.write_text('#!/bin/sh\nfor a in "$@"; do [ "$a" = "--select" ] && exit 0; done\necho F401 unused\nexit 1\n')
    script.chmod(0o755)
    raw(tdd_repo.repo, "add", "-A")
    raw(tdd_repo.repo, "commit", "-q", "-m", "a ruff")
    body = yaml.safe_load(tdd_repo.config())
    body["gates"]["lint"] = ["./ruff check ."]
    result = dry_run_gates(L4Config.model_validate(body), tdd_repo.repo, tdd_repo.environ, in_ci=False)
    lint = next(r for r in result.runs if r.gate == "lint")
    assert lint.status == "fail" and lint.narrowed == "./ruff check --select F,E9 ." and lint.narrowed_ok is True


# --- M1.10 (C9): path narrowing, a third lint run (decision 15; L4-DOC-001 GATE-001, L4-GAT-003) ---


def test_project_dirs_from_pyproject_then_conventional_dirs(tmp_path):
    from l4.gates.pyproject import PyProject, project_dirs

    for name in ("lib", "spec", "src/demo", "demo", "tests", "docs"):
        (tmp_path / name).mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text(
        '[tool.ruff]\nsrc = ["lib", "missing"]\n[tool.pytest.ini_options]\ntestpaths = ["spec"]\n'
        '[tool.hatch.build.targets.wheel]\npackages = ["src/demo"]\n'
    )
    project = PyProject(True, "demo")
    # pyproject first (ruff.src, testpaths, hatch packages), a directory that does not exist is left out, a directory
    # inside another of the list too (`src/demo` is in `src`), at most 4
    assert project_dirs(tmp_path, project) == ("lib", "spec", "src", "demo")
    (tmp_path / "pyproject.toml").write_text(
        '[tool.setuptools.packages.find]\nwhere = ["src"]\n[tool.setuptools.package-dir]\n"" = "lib"\n'
    )
    assert project_dirs(tmp_path, project) == ("src", "lib", "demo", "tests")  # then the conventional ones
    (tmp_path / "pyproject.toml").unlink()
    assert project_dirs(tmp_path, PyProject()) == ("src", "tests")
    (tmp_path / "pyproject.toml").write_text('[tool.ruff]\nsrc = ["../outside", "/etc", "lib/../../x"]\n')
    assert project_dirs(tmp_path, PyProject()) == ("src", "tests")  # nothing outside the repository


def test_narrow_ruff_paths_replaces_the_dot_and_keeps_options():
    from l4.gates.dryrun import narrow_ruff_paths

    dirs = ("src", "tests")
    assert narrow_ruff_paths("ruff check --select F,E9 .", dirs) == "ruff check --select F,E9 src tests"
    assert (
        narrow_ruff_paths("uv run ruff check --select F,E9 --line-length 92 --output-format=concise .", dirs)
        == "uv run ruff check --select F,E9 --line-length 92 --output-format=concise src tests"
    )
    assert narrow_ruff_paths("./ruff check --select F,E9 --exclude 'build dir' --fix", dirs) == (
        "./ruff check --select F,E9 --exclude 'build dir' --fix src tests"
    )  # no path given: ruff checks `.`, so the directories are added
    assert narrow_ruff_paths("ruff check --select F,E9 src", dirs) is None  # the project chose its paths
    assert narrow_ruff_paths("ruff check --select F,E9 .", ()) is None  # no directory to narrow to


def test_an_unknown_option_shape_gives_none():
    from l4.gates.dryrun import narrow_ruff_paths

    dirs = ("src",)
    assert narrow_ruff_paths("ruff check --select F,E9 --frobnicate x .", dirs) is None  # may take a value: unknown
    assert narrow_ruff_paths("ruff check --select F,E9 -Z .", dirs) is None
    assert narrow_ruff_paths("ruff format .", dirs) is None and narrow_ruff_paths("eslint .", dirs) is None
    assert narrow_ruff_paths("ruff check --select 'F,E9 .", dirs) is None  # does not parse
    assert narrow_ruff_paths("ruff check --select", dirs) is None  # a value option with no value


def test_a_path_narrowed_run_follows_a_failing_rule_narrowed_one(tdd_repo, raw):
    script = tdd_repo.repo / "ruff"
    script.write_text('#!/bin/sh\nfor a in "$@"; do [ "$a" = "." ] && echo "F401 in ./build" && exit 1; done\nexit 0\n')
    script.chmod(0o755)
    raw(tdd_repo.repo, "add", "-A")
    raw(tdd_repo.repo, "commit", "-q", "-m", "a ruff that fails on the dot only")
    body = yaml.safe_load(tdd_repo.config())
    body["gates"]["lint"] = ["./ruff check ."]
    result = dry_run_gates(L4Config.model_validate(body), tdd_repo.repo, tdd_repo.environ, in_ci=False)
    lint = next(r for r in result.runs if r.gate == "lint")
    assert lint.status == "fail" and lint.narrowed == "./ruff check --select F,E9 ." and lint.narrowed_ok is False
    # the fixture's pyproject names `tests` (pytest testpaths) and `src/pytdd` (hatch): `src` already holds the latter
    assert lint.narrowed_paths == "./ruff check --select F,E9 tests src" and lint.narrowed_paths_ok is True
    # a rule-narrowed run that passes needs no third run
    body["gates"]["lint"] = ["./ruff check src"]
    quiet = dry_run_gates(L4Config.model_validate(body), tdd_repo.repo, tdd_repo.environ, in_ci=False)
    assert next(r for r in quiet.runs if r.gate == "lint").narrowed_paths is None


# --- L4-SEC-035: the dry run empties the tool caches before each gate that does not build the environment ---

CACHES = (".cache", ".vite", ".vite-temp", ".vitest-cache")
FRESH_INSTALL = (  # what a fresh `pnpm install` leaves: a package, a stale cache entry and a symlinked cache
    "set -e\nmkdir -p node_modules/pkg node_modules/.vite\necho x > node_modules/pkg/index.js\n"
    'echo x > node_modules/.vite/stale\nln -s "$1" node_modules/.vitest-cache\n'
)
CACHES_EMPTY = (
    "for d in .cache .vite .vite-temp .vitest-cache; do\n  p=node_modules/$d\n"
    '  if [ ! -d "$p" ] || [ -L "$p" ]; then echo "not a real directory: $p"; exit 1; fi\n'
    '  if [ -n "$(ls -A "$p")" ]; then echo "not empty: $p"; exit 1; fi\ndone\n'
)


def commit_files(tdd_repo, raw, files: dict[str, str]) -> None:
    for name, text in files.items():
        path = tdd_repo.repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    raw(tdd_repo.repo, "add", "-A")
    raw(tdd_repo.repo, "commit", "-q", "-m", "files")


def gates_cfg(tdd_repo, *, setup: str, lint: str) -> L4Config:
    body = yaml.safe_load(tdd_repo.config())
    body["gates"].update({"setup": [setup], "lint": [lint], "test": {"command": ""}})
    return L4Config.model_validate(body)


def test_a_gate_after_a_fresh_install_finds_the_tool_caches_empty(tdd_repo, raw, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("k\n")
    commit_files(tdd_repo, raw, {"install.sh": FRESH_INSTALL, "check.sh": CACHES_EMPTY})
    config = gates_cfg(tdd_repo, setup=f"sh install.sh {outside}", lint="sh check.sh")
    result = dry_run_gates(config, tdd_repo.repo, tdd_repo.environ, in_ci=False)
    assert [(r.gate, r.status) for r in result.runs] == [("setup", "pass"), ("lint", "pass")], result.runs
    assert (outside / "keep.txt").read_text() == "k\n"  # the symlink was unlinked, not followed


def test_the_tool_caches_exist_when_the_sandbox_spec_of_the_gate_is_built(tdd_repo, raw, tmp_path, monkeypatch):
    from l4.gates import dryrun

    outside = tmp_path / "outside"
    outside.mkdir()
    commit_files(tdd_repo, raw, {"install.sh": FRESH_INSTALL, "check.sh": CACHES_EMPTY})
    seen: dict[str, bool] = {}
    real = dryrun.gate_sandbox_spec

    def watching(*, worktree, builds_env, **kw):
        seen["setup" if builds_env else "lint"] = all(
            (worktree / "node_modules" / name).is_dir() and not (worktree / "node_modules" / name).is_symlink()
            for name in CACHES
        )
        return real(worktree=worktree, builds_env=builds_env, **kw)

    monkeypatch.setattr(dryrun, "gate_sandbox_spec", watching)
    config = gates_cfg(tdd_repo, setup=f"sh install.sh {outside}", lint="sh check.sh")
    result = dry_run_gates(config, tdd_repo.repo, tdd_repo.environ, in_ci=False)
    assert [r.status for r in result.runs] == ["pass", "pass"]
    assert seen == {"setup": False, "lint": True}  # the setup gate is left alone, the next gate's spec sees the caches


def test_a_tracked_node_modules_is_source_and_keeps_its_cache_folder(tdd_repo, raw):
    commit_files(tdd_repo, raw, {
        "vendor/node_modules/lib.js": "x\n",
        "install.sh": "set -e\nmkdir -p vendor/node_modules/.cache\necho k > vendor/node_modules/.cache/keep\n",
        "check.sh": "test -f vendor/node_modules/.cache/keep\n",
    })  # fmt: skip
    config = gates_cfg(tdd_repo, setup="sh install.sh", lint="sh check.sh")
    result = dry_run_gates(config, tdd_repo.repo, tdd_repo.environ, in_ci=False)
    assert [(r.gate, r.status) for r in result.runs] == [("setup", "pass"), ("lint", "pass")], result.runs
