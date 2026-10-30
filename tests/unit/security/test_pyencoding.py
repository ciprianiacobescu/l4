"""L4-SEC-042: the declared source encoding of a Python file (`tokenize.detect_encoding`), as the harness reads it."""

import pytest

from l4.security.pyencoding import (
    COOKIE_PREFIX_BYTES,
    UNREADABLE,
    declared_encoding,
    is_python_file,
    non_utf8,
    resolve_links,
)

PLAIN = b"def f():\n    return 1\n"


@pytest.mark.parametrize(
    "data",
    [
        PLAIN,
        b"# -*- coding: utf-8 -*-\n" + PLAIN,
        b"# coding=UTF8\n" + PLAIN,
        b"#!/usr/bin/env python\n# vim: set fileencoding=utf_8 :\n" + PLAIN,
        b"\xef\xbb\xbf" + PLAIN,  # a byte-order mark
        b"\xef\xbb\xbf# coding: utf-8\n" + PLAIN,
        "# café\n".encode() + PLAIN,
        b"",
    ],
    ids=["none", "cookie", "alias", "shebang+cookie", "bom", "bom+cookie", "utf8-text", "empty"],
)
def test_utf8_sources_are_not_flagged(data):
    assert non_utf8(data) is None
    assert declared_encoding(data) in ("utf-8", "utf-8-sig")


@pytest.mark.parametrize(
    ("data", "name"),
    [
        (b"# coding: utf-7\n" + PLAIN, "utf-7"),
        (b"#!/usr/bin/env python\n# -*- coding: latin-1 -*-\n" + PLAIN, "iso-8859-1"),  # tokenize's normalized name
        (b"# coding: utf-16\n" + PLAIN, "utf-16"),
        (b"# coding: cp1252\n" + PLAIN, "cp1252"),
        (b"# comment\r# coding: utf-7\r" + PLAIN, "utf-7"),  # CR-only line ends: the compiler translates them first
        (b"# comment\r\n# coding: utf-7\r\n" + PLAIN, "utf-7"),
    ],
)
def test_another_declared_encoding_is_reported_by_name(data, name):
    assert declared_encoding(data) == name
    assert non_utf8(data) == name


@pytest.mark.parametrize(
    "data",
    [
        b"# coding: no-such-codec\n" + PLAIN,
        b"\xef\xbb\xbf# coding: latin-1\n" + PLAIN,  # a byte-order mark that contradicts the cookie
        b"# \xff\xfe not utf-8 on the first line\n" + PLAIN,
    ],
    ids=["unknown-codec", "bom-vs-cookie", "bad-first-line"],
)
def test_a_decode_error_counts_as_not_utf8(data):
    assert declared_encoding(data) == "undecodable"
    assert non_utf8(data) == "undecodable"


def test_a_cookie_after_the_second_line_or_after_code_is_not_a_declaration():
    assert non_utf8(b"x = 1\n# coding: utf-7\n") is None  # line 2 counts only when line 1 is blank or a comment
    assert non_utf8(b"\n\n# coding: utf-7\n") is None
    assert non_utf8(b"\n# coding: utf-7\n") == "utf-7"


@pytest.mark.parametrize(
    ("path", "expected"),
    [("a.py", True), ("src/x/a.pyi", True), ("A.PY", True), ("a.md", False), ("a.pyc", False), ("py", False)],
)
def test_only_py_and_pyi_files_are_python_sources(path, expected):
    assert is_python_file(path) is expected


@pytest.mark.parametrize("cookie", ["ascii", "us-ascii", "US_ASCII", "646"])
def test_ascii_is_a_subset_of_utf8_and_hides_nothing(cookie):
    data = f"# coding: {cookie}\n".encode() + PLAIN
    assert declared_encoding(data) == "ascii"
    assert non_utf8(data) is None


# --- a bounded prefix: nothing larger than COOKIE_PREFIX_BYTES + 1 is needed to decide (L4-SEC-042) ----------------

LIMIT = COOKIE_PREFIX_BYTES
LONG = LIMIT + 5000


def test_the_prefix_limit_is_64_kib():
    assert LIMIT == 64 * 1024


def test_a_cookie_on_line_one_is_found_in_a_file_of_any_size():
    data = b"# coding: utf-7\n" + PLAIN + b"#" + b" " * 1022 + b"\n" * 9000
    assert non_utf8(data) == "utf-7"
    assert non_utf8(data[: LIMIT + 1]) == "utf-7"  # what a reader that stops at the prefix hands over
    assert non_utf8(data + b"x" * 10_000_000) == "utf-7"


def test_a_cookie_on_line_two_after_a_long_first_line_is_unreadable_not_skipped():
    data = b"# " + b"x" * LONG + b"\n# coding: utf-7\n" + PLAIN
    assert non_utf8(data[: LIMIT + 1]) == UNREADABLE
    assert non_utf8(data) == UNREADABLE
    assert non_utf8(b"   \t" + b" " * LONG + b"\n# coding: utf-7\n" + PLAIN) == UNREADABLE  # a blank line counts too
    assert non_utf8(b"\xef\xbb\xbf# " + b"x" * LONG + b"\n" + PLAIN) == UNREADABLE  # a byte-order mark first


def test_a_long_second_line_after_a_comment_is_unreadable_but_after_code_it_is_not():
    comment_after_comment = b"# one\n# " + b"x" * LONG + b"\n" + PLAIN
    assert non_utf8(comment_after_comment) == UNREADABLE
    assert non_utf8(b"# one\n   " + b" " * LONG + b"\n" + PLAIN) == UNREADABLE
    code_after_comment = b"# one\nDATA = '" + b"x" * LONG + b"'\n" + PLAIN
    assert non_utf8(code_after_comment) is None  # no cookie can sit on a line of code
    comment_after_code = b"import os\n# " + b"x" * LONG + b"\n" + PLAIN
    assert non_utf8(comment_after_code) is None  # line 1 is code: line 2 is never read for a cookie
    assert non_utf8(b"# coding: utf-8\n# " + b"x" * LONG + b"\n") == UNREADABLE  # fail closed, even with line 1 decided


def test_a_long_first_line_of_code_is_fine_and_is_never_decoded_where_it_is_cut():
    assert non_utf8(b"DATA = '" + "\u00e9".encode() * LONG + b"'\n") is None  # cut inside a multi-byte character
    assert non_utf8(b"\xef\xbb\xbfDATA = '" + b"x" * LONG + b"'\n") is None
    assert declared_encoding(b"DATA = '" + b"x" * LONG + b"'\n") == "utf-8"


def test_a_cookie_in_a_complete_line_before_the_cut_is_honoured():
    assert non_utf8(b"# coding: latin-1\n" + b"x" * LONG) == "iso-8859-1"
    assert non_utf8(b"x = 1\n# " + b"y" * LONG) is None
    assert non_utf8(b"# one\n# coding: utf-7\n" + b"x" * LONG) == "utf-7"
    assert non_utf8(b"# \xff\xfe\n" + b"x" * LONG) == "undecodable"  # a complete first line that is not text


def test_line_ends_are_normalised_at_the_cut_too():
    assert non_utf8(b"# one\r# coding: utf-7\r" + b"x" * LONG) == "utf-7"
    assert non_utf8(b"# one\r\n# coding: utf-7\r\n" + b"x" * LONG) == "utf-7"


def test_a_cut_between_the_two_bytes_of_a_line_end_leaves_the_line_open():
    comment = b"# " + b"x" * (LIMIT - 3) + b"\r\n# coding: utf-7\n"
    assert comment[LIMIT - 1 : LIMIT] == b"\r"  # the prefix ends on the \r of a \r\n
    assert non_utf8(comment[: LIMIT + 1]) == UNREADABLE  # line 2 is out of sight: fail closed
    code = b"D = '" + b"x" * (LIMIT - 7) + b"'\r\n" + PLAIN
    assert code[LIMIT - 1 : LIMIT] == b"\r" and non_utf8(code[: LIMIT + 1]) is None


def test_a_file_that_ends_inside_the_prefix_is_read_whole():
    assert non_utf8(b"# coding: utf-7") == "utf-7"
    assert non_utf8(b"DATA = 1") is None
    assert non_utf8(b"# " + b"x" * (LIMIT - 4)) is None


# --- following links inside a tree (F2) -----------------------------------------------------------------------------


def resolver(links: dict[str, str]):
    return links.get


def test_a_link_is_followed_to_the_file_it_names_relative_to_its_directory():
    assert resolve_links("pkg/x.py", resolver({"pkg/x.py": "notes.txt"})) == ("pkg/notes.txt", ["pkg/x.py"])
    assert resolve_links("pkg/x.py", resolver({"pkg/x.py": "../data/n.txt"}))[0] == "data/n.txt"
    assert resolve_links("x.py", resolver({}))[0] == "x.py"  # not a link: itself


def test_a_chain_and_a_linked_directory_are_followed():
    links = {"x.py": "y.txt", "y.txt": "z/n.txt", "z": "real"}
    assert resolve_links("x.py", resolver(links)) == ("real/n.txt", ["x.py", "y.txt", "z"])


def test_a_link_that_leaves_the_tree_loops_or_is_too_long_a_chain_resolves_to_nothing():
    assert resolve_links("x.py", resolver({"x.py": "/etc/passwd"}))[0] is None
    assert resolve_links("x.py", resolver({"x.py": "../outside"}))[0] is None
    assert resolve_links("x.py", resolver({"x.py": "y", "y": "x.py"}))[0] is None
    chain = {f"l{i}": f"l{i + 1}" for i in range(60)}
    assert resolve_links("l0", resolver(chain))[0] is None
    short = {f"l{i}": f"l{i + 1}" for i in range(30)}
    assert resolve_links("l0", resolver(short))[0] == "l30"


# ledger-surrogate-safe 1.1: `surrogate_free` (the ledger's values) next to `shown`


def test_shown_and_surrogate_free_agree_on_an_fsdecoded_name():
    import os

    from l4.security.pyencoding import shown, surrogate_free

    name = os.fsdecode("src/é→".encode() + b"\xff\x80.py")
    assert surrogate_free(name) == shown(name) == "src/é→\\xff\\x80.py"


def test_a_lone_surrogate_that_is_no_escaped_byte_becomes_uxxxx_text():
    from l4.security.pyencoding import surrogate_free

    assert surrogate_free("a\ud800b\udbffc\udc7f\ude00") == "a\\ud800b\\udbffc\\udc7f\\ude00"
    assert surrogate_free("\udcffx\ud800") == "\\xffx\\ud800"


def test_escaped_bytes_are_never_joined_into_a_character():
    """`shown` of the three escaped bytes of a euro sign would decode them; a ledger value keeps them as text."""
    from l4.security.pyencoding import surrogate_free

    assert surrogate_free("\udce2\udc82\udcac") == "\\xe2\\x82\\xac"


def test_surrogate_free_walks_keys_values_lists_and_tuples_and_leaves_the_rest():
    from l4.security.pyencoding import surrogate_free

    value = {"k\ud800": ["a\udcff", ("b\udc80", 3, None, True, 1.5)], 7: "plain ü"}
    assert surrogate_free(value) == {"k\\ud800": ["a\\xff", ["b\\x80", 3, None, True, 1.5]], 7: "plain ü"}


def test_text_without_a_surrogate_is_returned_as_the_same_object():
    from l4.security.pyencoding import has_surrogate, surrogate_free

    text = "ü → 😀 \\xff �"
    assert surrogate_free(text) is text and not has_surrogate(text) and has_surrogate("a\udcff")
