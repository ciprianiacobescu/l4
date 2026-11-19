from pathlib import Path

from l4.gates.junit import TestCase, TestReport
from l4.implementer.excerpt import case_excerpt, failure_excerpt, lint_excerpt
from l4.redact import Redactor

WORK = Path("/runner/work/unit-wt")
TMP = Path("/runner/cache/units/u1/gate-tmp")

FILE_NOT_FOUND = f"""    def test_reads_the_table():
>       open("data/table.csv")
E       FileNotFoundError: [Errno 2] No such file or directory: '{WORK}/data/table.csv'

tests/test_table.py:7: FileNotFoundError
"""


def case(test_id: str, detail: str = "", message: str = "", status: str = "failed") -> TestCase:
    return TestCase(test_id, status, message, detail=detail)  # type: ignore[arg-type]


def report(*cases: TestCase) -> TestReport:
    return TestReport({c.id: c for c in cases})


def excerpt(rep: TestReport, ids: list[str], redact=lambda text: text) -> str:
    return failure_excerpt(rep, ids, worktree=WORK, tmp_root=TMP, redact=redact)


def test_an_error_in_an_existing_test_gives_its_location_and_e_lines():
    text = excerpt(
        report(case("tests.test_table::test_reads_the_table", FILE_NOT_FOUND)),
        ["tests.test_table::test_reads_the_table"],
    )
    assert "tests.test_table::test_reads_the_table" in text
    assert "E       FileNotFoundError: [Errno 2] No such file or directory: 'data/table.csv'" in text
    assert '>       open("data/table.csv")' in text
    assert "tests/test_table.py:7: FileNotFoundError" in text


def test_forty_lines_and_3000_characters_at_most():
    many = {
        f"t.m::test_{n}": "\n".join(f"E   Error number {n} line {k} " + "x" * 100 for k in range(20)) for n in range(30)
    }
    rep = report(*(case(i, d) for i, d in many.items()))
    text = excerpt(rep, sorted(many))
    assert len(text.splitlines()) <= 40
    assert len(text) <= 3000
    one = excerpt(rep, ["t.m::test_0"])
    assert len([line for line in one.splitlines() if line.startswith("E ")]) <= 6


def test_identical_lines_are_kept_once_with_a_count():
    detail = "E   ValueError: the same\n\nsrc/pkg/mod.py:3: ValueError"
    ids = [f"t.m::test_{n}" for n in range(3)]
    text = excerpt(report(*(case(i, detail) for i in ids)), ids)
    assert text.count("E   ValueError: the same") == 1
    assert "(same for 3 tests)" in text
    assert text.count("src/pkg/mod.py:3: ValueError") == 1


def test_paths_are_made_relative_and_tmp_is_masked():
    detail = f"E   OSError: {WORK}/a/b and {TMP}/pytest-0/x and /tmp/pytest-of-ci/pytest-4/y"
    text = excerpt(report(case("t.m::test_a", detail)), ["t.m::test_a"])
    assert str(WORK) not in text and str(TMP) not in text
    assert "a/b" in text and "<tmp>/pytest-0/x" in text and "<tmp>/y" in text


def test_a_token_in_the_output_is_redacted():
    text = excerpt(
        report(case("t.m::test_a", "E   AssertionError: SECRETVALUE leaked")),
        ["t.m::test_a"],
        redact=lambda t: t.replace("SECRETVALUE", "[REDACTED]"),
    )
    assert "SECRETVALUE" not in text and "[REDACTED]" in text


def test_a_secret_cut_by_the_line_bounds_is_redacted_whole():
    """m1.11(fix): the redactor sees the whole body before the excerpt keeps six `E` lines; redacting after the cut
    lost a private key's END marker, so the key's first lines went out as they were (the gate log redacts it whole)."""
    from l4.redact import Redactor

    key_lines = [f"MIIEkey{n:02d}" + "Q" * 50 for n in range(12)]
    body = (
        "    def test_reads_the_key():\n>       load_key()\n"
        "E       ValueError: -----BEGIN RSA PRIVATE KEY-----\n"
        + "".join(f"E       {line}\n" for line in key_lines)
        + "E       -----END RSA PRIVATE KEY-----\n\ntests/test_key.py:2: ValueError\n"
    )
    text = excerpt(report(case("t.m::test_reads_the_key", body)), ["t.m::test_reads_the_key"],
                   redact=Redactor({}).redact_text)  # fmt: skip
    assert "MIIEkey" not in text
    assert "[REDACTED:private-key]" in text


def test_no_body_falls_back_to_the_message():
    text = excerpt(report(case("t.m::test_a", "", "assert 1 == 2")), ["t.m::test_a"])
    assert "assert 1 == 2" in text


def test_an_id_the_report_lacks_is_left_out_and_nothing_gives_an_empty_text():
    assert excerpt(report(), ["t.m::missing"]) == ""


def test_the_lint_excerpt_keeps_the_head_and_the_summary_line_once_each():
    log = "\n".join([*(f"src/a.py:{n}:1: E501 line too long" for n in range(60)), "Found 60 errors."])
    out = lint_excerpt(log)
    lines = out.splitlines()
    assert len(lines) <= 40 and lines[-1] == "Found 60 errors."
    assert lines[0].startswith("src/a.py:0:1")
    assert len(out) <= 3000


def test_the_lint_excerpt_drops_repeated_lines():
    log = "same long repeated line here\n" * 10 + "other line\nFound 1 error."
    assert lint_excerpt(log).splitlines() == ["same long repeated line here", "other line", "Found 1 error."]


# L4-VER-078: the excerpt a round records for one failing test

BROWSER_BODY = f"""    def test_width(page):
>       assert page.evaluate("document.body.scrollWidth") == 1500
E       assert 1508 == 1500
E        +  where 1508 = page at '{WORK}/e2e/page.html'

e2e/test_layout.py:12: AssertionError
"""


def case_text(one: TestCase, redact=lambda text: text, limit: int | None = None) -> str:
    kwargs = {} if limit is None else {"limit": limit}
    return case_excerpt(one, worktree=WORK, tmp_root=None, redact=redact, **kwargs)


def test_a_cases_excerpt_holds_the_arrow_and_e_lines_with_a_relative_path():  # SCN-VER-308
    text = case_text(case("e2e.test_layout::test_width[chromium]", BROWSER_BODY, "assert 1508 == 1500"))
    assert text.splitlines() == [
        '>       assert page.evaluate("document.body.scrollWidth") == 1500',
        "E       assert 1508 == 1500",
        "E        +  where 1508 = page at 'e2e/page.html'",
        "e2e/test_layout.py:12: AssertionError",
    ]
    assert str(WORK) not in text and len(text.splitlines()) <= 8 and len(text) <= 600


def test_a_cases_excerpt_is_cut_at_eight_lines():
    body = "\n".join(f"E   line {n}" for n in range(30))
    assert case_text(case("t::a", body)).splitlines() == [f"E   line {n}" for n in range(6)]  # six E lines at most
    message = "\n".join(f"line {n}" for n in range(30))
    assert case_text(case("t::a", message=message)).splitlines() == [f"line {n}" for n in range(8)]


def test_a_cases_excerpt_is_cut_at_600_characters():
    assert len(case_text(case("t::a", "E   " + "x" * 2000))) == 600  # one long line: cut at the limit
    lines = "\n".join(f"E   {n} " + "y" * 196 for n in range(6))  # 200 characters per line
    text = case_text(case("t::a", lines))
    assert text.splitlines() == [f"E   {n} " + "y" * 196 for n in range(2)] and len(text) <= 600  # whole lines only


def test_a_case_with_a_message_and_no_body_gives_the_messages_first_lines():
    assert case_text(case("t::a", message="Error: boom\nsecond\n\nthird")) == "Error: boom\nsecond\nthird"


def test_a_case_with_nothing_to_show_gives_an_empty_excerpt():
    assert case_text(case("t::a")) == ""


def test_a_token_in_the_body_is_in_no_part_of_the_excerpt():  # SCN-VER-309
    token = "glpat-" + "A1b2C3d4E5f6G7h8I9j0"
    text = case_text(case("t::a", f"E   RuntimeError: {'x' * 570} {token}\n"), redact=Redactor({}).redact_text)
    for size in range(8, len(token) + 1):
        assert token[:size] not in text


def test_a_key_block_that_ends_past_the_eighth_line_leaves_no_line_of_it():  # SCN-VER-309
    begin, end = "-----BEGIN " + "RSA PRIVATE " + "KEY" + "-----", "-----END " + "RSA PRIVATE " + "KEY" + "-----"
    key = [f"E   MIIEowIBAAKCAQEA{n:02}" + "q" * 20 for n in range(12)]
    body = "\n".join(["E   first", f"E   {begin}", *key, f"E   {end}"])
    text = case_text(case("t::a", body), redact=Redactor({}).redact_text)
    assert "first" in text and not any(line.strip()[4:] in text for line in key) and "MIIEow" not in text


# finding 7: a private-key block whose marker fell outside the text the report kept

BEGIN = "-----BEGIN " + "RSA PRIVATE " + "KEY" + "-----"
END = "-----END " + "RSA PRIVATE " + "KEY" + "-----"
KEY_LINES = [f"MIIEowIBAAKCAQEA{n:02}" + "q" * 20 for n in range(6)]


def test_an_end_marker_without_its_begin_removes_the_key_lines_before_it():
    """The JUnit reader keeps the last 4,000 characters of a body, so the BEGIN marker can be gone."""
    body = "\n".join([*(f"E   {line}" for line in KEY_LINES), f"E   {END}", "E   after the key", "tests/t.py:3: Error"])
    text = case_text(case("t::a", body), redact=Redactor({}).redact_text)
    assert "MIIEow" not in text and "qqqq" not in text and "after the key" in text


def test_a_begin_marker_without_its_end_removes_everything_after_it():
    """The message is cut at 500 characters, so the END marker can be gone."""
    message = "\n".join(["first line", BEGIN, *KEY_LINES])
    text = case_text(case("t::a", message=message), redact=Redactor({}).redact_text)
    assert "first line" in text and "MIIEow" not in text and "qqqq" not in text


def test_a_whole_key_block_is_still_removed_by_the_shared_redactor_alone():
    redact = Redactor({}).redact_text
    assert "MIIEow" not in redact("\n".join([BEGIN, *KEY_LINES, END]))  # the shared redactor is unchanged


def test_the_run_retry_excerpt_has_the_same_protection():
    body = "\n".join([*(f"E   {line}" for line in KEY_LINES), f"E   {END}", "E   after"])
    text = excerpt(report(case("t::a", body)), ["t::a"], redact=Redactor({}).redact_text)
    assert "MIIEow" not in text and "after" in text


# finding 8 and F7: a collection error's excerpt


def test_a_collection_excerpt_is_cut_at_eight_lines_like_a_tests():
    from l4.implementer.excerpt import collection_case_excerpt

    detail = "\n".join(f"E   line {n}" for n in range(20))
    text = collection_case_excerpt(detail, worktree=WORK, tmp_root=None, redact=lambda t: t)
    assert text.splitlines() == [f"E   line {n}" for n in range(8)]
    long = collection_case_excerpt("E   " + "x" * 2000, worktree=WORK, tmp_root=None, redact=lambda t: t)
    assert len(long) == 600


def test_a_collection_excerpt_is_cut_at_a_line_end_before_600_characters():
    from l4.implementer.excerpt import collection_case_excerpt

    lines = "\n".join(f"E   {n} " + "y" * 196 for n in range(6))
    text = collection_case_excerpt(lines, worktree=WORK, tmp_root=None, redact=lambda t: t)
    assert text.splitlines() == [f"E   {n} " + "y" * 196 for n in range(2)]


def test_a_collection_excerpt_redacts_before_the_cut_and_after_the_paths_are_made_relative():
    """F7: the inner redaction sees the whole detail (a token that the 600 cut would split), the outer one the text."""
    from l4.implementer.excerpt import collection_case_excerpt

    token = "glpat-" + "A1b2C3d4E5f6G7h8I9j0"
    detail = f"E   ImportError: {'x' * 580} {token}"
    text = collection_case_excerpt(detail, worktree=WORK, tmp_root=None, redact=Redactor({}).redact_text)
    assert "glpat-" not in text
    seen: list[str] = []

    def spy(value: str) -> str:
        seen.append(value)
        return value

    collection_case_excerpt(f"E   cannot import {WORK}/src/x.py", worktree=WORK, tmp_root=None, redact=spy)
    assert len(seen) >= 2 and str(WORK) in seen[0] and str(WORK) not in seen[-1]  # inner: raw; outer: relative paths
