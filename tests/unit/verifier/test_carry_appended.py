"""ui-carry-followup 2.1 (L4-VER-097, L4-VER-098, SCN-VER-416..420, 422, 424, 425): `appended_only` says whether a unit
only added whole new tests to a test file. Pure: two texts, the ids of the traced tests, the names of the head's report
and the facts of the diff. One case per row of the change's D4."""

import re

import pytest

from l4.implementer.test_locate import call_span, window
from l4.implementer.test_locate import test_names_of as names_in_file
from l4.verifier.carry_appended import FileFacts, Step1Run, appended_only, base_run_covers, is_closed

TS = "web/src/journey.test.ts"
PREFIX = "web.src.journey.test.ts::"
OK = FileFacts("M", 0)

HEADER = 'import { expect, test } from "vitest";\nimport { open } from "./journey";\n\n'


def old_block(n: int) -> str:
    return f'test("C-{n:08x} old test {n}", () => {{\n  expect(open({n})).toBe({n});\n}});\n'


def new_block(title: str = "C-0badf00d the new test", lines: int = 11) -> str:
    """One whole top-level test: 11 lines, a plain string title (the real shape of the motivating diff)."""
    body = "".join(f"  const v{i} = open({i});\n" for i in range(lines - 6))
    return f'test("{title}", () => {{\n{body}  // what it checks\n  expect(\n    open(0),\n  ).toBe(0);\n}});\n'


def flat(count: int = 15, *, new_at: int | None = None, new: str | None = None, tail: str = "const done = 1;\n") -> str:
    """A TypeScript file of `count` flat tests, a `const` after them, and `new` inserted before block `new_at`."""
    blocks = [old_block(n) for n in range(count)]
    if new is not None:
        blocks.insert(count if new_at is None else new_at, new)
    return HEADER + "\n".join(blocks) + "\n" + tail


def names_of(text: str) -> list[str]:
    """The names a reporter gives the tests of `text`: the strings of its `test(` and `it(` calls."""
    return re.findall(r"""^\s*(?:test|it)(?:\.\w+)*\(\s*["'`](.+?)["'`]""", text, re.M)


def accepts(base: str, head: str, traced: list[str] | None = None, *, path: str = TS, facts=OK, names=None) -> bool:
    traced = [f"{PREFIX}C-{n:08x} old test {n}" for n in (3, 7)] if traced is None else traced
    return appended_only(path, base, head, traced, names_of(head) if names is None else names, facts)


BASE = flat()


# -- SCN-VER-416: the real shape ------------------------------------------------------------------------------------


def test_scn_ver_416_one_new_test_block_between_two_old_ones_is_only_added_tests():
    block = new_block()
    assert len(block.splitlines()) == 11
    assert accepts(BASE, flat(new=block, new_at=8))


def test_scn_ver_416_at_the_end_of_the_file_and_before_the_first_test():
    assert accepts(BASE, flat(new=new_block()))
    assert accepts(BASE, flat(new=new_block(), new_at=0))


def test_scn_ver_416_a_test_between_the_last_test_and_a_const_after_them():
    head = flat(new=new_block(), tail="const done = 1;\n")
    assert head.index("the new test") < head.index("const done")
    assert accepts(BASE, head)


def test_scn_ver_416_a_new_test_at_the_end_of_a_describe():
    base = HEADER + 'describe("the journey", () => {\n' + "".join(
        f'  it("C-{n:08x} old test {n}", () => {{\n    expect(open({n})).toBe({n});\n  }});\n\n' for n in range(5)
    ) + "});\n"  # fmt: skip
    new = '  it("C-0badf00d the new test", () => {\n    expect(open(9)).toBe(9);\n  });\n'
    head = base.replace("});\n", new + "});\n") if base.endswith("});\n") else base
    head = base[: base.rindex("});")] + new + "});\n"
    traced = [f"{PREFIX}the journey C-{n:08x} old test {n}" for n in (1, 3)]
    names = [f"the journey {n}" for n in names_of(head)]
    assert accepts(base, head, traced, names=names)
    assert accepts(base, head, [f"{PREFIX}C-{n:08x} old test {n}" for n in (1, 3)])  # a reporter that skips describe


def test_scn_ver_416_blank_lines_around_the_new_test_do_not_matter():
    head = flat(new=new_block()).replace('\ntest("C-0badf00d', '\n\n\ntest("C-0badf00d')
    assert accepts(BASE, head)


# -- SCN-VER-417: a deleted or changed line anywhere keeps the hold --------------------------------------------------


@pytest.mark.parametrize("facts", [FileFacts("M", 1), FileFacts("M", None), FileFacts("A", 0), FileFacts("D", 0),
                                   FileFacts("R", 0), None])  # fmt: skip
def test_scn_ver_417_a_deleted_line_a_binary_file_or_a_status_other_than_modified_keeps_the_hold(facts):
    assert not accepts(BASE, flat(new=new_block()), facts=facts)


def test_scn_ver_417_a_line_the_head_lacks_is_caught_by_the_text_leg_too():
    head = flat(new=new_block()).replace("const done = 1;\n", "")  # numstat would say 1 deleted; the texts disagree too
    assert not accepts(BASE, head)
    assert not accepts(BASE, flat(new=new_block()).replace('import { expect, test } from "vitest";\n', ""))
    assert not accepts(BASE.replace("const done", "// kept\nconst done"), flat(new=new_block()))
    changed = flat(new=new_block()).replace("import { open }", "import { open, close }")  # a changed import
    assert not accepts(BASE, changed)


def test_scn_ver_417_a_changed_assertion_of_an_old_test_that_is_not_traced():
    head = flat(new=new_block()).replace("toBe(11)", "toBe(12)")
    assert not accepts(BASE, head)


# -- SCN-VER-418: a line added inside an old test keeps the hold -----------------------------------------------------


def test_scn_ver_418_a_line_added_inside_the_traced_test():
    head = flat(new=new_block()).replace("expect(open(3)).toBe(3);", "expect(open(3)).toBe(3);\n  expect(1).toBe(1);")
    assert not accepts(BASE, head)


def test_scn_ver_418_a_line_added_inside_another_old_test():
    head = flat(new=new_block()).replace("expect(open(5)).toBe(5);", "expect(open(5)).toBe(5);\n  expect(1).toBe(1);")
    assert not accepts(BASE, head)


def test_scn_ver_418_a_new_test_nested_inside_an_old_one():
    nested = '  test("C-0badf00d the nested new test", () => {\n    expect(1).toBe(1);\n  });\n'
    head = flat().replace("expect(open(3)).toBe(3);\n", "expect(open(3)).toBe(3);\n" + nested)
    assert not accepts(BASE, head)


# -- SCN-VER-419: an added line that is not a whole new test keeps the hold ------------------------------------------


@pytest.mark.parametrize(
    "added",
    [
        "beforeEach(() => {\n  reset();\n});\n",
        "afterAll(() => {\n  close();\n});\n",
        'import { reset } from "./reset";\n',
        "const shared = { id: 1 };\n",
        "function helper() {\n  return 1;\n}\n",
        'vi.mock("./journey", () => ({ open: () => 1 }));\n',
        "// a comment outside every test\n",
    ],
    ids=["beforeEach", "afterAll", "import", "constant", "helper", "vi.mock", "comment"],
)
def test_scn_ver_419_a_line_outside_the_tests_that_the_unit_added_keeps_the_hold(added):
    assert not accepts(BASE, flat(new=new_block() + "\n" + added, new_at=8))
    assert not accepts(BASE, flat(new=added))  # with no new test at all as well


def test_scn_ver_419_a_describe_that_wraps_the_new_test():
    wrapped = (
        'describe("a group", () => {\n' + "".join("  " + line + "\n" for line in new_block().splitlines()) + "});\n"
    )
    assert not accepts(BASE, flat(new=wrapped), names=names_of(wrapped))


def test_scn_ver_419_a_title_that_is_a_template_literal_has_no_block():
    template = new_block().replace('"C-0badf00d the new test"', "`C-0badf00d the ${kind} test`")
    assert not accepts(BASE, flat(new=template), names=["C-0badf00d the first test"])  # the report's name != the source
    assert not accepts(BASE, flat(new=template), names=["C-0badf00d the ${kind} test"])  # a literal name: no `["'` call


def test_scn_ver_419_an_each_table_that_the_report_names_differently():
    each = 'test.each([1, 2])("C-0badf00d case %i", (n) => {\n  expect(open(n)).toBe(n);\n});\n'
    assert not accepts(BASE, flat(new=each), names=["C-0badf00d case 1", "C-0badf00d case 2"])


# -- SCN-VER-420: a traced test whose block cannot be found once on each side keeps the hold -------------------------


def test_scn_ver_420_a_new_test_with_the_traced_tests_title_is_ambiguous():
    traced_title = "C-00000003 old test 3"
    head = flat(new=new_block(traced_title))
    assert not accepts(BASE, head)


def test_scn_ver_420_a_traced_test_declared_by_each_or_a_template_title_is_not_found():
    each = 'test.each([1, 2])("C-00000003 old test %i", (n) => {\n  expect(open(n)).toBe(n);\n});\n'
    base = flat().replace(old_block(3), each)
    head = flat(new=new_block()).replace(old_block(3), each)
    assert not accepts(base, head, [f"{PREFIX}C-00000003 old test 3"], names=names_of(head) + ["C-00000003 old test 3"])
    tpl = "test(`C-00000003 old test ${3}`, () => {\n  expect(open(3)).toBe(3);\n});\n"
    base, head = flat().replace(old_block(3), tpl), flat(new=new_block()).replace(old_block(3), tpl)
    assert not accepts(base, head, [f"{PREFIX}C-00000003 old test 3"], names=names_of(head) + ["C-00000003 old test 3"])


@pytest.mark.parametrize("breaker", ["  const text = 'it's open';\n", "  const jsx = <p>don't</p>;\n"])
def test_scn_ver_420_a_file_that_does_not_close_its_brackets_is_not_read(breaker):
    """An apostrophe in JSX text or an unbalanced string leaves a quote open: the traced block is not closed."""
    old = old_block(3).replace("  expect", breaker + "  expect")
    base, head = flat().replace(old_block(3), old), flat(new=new_block()).replace(old_block(3), old)
    assert not accepts(base, head)


def test_scn_ver_420_a_traced_test_whose_first_line_is_not_a_call_line():
    """`window` falls back to the first line that holds the name; that is no block (a helper call, a comment)."""
    helper = 'runCase("C-00000003 old test 3", () => {\n  expect(open(3)).toBe(3);\n});\n'
    base, head = flat().replace(old_block(3), helper), flat(new=new_block()).replace(old_block(3), helper)
    assert window(base, "C-00000003 old test 3") is not None  # `window` finds the helper line...
    assert call_span(base.splitlines(), "C-00000003 old test 3") is None  # ...and the carry does not take it
    assert not accepts(base, head)


# -- the traced tests must be in the old tests, and `names` are the head's report ------------------------------------


def test_every_traced_test_of_the_file_is_an_old_test_whatever_criterion_it_traces():
    assert not accepts(
        BASE, flat(new=new_block()), [f"{PREFIX}C-00000003 old test 3", f"{PREFIX}C-0badf00d the new test"]
    )
    assert not accepts(BASE, flat(new=new_block()), [])  # nothing traced is no carry


def test_a_name_the_head_report_does_not_have_leaves_its_lines_outside_and_they_differ():
    assert not accepts(
        BASE, flat(new=new_block()), names=[n for n in names_of(flat(new=new_block())) if "the new" not in n]
    )


# -- ids with a describe prefix against `window`'s reading of a name ------------------------------------------------

DESCRIBED = (
    'describe("checkout", () => {\n'
    '  it("applies the code", () => {\n    expect(1).toBe(1);\n  });\n'
    '  it("rejects the code", () => {\n    expect(2).toBe(2);\n  });\n'
    "});\n"
)


@pytest.mark.parametrize("name", ["checkout applies the code", "checkout > applies the code", "applies the code"])
def test_a_describe_prefix_of_the_reported_name_is_read_by_the_block_finder(name):
    lines = DESCRIBED.splitlines()
    assert call_span(lines, name) == (1, 4)  # the `it` block: from its call line to its closing line


def test_a_describe_titled_like_the_test_tells_them_apart_by_the_reported_name():
    lines = ('describe("same", () => {\n  it("same", () => {\n    expect(1).toBe(1);\n  });\n});\n').splitlines()
    assert call_span(lines, "same same") == (1, 4) and call_span(lines, "same > same") == (1, 4)  # the test
    assert call_span(lines, "same") == (0, 5)  # a reporter with no prefix reads the describe: a superset, never less


def test_two_sibling_tests_with_one_title_are_not_found():
    lines = 'it("same", () => {\n  a();\n});\nit("same", () => {\n  b();\n});\n'.splitlines()
    assert call_span(lines, "same") is None


# -- step 1's record -------------------------------------------------------------------------------------------------


def test_the_base_file_must_have_been_run_by_step_1_and_no_traced_test_failed_there():
    traced = [f"{PREFIX}C-00000003 old test 3"]
    ran = Step1Run(reverted=(TS,), passed=tuple(traced))
    assert base_run_covers(ran, TS, traced)
    assert not base_run_covers(None, TS, traced)  # step 1 did not run
    assert not base_run_covers(Step1Run(reverted=("web/src/other.test.ts",), passed=tuple(traced)), TS, traced)
    for field in ("failing", "not_run", "flaky"):
        assert not base_run_covers(Step1Run(reverted=(TS,), passed=tuple(traced), **{field: tuple(traced)}), TS, traced)
    assert base_run_covers(
        Step1Run(reverted=(TS,), passed=tuple(traced), failing=("web.src.other.test.ts::x",)), TS, traced
    )


# -- SCN-VER-422: other files and other languages --------------------------------------------------------------------


@pytest.mark.parametrize(
    "path", ["svc/pricing_test.go", "src/test/java/PricingTest.java", "Pricing.Tests/CartTests.cs"]
)
def test_scn_ver_422_a_language_other_than_javascript_typescript_and_python_keeps_the_file_level_rule(path):
    assert not accepts(BASE, flat(new=new_block()), path=path)


def test_scn_ver_422_an_unread_blob_keeps_the_hold():
    assert not appended_only(TS, None, flat(new=new_block()), [f"{PREFIX}x"], [], OK)
    assert not appended_only(TS, BASE, None, [f"{PREFIX}x"], [], OK)


@pytest.mark.parametrize("extension", ["ts", "tsx", "js", "jsx", "mjs", "cjs", "mts", "cts"])
def test_scn_ver_416_every_javascript_and_typescript_extension_is_read(extension):
    assert accepts(BASE, flat(new=new_block()), path=f"web/src/journey.test.{extension}")


# -- the block scanner -----------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,closed",
    [
        ('test("a", () => {\n  expect(1).toBe(1);\n});', True),
        ('test("a (", () => {\n  expect("}").toBe("}");\n});', True),  # a bracket in a string
        ("test('a', () => {\n  // ) unbalanced in a comment\n  /* } */\n});", True),
        ("test(`a`, () => {\n  const s = `x ${a + `${b}`} (`;\n});", True),  # a template with `${}` and a lone `(`
        ("test('a', () => {\n  const s = 'it's';\n});", False),  # a quote left open on its line
        ('test("a", () => {\n  expect(1).toBe(1);\n}', False),  # a missing `)`
        ('test("a", () => {\n  expect(1).toBe(1);\n}));', False),  # a negative count
        ("test(`a`, () => {\n  const s = `open;\n});", False),  # an unterminated template
        ('test("a", () => {\n  /* open \n});', False),  # an unterminated comment
    ],
)
def test_the_closed_block_scanner(text, closed):
    assert is_closed(text) is closed


# -- SCN-VER-424, 425: Python ----------------------------------------------------------------------------------------

PY = "tests/test_page.py"
PY_BASE = '''"""The page."""

import pytest

from page import render


def test_title():
    assert render("a") == "A"


def test_empty():
    assert render("") == ""


class TestFooter:
    def test_links(self):
        assert render("f") == "F"
'''


def py(base: str, head: str, traced: list[str] | None = None, *, facts=OK) -> bool:
    traced = traced if traced is not None else ["tests.test_page::test_title", "tests.test_page.TestFooter::test_links"]
    return appended_only(PY, base, head, traced, [], facts)


def test_scn_ver_424_a_new_function_and_a_new_method_of_an_old_class_are_only_added_tests():
    head = (
        PY_BASE.replace(
            "\n\nclass TestFooter:", '\n\ndef test_new():\n    assert render("n") == "N"\n\n\nclass TestFooter:'
        )
        + '\n    def test_other(self):\n        assert render("o") == "O"\n'
    )
    assert py(PY_BASE, head)
    assert py(PY_BASE, head, ["tests.test_page::test_title[a-b]"])  # a parametrised id names the function


def test_scn_ver_424_comment_and_blank_lines_the_unit_added_do_not_count():
    head = PY_BASE + '\n\n# the new one\ndef test_new():\n    assert render("n") == "N"\n'
    assert py(PY_BASE, head.replace('"""The page."""', '"""The page."""\n\n# a note'))


def test_scn_ver_425_a_new_test_with_an_old_tests_name_replaces_it_and_keeps_the_hold():
    head = PY_BASE + '\n\ndef test_title():\n    assert render("a") == "other"\n'
    assert not py(PY_BASE, head)
    assert not py(PY_BASE, head, ["tests.test_page::test_empty"])  # the old name is rebound whichever is traced
    method = PY_BASE + '\n    def test_links(self):\n        assert render("f") == "other"\n'
    assert not py(PY_BASE, method, ["tests.test_page::test_title"])


def test_scn_ver_425_a_new_test_named_like_a_non_test_binding_of_the_base_replaces_it():
    """`from helpers import test_shared` collects a test at the base; a `def test_shared` of the head replaces it, with
    the base's lines all there: only the rule that the name is bound by none at the base sees it."""
    base = PY_BASE.replace("from page import render", "from page import render\nfrom helpers import test_shared")
    head = base + "\n\ndef test_shared():\n    assert 1\n"
    assert not py(base, head)
    assert py(base, base + "\n\ndef test_fresh():\n    assert 1\n")  # the same base with a name that is free


def test_scn_ver_425_a_decorator_on_the_new_test():
    head = PY_BASE + '\n\n@pytest.mark.slow\ndef test_new():\n    assert render("n") == "N"\n'
    assert not py(PY_BASE, head)


def test_scn_ver_425_a_new_test_nested_in_an_old_one_or_in_a_class_that_is_not_module_level():
    nested = PY_BASE.replace(
        '    assert render("a") == "A"\n', '    assert render("a") == "A"\n\n    def test_inner():\n        assert 1\n'
    )
    assert not py(PY_BASE, nested)
    inner_class = PY_BASE + "\n\nclass TestNew:\n    def test_x(self):\n        assert 1\n"
    assert not py(PY_BASE, inner_class)  # a new class: its `class` line is a new line outside the new test


def test_scn_ver_425_a_changed_or_added_line_outside_the_new_test():
    new = '\n\ndef test_new():\n    assert render("n") == "N"\n'
    assert not py(PY_BASE, PY_BASE.replace('render("")', 'render("x")') + new)  # a changed line of an old test
    assert not py(PY_BASE, PY_BASE.replace("import pytest", "import pytest\nimport os") + new)  # a new import
    assert not py(PY_BASE, PY_BASE + "\nVALUE = 1\n" + new)  # a module-level statement
    assert not py(PY_BASE, new.join([PY_BASE, "\n\nVALUE = 1\n"]))


def test_scn_ver_425_a_name_bound_again_by_a_later_statement():
    head = PY_BASE + '\n\ndef test_new():\n    assert render("n") == "N"\n\n\ntest_new = None\n'
    assert not py(PY_BASE, head)


def test_scn_ver_425_a_file_that_does_not_parse_and_a_traced_test_that_is_gone_keep_the_hold():
    assert not py(PY_BASE, PY_BASE + "\ndef test_new(:\n")
    assert not py("def test_title(:\n", PY_BASE)
    assert not py(PY_BASE, PY_BASE.replace("def test_title", "def test_heading") + "\n\ndef test_x():\n    assert 1\n")


def test_a_blank_line_inside_a_triple_quoted_string_is_a_changed_line():
    base = 'DOC = """one\n\ntwo"""\n\n\ndef test_a():\n    assert DOC\n'
    head = 'DOC = """one\n\n\ntwo"""\n\n\ndef test_a():\n    assert DOC\n\n\ndef test_new():\n    assert 1\n'
    assert not appended_only(PY, base, head, ["tests.test_page::test_a"], [], OK)


def test_python_rule_needs_a_modified_file_with_no_deleted_line():
    head = PY_BASE + '\n\ndef test_new():\n    assert render("n") == "N"\n'
    assert py(PY_BASE, head)
    assert not py(PY_BASE, head, facts=FileFacts("M", 2))
    assert not py(PY_BASE, head, facts=FileFacts("A", 0))
    assert not py(PY_BASE, head, [])  # nothing traced


def test_the_names_of_a_file_in_a_report_are_read_through_file_of_id():
    """`test_locate.test_names_of` (moved from the red step): the part after the first `::` of the ids that lie in the
    file, whatever form the reporter gave the head."""
    ids = [f"{PREFIX}one", f"{PREFIX}two > three", "web.src.other.test.ts::x", "tests.test_page.TestA::test_y"]
    paths = [TS, "web/src/other.test.ts", "tests/test_page.py"]
    assert names_in_file(TS, ids, paths) == ["one", "two > three"]
    assert names_in_file("tests/test_page.py", ids, paths) == ["test_y"]
    assert names_in_file("web/src/none.test.ts", ids, paths) == []


# -- the facts and the blobs, read from a real repository (L4-VER-097 (a), SCN-VER-422) -------------------------------


@pytest.fixture
def repo(make_repo, raw, git_for):
    """`web/src/journey.test.ts` (the base's file), a binary file, a big one, a file to rename and one to delete."""
    path = make_repo("facts")

    class Repo:
        root, git = path, git_for(path)

        def write(self, name: str, data: str | bytes) -> None:
            target = path / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data if isinstance(data, bytes) else data.encode())

        def commit(self, message: str) -> str:
            raw(path, "add", "-A")
            raw(path, "commit", "-q", "-m", message)
            return raw(path, "rev-parse", "HEAD").strip()

    r = Repo()
    r.write(TS, BASE)
    r.write("web/src/binary.test.ts", b"\x00\x01\x02\n")
    r.write("web/src/gone.test.ts", "test('x', () => {});\n")
    r.write("web/src/moved.test.ts", BASE)
    r.write("web/src/exec.test.ts", "test('x', () => {});\n")
    r.base = r.commit("base")
    return r


def test_the_facts_of_a_diff_say_modified_added_deleted_binary_renamed_and_mode_changed(repo, raw):
    from l4.verifier.playwright import changed_file_facts

    repo.write(TS, flat(new=new_block()))  # +11 -0
    repo.write("web/src/binary.test.ts", b"\x00\x01\x02\x03\n")
    repo.write("web/src/new.test.ts", "test('y', () => {});\n")
    (repo.root / "web/src/gone.test.ts").unlink()
    (repo.root / "web/src/moved.test.ts").rename(repo.root / "web/src/moved2.test.ts")
    (repo.root / "web/src/exec.test.ts").chmod(0o755)
    head = repo.commit("the unit")
    facts = changed_file_facts(repo.git, repo.base, head)
    assert facts[TS] == FileFacts("M", 0)
    assert facts["web/src/new.test.ts"] == FileFacts("A", 0)
    assert facts["web/src/gone.test.ts"].status == "D"
    assert facts["web/src/binary.test.ts"] == FileFacts("M", None)
    assert facts["web/src/moved.test.ts"].status == "D" and facts["web/src/moved2.test.ts"].status == "A"  # no rename
    assert facts["web/src/exec.test.ts"].status == "T"  # a mode change is not a plain modification
    repo.write(TS, flat(new=new_block()).replace("const done = 1;\n", ""))
    assert changed_file_facts(repo.git, repo.base, repo.commit("a line less"))[TS] == FileFacts("M", 1)
    assert changed_file_facts(repo.git, "0" * 40, head) == {}  # git cannot say


def glue(repo, head, *, run=None, traced=None, reports=()):
    from l4.gates.junit import TestCase, TestReport
    from l4.verifier.carry_appended import AppendedFiles
    from l4.verifier.playwright import changed_file_facts

    ids = traced if traced is not None else [f"{PREFIX}C-00000003 old test 3"]
    report = TestReport({i: TestCase(i, "passed") for i in [*ids, *(f"{PREFIX}{n}" for n in reports)]})
    return AppendedFiles(
        repo.git, repo.base, head, run=run or Step1Run(reverted=(TS,), passed=tuple(ids)), files=dict.fromkeys(ids, TS),
        reports=[report, None], paths=lambda: [TS], facts=lambda: changed_file_facts(repo.git, repo.base, head),
    )  # fmt: skip


def test_the_glue_reads_git_decides_once_per_file_and_remembers_what_it_accepted(repo):
    repo.write(TS, flat(new=new_block()))
    head = repo.commit("the unit adds one test")
    only = glue(repo, head, reports=["C-0badf00d the new test"])
    test = f"{PREFIX}C-00000003 old test 3"
    assert only(test, TS) is True and only(test, TS) is True and only.accepted == {TS}
    assert glue(repo, head, run=Step1Run())(test, TS) is False  # step 1 did not run the base's file
    assert glue(repo, head, run=Step1Run(reverted=(TS,), passed=(test,), failing=(test,)))(test, TS) is False
    refused = glue(repo, head)  # the report of the head lacks the new test: its lines are outside every block
    assert refused(test, TS) is False and refused.accepted == set()


def test_scn_ver_422_a_binary_or_oversized_or_not_utf8_blob_keeps_the_hold(repo):
    from l4.verifier.carry_appended import MAX_BLOB_BYTES

    for data in (flat(new=new_block()) + "// é\n".encode("latin-1").decode("latin-1"), None):
        if data is None:
            continue
    repo.write(TS, flat(new=new_block()).encode() + b"\xff\xfe\n")  # not UTF-8
    head = repo.commit("not utf-8")
    assert glue(repo, head, reports=["C-0badf00d the new test"])(f"{PREFIX}C-00000003 old test 3", TS) is False
    big = flat(new=new_block()) + "// " + "x" * MAX_BLOB_BYTES + "\n"
    repo.write(TS, big)
    head = repo.commit("oversized")
    assert glue(repo, head, reports=["C-0badf00d the new test"])(f"{PREFIX}C-00000003 old test 3", TS) is False


# -- group 5 (review findings): F1, a new block is exactly one plain `it(` or `test(` statement ------------------------

N = "C-0badf00d the new test"


def with_new(text: str, *, at: int = 8) -> str:
    """`BASE` with `text` (lines, as written) before old block `at`."""
    return flat(new=text, new_at=at)


@pytest.mark.parametrize(
    "new",
    [
        f'it("{N}", () => {{}}); beforeEach(() => {{ counter = 5; }});\n',
        f'it("{N}", () => {{}}); vi.mock("./mod");\n',
        f'it("{N}", () => {{}}); counter = 5;\n',
        f'it("{N}", () => {{\n  expect(2).toBe(2);\n  }}); beforeEach(() => {{ counter = 5;\n}});\n',
        f'it("{N}", (counter = 7, () => {{}}));\n',
        f'it("{N}", (() => {{ counter = 9; return () => {{}}; }})());\n',
        f'it("{N}", () => {{}}, (counter = 4));\n',
        f'foo(); it("{N}", () => {{}});\n',
        f'it("{N}", () => {{}}) + (counter = 1);\n',
        f'it("{N}", () => {{\n  expect(2).toBe(2);\n}}).skip;\n',
        f'it.only("{N}", () => {{\n  expect(2).toBe(2);\n}});\n',
        f'it.skip("{N}", () => {{\n  expect(2).toBe(2);\n}});\n',
        f'test.todo("{N}");\n',
        f'it("{N}", (a = counter++) => {{\n  expect(2).toBe(2);\n}});\n',
        f'it("{N}", async ({{ page = open(1) }}) => {{\n  expect(2).toBe(2);\n}});\n',
        f'it("{N}", (a, b) => {{\n  expect(2).toBe(2);\n}});\n',
        f'it("{N}", () => expect(2).toBe(2));\n',
        f'it("{N}", {{ retry: 2 }}, () => {{\n  expect(2).toBe(2);\n}});\n',
        f'it("{N}", () => {{\n  expect(2).toBe(2);\n}}, {{ timeout: 5 }});\n',
        f"it(`{N} ${{kind}}`, () => {{\n  expect(2).toBe(2);\n}});\n",
        f'it("{N}" + suffix, () => {{\n  expect(2).toBe(2);\n}});\n',
        "it(title, () => {\n  expect(2).toBe(2);\n});\n",
        f'describe("{N}", () => {{\n  it("{N}", () => {{\n    expect(2).toBe(2);\n  }});\n}});\n',
        f'describe("{N}", () => {{\n  beforeEach(() => {{ counter = 5; }});\n  it("{N}", () => {{\n    a();\n  }});\n}});\n',  # noqa: E501
        f'if (flag)\nit("{N}", () => {{\n  expect(2).toBe(2);\n}});\n',
        f'foo(\nit("{N}", () => {{\n  expect(2).toBe(2);\n}})\n);\n',
        f'const x = [\nit("{N}", () => {{\n  expect(2).toBe(2);\n}}),\n];\n',
        f'it("{N}", () => {{\n  expect(2).toBe(2);\n}})\n(counter = 1);\n',
        f'it("{N}", () => {{\n  expect(2).toBe(2);\n}})\n.skip;\n',
    ],
    ids=[
        "hook-on-the-line",
        "vi.mock-on-the-line",
        "assignment-on-the-line",
        "hook-opened-on-the-closing-line",
        "default-argument-side-effect",
        "called-function-argument",
        "timeout-is-an-assignment",
        "code-before-the-it",
        "operator-after-the-call",
        "member-after-the-call",
        "it.only",
        "it.skip",
        "test.todo",
        "default-value-param",
        "destructured-default",
        "two-params",
        "expression-body",
        "options-object-second",
        "options-object-third",
        "template-title-with-expression",
        "concatenated-title",
        "variable-title",
        "describe-with-the-same-title",
        "describe-with-a-hook-and-the-same-title",
        "body-of-an-if",
        "argument-of-a-call",
        "element-of-an-array",
        "next-line-calls-it",
        "next-line-member",
    ],
)
def test_scn_ver_419_a_new_block_is_exactly_one_plain_it_or_test_statement(new):
    assert not accepts(BASE, with_new(new))


@pytest.mark.parametrize(
    "new",
    [
        f'it("{N}", () => {{\n  expect(2).toBe(2);\n}});\n',
        f'it("{N}", () => {{}});\n',
        f'it("{N}", () => {{\n  expect(2).toBe(2);\n}})\n',
        f'it("{N}", async () => {{\n  expect(2).toBe(2);\n}});\n',
        f'it("{N}", function () {{\n  expect(2).toBe(2);\n}});\n',
        f'it("{N}", async function named() {{\n  expect(2).toBe(2);\n}});\n',
        f'it("{N}", ({{ page }}) => {{\n  expect(2).toBe(2);\n}});\n',
        f'it("{N}", async ({{ page }}: Fixtures) => {{\n  expect(2).toBe(2);\n}});\n',
        f'it("{N}", async (ctx: TestContext) => {{\n  expect(2).toBe(2);\n}});\n',
        f'it("{N}", ctx => {{\n  expect(2).toBe(2);\n}});\n',
        f'it("{N}", () => {{\n  expect(2).toBe(2);\n}}, 5000);\n',
        f"it('{N}', () => {{\n  expect(2).toBe(2);\n}});\n",
        f"it(`{N}`, () => {{\n  expect(2).toBe(2);\n}});\n",
        f'it("{N}", () => {{\n  expect(2).toBe(2);\n}}); // why\n',
        f'it(\n  "{N}",\n  () => {{\n    expect(2).toBe(2);\n  }},\n);\n',
        f'it(\n  "{N}",\n  () => {{\n    expect(2).toBe(2);\n  }},\n  1000,\n);\n',
        f'test("{N}", () => {{\n  const text = "a ) }} ] and a (";\n  expect(text).toBe(text);\n}});\n',
        f'test("{N}", () => {{\n  const t = `a ${{b}} ) `;\n  expect(t).toBe(t);\n}});\n',
    ],
    ids=[
        "plain",
        "empty-body",
        "no-semicolon",
        "async-arrow",
        "function",
        "named-async-function",
        "destructured",
        "destructured-typed",
        "named-typed",
        "bare-param",
        "timeout",
        "single-quotes",
        "backtick-title",
        "trailing-comment",
        "prettier-multiline",
        "prettier-timeout",
        "brackets-in-strings",
        "template-body",
    ],
)
def test_scn_ver_416_a_plain_it_or_test_statement_is_a_new_block(new):
    assert accepts(BASE, with_new(new))
    assert accepts(BASE, with_new(new, at=0)) and accepts(BASE, flat(new=new))


@pytest.mark.parametrize("head", ["if (flag)", "for (const x of xs)", "for await (const x of xs)", "while (go)"])
def test_scn_ver_419_a_test_inserted_as_the_body_of_a_braceless_control_statement_keeps_the_hold(head):
    """The base's next line is the body of `<head>`; a plain `it(` inserted between them becomes that body."""
    base = BASE.replace("const done = 1;\n", f"{head}\n  done();\n")
    new = f'it("{N}", () => {{\n  expect(2).toBe(2);\n}});\n'
    assert not accepts(base, base.replace(f"{head}\n", f"{head}\n{new}"))
    assert accepts(base, base.replace(f"{head}\n", new + f"{head}\n"))  # before the head: a statement of its own


def test_scn_ver_416_a_plain_statement_inside_a_describe_and_after_one_without_a_semicolon():
    base = HEADER + 'describe("g", () => {\n  it("C-00000003 old test 3", () => {\n    expect(1).toBe(1);\n  })\n})\n'
    new = f'  it("{N}", () => {{\n    expect(2).toBe(2);\n  }})\n'
    head = base.replace("  })\n})\n", "  })\n" + new + "})\n")
    traced = [f"{PREFIX}g C-00000003 old test 3"]
    assert accepts(base, head, traced, names=[f"g {n}" for n in names_of(head)])


def test_scn_ver_419_a_block_in_a_template_literal_or_a_comment_is_not_a_block():
    block = f'it("{N}", () => {{\n  expect(2).toBe(2);\n}});\n'
    base = BASE.replace("const done = 1;\n", "const page = `\n<p>a</p>\n`;\nconst done = 1;\n")
    assert not accepts(base, base.replace("<p>a</p>\n", "<p>a</p>\n" + block))  # the constant's text changed
    assert not accepts(BASE, flat(new=f"/*\n{block}*/\n"))
    assert not accepts(BASE, flat(new=f"// {block}"))


def test_scn_ver_419_a_title_equal_to_a_describes_picks_the_it_never_the_describe():
    hook = "  beforeEach(() => { counter = 5; });\n"
    wrapped = f'describe("{N}", () => {{\n{hook}  it("{N}", () => {{\n    a();\n  }});\n}});\n'
    assert not accepts(BASE, flat(new=wrapped), names=[N])
    assert not accepts(BASE, flat(new=wrapped), names=[f"{N} {N}"])


def test_scn_ver_419_two_new_tests_that_one_name_cannot_tell_apart_keep_the_hold():
    block = f'it("{N}", () => {{\n  expect(2).toBe(2);\n}});\n'
    assert not accepts(BASE, flat(new=block + "\n" + block), names=[*names_of(BASE), N])
    assert accepts(BASE, flat(new=block + "\n" + block.replace(N, N + " b")), names=[*names_of(BASE), N, N + " b"])


# -- F4: a file is read once ------------------------------------------------------------------------------------------


def test_a_generated_file_of_3000_tests_is_decided_in_a_few_seconds():
    import time

    base = HEADER + "\n".join(old_block(n) for n in range(3000)) + "\nconst done = 1;\n"
    head = base.replace("const done", new_block() + "\nconst done")
    names = names_of(head)
    traced = [f"{PREFIX}C-{n:08x} old test {n}" for n in (3, 1500, 2999)]
    started = time.monotonic()
    assert appended_only(TS, base, head, traced, names, OK)
    assert time.monotonic() - started < 10, "a name is looked up in an index of the file, never found by a new scan"
    started = time.monotonic()
    assert not appended_only(
        TS, base, head.replace("const done", f'it("{N}", () => {{}}); x = 1;\nconst done'), traced, names, OK
    )
    assert time.monotonic() - started < 10


def test_a_generated_python_file_of_3000_tests_is_decided_in_a_few_seconds():
    import time

    base = "import pytest\n\n\n" + "\n\n".join(f"def test_{n}():\n    assert {n} == {n}\n" for n in range(3000))
    head = base + "\n\n" + "\n\n".join(f"def test_new_{n}():\n    assert {n}\n" for n in range(300))
    started = time.monotonic()
    assert appended_only(PY, base, head, ["tests.test_page::test_5", "tests.test_page::test_2999"], [], OK)
    assert time.monotonic() - started < 10


# -- F2: a coding declaration or a shebang is code ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "first",
    [
        "# coding: latin-1\n",
        "# -*- coding: latin-1 -*-\n",
        "#!/usr/bin/env python3\n",
        "# vim: set fileencoding=latin-1\n",
    ],
    ids=["coding", "emacs-style", "shebang", "fileencoding"],
)
def test_scn_ver_424_a_coding_declaration_or_a_shebang_added_on_line_one_or_two_keeps_the_hold(first):
    new = '\n\ndef test_new():\n    assert render("n") == "N"\n'
    assert not py(PY_BASE, first + PY_BASE + new)
    lines = PY_BASE.splitlines(keepends=True)
    if not first.startswith("#!"):  # a shebang is one on line 1 only; on line 2 it is a comment
        assert not py(PY_BASE, lines[0] + first + "".join(lines[1:]) + new)


def test_scn_ver_424_a_changed_or_removed_declaration_keeps_the_hold_and_an_equal_one_does_not():
    new = '\n\ndef test_new():\n    assert render("n") == "N"\n'
    cookie = "# -*- coding: utf-8 -*-\n"
    shebang = "#!/usr/bin/env python3\n"
    with_cookie = cookie + PY_BASE
    assert py(with_cookie, with_cookie + new)  # the same declaration on both sides
    assert not py(with_cookie, with_cookie.replace("utf-8", "latin-1") + new)
    assert not py(with_cookie, PY_BASE + new)
    assert py(shebang + PY_BASE, shebang + PY_BASE + new)
    assert not py(shebang + PY_BASE, shebang.replace("python3", "python2") + PY_BASE + new)
    assert not py(
        PY_BASE, PY_BASE.replace('"""The page."""', '"""The page."""\n# coding: x') + new
    )  # line 2: read as one


def test_scn_ver_424_a_plain_comment_on_line_one_is_still_dropped_and_a_late_cookie_looking_comment_too():
    new = '\n\ndef test_new():\n    assert render("n") == "N"\n'
    assert py(PY_BASE, "# a note\n" + PY_BASE + new)
    late = PY_BASE.replace("def test_title", "# coding: latin-1\ndef test_title")  # line 8: not a declaration
    assert py(PY_BASE, late + new)


# -- F3: a new Python test has a plain signature -----------------------------------------------------------------------


@pytest.mark.parametrize(
    "signature",
    [
        "def test_new(x=STATE.update(n=5)):",
        "def test_new(x=1):",
        "def test_new(*, x=1):",
        "def test_new(a, /, b=2):",
        "def test_new(a: STATE.update(n=5)):",
        "def test_new(a: (lambda: 1)()):",
        "def test_new(a: (b := 3)):",
        "def test_new(a: list[make()]):",
        "def test_new(a: int | None):",
        "def test_new(*args: f(), **kw):",
        "def test_new(**kw: f()):",
        "def test_new() -> STATE.update(n=5):",
        "def test_new() -> (lambda: 1)():",
        "async def test_new(x=f()):",
    ],
)
def test_scn_ver_425_a_default_value_or_a_computed_annotation_on_a_new_test_keeps_the_hold(signature):
    head = PY_BASE + f"\n\n{signature}\n    assert 1\n"
    assert not py(PY_BASE, head)
    method = PY_BASE + f"\n    {signature.replace('(', '(self, ', 1).replace('(self, )', '(self)')}\n        assert 1\n"
    assert not py(PY_BASE, method)


@pytest.mark.parametrize(
    "signature",
    [
        "def test_new():",
        "def test_new(db):",
        "def test_new(db, tmp_path):",
        "def test_new(db: Session) -> None:",
        "def test_new(db: orm.Session, n: int, *rest: str, **kw: bool) -> None:",
        "def test_new(db: dict[str, list[int]]) -> 'Result':",
        "def test_new(db: Optional['Session']) -> pytest.Item:",
        "def test_new(*, db: Session) -> None:",
        "async def test_new(db):",
    ],
)
def test_scn_ver_424_plain_fixture_parameters_and_annotations_stay_allowed(signature):
    assert py(PY_BASE, PY_BASE + f"\n\n{signature}\n    assert 1\n")


# -- F5: the traced tests must have passed in step 1's run -------------------------------------------------------------


def test_scn_ver_421_a_traced_test_absent_from_step_1s_passed_list_keeps_the_hold():
    traced = [f"{PREFIX}C-00000003 old test 3", f"{PREFIX}C-00000007 old test 7"]
    assert base_run_covers(Step1Run(reverted=(TS,), passed=tuple(traced)), TS, traced)
    assert base_run_covers(Step1Run(reverted=(TS,), passed=(*traced, "x::y")), TS, traced)
    assert not base_run_covers(Step1Run(reverted=(TS,), passed=(traced[0],)), TS, traced)  # one is missing
    assert not base_run_covers(Step1Run(reverted=(TS,), passed=()), TS, traced)
    assert not base_run_covers(Step1Run(reverted=(TS,)), TS, traced)  # the list is absent: fail closed
    assert Step1Run().passed is None
