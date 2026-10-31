"""own-test-repair (L4-IMP-091, design D3 "What the person reads"): the views of a held step show the lines that git and
Python count, not the ones `str.splitlines` counts, and the source view of a test shows the method its id names."""

import hashlib

import pytest

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


def test_indented_spells_a_form_feed_inside_its_line_and_shows_no_phantom_line():
    assert held._indented(f"a{FF}b\nc\n") == [r"    a\x0cb", "    c"]
    assert held._indented("a\r\nb\r\n") == ["    a", "    b"]
    assert held._indented("") == [] and held._indented("\n") == ["    "]


def test_cut_counts_the_lines_git_counts():
    text = "\n".join([f"line{FF}{n}" for n in range(MAX_SOURCE_LINES + 1)])
    shown = held_patch._cut(text)
    assert shown.endswith("[cut: 1 more lines]") and shown.count("\n") == MAX_SOURCE_LINES
    exact = "\n".join(f"a{FF}b" for _ in range(MAX_SOURCE_LINES))
    assert held_patch._cut(exact) == "\n".join(r"a\x0cb" for _ in range(MAX_SOURCE_LINES))  # no line is added


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


# --- the characters a view does not show, by Unicode class (design D3; SCN-IMP-479, SCN-IMP-484) ---------------------

# what a list missed (the review's character probe) and what the class rule names; each is refused in a line of code
HIDDEN = [
    0x00, 0x08, 0x0B, 0x0C, 0x1B, 0x7F, 0x85, 0x9F,  # controls
    0xA0, 0x202F, 0x2000, 0x3000,  # spaces other than U+0020
    0xAD, 0x2061, 0x2064, 0x206A, 0x206F, 0x180E, 0xFFF9, 0x1BCA0, 0xE0001, 0xE0041,  # format characters
    0x2028, 0x2029, 0x061C, 0x200B, 0x200F, 0x202A, 0x202E, 0x2060, 0x2066, 0x2069,  # separators, bidi, zero-width
    0xE000, 0x0378,  # private use, unassigned
    0x034F, 0x115F, 0x1160, 0x17B4, 0x17B5, 0x180B, 0x180D, 0x180F, 0x3164, 0xFE00, 0xFE0F, 0xFFA0,  # printable
    0xE0100, 0xE01EF, 0x2800,  # default-ignorable characters that `isprintable()` accepts
]  # fmt: skip


@pytest.mark.parametrize("code", HIDDEN, ids=lambda c: f"U+{c:04X}")
def test_every_character_of_the_class_rule_is_named_in_a_line_of_code(code):  # SCN-IMP-479
    text = f"    assert 'na{chr(code)}n' not in str(value)\n"
    assert held.unshown_in(text) == f"U+{code:04X}"
    assert chr(code) not in held.escape_unshown(text)


def test_the_escapes_are_two_four_or_eight_digits_by_the_size_of_the_code_point():
    assert held.escape_unshown("a\x0cb\xadc\x7fd") == r"a\x0cb\xadc\x7fd"
    assert held.escape_unshown("a\u202eb\u3164c\ufe0f") == r"a\u202eb\u3164c\ufe0f"
    assert held.escape_unshown("a\U000e0041b\U0001bca0c\U000e0100") == r"a\U000e0041b\U0001bca0c\U000e0100"


@pytest.mark.parametrize(
    "text",
    [
        "plain ascii\twith a tab\nand two lines\n",
        "line one\r\nline two\r\n",  # a carriage return directly before a newline is a line end
        "\ufeffimport os\n",  # one byte order mark at the very start
        'label = "Înapoi" # 日本語 ✓ ünï — “quoted” 😀\n',
        "",
        "\n\n",
    ],
)
def test_text_a_view_shows_as_it_is_is_not_named(text):
    assert held.unshown_in(text) is None


@pytest.mark.parametrize(
    ("text", "named"),
    [
        ("a\rb\n", "U+000D"),  # a lone carriage return
        ("a\r", "U+000D"),  # one at the end of a text with no newline after it
        ("a\r\r\nb", "U+000D"),  # the first of two is lone
        ("a\ufeffb", "U+FEFF"),  # a byte order mark that is not at the start
        ("\ufeff\ufeffa", "U+FEFF"),  # the second one
        ("ok\n\ufeffa", "U+FEFF"),  # at the start of a later line
        ("x\xa0y", "U+00A0"),
    ],
)
def test_a_carriage_return_not_before_a_newline_and_a_misplaced_byte_order_mark_are_named(text, named):
    assert held.unshown_in(text) == named


def test_the_first_character_of_the_class_is_the_one_named_and_a_big_file_is_read_whole():
    assert held.unshown_in("a\u200bb\xadc") == "U+200B"
    big = "def test_x():\n    assert value == 1  # ünï\n" * 20_000
    assert held.unshown_in(big) is None
    assert held.unshown_in(big + "\U000e0041") == "U+E0041"


def test_a_line_shown_to_a_person_spells_a_carriage_return_and_a_leading_byte_order_mark_too():
    assert held.escape_unshown("a\rb\r\n\ufeff") == r"a\x0db\x0d" + "\n" + r"\ufeff"
    assert held.escape_unshown("a\tb\nc") == "a\tb\nc"
    assert held.escape_unshown("Înapoi ✓") == "Înapoi ✓"


# --- a shown line keeps its place: through a held question of check `tests` (SCN-IMP-484, SCN-IMP-483) ---------------

CR_TESTS = (
    "from pytdd.pricing import total\n\n\ndef test_total_of_two():\n"
    "    # one\r# two\u00ad<b>\n    assert total([1.0, 2.0]) == 3.0\n"
)


def hold_tests_chore(make_bench, monkeypatch, step_text: str, *, autocrlf: bool = False):
    """A test chore whose discrimination runs cannot decide: held, and the loop raises its question."""
    from l4.agents.fake import Step
    from l4.implementer import loop, tdd
    from l4.implementer.discrimination import ExtraRun

    from .conftest import result
    from .test_criterion_tests_chore import BOUND, run_bound

    monkeypatch.setattr(
        tdd,
        "discriminate_extra",
        lambda wb, tests, base, **kw: ExtraRun(inconclusive=dict.fromkeys(tests, "did not run in test-extra-zero")),
    )
    bench, first = run_bound(make_bench, Step(writes={"tests/test_more.py": step_text}, structured=result("single")))
    assert first.status == "held" and first.held is not None and first.held.check == "tests", first.reason
    if autocrlf:
        bench.wb.git.run("config", "core.autocrlf", "input")  # the operator's repository config
    [qid] = loop._raise_held(bench.wb, BOUND, first.held, 1)
    return bench, qid


def test_a_line_with_a_lone_carriage_return_and_a_soft_hyphen_is_shown_once_inside_its_block(
    make_bench, monkeypatch
):  # SCN-IMP-484
    bench, qid = hold_tests_chore(make_bench, monkeypatch, CR_TESTS)
    raw = (bench.wb.ref.path / "questions.md").read_bytes()
    section = raw.split(f"## {qid}".encode(), 1)[1].decode()
    shown = [ln for ln in section.split("\n") if "# two" in ln]
    # every line of it is indented, as a block line is (`_block` puts a backslash before a line that reads as markup)
    assert all(ln.removeprefix("\\").startswith("    ") for ln in shown), shown
    assert r"    +    # one\x0d# two\xad<b>" in shown  # the diff line, once, the characters spelled
    assert "\r" not in section and "\xad" not in section


def test_a_held_patch_is_committed_byte_for_byte_whatever_the_repository_says_about_line_ends(
    make_bench, monkeypatch
):  # SCN-IMP-483, check `tests`
    crlf = CR_TESTS.replace("\r", "").replace("\n", "\r\n")
    bench, _ = hold_tests_chore(make_bench, monkeypatch, crlf, autocrlf=True)
    [raised] = bench.events("question.raised")
    rel = held_patch.held_rel(bench.wb, "1.2", "tests", "patch")
    on_disk = (bench.wb.worktree / rel).read_bytes()
    in_commit = bench.wb.git.run_bytes("show", f"HEAD:{rel}")
    assert b"\r\n" in on_disk and in_commit == on_disk  # the patch holds the file's CRLF line ends, committed as is
    assert hashlib.sha256(in_commit).hexdigest() == raised["patch_sha256"]


# --- the suppressions a repair question lists (SCN-IMP-482) ----------------------------------------------------------


def repair_with(suppressions: list[dict]) -> HeldCheck:
    import json

    return HeldCheck(
        "1.1", "green", "repair", (), ("tests.test_flow::test_x",), "why", runs=("test",),
        repaired=(RepairedTest("tests.test_flow::test_x", "tests/a.py::test_x", "other", "test", "m", "zero_value"),),
        patch=b"x", result=json.dumps({"suppressions": suppressions}), patch_path=".l4/held/1.1-repair.patch",
    )  # fmt: skip


def test_a_suppression_is_listed_with_its_file_line_rule_and_reason():
    context = held_question(
        repair_with([{"file": "tests/a.py", "line": 7, "rule": "E501", "reason": "long"}]), {}, "A"
    ).context
    assert "\n    tests/a.py:7 E501: long\n" in context


def test_a_suppression_is_one_bounded_line_with_its_characters_spelled():
    reason = "first\nsecond\u00ad\r" + "x" * 900
    context = held_question(
        repair_with([{"file": "tests/a.py", "line": 7, "rule": "E501", "reason": reason}]), {}, "A"
    ).context
    [line] = [ln for ln in context.split("\n") if ln.startswith("    tests/a.py:7")]
    assert line.startswith(r"    tests/a.py:7 E501: first\nsecond\xad\x0dxxx") and "[line cut:" in line
    assert len(line) < 450 and "\u00ad" not in context and "\r" not in context


def test_at_most_twenty_suppressions_are_listed_and_the_rest_counted():
    many = [{"file": "tests/a.py", "line": n, "rule": "E501", "reason": "r"} for n in range(1, 24)]
    context = held_question(repair_with(many), {}, "A").context
    assert "tests/a.py:20 E501" in context and "tests/a.py:21 E501" not in context
    assert "    ... 3 more suppressions\n" in context


def test_a_repair_without_suppressions_or_with_an_unreadable_result_lists_none():
    for result in ("", "{}", "not json", "[]", '{"suppressions": "x"}', '{"suppressions": [1, "a"]}'):
        held_check = repair_with([])
        context = held_question(HeldCheck(**{**held_check.__dict__, "result": result}), {}, "A").context
        assert "Suppressions the agent declared" not in context, result
