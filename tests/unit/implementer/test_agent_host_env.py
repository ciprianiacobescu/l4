"""The harness's own environment reaches an adapter only as `RunRequest.host_env` (an opencode provider key is read
from it), and never widens the sandbox environment the agent gets (L4-SEC-001)."""

from l4.agents.base import RunResult
from l4.agents.fake import FakeAdapter
from l4.implementer.tdd import agent_step
from l4.specs.base import Task

from .conftest import red_step

TASK = Task("1.1", "1.1", "1.1 Add `apply_discount`", False, " ", 0, 1, 3)
KEY = "sk-host-only-0123456789abcdef"


class Capture:
    name = "fake"

    def __init__(self) -> None:
        self.requests = []

    def capabilities(self):
        return FakeAdapter([]).capabilities()

    def run(self, req) -> RunResult:
        self.requests.append(req)
        return FakeAdapter([red_step()]).run(req)


def test_the_request_carries_the_host_environment_but_the_agent_env_stays_closed(make_bench):
    bench = make_bench([])
    wb = bench.wb
    wb.host_env["MAGNITUDE_API_KEY"] = KEY  # type: ignore[index]
    capture = Capture()
    wb.selected.impl = capture  # type: ignore[misc]
    agent_step(wb, "red", TASK, 1, None)
    (req,) = capture.requests
    assert req.host_env["MAGNITUDE_API_KEY"] == KEY
    assert "MAGNITUDE_API_KEY" not in req.env and KEY not in str(req.env)
