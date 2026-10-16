"""result-contract 1.1: finding the result object (design D3). SCN-IMP-191 at function level."""

import json
import time
from pathlib import Path

from l4.agents.base import RunResult
from l4.implementer.normalize import SCAN_CHARS, Found, find_result, last_result_object


def run(status: str = "ok", **fields: object) -> RunResult:
    return RunResult(status=status, raw_events_path=Path("events.jsonl"), **fields)  # type: ignore[arg-type]


def test_the_object_with_status_wins_over_an_earlier_code_sample():
    obj = {"status": "done", "summary": "added two tests"}
    text = f'Here is a sample: {{"a": 1}}\n\nThe result:\n```json\n{json.dumps(obj)}\n```\n'
    found = last_result_object(text)
    assert found == Found(obj, "final_message", json.dumps(obj))


def test_a_nested_question_object_is_not_taken_alone():
    obj = {"status": "blocked", "questions": [{"title": "t", "context": "c", "kind": "product", "summary": "x"}]}
    found = last_result_object("text " + json.dumps(obj))
    assert found is not None and found.obj == obj


def test_an_object_with_only_summary_is_result_like():
    found = last_result_object('{"summary": "s"}')
    assert found is not None and found.obj == {"summary": "s"}


def test_the_last_result_like_object_wins():
    text = '{"status": "failed", "summary": "first"} then {"status": "done", "summary": "second"}'
    found = last_result_object(text)
    assert found is not None and found.obj["summary"] == "second"
    assert found.text == '{"status": "done", "summary": "second"}'


def test_an_object_that_wraps_a_result_like_object_is_looked_into():
    # the wrapper has no `status` or `summary` itself: the scan goes on at the next character
    found = last_result_object('{"result": {"status": "done", "summary": "inner"}}')
    assert found is not None and found.obj == {"status": "done", "summary": "inner"}


def test_text_with_no_result_like_object_gives_none():
    assert last_result_object("") is None
    assert last_result_object("prose only, a brace { here and } there") is None
    assert last_result_object('{"a": 1} and [1, 2] and {"b": {"c": 2}}') is None
    assert last_result_object('{"status": "done", "summary": "cut off') is None


def test_a_300_000_character_text_is_scanned_only_at_its_end():
    early = '{"status": "done", "summary": "early"}'
    late = '{"status": "done", "summary": "late"}'
    pad = "x" * 300_000
    assert last_result_object(early + pad) is None  # the object lies before the last 200 000 characters
    found = last_result_object(early + pad + late)
    assert found is not None and found.obj["summary"] == "late"
    edge = "y" * (SCAN_CHARS - len(late)) + late  # exactly the scanned size: found
    assert last_result_object("z" * 5000 + edge) is not None


def test_a_deep_unterminated_text_does_not_hang_or_raise():
    started = time.monotonic()
    assert last_result_object('{"a":' * 40_000) is None
    assert time.monotonic() - started < 20


def test_source_1_the_delivered_result_when_the_run_is_ok():
    obj = {"status": "done", "summary": "s"}
    found = find_result(run(structured=obj, final_text='{"status": "failed", "summary": "other"}'))
    assert found == Found(obj, "result")


def test_source_2_the_rejected_object_when_the_result_is_invalid():
    rejected = {"status": "red", "summary": "s"}
    found = find_result(
        run("error", rejected=rejected, result_problem="invalid", final_text='{"status": "done", "summary": "t"}')
    )
    assert found == Found(rejected, "result")


def test_source_3_the_final_text_when_there_is_no_file():
    text = 'done.\n```json\n{"status": "done", "summary": "added two tests"}\n```'
    found = find_result(run(final_text=text, result_problem="missing"))
    assert found is not None and found.source == "final_message"
    assert found.obj == {"status": "done", "summary": "added two tests"}
    assert found.text == '{"status": "done", "summary": "added two tests"}'
    # a native run whose result channel failed also falls back to its text
    assert find_result(run("error", final_text=text, result_problem="not_json")) is not None


def test_an_ok_run_with_no_object_falls_back_to_the_text():
    assert find_result(run(final_text='{"status": "done", "summary": "s"}')) is not None
    assert find_result(run(final_text="prose, no object")) is None
    assert find_result(run()) is None


def test_invalid_without_a_rejected_object_falls_back_to_the_text():
    found = find_result(run("error", result_problem="invalid", final_text='{"summary": "s"}'))
    assert found is not None and found.source == "final_message"


def test_a_run_that_is_not_ok_and_has_no_result_problem_is_not_a_callers_case():
    text = '{"status": "done", "summary": "s"}'
    assert find_result(run("error", final_text=text, structured={"status": "done"})) is None
    assert find_result(run("timeout", final_text=text)) is None


def test_the_order_of_the_three_sources():
    text = '{"status": "done", "summary": "from text"}'
    ok = run(structured={"summary": "r"}, rejected={"summary": "j"}, final_text=text, result_problem="invalid")
    assert find_result(ok) == Found({"summary": "r"}, "result")
    bad = run("error", rejected={"summary": "j"}, final_text=text, result_problem="invalid")
    assert find_result(bad) == Found({"summary": "j"}, "result")
    only_text = run("error", final_text=text, result_problem="missing")
    assert find_result(only_text) is not None and find_result(only_text).source == "final_message"  # type: ignore[union-attr]
