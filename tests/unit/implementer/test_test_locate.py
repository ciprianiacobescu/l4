"""A test id is followed to its file in any language, and a test's own lines are found in a file that is not Python
(test-file-reach 1.1, L4-IMP-065, SCN-IMP-413, SCN-IMP-414)."""

from l4.implementer.test_locate import file_of_id, window

PATHS = [
    "deploy/seed.py",
    "src/pricing/total.test.ts",
    "src/pricing/total.v2.test.ts",
    "src/cart/total.test.ts",
    "tests/test_x.py",
    "tests/test_total.py",
    "pkg/total_test.go",
    "src/pricing/total.py",  # a Python file of the same stem as the TypeScript test, one directory up, and at the root
    "src/pricing.py",
    "src.py",
]


def test_the_head_as_a_path_is_found():
    assert file_of_id("src/pricing/total.test.ts::C-0a1b2c3d total of two prices", PATHS) == "src/pricing/total.test.ts"


def test_a_dotted_python_module_is_found_by_its_longest_prefix():
    assert file_of_id("tests.test_x.TestY::test_z", PATHS) == "tests/test_x.py"
    assert file_of_id("tests.test_total::test_total", PATHS) == "tests/test_total.py"


def test_a_dotted_typescript_head_with_dots_in_the_file_name_is_found():
    assert file_of_id("src.pricing.total.v2.test.ts::C-0a1b2c3d total", PATHS) == "src/pricing/total.v2.test.ts"
    assert file_of_id("src.pricing.total.test.ts::C-0a1b2c3d total of two prices", PATHS) == "src/pricing/total.test.ts"


def test_a_head_below_the_repository_root_is_found_when_one_file_ends_with_it():
    assert file_of_id("pricing.total.test.ts::total", PATHS) == "src/pricing/total.test.ts"


def test_two_matches_give_none_unless_exactly_one_is_preferred():
    assert file_of_id("total.test.ts::total", PATHS) is None
    assert file_of_id("total.test.ts::total", PATHS, preferred=["src/cart/total.test.ts"]) == "src/cart/total.test.ts"
    assert (
        file_of_id("total.test.ts::total", PATHS, preferred=["src/cart/total.test.ts", "src/pricing/total.test.ts"])
        is None
    )
    assert file_of_id("total.test.ts::total", PATHS, preferred=["deploy/seed.py"]) is None


def test_a_file_that_is_not_there_and_a_double_colon_inside_the_test_name():
    assert file_of_id("lib.nowhere.test.ts::total", PATHS) is None
    assert file_of_id("src/pricing/total.test.ts::total::adds", PATHS) == "src/pricing/total.test.ts"
    assert file_of_id("", PATHS) is None


def test_the_head_is_never_split_to_guess_a_path():
    """`total.test` is not a prefix of a path: only whole paths are compared."""
    assert file_of_id("src.pricing.total.test::x", ["src/pricing/total.test.ts"]) is None


def test_an_exact_dotted_path_wins_over_a_python_module_that_is_a_prefix_of_it():
    """`src.pricing.total.test.ts` is the TypeScript file, not the module `src.pricing.total` beside it."""
    assert file_of_id("src.pricing.total.test.ts::x", PATHS) == "src/pricing/total.test.ts"
    assert file_of_id("src.pricing.total.v2.test.ts::x", PATHS) == "src/pricing/total.v2.test.ts"
    assert file_of_id("tests.test_x.TestY::test_z", PATHS) == "tests/test_x.py"  # no exact match: the module walk


def test_two_exact_matches_give_none_unless_exactly_one_is_preferred():
    paths = ["a/b.ts", "a.b/ts", "a.py"]
    assert file_of_id("a.b.ts::x", paths) is None
    assert file_of_id("a.b.ts::x", paths, preferred=["a.b/ts"]) == "a.b/ts"
    assert file_of_id("a.b.ts::x", paths, preferred=["a/b.ts", "a.b/ts"]) is None


def test_the_ending_match_comes_after_the_python_module_walk():
    """A head below the root is tried as a module first, then as the end of a path."""
    assert file_of_id("pricing.total.test.ts::x", PATHS) == "src/pricing/total.test.ts"
    assert file_of_id("test_x.TestY::z", PATHS + ["test_x.py"]) == "test_x.py"


TS = """\
import { total } from "./total";

describe("total", () => {
  it("adds", () => {
    expect(total([1, 2])).toBe(3);
  });

  it("subtracts", () => {
    expect(total([3, -1])).toBe(2);
  });
});

test("C-0a1b2c3d total of two prices", () => {
  const prices = [1.5, 2.5];
  expect(total(prices)).toBe(4);
});

test.only("only one", () => {
  expect(1).toBe(1);
});

it.skip("skipped one", () => {
  expect(2).toBe(2);
});

test.each([[1, 2]])("each one", (a, b) => {
  expect(a + b).toBe(3);
});

describe.skip("skipped block", () => {
  it("inside", () => {});
});
"""


def lines(text: str | None) -> list[str]:
    assert text is not None
    return text.splitlines()


def test_a_top_level_test_call_runs_to_its_closing_line_and_not_to_the_next_test():
    got = lines(window(TS, "C-0a1b2c3d total of two prices"))
    assert got[0].startswith('test("C-0a1b2c3d total of two prices"') and got[-1] == "});"
    assert len(got) == 4 and "expect(total(prices)).toBe(4);" in got[-2]


def test_an_it_inside_a_describe_is_found_by_its_name_joined_with_a_space_or_an_arrow():
    for name in ("total > adds", "total adds", "adds"):
        got = lines(window(TS, name))
        assert got == ['  it("adds", () => {', "    expect(total([1, 2])).toBe(3);", "  });"], name
    assert lines(window(TS, "total subtracts"))[0] == '  it("subtracts", () => {'


def test_a_describe_block_is_a_test_call_too():
    got = lines(window(TS, "total"))
    assert got[0] == 'describe("total", () => {' and got[-1] == "});" and len(got) == 9


def test_the_longest_literal_that_ends_the_name_wins():
    text = 'it("adds", () => {\n  a();\n});\n\nit("total adds", () => {\n  b();\n});\n'
    assert lines(window(text, "total adds")) == ['it("total adds", () => {', "  b();", "});"]


def test_a_literal_that_is_only_the_end_of_a_word_does_not_name_the_test():
    text = 'it("ds", () => {\n  a();\n});\n\nit("adds", () => {\n  b();\n});\n'
    assert lines(window(text, "adds"))[0] == 'it("adds", () => {'


def test_only_skip_and_each_calls_are_found():
    assert lines(window(TS, "only one"))[-1] == "});"
    assert lines(window(TS, "skipped one"))[1] == "  expect(2).toBe(2);"
    assert lines(window(TS, "each one"))[1] == "  expect(a + b).toBe(3);"
    assert lines(window(TS, "skipped block"))[0] == 'describe.skip("skipped block", () => {'


def test_a_go_test_function_runs_to_its_closing_brace():
    go = (
        'package pkg\n\nfunc TestTotal(t *testing.T) {\n\tif Total(1, 2) != 3 {\n\t\tt.Fatal("x")\n\t}\n}\n\n'
        "func TestOther(t *testing.T) {\n}\n"
    )
    assert lines(window(go, "TestTotal")) == [
        "func TestTotal(t *testing.T) {",
        "\tif Total(1, 2) != 3 {",
        '\t\tt.Fatal("x")',
        "\t}",
        "}",
    ]


def test_a_block_longer_than_forty_lines_is_given_whole_for_the_caller_to_cut():
    body = "".join(f"  expect(f({n})).toBe({n});\n" for n in range(60))
    got = lines(window(f'test("long one", () => {{\n{body}}});\ntest("next", () => {{}});\n', "long one"))
    assert len(got) == 62 and got[-1] == "});"


def test_a_name_with_no_call_falls_back_to_the_first_line_that_holds_it():
    text = "const cases = [\n  'weird name',\n];\nrun('weird name');\n"
    assert lines(window(text, "weird name"))[0] == "  'weird name',"


def test_a_missing_name_gives_none():
    assert window(TS, "no such test") is None
    assert window("", "x") is None
    assert window(TS, "") is None


def test_the_last_lines_of_a_file_end_the_block_too():
    assert lines(window('test("last", () => {\n  expect(1);\n', "last")) == ['test("last", () => {', "  expect(1);"]


TEMPLATE = """\
test("with a fixture", () => {
  const text = `
first line
}
  indented line
`;
  expect(parse(text)).toBe(1);
});

test("next one", () => {
  expect(2).toBe(2);
});
"""


def test_a_line_at_column_zero_inside_an_unclosed_template_literal_does_not_end_the_block():
    got = lines(window(TEMPLATE, "with a fixture"))
    assert got[0] == 'test("with a fixture", () => {' and got[-1] == "});"
    assert "  expect(parse(text)).toBe(1);" in got and len(got) == 8
    assert lines(window(TEMPLATE, "next one"))[1] == "  expect(2).toBe(2);"


def test_quotes_backticks_and_escapes_do_not_open_a_template():
    text = (
        "test(\"has a '`' in a string\", () => {\n  const a = '`';\n  const b = \"`\";\n  const c = `x\\`y`;\n"
        '  expect(1).toBe(1);\n});\n\ntest("after", () => {\n  expect(2).toBe(2);\n});\n'
    )
    got = lines(window(text, "has a '`' in a string"))
    assert got[-1] == "});" and len(got) == 6


TWO_DESCRIBES = """\
describe("a", () => {
  it("adds", () => {
    expect(1).toBe(1);
  });
});

describe("b", () => {
  it("adds", () => {
    expect(2).toBe(2);
  });
});

describe("x", () => {
  describe("inner", () => {
    it("deep", () => {
      expect(3).toBe(3);
    });
  });
});

describe("y", () => {
  describe("inner", () => {
    it("deep", () => {
      expect(4).toBe(4);
    });
  });
});
"""


def test_equal_literals_in_two_describe_blocks_are_told_apart_by_the_enclosing_names():
    assert "expect(1)" in window(TWO_DESCRIBES, "a > adds")
    assert "expect(2)" in window(TWO_DESCRIBES, "b adds")
    assert "expect(2)" in window(TWO_DESCRIBES, "b > adds")
    assert "expect(3)" in window(TWO_DESCRIBES, "x > inner > deep")
    assert "expect(4)" in window(TWO_DESCRIBES, "y inner deep")


def test_equal_literals_that_the_name_does_not_tell_apart_give_none():
    assert window(TWO_DESCRIBES, "adds") is None
    assert window(TWO_DESCRIBES, "inner deep") is None
    assert window(TWO_DESCRIBES, "c > adds") is None
    assert window('it("same", () => {\n});\nit("same", () => {\n});\n', "same") is None
