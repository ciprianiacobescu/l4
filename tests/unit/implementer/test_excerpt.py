from pathlib import Path

from l4.gates.junit import TestCase, TestReport
from l4.implementer.excerpt import failure_excerpt, lint_excerpt

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
