import copy
from pathlib import Path

from l4.eval.render import render_markdown

from ._cards import sample_card

GOLDEN = Path(__file__).parent / "golden" / "render.md"


def test_the_markdown_matches_the_golden_file() -> None:
    assert render_markdown(sample_card()) == GOLDEN.read_text(encoding="utf-8")


def test_rendering_is_pure() -> None:
    card = sample_card()
    before = copy.deepcopy(card)
    first = render_markdown(card)
    assert card == before and render_markdown(card) == first


def test_invalid_cells_have_their_own_heading_with_the_reason() -> None:
    text = render_markdown(sample_card())
    assert "## Invalid cells (not in any rate)" in text
    section = text.split("## Invalid cells (not in any rate)")[1]
    assert "rate_limited" in section and "add-late-fee" in section


def test_a_card_without_invalid_cells_has_no_such_heading() -> None:
    card = sample_card()
    card["cells"] = [c for c in card["cells"] if c["status"] != "invalid"]
    assert "Invalid cells" not in render_markdown(card)


def test_a_partial_scorecard_is_marked() -> None:
    card = sample_card()
    card["complete"] = False
    assert "PARTIAL" in render_markdown(card).splitlines()[0]
    assert "PARTIAL" not in render_markdown(sample_card())


def test_markdown_table_cells_cannot_be_broken_by_a_pipe() -> None:
    card = sample_card()
    card["profiles"][0]["profile"] = "a|b"
    assert "a\\|b" in render_markdown(card)
