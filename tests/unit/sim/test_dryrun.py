"""`l4 run --dry-run` changes nothing (SCN-DRY-01) and probes only when asked (SCN-DRY-02)."""

import subprocess
from pathlib import Path

import pytest

from l4 import archive
from l4.agents import factory
from l4.agents.base import ProbeResult
from l4.cli import main


class Scripted:
    def __init__(self, fail: str | None = None) -> None:
        self.steps: list[str] = []
        self.fail = fail
        self.runs = 0

    def probe(self, profile, step, ctx):
        self.steps.append(step)
        ok = step != self.fail
        return ProbeResult(step, ok, {}, reason=None if ok else f"{step} refused")

    def run(self, req):
        self.runs += 1
        raise AssertionError("a dry run starts no agent")


def state_of(tdd, raw) -> dict:
    """Everything a dry run must leave as it was: refs, tracked and untracked files outside `.l4-out`, the cache."""
    repo = tdd.repo
    files = {
        str(p.relative_to(repo)): p.read_bytes()
        for p in sorted(repo.rglob("*"))
        if p.is_file() and ".git" not in p.parts and ".l4-out" not in p.parts
    }
    return {
        "refs": raw(repo, "for-each-ref"),
        "origin": raw(tdd.origin, "for-each-ref"),
        "status": raw(repo, "status", "--porcelain=v2", "--untracked-files=all", "--", ".", ":!.l4-out"),
        "files": files,
        "cache": sorted(str(p) for p in tdd.cache.rglob("*")) if tdd.cache.exists() else None,
    }


def dry_run(tdd, capsys, *flags: str, config: dict | None = None):
    tdd.write_config(**(config or {}))
    code = main(["run", "--dry-run", *flags, "--repo", str(tdd.repo)], environ=tdd.environ)
    out = capsys.readouterr()
    return code, out.out, out.err


def test_dry_run_leaves_refs_tree_forge_and_cache_unchanged(tdd_repo, raw, capsys, monkeypatch):
    agent = Scripted()
    monkeypatch.setitem(factory.ADAPTERS, "fake", lambda: agent)
    monkeypatch.setattr(archive, "make_forge", lambda *a, **k: pytest.fail("a dry run touches no forge"))
    spawned: list[str] = []
    real = subprocess.Popen

    class Spy(real):  # type: ignore[valid-type, misc]
        def __init__(self, args, *a, **k):
            spawned.append(Path(args[0]).name)
            super().__init__(args, *a, **k)

    tdd_repo.write_config()
    raw(tdd_repo.repo, "add", "-A")
    raw(tdd_repo.repo, "commit", "-q", "-m", "config")
    before = state_of(tdd_repo, raw)
    monkeypatch.setattr(subprocess, "Popen", Spy)
    code, out, err = dry_run(tdd_repo, capsys)
    monkeypatch.setattr(subprocess, "Popen", real)
    assert code == 0, err
    assert state_of(tdd_repo, raw) == before
    assert set(spawned) == {"git"} and agent.steps == [] and agent.runs == 0  # git reads only; nothing probed
    run_id = next((tdd_repo.repo / ".l4-out" / "dry-run").iterdir()).name
    prompt = tdd_repo.repo / ".l4-out" / "dry-run" / run_id / "openspec-add-discount-codes" / "1.1-red.prompt.md"
    assert "# Task 1.1" in prompt.read_text() and "# Phase" in prompt.read_text()


def test_the_output_names_the_command_the_gates_and_the_env_names_but_no_value(tdd_repo, capsys):
    config = {"profiles": {"impl": {"adapter": "claude-code", "vendor": "anthropic"}}}
    code, out, _ = dry_run(tdd_repo, capsys, config=config)
    assert code == 0
    assert "command: claude -p --output-format stream-json" in out and "--setting-sources" in out
    assert "env:" in out and "PATH" in out and "L4_RESULT_PATH" in out and "(names only)" in out
    assert str(tdd_repo.environ["HOME"]) not in out.split("env:")[1].splitlines()[0]
    assert "gate setup:" in out and "gate test: .venv/bin/python -m pytest" in out
    lines = out.strip().splitlines()
    assert lines[-1] == "would exit 0"
    assert any(line.startswith("UNIT") and "ACTION" in line for line in lines)  # the decision table
    assert any("openspec:add-discount-codes" in line and "implement" in line and "1.1" in line for line in lines)


def test_no_probe_unless_asked_and_uncached_profiles_are_unknown(tdd_repo, capsys, monkeypatch):
    agent = Scripted()
    monkeypatch.setitem(factory.ADAPTERS, "fake", lambda: agent)
    code, out, _ = dry_run(tdd_repo, capsys)
    assert code == 0 and agent.steps == []
    rows = [line for line in out.splitlines() if line.startswith("openspec:add-discount-codes") and "implement" in line]
    assert rows and "unknown" in rows[-1]


def test_probe_without_dry_run_is_a_usage_error_that_starts_nothing(tdd_repo, capsys, monkeypatch):
    agent = Scripted()
    monkeypatch.setitem(factory.ADAPTERS, "fake", lambda: agent)
    tdd_repo.write_config()
    assert main(["run", "--probe", "--repo", str(tdd_repo.repo)], environ=tdd_repo.environ) == 2
    assert "--probe needs --dry-run" in capsys.readouterr().err
    assert agent.steps == [] and agent.runs == 0


def test_dry_run_probe_asks_the_agents(tdd_repo, capsys, monkeypatch):
    agent = Scripted()
    monkeypatch.setitem(factory.ADAPTERS, "fake", lambda: agent)
    code, out, _ = dry_run(tdd_repo, capsys, "--probe")
    assert code == 0 and agent.steps == ["binary", "auth", "quota", "hello"] and agent.runs == 0  # M1.2 ladder
    assert "usable" in out and out.strip().splitlines()[-1] == "would exit 0"


def test_the_ci_mirror_counts_the_units_the_dry_run_listed(tdd_repo, capsys):
    code, out, _ = dry_run(tdd_repo, capsys)
    assert code == 0 and "add-discount-codes" in out
    env = (tdd_repo.repo / ".l4-out" / "l4.env").read_text().splitlines()
    assert "L4_UNITS_ACTIONABLE=1" in env


def test_an_unavailable_head_is_a_would_exit_12_and_still_exit_0(tdd_repo, capsys, monkeypatch):
    agent = Scripted(fail="auth")
    monkeypatch.setitem(factory.ADAPTERS, "fake", lambda: agent)
    code, out, _ = dry_run(tdd_repo, capsys, "--probe")
    assert code == 0
    assert out.strip().splitlines()[-1] == "would exit 12" and "unavailable" in out


def test_an_unknown_unit_is_the_usage_error_of_a_real_run(tdd_repo, capsys):
    code, _, err = dry_run(tdd_repo, capsys, "--unit", "openspec:nope")
    assert code == 2 and "no such unit" in err


def test_nothing_actionable_would_exit_0(tdd_repo, raw, capsys):
    raw(tdd_repo.repo, "rm", "-rq", "openspec/changes/add-discount-codes")
    (tdd_repo.repo / "openspec" / "changes").mkdir(parents=True)  # the framework stays, the units go
    (tdd_repo.repo / "openspec" / "changes" / ".gitkeep").write_text("")
    code, out, _ = dry_run(tdd_repo, capsys)
    assert code == 0 and out.strip().splitlines()[-1] == "would exit 0" and "add-discount-codes" not in out


def moved_branch(tdd, raw, *, main_files: dict[str, str]) -> str:
    """The unit's branch on `origin` has one commit of its own (it edits `pricing.py`); then `main` moves on."""
    from ..orchestrator.conftest import BRANCH

    repo = tdd.repo
    raw(repo, "checkout", "-q", "-b", BRANCH)
    with (repo / "src/pytdd/pricing.py").open("a") as handle:
        handle.write("\n# unit edit\n")
    raw(repo, "commit", "-q", "-am", "unit work")
    raw(repo, "push", "-q", "origin", BRANCH)
    raw(repo, "checkout", "-q", "main")
    raw(repo, "branch", "-q", "-D", BRANCH)
    for name, text in main_files.items():
        (repo / name).write_text(text)
    raw(repo, "add", "-A")
    raw(repo, "commit", "-q", "-m", "main moved")
    raw(repo, "push", "-q", "origin", "main")
    raw(repo, "fetch", "-q", "origin", "+refs/heads/*:refs/remotes/origin/*")
    return raw(repo, "rev-parse", "origin/main").strip()


def test_base_moved_line_names_overlap(tdd_repo, raw, capsys):
    pricing = (tdd_repo.repo / "src/pytdd/pricing.py").read_text()
    head = moved_branch(tdd_repo, raw, main_files={"src/pytdd/pricing.py": "# main\n" + pricing, "NEWS.md": "n\n"})
    code, out, err = dry_run(tdd_repo, capsys, "--unit", "openspec:add-discount-codes")
    assert code == 0, err
    assert (
        f"  base moved: step 0 merges main@{head[:12]} (1 commit behind; changed on both sides: src/pytdd/pricing.py)"
        in out.splitlines()
    )
    # a second commit on main, in a file the unit never touched: still one overlap, now two commits behind
    (tdd_repo.repo / "NEWS.md").write_text("n2\n")
    raw(tdd_repo.repo, "commit", "-q", "-am", "more news")
    raw(tdd_repo.repo, "push", "-q", "origin", "main")
    raw(tdd_repo.repo, "fetch", "-q", "origin", "+refs/heads/*:refs/remotes/origin/*")
    _, out, _ = dry_run(tdd_repo, capsys, "--unit", "openspec:add-discount-codes")
    assert "(2 commits behind; changed on both sides: src/pytdd/pricing.py)" in out


def test_base_moved_line_says_none_without_overlap_and_is_absent_when_contained(tdd_repo, raw, capsys):
    head = moved_branch(tdd_repo, raw, main_files={"NEWS.md": "n\n"})
    _, out, _ = dry_run(tdd_repo, capsys, "--unit", "openspec:add-discount-codes")
    assert f"base moved: step 0 merges main@{head[:12]} (1 commit behind; changed on both sides: none)" in out
    from ..orchestrator.conftest import BRANCH

    raw(tdd_repo.repo, "checkout", "-q", "-b", "scratch", f"origin/{BRANCH}")
    raw(tdd_repo.repo, "merge", "-q", "--no-ff", "-m", "merge main", "origin/main")
    raw(tdd_repo.repo, "push", "-q", "origin", f"scratch:refs/heads/{BRANCH}")
    raw(tdd_repo.repo, "checkout", "-q", "main")
    raw(tdd_repo.repo, "fetch", "-q", "origin", "+refs/heads/*:refs/remotes/origin/*")
    _, out, _ = dry_run(tdd_repo, capsys, "--unit", "openspec:add-discount-codes")
    assert "base moved" not in out


def test_dry_run_shows_a_unit_held_by_yolo_hold(tdd_repo, capsys):
    """SCN-ADO-33: the dry run starts nothing for a unit `yolo.hold` names; named, it would exit 13."""
    tdd_repo.write_config()
    config = tdd_repo.repo / ".l4" / "config.yaml"
    config.write_text(config.read_text() + "yolo:\n  hold: ['openspec:add-discount-codes']\n")
    code = main(["run", "--dry-run", "--repo", str(tdd_repo.repo)], environ=tdd_repo.environ)
    out = capsys.readouterr().out
    assert code == 0 and "add-discount-codes" not in out and out.strip().splitlines()[-1] == "would exit 0"
    code = main(["run", "--dry-run", "--unit", "openspec:add-discount-codes", "--repo", str(tdd_repo.repo)],
                environ=tdd_repo.environ)  # fmt: skip
    out = capsys.readouterr().out
    assert code == 0 and "held: held by yolo.hold" in out and "would exit 13" in out
