"""L4-IMP-026: the zero-value variant of a generator or a context manager still behaves as one, so a test of it can
fail by assertion instead of by a `TypeError` before its body runs (SCN-IMP-216..218)."""

import textwrap

from l4.implementer.stubs import zero_value_variant

SOURCE = textwrap.dedent(
    """\
    import contextlib
    from collections.abc import Iterator
    from contextlib import contextmanager


    class Phase:
        def __init__(self) -> None:
            self.count = 0

        def set_count(self, n: int) -> None:
            self.count = n


    RECORDED: list[str] = []


    @contextmanager
    def search_phase(name: str) -> Iterator[Phase]:
        RECORDED.append(name)
        yield Phase()


    @contextlib.contextmanager
    def counted() -> Iterator[int]:
        yield 7


    def numbers() -> Iterator[int]:
        yield 1
        yield 2


    def opened(name: str) -> contextlib.AbstractContextManager[str]:
        return contextlib.nullcontext(name)
    """
)


def _module() -> dict:
    namespace: dict = {}
    exec(compile(zero_value_variant(SOURCE, public=True), "<zero>", "exec"), namespace)  # noqa: S102
    return namespace


def test_a_context_manager_enters_and_yields_the_zero_value():
    module = _module()
    with module["search_phase"]("fts") as phase:
        entered = True
    assert entered and phase is None  # a test can assert `phase is not None` and fail by assertion
    assert module["RECORDED"] == []  # the body is gone: nothing was recorded
    with module["counted"]() as value:
        assert value == 0


def test_an_exception_in_the_block_still_reaches_the_caller():
    module = _module()
    try:
        with module["search_phase"]("fts"):
            raise ValueError("boom")
    except ValueError as exc:
        assert str(exc) == "boom"
    else:  # pragma: no cover
        raise AssertionError("the block's exception was swallowed")


def test_a_generator_yields_nothing_and_a_returned_context_manager_is_a_null_one():
    module = _module()
    assert list(module["numbers"]()) == []
    with module["opened"]("x") as value:
        assert value is None


RED_STUBS = textwrap.dedent(
    """\
    from collections.abc import Iterator
    from contextlib import contextmanager


    class Phase:
        def set_count(self, n: int) -> None:
            raise NotImplementedError


    @contextmanager
    def search_phase(name: str, *, span: bool = True) -> Iterator[Phase]:
        raise NotImplementedError


    def numbers() -> Iterator[int]:
        raise NotImplementedError
    """
)


def test_a_red_stub_of_a_context_manager_or_a_generator_keeps_its_kind():
    """A red stub has no `yield`: the decorator and the annotation say what it is (the consumer's `search_phase`)."""
    namespace: dict = {}
    exec(compile(zero_value_variant(RED_STUBS), "<zero>", "exec"), namespace)  # noqa: S102
    with namespace["search_phase"]("fts") as phase:
        assert phase is None
    assert list(namespace["numbers"]()) == []
