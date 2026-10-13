"""The red-phase stub guard (L4-IMP-002): HEAD plus admissible additions, never the agent's text patched in place."""

import ast
import subprocess
import sys
from collections.abc import Callable
from textwrap import dedent

import pytest

from l4.implementer.stubs import classify_red_changes, enforce_red_scope, has_stub, zero_value_variant

from .conftest import Bench

HEAD = dedent(
    '''\
    """Pricing."""

    from decimal import Decimal


    def total(prices: list[float]) -> float:
        return round(sum(prices), 2)


    class Cart:
        def __init__(self) -> None:
            self.items: list[float] = []

        def add(self, price: float) -> None:
            self.items.append(price)
    '''
)


def rebuilt(new: str, head: str = HEAD):
    out = classify_red_changes(head, dedent(new))
    ast.parse(out.source)  # whatever the guard returns is valid Python
    return out


def test_a_new_function_with_real_code_is_stubbed_and_head_bytes_are_kept():
    out = rebuilt(HEAD + "\n\ndef apply_discount(amount, code):\n    return amount * 0.9\n")
    assert out.source.startswith(HEAD.rstrip("\n"))
    assert out.source.rstrip().endswith("def apply_discount(amount, code):\n    raise NotImplementedError")
    assert out.stubs == ("apply_discount",) and "replaced by a stub" in out.restored[0]


def test_a_stub_the_agent_wrote_keeps_its_own_formatting():
    stub = (
        'def apply_discount(\n    amount: float,\n    code: str,\n) -> float:\n    """Doc."""\n'
        '    raise NotImplementedError("later")\n'
    )
    out = rebuilt(HEAD + "\n\n" + stub)
    assert stub in out.source and out.restored == ()


def test_changing_or_removing_existing_code_is_restored_byte_for_byte():
    changed = HEAD.replace("round(sum(prices), 2)", "sum(prices)").replace("self.items.append(price)", "pass")
    out = rebuilt(changed)
    assert out.source == HEAD
    assert any("total was changed" in r for r in out.restored)
    assert any("Cart.add was changed" in r for r in out.restored)
    assert rebuilt(HEAD.split("\n\nclass Cart")[0] + "\n").source == HEAD  # removing a whole class is restored too


def test_a_guarded_parameter_stub_is_admissible():
    new = HEAD.replace(
        "def total(prices: list[float]) -> float:\n",
        "def total(prices: list[float], rounding: str | None = None) -> float:\n"
        "    if rounding is not None:\n        raise NotImplementedError\n",
    )
    out = rebuilt(new)
    assert "if rounding is not None:" in out.source and "rounding: str | None = None" in out.source
    assert out.stubs == ("total (guard)",) and out.restored == ()


@pytest.mark.parametrize(
    "guard",
    [
        "if len(prices) > 0:\n        raise NotImplementedError",  # a call is behaviour
        "if rounding:\n        return 0.0",  # not a not-implemented statement
        "if rounding:\n        raise NotImplementedError\n    else:\n        pass",
        "if rounding == 'x':\n        raise NotImplementedError",  # a string literal
    ],
)
def test_a_guard_that_is_not_a_pure_flag_check_is_restored(guard: str):
    body = "    " + guard + "\n    return round(sum(prices), 2)\n"
    new = HEAD.replace(
        "def total(prices: list[float]) -> float:\n    return round(sum(prices), 2)\n",
        "def total(prices: list[float], rounding: str | None = None) -> float:\n" + body,
    )
    assert rebuilt(new).source == HEAD


@pytest.mark.parametrize(
    "signature",
    [
        "prices: list[float], rounding",  # no default
        "prices: list[float] = None, rounding=None",  # a default added to an existing parameter
        "rounding=None, prices: list[float] = ()",  # reordered
    ],
)
def test_changed_parameters_are_not_a_guarded_stub(signature: str):
    new = HEAD.replace(
        "def total(prices: list[float]) -> float:\n    return round(sum(prices), 2)\n",
        f"def total({signature}) -> float:\n    if rounding is not None:\n        raise NotImplementedError\n"
        "    return round(sum(prices), 2)\n",
    )
    assert rebuilt(new).source == HEAD


def test_a_guarded_stub_that_also_changes_the_body_is_restored():
    new = HEAD.replace(
        "def total(prices: list[float]) -> float:\n    return round(sum(prices), 2)\n",
        "def total(prices: list[float], rounding: str | None = None) -> float:\n"
        "    if rounding is not None:\n        raise NotImplementedError\n    return sum(prices)\n",
    )
    assert rebuilt(new).source == HEAD


def test_new_classes_keep_bases_and_plain_fields_but_lose_behaviour():
    new = HEAD + dedent(
        """


        class UnsupportedShippingCountry(Exception):
            pass


        def cached(fn):
            return fn


        @dataclass(frozen=True)
        class Rate:
            country: str
            cents: int = 500
            label = "x"

            @staticmethod
            def zero() -> "Rate":
                return Rate("", 0)

            @cached
            def label_for(self) -> str:
                return self.country.upper()
        """
    )
    out = rebuilt(new)
    tree = ast.parse(out.source)
    classes = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}
    assert ast.unparse(classes["UnsupportedShippingCountry"]).endswith("pass")
    rate = ast.unparse(classes["Rate"])
    assert rate.startswith("@dataclass(frozen=True)\nclass Rate")
    assert "cents: int" in rate and "500" not in rate and "label =" not in rate  # field values and bare attributes go
    assert "@staticmethod" in rate and "@cached" not in rate
    assert rate.count("raise NotImplementedError") == 2
    assert "return Rate" not in out.source and "cents * " not in out.source


def test_enum_members_are_declarations():
    out = rebuilt(HEAD + "\n\nclass Color(Enum):\n    RED = 1\n    BLUE = 2\n")
    assert "RED = 1" in out.source and "BLUE = 2" in out.source


def test_new_methods_go_to_the_end_of_their_class_and_the_rest_is_untouched():
    new = HEAD + "\n    def remove(self, price: float) -> None:\n        self.items.remove(price)\n"
    out = rebuilt(new)
    assert out.source == HEAD + "\n    def remove(self, price: float) -> None:\n        raise NotImplementedError\n"
    assert out.stubs == ("Cart.remove",)


def test_a_method_added_to_a_class_that_is_not_last_stays_inside_it():
    head = HEAD + "\n\ndef tail() -> int:\n    return 1\n"
    new = head.replace(
        "self.items.append(price)\n", "self.items.append(price)\n\n    def clear(self) -> None:\n        pass\n"
    )
    out = rebuilt(new, head=head)
    cart_end = out.source.index("def tail")
    assert out.source.index("def clear") < cart_end


def test_imports_and_all_entries_are_kept_and_module_values_are_dropped():
    head = HEAD + '\n__all__ = ["total"]\n'
    new = (
        head.replace('["total"]', '["total", "apply_discount"]').replace(
            "from decimal import Decimal", "from decimal import Decimal, ROUND_UP\nimport math"
        )
        + "\nCODES = {'A': 1}\n\ndef apply_discount(amount, code):\n    return amount\n"
    )
    out = rebuilt(new, head=head)
    assert "from decimal import Decimal, ROUND_UP" in out.source and "import math" in out.source
    assert '__all__ = ["total", "apply_discount"]' in out.source
    assert "CODES" not in out.source
    assert out.source.index("import math") < out.source.index("def total")


def test_removing_an_all_entry_is_restored():
    head = HEAD + '\n__all__ = ["total", "Cart"]\n'
    assert rebuilt(head.replace('"total", ', ""), head=head).source == head


def test_a_new_module_is_stubs_only_and_keeps_its_docstring_and_imports():
    out = classify_red_changes(
        "", 'import math\nX = 1\n\ndef f(x: int) -> int:\n    """Doc."""\n    return math.floor(x)\n'
    )
    assert out.source == 'import math\n\n\ndef f(x: int) -> int:\n    """Doc."""\n    raise NotImplementedError\n'
    assert out.stubs == ("f",)


# kiro-e2e H1 finding 3: kiro-cli's red module for task 2.1 (docs/live/kiro-e2e/h1/C/i001-repro/agent-written.py, plus
# its second stub, which uses Decimal). The rebuild joined its three isort sections and dropped the module docstring, so
# a file that passed ruff in Kiro's own run failed the lint gate (I001) and the attempt was blamed on the agent.
KIRO_NEW_MODULE = dedent(
    '''\
    """Bulk discount rule: 5% off line items with quantity >= 10."""

    from __future__ import annotations

    from decimal import Decimal

    from pricing.cart import LineItem


    def qualifies_for_bulk_discount(item: LineItem) -> bool:
        """Return True if the line item qualifies for bulk discount."""
        raise NotImplementedError


    def calculate_bulk_discount(item: LineItem) -> Decimal:
        """Return the bulk discount of the line item, rounded to 0.01 half-up."""
        raise NotImplementedError
    '''
)


def test_a_new_module_of_stubs_keeps_its_docstring_and_the_blank_lines_between_its_import_sections():
    out = classify_red_changes("", KIRO_NEW_MODULE)
    assert out.source == KIRO_NEW_MODULE
    assert out.restored == ()


def test_a_new_module_keeps_one_section_together_and_still_drops_its_values():
    new = dedent(
        '''\
        """Rates."""

        import math
        import os

        from pricing.cart import LineItem

        RATE = 5


        def f(item: LineItem) -> int:
            return math.floor(os.cpu_count() or RATE)
        '''
    )
    out = classify_red_changes("", new)
    assert out.source == dedent(
        '''\
        """Rates."""

        import math
        import os

        from pricing.cart import LineItem


        def f(item: LineItem) -> int:
            raise NotImplementedError
        '''
    )


def _ruff_findings(source: str, cwd) -> str:
    done = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "--isolated", "--select", "I,E,F", "--output-format", "concise",
         "--stdin-filename", "src/pricing/bulk_discount.py", "-"],
        input=source, capture_output=True, text=True, cwd=cwd, check=False,
    )  # fmt: skip
    return "" if done.returncode == 0 else done.stdout + done.stderr


def test_a_lint_clean_new_module_stays_lint_clean_after_the_rebuild(tmp_path):
    assert _ruff_findings(KIRO_NEW_MODULE, tmp_path) == ""  # the agent's file is clean
    assert _ruff_findings(classify_red_changes("", KIRO_NEW_MODULE).source, tmp_path) == ""


def test_unparsable_files_go_back_to_head():
    assert classify_red_changes(HEAD, "def broken(:\n").source == HEAD


def test_nothing_changed_is_nothing_to_report():
    out = classify_red_changes(HEAD, HEAD)
    assert out.source == HEAD and out.stubs == () and out.restored == ()


# --- zero-value variants -------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("annotation", "zero"),
    [
        ("str", '""'), ("int", "0"), ("float", "0.0"), ("bool", "False"), ("list[float]", "[]"),
        ("dict[str, int]", "{}"),
        ("set[int]", "set()"), ("tuple[int, ...]", "()"), ("bytes", 'b""'), ("List[str]", "[]"), ("'str'", '""'),
        ("Decimal", "None"), ("str | None", "None"), ("Optional[str]", "None"),
    ],
)  # fmt: skip
def test_zero_values_by_return_annotation(annotation: str, zero: str):
    out = zero_value_variant(f"def f(x) -> {annotation}:\n    raise NotImplementedError\n")
    assert out.strip().splitlines()[-1].strip() == ast.unparse(ast.parse(f"return {zero}"))


def test_unannotated_returns_none_and_none_annotated_does_nothing():
    out = zero_value_variant(
        "def f(x):\n    raise NotImplementedError\n\ndef g(x) -> None:\n    raise NotImplementedError\n"
    )
    assert "return None" in out and "def g(x) -> None:\n    pass" in out


def test_a_guarded_stub_gets_its_guard_body_replaced_and_real_code_is_kept():
    source = (
        "def total(prices, rounding: str | None = None) -> float:\n    if rounding is not None:\n"
        "        raise NotImplementedError\n    return round(sum(prices), 2)\n"
    )
    out = zero_value_variant(source)
    assert "if rounding is not None:\n        return 0.0" in out and "return round(sum(prices), 2)" in out


PARTIAL = (
    'def pick_priority(on_hand: int, reorder_point: int) -> str:\n    """Return urgency label for a pick item."""\n'
    "    if on_hand < 0 or reorder_point < 0:\n"
    '        raise ValueError("on_hand and reorder_point must be non-negative")\n'
    "    raise NotImplementedError\n"
)  # task 2.1 (validation) was implemented before task 1.1: guards, then the bare raise (live GitHub run, Kiro glm-5)


def test_a_partial_stub_keeps_its_guard_and_answers_the_zero_value_in_place_of_the_final_raise():
    out = zero_value_variant(PARTIAL)
    assert "raise ValueError('on_hand and reorder_point must be non-negative')" in out
    assert "NotImplementedError" not in out and out.strip().splitlines()[-1].strip() == "return ''"
    assert out.count("raise") == 1


def test_a_full_stub_is_unchanged_in_behaviour_next_to_a_partial_one():
    out = zero_value_variant("def f(x) -> int:\n    raise NotImplementedError\n\n" + PARTIAL)
    assert "def f(x) -> int:\n    return 0" in out and "NotImplementedError" not in out


def test_a_method_with_a_guard_then_the_raise_is_a_partial_stub():
    source = (
        "class Stock:\n    def reserve(self, n: int) -> bool:\n        if n < 0:\n            raise ValueError(n)\n"
        "        raise NotImplementedError('later')\n"
    )
    out = zero_value_variant(source)
    assert "raise ValueError(n)" in out and "NotImplementedError" not in out
    assert out.strip().splitlines()[-1].strip() == "return False"


@pytest.mark.parametrize(
    ("annotation", "zero"),
    [("int", "0"), ("bool", "False"), ("list[str]", "[]"), ("Thing | None", "None"), ("None", "pass")],
)
def test_a_partial_stub_zero_follows_the_return_annotation(annotation: str, zero: str):
    out = zero_value_variant(
        f"def f(x) -> {annotation}:\n    if x < 0:\n        raise ValueError\n    raise NotImplementedError()\n"
    )
    last = out.strip().splitlines()[-1].strip()
    assert "raise ValueError" in out and last == (zero if zero == "pass" else f"return {zero}")


def test_a_partial_stub_counts_as_a_stub_but_real_code_does_not():
    assert has_stub(PARTIAL)
    assert not has_stub("def f(x):\n    if x:\n        raise ValueError\n    return 1\n")


def test_methods_are_zeroed_and_docstrings_kept():
    source = 'class C:\n    def m(self) -> str:\n        """Doc."""\n        raise NotImplementedError\n'
    assert zero_value_variant(source).splitlines()[-1].strip() == "return ''"
    assert '"""Doc."""' in zero_value_variant(source)


def test_public_mode_zeroes_every_public_function_and_method_and_nothing_else():
    source = (
        "def total(prices) -> float:\n    return sum(prices)\n\ndef _hidden() -> int:\n    return 7\n\n"
        "class C:\n    def __init__(self):\n        self.x = 1\n\n    def count(self) -> int:\n        return self.x\n"
        "    def outer(self):\n        def inner():\n            return 1\n        return inner()\n"
    )
    out = zero_value_variant(source, public=True)
    assert "return 0.0" in out and "return 7" in out and "self.x = 1" in out
    assert "def count(self) -> int:\n        return 0" in out
    assert "def outer(self):\n        return None" in out


# --- the guard on a real worktree ------------------------------------------------------------------------------------


@pytest.fixture
def bench(make_bench: Callable[..., Bench]) -> Bench:
    return make_bench([])


def test_real_code_in_red_is_rebuilt_as_head_plus_stubs(bench: Bench):
    wb = bench.wb
    base = wb.head()
    pricing = wb.worktree / "src/pytdd/pricing.py"
    head_text = pricing.read_text()
    pricing.write_text(
        head_text.replace("round(sum(prices), 2)", "0")
        + "\n\ndef apply_discount(amount, code):\n    return amount * 0.9\n"
    )
    (wb.worktree / "tests").mkdir(exist_ok=True)
    (wb.worktree / "tests/test_new.py").write_text("def test_x():\n    assert False\n")
    (wb.worktree / "notes.txt").write_text("hello\n")
    task = wb.provider.tasks(wb.ref)[0]

    scope = enforce_red_scope(wb, task, base)

    text = pricing.read_text()
    assert text.startswith(head_text.rstrip("\n")) and "round(sum(prices), 2)" in text
    assert text.rstrip().endswith("raise NotImplementedError") and "amount * 0.9" not in text
    assert not (wb.worktree / "notes.txt").exists()
    assert (wb.worktree / "tests/test_new.py").exists()  # tests are the point of red
    assert scope.stub_files == ("src/pytdd/pricing.py",)
    assert scope.stubs == ("src/pytdd/pricing.py:apply_discount",)
    violations = bench.events("guard.violation")
    assert violations and all(v["phase"] == "red" for v in violations)
    assert {v["path"] for v in violations} == {"src/pytdd/pricing.py", "notes.txt"}
    purity = bench.events("stub.purity")[0]
    assert purity["task"] == task.key and purity["restored"] == len(scope.restored) == len(violations)


def test_a_deleted_production_file_is_restored(bench: Bench):
    wb = bench.wb
    base = wb.head()
    (wb.worktree / "src/pytdd/pricing.py").unlink()
    enforce_red_scope(wb, wb.provider.tasks(wb.ref)[0], base)
    assert (wb.worktree / "src/pytdd/pricing.py").read_text().startswith("def total")


def test_a_clean_step_records_stub_purity_without_violations(bench: Bench):
    wb = bench.wb
    scope = enforce_red_scope(wb, wb.provider.tasks(wb.ref)[0], wb.head())
    assert scope.restored == () and scope.stub_files == ()
    assert bench.events("guard.violation") == [] and len(bench.events("stub.purity")) == 1


def test_dependency_manifests_and_runner_config_are_not_production_code(bench: Bench):
    wb = bench.wb
    base = wb.head()
    (wb.worktree / "pyproject.toml").write_text((wb.worktree / "pyproject.toml").read_text() + "\n# dep\n")
    (wb.worktree / "uv.lock").write_text("lock\n")
    enforce_red_scope(wb, wb.provider.tasks(wb.ref)[0], base)
    assert "# dep" in (wb.worktree / "pyproject.toml").read_text() and (wb.worktree / "uv.lock").exists()


def test_a_stub_does_not_keep_a_default_or_annotation_that_reads_a_dropped_module_value():
    out = rebuilt(HEAD + "\nRATE = 3\nRateT = int\n\n\ndef f(x=RATE, *, y: RateT = 1, z=2) -> RateT:\n    return x\n")
    assert "RATE" not in out.source and "RateT" not in out.source
    assert "def f(x=None, *, y=1, z=2):" in out.source
    namespace: dict[str, object] = {}
    exec(compile(out.source, "<red>", "exec"), namespace)  # the rebuilt module imports without a NameError
    assert "f" in namespace and "f" in out.stubs
