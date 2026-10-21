"""A hold on a spec file the judge could not read whole is bound to that file's content and says so in its own words:
the config key to raise and the file that was cut, not the wording of a diff hold (L4-KSP-014, L4-VER-043)."""

from l4.implementer.unit_context import Cut, SourceFile
from l4.verifier.ladder import _spec_hold_views, _spec_holds
from l4.verifier.verdicts import _hold_question, finding_sha256, hold_id, hold_kind, hold_sha256

PATH = ".kiro/specs/x/requirements.md"


def cut(reason="budget", kind="narrative") -> Cut:
    return Cut(PATH, kind, reason, 100, 5000, 5000, ((10, None),), True)


def source(text: str) -> SourceFile:
    return SourceFile("requirements.md", PATH, text, len(text), "")


def views_of(text: str):
    cuts = [cut()]
    views = _spec_hold_views(cuts, [source(text)])
    return _spec_holds(cuts)[0], {h: {"sha": v.sha, "paths": list(v.paths)} for h, v in views.items()}


def test_the_accept_of_a_spec_hold_is_bound_to_the_file_content():
    hold, views = views_of("one\n")
    assert hold_kind(hold) == "judge_view"
    assert hold_sha256(hold, views) != finding_sha256(hold_id(hold))
    assert views[hold]["paths"] == [PATH]
    again, views_again = views_of("one\n")
    assert hold_sha256(again, views_again) == hold_sha256(hold, views)  # same content: the accept stands
    other, views_other = views_of("two\n")
    assert other == hold and hold_sha256(other, views_other) != hold_sha256(hold, views)  # edited: the accept is void


def test_the_question_names_the_budget_key_and_the_cut_file_not_the_diff():
    hold, views = views_of("one\n")
    context = _hold_question(hold, 1, (), tuple(views[hold]["paths"])).context
    assert "judge_context_budget_tokens" in context and PATH in context
    assert "could not see all of the diff" not in context and "split the change" not in context
    assert "The files the judge did not see" not in context


def test_an_unreadable_spec_file_is_bound_too():
    cuts = [cut("symlink")]
    views = _spec_hold_views(cuts, [])
    (hold,) = _spec_holds(cuts)
    assert hold in views and views[hold].paths == (PATH,)
