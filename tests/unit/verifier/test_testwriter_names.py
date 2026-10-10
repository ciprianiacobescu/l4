"""M1.13 lines 24-25 (W-C4, SPEC L4-VER-002a): an audit test uses only names the shown sources define, never probes for
a method with a cascade of `hasattr`, and the rules say so. Wave C: `hasattr(Indexer, "row")` guessed a method that
does not exist, and two NEEDS_HUMAN rounds went to a correct implementation."""

import pytest

from l4.agents.base import Usage
from l4.llm.agent_judge import StructuredResult
from l4.verifier.testwriter import TEMPLATE_VERSION, build_writer_prompt, request_test

from .test_testwriter import ID, Scripted

INDEXER = (
    "import os\n\nLIMIT = 3\n\n\nclass Indexer:\n    def rows(self):\n        return []\n\n\n"
    "def build(path):\n    return Indexer()\n\n\nasync def refresh():\n    pass\n"
)
BLOCKS = [("src/sample/index.py", INDEXER), ("tests/test_a.py (the start of an existing test file)", "import pytest\n")]


def ask(code: str, blocks=BLOCKS):
    result = StructuredResult(
        "ok", parsed={"criterion": ID, "code": code}, usage=Usage(cost_usd=0.0), model_resolved="m"
    )
    return request_test(Scripted(result), kind="audit", criterion_id=ID, criterion_text="c", data_blocks=blocks)


def test_a_cascade_of_hasattr_on_one_object_is_rejected():
    code = (
        "from sample.index import build\n\n\ndef test_x():\n    idx = build('p')\n"
        "    if hasattr(idx, 'row'):\n        assert idx.row() == []\n"
        "    elif hasattr(idx, 'rows'):\n        assert idx.rows() == []\n"
    )
    reply = ask(code)
    assert reply.status == "invalid" and "hasattr" in reply.detail and "idx" in reply.detail
    assert "read the source" in reply.detail


def test_one_hasattr_and_hasattr_on_different_objects_are_allowed():
    one = "from sample.index import build\n\n\ndef test_x():\n    idx = build('p')\n    assert hasattr(idx, 'rows')\n"
    two = one + "    other = build('q')\n    assert hasattr(other, 'rows')\n"
    assert ask(one).status == "ok" and ask(two).status == "ok"


def test_an_import_of_a_name_the_source_does_not_define_is_rejected_naming_what_it_defines():
    reply = ask("from sample.index import Indexer, snapshot\n\n\ndef test_x():\n    assert Indexer\n")
    assert reply.status == "invalid" and "`snapshot` is not defined in `src/sample/index.py`" in reply.detail
    assert "Indexer" in reply.detail and "build" in reply.detail  # what it does define
    assert "`Indexer` is not" not in reply.detail


def test_the_names_a_source_defines_are_all_accepted():
    names = "Indexer, LIMIT, build, refresh, os"
    assert ask(f"from sample.index import {names}\n\n\ndef test_x():\n    assert build\n").status == "ok"


def test_a_module_that_is_not_among_the_shown_sources_is_not_checked():
    assert ask("from other.mod import anything\n\n\ndef test_x():\n    assert anything\n").status == "ok"


def test_a_submodule_import_from_a_package_is_not_flagged():
    blocks = [("src/pkg/__init__.py", "X = 1\n"), ("src/pkg/sub.py", "Y = 2\n")]
    assert ask("from pkg import sub, X\n\n\ndef test_x():\n    assert sub.Y and X\n", blocks).status == "ok"


def test_an_attribute_of_an_imported_module_that_the_source_lacks_is_rejected():
    code = "import sample.index as index\n\n\ndef test_x():\n    assert index.build('p') and index.snapshot\n"
    reply = ask(code)
    assert reply.status == "invalid" and "`snapshot` is not defined in `src/sample/index.py`" in reply.detail


def test_a_dunder_attribute_of_a_module_is_fine():
    code = "import sample.index as index\n\n\ndef test_x():\n    assert index.__name__\n"
    assert ask(code).status == "ok"


def test_a_source_with_a_star_import_or_a_module_getattr_is_not_checked():
    for text in ("from os.path import *\n", "def __getattr__(name):\n    return name\n"):
        blocks = [("src/sample/index.py", text)]
        assert ask("from sample.index import whatever\n\n\ndef test_x():\n    assert whatever\n", blocks).status == "ok"


def test_the_e2e_kind_is_not_checked():
    code = "from sample.index import nope\n\n\ndef test_x(page):\n    assert nope\n"
    result = StructuredResult(
        "ok", parsed={"criterion": ID, "code": code}, usage=Usage(cost_usd=0.0), model_resolved="m"
    )
    reply = request_test(Scripted(result), kind="e2e", criterion_id=ID, criterion_text="c", data_blocks=BLOCKS)
    assert reply.status == "ok"


def test_the_audit_rules_v4_say_names_sources_and_excluded_files():
    system, _ = build_writer_prompt("audit", ID, "c", [])
    assert TEMPLATE_VERSION >= 4
    assert "use only names the shown sources define" in system and "Read the shown sources" in system
    assert "Never snapshot or compare a whole folder" in system and "left out of every comparison" in system
    assert "hasattr" in system
    e2e, _ = build_writer_prompt("e2e", ID, "c", [])
    assert "use only names the shown sources define" not in e2e


@pytest.mark.parametrize("kind", ["audit"])
def test_the_lock_is_regenerated(kind):
    from l4 import templatelock

    assert templatelock.problems(templatelock.read_lock(), templatelock.current()) == []
    assert templatelock.read_lock()[f"testwriter/{kind}"]["version"] >= 4


def test_the_spec_describes_the_three_rules():
    from pathlib import Path

    spec = " ".join((Path(__file__).resolve().parents[3] / "docs" / "SPEC.md").read_text(encoding="utf-8").split())
    assert "a cascade that guesses a method) is `invalid`" in spec
    assert "that the file does not bind is `invalid`" in spec and "`testwriter/audit` v4" in spec
