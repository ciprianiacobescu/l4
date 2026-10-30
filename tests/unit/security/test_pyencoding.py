"""L4-SEC-042: the declared source encoding of a Python file (`tokenize.detect_encoding`), as the harness reads it."""

import pytest

from l4.security.pyencoding import declared_encoding, is_python_file, non_utf8

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
