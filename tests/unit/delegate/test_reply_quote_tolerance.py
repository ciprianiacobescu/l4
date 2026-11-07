"""A `checked` quote that the file holds is placed by the harness, and the bold of a markdown file is not compared
(delegate-quote-tolerance; L4-DLG-005; SCN-DLG-134 to SCN-DLG-143). Every case is at the `check_reply` level."""

from l4.delegate.reply import Discarded, HeadTree, Kept

from .test_reply import FILES, HARNESS_REASON, UNIT_REL, check, cite, reply, short_quote

DESIGN = f"{UNIT_REL}/design.md"
SENTENCE = "Run the migration check before you merge, and name the table it touched."
SENTENCE_LINE = 63
LIMIT = "The limit is twenty entries per reply."


def lines_of(count: int, put: dict[int, str]) -> str:
    """`count` lines, `filler n` unless `put` gives the line."""
    return "\n".join(put.get(n, f"filler {n}") for n in range(1, count + 1)) + "\n"


def with_files(files: dict[str, str]) -> HeadTree:
    """The unit head of the reply tests with `files` added (every file tracked and regular)."""
    every = {**FILES, **files}
    return HeadTree({p: True for p in every}, lambda p: every.get(p), UNIT_REL)


def run(tmp_path, head: HeadTree, *entries):
    return check(tmp_path, reply(checked=list(entries)), head=head)


def not_resolved(got, ref: str) -> None:
    assert isinstance(got, Discarded), got
    assert got.reason == f"checked {ref} does not resolve" and got.retryable and got.status == "discarded"


def placed_at(got, *where: str | None) -> None:
    """`got` is kept, and its entries carry `resolved` as `where` says (None: no key)."""
    assert isinstance(got, Kept), got
    assert [e.get("resolved") for e in got.checked] == list(where)


AGENTS = with_files({"AGENTS.md": lines_of(70, {SENTENCE_LINE: SENTENCE})})


# -- the exactly-one rule (L4-DLG-005; SCN-DLG-134 to SCN-DLG-137) ----------------------------------------------------


def test_a_quote_the_file_holds_once_resolves_at_its_real_line(tmp_path):  # SCN-DLG-134
    entry = cite("AGENTS.md:1", SENTENCE)
    got = run(tmp_path, AGENTS, entry)
    assert isinstance(got, Kept)
    assert got.checked == ({**entry, "resolved": "AGENTS.md:63"},)  # ref, quote and claim as the delegate wrote them
    for ref in ("AGENTS.md:1-5", "AGENTS.md:500"):  # a range, and a line past the end of the file
        got = run(tmp_path, AGENTS, cite(ref, SENTENCE))
        placed_at(got, "AGENTS.md:63")
        assert got.checked[0]["ref"] == ref


def test_a_quote_before_the_window_is_placed_at_that_earlier_line(tmp_path):
    head = with_files({"AGENTS.md": lines_of(70, {5: SENTENCE})})  # nothing from line 57 on holds it
    placed_at(run(tmp_path, head, cite("AGENTS.md:60", SENTENCE)), "AGENTS.md:5")


def test_a_quote_the_file_holds_twice_off_the_line_does_not_resolve(tmp_path):  # SCN-DLG-135
    head = with_files({"AGENTS.md": lines_of(70, {20: SENTENCE, SENTENCE_LINE: SENTENCE})})
    not_resolved(run(tmp_path, head, cite("AGENTS.md:1", SENTENCE)), "AGENTS.md:1")
    placed_at(run(tmp_path, head, cite("AGENTS.md:61", SENTENCE)), None)  # within three lines of 63: the cited line


def test_overlapping_occurrences_count_as_two(tmp_path):
    head = with_files({"notes.txt": lines_of(40, {30: "ab ab ab ab ab ab ab"})})  # str.count finds one, offsets 0 and 3
    not_resolved(run(tmp_path, head, cite("notes.txt:20", "ab ab ab ab ab")), "notes.txt:20")


def test_a_quote_that_only_another_file_holds_does_not_resolve(tmp_path):  # SCN-DLG-136
    head = with_files({"AGENTS.md": lines_of(70, {}), "docs/guide.md": lines_of(30, {12: SENTENCE})})
    not_resolved(run(tmp_path, head, cite("AGENTS.md:1", SENTENCE)), "AGENTS.md:1")


def test_a_quote_within_the_window_keeps_its_cited_line(tmp_path):  # SCN-DLG-137
    head = with_files({"AGENTS.md": lines_of(100, {42: SENTENCE, 90: SENTENCE})})
    placed_at(run(tmp_path, head, cite("AGENTS.md:40", SENTENCE)), None)


def test_a_quote_four_lines_off_is_placed_at_its_line(tmp_path):  # SCN-DLG-16, the single-copy cases
    for ref in ("src/pkg/store.py:46", "src/pkg/store.py:38"):
        placed_at(run(tmp_path, with_files({}), cite(ref, "return hash_password(raw, cost=12)")), "src/pkg/store.py:42")


def test_an_entry_that_resolves_today_is_kept_with_no_resolved_key(tmp_path):
    store = FILES["src/pkg/store.py"] + "    return hash_password(raw, cost=12)\n"  # the quote again, far below
    head = with_files({"src/pkg/store.py": store})
    placed_at(run(tmp_path, head, cite("src/pkg/store.py:42", "return hash_password(raw, cost=12)")), None)


def test_only_a_path_line_entry_placed_by_the_file_gets_resolved(tmp_path):
    entries = [
        cite("AGENTS.md:1", SENTENCE),  # placed
        cite("AGENTS.md:63", SENTENCE),  # as cited
        cite("spec:design.md#D3", "Use bcrypt with cost 12."),
        cite("test:tests/test_store.py::test_add", ""),
    ]
    got = run(tmp_path, AGENTS, *entries)
    placed_at(got, "AGENTS.md:63", None, None, None)
    assert got.checked[0] == {**entries[0], "resolved": "AGENTS.md:63"}
    assert got.checked[1:] == tuple(entries[1:])


def test_the_refusals_stay_when_the_quote_is_in_the_file_once_far_from_the_line(tmp_path):
    head = with_files(
        {
            "link.py": "import os, sys",
            "questions.md": lines_of(70, {SENTENCE_LINE: SENTENCE}),
            "AGENTS.md": lines_of(70, {SENTENCE_LINE: "short one"}),
        }
    )
    head = HeadTree({**head.tracked, "link.py": False}, head.read, UNIT_REL)  # a symlink: tracked, not regular
    not_resolved(run(tmp_path, head, cite("link.py:1", "import os, sys")), "link.py:1")
    got = run(tmp_path, head, cite("questions.md:1", SENTENCE))
    assert isinstance(got, Discarded) and got.reason == f"checked questions.md:1 {HARNESS_REASON}"
    assert not got.retryable
    got = run(tmp_path, head, cite("AGENTS.md:1", "short one"))
    assert isinstance(got, Discarded) and got.reason == short_quote("AGENTS.md:1")


# -- the line of a match (design D2) ------------------------------------------------------------


def test_the_line_of_a_match_counts_blank_lines_and_removed_markers(tmp_path):
    put = {
        2: "",
        3: "**Bold** lead in the line",
        4: "",
        5: "",
        6: "More **strong** and __kept__ text here",
        40: "The **only** gate is the test run, and nothing else.",
    }
    head = with_files({"docs/guide.md": lines_of(50, put)})
    got = run(tmp_path, head, cite("docs/guide.md:1", "The only gate is the test run, and nothing else."))
    placed_at(got, "docs/guide.md:40")
    # the same line, found as written
    placed_at(run(tmp_path, head, cite("docs/guide.md:1", "The **only** gate is the test run, and nothing else.")),
              "docs/guide.md:40")  # fmt: skip


def test_the_line_of_a_match_after_lines_that_fold_to_nothing(tmp_path):
    fill = "".join(f"filler {n}\n" for n in range(1, 48))
    head = with_files(
        {
            "AGENTS.md": "\n\n" + SENTENCE + "\n" + fill,  # two blank lines first: the match starts at offset 0
            "docs/first.md": "**\nThe **only** gate is the test run, and nothing else.\n"
            + fill,  # `**` folds to nothing
        }
    )
    placed_at(run(tmp_path, head, cite("AGENTS.md:40", SENTENCE)), "AGENTS.md:3")
    placed_at(run(tmp_path, head, cite("docs/first.md:40", "The only gate is the test run, and nothing else.")),
              "docs/first.md:2")  # fmt: skip


def test_the_placed_line_is_counted_by_line_feeds_only(tmp_path):
    # a form feed, a vertical tab and a lone carriage return split `str.splitlines()` but not git or an editor
    text = lines_of(30, {5: "x = 1\x0c", 6: "y = 2\x0b", 7: "z = 3\rw = 4", 10: SENTENCE})
    head = with_files({"src/app.py": text})
    placed_at(run(tmp_path, head, cite("src/app.py:25", SENTENCE)), "src/app.py:10")


def test_a_dot_slash_path_records_the_normalised_path(tmp_path):
    got = run(tmp_path, AGENTS, cite("./AGENTS.md:1", SENTENCE))
    placed_at(got, "AGENTS.md:63")
    assert got.checked[0]["ref"] == "./AGENTS.md:1"


def test_the_line_of_a_match_in_a_file_with_crlf_line_ends(tmp_path):
    text = lines_of(50, {30: SENTENCE}).replace("\n", "\r\n")
    head = with_files({"AGENTS.md": text, "docs/guide.md": text.replace(SENTENCE, "A **bold** " + SENTENCE)})
    placed_at(run(tmp_path, head, cite("AGENTS.md:1", SENTENCE)), "AGENTS.md:30")
    placed_at(run(tmp_path, head, cite("docs/guide.md:1", "A bold " + SENTENCE)), "docs/guide.md:30")


def test_a_wrapped_quote_is_placed_at_the_line_where_it_starts(tmp_path):
    text = lines_of(50, {30: "a sentence that wraps", 31: "    over two lines of the file."})
    head = with_files({"docs/guide.md": text})
    placed_at(run(tmp_path, head, cite("docs/guide.md:2", "a sentence that wraps over two lines of the file.")),
              "docs/guide.md:30")  # fmt: skip


def test_a_markdown_quote_is_placed_only_when_it_is_alone_as_written_and_folded(tmp_path):
    # once plain and once in bold: once as written, twice once the bold is dropped, so no place is certain
    mixed = lines_of(80, {60: LIMIT, 70: "The **limit** is twenty entries per reply."})
    not_resolved(run(tmp_path, with_files({"docs/guide.md": mixed}), cite("docs/guide.md:1", LIMIT)), "docs/guide.md:1")
    # twice as written
    twice = lines_of(80, {60: LIMIT, 70: LIMIT})
    not_resolved(run(tmp_path, with_files({"docs/guide.md": twice}), cite("docs/guide.md:1", LIMIT)), "docs/guide.md:1")
    # twice as written, once folded: the quote sits inside `**bold words stand here` and again in `a *bold ...`
    inside = lines_of(80, {20: "**bold words stand here", 60: "a *bold words stand here"})
    not_resolved(run(tmp_path, with_files({"g.md": inside}), cite("g.md:1", "*bold words stand here")), "g.md:1")
    # once as written and once folded (the same place): placed; once folded only: placed
    alone = lines_of(80, {60: LIMIT})
    placed_at(run(tmp_path, with_files({"docs/guide.md": alone}), cite("docs/guide.md:1", LIMIT)), "docs/guide.md:60")
    bold = lines_of(80, {60: "The **limit** is twenty entries per reply."})
    placed_at(run(tmp_path, with_files({"docs/guide.md": bold}), cite("docs/guide.md:1", LIMIT)), "docs/guide.md:60")
    # a file that is not markdown holds the bold as text: only the written form is compared
    code = lines_of(80, {60: LIMIT, 70: "The **limit** is twenty entries per reply."})
    placed_at(run(tmp_path, with_files({"docs/guide.txt": code}), cite("docs/guide.txt:1", LIMIT)), "docs/guide.txt:60")


# -- markdown bold (L4-DLG-005; SCN-DLG-138 to SCN-DLG-143) --------------------------------------------------

BOLD = "**`parseRef(ref, hook?)`**: `undefined` `U`"
PLAIN = "`parseRef(ref, hook?)`: `undefined` `U`"


def test_a_spec_quote_without_the_bold_of_the_file_resolves(tmp_path):  # SCN-DLG-138
    head = with_files({DESIGN: lines_of(12, {10: BOLD})})
    for quote in (PLAIN, BOLD):
        got = run(tmp_path, head, cite("spec:design.md", quote))
        placed_at(got, None)
    # and a quote that adds the bold to a file that has none
    head = with_files({DESIGN: lines_of(12, {10: PLAIN})})
    placed_at(run(tmp_path, head, cite("spec:design.md", BOLD)), None)


def test_a_markdown_path_line_quote_without_the_bold_resolves(tmp_path):  # SCN-DLG-139
    text = lines_of(30, {10: "The limit is **twenty** entries per reply."})
    head = with_files({"docs/guide.md": text, DESIGN: text})
    for path in ("docs/guide.md", DESIGN):
        placed_at(run(tmp_path, head, cite(f"{path}:10", LIMIT)), None)  # as cited
        placed_at(run(tmp_path, head, cite(f"{path}:1", LIMIT)), f"{path}:10")  # placed by the file


def test_the_markdown_suffix_is_matched_without_regard_to_case(tmp_path):
    text = lines_of(30, {10: "The limit is **twenty** entries per reply."})
    head = with_files({"docs/GUIDE.MD": text, "docs/notes.markdown": text})
    placed_at(run(tmp_path, head, cite("docs/GUIDE.MD:10", LIMIT)), None)
    placed_at(run(tmp_path, head, cite("docs/notes.markdown:1", LIMIT)), "docs/notes.markdown:10")


def test_backticks_and_single_markers_stay_significant(tmp_path):  # SCN-DLG-140
    text = lines_of(
        20,
        {
            10: BOLD,
            11: "Call `_snake_case_name_` from the loader.",
            12: "The *only* rule that holds here.",
            13: "Call `__init__` from the loader.",
            14: "The __limit__ is twenty entries per reply.",
        },
    )
    head = with_files({"docs/guide.md": text})
    for quote in (
        "parseRef(ref, hook?): undefined U",
        "Call `snake_case_name` from the loader.",
        "The only rule that holds here.",
        "Call `init` from the loader.",  # `__` is not folded: a dunder name stays distinct
        LIMIT,
    ):
        for line in (10, 1):
            not_resolved(run(tmp_path, head, cite(f"docs/guide.md:{line}", quote)), f"docs/guide.md:{line}")
    placed_at(run(tmp_path, head, cite("docs/guide.md:11", "Call `_snake_case_name_` from the loader.")), None)
    placed_at(run(tmp_path, head, cite("docs/guide.md:13", "Call `__init__` from the loader.")), None)


def test_a_quote_that_differs_by_more_than_the_bold_does_not_resolve(tmp_path):  # SCN-DLG-141
    head = with_files({DESIGN: lines_of(12, {10: BOLD})})
    not_resolved(run(tmp_path, head, cite("spec:design.md", "`parseRef(ref, hook)`: `undefined` `U`")),
                 "spec:design.md")  # fmt: skip
    not_resolved(run(tmp_path, head, cite(f"{DESIGN}:10", "`parseRef(ref, hook)`: `undefined` `U`")), f"{DESIGN}:10")


def test_the_bold_is_folded_in_markdown_files_only(tmp_path):  # SCN-DLG-142
    head = with_files(
        {
            "src/app.py": "import os\n\ndef build(**kwargs):\n    return kwargs\n",
            f"{UNIT_REL}/schema.json": '{"note": "**keep** this value as written"}\n',
        }
    )
    not_resolved(run(tmp_path, head, cite("src/app.py:3", "def build(kwargs):")), "src/app.py:3")
    not_resolved(run(tmp_path, head, cite("spec:schema.json", "keep this value as written")), "spec:schema.json")
    placed_at(run(tmp_path, head, cite("src/app.py:3", "def build(**kwargs):")), None)  # as written, it does


def test_a_quote_that_is_only_markers_matches_nothing(tmp_path):  # SCN-DLG-143
    head = with_files({"docs/guide.md": lines_of(20, {5: "Note: see the table", 6: "---"})})
    for quote in ("************", "****** ******"):  # folds to the empty string, a substring of every file
        not_resolved(run(tmp_path, head, cite("docs/guide.md:5", quote)), "docs/guide.md:5")
    head = with_files({DESIGN: lines_of(20, {5: "Note: see the table"})})
    not_resolved(run(tmp_path, head, cite("spec:design.md", "************")), "spec:design.md")
    # the folded form `Note: see` has 9 characters: the quote is compared as written only
    not_resolved(run(tmp_path, head, cite("spec:design.md", "**Note:** see")), "spec:design.md")
    not_resolved(run(tmp_path, head, cite(f"{DESIGN}:5", "**Note:** see")), f"{DESIGN}:5")
