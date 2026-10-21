"""Review M3 (L4-IMP-064, L4-SEC): every excerpt is redacted BEFORE it is cut, so no prefix of a secret reaches the
committed ledger, `questions.md` or the console."""

import json
from pathlib import Path

import pytest

from l4.gates.junit import TestCase, TestReport
from l4.gates.runner import GateResult
from l4.implementer import variant
from l4.implementer.tdd import run_setup
from l4.redact import Redactor

from .conftest import RUN_ID, Bench

TOKEN = "glpat-" + "A1b2C3d4E5f6G7h8I9j0"  # a GitLab PAT shape


@pytest.mark.parametrize("pad", [500, 539, 544, 560])
def test_s1_no_fragment_of_a_token_reaches_the_committed_ledger(make_bench, pad):
    bench: Bench = make_bench([])
    (bench.wb.worktree / "tests/test_leak.py").write_text(f'raise RuntimeError("{"x" * pad} {TOKEN}")\n')
    run_setup(bench.wb)
    bench.wb.run_gate("test", bench.wb.cfg.gates.test.command, reports=bench.wb.cfg.gates.test.reports)
    ledger = (bench.wb.ref.path / ".l4" / "ledger" / f"{RUN_ID}.jsonl").read_text()
    for fragment in range(8, len(TOKEN)):
        assert TOKEN[:fragment] not in ledger, f"the first {fragment} characters of the token are in the ledger"
    events = [e for e in map(json.loads, ledger.splitlines()) if e["type"] == "gate.finished" and e.get("excerpt")]
    assert events and all(len(e["excerpt"]) <= 600 for e in events)


SECRET = "Q7" * 50  # a configured value of 100 characters, no token shape


@pytest.mark.parametrize("pad", [150, 182, 220])
def test_s2_a_configured_value_never_leaks_a_prefix_into_a_reason(tmp_path: Path, pad: int):
    redactor = Redactor({"API_KEY": SECRET})
    detail = f"tests/test_a.py:1: in <module>\n    import pytdd.store\nE   RuntimeError: {'x' * pad} {SECRET}\n"
    real = TestReport({"tests.test_a::test_x": TestCase("tests.test_a::test_x", "passed")})
    other = TestCase("tests.test_b::test_y", "passed")
    report = TestReport(
        {other.id: other}, ["tests.test_a"], {"tests.test_a": "src/pytdd/store.py:3: in <module>\n" + detail}
    )
    log = tmp_path / "g.log"
    log.write_text("")
    run = variant.classify(
        GateResult("test-presatisfied", "fail", "", 1, log, report), real, redact=redactor.redact_text
    )
    _, why = variant.test_outcome(run, "tests.test_a::test_x", real, frozenset(), redact=redactor.redact_text)
    empty = TestReport({}, ["tests.test_a"], {"tests.test_a": detail})
    whole = variant.classify(
        GateResult("test-presatisfied", "fail", "", 2, log, empty), real, redact=redactor.redact_text
    )
    for text in (why, whole.reason):
        assert SECRET[:6] not in text, text[-60:]
    # a log tail with no report (the no-report branch) is redacted before its first E line is cut
    log.write_text(f"E   RuntimeError: {'y' * pad} {SECRET}\n")
    nothing = variant.classify(
        GateResult("test-presatisfied", "fail", "exit 2", 2, log, None), real, redact=redactor.redact_text
    )
    assert SECRET[:6] not in nothing.reason
