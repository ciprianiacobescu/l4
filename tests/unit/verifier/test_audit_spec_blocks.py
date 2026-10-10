"""M1.13 line 26 (W-C4, SPEC L4-VER-002a): the audit writer sees the unit's design and proposal, so a file the spec lets
change (wave C: the event log, in design D3) is visible to it; bounded, and absent when the unit has none."""

from l4.specs.base import Criterion, Framework
from l4.verifier.audit import MAX_SPEC_CHARS, run_audit

from .test_audit import CID, Replies

OK = {"criterion": CID, "not_testable": "needs a browser"}


def run(make_bench, files: dict[str, str]):
    bench = make_bench([])
    for name, text in files.items():
        (bench.wb.ref.path / name).write_text(text, encoding="utf-8")
    criterion = Criterion(CID, "a > b > c", Framework.OPENSPEC, "pricing", "b", "c", "WHEN x THEN y", "specs/x.md", 1)
    writer = Replies(OK)
    run_audit(
        bench.wb, writer, {CID: criterion}, [CID], [], base_sha="HEAD", head="HEAD", round_no=1, timeout_s=5,
        emit=lambda kind, **data: None,
    )  # fmt: skip
    return writer.sent[0]


def test_the_design_and_the_proposal_reach_the_writer_after_the_code(make_bench):
    sent = run(make_bench, {"design.md": "D3: only events.jsonl may change when the server logs a request."})
    assert '<l4:data source="design.md">' in sent and "only events.jsonl may change" in sent
    assert '<l4:data source="proposal.md">' in sent  # the fixture unit has one


def test_a_unit_without_a_design_has_no_design_block(make_bench):
    assert 'source="design.md"' not in run(make_bench, {})


def test_the_spec_text_is_bounded(make_bench):
    sent = run(make_bench, {"design.md": "x" * (MAX_SPEC_CHARS * 3) + " END-OF-DESIGN"})
    assert "END-OF-DESIGN" not in sent and sent.count("x") < MAX_SPEC_CHARS * 2


def test_the_spec_blocks_are_not_taken_for_source_files_to_check_names_against():
    from l4.verifier.testwriter import _source_modules

    assert _source_modules([("design.md", "x = 1\n"), ("proposal.md", "y = 2\n")]) == {}
