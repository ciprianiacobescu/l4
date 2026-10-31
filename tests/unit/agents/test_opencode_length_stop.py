"""SCN-VER-268: an opencode run whose stream ends with last reason `length` is marked `length_stop` (L4-VER-071).

The status stays `error` and the detail is the one of every other run without a final stop; the mark is a field, never
a reading of the detail text. A run that ends for any other reason is not marked."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from l4.agents.base import RunResult
from l4.agents.opencode import OpenCodeAdapter
from l4.agents.opencode_v2 import OpenCodeV2Adapter

NOW = datetime(2026, 10, 31, 10, 0, tzinfo=UTC)


def event(kind: str, **fields) -> str:
    return json.dumps({"type": kind, "sessionID": "ses_x", **fields})


def stream(reason: str | None) -> list[str]:
    """A judge run: one step that writes some text and finishes for `reason` (None: no `step_finish` at all)."""
    lines = [event("step_start", part={}), event("text", part={"type": "text", "text": '{"criteria": ['})]
    if reason is not None:
        lines.append(event("step_finish", part={"reason": reason, "tokens": {"input": 10, "output": 32000}}))
    return lines


def v1(lines: list[str], tmp_path: Path) -> RunResult:
    return OpenCodeAdapter().parse(lines, exit_code=0, raw_events_path=tmp_path / "raw.jsonl", judge=True, now=NOW)


def v2(lines: list[str], tmp_path: Path, **kw) -> RunResult:
    return OpenCodeV2Adapter().parse(
        lines, exit_code=0, raw_events_path=tmp_path / "raw.jsonl", step_bound=200, judge=True, now=NOW, **kw
    )


def test_v1_a_length_reason_marks_the_run_and_keeps_status_and_detail(tmp_path):
    out = v1(stream("length"), tmp_path)
    assert out.length_stop is True and out.status == "error"
    assert out.detail == "the stream ended without a final stop (last reason: length)"


@pytest.mark.parametrize("reason", ["tool-calls", "other", None])
def test_v1_another_last_reason_does_not_mark_the_run(tmp_path, reason):
    out = v1(stream(reason), tmp_path)
    assert out.length_stop is False and out.status == "error"
    assert out.detail == f"the stream ended without a final stop (last reason: {reason or 'none'})"


def test_v1_a_finished_run_is_not_marked(tmp_path):
    out = v1(stream("stop"), tmp_path)
    assert out.length_stop is False and out.detail != "the stream ended without a final stop (last reason: stop)"


def test_v1_a_run_that_timed_out_after_a_length_step_is_not_marked(tmp_path):
    out = OpenCodeAdapter().parse(
        stream("length"), exit_code=0, raw_events_path=tmp_path / "raw.jsonl", judge=True, timed_out=True, now=NOW
    )
    assert out.status == "timeout" and out.length_stop is False


def test_v2_a_length_reason_with_no_export_marks_the_run(tmp_path):
    out = v2(stream("length"), tmp_path, export=None, export_problem="exit 1")
    assert out.status == "error" and out.length_stop is True
    assert out.detail == "opencode2 session export failed (exit 1) and the stream has no final stop"


def test_v2_a_length_reason_with_an_export_that_has_no_outcome_marks_the_run(tmp_path):
    out = v2(stream("length"), tmp_path, export={"info": {}, "messages": []})
    assert out.status == "error" and out.length_stop is True


def test_v2_a_length_reason_with_an_unsuccessful_outcome_marks_the_run(tmp_path):
    out = v2(stream("length"), tmp_path, export={"info": {"outcome": "failed"}, "messages": []})
    assert out.status == "error" and out.length_stop is True
    assert out.detail == "opencode2 session outcome failed"


@pytest.mark.parametrize("reason", ["tool-calls", "other", None])
def test_v2_another_last_reason_does_not_mark_the_run(tmp_path, reason):
    out = v2(stream(reason), tmp_path, export=None, export_problem="exit 1")
    assert out.status == "error" and out.length_stop is False
    out = v2(stream(reason), tmp_path, export={"info": {"outcome": "failed"}, "messages": []})
    assert out.status == "error" and out.length_stop is False


def test_v2_a_succeeded_export_is_not_marked_even_after_a_length_step(tmp_path):
    out = v2(stream("length"), tmp_path, export={"info": {"outcome": "succeeded"}, "messages": []}, result_text="{}")
    assert out.length_stop is False
