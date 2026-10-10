import subprocess
import sys
import threading

import pytest

from l4.agents.base import RunRequest
from l4.agents.fake import FakeAdapter, Step
from l4.agents.gate import ConcurrencyGate, GateBusy, GatedAdapter, slots_for
from l4.config.schema import Profile


def gate(tmp_path, **kw) -> ConcurrencyGate:
    return ConcurrencyGate(tmp_path, **kw)


def test_second_run_waits_or_falls_back(tmp_path):
    g = gate(tmp_path)
    first = g.try_acquire("codex", "abc", 1)
    assert first is not None and g.is_busy("codex", "abc", 1)
    assert g.try_acquire("codex", "abc", 1) is None
    assert not g.is_busy("codex", "other-identity", 1) and not g.is_busy("claude-code", "abc", 1)
    first.release()
    assert not g.is_busy("codex", "abc", 1)
    first.release()  # releasing twice is harmless


def test_max_concurrency_slots_are_independent(tmp_path):
    g = gate(tmp_path)
    held = [g.try_acquire("codex", "abc", 2) for _ in range(2)]
    assert all(held) and g.try_acquire("codex", "abc", 2) is None
    held[0].release()
    assert g.try_acquire("codex", "abc", 2) is not None


def test_acquire_polls_until_a_slot_frees_and_gives_up_after_the_wait(tmp_path):
    clock = {"t": 0.0}
    holder = gate(tmp_path).try_acquire("codex", "abc", 1)
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        clock["t"] += seconds
        if clock["t"] >= 6:
            holder.release()

    g = gate(tmp_path, sleep=sleep, monotonic=lambda: clock["t"])
    taken = g.acquire("codex", "abc", 1, wait_s=120, poll_s=2)
    assert taken is not None and sleeps == [2.0, 2.0, 2.0]
    stuck = gate(tmp_path, sleep=sleep, monotonic=lambda: clock["t"])  # the slot is taken again by `acquire` above
    assert stuck.wait_free("codex", "abc", 1, wait_s=10, poll_s=2) is False
    raised: list[BaseException] = []

    def contend() -> None:  # another thread: this one already holds a login lock (one at a time)
        try:
            stuck.acquire("codex", "abc", 1, wait_s=4, poll_s=2)
        except GateBusy as exc:
            raised.append(exc)

    thread = threading.Thread(target=contend)
    thread.start()
    thread.join()
    assert len(raised) == 1
    taken.release()


def test_a_slot_dies_with_its_process(tmp_path):
    code = (
        "import sys, time\nfrom pathlib import Path\nfrom l4.agents.gate import ConcurrencyGate\n"
        "slot = ConcurrencyGate(Path(sys.argv[1])).try_acquire('codex', 'abc', 1)\n"
        "print('held' if slot else 'busy', flush=True)\ntime.sleep(60)\n"
    )
    child = subprocess.Popen([sys.executable, "-c", code, str(tmp_path)], stdout=subprocess.PIPE, text=True)
    try:
        assert child.stdout.readline().strip() == "held"
        assert gate(tmp_path).is_busy("codex", "abc", 1)
    finally:
        child.kill()
        child.wait()
    assert not gate(tmp_path).is_busy("codex", "abc", 1)  # a crashed run leaks nothing


def test_the_default_slots_are_one_for_a_subscription_and_none_for_an_api_key():
    assert slots_for(Profile(adapter="codex", auth="subscription")) == 1
    assert slots_for(Profile(adapter="codex", auth="subscription", max_concurrency=3)) == 1  # a refreshable login
    assert slots_for(Profile(adapter="fake", auth="subscription", max_concurrency=3)) == 3  # no refresh token
    assert slots_for(Profile(adapter="codex", auth="api_key")) is None
    assert slots_for(Profile(adapter="codex", auth="api_key", max_concurrency=2)) == 2
    assert slots_for(Profile(adapter="fake")) is None


def request(tmp_path) -> RunRequest:
    return RunRequest(
        profile=Profile(adapter="fake"), role="implementer", cwd=tmp_path, prompt="p",
        result_path=tmp_path / "r.json", raw_events_path=tmp_path / "raw.jsonl", env={},
    )  # fmt: skip


def test_the_wrapping_adapter_holds_a_slot_around_each_run_and_releases_it_after_a_failure(tmp_path):
    g = gate(tmp_path)
    seen: list[bool] = []

    class Spy(FakeAdapter):
        extra_env = {"X": "1"}

        def run(self, req):
            seen.append(g.is_busy("fake", "id", 1))
            if len(seen) == 2:
                raise RuntimeError("agent crashed")
            return super().run(req)

    gated = GatedAdapter(Spy([Step(status="ok")] * 2), g, "fake", "id", 1)
    assert gated.name == "fake" and gated.extra_env == {"X": "1"} and gated.capabilities().schema_mode == "native"
    assert gated.run(request(tmp_path)).status == "ok" and seen == [True]
    assert not g.is_busy("fake", "id", 1)
    with pytest.raises(RuntimeError):
        gated.run(request(tmp_path))
    assert not g.is_busy("fake", "id", 1)  # released even though the run raised
    with pytest.raises(AttributeError):
        gated._missing  # noqa: B018


def test_a_run_that_cannot_get_a_slot_in_time_is_an_error_result_not_a_hang(tmp_path):
    g = gate(tmp_path, sleep=lambda s: None, monotonic=iter([0.0, 0.0, 999.0, 999.0]).__next__)
    holder = g.try_acquire("fake", "id", 1)
    gated = GatedAdapter(FakeAdapter([Step(status="ok")]), g, "fake", "id", 1, wait_s=5)
    out = gated.run(request(tmp_path))
    assert out.status == "rate_limited" and "another process holds the fake login" in out.detail
    holder.release()


def test_threads_never_share_a_slot(tmp_path):
    g = gate(tmp_path)
    inside, peak, lock = [0], [0], threading.Lock()

    def work():
        with g.acquire("t", "i", 1, wait_s=30, poll_s=0.001):
            with lock:
                inside[0] += 1
                peak[0] = max(peak[0], inside[0])
            with lock:
                inside[0] -= 1

    threads = [threading.Thread(target=work) for _ in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert peak[0] == 1
