from l4.agents.base import RunResult, Usage
from l4.agents.fake import FakeAdapter, Step
from l4.implementer import normalize as n
from l4.implementer.result import FILE_RESULT_SCHEMA, RESULT_SCHEMA


def test_file_schema_drops_what_l4_knows():
    assert FILE_RESULT_SCHEMA["required"] == ["status", "summary"]
    assert FILE_RESULT_SCHEMA["$id"] == "l4/implementer-file-result@1"
    for name in ("phase", "task_ids", "files_changed", "tests_added"):
        assert name not in FILE_RESULT_SCHEMA["properties"]
        assert name in RESULT_SCHEMA["properties"]
    assert RESULT_SCHEMA["$id"] == "l4/implementer-result@1"
    assert RESULT_SCHEMA["required"] == ["status", "phase", "task_ids", "summary"]
    assert set(FILE_RESULT_SCHEMA["properties"]) == set(RESULT_SCHEMA["properties"]) - {
        "phase", "task_ids", "files_changed", "tests_added",
    }  # fmt: skip


def test_new_run_fields_default_to_none(tmp_path):
    run = RunResult(status="ok", raw_events_path=tmp_path / "e")
    assert run.last_message is None and run.result_problem is None
    assert Usage().context_peak_tokens is None and Usage().context_peak_percent is None
    step = Step()
    assert step.last_message is None and step.rejected is None and step.result_problem is None


def test_fix_event_writes_from_and_leaves_out_none():
    assert n.Fix("summary", "set", from_="final_message").as_event() == {
        "field": "summary", "fix": "set", "from": "final_message",
    }  # fmt: skip
    assert n.Fix("notes", "cut", length=9, count=2).as_event() == {
        "field": "notes", "fix": "cut", "count": 2, "length": 9,
    }  # fmt: skip


def test_constants():
    assert n.CUT_MARKER.format(n=5) == "[cut by L4: 5 characters removed]"
    assert n.SCAN_CHARS == 200_000 and n.NO_SUMMARY.startswith("(no summary")


def test_fake_adapter_passes_the_new_fields(tmp_path):
    from l4.agents.base import RunRequest
    from l4.config.schema import Profile

    cwd = tmp_path / "wt"
    cwd.mkdir()
    req = RunRequest(
        profile=Profile(adapter="fake"), role="implementer", cwd=cwd, prompt="p",
        result_path=tmp_path / "r" / "result.json", raw_events_path=tmp_path / "e" / "events.jsonl", env={},
    )  # fmt: skip
    step = Step(last_message="m", rejected={"a": 1}, result_problem="invalid")
    run = FakeAdapter([step]).run(req)
    assert (run.last_message, run.rejected, run.result_problem) == ("m", {"a": 1}, "invalid")
