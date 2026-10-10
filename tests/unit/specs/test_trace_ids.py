import pytest

from l4.gates.junit import TestCase
from l4.specs.criteria import trace_ids

C = "C-1234abcd"


def case(test_id: str, *criteria: str, message: str = "") -> TestCase:
    return TestCase(test_id, "failed", message, criteria=tuple(criteria))


@pytest.mark.parametrize(
    "test_id",
    [
        "tests.test_a::test_x_C-1234abcd",
        "tests.test_a::test_C_1234abcd_edge",
        "tests.test_a::test_c_1234ABCD",
        "tests.test_c_1234abcd::test_y",
        "tests.test_a::test_l4_c_1234abcd_free_shipping",
        "tests.test_a::test_l4_audit_c_1234abcd",
        "tests.test_a::test_param[C-1234abcd]",
    ],
)
def test_ids_in_name_classname_and_harness_names_trace(test_id: str):
    assert trace_ids(case(test_id)) == {C}


def test_the_marker_property_traces_and_merges_with_the_name():
    assert trace_ids(case("t::test_a_C_aaaaaaaa", C, "C-bbbbbbbb")) == {C, "C-bbbbbbbb", "C-aaaaaaaa"}


@pytest.mark.parametrize(
    "test_id",
    ["t::test_C_1234abc", "t::test_C_1234abcde", "t::test_xc_1234abcd", "t::test_AC-1234abcd", "t::test_C1234abcd"],
)
def test_malformed_or_embedded_ids_do_not_trace(test_id: str):
    assert trace_ids(case(test_id)) == frozenset()


def test_comments_and_messages_never_trace():
    assert trace_ids(case("t::test_a", message="# covers C-1234abcd\nassert False")) == frozenset()
