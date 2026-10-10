import typing
from pathlib import Path

from l4.agents.base import AdapterError, EventSink, LimitSignal, RunResult, Usage
from l4.state.ledger import LedgerWriter

SPEC_STATUSES = {
    "ok", "max_turns", "budget", "permission_blocked", "auth", "quota",
    "rate_limited", "error", "timeout", "cancelled",
}  # fmt: skip


def test_runresult_status_values_match_spec():
    # SPEC L4-FAC-001: the ten values, nothing added or dropped
    assert set(typing.get_args(typing.get_type_hints(RunResult)["status"])) == SPEC_STATUSES


def test_runresult_defaults_are_empty_not_shared(tmp_path: Path):
    a = RunResult(status="ok", raw_events_path=tmp_path / "a")
    b = RunResult(status="ok", raw_events_path=tmp_path / "b")
    a.permission_denials.append({"tool_name": "Bash"})
    assert b.permission_denials == [] and a.usage == Usage() and a.limit is None


def test_limit_signal_is_immutable_and_adapter_error_is_an_exception():
    signal = LimitSignal(tool="codex", model=None, kind="usage_limit", resets_at=None, source="text", raw_excerpt="x")
    try:
        signal.tool = "other"  # type: ignore[misc]
    except AttributeError:
        pass
    else:
        raise AssertionError("LimitSignal must be frozen")
    assert issubclass(AdapterError, Exception)


def test_a_ledger_writer_is_an_event_sink(tmp_path: Path):
    from l4.redact import Redactor

    writer = LedgerWriter.open(tmp_path, "openspec:x", "r-20261003T1312Z-7f3a", redactor=Redactor({}))
    sink: EventSink = writer  # structural: mypy/pyright would reject a signature mismatch
    sink.append("availability.selected", role="implementer")


def test_read_result_file_never_follows_a_symlink_or_reads_a_huge_file(tmp_path):
    from l4.agents.base import MAX_RESULT_BYTES, read_result_file

    real = tmp_path / "real.json"
    real.write_text('{"a": 1}')
    link = tmp_path / "link.json"
    link.symlink_to(real)
    big = tmp_path / "big.json"
    big.write_bytes(b"x" * (MAX_RESULT_BYTES + 1))
    assert read_result_file(real) == '{"a": 1}'
    assert read_result_file(link) is None and read_result_file(big) is None
    assert read_result_file(tmp_path / "missing.json") is None
    assert read_result_file(tmp_path) is None
