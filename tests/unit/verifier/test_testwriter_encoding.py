"""L4-SEC-042: the verifier's test writer puts its marker on line 1, so a cookie the model writes lands on line 2,
where Python honours it, and `ast.parse(str)` does not see it. The writer refuses such code (audit and e2e) and never
writes it."""

import ast

import pytest

from l4.agents.base import Usage
from l4.llm.agent_judge import StructuredResult
from l4.security.pyencoding import non_utf8
from l4.verifier.testwriter import GENERATED_MARKER, request_test, write_test_file

ID = "C-0a1b2c3d"
HIDDEN = "# coding: utf-7\ndef test_c_1():  # +AAo-    return\n    assert 1 == 2\n"
GOOD = "def test_it():\n    assert 1 + 1 == 2\n"


class Scripted:
    def __init__(self, parsed):
        self.result = StructuredResult("ok", parsed=parsed, usage=Usage(cost_usd=0.0), model_resolved="m", detail="")

    def complete_structured(self, system, messages, json_schema, *, effort, max_tokens, timeout_s):
        return self.result


def test_the_cookie_is_invisible_to_the_ast_which_is_why_the_ast_checks_cannot_see_it():
    assert "Return" not in ast.dump(ast.parse(HIDDEN))
    assert non_utf8((GENERATED_MARKER + "\n" + HIDDEN).encode()) == "utf-7"  # on line 2 behind the marker


@pytest.mark.parametrize("kind", ["audit", "e2e"])
def test_the_writer_refuses_code_that_declares_another_encoding(kind):
    reply = request_test(
        Scripted({"criterion": ID, "code": HIDDEN}), kind=kind, criterion_id=ID, criterion_text="c", data_blocks=[]
    )
    assert reply.status == "invalid" and reply.test is None
    assert "utf-7" in reply.detail and "UTF-8" in reply.detail and "coding cookie" in reply.detail


@pytest.mark.parametrize("kind", ["audit", "e2e"])
def test_the_writer_refuses_a_cookie_after_the_marker_it_wrote_itself(kind):
    code = GENERATED_MARKER + "\n" + HIDDEN  # the model repeats the marker: its own line 1 is the marker again
    reply = request_test(
        Scripted({"criterion": ID, "code": code}), kind=kind, criterion_id=ID, criterion_text="c", data_blocks=[]
    )
    assert reply.status == "invalid" and "utf-7" in reply.detail


def test_the_writer_refuses_a_cookie_on_the_first_line_too():
    reply = request_test(
        Scripted({"criterion": ID, "code": "# coding: latin-1\n" + GOOD}),
        kind="audit", criterion_id=ID, criterion_text="c", data_blocks=[],
    )  # fmt: skip
    assert reply.status == "invalid" and "iso-8859-1" in reply.detail


@pytest.mark.parametrize("code", [GOOD, "# -*- coding: utf-8 -*-\n" + GOOD, "# coding: ascii\n" + GOOD])
def test_code_without_a_cookie_or_with_a_utf8_one_is_accepted(code):
    reply = request_test(
        Scripted({"criterion": ID, "code": code}), kind="e2e", criterion_id=ID, criterion_text="c", data_blocks=[]
    )
    assert reply.status == "ok", reply.detail


@pytest.mark.parametrize("rel", ["tests/test_l4_audit_c_0a1b2c3d_r1.py", "e2e/test_l4_c_0a1b2c3d.py"])
def test_write_test_file_never_writes_a_file_with_another_encoding(tmp_path, rel):
    with pytest.raises(ValueError, match="utf-7"):
        write_test_file(tmp_path, rel, HIDDEN)
    assert not (tmp_path / rel).exists()
    with pytest.raises(ValueError, match="utf-7"):
        write_test_file(tmp_path, rel, GENERATED_MARKER + "\n" + HIDDEN, overwrite=True)
    path = write_test_file(tmp_path, rel, GOOD)
    assert non_utf8(path.read_bytes()) is None
