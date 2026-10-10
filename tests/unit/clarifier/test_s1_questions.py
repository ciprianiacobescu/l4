import json
import re
from pathlib import Path

from l4.clarifier.ports import QuestionView
from l4.clarifier.router import (
    CITATION_INSTRUCTION,
    ROUTER_INSTRUCTION,
    approx_tokens,
    citation_question,
    router_question,
    trim_state,
)
from l4.clarifier.s1_decisions import (
    ESTABLISHES_INSTRUCTION,
    INTERNAL_INSTRUCTION,
    OPPOSITE_INSTRUCTION,
    QUESTION_SET,
    ROUTE_INSTRUCTION,
    SHOWS_INSTRUCTION,
)
from l4.specs.questions import QuestionKind, QuestionStatus

SPEC = Path(__file__).parents[3] / "docs" / "SPEC.md"


def view(**over) -> QuestionView:
    values = dict(
        id="Q-001", title="Which VAT rate applies?", status=QuestionStatus.OPEN, kind=QuestionKind.TECHNICAL,
        blocking=("1.1",), context="The spec lists no rate.", options=("19%", "9%"), answer_text="", suggestion_text="",
        by=None,
    )  # fmt: skip
    return QuestionView(**{**values, **over})


def test_the_instructions_are_the_ones_in_spec_l4_clr_003():
    text = " ".join(SPEC.read_text(encoding="utf-8").split())
    clr = text[text.index("**L4-CLR-003**") : text.index("**L4-CLR-004**")]
    assert f'"{ROUTER_INSTRUCTION}"' in clr  # the boolean stand-in's two questions
    assert CITATION_INSTRUCTION in clr and "`cited_text`" in clr
    for shipped in (
        ROUTE_INSTRUCTION,
        SHOWS_INSTRUCTION,
        OPPOSITE_INSTRUCTION,
        ESTABLISHES_INSTRUCTION,
        INTERNAL_INSTRUCTION,
    ):
        assert f'"{shipped}"' in clr, shipped  # the System-One questions
    assert QUESTION_SET in clr


def test_router_state_instruction_and_trim():
    short = router_question(view(), max_tokens=450)
    assert short.instruction == ROUTER_INSTRUCTION
    assert short.state == (
        "Question: Which VAT rate applies?\n\nContext:\nThe spec lists no rate.\n\nOptions:\n1. 19%\n2. 9%"
    )
    big = view(context="c" * 4000, options=tuple(f"option {n} " + "o" * 200 for n in range(10)))
    trimmed = router_question(big, max_tokens=100)
    assert approx_tokens(trimmed.state + trimmed.instruction) <= 100
    assert trimmed.state.startswith("Question: Which VAT rate applies?\n\nContext:\n\n")  # title whole, context gone
    assert "[truncated]" in trimmed.state and "1. option 0" in trimmed.state  # options give way only after the context
    some = router_question(view(context="c" * 4000), max_tokens=100)  # two short options: the context is cut to fit
    assert "ccc" in some.state and "[truncated]" in some.state and "1. 19%\n2. 9%" in some.state
    nothing_left = router_question(view(title="t" * 300), max_tokens=10)
    assert "t" * 300 in nothing_left.state and nothing_left.instruction == ROUTER_INSTRUCTION  # never cut


def test_options_are_cut_only_after_the_context_is_gone():
    out = trim_state(
        lambda parts: f"T\n{parts[0]}\n{parts[1]}", ["x" * 400, "y" * 400], instruction="I", max_tokens=150
    )
    assert "y" * 400 in out and "[truncated]" in out and "x" * 400 not in out  # only the first part gave way
    assert approx_tokens(out + "I") <= 150
    both = trim_state(lambda p: f"T\n{p[0]}\n{p[1]}", ["x" * 400, "y" * 400], instruction="I", max_tokens=60)
    assert "x" not in both and "y" * 400 not in both and "[truncated]" in both  # the first is gone, then the second
    assert approx_tokens(both + "I") <= 60


def test_citation_state_is_the_json_of_answer_and_cited_text():
    query = citation_question("Use bcrypt.", "hash with bcrypt", max_tokens=450)
    assert query.instruction == CITATION_INSTRUCTION
    assert json.loads(query.state) == {"answer": "Use bcrypt.", "cited_text": "hash with bcrypt"}
    long = citation_question("a" * 100, "c" * 4000, max_tokens=120)
    assert approx_tokens(long.state + long.instruction) <= 120
    parsed = json.loads(long.state)
    assert parsed["answer"] == "a" * 100 and parsed["cited_text"].endswith("[truncated]")  # S1 reads less, never more
    assert re.fullmatch(r"c+\n?\[truncated\]", parsed["cited_text"])


def test_a_cut_citation_state_says_so_and_a_whole_one_does_not():
    assert not citation_question("Use bcrypt.", "hash with bcrypt", max_tokens=450).truncated
    answer = "a" * 1500  # a real-length answer: at 450 tokens the cited block is what gives way
    cited = "\n".join(f"line {n} of the cited block" for n in range(10))
    query = citation_question(answer, cited, max_tokens=450)
    assert query.truncated and json.loads(query.state)["answer"] == answer
    assert json.loads(query.state)["cited_text"].endswith("[truncated]")
