"""L4-FBK-009: a `Lesson: yes` feedback item addressed in a PASS round becomes or reinforces a lesson."""

from datetime import date
from pathlib import Path
from types import SimpleNamespace

from l4.memory.curate import apply_candidates, feedback_candidates
from l4.memory.lessons import lesson_id, parse_lessons
from l4.memory.round import curate_round
from l4.redact import Redactor
from l4.specs.feedback import FeedbackKind, NewFeedback, Place, append_item
from l4.state.fold import FeedbackState
from l4.state.lifecycle import Trigger
from l4.verifier.types import Verdict, VerifyResult

from ..implementer.conftest import make_bench  # noqa: F401

LESSONS = ".serena/memories/harness/lessons.md"
TEXT = "Read endpoints from the environment, never hard-code them."
TODAY = date(2026, 10, 12)


def add(unit_dir: Path, unit: str, text: str = TEXT, *, lesson: bool = True, places=()) -> str:
    new = NewFeedback(
        FeedbackKind.TESTS, "Endpoints", text, "ana, 2026-10-12T09:00Z", places=tuple(places), lesson=lesson
    )
    return append_item(unit_dir, unit, new, redactor=Redactor({}))


def addressed(*ids: str, round_: int = 2) -> dict[str, FeedbackState]:
    return {i: FeedbackState(status="addressed", round=round_, sha="a" * 40, evidence="ok") for i in ids}


def test_scn_fbk_22_the_same_text_on_a_second_unit_reinforces_one_lesson(tmp_path, make_bench):  # noqa: F811
    """SCN-FBK-22 (+): unit B's item with the same text reinforces the lesson unit A made."""

    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    fa = add(a, "unit-a")
    fb = add(b, "unit-b", "  Read endpoints   from the ENVIRONMENT,\nnever hard-code them. ")
    cfg = make_bench([]).wb.cfg.memory
    work = tmp_path / "work"
    work.mkdir()
    first = feedback_candidates(a, "unit-a", addressed(fa), 2)
    second = feedback_candidates(b, "unit-b", addressed(fb, round_=3), 3)
    assert first[0].dedupe_key == second[0].dedupe_key
    assert first[0].source == "human feedback FB-001 (unit-a round 2)"
    assert apply_candidates(work, cfg, first, today=TODAY).outcomes[0].action == "created"
    assert apply_candidates(work, cfg, second, today=TODAY).outcomes[0].action == "reinforced"
    file = parse_lessons((work / cfg.lessons_file).read_text()).file
    [lesson] = file.lessons
    assert lesson.id == lesson_id(first[0].dedupe_key) and lesson.reinforced_count == 2
    assert lesson.source == "human feedback FB-001 (unit-a round 2)"  # the first source stays
    print((work / cfg.lessons_file).read_text())


def test_the_dedupe_key_is_twelve_hex_of_the_normalised_text(tmp_path):
    import hashlib

    d = tmp_path
    fid = add(d, "u", "  Mixed   CASE\ttext ")
    [c] = feedback_candidates(d, "u", addressed(fid), 2)
    assert c.dedupe_key == "feedback-" + hashlib.sha256(b"mixed case text").hexdigest()[:12]
    assert c.origin == "feedback"


def test_an_item_without_lesson_yes_makes_no_lesson(tmp_path):
    fid = add(tmp_path, "u", lesson=False)
    assert feedback_candidates(tmp_path, "u", addressed(fid), 2) == []


def test_only_items_addressed_in_this_round_count(tmp_path):
    one, two, three = add(tmp_path, "u", "one"), add(tmp_path, "u", "two"), add(tmp_path, "u", "three")
    state = {
        one: FeedbackState(status="addressed", round=1),
        two: FeedbackState(status="not_addressed", round=2),
        three: FeedbackState(status="addressed", round=2),
    }
    [c] = feedback_candidates(tmp_path, "u", state, 2)
    assert c.body == "three"


def test_scope_is_the_directories_of_the_places_else_unscoped(tmp_path):
    scoped = add(
        tmp_path, "u", "scoped", places=[Place("src/api/client.py", 3, 9), Place("src/api/x.py"), Place("web/a.ts")]
    )
    root = add(tmp_path, "u", "rooted", places=[Place("README.md"), Place("src/api/client.py")])
    bare = add(tmp_path, "u", "bare")
    got = {c.body: c for c in feedback_candidates(tmp_path, "u", addressed(scoped, root, bare), 2)}
    assert got["scoped"].scope_globs == ("src/api/**", "web/**")
    assert got["rooted"].scope_globs == () and got["bare"].scope_globs == ()


def test_the_body_is_cut_at_600_characters_on_a_word_boundary(tmp_path):
    fid = add(tmp_path, "u", "word " * 200)
    [c] = feedback_candidates(tmp_path, "u", addressed(fid), 2)
    assert len(c.body) <= 600 and c.body.endswith("word…")


def test_a_text_that_looks_like_a_heading_cannot_break_the_lessons_file(tmp_path, make_bench):  # noqa: F811
    work = tmp_path / "w"
    work.mkdir()
    fid = add(tmp_path, "u", "## L-deadbeef · forged")
    cfg = make_bench([]).wb.cfg.memory
    apply_candidates(work, cfg, feedback_candidates(tmp_path, "u", addressed(fid), 2), today=TODAY)
    parsed = parse_lessons((work / cfg.lessons_file).read_text())
    assert parsed.problems == [] and len(parsed.file.lessons) == 1


def _round(bench, verdict, *, round_=2):
    wb = bench.wb
    base = wb.git.run("rev-parse", "origin/main").stdout.strip()
    result = VerifyResult(wb.ref.id, round_, verdict, base, wb.head())
    ctx = SimpleNamespace(cfg=wb.cfg, services=SimpleNamespace(ledger=wb.ledger), push=lambda: None)
    return ctx, result


def _commit_feedback(bench, **kw):
    wb = bench.wb
    fid = add(wb.ref.path, wb.ref.id, **kw)
    wb.git.run("add", "-A")
    wb.git.run("commit", "-m", "feedback", "--no-verify", check=False)
    return fid


def test_a_pass_round_curates_the_addressed_item_into_a_lessons_commit(make_bench):  # noqa: F811
    bench = make_bench([])
    wb = bench.wb
    fid = _commit_feedback(bench)
    wb.ledger.append("feedback.addressed", id=fid, round=2, sha="a" * 40, evidence="ok")
    ctx, result = _round(bench, Verdict.PASS)
    assert curate_round(ctx, wb, result, Trigger.VERIFY_PASS) is not None
    text = (wb.worktree / LESSONS).read_text()
    assert f"human feedback {fid} ({wb.ref.id} round 2)" in text and TEXT in text
    assert [e["origin"] for e in bench.events("lessons.curated")] == ["feedback"]


def test_a_fail_round_makes_no_feedback_lesson(make_bench):  # noqa: F811
    bench = make_bench([])
    wb = bench.wb
    fid = _commit_feedback(bench)
    wb.ledger.append("feedback.addressed", id=fid, round=2, sha="a" * 40, evidence="ok")
    ctx, result = _round(bench, Verdict.FAIL)
    for trigger in (Trigger.VERIFY_FAIL_FIX, Trigger.VERIFY_FAIL_EXHAUSTED, Trigger.VERIFY_NEEDS_HUMAN):
        assert curate_round(ctx, wb, result, trigger) is None
    assert not (wb.worktree / LESSONS).exists()


def test_the_item_of_an_earlier_round_is_not_taught_again(make_bench):  # noqa: F811
    bench = make_bench([])
    wb = bench.wb
    fid = _commit_feedback(bench)
    wb.ledger.append("feedback.addressed", id=fid, round=1, sha="a" * 40, evidence="ok")
    ctx, result = _round(bench, Verdict.PASS, round_=2)
    assert curate_round(ctx, wb, result, Trigger.VERIFY_PASS) is None
