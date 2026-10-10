import inspect

from l4.s1 import states as s
from l4.s1.questions import CHANGE_COVERED, FILE_RELEVANT, get_set

PROPOSAL = (
    "## Why\nA cart shows a total.\n\n## What Changes\n- Total with discount.\n\n## Impact\n- `src/shop/cart.py`\n"
)
INSTRUCTION = get_set(FILE_RELEVANT).questions[0].instructions
BUDGET = 300


def test_states_fit_budget_and_do_not_leak_their_label():
    spec = s.spec_summary("cart-totals", PROPOSAL)
    assert "Impact:\n- `src/shop/cart.py`" in spec and "A cart shows a total" not in spec
    huge_hunk = "\n".join(f"+    line {n} of a very long change" for n in range(400))
    file_state = s.file_state(
        spec, "src/inventory/stock.py", s.hunk_summary(huge_hunk), instruction=INSTRUCTION, budget=BUDGET
    )
    assert file_state.truncated and s.fits(file_state, INSTRUCTION, BUDGET)
    assert "Impact:\n- `src/shop/cart.py`" in file_state.text and "src/inventory/stock.py" in file_state.text
    for leak in ("out_of_scope", "not named", "unrelated", "verdict"):
        assert leak not in file_state.text

    tests = {
        "tests/test_cart.py": "from shop.cart import cart_total\n\ndef test_a():\n    assert cart_total([]) == 0\n"
    }
    mentions = s.static_mentions("Cart.cart_total", tests)
    assert mentions == ["tests/test_cart.py:1: from shop.cart import cart_total",
                        "tests/test_cart.py:4: assert cart_total([]) == 0"]  # fmt: skip
    instruction = get_set(CHANGE_COVERED).questions[0].instructions
    func = s.function_state(
        "src/shop/cart.py", "cart_total", "+def cart_total(items):\n+    return 0\n" * 80,
        [f"tests/test_cart.py::test_{n}" for n in range(60)], mentions * 20, instruction=instruction, budget=BUDGET,
    )  # fmt: skip
    assert func.truncated and s.fits(func, instruction, BUDGET)
    assert "def cart_total" in func.text  # the changed code is cut last
    for leak in ("executed", "missing", "covered", "uncovered", "percent", "%"):
        assert leak not in func.text
    assert set(inspect.signature(s.function_state).parameters) == {
        "path", "qualname", "changed", "test_names", "mentions", "instruction", "budget"
    }  # fmt: skip
    assert "coverage" not in " ".join(inspect.signature(s.file_state).parameters)


def test_tests_state_is_the_stated_sanity_question_and_small_states_are_not_cut():
    st = s.tests_state({"total": 9, "passed": 8, "failed": 1}, [("tests.test_a::test_x", "failed")],
                       instruction="Did every test of the run pass?", budget=BUDGET)  # fmt: skip
    assert (
        st.text
        == "Test run: 9 total, 8 passed, 1 failed, 0 errored, 0 skipped\n\nNew tests:\ntests.test_a::test_x: failed"
    )
    assert not st.truncated
    assert s.static_mentions("<module>", {"t.py": "x"}) == []
