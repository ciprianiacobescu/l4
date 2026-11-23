"""L4-IMP-102 (D2, D3): which tests a fix task is about, and the failure block it carries."""

from l4.verifier.failures import (
    BASE_FAILS_TITLE,
    MAX_FAILURE_BLOCK_CHARS,
    MAX_SHOWN_FAILURES,
    failure_block,
    shown_failure_ids,
)

E2E_ID, UNIT_ID, BROKEN = "e2e.test_layout::test_width[chromium]", "tests.test_a::test_x", "tests.test_broken"
FAILURES = {
    E2E_ID: {
        "gate": "e2e",
        "kind": "assertion",
        "message": "assert 1508 == 1500",
        "excerpt": "E   assert 1508 == 1500",
    },
    "e2e.test_layout::test_other": {"gate": "e2e", "kind": "other", "message": "Error: boom"},
    "e2e.test_gone": {"gate": "e2e", "kind": "collection", "message": "ImportError"},
    UNIT_ID: {"gate": "test", "kind": "assertion", "message": "assert 0"},
    BROKEN: {"gate": "test", "kind": "collection", "message": "ImportError: x"},
}


def test_a_gate_finding_names_every_record_of_its_gate_collection_ones_included():
    assert shown_failure_ids(FAILURES, "e2e gate failed", "x") == sorted(
        [E2E_ID, "e2e.test_layout::test_other", "e2e.test_gone"]
    )
    assert shown_failure_ids(FAILURES, "test gate failed", "x") == sorted([UNIT_ID, BROKEN])


def test_a_new_tests_finding_names_the_recorded_ids_its_detail_holds_even_from_a_cut_list():
    detail = f"{E2E_ID}, {UNIT_ID} and 4 more"
    assert shown_failure_ids(FAILURES, "new tests failed", detail) == sorted([E2E_ID, UNIT_ID])
    assert shown_failure_ids(FAILURES, "new tests errored", f"{UNIT_ID}, no.such::id") == [UNIT_ID]


def test_any_other_title_and_a_verdict_without_failures_name_none():
    assert shown_failure_ids(FAILURES, "other", E2E_ID) == []
    assert shown_failure_ids(None, "e2e gate failed", "x") == [] and shown_failure_ids({}, "test gate failed", "") == []


def test_the_block_shows_each_test_with_its_excerpt_indented_by_two_spaces():
    block = failure_block(FAILURES, [E2E_ID])
    assert block == f"{E2E_ID} (assertion, e2e):\n  E   assert 1508 == 1500"


def test_a_test_without_an_excerpt_shows_its_message():
    assert failure_block(FAILURES, [UNIT_ID]) == f"{UNIT_ID} (assertion, test):\n  assert 0"


def test_ids_without_a_record_give_an_empty_block():
    assert failure_block(FAILURES, ["no.such::id"]) == "" and failure_block(FAILURES, []) == ""
    assert failure_block(None, [E2E_ID]) == ""


def test_the_block_shows_at_most_eight_tests_and_counts_the_rest():
    many = {f"t.m::t{n:02}": {"gate": "test", "kind": "assertion", "message": f"m{n}"} for n in range(11)}
    block = failure_block(many, list(many))
    assert MAX_SHOWN_FAILURES == 8 and block.count("(assertion, test):") == 8
    assert block.splitlines()[-1] == "and 3 more failing tests (the round's verdict.json)"
    assert "t.m::t07" in block and "t.m::t08" not in block  # sorted, whole tests only


def test_the_block_is_cut_at_6000_characters_at_a_test_boundary_the_closing_count_included():
    big = {
        f"t.m::t{n}": {"gate": "test", "kind": "assertion", "excerpt": "\n".join(["E   " + "x" * 90] * 8)}
        for n in range(8)
    }
    block = failure_block(big, list(big))
    assert len(block) <= MAX_FAILURE_BLOCK_CHARS and block.count("(assertion, test):") < 8
    assert block.splitlines()[-1].startswith("and ") and "more failing tests" in block.splitlines()[-1]
    assert all(line.startswith(("t.m::t", "  ", "and ")) for line in block.splitlines())  # whole tests only


def test_one_test_over_the_bound_is_cut_to_it_and_counted_with_the_rest():
    one = {f"t.m::{n}": {"gate": "test", "kind": "assertion", "excerpt": "E   " + "y" * 7000} for n in "ab"}
    block = failure_block(one, list(one))
    assert len(block) <= MAX_FAILURE_BLOCK_CHARS and block.startswith("t.m::a (assertion, test):")
    assert block.splitlines()[-1] == "and 1 more failing tests (the round's verdict.json)"


BASE_ID = "test/arch/repo.test.ts::graph"
WITH_BASE = {
    **FAILURES,
    BASE_ID: {"gate": "base-tests", "kind": "assertion", "message": "expected [] to deeply equal []", "excerpt": "E x"},
    "test/arch/gone.test.ts": {"gate": "base-tests", "kind": "other", "message": "boom"},
}


def test_a_base_tests_finding_names_every_base_tests_record():  # L4-VER-080
    assert BASE_FAILS_TITLE == "a pre-existing test fails on the unit's code"
    assert shown_failure_ids(WITH_BASE, BASE_FAILS_TITLE, "x") == sorted([BASE_ID, "test/arch/gone.test.ts"])
    assert shown_failure_ids(FAILURES, BASE_FAILS_TITLE, "x") == []  # a verdict of 0.4.59 holds no such record


def test_the_readers_that_filter_by_gate_ignore_base_tests_records():  # L4-VER-080
    from l4.verifier.failures import e2e_ids_of, failing_ids, finding_test_ids

    assert failing_ids(WITH_BASE, "test") == failing_ids(FAILURES, "test")
    assert failing_ids(WITH_BASE, "e2e") == failing_ids(FAILURES, "e2e")
    assert shown_failure_ids(WITH_BASE, "test gate failed", "x") == shown_failure_ids(FAILURES, "test gate failed", "x")
    verdict = {"failures": WITH_BASE, "findings": []}
    assert e2e_ids_of(verdict, []) == []
    for title in ("test gate failed", "e2e gate failed", BASE_FAILS_TITLE):
        assert finding_test_ids(title, "x", WITH_BASE) == finding_test_ids(title, "x", FAILURES)
