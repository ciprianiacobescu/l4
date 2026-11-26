"""The report, `verdict.json` and a restored round with M1.5's steps 5 (generated UI tests) and 8 (S1)."""

import json

from l4.implementer.excerpt import redacted_cut
from l4.redact import Redactor
from l4.verifier.evidence import restore_round
from l4.verifier.report import render_verification_md, verdict_json, write_round_evidence
from l4.verifier.types import (
    CriterionEvidence,
    CriterionOutcome,
    GateLine,
    GeneratedOutcome,
    S1Record,
    StepRecord,
    TracingTest,
    Verdict,
    VerifyResult,
)

UNIT = "openspec:show-item-count"
CID = "C-de7f2d3f"
TEST_ID = "e2e.test_l4_c_de7f2d3f::test_badge_shows_the_count"
ACCEPTED = GeneratedOutcome(
    CID, "accepted", "e2e/test_l4_c_de7f2d3f.py", 2, "", "def test_x(): ...", (), 0.02, "claude-sonnet-5-5", "p" * 64,
    "fail", "pass", (TEST_ID,), "f" * 64,
)  # fmt: skip
REFUSED = GeneratedOutcome(
    "C-68f2e098", "fails_at_head", "e2e/test_l4_c_68f2e098.py", 2, "the test fails at the head: t::x", "def t(): ...",
    ("test-results/t/trace.zip",), base="fail", head="fail",
)  # fmt: skip


def result(**over) -> VerifyResult:
    base = VerifyResult(
        UNIT, 1, Verdict.PASS, "a" * 40, "b" * 40,
        steps=[StepRecord("5", "ui test generation", "ok", 12.0, "1 accepted"), StepRecord("8", "s1 judge", "ok", 1.0)],
        gates=[GateLine("e2e", "pytest e2e", "pass", "", ".l4-out/gates/r-1/004-e2e.log")],
        trace=[CriterionEvidence(CID, "cart › Count", "covered", (TracingTest(TEST_ID, "passed", "generated"),))],
        criteria=[CriterionOutcome(CID, "cart › Count", "pass", "pass", "ok", tests=(TEST_ID,), s1_p=0.83)],
        generated=[ACCEPTED, REFUSED],
        s1=[S1Record(CID, "ok", 0.83, "laya-1", "laya-local", evidence={"implemented": 0.6, "unrelated": 0.4}),
            S1Record("C-68f2e098", "unavailable", reason="the state does not fit 300 tokens")],
    )  # fmt: skip
    for key, value in over.items():
        setattr(base, key, value)
    return base


def test_the_matrix_marks_the_generated_test_with_base_head_s1_and_links():
    text = render_verification_md(result())
    row = next(line for line in text.splitlines() if line.startswith(f"| {CID} | cart"))
    assert f"{TEST_ID} (passed, generated, base fail, head pass)" in row
    assert "0.83" in row and "e2e/test_l4_c_de7f2d3f.py" in row
    assert ".l4-out/e2e/page.html" in text


def test_a_test_generated_in_an_earlier_round_is_marked_without_base_and_head():
    text = render_verification_md(result(generated=[], s1=[]))
    assert f"{TEST_ID} (passed, generated)" in text and "base fail" not in text


def test_the_generated_section_lists_every_attempt_with_its_artifacts_and_reason():
    text = render_verification_md(result())
    assert "## Generated UI tests" in text
    refused = next(line for line in text.splitlines() if line.startswith("| C-68f2e098 | fails_at_head"))
    assert "test-results/t/trace.zip" in refused and "fails at the head" in refused
    assert "def t(): ..." in text  # the unaccepted test is shown in its own section (L4-VER-083)


NOTED = GeneratedOutcome(
    CID,
    "not_testable",
    reason="pure functions",
    covered_by=("tests.a::t1", "tests.a::t2", "tests.a::t3", "tests.a::t4"),
)


def test_a_noted_criterion_says_in_its_row_that_step_4_covers_it():  # SCN-VER-298
    text = render_verification_md(result(generated=[NOTED, REFUSED]))
    row = next(line for line in text.splitlines() if line.startswith(f"| {CID} | not_testable"))
    assert (
        "pure functions; covered by step 4: tests.a::t1, tests.a::t2, tests.a::t3 (+1 more); "
        "a note, not a hold (L4-VER-067)" in row
    )
    one = GeneratedOutcome(CID, "not_testable", reason="pure functions", covered_by=("tests.a::t1",))
    row = next(line for line in render_verification_md(result(generated=[one])).splitlines() if "not_testable" in line)
    assert "pure functions; covered by step 4: tests.a::t1; a note, not a hold (L4-VER-067)" in row
    assert "more" not in row
    plain = GeneratedOutcome(CID, "not_testable", reason="pure functions")
    row = next(
        line for line in render_verification_md(result(generated=[plain])).splitlines() if "not_testable" in line
    )
    assert "covered by step 4" not in row and "pure functions" in row


def test_verdict_json_stores_covered_by_as_a_list():  # SCN-VER-298
    body = verdict_json(result(generated=[NOTED, REFUSED]))
    back = json.loads(json.dumps(body))
    assert back["generated"][0]["covered_by"] == ["tests.a::t1", "tests.a::t2", "tests.a::t3", "tests.a::t4"]
    assert back["generated"][1]["covered_by"] == []


def test_the_s1_section_says_it_decides_nothing_and_lists_the_unavailable():
    text = render_verification_md(result())
    assert "## S1" in text and "never decides" in text
    assert "| C-68f2e098 | unavailable" in text and "does not fit 300 tokens" in text


def test_a_round_without_step_5_or_8_renders_no_new_section_or_column():
    text = render_verification_md(result(generated=[], s1=[], gates=[]))
    assert "## Generated UI tests" not in text and "## S1" not in text and "S1 p" not in text


def test_verdict_json_carries_generated_and_s1_and_the_criterion_fields():
    body = verdict_json(result())
    back = json.loads(json.dumps(body))
    assert back["generated"] == body["generated"] and back["s1"] == body["s1"]
    accepted, refused = body["generated"]
    assert accepted["status"] == "accepted" and accepted["tests"] == [TEST_ID] and "code" not in accepted
    assert refused["code"] == "def t(): ..." and refused["artifacts"] == ["test-results/t/trace.zip"]
    assert body["s1"][0]["p"] == 0.83 and body["s1"][1]["status"] == "unavailable"
    assert body["criteria"][0]["tests"] == [TEST_ID] and body["criteria"][0]["s1_p"] == 0.83


def test_a_restored_round_keeps_steps_5_and_8_their_outcomes_and_their_status():
    original = result()
    original.steps[1] = StepRecord("8", "s1 judge", "unavailable", note="no laya")
    back = restore_round(json.loads(json.dumps(verdict_json(original))), UNIT, 2)
    assert [(s.step, s.status) for s in back.steps] == [("5", "reused"), ("8", "unavailable")]
    assert back.generated == [GeneratedOutcome(**{**ACCEPTED.__dict__, "code": ""}), REFUSED]
    assert back.s1 == original.s1


EXCERPT = (
    "tests.e2e.test_l4_c_68f2e098::test_badge:\n"
    '  >       expect(page.get_by_role("heading", name="Orders")).to_be_visible()\n'
    "  E       AssertionError: Locator expected to be visible\n"
    "  e2e/test_l4_c_68f2e098.py:19: AssertionError"
)
CODE = "\n".join(f"line {n}" if n != 19 else "# the heading check" for n in range(1, 21)) + "\n"
TOKEN = "glpat-" + "A1b2C3d4E5f6G7h8I9j0"
FAILED = GeneratedOutcome(
    "C-68f2e098", "fails_at_head", "e2e/test_l4_c_68f2e098.py", 2, "the test fails at the head: t::x", CODE,
    ("test-results/t/trace.zip",), base="fail", head="fail", excerpt=EXCERPT,
)  # fmt: skip


def test_verdict_json_stores_the_excerpt_when_there_is_one_and_no_key_when_there_is_none():  # SCN-VER-333
    body = verdict_json(result(generated=[ACCEPTED, FAILED, REFUSED]))
    accepted, failed, refused = body["generated"]
    assert failed["excerpt"] == EXCERPT and failed["code"] == CODE
    assert "excerpt" not in accepted and "excerpt" not in refused and refused["code"] == "def t(): ..."
    back = restore_round(json.loads(json.dumps(body)), UNIT, 2)
    assert back.generated[1] == FAILED  # a reused round keeps both


def test_the_unaccepted_section_has_the_item_and_a_six_space_block_with_the_numbered_code():  # SCN-VER-333
    text = render_verification_md(result(generated=[ACCEPTED, FAILED]))
    lines = text.splitlines()
    head = lines.index("## Generated UI tests that were not accepted")
    assert lines.index("## Generated UI tests") < head
    assert lines[head + 2] == "- C-68f2e098 (fails_at_head after 2 attempt(s)): `e2e/test_l4_c_68f2e098.py`"
    block = lines[head + 3 : head + 3 + 4 + 1 + 20 + 1]
    assert block[0] == "" and block[1] == "      Failure at the head:"
    assert "          E       AssertionError: Locator expected to be visible" in block
    assert "      The test (at most 200 lines and 6,000 characters):" in block
    assert "        19  # the heading check" in block and "         1  line 1" in block
    assert all(line.startswith("      ") for line in block[1:])
    section = lines[head : head + 3 + 4 + 1 + 20 + 3]
    assert not any(line.startswith("- C-de7f2d3f") for line in section)  # the accepted outcome has no item


def test_the_unaccepted_section_bounds_the_numbered_code_and_says_how_many_lines_it_cut():  # SCN-VER-331
    huge = GeneratedOutcome("C-a", "fails_at_head", "e2e/test_l4_c_a.py", 2, "r", "\n" * 4000, excerpt="E  boom")
    lines = render_verification_md(result(generated=[huge])).splitlines()
    head = lines.index("      The test (at most 200 lines and 6,000 characters):")
    shown = lines[head + 1 :]
    shown = shown[: shown.index("      … (cut: 3800 more lines)") + 1]
    assert len(shown) == 201 and shown[0] == "         1"  # the numbered lines are kept from the top
    assert sum(len(line) + 1 for line in shown) <= 6000 + 6 * len(shown)  # the indent of six is the block's


def test_no_unaccepted_section_without_a_written_test():  # SCN-VER-335
    nothing = [
        ACCEPTED,
        GeneratedOutcome("C-a", "not_testable", reason="pure functions"),
        GeneratedOutcome("C-b", "writer_failed", attempts=1, reason="no answer"),
        GeneratedOutcome("C-c", "waived", by="Q-004"),
        GeneratedOutcome("C-d", "fails_at_head", "e2e/test_l4_c_d.py", 2, "the test fails at the head: t::x"),
    ]
    assert "were not accepted" not in render_verification_md(result(generated=nothing))
    assert "were not accepted" not in render_verification_md(result(generated=[]))


def test_a_writer_failed_outcome_that_kept_a_test_is_listed():  # SCN-VER-350
    kept = GeneratedOutcome("C-a", "writer_failed", "e2e/test_l4_c_a.py", 2, "no answer", "x = 1\n", excerpt="E  boom")
    text = render_verification_md(result(generated=[kept]))
    assert "- C-a (writer_failed after 2 attempt(s)): `e2e/test_l4_c_a.py`" in text and "         1  x = 1" in text


def test_verdict_json_keeps_the_line_count_of_the_whole_test_next_to_the_code():  # SCN-VER-355
    counted = GeneratedOutcome(**{**FAILED.__dict__, "code_lines": 120})
    accepted = GeneratedOutcome(**{**ACCEPTED.__dict__, "code_lines": 40})
    body = json.loads(json.dumps(verdict_json(result(generated=[accepted, counted, FAILED]))))
    accepted_row, counted_row, plain_row = body["generated"]
    assert counted_row["code_lines"] == 120 and counted_row["code"] == CODE
    assert "code_lines" not in plain_row  # unknown (0): no key, like an empty excerpt
    assert "code" not in accepted_row and "code_lines" not in accepted_row  # no code written, no count
    back = restore_round(body, UNIT, 2)
    assert back.generated[1] == counted and back.generated[1].code_lines == 120  # a reused round keeps it
    assert back.generated[2].code_lines == 0


def test_a_record_of_0_4_59_without_the_line_count_restores_as_unknown_and_shows_the_copy():  # SCN-VER-355
    from l4.verifier.evidence import _generated

    stored = {  # the `generated` entry of a verdict.json of 0.4.59
        "criterion": "C-a", "status": "fails_at_head", "path": "e2e/test_l4_c_a.py", "attempts": 2, "reason": "r",
        "artifacts": [], "tests": [], "code": "x = 1\ny = 2\n",
    }  # fmt: skip
    restored = _generated(stored)
    assert restored.code_lines == 0
    text = render_verification_md(result(generated=[restored]))
    assert "         1  x = 1" in text and "         2  y = 2" in text and "more line" not in text


def test_the_report_ends_a_copy_shorter_than_the_test_with_the_cut_line():  # SCN-VER-355
    kept = GeneratedOutcome("C-a", "fails_at_head", "e2e/test_l4_c_a.py", 2, "r", "x = 1\ny = 2\n", code_lines=120)
    lines = render_verification_md(result(generated=[kept])).splitlines()
    assert lines[lines.index("         2  y = 2") + 1] == "      … (cut: 118 more lines)"


def test_a_secret_in_the_code_or_the_failure_is_in_no_file_of_the_round(tmp_path):  # SCN-VER-332
    redactor = Redactor({})
    raw = "# " + "x" * 3983 + " " + TOKEN + "\n# more\n"  # one line: the token starts before the 4,000th character
    kept = GeneratedOutcome(
        "C-a", "fails_at_head", "e2e/test_l4_c_a.py", 2, "r", redacted_cut(raw, redactor.redact_text, 4000),
        excerpt="E   RuntimeError: " + TOKEN,
    )  # fmt: skip
    write_round_evidence(tmp_path, 1, result(generated=[kept]), redactor)
    for name in ("verification.md", ".l4/evidence/round-1/verification.md", ".l4/evidence/round-1/verdict.json"):
        text = (tmp_path / name).read_text()
        assert all(TOKEN[i : i + 8] not in text for i in range(len(TOKEN) - 7)), name


def test_a_half_key_block_in_a_record_that_0_4_59_wrote_is_in_no_file_of_the_round(tmp_path):  # SCN-VER-353
    """0.4.59 cut a generated test's code before it redacted it, so a stored copy can end inside a private key, and
    the shared redactor needs both markers. A reused round restores that copy: it is redacted again, whole, cut and
    whole again, where `verification.md` and `verdict.json` are written, so 0.4.60 does not write the half key again."""
    from l4.verifier.evidence import _generated

    begin = "-----BEGIN " + "RSA PRIVATE " + "KEY" + "-----"
    stored = {  # the `generated` entry of a verdict.json of 0.4.59: no `excerpt`
        "criterion": "C-a", "status": "fails_at_head", "path": "e2e/test_l4_c_a.py", "attempts": 2, "reason": "r",
        "artifacts": [], "tests": [], "code": f"x = 1\n# {begin}\n# MIIEowIBAAKCAQEA" + "q" * 60,
    }  # fmt: skip
    restored = _generated(stored)
    assert "MIIEow" in render_verification_md(result(generated=[restored]))  # the shared redactor is not applied yet
    write_round_evidence(tmp_path, 1, result(generated=[restored]), Redactor({}))
    for name in ("verification.md", ".l4/evidence/round-1/verification.md", ".l4/evidence/round-1/verdict.json"):
        text = (tmp_path / name).read_text()
        assert "MIIEow" not in text and "q" * 20 not in text, name
        assert "x = 1" in text and "[REDACTED:private-key]" in text, name
    body = json.loads((tmp_path / ".l4/evidence/round-1/verdict.json").read_text())
    assert body["generated"][0]["code"].startswith("x = 1\n# [REDACTED:private-key]")


def test_the_row_of_a_carried_outcome_says_it_is_carried_from_the_base_and_not_step_4_cover():  # SCN-VER-343
    many = ("tests.a::t1", "tests.a::t2", "tests.a::t3", "tests.a::t4")
    carried = GeneratedOutcome(CID, "carried", reason="carried from the base", covered_by=many)
    text = render_verification_md(result(generated=[carried]))
    row = next(line for line in text.splitlines() if line.startswith(f"| {CID} | carried"))
    assert (
        "carried from the base: tests.a::t1, tests.a::t2, tests.a::t3 (+1 more) (the scenario and these tests are "
        "the base's, and they pass); a note, not a hold (L4-VER-086)" in row
    )
    assert "covered by step 4" not in row and "were not accepted" not in text
    one = GeneratedOutcome(CID, "carried", reason="carried from the base", covered_by=("tests.a::t1",))
    row = next(line for line in render_verification_md(result(generated=[one])).splitlines() if "| carried" in line)
    assert "carried from the base: tests.a::t1 (the scenario" in row and "more" not in row


def test_scn_ver_426_the_row_of_a_carried_outcome_names_the_files_the_unit_only_added_tests_to():
    carried = GeneratedOutcome(
        CID, "carried", reason="carried from the base", covered_by=("tests.a::t1",),
        appended=("web/src/a.test.ts", "tests/test_b.py"),
    )  # fmt: skip
    row = next(line for line in render_verification_md(result(generated=[carried])).splitlines() if "| carried" in line)
    assert (
        "carried from the base: tests.a::t1 (the scenario and these tests are the base's, and they pass); "
        "the unit only added tests to web/src/a.test.ts, tests/test_b.py; a note, not a hold (L4-VER-086)" in row
    )
    plain = GeneratedOutcome(CID, "carried", reason="carried from the base", covered_by=("tests.a::t1",))
    row = next(line for line in render_verification_md(result(generated=[plain])).splitlines() if "| carried" in line)
    assert "only added tests" not in row  # the 0.4.60 row, word for word


def test_scn_ver_426_appended_is_stored_only_when_there_is_one_and_a_reused_round_restores_it():
    carried = GeneratedOutcome(
        CID, "carried", reason="carried from the base", covered_by=("tests.a::t1",), appended=("web/src/a.test.ts",)
    )
    body = json.loads(json.dumps(verdict_json(result(generated=[carried]))))
    assert body["generated"][0]["appended"] == ["web/src/a.test.ts"]
    assert restore_round(body, UNIT, 2).generated == [carried]
    plain = GeneratedOutcome(CID, "carried", reason="carried from the base", covered_by=("tests.a::t1",))
    assert "appended" not in json.loads(json.dumps(verdict_json(result(generated=[plain]))))["generated"][0]


def test_verdict_json_stores_a_carried_outcome_and_a_reused_round_restores_it():  # SCN-VER-349
    carried = GeneratedOutcome(CID, "carried", reason="carried from the base", covered_by=("tests.a::t1",))
    body = json.loads(json.dumps(verdict_json(result(generated=[carried]))))
    assert body["generated"][0]["status"] == "carried" and body["generated"][0]["covered_by"] == ["tests.a::t1"]
    assert "code" not in body["generated"][0] and "excerpt" not in body["generated"][0]
    assert restore_round(body, UNIT, 2).generated == [carried]
