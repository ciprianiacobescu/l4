"""opencode-transient-errors 2.1 (L4-AVL-006): a transient error event of an OpenCode hello (1.x and 2.x) is tried once
more after 20 s, with the run deadline checked before and after the wait. Every test gives the context a `sleep`, so no
test waits."""

import dataclasses
import json
from pathlib import Path

import pytest

from l4 import deadline
from l4.agents.base import ProbeCtx
from l4.agents.factory import Factory, RoleUnavailable
from l4.agents.opencode import OpenCodeAdapter
from l4.agents.opencode_v2 import OpenCodeV2Adapter
from l4.availability.probes import HELLO_RETRY_WAIT_S, hello_retry
from l4.config.schema import Profile
from l4.doctor.context import CmdResult

from ._selection_helpers import Sink, config, world
from .conftest import RECORDED
from .test_hello_failure_class import opencode_error, opencode_profile
from .test_probes_opencode_v2 import FREE, V2_VERSION

OPENCODE_1 = RECORDED / "opencode" / "1.18.33"
V1_VERSION = {("--version",): CmdResult(0, "1.18.34\n", "")}
OVERLOADED = opencode_error("[503] Upstream error: Service temporarily overloaded")
OK = (OPENCODE_1 / "hello-ok-stdin-prompt.jsonl").read_text()
V2_OK = (RECORDED / "opencode" / "2.0.32" / "hello-ok-step-finish.jsonl").read_text()


def v2_error(message: str, status: int | None = None) -> str:
    error: dict[str, object] = {"type": "unknown", "message": message}
    if status is not None:
        error["status"] = status
    return json.dumps({"type": "error", "sessionID": "ses_x", "error": error}) + "\n"


class Hellos:
    """Answers the hello (the `run` call) from a queue and counts the hellos; every other call goes to the rules."""

    def __init__(self, base, *answers: CmdResult) -> None:
        self.base, self.answers, self.hellos = base, list(answers), 0

    def __call__(self, argv, cwd, env, timeout):
        if argv[1] != "run":
            return self.base(argv, cwd, env, timeout)
        self.hellos += 1
        return self.answers.pop(0)


def sequenced(make_ctx, version, *answers: CmdResult) -> tuple[ProbeCtx, Hellos, list[float]]:
    ctx, run = make_ctx(version)
    hellos, waits = Hellos(run, *answers), []
    return dataclasses.replace(ctx, run=hellos, sleep=waits.append), hellos, waits


def v1(make_ctx, *answers: CmdResult):
    ctx, hellos, waits = sequenced(make_ctx, V1_VERSION, *answers)
    return OpenCodeAdapter().probe(opencode_profile, "hello", ctx), hellos, waits


def v2(make_ctx, *answers: CmdResult):
    ctx, hellos, waits = sequenced(make_ctx, V2_VERSION, *answers)
    return OpenCodeV2Adapter().probe(FREE, "hello", ctx), hellos, waits


def failing(stdout: str, code: int = 1) -> CmdResult:
    return CmdResult(code, stdout, "")


# --- the helper ---


def ctx_with(sleep) -> ProbeCtx:
    return ProbeCtx(environ={}, cwd=Path("."), run=lambda *a: None, sleep=sleep)


def test_the_helper_runs_once_when_the_result_is_not_transient_and_twice_when_it_is():
    waits: list[float] = []
    ctx = ctx_with(waits.append)
    calls = iter(["fine"])
    assert hello_retry(ctx, lambda: next(calls), lambda _r: False) == ("fine", None) and waits == []
    answers = iter(["busy", "busy again"])
    assert hello_retry(ctx, lambda: next(answers), lambda r: r.startswith("busy")) == ("busy again", HELLO_RETRY_WAIT_S)
    assert waits == [HELLO_RETRY_WAIT_S]  # a second transient result is final: no third call (the iterator is empty)


def test_a_deadline_that_has_fired_stops_the_helper_before_the_wait(armed_deadline):
    waits: list[float] = []
    armed_deadline().fire()
    calls: list[int] = []
    with pytest.raises(deadline.DeadlineReached):
        hello_retry(ctx_with(waits.append), lambda: calls.append(1) or "busy", lambda _r: True)
    assert calls == [1] and waits == []


def test_a_deadline_that_fires_during_the_wait_stops_the_second_hello(armed_deadline):
    dl = armed_deadline()
    calls: list[int] = []
    with pytest.raises(deadline.DeadlineReached):
        hello_retry(ctx_with(lambda _s: dl.fire()), lambda: calls.append(1) or "busy", lambda _r: True)
    assert calls == [1]


def test_a_deadline_that_fires_during_the_wait_of_an_opencode_hello_passes_through(make_ctx, armed_deadline):
    dl = armed_deadline()
    ctx, hellos, _ = sequenced(make_ctx, V1_VERSION, failing(OVERLOADED), failing(OVERLOADED))
    ctx = dataclasses.replace(ctx, sleep=lambda _s: dl.fire())
    with pytest.raises(deadline.DeadlineReached):
        OpenCodeAdapter().probe(opencode_profile, "hello", ctx)
    assert hellos.hellos == 1


# --- SCN-AVL-29, SCN-AVL-30 ---


@pytest.mark.parametrize(("run", "overloaded"), [(v1, OVERLOADED), (v2, v2_error("[503] Service overloaded"))])
def test_a_transient_hello_is_tried_once_more_after_one_wait(make_ctx, run, overloaded):
    good = CmdResult(0, OK if run is v1 else V2_OK, "")
    out, hellos, waits = run(make_ctx, failing(overloaded), good)
    assert out.ok and hellos.hellos == 2 and waits == [20.0]
    assert out.detail["hello_retry_wait_s"] == 20.0 and "ms" in out.detail


@pytest.mark.parametrize(("run", "overloaded"), [(v1, OVERLOADED), (v2, v2_error("[503] Service overloaded"))])
def test_a_second_transient_error_is_final_and_the_wait_is_recorded(make_ctx, run, overloaded):
    out, hellos, waits = run(make_ctx, failing(overloaded), failing(overloaded), CmdResult(0, "unused", ""))
    assert not out.ok and out.failure_class == "transient" and "(status 503)" in (out.reason or "")
    assert hellos.hellos == 2 and waits == [20.0] and len(hellos.answers) == 1  # no third hello
    assert out.detail["hello_retry_wait_s"] == 20.0


def test_a_first_try_that_answers_has_no_retry_field(make_ctx):
    out, hellos, waits = v1(make_ctx, CmdResult(0, OK, ""))
    assert out.ok and hellos.hellos == 1 and waits == [] and "hello_retry_wait_s" not in out.detail


# --- SCN-AVL-31: what is not tried again ---

V1_NOT_RETRIED = [
    (opencode_error("[401] key rejected"), 1, "auth"),
    (opencode_error("You are out of credits", 402), 1, "limit"),
    (opencode_error("[429] Too many requests"), 1, "limit"),
    (opencode_error("[400] bad request"), 1, "other"),
    (opencode_error("something else went wrong"), 1, "other"),
    ("", 124, "transient"),  # the hello itself timed out
    ("", 2, "transient"),  # an exit without an error event
    (OVERLOADED, 124, "transient"),  # timed out, whatever the stream said
]
V2_NOT_RETRIED = [
    (v2_error("[401] key rejected"), 1, "auth"),
    (v2_error("out of credits", 402), 1, "limit"),
    (v2_error("[429] Too many requests"), 1, "limit"),
    (v2_error("[400] bad request"), 1, "other"),
    (v2_error("something else went wrong"), 1, "other"),
    ("", 124, "transient"),
    ("", 2, "transient"),
    (v2_error("[503] Service overloaded"), 124, "transient"),
]


@pytest.mark.parametrize(("stdout", "code", "kind"), V1_NOT_RETRIED)
def test_v1_hello_is_not_tried_again_for_anything_but_a_transient_error_event(make_ctx, stdout, code, kind):
    out, hellos, waits = v1(make_ctx, failing(stdout, code), CmdResult(0, OK, ""))
    assert not out.ok and out.failure_class == kind
    assert hellos.hellos == 1 and waits == [] and "hello_retry_wait_s" not in out.detail


@pytest.mark.parametrize(("stdout", "code", "kind"), V2_NOT_RETRIED)
def test_v2_hello_is_not_tried_again_for_anything_but_a_transient_error_event(make_ctx, stdout, code, kind):
    out, hellos, waits = v2(make_ctx, failing(stdout, code), CmdResult(0, V2_OK, ""))
    assert not out.ok and out.failure_class == kind
    assert hellos.hellos == 1 and waits == [] and "hello_retry_wait_s" not in out.detail


def test_an_unsupported_version_hello_is_not_tried_again(make_ctx):
    cli_major = RECORDED.parent / "cli_major" / "opencode"
    ctx, run = make_ctx(V1_VERSION)
    stderr = (cli_major / "v2-2.0.32.run-pure.stderr.txt").read_text()
    hellos, waits = Hellos(run, CmdResult(1, (cli_major / "v2-2.0.32.run-help.stdout.txt").read_text(), stderr)), []
    out = OpenCodeAdapter().probe(opencode_profile, "hello", dataclasses.replace(ctx, run=hellos, sleep=waits.append))
    assert out.failure_class == "unsupported_version" and hellos.hellos == 1 and waits == []


# --- the selection: nothing cached, the wait shown ---

FREE_V1 = Profile(adapter="opencode", model="opencode/big-pickle", vendor="unknown")


def selection(tmp_path, make_ctx, *answers: CmdResult):
    ctx, run = make_ctx(V1_VERSION)
    hellos, waits, sink = Hellos(run, *answers), [], Sink()
    ctx = dataclasses.replace(ctx, run=hellos, sleep=waits.append)
    clock, store = world(tmp_path)
    cfg = config({"free": FREE_V1}, implementer=["free"])
    factory = Factory(cfg, ctx, events=sink, adapters={"opencode": OpenCodeAdapter()}, availability=store, clock=clock)
    return factory, hellos, waits, sink


def test_a_selection_shows_the_hello_retry_wait(tmp_path, make_ctx):
    factory, hellos, waits, sink = selection(tmp_path, make_ctx, failing(OVERLOADED), CmdResult(0, OK, ""))
    assert factory.for_role("implementer", "u").profile_name == "free"
    [event] = sink.of("availability.selected")
    assert event["probes"]["free"]["hello_retry_wait_s"] == 20.0 and "hello_ms" in event["probes"]["free"]
    assert hellos.hellos == 2 and waits == [20.0]


def test_a_profile_skipped_after_two_transient_hellos_is_asked_again_at_the_next_selection(tmp_path, make_ctx):
    overloaded = failing(OVERLOADED)
    factory, hellos, waits, sink = selection(tmp_path, make_ctx, overloaded, overloaded, overloaded, overloaded)
    for _ in range(2):
        with pytest.raises(RoleUnavailable):
            factory.for_role("implementer", "u")
    assert hellos.hellos == 4 and waits == [20.0, 20.0]  # nothing was cached: two hellos each time, no third
