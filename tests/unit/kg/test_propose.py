"""`kg.propose`: drafts for a person, in the inbox (L4-KG-012; SCN-KG-22 proposal part, SCN-KG-24, SCN-KG-25,
SCN-KG-26)."""

import json
import subprocess
from datetime import date
from pathlib import Path

import pytest

from l4.exitcodes import L4Exit
from l4.kg.extract import slug
from l4.kg.propose import INBOX, TODO_LINE, propose
from l4.memory.curate import UI_GAP_KEY, UI_GAP_TITLE
from l4.memory.inbox import parse_proposal
from l4.memory.lessons import lesson_id, parse_lessons
from l4.redact import Redactor

from ._readers import index

TODAY = date(2026, 10, 14)
CLASS = "no new test traces <criterion>"
KEY = "kg-a-no-new-test-traces-criterion"
LID = lesson_id(KEY)
REASON = "no new test traces C-e25f06d8: tag your test with the criterion id"
DRAFT = f"{INBOX}/kg-2026-10-14/{LID}.md"


def run_propose(kg_repo, redactor=None, **kw):
    idx = index(kg_repo)
    git = kg_repo.recording_git()
    return propose(
        idx.nodes, idx.edges, repo=kg_repo.root, git=git, today=kw.pop("today", TODAY), redactor=redactor, **kw
    )


def failed(task="1.1", phase="red", attempt=1, reason=REASON):
    return ("task.attempt_failed", {"task": task, "phase": phase, "attempt": attempt, "reason": reason})


def failing_units(kg_repo, *names, reason=REASON, phase="red"):
    for name in names:
        kg_repo.unit(f"openspec:{name}", where="base", runs=[kg_repo.run(failed(reason=reason, phase=phase))])


def drafts(result):
    return [p for p in result.proposals if p.covered_by is None]


# --- SCN-KG-24: pattern (a) ---------------------------------------------------------------------------------


def test_scn_kg_24_a_recurring_red_failure_becomes_a_draft(kg_repo):
    kg_repo.lessons(kg_repo.lesson("Other lesson", "other"))
    failing_units(kg_repo, "a", "b")
    result = run_propose(kg_repo)
    (draft,) = drafts(result)
    assert (draft.kind, draft.dedupe_key, draft.lesson_id) == ("a", KEY, LID)
    assert draft.path == DRAFT and draft.evidence_path == f"{INBOX}/kg-2026-10-14/{LID}.evidence.md"
    text = (kg_repo.root / draft.path).read_text(encoding="utf-8")
    assert text.rstrip("\n").endswith(
        f"TODO(person): write what the implementer should do instead, then run l4 lessons promote {LID}"
    )
    assert TODO_LINE.format(lid=LID) in text
    parsed = parse_lessons(text)
    assert parsed.problems == []
    (lesson,) = parsed.file.lessons
    assert lesson.id == LID and lesson.dedupe_key == KEY
    assert lesson.title == f"Recurring red failure: {CLASS}"
    assert lesson.source == "l4 kg propose 2026-10-14: n = 2 units, n = 2 attempts"
    assert lesson.scope_globs == ()
    assert (kg_repo.root / draft.evidence_path).is_file()
    # nothing else moved: only untracked inbox files, nothing staged, no lessons.md change
    assert kg_repo.status().split() == ["??", ".serena/"]
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"], cwd=kg_repo.root, capture_output=True, text=True, check=True
    )
    assert staged.stdout == ""


def test_a_draft_ready_for_the_person_is_accepted_by_promote_once_the_todo_is_replaced(kg_repo):
    failing_units(kg_repo, "a", "b")
    (draft,) = drafts(run_propose(kg_repo))
    path = kg_repo.root / draft.path
    path.write_text(
        path.read_text(encoding="utf-8").replace(TODO_LINE.format(lid=LID), "Tag the test with the criterion id."),
        encoding="utf-8",
    )
    lesson = parse_proposal(path, LID)
    assert lesson.dedupe_key == KEY and "Tag the test" in lesson.body


def test_the_draft_as_written_is_refused_by_promote_for_its_todo_line(kg_repo):
    failing_units(kg_repo, "a", "b")
    (draft,) = drafts(run_propose(kg_repo))
    with pytest.raises(L4Exit, match="TODO"):
        parse_proposal(kg_repo.root / draft.path, LID)


def test_the_title_names_the_phase_when_the_phases_differ(kg_repo):
    failing_units(kg_repo, "a")
    kg_repo.unit("openspec:b", where="base", runs=[kg_repo.run(failed(phase="green"))])
    (draft,) = drafts(run_propose(kg_repo))
    assert draft.title == f"Recurring attempt failure: {CLASS}"


def test_a_class_in_one_unit_is_below_the_floor_and_min_units_moves_it(kg_repo):
    failing_units(kg_repo, "a")
    assert run_propose(kg_repo).proposals == []
    assert len(drafts(run_propose(kg_repo, min_units=1))) == 1


def test_the_evidence_lists_units_runs_and_src_pointers_only(kg_repo):
    failing_units(kg_repo, "a", "b")
    (draft,) = drafts(run_propose(kg_repo))
    evidence = (kg_repo.root / draft.evidence_path).read_text(encoding="utf-8")
    assert "openspec:a" in evidence and "openspec:b" in evidence and "r-" in evidence
    assert ".jsonl#" in evidence
    assert "tag your test" not in evidence  # the reason text is not evidence, the class is
    assert "promote never reads this file" in evidence


# --- SCN-KG-25: covered patterns ----------------------------------------------------------------------------


def test_scn_kg_25_a_pattern_with_a_lesson_gets_no_draft(kg_repo):
    kg_repo.lessons(kg_repo.lesson("Trace your tests", KEY))
    failing_units(kg_repo, "a", "b")
    result = run_propose(kg_repo)
    assert drafts(result) == []
    (proposal,) = result.proposals
    assert proposal.covered_by == LID
    assert f"covered by {LID}" in result.render()
    assert not (kg_repo.root / INBOX).exists()


def test_an_archived_lesson_covers_it_too(kg_repo):
    kg_repo.lessons(kg_repo.lesson("Trace your tests", KEY), archive=LID)
    failing_units(kg_repo, "a", "b")
    assert drafts(run_propose(kg_repo)) == []


def test_a_lesson_rule_covers_its_finding_title(kg_repo):
    for name in ("a", "b"):
        crit = kg_repo.criterion(f"cap{name} › Cart › Shows count")
        found = kg_repo.finding(UI_GAP_TITLE, criterion=crit.id)
        kg_repo.unit(f"openspec:{name}", where="base", verdicts=[kg_repo.verdict(1, findings=[found], criteria=[crit])])
    result = run_propose(kg_repo)
    assert drafts(result) == []
    (proposal,) = result.proposals
    assert proposal.covered_by == lesson_id(UI_GAP_KEY)


# --- pattern (b): deterministic findings; SCN-KG-26 ---------------------------------------------------------


def finding_units(kg_repo, title, names, *, source="deterministic", files=None):
    for name in names:
        crit = kg_repo.criterion(f"cap{name} › Cart › Shows count")
        found = kg_repo.finding(title, criterion=crit.id, source=source)
        kg_repo.unit(f"openspec:{name}", where="base", verdicts=[kg_repo.verdict(1, findings=[found], criteria=[crit])])


def test_a_recurring_deterministic_finding_becomes_a_draft(kg_repo):
    finding_units(kg_repo, "Tests not collected individually", ["a", "b"])
    (draft,) = drafts(run_propose(kg_repo))
    key = "tests not collected individually | cart › shows count"
    assert draft.kind == "b" and draft.dedupe_key == f"kg-b-{slug(key)}"
    assert draft.title == "Recurring finding: Tests not collected individually"
    evidence = (kg_repo.root / draft.evidence_path).read_text(encoding="utf-8")
    assert "verdict.json#/findings/0" in evidence


def test_scn_kg_26_judge_text_never_reaches_a_draft(kg_repo):
    finding_units(kg_repo, "Edge case not handled", ["a", "b", "c"], source="judge")
    result = run_propose(kg_repo)
    assert result.proposals == []
    inbox = kg_repo.root / INBOX
    assert not inbox.exists()
    assert "Edge case" not in result.render()


def test_a_judge_title_is_not_quoted_even_when_a_failure_is_drafted(kg_repo):
    finding_units(kg_repo, "Edge case not handled", ["a", "b", "c"], source="judge")
    failing_units(kg_repo, "a", "b")
    run_propose(kg_repo)
    for path in (kg_repo.root / INBOX).rglob("*"):
        if path.is_file():
            assert "Edge case" not in path.read_text(encoding="utf-8")


def test_the_scope_is_the_folders_of_the_changed_files_where_known(kg_repo):
    base = kg_repo.commit("main", {"src/a.py": "1\n"}, "base")
    head = kg_repo.commit("work", {"src/web/b.py": "2\n", "src/api/c.py": "3\n"}, "head")
    for name in ("a", "b"):
        crit = kg_repo.criterion(f"cap{name} › Cart › Shows count")
        found = kg_repo.finding("Tests not collected individually", criterion=crit.id)
        raw = json.dumps({
            "schema": "l4/verdict@1", "round": 1, "verdict": "FAIL", "base_sha": base, "head_sha": head,
            "findings": [{"id": found.id, "title": found.title, "severity": "major", "source": "deterministic",
                          "criterion": crit.id, "spec_gap": False, "detail": "d"}],
            "criteria": [{"id": crit.id, "alias": crit.alias, "result": "fail"}],
            "gates": [], "profiles": {"judge": "", "implementer": []},
        }).encode()  # fmt: skip
        kg_repo.unit(f"openspec:{name}", where="base", verdicts=[kg_repo.verdict(1, raw=raw)])
    (draft,) = drafts(run_propose(kg_repo))
    (lesson,) = parse_lessons((kg_repo.root / draft.path).read_text(encoding="utf-8")).file.lessons
    assert lesson.scope_globs == ("src/api/**", "src/web/**")


# --- pattern (c): guard rules -------------------------------------------------------------------------------


def guard(rule="frozen support file"):
    return ("guard.violation", {"path": "tests/conftest.py", "phase": "green", "rule": rule})


def test_a_guard_rule_in_two_units_becomes_a_draft(kg_repo):
    for name in ("a", "b"):
        kg_repo.unit(f"openspec:{name}", where="base", runs=[kg_repo.run(guard())])
    (draft,) = drafts(run_propose(kg_repo))
    assert (draft.kind, draft.dedupe_key) == ("c", "kg-c-frozen-support-file")
    assert draft.title == "Recurring guard rule: frozen support file"
    assert "tests/conftest.py" not in (kg_repo.root / draft.path).read_text(encoding="utf-8")  # the path is the agent's


def test_the_guard_lesson_of_curation_covers_the_rule(kg_repo):
    kg_repo.lessons(kg_repo.lesson("Guard rule repeated", "guard-violation-frozen-support-file"))
    for name in ("a", "b"):
        kg_repo.unit(f"openspec:{name}", where="base", runs=[kg_repo.run(guard())])
    (proposal,) = run_propose(kg_repo).proposals
    assert proposal.covered_by == lesson_id("guard-violation-frozen-support-file")


# --- dry run, repeats, the ignore warning, redaction --------------------------------------------------------


def test_dry_run_prints_the_files_and_writes_nothing(kg_repo):
    failing_units(kg_repo, "a", "b")
    result = run_propose(kg_repo, dry_run=True)
    assert not (kg_repo.root / INBOX).exists()
    out = result.render()
    assert f"would write {DRAFT}" in out and "TODO(person)" in out and "Evidence for" in out
    assert "wrote" not in out


def test_a_second_run_on_the_same_day_writes_the_same_bytes(kg_repo):
    failing_units(kg_repo, "a", "b")
    run_propose(kg_repo)
    before = {p: p.read_bytes() for p in (kg_repo.root / INBOX).rglob("*") if p.is_file()}
    result = run_propose(kg_repo)
    after = {p: p.read_bytes() for p in (kg_repo.root / INBOX).rglob("*") if p.is_file()}
    assert before == after and len(before) == 2
    assert drafts(result)[0].status == "unchanged"


def test_a_draft_the_person_edited_is_kept(kg_repo):
    failing_units(kg_repo, "a", "b")
    run_propose(kg_repo)
    path = kg_repo.root / DRAFT
    path.write_text(path.read_text(encoding="utf-8") + "\nMy advice.\n", encoding="utf-8")
    edited = path.read_bytes()
    (draft,) = drafts(run_propose(kg_repo))
    assert path.read_bytes() == edited and draft.status == "kept, the person edited it"


def test_a_draft_already_in_another_inbox_folder_is_not_made_twice(kg_repo):
    failing_units(kg_repo, "a", "b")
    run_propose(kg_repo, today=date(2026, 10, 13))
    (draft,) = drafts(run_propose(kg_repo))
    assert draft.status.startswith("already drafted in ")
    assert not (kg_repo.root / DRAFT).exists()


def test_the_inbox_that_git_does_not_ignore_gets_a_warning(kg_repo):
    failing_units(kg_repo, "a", "b")
    result = run_propose(kg_repo)
    expected = (
        "do not commit .serena/memories/inbox/kg-*: a committed inbox file is readable and writable by agents "
        "through Serena"
    )
    assert result.warnings == [expected]
    assert expected in result.render()


def test_an_ignored_inbox_gets_no_warning(kg_repo):
    (kg_repo.root / ".gitignore").write_text(".serena/memories/inbox/kg-*\n", encoding="utf-8")
    failing_units(kg_repo, "a", "b")
    assert run_propose(kg_repo).warnings == []


def test_scn_kg_22_a_secret_in_a_ledger_is_not_in_a_proposal(kg_repo):
    secret = "supersecretvalue99"
    reason = f"{secret} rejected: see the log"
    failing_units(kg_repo, "a", "b", reason=reason)
    redactor = Redactor({"TOKEN": secret})
    result = run_propose(kg_repo, redactor=redactor)  # the index was built without this rule
    (draft,) = drafts(result)
    for path in (kg_repo.root / INBOX).rglob("*"):
        assert secret not in path.name
        if path.is_file():
            assert secret not in path.read_text(encoding="utf-8")
    assert secret not in draft.dedupe_key and secret not in result.render()


def test_a_symlinked_inbox_is_refused(kg_repo, tmp_path):
    failing_units(kg_repo, "a", "b")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (kg_repo.root / ".serena" / "memories").mkdir(parents=True)
    (kg_repo.root / INBOX).symlink_to(elsewhere)
    with pytest.raises(L4Exit):
        run_propose(kg_repo)
    assert list(elsewhere.iterdir()) == []


def test_the_output_says_what_to_do_next(kg_repo):
    failing_units(kg_repo, "a", "b")
    out = run_propose(kg_repo).render()
    assert f"wrote {DRAFT}" in out
    assert f"l4 lessons promote {LID}" in out
    assert Path(DRAFT).name in out


def test_no_pattern_says_so(kg_repo):
    out = run_propose(kg_repo).render()
    assert "no pattern recurs in at least n = 2 units (n = 0 drafts)" in out
