"""Step 4 (verifier 1.9, 3.4, 3.5): tracing tests, proofs and the evidence state of each criterion."""

from datetime import UTC, datetime

from l4.config.schema import L4Config
from l4.gates.junit import TestCase, TestReport
from l4.specs.base import Criterion, Framework
from l4.state.ledger import LedgerEvent
from l4.verifier.traceability import (
    NO_PROOF,
    apply_adequacy,
    extra_candidates,
    extra_proofs,
    ignored_findings,
    inadequate_findings,
    new_covered,
    red_proofs,
    trace_criteria,
)

A, B, C = "C-aaaaaaaa", "C-bbbbbbbb", "C-cccccccc"


def crit(cid: str, text: str = "WHEN x THEN y") -> Criterion:
    return Criterion(cid, f"cap › req › {cid}", Framework.OPENSPEC, "cap", "req", cid, text, "specs/cap/spec.md", 1)


def case(test_id: str, status: str = "passed", *marks: str) -> TestCase:
    return TestCase(test_id, status, criteria=marks)  # type: ignore[arg-type]


def report(*cases: TestCase) -> TestReport:
    return TestReport({c.id: c for c in cases})


def red_ok(criteria: dict) -> LedgerEvent:
    return LedgerEvent(datetime(2026, 10, 4, tzinfo=UTC), "r-1", "openspec:u", 1, "task.red_ok", {"criteria": criteria})


def audit(criterion: str, tests: list[str], status: str = "accepted") -> LedgerEvent:
    data = {"criterion": criterion, "status": status, "tests": tests}
    return LedgerEvent(datetime(2026, 10, 4, tzinfo=UTC), "r-1", "openspec:u", 2, "verify.audit", data)


CFG = L4Config()


def proof(tests: list[str], disc: list[str] | None = None, kind: str = "zero_value") -> dict:
    return {"tests": tests, "proof": kind, "discriminating": tests if disc is None else disc}


def test_criterion_without_tracing_test_is_uncovered():
    [e] = trace_criteria([crit(A)], report(case("t::other")), [], CFG)
    assert e.state == "uncovered" and not e.tests


def test_red_proved_test_covers_and_a_failing_one_fails():
    ledger = [red_ok({A: proof(["t::a"])})]
    [ok] = trace_criteria([crit(A)], report(case("t::a", "passed", A)), ledger, CFG)
    assert ok.state == "covered" and [(t.id, t.proof) for t in ok.tests] == [("t::a", "zero_value")]
    [bad] = trace_criteria([crit(A)], report(case("t::a", "failed", A)), ledger, CFG)
    assert bad.state == "fail"


def test_the_test_name_traces_like_the_marker():
    ledger = [red_ok({A: proof(["t.test_x::test_c_aaaaaaaa_rounds"])})]
    [e] = trace_criteria([crit(A)], report(case("t.test_x::test_c_aaaaaaaa_rounds")), ledger, CFG)
    assert e.state == "covered"


def test_five_criteria_test_is_evidence_for_none():
    ids = ["C-0000000" + str(i) for i in range(1, 6)]
    marks = tuple(ids)
    ledger = [red_ok({i: proof(["t::wide"]) for i in ids})]
    out = trace_criteria([crit(i) for i in ids], report(case("t::wide", "passed", *marks)), ledger, CFG)
    assert {e.state for e in out} == {"uncovered"}
    assert all("traces 5 criteria" in why for e in out for _, why in e.ignored)
    assert len(ignored_findings(out)) == 5


def test_call_only_tagged_test_is_non_discriminating_minor():
    ledger = [
        red_ok({A: proof(["t::calls_only"], disc=[])})
    ]  # the zero-value run left the criterion with no failing test
    [e] = trace_criteria([crit(A)], report(case("t::calls_only", "passed", A)), ledger, CFG)
    assert e.state == "uncovered" and e.ignored
    [finding] = ignored_findings([e])
    assert finding.severity.value == "minor" and finding.criterion == A


def test_zero_answer_test_counts_together_with_its_sibling():
    ledger = [red_ok({A: proof(["t::zero", "t::real"], disc=["t::real"])})]
    cases = [case("t::zero", "passed", A), case("t::real", "passed", A)]
    [e] = trace_criteria([crit(A)], report(*cases), ledger, CFG)
    assert e.state == "covered" and {t.id for t in e.tests} == {"t::zero", "t::real"}


def test_unchanged_criterion_pass_to_pass_counts():
    [e] = trace_criteria([crit(A)], report(case("t::a", "passed", A)), [], CFG, base=[crit(A)])
    assert e.state == "covered" and e.tests[0].proof == "pass_to_pass"
    [changed] = trace_criteria([crit(A, "WHEN x THEN z")], report(case("t::a", "passed", A)), [], CFG, base=[crit(A)])
    assert changed.state == "uncovered"


def test_an_audit_test_counts_only_when_the_ledger_accepted_it():
    name = "tests.test_l4_audit_c_aaaaaaaa_r1::test_a"
    [named] = trace_criteria([crit(A)], report(case(name)), [], CFG)
    assert named.state == "uncovered"  # the name alone proves nothing
    [e] = trace_criteria([crit(A)], report(case(name)), [audit(A, [name])], CFG)
    assert e.state == "covered" and e.tests[0].proof == "audit"
    [rejected] = trace_criteria([crit(A)], report(case(name)), [audit(A, [name], "rejected")], CFG)
    assert rejected.state == "uncovered"


def test_extra_reports_count_as_generated():
    e2e = report(case("e2e.test_l4_c_aaaaaaaa::test_login", "passed", A))
    [e] = trace_criteria([crit(A)], report(), [], CFG, extra_reports=[e2e])
    assert e.state == "covered" and e.tests[0].proof == "generated"
    failing = report(case("e2e.test_l4_c_aaaaaaaa::test_login", "failed", A))
    assert trace_criteria([crit(A)], report(), [], CFG, extra_reports=[failing])[0].state == "fail"


def test_skipped_tests_are_not_evidence():
    ledger = [red_ok({A: proof(["t::a"])})]
    [e] = trace_criteria([crit(A)], report(case("t::a", "skipped", A)), ledger, CFG)
    assert e.state == "uncovered" and e.ignored == (("t::a", "it was skipped"),)


def test_adequacy_review_removes_a_test_from_the_evidence_and_is_listed():
    ledger = [red_ok({A: proof(["t::a"])})]
    ev = trace_criteria([crit(A)], report(case("t::a", "passed", A)), ledger, CFG)
    [judged] = apply_adequacy(ev, [("t::a", A, False)])
    assert not judged.tests[0].adequate
    assert [f.title for f in inadequate_findings([judged])] == ["the judge called a test inadequate"]
    assert ignored_findings([judged]) == []
    [other] = apply_adequacy(ev, [("t::a", B, False)])
    assert other.tests[0].adequate


def test_red_proofs_ignore_a_record_without_a_discriminating_test():
    assert red_proofs([red_ok({A: proof(["t::a"], disc=[])})]) == {}
    assert red_proofs([red_ok({A: proof(["t::a"])})]) == {A: {"t::a": "zero_value"}}


def test_new_covered_leaves_out_pass_to_pass_and_audited_criteria():
    ledger = [red_ok({A: proof(["t::a"])}), audit(B, ["t.test_l4_audit_c_bbbbbbbb_r1::test_b"])]
    cases = [
        case("t::a", "passed", A),
        case("t.test_l4_audit_c_bbbbbbbb_r1::test_b", "passed", B),
        case("t::c", "passed", C),
    ]
    ev = trace_criteria([crit(A), crit(B), crit(C)], report(*cases), ledger, CFG, base=[crit(C)])
    assert [e.criterion for e in new_covered(ev)] == [A]


# --- tests no red record covers: candidates for a discrimination run (M1.11 W6, decision 8) ---------------------------

OWNER = "tests.test_owner::test_regression"
FILE_OF = {OWNER: "tests/test_owner.py", "tests.test_other::test_x": "tests/test_other.py"}.get


def ignored_for(why: str, test: str = OWNER, criterion: str = A):
    from l4.verifier.types import CriterionEvidence

    return [CriterionEvidence(criterion, "alias", "uncovered", (), ((test, why),))]


def test_a_test_only_people_wrote_is_a_human_candidate():
    found = extra_candidates(
        ignored_for(f"{NO_PROOF} (no red, audit or generated record)"),
        {"tests/test_owner.py": "human"},
        (),
        file_of=FILE_OF,
    )
    assert found == {A: [(OWNER, "human")]}


def test_a_file_the_harness_also_touched_is_no_candidate():
    ignored = ignored_for(f"{NO_PROOF} (no red, audit or generated record)")
    assert extra_candidates(ignored, {}, (), file_of=FILE_OF) == {}  # not attributed to people alone
    assert extra_candidates(ignored, {"tests/test_other.py": "human"}, (), file_of=FILE_OF) == {}


def test_a_test_chore_file_is_a_chore_candidate():
    ignored = ignored_for(f"{NO_PROOF} (no red, audit or generated record)")
    assert extra_candidates(ignored, {}, ["tests/test_owner.py"], file_of=FILE_OF) == {A: [(OWNER, "chore")]}
    both = extra_candidates(ignored, {"tests/test_owner.py": "human"}, ["tests/test_owner.py"], file_of=FILE_OF)
    assert both == {A: [(OWNER, "human")]}  # the person's authorship is the stronger claim


def test_a_test_ignored_for_tracing_too_many_criteria_is_no_candidate():
    many = ignored_for("it traces 3 criteria (verifier.max_criteria_per_test=2)")
    assert extra_candidates(many, {"tests/test_owner.py": "human"}, ["tests/test_owner.py"], file_of=FILE_OF) == {}
    skipped = ignored_for("it was skipped")
    assert extra_candidates(skipped, {"tests/test_owner.py": "human"}, (), file_of=FILE_OF) == {}


def extra(criterion: str, tests: list[str], files: dict[str, str], source: str = "human") -> LedgerEvent:
    data = {"round": 1, "criterion": criterion, "tests": tests, "source": source, "via": "base", "files": files}
    return LedgerEvent(datetime(2026, 10, 4, tzinfo=UTC), "r-1", "openspec:u", 3, "verify.extra_proof", data)


def test_an_accepted_extra_proof_counts_for_the_same_file_content_only():
    event = extra(A, [OWNER], {"tests/test_owner.py": "abcdef0123"})
    assert extra_proofs([event], {"tests/test_owner.py": "abcdef0123"}.get) == {A: {OWNER: "human"}}
    assert extra_proofs([event], {"tests/test_owner.py": "0000000000"}.get) == {}  # the file changed since
    assert extra_proofs([event], {}.get) == {}  # or is gone
    [e] = trace_criteria(
        [crit(A)], report(case(OWNER, "passed", A)), [event], CFG, extra=extra_proofs([event], lambda p: "abcdef0123")
    )
    assert e.state == "covered" and [(t.id, t.proof) for t in e.tests] == [(OWNER, "human")]
    [bare] = trace_criteria([crit(A)], report(case(OWNER, "passed", A)), [event], CFG)
    assert bare.state == "uncovered"  # an event alone is no proof: only `extra_proofs` checks the file


def test_a_reason_given_by_the_caller_replaces_the_generic_no_proof_text():
    [e] = trace_criteria(
        [crit(A)],
        report(case(OWNER, "passed", A)),
        [],
        CFG,
        reasons={OWNER: "passes against the zero values and on the base"},
    )
    assert e.ignored == ((OWNER, "passes against the zero values and on the base"),)
