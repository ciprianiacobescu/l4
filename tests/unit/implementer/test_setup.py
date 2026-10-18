import pytest

from l4.implementer.tdd import SetupFailed, run_red, run_setup
from l4.specs.base import Task

from .conftest import red_step, result

TASK = Task("1.1", "1.1", "1.1 Add `apply_discount`", False, " ", 0, 1, 3)


def test_setup_runs_before_each_agent_step(make_bench):
    bench = make_bench([red_step()])
    order: list[str] = []
    real_gate, real_run = bench.wb.run_gate, bench.adapter.run
    bench.wb.run_gate = lambda name, *a, **k: (order.append(name), real_gate(name, *a, **k))[1]  # type: ignore[method-assign]
    bench.adapter.run = lambda req: (order.append("agent"), real_run(req))[1]  # type: ignore[method-assign]
    outcome = run_red(bench.wb, TASK, attempt=1)
    assert outcome.status == "ok", outcome.reason
    # one setup for the baseline, which is also the step's HEAD; one after the agent, so its environment edits go
    # then the zero-value run of run (b)
    assert order == ["setup", "baseline", "agent", "setup", "test", "test-zero"]


def test_green_installs_again_between_the_agent_and_the_test_gate(make_bench):
    from l4.implementer.tdd import run_green

    from .conftest import green_step

    bench = make_bench([red_step(), green_step()])
    red = run_red(bench.wb, TASK, attempt=1)
    order: list[str] = []
    real_gate, real_run = bench.wb.run_gate, bench.adapter.run
    bench.wb.run_gate = lambda name, *a, **k: (order.append(name), real_gate(name, *a, **k))[1]  # type: ignore[method-assign]
    bench.adapter.run = lambda req: (order.append("agent"), real_run(req))[1]  # type: ignore[method-assign]
    assert run_green(bench.wb, TASK, red, attempt=1).status == "ok"
    assert order[:4] == ["setup", "agent", "setup", "test"]


def test_setup_runs_again_after_an_agent_step_at_the_same_head(make_bench):
    from l4.agents.fake import Step

    bench = make_bench([Step(structured=result("red")), red_step()])
    first = run_red(bench.wb, TASK, attempt=1)
    assert first.status == "failed"  # the agent added no test: same HEAD, but it may have touched the environment
    order: list[str] = []
    real_gate = bench.wb.run_gate
    bench.wb.run_gate = lambda name, *a, **k: (order.append(name), real_gate(name, *a, **k))[1]  # type: ignore[method-assign]
    run_red(bench.wb, TASK, attempt=2, previous_failure=first.reason)
    assert order[0] == "setup"


def test_setup_gets_the_network_and_the_unit_cache(make_bench):
    bench = make_bench([])
    seen = []
    real = type(bench.wb).gate_spec

    def spy(*, network, tree=None, record_dir=None):
        seen.append(network)
        return real(bench.wb, network=network, tree=tree, record_dir=record_dir)

    bench.wb.gate_spec = spy  # type: ignore[method-assign]
    run_setup(bench.wb)
    assert seen == [True]
    assert any(c.env == "UV_CACHE_DIR" and c.path.is_dir() for c in bench.wb.caches)
    assert (bench.wb.worktree / ".venv" / "bin" / "python").exists()  # the stand-in for `uv sync` ran in the worktree


def test_a_failing_setup_stops_before_any_agent_runs(make_bench):
    bench = make_bench([red_step()], setup=["false"])
    with pytest.raises(SetupFailed, match="gates.setup failed"):
        run_red(bench.wb, TASK, attempt=1)
    assert bench.adapter.requests == []


# -- m1.x F4 (live M1.6 job 5535): COV-001 was `skip` in CI because the doctor runs before gates.setup creates .venv


def _coverage_mode(bench, mode: str) -> None:
    bench.wb.cfg.verifier.evidence.diff_coverage.mode = mode


def _cov_events(bench) -> list[dict]:
    return [e for e in bench.events("doctor.check") if e["id"] == "COV-001"]


def test_coverage_is_checked_once_right_after_the_first_setup(make_bench):
    bench = make_bench([])
    _coverage_mode(bench, "warn")
    run_setup(bench.wb)
    [event] = _cov_events(bench)
    assert event["status"] == "pass" and event["when"] == "after gates.setup" and ".venv/bin/python" in event["message"]
    bench.wb.setup_at = None
    run_setup(bench.wb)  # the next step installs again: the answer stands, nothing more is said
    assert len(_cov_events(bench)) == 1
    assert any(e["name"] == "coverage-check" for e in bench.events("gate.finished"))


def test_no_coverage_check_when_diff_coverage_is_off(make_bench):
    bench = make_bench([])  # the fixtures run with `diff_coverage.mode: off`
    run_setup(bench.wb)
    assert _cov_events(bench) == []
    assert not any(e["name"] == "coverage-check" for e in bench.events("gate.finished"))


def test_a_project_environment_without_coverage_is_a_warning_event_not_a_failure(make_bench, caplog):
    from l4.gates.runner import GateResult

    bench = make_bench([])
    _coverage_mode(bench, "warn")
    real = bench.wb.run_gate

    def gate(name, command, **kw):
        if name != "coverage-check":
            return real(name, command, **kw)
        return GateResult(name, "fail", "exit code 1", 1, bench.wb.out_dir / "none.log")

    bench.wb.run_gate = gate  # type: ignore[method-assign]
    with caplog.at_level("WARNING", logger="l4.implementer"):
        run_setup(bench.wb)  # warns, never raises: the evidence step records `not_run` with its own reason
    [event] = _cov_events(bench)
    assert event["status"] == "fail" and "coverage.py is not importable" in event["message"]
    assert any("coverage.py is not importable" in r.message for r in caplog.records)
    assert bench.wb.setup_at is not None  # setup itself succeeded


def test_no_project_interpreter_after_setup_is_a_skip_event(make_bench):
    bench = make_bench([], test={"command": "pytest -q"})  # nothing names a Python and setup makes no .venv
    bench.wb.cfg.gates.setup[:] = ["true"]
    _coverage_mode(bench, "warn")
    run_setup(bench.wb)
    [event] = _cov_events(bench)
    assert event["status"] == "skip" and "no project interpreter" in event["message"]


def test_no_coverage_check_without_setup_commands(make_bench):
    """The doctor sees a repository's own environment; only a `gates.setup` that creates one needs a second look. (The
    simulation has no setup and may spawn nothing but git and its fixture gate.)"""
    bench = make_bench([], setup=[])
    _coverage_mode(bench, "warn")
    run_setup(bench.wb)
    assert _cov_events(bench) == []


# --- W10: a new unit's uv cache is copied from the project's seed (M1.11, decision 12) -----------------------------

import stat  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

from l4.sandbox.seed import seed_dir  # noqa: E402


@pytest.fixture
def fake_uv(tdd_repo, raw):
    """A `uv` that records where and with which cache it ran, fills the cache like a download, and then does what the
    fixture's setup does (a launcher for `.venv/bin/python`). The base branch gets a `uv.lock`."""
    work = tdd_repo.setup_script.parent
    log, flag = work / "uv-calls.log", work / "fail-seed"
    script = work / "bin" / "uv"
    script.parent.mkdir(exist_ok=True)
    script.write_text(
        "#!/bin/sh\n"
        f'echo "cache=$UV_CACHE_DIR cwd=$(pwd) planted=$([ -e planted.txt ] && echo yes || echo no)'
        f' unit_only=$([ -e unit-only.txt ] && echo yes || echo no) link=$UV_LINK_MODE" >> {log}\n'
        f'case "$UV_CACHE_DIR" in */seed/*) [ -e {flag} ] && exit 1;; esac\n'
        'mkdir -p "$UV_CACHE_DIR/wheels" && echo wheel > "$UV_CACHE_DIR/wheels/pkg-$$.whl"\n'
        f"exec {sys.executable} {tdd_repo.setup_script} {sys.executable}\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    (tdd_repo.repo / "uv.lock").write_text("version = 1\n")
    raw(tdd_repo.repo, "add", "-A")
    raw(tdd_repo.repo, "commit", "-q", "-m", "a lock file")
    raw(tdd_repo.repo, "push", "-q", "origin", "main")
    raw(tdd_repo.repo, "fetch", "-q", "origin")

    class Uv:
        command = f"{script} sync --frozen"

        @staticmethod
        def calls() -> list[dict[str, str]]:
            lines = log.read_text().splitlines() if log.exists() else []
            return [dict(part.split("=", 1) for part in line.split(" ")) for line in lines]

        fail_seed = flag

    return Uv


def uv_cache(bench) -> Path:
    return next(c.path for c in bench.wb.caches if c.env == "UV_CACHE_DIR")


def seed_of(bench, tdd_repo) -> Path:
    url = bench.wb.git.run("config", "--get", "remote.origin.url").stdout.strip()
    return seed_dir(tdd_repo.cache, url)


def test_a_new_unit_cache_is_copied_from_the_seed(make_bench, tdd_repo, fake_uv):
    bench = make_bench([], setup=[fake_uv.command])
    run_setup(bench.wb)
    [filled, own] = fake_uv.calls()
    assert filled["cache"].endswith("/uv") and "/seed/" in filled["cache"] and own["cache"] == str(uv_cache(bench))
    assert filled["cache"] == str(seed_of(bench, tdd_repo))
    filled_event, copied_event = bench.events("cache.seeded")  # the fill, then this unit's copy of it
    assert (filled_event["cache"], filled_event["via"]) == ("uv", "setup") and filled_event["bytes"] > 0
    assert (
        copied_event["via"] == "copy"
        and len(filled_event["digest"]) == 64
        and copied_event["digest"] == filled_event["digest"]
    )
    assert all("key" not in e for e in (filled_event, copied_event))  # a default secret scanner flags `key` + hex
    assert list((uv_cache(bench) / "wheels").iterdir())  # the unit's own setup found wheels in its cache
    # a second unit: its cache is new, so it is a copy of the seed, and the seed is not filled again
    for child in list(uv_cache(bench).iterdir()):
        __import__("shutil").rmtree(child)
    bench.wb.setup_at, bench.wb.seed_checked = None, False
    run_setup(bench.wb)
    assert [c["cache"] for c in fake_uv.calls()] == [filled["cache"], own["cache"], own["cache"]]
    assert [e["via"] for e in bench.events("cache.seeded")] == ["setup", "copy", "copy"]
    assert all(c["link"] == "copy" for c in fake_uv.calls())  # UV_LINK_MODE reaches the setup commands


def test_the_seed_runs_on_the_base_head_not_the_unit_worktree(make_bench, tdd_repo, fake_uv):
    bench = make_bench([], setup=[fake_uv.command])
    (bench.wb.worktree / "unit-only.txt").write_text("committed on the unit branch")
    bench.wb.git.run("add", "-A")
    bench.wb.git.run("commit", "-q", "-m", "unit work")
    (bench.wb.worktree / "planted.txt").write_text("a change the unit's agent left")
    run_setup(bench.wb)
    seed_run, unit_run = fake_uv.calls()[:2]
    assert (seed_run["planted"], seed_run["unit_only"]) == ("no", "no")  # the base branch's tree and nothing else
    assert (unit_run["planted"], unit_run["unit_only"]) == ("yes", "yes")  # the probe sees what is there
    assert seed_run["cwd"] != str(bench.wb.worktree) and Path(seed_run["cwd"]).parent.parent == tdd_repo.cache / "seed"
    assert not Path(seed_run["cwd"]).exists()  # the scratch tree is gone afterwards


def test_the_seed_is_not_mounted_into_agent_or_gate_sandboxes(make_bench, tdd_repo, fake_uv):
    bench = make_bench([], setup=[fake_uv.command])
    run_setup(bench.wb)
    seed = seed_of(bench, tdd_repo)
    specs = [bench.wb.agent_spec(), bench.wb.gate_spec(network=False), bench.wb.gate_spec(network=True)]
    for spec in specs:
        for cache in spec.caches:
            assert seed not in (cache.path, *cache.path.parents) and cache.path != seed
        assert not any(str(seed.parent.parent) in str(p) for p in (spec.worktree, spec.tmp_dir, spec.home))
    assert uv_cache(bench) != seed and seed.exists()


def test_a_failed_seed_falls_back_to_todays_download_with_an_event(make_bench, tdd_repo, fake_uv):
    fake_uv.fail_seed.write_text("1")
    bench = make_bench([], setup=[fake_uv.command])
    run_setup(bench.wb)  # the unit's own setup is not stopped by it
    assert bench.wb.setup_at == bench.wb.head()
    [failed] = bench.events("cache.seed_failed")
    assert failed["cache"] == "uv" and failed["reason"] and bench.events("cache.seeded") == []
    assert list((uv_cache(bench) / "wheels").iterdir())  # the unit downloaded, as it did before the seed
    assert not (seed_of(bench, tdd_repo).parent / "seed.json").exists()  # an unfinished fill is no seed


def test_no_uv_lock_or_a_non_uv_setup_runs_no_seed(make_bench, tdd_repo, fake_uv, raw):
    plain = make_bench([])  # the fixture's own setup is a Python script, not `uv`
    run_setup(plain.wb)
    assert plain.events("cache.seeded") == [] and plain.events("cache.seed_failed") == []
    assert fake_uv.calls() == [] and not (tdd_repo.cache / "seed").exists()
    raw(tdd_repo.repo, "rm", "-q", "uv.lock")
    raw(tdd_repo.repo, "commit", "-q", "-m", "no lock")
    raw(tdd_repo.repo, "push", "-q", "origin", "main")
    raw(tdd_repo.repo, "fetch", "-q", "origin")
    bench = make_bench([], setup=[fake_uv.command])
    run_setup(bench.wb)
    assert [c["cache"] for c in fake_uv.calls()] == [str(uv_cache(bench))] and not (tdd_repo.cache / "seed").exists()


def test_seeded_digest_reads_the_new_field_and_the_key_of_older_ledgers():
    from l4.implementer.uvseed import seeded_digest

    assert seeded_digest({"type": "cache.seeded", "cache": "uv", "digest": "ab" * 32}) == "ab" * 32
    assert seeded_digest({"type": "cache.seeded", "cache": "uv", "key": "cd" * 32}) == "cd" * 32
    assert seeded_digest({"type": "cache.seeded", "cache": "uv"}) is None
