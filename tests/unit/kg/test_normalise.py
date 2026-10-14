"""The text normaliser, the recurrence key and the failure class (L4-KG-006, SCN-KG-12, SCN-KG-13)."""

import pytest

from l4.kg.normalise import failure_class, norm, recurrence_key


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Fix C-e25f06d8 now", "fix <criterion> now"),
        ("see F-1234abcd and L-09421538 and Q-12", "see <finding> and <lesson> and <question>"),
        ("commit deadbeef1 and 0123456789abcdef", "commit <sha> and <sha>"),
        ("lint gate `.venv/bin/ruff check --extend-exclude .l4 .` failed", "lint gate `…` failed"),
        ("wrote src/pricing/discounts.py:5:20 here", "wrote <path>:#:# here"),
        ("exit code 1 after 30 seconds", "exit code # after # seconds"),
        ("  Mixed   CASE\n\tand   spaces ", "mixed case and spaces"),
        ("C-e25f06d8, C-fa2e5d61", "<criterion>"),
        ("", ""),
    ],
)
def test_norm_rules(text, expected):
    assert norm(text) == expected


def test_norm_applies_nfc_before_folding():
    assert norm("Café") == norm("Café") == "café"


def test_norm_is_idempotent():
    for text in ["no new test traces C-e25f06d8", "lint gate `x` failed", "a/b 12 deadbeef1", "<criterion> <sha> #"]:
        assert norm(norm(text)) == norm(text)


def test_a_backticked_span_hides_its_ids_and_paths():
    assert norm("run `pytest tests/a.py::t C-e25f06d8` first") == "run `…` first"


def test_a_short_hex_word_or_a_dashed_word_is_kept():
    assert norm("a face, a decade, F-12") == "a face, a decade, f-#"


KEY_TITLE = "UI criterion without an end-to-end test"


def test_one_mistake_in_two_units_has_one_key_although_the_criterion_ids_differ():
    a = recurrence_key(KEY_TITLE, "cart-a › Cart › Shows count", "openspec")
    b = recurrence_key(KEY_TITLE, "cart-b › Cart › Shows count", "openspec")
    assert a == b == "ui criterion without an end-to-end test | cart › shows count"


def test_the_same_title_on_different_scenarios_has_two_keys():
    a = recurrence_key(KEY_TITLE, "cart › Cart › Shows count", "openspec")
    b = recurrence_key(KEY_TITLE, "cart › Cart › Clears", "openspec")
    assert a != b


def test_a_kiro_alias_or_no_criterion_has_an_empty_second_part():
    expected = "ui criterion without an end-to-end test | "
    assert recurrence_key(KEY_TITLE, "Req 2.1", "kiro") == expected
    assert recurrence_key(KEY_TITLE, "Req 3.4", "kiro") == expected
    assert recurrence_key(KEY_TITLE, None, "openspec") == expected
    assert recurrence_key(KEY_TITLE, "", "openspec") == expected
    assert recurrence_key(KEY_TITLE, "cap-only", "openspec") == expected


def test_the_title_goes_through_the_normaliser():
    assert recurrence_key("Test for C-e25f06d8 is missing", None, "kiro") == "test for <criterion> is missing | "


LIVE_REASONS = [
    ("no new test traces C-e25f06d8: tag the tests that check them with @pytest.mark.l4(",
     "no new test traces <criterion>"),
    ("no new test traces C-7dc9fae5, C-fa2e5d61: tag the tests", "no new test traces <criterion>"),
    ("lint gate `.venv/bin/ruff check .` failed (exit code 1):\nF401 [*] unused\n --> src/a.py:5:20",
     "lint gate `…` failed"),
    ("lint gate `.venv/bin/ruff check --extend-exclude .l4 .` failed (exit code 1):\nI001 Import block",
     "lint gate `…` failed"),
    ("new tests fail with an error that is neither an assertion nor NotImplementedError: tests.test_a::test_b",
     "new tests fail with an error that is neither an assertion nor notimplementederror"[:80]),  # cut at 80
    ("the agent step ended with status error: result invalid: summary: required",
     "the agent step ended with status error"),
    ("the agent step ended with status error: kiro-cli exited with code 4 (runError at init)",
     "the agent step ended with status error"),
    ("no new test: existing tests were changed and now fail: tests.test_stock::test_a", "no new test"),
]  # fmt: skip


@pytest.mark.parametrize(("reason", "expected"), LIVE_REASONS)
def test_failure_class_of_the_live_reasons(reason, expected):
    assert failure_class(reason) == expected


def test_failure_class_is_cut_at_the_first_paren_or_colon_outside_a_backticked_span():
    assert failure_class("gate `pytest a.py::t (x)` failed (exit code 2)") == "gate `…` failed"
    assert failure_class("it failed (exit code 2): detail") == "it failed"


def test_failure_class_is_at_most_80_characters_with_no_trailing_space():
    got = failure_class("word " * 40)
    assert len(got) <= 80 and got == got.rstrip()


def test_failure_class_of_an_empty_or_blank_first_line():
    assert failure_class("") == ""
    assert failure_class("   \nsecond line: x") == ""
    assert failure_class(": starts with a colon") == ""
