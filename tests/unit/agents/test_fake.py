import json
from pathlib import Path

import pytest

from l4.agents.base import AdapterError, ProbeCtx, RunRequest
from l4.agents.fake import FakeAdapter, Step
from l4.config.schema import Profile


def request(tmp_path: Path, **kw) -> RunRequest:
    cwd = tmp_path / "wt"
    cwd.mkdir(exist_ok=True)
    return RunRequest(
        profile=Profile(adapter="fake"), role="implementer", cwd=cwd, prompt="do it",
        result_path=tmp_path / "res" / "result.json", raw_events_path=tmp_path / "raw" / "events.jsonl", env={}, **kw,
    )  # fmt: skip


def test_fake_adapter_replays_script(tmp_path):
    fake = FakeAdapter([
        Step(status="ok", final_text="red done", structured={"status": "done"}, session_id="s1",
             writes={"tests/test_a.py": "def test_a(): assert False\n"}),
        Step(status="quota"),
    ])  # fmt: skip
    first = fake.run(request(tmp_path))
    assert first.status == "ok" and first.structured == {"status": "done"} and first.session_id == "s1"
    assert (tmp_path / "wt/tests/test_a.py").read_text() == "def test_a(): assert False\n"
    assert json.loads((tmp_path / "res/result.json").read_text()) == {"status": "done"}
    assert first.raw_events_path.read_text().strip() != ""
    assert fake.run(request(tmp_path)).status == "quota"
    assert [r.prompt for r in fake.requests] == ["do it", "do it"]


def test_an_exhausted_script_is_a_loud_error(tmp_path):
    with pytest.raises(AdapterError, match="exhausted"):
        FakeAdapter([]).run(request(tmp_path))


@pytest.mark.parametrize("target", ["../escape.txt", "/etc/l4-escape", "a/../../x"])
def test_scripted_writes_cannot_leave_the_worktree(tmp_path, target):
    with pytest.raises(AdapterError, match="outside the worktree"):
        FakeAdapter([Step(status="ok", writes={target: "x"})]).run(request(tmp_path))
    assert not (tmp_path / "escape.txt").exists()


def test_probes_pass_by_default_and_can_be_scripted(tmp_path):
    from l4.agents.base import ProbeResult

    ctx = ProbeCtx(environ={}, cwd=tmp_path, run=lambda *a: None)
    fake = FakeAdapter([], probes={"auth": ProbeResult("auth", False, reason="logged out")})
    assert fake.probe(Profile(adapter="fake"), "binary", ctx).ok
    out = fake.probe(Profile(adapter="fake"), "auth", ctx)
    assert not out.ok and out.reason == "logged out"
    assert fake.capabilities().schema_mode == "native"


def test_a_step_with_idle_s_sets_the_watch_mark_and_returns_timeout(tmp_path):
    from l4.agents.activity import ActivityWatch

    watch = ActivityWatch(0, lambda beat: None)
    fake = FakeAdapter([Step(idle_s=600), Step(idle_s=600), Step()])
    result = fake.run(request(tmp_path, watch=watch))
    assert result.status == "timeout" and watch.stopped_idle_s == 600
    assert fake.run(request(tmp_path)).status == "timeout"  # no watch: no mark, no error
    fresh = ActivityWatch(0, lambda beat: None)
    assert fake.run(request(tmp_path, watch=fresh)).status == "ok" and fresh.stopped_idle_s is None


def test_an_idle_step_shows_the_watch_the_tool_calls_and_the_reader_it_is_told_of(tmp_path):
    from l4.agents.activity import ActivityWatch

    silent, busy, bare = (ActivityWatch(0, lambda beat: None) for _ in range(3))
    fake = FakeAdapter([Step(idle_s=600), Step(idle_s=600, tool_calls=2), Step(idle_s=600, stream_reader=False)])
    fake.run(request(tmp_path, watch=silent))
    fake.run(request(tmp_path, watch=busy))
    fake.run(request(tmp_path, watch=bare))
    seen = [(w.snapshot(w.clock()).counts, w.snapshot(w.clock()).tool_calls) for w in (silent, busy, bare)]
    assert seen == [(True, 0), (True, 2), (False, 0)]


def test_a_step_reports_the_tokens_it_is_given(tmp_path):
    result = FakeAdapter([Step(input_tokens=7, output_tokens=3)]).run(request(tmp_path))
    assert (result.usage.input_tokens, result.usage.output_tokens) == (7, 3)


def test_a_step_replaces_a_file_a_directory_and_a_missing_path_with_a_link(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    wt = tmp_path / "wt"
    (wt / "pkg").mkdir(parents=True)
    (wt / "pkg" / "a.py").write_text("a\n")
    (wt / "f.py").write_text("f\n")
    step = Step(
        writes={"w.py": "w\n"},
        links={"pkg": str(outside), "f.py": "../x", "new/dir/l": "rel", "w.py": "../w"},
    )
    FakeAdapter([step]).run(request(tmp_path))
    assert (wt / "pkg").is_symlink() and (wt / "pkg").readlink() == outside  # a directory with files in it
    assert (wt / "f.py").is_symlink() and (wt / "f.py").readlink() == Path("../x")  # a file
    assert (wt / "new/dir/l").is_symlink()  # a missing path
    assert (wt / "w.py").is_symlink()  # applied after the writes
    assert list(outside.iterdir()) == []  # nothing was written through any of them


def test_a_scripted_link_outside_the_worktree_is_an_error(tmp_path):
    with pytest.raises(AdapterError, match="outside the worktree"):
        FakeAdapter([Step(links={"../escape": "x"})]).run(request(tmp_path))


def test_on_start_runs_first(tmp_path):
    seen: list[bool] = []
    req = request(tmp_path)
    step = Step(writes={"a.txt": "x"}, on_start=lambda r: seen.append((r.cwd / "a.txt").exists()))
    assert FakeAdapter([step]).run(req).status == "ok"
    assert seen == [False]  # before the step's writes


def test_the_fake_honours_the_interrupt_and_the_deadline(tmp_path):
    import threading
    from datetime import timedelta

    from l4 import deadline
    from l4.availability.cooldown import SystemClock

    # the request's own interrupt event, set by `on_start`
    req = request(tmp_path)
    done = FakeAdapter([Step(writes={"half.txt": "x"}, on_start=lambda r: r.interrupt.set())]).run(req)
    assert done.status == "cancelled" and (req.cwd / "half.txt").exists()  # the work was in progress
    # the run deadline, fired by `on_start`; the idle rule does not win over it
    clock = SystemClock()
    dl = deadline.RunDeadline(at=clock.now() + timedelta(hours=1), clock=clock, event=threading.Event())
    deadline.arm(dl)
    try:
        watch = type("W", (), {"stopped_idle_s": None})()
        req = request(tmp_path, watch=watch)
        done = FakeAdapter([Step(idle_s=600, on_start=lambda r: dl.fire())]).run(req)
        assert done.status == "cancelled" and watch.stopped_idle_s is None
    finally:
        deadline.disarm()
    # neither: unchanged
    assert FakeAdapter([Step(idle_s=600)]).run(request(tmp_path)).status == "timeout"
