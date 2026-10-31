"""own-test-repair (L4-IMP-091, design D3 "What the person reads"): the views of a held step show the lines that git and
Python count, not the ones `str.splitlines` counts, and the source view of a test shows the method its id names."""

from l4.implementer import held, held_patch
from l4.implementer.held import MAX_SOURCE_LINES, HeldCheck, RepairedTest, held_question

FF = "\x0c"
TWO_CLASSES = f'''"""A module."""
# see the docs {FF}{FF}


class TestA:
    def test_x(self):
        assert strong() == 42


class TestB:
    def helper(self):
        return 1

    def test_x(self):
        value = weak()
        assert value
'''
TB_X = "    def test_x(self):\n        value = weak()\n        assert value"
TA_X = "    def test_x(self):\n        assert strong() == 42"
NESTED = """class TestOuter:
    class TestInner:
        def test_x(self):
            assert inner()

    def test_x(self):
        assert outer()


def test_x():
    assert plain()
"""


def write(bench, name: str, text: str) -> None:
    path = bench.wb.worktree / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode())


# --- the source view of a Python test (SCN-IMP-480) -----------------------------------------------------------------


def test_the_source_view_of_a_method_is_all_of_it_whatever_the_form_feeds_before_it(make_bench):  # SCN-IMP-480
    bench = make_bench([])
    write(bench, "tests/test_cls.py", TWO_CLASSES)
    assert held_patch.test_source(bench.wb, "tests/test_cls.py::TestB::test_x") == TB_X
    assert held_patch.test_source(bench.wb, "tests/test_cls.py::TestA::test_x") == TA_X


def test_a_dotted_classname_id_names_its_class_too(make_bench):  # the form the JUnit reports write
    bench = make_bench([])
    write(bench, "tests/test_cls.py", TWO_CLASSES)
    assert held_patch.test_source(bench.wb, "tests.test_cls.TestB::test_x") == TB_X
    assert held_patch.test_source(bench.wb, "tests.test_cls.TestA::test_x") == TA_X


def test_a_nested_class_chain_and_a_plain_name_are_resolved(make_bench):
    bench = make_bench([])
    write(bench, "tests/test_n.py", NESTED)
    inner = "        def test_x(self):\n            assert inner()"
    assert held_patch.test_source(bench.wb, "tests/test_n.py::TestOuter::TestInner::test_x") == inner
    assert held_patch.test_source(bench.wb, "tests/test_n.py::TestOuter::test_x") == (
        "    def test_x(self):\n        assert outer()"
    )
    # a plain name keeps the first match of a walk from the top, as before
    assert held_patch.test_source(bench.wb, "tests/test_n.py::test_x") == "def test_x():\n    assert plain()"
    # a class that does not hold the method is no match: the view does not fall back to another class's method
    assert "assert strong()" not in held_patch.test_source(bench.wb, "tests/test_n.py::TestOther::test_x")


def test_the_digest_of_a_method_is_the_digest_of_the_method_the_id_names(make_bench):
    import hashlib

    bench = make_bench([])
    write(bench, "tests/test_cls.py", TWO_CLASSES)
    want = hashlib.sha256(TB_X.encode()).hexdigest()
    assert held_patch.source_digest(bench.wb, "tests/test_cls.py::TestB::test_x") == want


def test_a_parametrized_id_with_a_class_still_resolves(make_bench):
    bench = make_bench([])
    write(bench, "tests/test_cls.py", TWO_CLASSES)
    assert held_patch.test_source(bench.wb, "tests/test_cls.py::TestB::test_x[a-1]") == TB_X


def test_python_source_counts_lines_as_python_does():
    text = f"x = 1  # {FF}\r\n# a\rdef test_x():\r\n    assert 1\r\n"
    assert held_patch._python_source(text, "test_x") == "def test_x():\n    assert 1"


# --- the lines a question shows are the lines git has ---------------------------------------------------------------


def test_indented_shows_a_form_feed_inside_its_line_and_no_phantom_line():
    assert held._indented(f"a{FF}b\nc\n") == [f"    a{FF}b", "    c"]
    assert held._indented("a\r\nb\r\n") == ["    a", "    b"]
    assert held._indented("") == [] and held._indented("\n") == ["    "]


def test_cut_counts_the_lines_git_counts():
    text = "\n".join([f"line{FF}{n}" for n in range(MAX_SOURCE_LINES + 1)])
    shown = held_patch._cut(text)
    assert shown.endswith("[cut: 1 more lines]") and shown.count("\n") == MAX_SOURCE_LINES
    exact = "\n".join(f"a{FF}b" for _ in range(MAX_SOURCE_LINES))
    assert held_patch._cut(exact) == exact  # a form feed adds no line to the count


def test_a_failure_line_escapes_the_characters_a_view_does_not_show():
    message = "TypeError: bad\x0c call\u202e x\u200b y\x1b[31m z\x85"
    shown = RepairedTest("e2e.a::test_x", "e2e/a.py::test_x", "other", "e2e", message, "base")
    held_check = HeldCheck(
        "1.1", "green", "repair", (), ("e2e.a::test_x",), "why", runs=("test",), repaired=(shown,),
        patch=b"x", result="{}", patch_path=".l4/held/1.1-repair.patch",
    )  # fmt: skip
    context = held_question(held_check, {}, "ASKED").context
    line = next(ln for ln in context.split("\n") if "failed with other in the e2e gate" in ln)
    assert line.endswith(r"TypeError: bad\x0c call\u202e x\u200b y\x1b[31m z\x85")
    for char in "\x0c\u202e\u200b\x1b\x85":
        assert char not in context
