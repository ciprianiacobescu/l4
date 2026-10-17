"""The judge's diff in parts (L4-VER-040 to L4-VER-043): the bookkeeping list, the order and the packing of parts."""

from l4.state.review import UNIT_CHANNELS
from l4.verifier.diffparts import bookkeeping_pathspecs


def test_the_bookkeeping_pathspecs_name_the_globs_then_each_channel_file_of_each_unit_folder():
    assert bookkeeping_pathspecs(["u", "u-fix-1"]) == [
        ":(glob,exclude)**/.l4/**",
        ":(glob,exclude).serena/memories/harness/**",
        ":(literal,exclude)u/verification.md",
        ":(literal,exclude)u/questions.md",
        ":(literal,exclude)u/feedback.md",
        ":(literal,exclude)u-fix-1/verification.md",
        ":(literal,exclude)u-fix-1/questions.md",
        ":(literal,exclude)u-fix-1/feedback.md",
    ]


def test_the_file_names_come_from_the_unit_channel_list_of_the_review_module():
    names = [n for n in UNIT_CHANNELS if n != ".l4"]
    assert names == ["verification.md", "questions.md", "feedback.md"]
    assert bookkeeping_pathspecs([]) == [":(glob,exclude)**/.l4/**", ":(glob,exclude).serena/memories/harness/**"]
