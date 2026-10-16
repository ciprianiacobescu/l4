"""Agent A of run-liveness: the stream readers, the activity watch and the beat text (SCN-FAC-20, SCN-FAC-21)."""

import json
import logging
from pathlib import Path

import pytest

from l4.agents.activity import (
    ActivityWatch,
    Beat,
    Signal,
    StreamReader,
    beat_text,
    claude_code_signals,
    codex_signals,
    kiro_signals,
    opencode_signals,
)

RECORDED = Path(__file__).resolve().parents[2] / "fixtures" / "recorded"
STREAMS: dict[str, tuple[str, StreamReader]] = {
    "opencode": ("opencode/1.18.33/red-ok.jsonl", opencode_signals),
    "claude-code": ("claude-code/2.1.288/red-ok.jsonl", claude_code_signals),
    "codex": ("codex/0.160.0/red-ok.jsonl", codex_signals),
    "kiro-cli": ("kiro-cli/2.28.0/red-tools.stream.jsonl", kiro_signals),
}
READERS = [opencode_signals, claude_code_signals, codex_signals, kiro_signals]


def lines_of(name: str) -> list[str]:
    # The committed opencode stream has one line that the e-mail scrubber broke (`@pytest.mark` became `\\<email>`,
    # an invalid JSON escape). It is a fixture artifact, not agent output: the test mends it, the fixture stays.
    text = (RECORDED / STREAMS[name][0]).read_text().replace("\\<email>", "@")
    return text.splitlines()


def expected_calls(name: str) -> int:
    events = [json.loads(x) for x in lines_of(name)]
    if name == "opencode":
        return sum(e.get("type") == "tool_use" for e in events)
    if name == "claude-code":
        return sum(
            b.get("type") == "tool_use" for e in events if e.get("type") == "assistant" for b in e["message"]["content"]
        )
    if name == "codex":
        return sum(
            e.get("type") == "item.started" and e["item"]["type"] in {"command_execution", "file_change"}
            for e in events
        )
    return sum(e["data"]["update"]["sessionUpdate"] == "tool_call" for e in events if e.get("type") == "sessionUpdate")


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def watch_over(name: str, lines: list[str]) -> ActivityWatch:
    watch = ActivityWatch(0, lambda beat: None)
    watch.start(0.0, STREAMS[name][1])
    for text in lines:
        watch.line(text)
    return watch


@pytest.mark.parametrize("name", list(STREAMS))
def test_recorded_stream_counts_and_closes_every_call(name):
    watch = watch_over(name, lines_of(name))
    beat = watch.snapshot(1.0)
    assert expected_calls(name) > 0
    assert beat.tool_calls == expected_calls(name)
    assert beat.counts is True
    assert watch.has_open_call() is False and beat.open_calls == 0


def test_recorded_stream_counts_match_the_task_notes():
    assert [expected_calls(n) for n in STREAMS] == [19, 6, 4, 20]


def cut_after_first_start(name: str) -> list[str]:
    reader = STREAMS[name][1]
    lines = lines_of(name)
    for i, text in enumerate(lines):
        if any(s.kind == "start" for s in reader(text)):
            return lines[: i + 1]
    raise AssertionError("no start in the stream")


@pytest.mark.parametrize("name", ["claude-code", "codex", "kiro-cli"])
def test_stream_cut_after_a_start_has_one_open_call(name):
    watch = watch_over(name, cut_after_first_start(name))
    assert watch.has_open_call() is True
    assert watch.snapshot(1.0).open_calls == 1


def test_opencode_stream_never_has_an_open_call():
    lines = lines_of("opencode")
    first = next(i for i, x in enumerate(lines) if opencode_signals(x))
    watch = watch_over("opencode", lines[: first + 1])
    assert watch.snapshot(1.0).tool_calls == 1
    assert watch.has_open_call() is False


def test_reader_shapes():
    assert opencode_signals(json.dumps({"type": "tool_use", "part": {}})) == (Signal("call"),)
    claude_start = {
        "type": "assistant",
        "message": {"content": [{"type": "text", "text": "x"}, {"type": "tool_use", "id": "t1"}]},
    }
    claude_end = {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": "t1"}]}}
    assert claude_code_signals(json.dumps(claude_start)) == (Signal("start", "t1"),)
    assert claude_code_signals(json.dumps(claude_end)) == (Signal("end", "t1"),)
    for kind, event in (("start", "item.started"), ("end", "item.completed")):
        for item_type in ("command_execution", "file_change", "mcp_tool_call", "web_search"):
            line = json.dumps({"type": event, "item": {"id": "i1", "type": item_type}})
            assert codex_signals(line) == (Signal(kind, "i1"),)
    for status, kind in (("completed", "end"), ("failed", "end"), ("in_progress", None)):
        update = {"sessionUpdate": "tool_call_update", "toolCallId": "k1", "status": status}
        got = kiro_signals(json.dumps({"type": "sessionUpdate", "data": {"update": update}}))
        assert got == ((Signal(kind, "k1"),) if kind else ())
    started = {"sessionUpdate": "tool_call", "toolCallId": "k1"}
    assert kiro_signals(json.dumps({"type": "sessionUpdate", "data": {"update": started}})) == (Signal("start", "k1"),)


SILENT_LINES = [
    "not json at all",
    "[1, 2, 3]",
    json.dumps({"type": "something_unknown", "x": 1}),
    json.dumps({"type": "item.started", "item": {"id": "t", "type": "todo_list"}}),
]


@pytest.mark.parametrize("reader", READERS)
def test_scn_fac_21_readers_never_raise_and_give_no_signal(reader):
    odd = ["", "null", "42", '"s"', "{", json.dumps({"type": "assistant", "message": "x"}),
           json.dumps({"type": "user", "message": {"content": [1, "a", None]}}),
           json.dumps({"type": "sessionUpdate", "data": "x"}),
           json.dumps({"type": "item.started", "item": "x"})]  # fmt: skip
    for text in SILENT_LINES + odd:
        assert reader(text) == ()


def test_scn_fac_21_lines_count_as_activity_and_unknown_end_counts_one_call():
    clock = Clock()
    watch = ActivityWatch(0, lambda beat: None, clock)
    watch.start(0.0, codex_signals)
    clock.now = 5.0
    for text in SILENT_LINES:
        watch.line(text)
    beat = watch.snapshot(8.0)
    assert (beat.tool_calls, beat.open_calls, beat.since_last_s) == (0, 0, 3.0)
    assert watch.has_open_call() is False
    watch.line(json.dumps({"type": "item.completed", "item": {"id": "never", "type": "command_execution"}}))
    beat = watch.snapshot(8.0)
    assert (beat.tool_calls, beat.open_calls) == (1, 0)


def test_watch_state_holds_no_text():
    secret = "SECRET-TEXT-OF-THE-STREAM"
    watch = ActivityWatch(0, lambda beat: None)
    watch.start(0.0, claude_code_signals)
    watch.line(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": secret}]}}))
    watch.line(secret)
    assert secret not in repr(vars(watch))
    assert secret not in repr(watch.snapshot(1.0))


def test_start_without_a_reader_has_no_counts():
    watch = ActivityWatch(0, lambda beat: None)
    watch.start(2.0, None)
    watch.line("anything")
    beat = watch.snapshot(10.0)
    assert beat.counts is False and beat.elapsed_s == 8.0 and beat.tool_calls == 0


def test_open_calls_by_id_and_a_repeated_start_counts_once():
    clock = Clock()
    watch = ActivityWatch(0, lambda beat: None, clock)
    watch.start(0.0, claude_code_signals)

    def start(i: str) -> str:
        return json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "id": i}]}})

    def end(i: str) -> str:
        return json.dumps({"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": i}]}})

    clock.now = 10.0
    watch.line(start("a"))
    watch.line(start("a"))
    clock.now = 30.0
    watch.line(start("b"))
    beat = watch.snapshot(100.0)
    assert (beat.tool_calls, beat.open_calls, beat.open_for_s, beat.since_last_s) == (2, 2, 90.0, 70.0)
    watch.line(end("a"))
    beat = watch.snapshot(100.0)
    assert (beat.open_calls, beat.open_for_s) == (1, 70.0)
    watch.line(end("b"))
    assert watch.has_open_call() is False
    assert watch.snapshot(100.0).open_for_s == 0.0


def beats_over(heartbeat_s: float, times: list[float]) -> list[float]:
    got: list[float] = []
    watch = ActivityWatch(heartbeat_s, lambda beat: got.append(beat.elapsed_s))
    watch.start(100.0, None)
    for t in times:
        watch.tick(100.0 + t)
    return got


def test_beat_times_with_a_fake_clock():
    times = [0.0, 30.0, 59.9, 60.0, 61.0, 100.0, 119.9, 120.0, 130.0, 181.0]
    assert beats_over(60, times) == [60.0, 120.0, 181.0]
    assert beats_over(0, times) == []
    assert beats_over(60, [0.0, 59.0]) == []


def test_a_late_tick_gives_one_beat_not_a_burst():
    assert beats_over(60, [250.0, 251.0, 259.0, 299.0, 300.0]) == [250.0, 300.0]


def test_a_callback_that_raises_does_not_stop_tick(caplog):
    calls: list[float] = []

    def on_beat(beat: Beat) -> None:
        calls.append(beat.elapsed_s)
        raise RuntimeError("boom")

    watch = ActivityWatch(10, on_beat)
    watch.start(0.0, None)
    with caplog.at_level(logging.DEBUG):
        watch.tick(10.0)
        watch.tick(20.0)
    assert calls == [10.0, 20.0]
    assert any(r.levelno == logging.DEBUG for r in caplog.records)
    assert not any(r.levelno > logging.DEBUG for r in caplog.records)


def test_beat_text_forms():
    assert beat_text(Beat(360, 14, 20, 0, 0, True)) == "working 6m, 14 tool calls, last activity 20s ago"
    assert beat_text(Beat(60, 1, 5, 0, 0, True)) == "working 1m, 1 tool call, last activity 5s ago"
    assert beat_text(Beat(480, 15, 240, 1, 240, True)) == (
        "working 8m, 15 tool calls, last activity 4m ago, 1 tool call open for 4m"
    )
    assert beat_text(Beat(480, 15, 240, 2, 245, True)).endswith(", 2 tool calls open for 4m")
    assert beat_text(Beat(360, 0, 360, 0, 0, False)) == "working 6m"
    assert beat_text(Beat(3725, 0, 0, 0, 0, False)) == "working 1h 2m"
