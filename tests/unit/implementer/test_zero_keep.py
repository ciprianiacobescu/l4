"""L4-IMP-061 (SCN-IMP-302): zeroing every public function keeps a function annotated to return a callable or a class,
because the zero value of a decorator factory is not a value a test can meet: it breaks the import of the module that
applies the decorator while its class body runs."""

import textwrap
from typing import Any

import pytest

from l4.implementer.stubs import zero_value_plan, zero_value_variant

SOURCE = textwrap.dedent(
    """\
    from typing import Any, Callable, TypeVar

    _F = TypeVar("_F", bound=Callable[..., Any])


    def traced(name: str) -> Callable[[_F], _F]:
        def decorate(fn: _F) -> _F:
            return fn

        return decorate


    def span_names(spans: list[str]) -> list[str]:
        return [f"span:{s}" for s in spans]
    """
)


def run(source: str) -> dict[str, Any]:
    namespace: dict[str, Any] = {}
    exec(compile(source, "<variant>", "exec"), namespace)  # noqa: S102 - the variant of a fixture
    return namespace


def test_scn_imp_302_a_decorator_factory_annotated_to_return_a_callable_keeps_its_body():
    plan = zero_value_plan(SOURCE, public=True)
    ns = run(plan.source)

    def f() -> None: ...

    assert ns["traced"]("x")(f) is f
    assert ns["span_names"](["a"]) == []
    assert plan.kept == ("traced",)
    assert "span_names" in plan.zeroed and "traced" not in plan.zeroed


@pytest.mark.parametrize(
    "annotation",
    [
        '"Callable[[_F], _F]"',
        "Callable[..., int] | None",
        "Optional[Callable[[], None]]",
        "type[Base]",
        "typing.Callable[..., Any]",
        "Callable",
        "Type[Base]",
    ],
)
def test_optional_and_string_annotations_are_kept(annotation: str):
    source = (
        "import typing\nfrom typing import Any, Callable, Optional, Type\n\n\nclass Base: ...\n\n\n"
        f"def make() -> {annotation}:\n    return Base\n"
    )
    plan = zero_value_plan(source, public=True)
    assert plan.kept == ("make",), annotation
    ns = run(plan.source)
    assert ns["make"]() is ns["Base"]


def test_a_non_callable_annotation_is_zeroed():
    plan = zero_value_plan("def f() -> list[int]:\n    return [1]\n\ndef g():\n    return 3\n", public=True)
    assert plan.kept == () and set(plan.zeroed) == {"f", "g"}


CLASS_SOURCE = textwrap.dedent(
    """\
    class Store:
        def add(self, a: int, b: int) -> int:
            return a + b

        def count(self) -> int:
            return 7
    """
)


def test_keep_leaves_a_named_method_real():
    plan = zero_value_plan(CLASS_SOURCE, public=True, keep={"Store.add"})
    store = run(plan.source)["Store"]()
    assert store.add(1, 2) == 3 and store.count() == 0
    assert plan.zeroed == ("Store.count",) and plan.kept == ()


def test_red_stub_mode_is_unchanged():
    source = (
        "from typing import Callable\n\n\ndef traced(name: str) -> Callable[[int], int]:\n"
        "    raise NotImplementedError\n"
    )
    plan = zero_value_plan(source, public=False)
    assert run(plan.source)["traced"]("x") is None
    assert plan.kept == ()
    assert zero_value_variant(source) == plan.source
