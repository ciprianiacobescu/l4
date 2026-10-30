"""own-test-repair (L4-IMP-091, second paragraph): the structural check of a repair, pure: the text of a test file
before and after the step in, the rules the change breaks out. Each rule is shown both ways."""

from l4.implementer.repaircheck import check_repair, function_source

BEFORE = """\
import pytest
from playwright.sync_api import Page, expect

URL = "http://localhost/cart"


@pytest.fixture
def cart(page: Page):
    page.goto(URL)
    return page


def helper(page):
    return page.get_by_role("button")


def test_x(cart, page):
    page.goto(URL)
    expect(page).to_have_url(lambda url: url.endswith("/cart"))
    assert page.get_by_role("button", name="Pay").is_visible()
    helper(page).click()


def test_y(page):
    assert page.title() == "Cart"


class TestCart:
    def test_total(self, page):
        page.goto(URL)
        assert page.locator("#total").inner_text() == "3"
"""


def broken(after: str, tests=("test_x",), before: str = BEFORE) -> list[str]:
    return [b.rule for b in check_repair(before, after, tests)]


def edited(old: str, new: str, text: str = BEFORE) -> str:
    assert old in text
    return text.replace(old, new, 1)


# --- what a repair may do -------------------------------------------------------------------------------------------


def test_the_consumer_repair_of_a_url_expectation_is_kept():  # SCN-IMP-450
    after = edited(
        'expect(page).to_have_url(lambda url: url.endswith("/cart"))',
        'page.wait_for_url(lambda url: url.endswith("/cart"))',
    )
    assert broken(after) == []


def test_the_consumer_repair_that_adds_exact_to_a_role_call_is_kept():
    after = edited('page.get_by_role("button", name="Pay")', 'page.get_by_role("button", name="Pay", exact=True)')
    assert broken(after) == []


def test_an_added_import_used_in_one_replaced_statement_is_kept():  # SCN-IMP-457
    after = edited("import pytest\n", "import re\n\nimport pytest\n")
    after = edited(
        'expect(page).to_have_url(lambda url: url.endswith("/cart"))',
        'expect(page).to_have_url(re.compile(r".*/cart"))',
        after,
    )
    assert broken(after) == []


def test_a_new_from_import_of_a_new_name_is_kept():
    after = edited("import pytest\n", "import pytest\nfrom re import compile as rx\n")
    after = edited('lambda url: url.endswith("/cart")', 'rx(r".*/cart")', after)
    assert broken(after) == []


def test_a_method_of_a_module_level_class_can_be_repaired():
    after = edited('inner_text() == "3"', 'inner_text(timeout=5000) == "3"')
    assert broken(after, ("TestCart.test_total",)) == []


def test_comments_layout_and_docstring_indentation_are_no_change():
    after = edited("def test_x(cart, page):\n", "def test_x(cart, page):\n    # explained\n")
    assert broken(after) == []


def test_three_statements_may_be_replaced_and_a_with_that_was_there_may_change_inside():
    with_before = BEFORE.replace(
        "    helper(page).click()\n", "    with page.expect_navigation():\n        helper(page).click()\n"
    )
    after = with_before.replace("helper(page).click()", "helper(page).click(timeout=1)").replace(
        "page.goto(URL)\n    expect", "page.goto(URL, wait_until='load')\n    expect"
    )
    assert broken(after, before=with_before) == []


# --- SCN-IMP-451: nothing else of the file may change ---------------------------------------------------------------


def test_another_test_of_the_file_changed_is_refused():  # SCN-IMP-451
    assert broken(edited('page.title() == "Cart"', 'page.title() == "Carts"')) == ["outside-changed"]


def test_a_helper_the_test_uses_changed_is_refused():
    assert broken(edited('return page.get_by_role("button")', 'return page.get_by_role("link")')) == ["outside-changed"]


def test_a_fixture_the_test_uses_changed_is_refused():
    assert broken(edited("page.goto(URL)\n    return page", "return page")) == ["outside-changed"]


def test_a_module_constant_changed_is_refused():
    assert broken(edited('URL = "http://localhost/cart"', 'URL = "http://localhost/other"')) == ["outside-changed"]


def test_a_module_level_call_added_is_refused():
    assert broken(BEFORE + "\nprint('hi')\n") == ["outside-changed"]


def test_a_new_function_or_a_new_test_is_refused():
    assert broken(BEFORE + "\n\ndef test_z():\n    assert True\n") == ["outside-changed"]


def test_a_method_of_the_class_other_than_the_repaired_one_changed_is_refused():
    after = edited('inner_text() == "3"', 'inner_text() == "4"')
    assert broken(after, ("test_x",)) == ["outside-changed"]


def test_another_test_renamed_is_refused():
    assert broken(BEFORE.replace("def test_y(page):", "def test_y_old(page):")) == ["outside-changed"]


# --- imports --------------------------------------------------------------------------------------------------------


def test_an_import_may_only_be_added_so_a_removed_one_is_refused():
    assert "import-removed" in broken(edited("import pytest\n", ""))


def test_a_star_import_is_refused():
    assert "import-star" in broken(edited("import pytest\n", "import pytest\nfrom os.path import *\n"))


def test_an_import_that_binds_a_name_the_module_binds_is_refused():
    after = edited("import pytest\n", "import pytest\nfrom os import getcwd as helper\n")
    assert "import-shadows" in broken(after)
    assert "import-shadows" in broken(edited("import pytest\n", "import pytest\nimport os as URL\n"))


def test_a_future_import_is_refused():
    assert "future-import" in broken(edited("import pytest\n", "from __future__ import annotations\n\nimport pytest\n"))


def test_an_import_that_rebinds_an_imported_name_to_another_source_is_refused():
    after = edited("import pytest\n", "import pytest\nfrom evil import expect as expect2\nfrom evil import Page\n")
    assert "import-shadows" in broken(after)


# --- SCN-IMP-452: no check may go -----------------------------------------------------------------------------------


def test_an_assert_removed_is_refused():  # SCN-IMP-452
    after = edited(
        '    assert page.get_by_role("button", name="Pay").is_visible()\n',
        '    page.get_by_role("button", name="Pay").is_visible()\n',
    )
    assert "assert-removed" in broken(after)


def test_a_deleted_statement_is_refused():
    assert broken(edited("    helper(page).click()\n", "")) == ["statement-count"]


def test_an_added_statement_is_refused():
    assert broken(edited("    helper(page).click()\n", "    helper(page).click()\n    page.reload()\n")) == [
        "statement-count"
    ]


def test_more_than_three_statements_replaced_is_refused():
    after = edited("    page.goto(URL)\n    expect", "    page.goto(URL + '/')\n    expect")
    after = edited('lambda url: url.endswith("/cart")', 'lambda url: url.endswith("/cart/")', after)
    after = edited('name="Pay"', 'name="Pay now"', after)
    assert broken(after) == []  # three
    after = edited("helper(page).click()", "helper(page).dblclick()", after)
    assert broken(after) == ["too-many-statements"]


def test_wrapping_statements_in_a_new_try_if_loop_or_with_is_refused():
    wrapped = {
        "try": "    try:\n        helper(page).click()\n    except Exception:\n        pass\n",
        "if": "    if page:\n        helper(page).click()\n",
        "for": "    for _ in range(1):\n        helper(page).click()\n",
        "while": "    while False:\n        helper(page).click()\n",
        "with": "    with page.expect_navigation():\n        helper(page).click()\n",
    }
    for text in wrapped.values():
        assert "compound-added" in broken(edited("    helper(page).click()\n", text)), text


def test_a_try_added_inside_an_existing_with_is_refused_too():
    with_before = BEFORE.replace(
        "    helper(page).click()\n", "    with page.expect_navigation():\n        helper(page).click()\n"
    )
    after = with_before.replace(
        "        helper(page).click()\n",
        "        try:\n            helper(page).click()\n        except Exception:\n            pass\n",
    )
    assert "compound-added" in broken(after, before=with_before)


def test_changing_the_fixtures_the_test_requests_is_refused():
    assert broken(edited("def test_x(cart, page):", "def test_x(page):")) == ["signature"]
    assert broken(edited("def test_x(cart, page):", "def test_x(cart, page, extra):")) == ["signature"]
    assert broken(edited("def test_x(cart, page):", "def test_x(cart, page) -> None:")) == ["signature"]


def test_changing_the_decorators_is_refused():
    assert broken(edited("def test_x(", "@pytest.mark.slow\ndef test_x(")) == ["decorators"]
    skipped = edited("def test_x(", "@pytest.mark.skip\ndef test_x(")
    assert "decorators" in broken(skipped)


def test_adding_a_skip_xfail_importorskip_or_exit_is_refused():
    for call in (
        "pytest.skip('x')",
        "pytest.xfail('x')",
        "pytest.importorskip('nope')",
        "pytest.exit('x')",
        "sys.exit(0)",
    ):
        after = edited("    helper(page).click()\n", f"    {call}\n")
        assert "skip-added" in broken(after), call


def test_replacing_a_check_with_a_statement_that_checks_nothing_is_refused():
    after = edited('    assert page.get_by_role("button", name="Pay").is_visible()\n', "    print('ok')\n")
    assert "assert-removed" in broken(after)
    after = edited('expect(page).to_have_url(lambda url: url.endswith("/cart"))', "print('ok')")
    assert "check-dropped" in broken(after)


def test_an_assert_turned_into_a_constant_is_refused():
    after = edited('assert page.get_by_role("button", name="Pay").is_visible()', "assert True")
    assert broken(after) == ["assert-constant"]


def test_an_assert_that_cannot_fail_is_refused():
    for trivial in ("True", "1", "(page, 'always true')", "page.title() == 'Cart' or True"):
        after = edited('assert page.get_by_role("button", name="Pay").is_visible()', f"assert {trivial}")
        assert "assert-constant" in broken(after), trivial


# --- the inputs -----------------------------------------------------------------------------------------------------


def test_a_file_that_does_not_parse_after_or_before_is_refused():
    assert broken("def test_x(:\n") == ["unparsable"]
    assert broken(BEFORE, before="def test_x(:\n") == ["unparsable"]


def test_a_repaired_test_that_is_gone_renamed_or_bound_twice_is_refused():
    assert broken(edited("def test_x(", "def test_x2(")) == ["repaired-test-missing"]
    assert broken(BEFORE + "\n\ndef test_x(cart, page):\n    assert 1\n") == ["repaired-test-missing"]
    assert broken(BEFORE, ("test_nope",)) == ["repaired-test-missing"]


def test_a_test_bound_twice_before_cannot_be_repaired():
    twice = BEFORE + "\n\ndef test_x(cart, page):\n    assert 1\n"
    assert broken(twice, before=twice) == ["repaired-test-missing"]


def test_no_tests_named_refuses_every_change():
    assert broken(BEFORE, ()) == ["repaired-test-missing"]


def test_function_source_is_the_tests_lines_with_its_decorators():
    text = "import pytest\n\n\n@pytest.mark.slow\ndef test_x(page):\n    assert 1\n\n\ndef test_y():\n    pass\n"
    assert function_source(text, "test_x") == "@pytest.mark.slow\ndef test_x(page):\n    assert 1"
    assert function_source(BEFORE, "TestCart.test_total").startswith("    def test_total(self, page):")
    assert function_source(text, "test_nope") is None and function_source("def test_x(:", "test_x") is None
