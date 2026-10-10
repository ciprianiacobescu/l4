"""SPEC L4-FAC-008 (login lock): one process at a time drives a refreshable OAuth login, whatever its $L4_CACHE,
profile name or entry point (incident 2026-10-07: two processes refreshed one single-use refresh token)."""

import contextlib
import os
import stat
import subprocess
import sys
import textwrap
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from l4.agents.base import ProbeCtx, RunRequest
from l4.agents.fake import FakeAdapter, Step
from l4.agents.gate import (
    ConcurrencyGate,
    GateBusy,
    GatedAdapter,
    GateNested,
    held_keys,
    lock_root,
    login_key,
    refreshable_login,
    slots_for,
)
from l4.config.schema import Profile

CLAUDE = Profile(adapter="claude-code", model="haiku", auth="subscription", vendor="anthropic")


def environ(home: Path, **extra: str) -> dict[str, str]:
    return {"HOME": str(home), "PATH": "/usr/bin", **extra}


def request(tmp_path: Path) -> RunRequest:
    return RunRequest(
        profile=Profile(adapter="fake"), role="implementer", cwd=tmp_path, prompt="p",
        result_path=tmp_path / "r.json", raw_events_path=tmp_path / "raw.jsonl", env={},
    )  # fmt: skip


# ---- the per-login limit is exactly 1 for a refreshable OAuth store ------------------------------------------------


@pytest.mark.parametrize("adapter", ["claude-code", "codex", "kiro-cli"])
def test_a_refreshable_login_has_exactly_one_slot_whatever_max_concurrency_says(adapter):
    for auth in ("subscription", None):
        assert slots_for(Profile(adapter=adapter, auth=auth, max_concurrency=4)) == 1  # type: ignore[arg-type]
    assert slots_for(Profile(adapter=adapter, auth="api_key", max_concurrency=4)) == 4  # type: ignore[arg-type]
    assert slots_for(Profile(adapter=adapter, auth="api_key")) is None  # type: ignore[arg-type]
    assert slots_for(Profile(adapter=adapter, api_key_env="SOME_KEY", max_concurrency=2)) == 2  # type: ignore[arg-type]


def test_opencode_is_refreshable_only_when_it_declares_a_subscription():
    assert slots_for(Profile(adapter="opencode", auth="subscription", max_concurrency=3)) == 1
    assert slots_for(Profile(adapter="opencode", auth="api_key", max_concurrency=3)) == 3
    assert slots_for(Profile(adapter="opencode")) is None
    assert refreshable_login(Profile(adapter="opencode", auth="subscription"))
    assert not refreshable_login(Profile(adapter="fake", auth="subscription"))


# ---- the lock key is the resolved credential home, never the profile name or the cache -----------------------------


def test_the_key_is_the_resolved_credential_home(tmp_path):
    home = tmp_path / "h"
    (home / ".claude").mkdir(parents=True)
    other = CLAUDE.model_copy(update={"model": "opus", "base_url": "https://x.example"})
    assert login_key(CLAUDE, environ(home)) == login_key(other, environ(home, L4_CACHE="/somewhere/else"))
    # a second path to the same directory is the same login
    alias = tmp_path / "alias"
    alias.symlink_to(home)
    assert login_key(CLAUDE, environ(alias)) == login_key(CLAUDE, environ(home))
    # another HOME is another login
    assert login_key(CLAUDE, environ(tmp_path / "other-home")) != login_key(CLAUDE, environ(home))


@pytest.mark.parametrize(
    ("profile", "override"),
    [(CLAUDE, "CLAUDE_CONFIG_DIR"), (Profile(adapter="codex", model="gpt-5", auth="subscription"), "CODEX_HOME")],
)
def test_the_key_is_the_store_the_spawned_cli_uses_so_an_override_in_the_host_env_does_not_split_it(
    tmp_path, profile, override
):
    """The harness builds every CLI environment from HOME (`probe_env`, `build_agent_env`) and never passes
    CLAUDE_CONFIG_DIR or CODEX_HOME on: the CLI it spawns uses `$HOME/.claude` / `$HOME/.codex` whatever the host
    environment says. A key that followed the override would let a process with it set and one without drive the same
    store under two different locks."""
    from l4.availability.probes import probe_env
    from l4.sandbox.base import SandboxSpec
    from l4.sandbox.env import build_agent_env

    home = tmp_path / "h"
    host = environ(home, **{override: str(tmp_path / "elsewhere")})
    assert login_key(profile, host) == login_key(profile, environ(home))
    # the reason: neither spawn environment carries the override
    ctx_env = probe_env(ProbeCtx(host, tmp_path, lambda *a: None))
    spec = SandboxSpec("agent", tmp_path, tmp_path / ".git", tmp_path / "t", home, adapter=profile.adapter)
    assert override not in ctx_env and override not in build_agent_env(host, spec)


def test_a_non_refreshable_profile_keeps_the_identity_hash():
    from l4.availability.cooldown import identity_hash

    fake = Profile(adapter="fake", auth="subscription", base_url="https://a.example")
    assert login_key(fake, {"HOME": "/h"}) == identity_hash(fake, {"HOME": "/h"})


# ---- where the locks live ------------------------------------------------------------------------------------------


def test_the_lock_dir_ignores_l4_cache_and_xdg(monkeypatch, tmp_path):
    monkeypatch.delenv("L4_LOCK_DIR")
    import pwd

    expected = Path(pwd.getpwuid(os.getuid()).pw_dir) / ".cache" / "l4" / "locks"
    assert lock_root(environ(tmp_path, L4_CACHE="/x", XDG_CACHE_HOME="/y", XDG_RUNTIME_DIR="/z")) == expected
    assert lock_root(environ(tmp_path / "another-home")) == expected  # an OS user, not a HOME
    assert lock_root(environ(tmp_path, L4_LOCK_DIR=str(tmp_path / "mine"))) == tmp_path / "mine"


def test_the_lock_dir_is_private_and_a_foreign_open_dir_is_tightened(tmp_path):
    locks = tmp_path / "state" / "locks"
    gate = ConcurrencyGate.for_user(environ(tmp_path, L4_LOCK_DIR=str(locks)))
    slot = gate.try_acquire("claude-code", "abc", 1)
    assert slot is not None
    assert stat.S_IMODE(locks.stat().st_mode) == 0o700
    (lock_file,) = locks.iterdir()
    assert stat.S_IMODE(lock_file.stat().st_mode) == 0o600
    slot.release()
    locks.chmod(0o777)
    lock_file.chmod(0o666)
    assert gate.try_acquire("claude-code", "abc", 1) is not None
    assert stat.S_IMODE(locks.stat().st_mode) == 0o700 and stat.S_IMODE(lock_file.stat().st_mode) == 0o600


def test_a_symlinked_lock_file_is_refused(tmp_path):
    locks = tmp_path / "locks"
    gate = ConcurrencyGate.for_user(environ(tmp_path, L4_LOCK_DIR=str(locks)))
    gate.try_acquire("claude-code", "abc", 1).release()  # type: ignore[union-attr]
    (lock_file,) = locks.iterdir()
    lock_file.unlink()
    lock_file.symlink_to(tmp_path / "victim")
    with pytest.raises(OSError):
        gate.try_acquire("claude-code", "abc", 1)
    assert not (tmp_path / "victim").exists()


# ---- two processes, two caches, one login --------------------------------------------------------------------------

CHILD = textwrap.dedent(
    """
    import sys, time
    from pathlib import Path
    from l4.agents.base import ProbeCtx, ProbeResult, RunRequest
    from l4.agents.factory import Factory
    from l4.agents.fake import FakeAdapter, Step
    from l4.availability.cooldown import AvailabilityStore
    from l4.config.schema import L4Config, Profile, RolesCfg

    home, cache, log, tag = sys.argv[1:5]

    class Sleeper(FakeAdapter):
        def probe(self, profile, step, ctx):
            with open(log, "a") as out:
                out.write(f"{tag} probe-start {time.time()}\\n")
            time.sleep(0.4)
            with open(log, "a") as out:
                out.write(f"{tag} probe-end {time.time()}\\n")
            return ProbeResult(step, True)

        def run(self, req):
            with open(log, "a") as out:
                out.write(f"{tag} run-start {time.time()}\\n")
            time.sleep(0.8)
            with open(log, "a") as out:
                out.write(f"{tag} run-end {time.time()}\\n")
            return super().run(req)

    profile = Profile(adapter="claude-code", model=tag, auth="subscription", vendor="anthropic")
    cfg = L4Config(profiles={"p": profile}, roles=RolesCfg(implementer=["p"]))
    ctx = ProbeCtx(environ={"HOME": home, "PATH": "/usr/bin"}, cwd=Path(home), run=lambda *a: None)
    factory = Factory(
        cfg, ctx, adapters={"claude-code": Sleeper([Step(status="ok")])}, availability=AvailabilityStore(Path(cache))
    )
    picked = factory.for_role("implementer", "u")
    req = RunRequest(
        profile=profile, role="implementer", cwd=Path(home), prompt="p", result_path=Path(home) / f"{tag}.json",
        raw_events_path=Path(home) / f"{tag}.jsonl", env={},
    )
    picked.impl.run(req)
    """
)


def test_two_processes_with_different_caches_never_overlap(tmp_path):
    home, log = tmp_path / "home", tmp_path / "events.log"
    home.mkdir()
    env = {**os.environ, "L4_LOCK_DIR": os.environ["L4_LOCK_DIR"]}
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", CHILD, str(home), str(tmp_path / f"cache-{tag}"), str(log), tag], env=env
        )
        for tag in ("a", "b")
    ]
    for proc in procs:
        assert proc.wait(timeout=300) == 0
    rows = [line.split() for line in log.read_text().splitlines()]
    spans: list[tuple[float, float, str]] = []
    for tag in ("a", "b"):
        for kind in ("probe", "run"):
            starts = [float(r[2]) for r in rows if r[0] == tag and r[1] == f"{kind}-start"]
            ends = [float(r[2]) for r in rows if r[0] == tag and r[1] == f"{kind}-end"]
            assert starts and len(starts) == len(ends)
            spans.append((min(starts), max(ends), f"{tag}-{kind}"))
    spans.sort()
    for earlier, later in zip(spans, spans[1:], strict=False):
        assert earlier[1] <= later[0], f"{earlier[2]} overlaps {later[2]}"


FAKE_CLAUDE = """#!{python}
import json, os, sys, time
log = {log!r}
def note(what):
    with open(log, "a") as out:
        out.write(f"{{os.getppid()}} {{what}} {{time.time()}}\\n")
note("start")
if sys.argv[1:] == ["--version"]:
    time.sleep(0.2)
    print("2.1.0 (Claude Code)")
else:
    time.sleep(1.0)  # `auth status` is where a real CLI refreshes an expired token
    print(json.dumps({{"loggedIn": True, "authMethod": "claude.ai", "subscriptionType": "max"}}))
note("end")
"""


def test_two_real_l4_probe_processes_with_different_caches_and_envs_serialize_on_one_fake_cli(tmp_path):
    """The runner incident end to end: a CI job (`l4 probe`, one $L4_CACHE) and an out-of-CI run (another $L4_CACHE,
    other XDG dirs and TMPDIR, a CLAUDE_CONFIG_DIR the harness does not pass on) drive one `$HOME/.claude`. Real
    entry point, real `run_process`, a fake `claude` on PATH: no two CLI invocations of the two processes overlap."""
    home, bin_dir, log = tmp_path / "home", tmp_path / "bin", tmp_path / "cli.log"
    (home / ".claude").mkdir(parents=True)
    bin_dir.mkdir()
    fake = bin_dir / "claude"
    fake.write_text(FAKE_CLAUDE.format(python=sys.executable, log=str(log)), encoding="utf-8")
    fake.chmod(0o755)
    config = tmp_path / "config.yaml"
    config.write_text(
        "version: 1\n"
        "profiles:\n  c: {adapter: claude-code, model: haiku, vendor: anthropic, auth: subscription}\n"
        "roles:\n  implementer: [c]\n  judges: [c]\n"
        "availability: {default_ladder: [binary, auth]}\n",
        encoding="utf-8",
    )
    base = {
        "HOME": str(home), "PATH": f"{bin_dir}:/usr/bin:/bin", "L4_LOCK_DIR": os.environ["L4_LOCK_DIR"],
        "PYTHONPATH": os.pathsep.join(sys.path),
    }  # fmt: skip
    procs = []
    for tag, extra in (("ci", {}), ("eval", {"CLAUDE_CONFIG_DIR": str(tmp_path / "not-used")})):
        (tmp_path / tag).mkdir()
        env = {
            **base, "L4_CACHE": str(tmp_path / tag / "cache"), "XDG_CACHE_HOME": str(tmp_path / tag / "xdg"),
            "XDG_RUNTIME_DIR": str(tmp_path / tag / "run"), "TMPDIR": str(tmp_path / tag), **extra,
        }  # fmt: skip
        repo = tmp_path / tag / "repo"
        repo.mkdir()
        argv = [sys.executable, "-m", "l4", "probe", "--no-cache", "--config", str(config), "--repo", str(repo)]
        procs.append(subprocess.Popen(argv, env=env, cwd=tmp_path / tag, stdout=subprocess.PIPE, text=True))
    outs = [proc.communicate(timeout=300)[0] for proc in procs]
    assert [proc.returncode for proc in procs] == [0, 0], outs
    rows = [line.split() for line in log.read_text().splitlines()]
    callers = sorted({r[0] for r in rows})
    # two processes; each step resolves the binary first: `--version` (binary), `--version` + `auth status` (auth)
    assert len(callers) == 2 and len(rows) == 2 * 2 * 3
    spans = []
    for caller in callers:
        mine = [(r[1], float(r[2])) for r in rows if r[0] == caller]
        spans.append((min(t for k, t in mine if k == "start"), max(t for k, t in mine if k == "end"), caller))
    spans.sort()
    assert spans[0][1] <= spans[1][0], f"the two processes drove the CLI at once: {spans}"


def test_a_crashed_holder_frees_the_login_at_once_and_its_detached_child_does_not_keep_it(tmp_path):
    """A flock dies with its process: SIGKILL of the holder (a cancelled CI job) frees the login, and a child it had
    started in its own session (what every spawn helper does) holds no copy of the lock descriptor."""
    ready = tmp_path / "ready"
    holder = textwrap.dedent(
        f"""
        import subprocess, sys, time
        from pathlib import Path
        from l4.agents.gate import ConcurrencyGate
        slot = ConcurrencyGate({str(tmp_path)!r}).acquire("claude-code", "id", 1)
        child = subprocess.Popen(["sleep", "60"], start_new_session=True, close_fds=True, stdin=subprocess.DEVNULL)
        Path({str(ready)!r}).write_text(str(child.pid))
        time.sleep(60)
        """
    )
    proc = subprocess.Popen([sys.executable, "-c", holder])
    try:
        deadline = time.monotonic() + 120  # a loaded machine can take long to start the holder
        while not (ready.exists() and ready.read_text()) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert ready.exists() and ready.read_text(), "the holder never took the lock"
        gate = ConcurrencyGate(tmp_path)
        assert gate.is_busy("claude-code", "id", 1)
        proc.kill()
        proc.wait(timeout=10)
        orphan = int(ready.read_text())
        os.kill(orphan, 0)  # still running, in its own session
        assert not gate.is_busy("claude-code", "id", 1)
    finally:
        proc.kill()
        if ready.exists() and ready.read_text():
            with contextlib.suppress(ProcessLookupError):
                os.kill(int(ready.read_text()), 9)


# ---- bounded wait, fallback, trace ---------------------------------------------------------------------------------


def test_a_busy_login_is_a_rate_limited_result_that_falls_back(tmp_path):
    g = ConcurrencyGate(tmp_path, sleep=lambda s: None, monotonic=iter([0.0, 0.0, 999.0, 999.0]).__next__)
    holder = g.try_acquire("claude-code", "id", 1)
    now = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)
    gated = GatedAdapter(
        FakeAdapter([Step(status="ok")]), g, "claude-code", "id", 1, wait_s=5, now=lambda: now,
    )  # fmt: skip
    out = gated.run(request(tmp_path))
    assert out.status == "rate_limited"
    assert out.detail == "unavailable: another process holds the claude-code login"
    assert out.limit is not None and out.limit.source == "gate.busy" and out.limit.kind == "rate_limit"
    assert out.limit.resets_at is not None and out.limit.resets_at > now
    holder.release()


def test_the_wait_is_traced_and_ledgered(tmp_path):
    clock = {"t": 0.0}
    holder = ConcurrencyGate(tmp_path).try_acquire("claude-code", "id", 1)

    def sleep(seconds):
        clock["t"] += seconds
        if clock["t"] >= 6:
            holder.release()

    seen: list[dict] = []
    g = ConcurrencyGate(tmp_path, sleep=sleep, monotonic=lambda: clock["t"])
    g.observe = seen.append
    slot = g.acquire("claude-code", "id", 1, wait_s=60, poll_s=2)
    assert seen == [{"tool": "claude-code", "slots": 1, "waited_s": 6.0, "outcome": "acquired"}]
    slot.release()
    seen.clear()
    g.acquire("claude-code", "id", 1, wait_s=60, poll_s=2).release()  # a free login is not worth a line
    assert seen == []
    blocker = g.try_acquire("claude-code", "id", 1)
    with pytest.raises(GateBusy):
        g.acquire("claude-code", "id", 1, wait_s=4, poll_s=2)
    assert seen and seen[-1]["outcome"] == "timeout"
    blocker.release()


# ---- one CLI at a time per process ---------------------------------------------------------------------------------


def test_a_second_blocking_acquire_in_one_thread_is_a_bug_not_a_deadlock(tmp_path):
    g = ConcurrencyGate(tmp_path)
    with g.acquire("claude-code", "a", 1):
        assert held_keys() == ["claude-code/a"]
        with pytest.raises(GateNested):
            g.acquire("codex", "b", 1)
        with pytest.raises(GateNested):
            g.acquire("claude-code", "a", 1)
    assert held_keys() == []


# ---- a child cannot keep the lock after the parent lets go ---------------------------------------------------------


def test_every_spawn_helper_closes_inherited_descriptors(tmp_path, monkeypatch):
    import l4.agents.proc as agents_proc
    import l4.availability.rpc as rpc
    import l4.proc as proc

    seen: list[dict] = []

    class Stop(Exception):
        pass

    def fake_popen(*args, **kwargs):
        seen.append(kwargs)
        raise Stop

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    with pytest.raises(Stop):
        agents_proc.ProcRunner().run(["x"], {}, tmp_path, stdout_path=tmp_path / "o", timeout_s=1)
    with pytest.raises(Stop):
        proc.run_process(["x"], tmp_path, {}, 1)
    with pytest.raises(Stop):
        rpc.run_rpc_session(["x"], tmp_path, {}, 1, [])
    assert len(seen) == 3 and all(kw.get("close_fds") is True for kw in seen)


def test_a_detached_grandchild_does_not_keep_the_slot(tmp_path):
    g = ConcurrencyGate(tmp_path)
    slot = g.acquire("claude-code", "id", 1)
    child = subprocess.Popen(
        ["sleep", "30"], start_new_session=True, close_fds=True, stdin=subprocess.DEVNULL
    )  # what ProcRunner does
    try:
        slot.release()
        assert not g.is_busy("claude-code", "id", 1)
    finally:
        child.kill()
        child.wait()


# ---- through the factory: fallback and ledger ----------------------------------------------------------------------


def _factory(tmp_path, gate, sink=None):
    from l4.agents.base import ProbeCtx
    from l4.agents.factory import Factory
    from l4.availability.cooldown import AvailabilityStore, FakeClock
    from l4.config.schema import L4Config, RolesCfg

    codex = Profile(adapter="codex", model="gpt-5", auth="subscription", vendor="openai")
    cfg = L4Config(
        profiles={"claude": CLAUDE, "codex": codex},
        roles=RolesCfg(implementer=["claude", "codex"]),
        availability={"login_lock_wait": "5s"},
    )
    clock = FakeClock(datetime(2026, 10, 8, 12, 0, tzinfo=UTC))
    ctx = ProbeCtx(environ={"HOME": str(tmp_path), "PATH": "/usr/bin"}, cwd=tmp_path, run=lambda *a: None)
    adapters = {"claude-code": FakeAdapter([Step(status="ok")]), "codex": FakeAdapter([Step(status="ok")])}
    return Factory(
        cfg, ctx, adapters=adapters, availability=AvailabilityStore(tmp_path / "cache", clock=clock), clock=clock,
        gate=gate, events=sink,
    )  # fmt: skip


class Sink:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []
        self.run_id = "r-1"

    def append(self, event_type, /, **data):
        self.events.append((event_type, data))


def test_a_login_taken_after_selection_falls_back_to_the_next_profile(tmp_path):
    gate = ConcurrencyGate.for_user({}, sleep=lambda s: None, monotonic=iter([0.0, 0.0, 99.0, 99.0, 99.0]).__next__)
    sink = Sink()
    factory = _factory(tmp_path, gate, sink)
    picked = factory.for_role("implementer", "u")
    assert picked.profile_name == "claude"
    other_process = gate.try_acquire("claude-code", login_key(CLAUDE, factory._ctx.environ), 1)
    assert other_process is not None
    result = picked.impl.run(request(tmp_path))
    assert result.status == "rate_limited" and result.limit is not None
    chosen = factory.on_limit(picked, result)
    assert chosen.profile_name == "codex"  # the busy login is passed over, not retried
    assert [n for n, _ in sink.events if n == "availability.fallback"]
    other_process.release()


def test_a_wait_for_the_login_is_a_ledger_event_and_a_console_line(tmp_path, caplog):
    clock = {"t": 0.0}
    holder: list = []

    def sleep(seconds):
        clock["t"] += seconds
        if clock["t"] >= 4:
            holder[0].release()

    gate = ConcurrencyGate.for_user({}, sleep=sleep, monotonic=lambda: clock["t"])
    sink = Sink()
    factory = _factory(tmp_path, gate, sink)
    picked = factory.for_role("implementer", "u")
    holder.append(gate.try_acquire("claude-code", login_key(CLAUDE, factory._ctx.environ), 1))
    with caplog.at_level("INFO", logger="l4.login"):
        assert picked.impl.run(request(tmp_path)).status == "ok"
    (fact,) = [d for n, d in sink.events if n == "availability.login_wait"]
    assert fact["tool"] == "claude-code" and fact["outcome"] == "acquired" and fact["waited_s"] == 4.0
    assert any("waited 4s" in r.getMessage() and "claude-code login" in r.getMessage() for r in caplog.records)


def test_an_unusable_lock_directory_makes_the_profile_unavailable_not_a_crash(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("not a directory")
    gate = ConcurrencyGate(locks_dir=blocker / "locks", sleep=lambda s: None)
    factory = _factory(tmp_path, gate)
    from l4.availability.errors import RoleUnavailable

    with pytest.raises(RoleUnavailable):
        factory.for_role("implementer", "u")  # both profiles share the broken lock directory
