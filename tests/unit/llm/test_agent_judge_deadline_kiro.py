"""C-m1: a real kiro-cli judge process (a shell stand-in) stopped by the run deadline mid-stream still has its
credits recorded. The stand-in prints credits, then waits; on SIGINT it prints a success `runFinished`.
"""

import threading
import time
from pathlib import Path

import pytest

from l4 import deadline
from l4.agents.base import PermissionPolicy, RunRequest
from l4.agents.kiro_cli import KiroCliAdapter
from l4.availability.cooldown import SystemClock
from l4.config.schema import Profile
from l4.llm.agent_judge import AgentJudge

SCRIPT = r"""#!/bin/sh
cat > /dev/null
SID=sess123
mkdir -p "$KIRO_HOME/sessions/cli"
MODEL='{"session_state":{"rts_model_state":{"model_info":{"model_id":"claude-sonnet-4.5"}}}}'
printf '%s' "$MODEL" > "$KIRO_HOME/sessions/cli/$SID.json"
finish() {
  echo '{"type":"runFinished","data":{"status":"success","finalText":"{\"verdict\":\"PASS\"}","stopReason":"end_turn"}}'
  exit 0
}
trap finish INT
echo '{"type":"runStarted","data":{"engine":"v2","sessionId":"'$SID'"}}'
echo '{"type":"sessionUpdate","data":{"update":{"sessionUpdate":"agent_message_chunk","content":{"text":"ok"}}}}'
echo '{"type":"metadata","data":{"meteringUsage":[{"unit":"credit","value":0.42}]}}'
touch "$MARKER"
i=0
while [ $i -lt 600 ]; do sleep 0.1; i=$((i+1)); done
"""


class _NoTimer:
    daemon = True

    def __init__(self, *a, **k) -> None: ...
    def start(self) -> None: ...
    def cancel(self) -> None: ...


@pytest.fixture
def armed():
    dl = deadline.RunDeadline(at=SystemClock().now(), clock=SystemClock(), event=threading.Event())
    dl.at = dl.clock.now().replace(year=dl.clock.now().year + 1)
    deadline.arm(dl, timer=_NoTimer)
    yield dl
    deadline.disarm()


def _request(tmp_path: Path) -> RunRequest:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    exe = bindir / "kiro-cli"
    exe.write_text(SCRIPT)
    exe.chmod(0o755)
    marker = tmp_path / "running"
    env = {"PATH": f"{bindir}:/usr/bin:/bin", "MARKER": str(marker)}
    (tmp_path / "wt").mkdir()
    return RunRequest(
        profile=Profile(adapter="kiro-cli"),
        role="judge",
        cwd=tmp_path / "wt",
        prompt="judge this",
        result_path=tmp_path / "res" / "result.json",
        raw_events_path=tmp_path / "raw" / "events.jsonl",
        env=env,
        result_schema={"type": "object"},
        permission_policy=PermissionPolicy("judge"),
        timeout_s=60,
    )


def _fire_when(marker: Path, dl) -> None:
    def go() -> None:
        end = time.monotonic() + 20
        while not marker.exists() and time.monotonic() < end:
            time.sleep(0.02)
        dl.fire()

    threading.Thread(target=go, daemon=True).start()


def test_a_stopped_kiro_judge_records_its_credits(tmp_path, armed):
    req = _request(tmp_path)
    _fire_when(tmp_path / "running", armed)
    events: list[tuple[str, dict]] = []

    class Sink:
        def append(self, type_: str, **fields) -> None:
            events.append((type_, fields))

    judge = AgentJudge(KiroCliAdapter(), lambda prompt, schema, timeout: req, events=Sink(), role="judge", profile="k")
    with pytest.raises(deadline.DeadlineReached):
        judge.complete_structured("system", [], {"type": "object"})
    credits = [f for t, f in events if t == "budget.cost" and "credits" in f]
    assert len(credits) == 1 and credits[0]["credits"] == pytest.approx(0.42)
    assert credits[0]["profile"] == "k" and credits[0]["role"] == "judge" and credits[0]["credits_source"]
