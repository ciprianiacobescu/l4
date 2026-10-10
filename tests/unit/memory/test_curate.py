from datetime import date
from pathlib import Path

import pytest

from l4.config.schema import L4Config, MemoryCfg
from l4.memory.curate import (
    LESSON_RULES,
    UI_GAP_KEY,
    UI_GAP_TITLE,
    Applied,
    LessonCandidate,
    apply_candidates,
    candidates_from_round,
    curate,
    guard_violation_candidates,
)
from l4.memory.lessons import Lesson, LessonsFile, lesson_id, parse_lessons, render_lessons
from l4.state.ledger import LedgerEvent
from l4.verifier.types import Finding, Severity, Verdict, VerifyResult

TODAY = date(2026, 10, 4)
LESSONS = ".serena/memories/harness/lessons.md"


def gap_finding(source="deterministic", criterion="C-de7f2d3f") -> Finding:
    return Finding(Severity.MINOR, UI_GAP_TITLE, "no e2e test traces it", source, criterion=criterion)  # type: ignore[arg-type]


def result(verdict=Verdict.PASS, *findings: Finding) -> VerifyResult:
    return VerifyResult("openspec:x", 1, verdict, "a" * 40, "b" * 40, findings=list(findings))


def cfg() -> L4Config:
    return L4Config()


def candidate(key="k", **kw) -> LessonCandidate:
    return LessonCandidate(
        key, kw.pop("title", key), kw.pop("scope_globs", ()), (), "src", kw.pop("body", "body"),
        kw.pop("origin", "verifier_finding_fixed"),
    )  # fmt: skip


def test_ui_gap_closed_by_generated_test_creates_L_09421538():
    assert lesson_id(UI_GAP_KEY) == "L-09421538" and UI_GAP_KEY in LESSON_RULES
    found = candidates_from_round(
        result(Verdict.PASS, gap_finding()), cfg(),
        changed_files=["web/app.py", "docs/x.md", "web/static/a.js"], generated_criteria={"C-de7f2d3f"},
    )  # fmt: skip
    assert len(found) == 1
    one = found[0]
    assert one.dedupe_key == UI_GAP_KEY and one.origin == "verifier_finding_fixed"
    assert one.title == "UI criteria need an end-to-end test"
    assert one.scope_globs and all(g in cfg().verifier.playwright.ui_paths for g in one.scope_globs)
    assert "docs/x.md" not in one.body and "C-de7f2d3f" not in one.body  # a template: nothing from the run is quoted
    assert curate(LessonsFile(), one, cfg().memory, TODAY).lesson_id == "L-09421538"


def test_judge_finding_never_becomes_a_lesson():
    judged = gap_finding(source="judge")
    got = candidates_from_round(
        result(Verdict.PASS, judged), cfg(), changed_files=["web/app.py"], generated_criteria={"C-de7f2d3f"}
    )
    assert got == []


def test_finding_without_accepted_generated_test_creates_nothing():
    assert candidates_from_round(result(Verdict.PASS, gap_finding()), cfg(), changed_files=["web/app.py"]) == []


@pytest.mark.parametrize("verdict", [Verdict.NEEDS_HUMAN, Verdict.FAIL])
def test_needs_human_round_curates_nothing(verdict):
    got = candidates_from_round(
        result(verdict, gap_finding()), cfg(), changed_files=["web/app.py"], generated_criteria={"C-de7f2d3f"}
    )
    assert got == []


def event(seq: int, run: str, rule: str, kind="guard.violation") -> LedgerEvent:
    return LedgerEvent(None, run, "openspec:x", seq, kind, {"rule": rule, "path": "evil\n/path", "action": "reverted"})  # type: ignore[arg-type]


def test_repeated_guard_violation_and_human_edit_create_lessons():
    events = [event(1, "run-a", "frozen test"), event(2, "run-a", "frozen test"), event(3, "run-a", "only once"),
              event(4, "run-b", "frozen test"), event(5, "run-b", "other kind", kind="guard.test_tamper")]  # fmt: skip
    got = guard_violation_candidates(events)
    assert [c.origin for c in got] == ["guard_violation_repeated"]
    assert "frozen test" in got[0].body and "evil" not in got[0].body  # the rule is the harness's, the path is not
    assert guard_violation_candidates(events[:2]) == []  # two events, one run: not repeated across runs
    human = candidate("hand-written", origin="human_edit")
    done = curate(LessonsFile(), human, MemoryCfg(), TODAY)
    assert done.action == "created" and done.file.lessons[0].id == lesson_id("hand-written")


def test_duplicate_key_reinforces():
    first = curate(LessonsFile(), candidate("same"), MemoryCfg(), date(2026, 10, 1))
    again = curate(first.file, candidate("same", title="other title"), MemoryCfg(), TODAY)
    assert again.action == "reinforced" and len(again.file.lessons) == 1
    kept = again.file.lessons[0]
    assert kept.reinforced_count == 2 and kept.last_reinforced == TODAY and kept.title == "same"
    assert "Reinforced:** 2 · 2026-10-04" in render_lessons(again.file)


def test_cap_exceeded_archives_least_recent():
    lessons = [
        Lesson(lesson_id(f"k{n}"), f"t{n}", f"k{n}", "b", last_reinforced=date(2026, 9, n + 1)) for n in range(3)
    ]
    cfg3 = MemoryCfg(max_lessons=3)
    done = curate(LessonsFile(lessons), candidate("new"), cfg3, TODAY)
    assert done.action == "created" and len(done.file.lessons) == 3
    assert [x.dedupe_key for x in done.archived] == ["k0"]  # the oldest reinforcement
    alone = len(render_lessons(curate(LessonsFile(), candidate("new"), MemoryCfg(), TODAY).file).encode())
    tight = MemoryCfg(max_bytes=alone + 1)
    done = curate(LessonsFile(lessons), candidate("new"), tight, TODAY)
    assert [x.dedupe_key for x in done.file.lessons] == ["new"]  # the new lesson itself is never the one archived
    assert [x.dedupe_key for x in done.archived] == ["k0", "k1", "k2"]


class Ledger:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def append(self, event_type: str, /, **data):
        self.events.append((event_type, data))


def test_curation_outcomes_are_in_ledger(tmp_path: Path):
    ledger = Ledger()
    c = MemoryCfg(max_lessons=1)
    apply_candidates(tmp_path, c, [candidate("one"), candidate("one"), candidate("two")], ledger, today=TODAY)
    kinds = [(e[1]["action"], e[1]["id"]) for e in ledger.events if e[0] == "lessons.curated"]
    assert kinds == [("created", lesson_id("one")), ("reinforced", lesson_id("one")),
                     ("created", lesson_id("two")), ("archived", lesson_id("one"))]  # fmt: skip
    text = (tmp_path / LESSONS).read_text()
    assert [x.id for x in parse_lessons(text).file.lessons] == [lesson_id("two")]
    archived = tmp_path / ".serena/memories/harness/_archive" / f"{lesson_id('one')}.md"
    assert parse_lessons(archived.read_text()).file.lessons[0].reinforced_count == 2


def test_unreadable_lessons_file_is_never_rewritten(tmp_path: Path):
    path = tmp_path / LESSONS
    path.parent.mkdir(parents=True)
    path.write_text("<!-- l4:lessons v2 -->\n\n## L-00000000 · future\n", encoding="utf-8")
    ledger = Ledger()
    assert apply_candidates(tmp_path, MemoryCfg(), [candidate("one")], ledger, today=TODAY) == Applied()
    assert path.read_text(encoding="utf-8").startswith("<!-- l4:lessons v2")
    assert ledger.events[0][1]["action"] == "refused"


def test_disabled_memory_curates_nothing(tmp_path: Path):
    assert apply_candidates(tmp_path, MemoryCfg(enabled=False), [candidate("one")], today=TODAY) == Applied()
    assert not (tmp_path / LESSONS).exists()


def test_green_phase_guard_events_without_a_rule_count_as_repeated():
    """The exact shapes of `implementer.guards.restore_frozen`: `path, phase` only."""
    shape = {"path": "evil\n/path", "phase": "green"}
    events = [
        LedgerEvent(None, "run-a", "openspec:x", 1, "guard.violation", dict(shape)),  # type: ignore[arg-type]
        LedgerEvent(None, "run-b", "openspec:x", 2, "guard.violation", dict(shape)),  # type: ignore[arg-type]
        LedgerEvent(None, "run-a", "openspec:x", 3, "guard.test_tamper", dict(shape)),  # type: ignore[arg-type]
        LedgerEvent(None, "run-b", "openspec:x", 4, "guard.test_tamper", dict(shape)),  # type: ignore[arg-type]
    ]
    got = guard_violation_candidates(events)
    assert sorted(c.title for c in got) == [
        "Guard rule repeated: frozen support file",
        "Guard rule repeated: frozen test",
    ]
    assert all("evil" not in c.body and "evil" not in c.dedupe_key for c in got)


def test_a_lessons_file_that_is_not_utf8_is_refused_not_rewritten(tmp_path: Path):
    path = tmp_path / LESSONS
    path.parent.mkdir(parents=True)
    raw = b"<!-- l4:lessons v1 -->\n\n\xff\xfe not utf-8\n"
    path.write_bytes(raw)
    ledger = Ledger()
    assert apply_candidates(tmp_path, MemoryCfg(), [candidate("one")], ledger, today=TODAY) == Applied()
    assert path.read_bytes() == raw
    assert ledger.events[0][1]["action"] == "refused" and "UTF-8" in ledger.events[0][1]["reason"]


def test_apply_candidates_returns_the_outcomes_for_the_commit_detail(tmp_path: Path):
    done = apply_candidates(tmp_path, MemoryCfg(), [candidate("one"), candidate("one")], today=TODAY)
    assert [(o.action, o.lesson_id) for o in done.outcomes] == [
        ("created", lesson_id("one")),
        ("reinforced", lesson_id("one")),
    ]
    assert done.paths == [LESSONS]


def test_an_unsafe_archive_path_refuses_and_the_ledger_claims_nothing(tmp_path: Path):
    harness = tmp_path / ".serena/memories/harness"
    harness.mkdir(parents=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (harness / "_archive").symlink_to(elsewhere)
    ledger = Ledger()
    two = [candidate("one"), candidate("two")]
    done = apply_candidates(tmp_path, MemoryCfg(max_lessons=1), two, ledger, today=TODAY)
    assert done == Applied() and not (tmp_path / LESSONS).exists() and list(elsewhere.iterdir()) == []
    assert [e[1]["action"] for e in ledger.events] == ["refused"] and "symlink" in ledger.events[0][1]["reason"]
