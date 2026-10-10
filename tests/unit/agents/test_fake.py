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
