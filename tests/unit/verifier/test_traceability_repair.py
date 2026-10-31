"""own-test-repair (L4-VER-070): a repaired test keeps no red proof by its id. Its own proof, recorded on
`task.repaired` and tied to the content of its file, is what counts."""

from datetime import UTC, datetime

from l4.config.schema import L4Config
from l4.gates.junit import TestCase, TestReport
from l4.state.ledger import LedgerEvent
from l4.verifier.traceability import NO_PROOF, red_proofs, trace_criteria

from .test_traceability import A, B, crit, proof, red_ok

X, Y = "e2e.check_a::test_x", "e2e.check_a::test_y"
PATH = "e2e/check_a.py"
SHA = "0123456789"


def repaired(proved: dict | None = None, sha10: dict | None = None, tests=(f"{PATH}::test_x",)) -> LedgerEvent:
    data = {
        "task": "1.1", "files": [PATH], "tests": list(tests), "ids": [X],
        "proved": {X: "base"} if proved is None else proved,
        "sha10": {PATH: SHA} if sha10 is None else sha10,
    }  # fmt: skip
    return LedgerEvent(datetime(2026, 10, 5, tzinfo=UTC), "r-1", "openspec:u", 3, "task.repaired", data)


def on_disk(content: str | None):
    return lambda path: content if path == PATH else None


LEDGER = [red_ok({A: proof([X, Y])})]


def test_a_repaired_test_loses_the_red_proof_of_its_id_and_the_others_keep_theirs():
    got = red_proofs([*LEDGER, repaired()])
    assert got == {A: {Y: "zero_value"}}  # no file content to tie the repair's proof to: none counts


def test_the_repairs_own_proof_stands_while_the_file_is_the_one_that_was_proved():
    got = red_proofs([*LEDGER, repaired()], on_disk(SHA))
    assert got == {A: {X: "repair", Y: "zero_value"}}


def test_the_repairs_proof_is_void_when_the_file_changed_after_it():
    assert red_proofs([*LEDGER, repaired()], on_disk("ffffffffff")) == {A: {Y: "zero_value"}}
    assert red_proofs([*LEDGER, repaired()], on_disk(None)) == {A: {Y: "zero_value"}}


def test_a_repair_that_proved_nothing_leaves_the_test_without_a_proof():
    assert red_proofs([*LEDGER, repaired(proved={})], on_disk(SHA)) == {A: {Y: "zero_value"}}
    assert red_proofs([*LEDGER, repaired(sha10={})], on_disk(SHA)) == {A: {Y: "zero_value"}}


def test_a_parametrised_variant_of_a_repaired_function_loses_its_proof_too():
    ledger = [red_ok({A: proof([f"{X}[1]", f"{X}[2]", Y])}), repaired(proved={f"{X}[1]": "zero_value"})]
    assert red_proofs(ledger, on_disk(SHA)) == {A: {f"{X}[1]": "repair", Y: "zero_value"}}


def test_a_proof_is_given_back_only_to_the_criteria_that_listed_the_test():
    ledger = [red_ok({A: proof([X]), B: proof([Y])}), repaired()]
    assert red_proofs(ledger, on_disk(SHA)) == {A: {X: "repair"}, B: {Y: "zero_value"}}


def test_the_evidence_of_a_criterion_rests_on_the_repair_proof_or_nothing():
    cases = TestReport({X: TestCase(X, "passed", criteria=(A,))})
    covered = trace_criteria([crit(A)], cases, [*LEDGER, repaired()], L4Config(), file_sha=on_disk(SHA))
    assert covered[0].state == "covered" and covered[0].tests[0].proof == "repair"
    voided = trace_criteria([crit(A)], cases, [*LEDGER, repaired()], L4Config(), file_sha=on_disk("ffffffffff"))
    assert voided[0].state == "uncovered" and voided[0].ignored[0][1].startswith(NO_PROOF)
    unproved = trace_criteria([crit(A)], cases, [*LEDGER, repaired()], L4Config())
    assert unproved[0].state == "uncovered"
