"""The follow-up call for a criterion whose evidence the parts of a long diff split (L4-VER-056 to L4-VER-058):
the files of a criterion, when it is split, the groups and the bound, and how a follow-up's reply is applied."""

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from l4.config.schema import L4Config
from l4.vcs.git import Git
from l4.verifier import diffparts
from l4.verifier.diffparts import DiffEntry, DiffPart, DiffParts
from l4.verifier.judge import JudgeVerdict, parse_judge_output
from l4.verifier.judge_followup import (
    Split,
    apply_followups,
    criterion_files,
    find_splits,
    plan_followups,
    proof_tasks,
    split_note,
    task_files,
)
from l4.verifier.types import CriterionEvidence, TracingTest

from .conftest import judge_reply

C1, C2, C3, C9 = "C-00000001", "C-00000002", "C-00000003", "C-00000009"
UNIT_DIRS = ["openspec/changes/u"]
TASKS_MD = "openspec/changes/u/tasks.md"
CFG = L4Config()


def entry(path: str, size: int = 10, text: str | None = None) -> DiffEntry:
    """An entry of `size` characters (its text is short when it is big: only its length is read)."""
    body = text if text is not None else "x" * min(size, 50)
    return DiffEntry((path,), body, chars=size)


def make_parts(*parts: list[DiffEntry], unseen: list[tuple[str, int]] = (), cut: tuple[int, ...] = (), reserve=0):  # type: ignore[assignment]
    built = tuple(
        DiffPart(i, tuple(entries), cut=i in cut, limit=diffparts.MAX_PART_CHARS - reserve)
        for i, entries in enumerate(parts, 1)
    )
    return DiffParts(
        built,
        tuple(p for p, _ in unseen),
        sum(e.length for p in built for e in p.entries),
        tuple(n for _, n in unseen),
        reserve,
    )


def verdict(*answers: tuple[str, str, list[str]], **over) -> JudgeVerdict:
    """A reply: (criterion, verdict word, cited refs) per answer."""
    reply = judge_reply([], **over)
    reply["criteria"] = [
        {
            "id": cid,
            "verdict": word,
            "evidence": [{"kind": "file", "ref": ref, "quote": "x"} for ref in refs]
            or [{"kind": "log", "ref": "gate"}],
        }
        for cid, word, refs in answers
    ]
    parsed = parse_judge_output(reply)
    assert isinstance(parsed, JudgeVerdict), parsed
    return parsed


def covered(cid: str, *tests: str, state: str = "covered", held: str = "", adequate: bool = True):
    return CriterionEvidence(
        cid,
        "alias",
        state,  # type: ignore[arg-type]
        tuple(TracingTest(t, "passed", "red_assertion", adequate=adequate) for t in tests),
        held=held,
    )


def two_part_world():
    """SCN-VER-193's diff: export in part 1, the report's test, code and format helper in part 2."""
    report_test = "+from app.report import header\n+from app.util import helper\n+def test_header(): pass\n"
    return make_parts(
        [entry("src/app/export.py", 100), entry("tests/test_export.py", 50)],
        [
            entry("src/app/format.py", 20),
            entry("src/app/report.py", 30),
            entry("tests/test_report.py", 40, report_test),
            entry(TASKS_MD, 5),
        ],
    )


def test_the_files_come_in_order_from_the_records_and_the_diff_only():
    parts = two_part_world()
    replies = [
        verdict((C1, "insufficient_evidence", ["src/app/export.py:40", "docs/old.md:3"])),
        verdict((C1, "insufficient_evidence", [])),
    ]
    evidence = covered(C1, "tests.test_report::test_header", "test_header")
    task_changes = {"1.2": frozenset({"src/app/report.py", "src/app/format.py", ".l4/ledger/r1.jsonl", TASKS_MD})}
    primary, secondary = criterion_files(
        C1,
        replies=replies,
        evidence=evidence,
        parts=parts,
        tasks=["1.2"],
        task_files=task_changes,
        unit_dirs=UNIT_DIRS,
        cfg=CFG,
    )
    assert primary + secondary == (
        "src/app/export.py",
        "tests/test_report.py",
        "src/app/report.py",
        "src/app/format.py",
    )
    assert primary == ("src/app/export.py", "tests/test_report.py", "src/app/report.py")
    for never in ("docs/old.md", "src/app/util.py", ".l4/ledger/r1.jsonl", TASKS_MD, "tasks.md"):
        assert never not in primary + secondary


@pytest.mark.parametrize(
    ("test_id", "path"),
    [
        ("packages.api.tests.test_x::test_y", "packages/api/tests/test_x.py"),
        ("tests.test_x::TestK::test_y", "tests/test_x.py"),
    ],
)
def test_a_dotted_pytest_id_resolves_to_its_file(test_id, path):
    parts = make_parts([entry(path, 10)], [entry("src/other.py", 10)])
    primary, _ = criterion_files(
        C1,
        replies=[],
        evidence=covered(C1, test_id),
        parts=parts,
        tasks=[],
        task_files={},
        unit_dirs=UNIT_DIRS,
        cfg=CFG,
    )
    assert primary == (path,)


def test_a_task_tick_of_tasks_md_never_makes_a_criterion_split():
    """SCN-VER-191: the task's commits also tick the unit folder's `tasks.md`, which part 2 holds."""
    parts = make_parts(
        [entry("src/app/export.py", 100), entry("tests/test_export.py", 50)],
        [entry("src/app/report.py", 30), entry(TASKS_MD, 5)],
    )
    changes = {"1.1": frozenset({"src/app/export.py", "tests/test_export.py", TASKS_MD})}
    evidence = covered(C2, "tests.test_export::test_csv")
    primary, secondary = criterion_files(
        C2, replies=[], evidence=evidence, parts=parts, tasks=["1.1"], task_files=changes, unit_dirs=UNIT_DIRS, cfg=CFG
    )
    assert TASKS_MD not in primary + secondary
    merged = verdict((C2, "insufficient_evidence", []))
    found = find_splits(
        [SimpleNamespace(id=C2)],
        merged,
        [evidence],
        parts,
        lambda cid: (primary, secondary),  # type: ignore[list-item]
    )
    assert found == []


def test_a_reference_names_the_longest_diff_path():
    parts = make_parts([entry("src/app/a.py", 10), entry("src/app/a.py.bak", 10), entry("tests/t.py", 10)])
    replies = [verdict((C1, "insufficient_evidence", ["src/app/a.py:3", "tests/t.py::test_x", "test_x"]))]
    primary, _ = criterion_files(
        C1, replies=replies, evidence=None, parts=parts, tasks=[], task_files={}, unit_dirs=UNIT_DIRS, cfg=CFG
    )
    assert primary == ("src/app/a.py", "tests/t.py")


def sh(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


def test_task_files_reads_the_task_commits_of_the_family(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    sh(repo, "init", "-q", "-b", "main")
    for key, value in (("user.email", "t@example.com"), ("user.name", "t"), ("commit.gpgsign", "false")):
        sh(repo, "config", key, value)

    counter = iter(range(1000))

    def commit(files: list[str], unit: str = "", task: str = "") -> None:
        for rel in files:
            (repo / rel).parent.mkdir(parents=True, exist_ok=True)
            (repo / rel).write_text(f"{rel} {next(counter)}\n")
            sh(repo, "add", rel)
        trailers = (f"\n\nL4-Unit: {unit}\n" if unit else "") + (f"L4-Task: {task}\n" if task else "")
        sh(repo, "commit", "-q", "-m", f"work{trailers}")

    (repo / "base.txt").write_text("b\n")
    sh(repo, "add", "base.txt")
    sh(repo, "commit", "-q", "-m", "base")
    base = sh(repo, "rev-parse", "HEAD")
    commit(["src/a.py"], "u", "1.2")
    commit(["src/b.py"], "u-fix-1", "1.2")  # a unit of the family
    commit(["src/c.py"], "other", "1.2")  # another unit
    commit(["src/d.py"])  # a person's commit
    commit(["src/e.py"], "u", "1.3")  # another task
    commit(["src/f.py"], "u", "1.2")
    head = sh(repo, "rev-parse", "HEAD")
    git = Git(repo)
    found = task_files(git, base, head, {"u", "u-fix-1"}, {"1.2"})
    assert found == {"1.2": frozenset({"src/a.py", "src/b.py", "src/f.py"})}
    names = [argv[argv.index("log") if "log" in argv else argv.index("diff-tree")] for argv in git.history]
    assert names.count("log") == 1 and names.count("diff-tree") == 3  # one log, one diff-tree per matching commit
    only = task_files(Git(repo), base, head, {"u"}, {"1.2"})
    assert only == {"1.2": frozenset({"src/a.py", "src/f.py"})}


class _Event:
    def __init__(self, type_: str, **data) -> None:
        self.type, self.data = type_, data


def test_the_tasks_of_a_criterion_come_from_red_ok_criteria():
    events = [
        _Event("task.red_ok", task="1.1", criteria={C1: {"tests": ["t::a"]}, C2: {}}),
        _Event("task.red_ok", task="9.9", fix_unit="u-fix-1", criteria={C1: {"tests": ["t::z"]}}),
        _Event("task.red_ok", task="1.2", criteria={C1: {"discriminating": ["t::b"]}}),
        _Event("task.done", task="1.3", criteria={C1: {"tests": ["t::c"]}}),
        _Event("task.red_ok", task="1.1", criteria={C1: {"tests": ["t::a"]}}),  # the same task twice: once
    ]
    assert proof_tasks(events) == {C1: ("1.1", "1.2")}  # type: ignore[arg-type]


# ---- when a criterion is split (D3) -------------------------------------------------------------------------------


def splits_for(*, merged, trace, criteria=(C1,), parts=None, files=None):
    parts = parts or two_part_world()
    calls: list[str] = []
    both = (("src/app/export.py", "src/app/report.py"), ())

    def files_of(cid):
        calls.append(cid)
        return (files or {}).get(cid, both)

    found = find_splits([SimpleNamespace(id=c) for c in criteria], merged, trace, parts, files_of)  # type: ignore[arg-type]
    return found, calls


INSUFFICIENT = verdict((C1, "insufficient_evidence", []))


def test_a_criterion_is_split_only_when_all_five_hold():
    found, _ = splits_for(merged=INSUFFICIENT, trace=[covered(C1, "t::a")])
    assert found == [Split(C1, (1, 2), ("src/app/export.py", "src/app/report.py"), 2)]
    ok = [covered(C1, "t::a")]
    for merged in (verdict((C1, "pass", [])), verdict((C1, "fail", [])), verdict((C1, "not_verifiable", []))):
        assert splits_for(merged=merged, trace=ok)[0] == []
    # not covered, held, a fail, or a criterion whose only passing test the parts called inadequate
    for trace in (
        [covered(C1)],
        [covered(C1, "t::a", held="a failed audit test")],
        [covered(C1, "t::a", state="uncovered")],
        [covered(C1, "t::a", state="fail")],
        [covered(C1, "t::a", adequate=False)],
        [],
    ):
        assert splits_for(merged=INSUFFICIENT, trace=trace)[0] == []
    # the files lie in one part, in no judged part, or one in a part and the rest in no part
    one = {C1: (("src/app/export.py", "tests/test_export.py"), ())}
    assert splits_for(merged=INSUFFICIENT, trace=ok, files=one)[0] == []
    gone = {C1: (("data/never.json",), ())}
    assert splits_for(merged=INSUFFICIENT, trace=ok, files=gone)[0] == []
    # one part's diff is never split
    single = make_parts([entry("src/app/export.py", 10), entry("src/app/report.py", 10)])
    assert splits_for(merged=INSUFFICIENT, trace=ok, parts=single)[0] == []


def test_a_cut_part_counts_as_its_part_and_secondary_files_count():
    parts = make_parts([entry("src/a.py", 200_000)], [entry("src/b.py", 10)], cut=(1,))
    found, _ = splits_for(
        merged=INSUFFICIENT, trace=[covered(C1, "t::a")], parts=parts, files={C1: (("src/a.py",), ("src/b.py",))}
    )
    assert found == [Split(C1, (1, 2), ("src/a.py", "src/b.py"), 1)]


def test_no_git_command_without_a_candidate():
    """SCN-VER-193: a merged verdict with no covered `insufficient_evidence` never asks for a criterion's files."""
    merged = verdict((C1, "pass", []), (C2, "insufficient_evidence", []))
    found, calls = splits_for(merged=merged, trace=[covered(C1, "t::a"), covered(C2)], criteria=(C1, C2))
    assert found == [] and calls == []
    found, calls = splits_for(merged=INSUFFICIENT, trace=[covered(C1, "t::a")])
    assert calls == [C1] and len(found) == 1


# ---- the groups and the bound (D4) --------------------------------------------------------------------------------


def split(cid, files, primary=None, parts_of=(1, 2)):
    return Split(cid, tuple(parts_of), tuple(files), len(files) if primary is None else primary)


def test_files_are_taken_while_they_fit():
    cap = diffparts.MAX_PART_CHARS - 1000
    parts = make_parts(
        [entry("src/a.py", cap - 10), entry("src/big.py", 500)],
        [entry("src/c.py", 10), entry("src/d.py", 5)],
        reserve=1000,
    )
    groups, records = plan_followups([split(C1, ["src/a.py", "src/big.py", "src/c.py", "src/d.py"])], parts)
    assert records == {}
    (group,) = groups
    # big.py does not fit after a.py and is skipped; c.py (10) fits; d.py does not
    assert [e.paths[-1] for e in group.entries] == ["src/a.py", "src/c.py"]
    assert [p for p, _, _ in group.not_shown] == ["src/big.py", "src/d.py"]


def test_a_cut_or_unseen_file_is_never_shown():
    """SCN-VER-198."""
    parts = make_parts([entry("src/app/seed.py", 10)], [entry("data/seed.json", 300_000)], cut=(2,))
    groups, records = plan_followups([split(C1, ["src/app/seed.py", "data/seed.json"])], parts)
    assert groups == [] and records[C1]["outcome"] == "no_fit"
    assert ("data/seed.json", 2, 300_000) in [tuple(x) for x in records[C1]["not_shown"]]
    two = make_parts([entry("src/app/a.py", 80_000)], [entry("src/app/b.py", 70_000)])
    groups, records = plan_followups([split(C1, ["src/app/a.py", "src/app/b.py"])], two)
    assert groups == [] and records[C1]["outcome"] == "no_fit"
    unseen = make_parts([entry("src/x.py", 10)], [entry("src/y.py", 10)], unseen=[("src/z.py", 10)])
    groups, _ = plan_followups([split(C1, ["src/x.py", "src/z.py", "src/y.py"])], unseen)
    (group,) = groups
    assert [e.paths[-1] for e in group.entries] == ["src/x.py", "src/y.py"]
    assert ("src/z.py", 0, 10) in group.not_shown


def test_criteria_share_a_group_when_their_files_fit():
    """SCN-VER-197, first case: three parts, files of 50000, 40000 and 60000 characters."""
    parts = make_parts(
        [entry("src/a.py", 50_000), entry("src/b.py", 40_000)], [entry("src/c.py", 60_000)], [entry("src/d.py", 10)]
    )
    splits = [
        split(C1, ["src/a.py", "src/d.py"], parts_of=(1, 3)),
        split(C2, ["src/b.py", "src/d.py"], parts_of=(1, 3)),
        split(C3, ["src/c.py", "src/d.py"], parts_of=(2, 3)),
    ]
    groups, records = plan_followups(splits, parts)
    assert [g.criteria for g in groups] == [(C1, C2), (C3,)] and records == {}
    assert [g.index for g in groups] == [1, 2]
    assert groups[0].parts == (1, 3)


def test_the_calls_are_bounded_by_the_parts():
    """SCN-VER-197, second case: two parts, three criteria whose files are 70000 characters each."""
    parts = make_parts(
        [entry("src/a1.py", 35_000), entry("src/a2.py", 35_000), entry("src/a3.py", 35_000)],
        [entry("src/b1.py", 35_000), entry("src/b2.py", 35_000), entry("src/b3.py", 35_000)],
    )
    splits = [
        split(C1, ["src/a1.py", "src/b1.py"]),
        split(C2, ["src/a2.py", "src/b2.py"]),
        split(C3, ["src/a3.py", "src/b3.py"]),
    ]
    groups, records = plan_followups(splits, parts)
    assert [g.criteria for g in groups] == [(C1,), (C2,)]
    assert records[C3]["outcome"] == "no_call_left" and records[C3]["calls"] == 2 and records[C3]["followup"] is None


def test_primary_files_group_first_and_task_files_fill_the_rest():
    parts = make_parts(
        [entry("src/a.py", 50_000), entry("src/b.py", 50_000)], [entry("src/s1.py", 60_000), entry("src/s2.py", 60_000)]
    )
    splits = [
        split(C1, ["src/a.py", "src/s1.py"], primary=1, parts_of=(1, 2)),
        split(C2, ["src/b.py", "src/s2.py"], primary=1, parts_of=(1, 2)),
    ]
    (group,), _ = plan_followups(splits, parts)  # the primary files of both fit together (100000)
    assert group.criteria == (C1, C2)
    # the secondary files take what room is left, and never the room of the other criterion's primary file
    assert [e.paths[-1] for e in group.entries] == ["src/a.py", "src/b.py"]
    assert {p for p, _, _ in group.not_shown} == {"src/s1.py", "src/s2.py"}
    small = make_parts([entry("src/a.py", 50_000), entry("src/b.py", 50_000)], [entry("src/s1.py", 10_000)])
    pair = [split(C1, ["src/a.py", "src/s1.py"], primary=1), split(C2, ["src/b.py", "src/s1.py"], primary=1)]
    (group,), _ = plan_followups(pair, small)
    assert [e.paths[-1] for e in group.entries] == ["src/a.py", "src/b.py", "src/s1.py"] and group.not_shown == ()


def test_a_groups_files_are_in_part_order():
    parts = make_parts([entry("src/a.py", 10), entry("src/b.py", 10)], [entry("src/c.py", 10)])
    groups, _ = plan_followups([split(C1, ["src/c.py", "src/b.py", "src/a.py"])], parts)
    assert [e.paths[-1] for e in groups[0].entries] == ["src/a.py", "src/b.py", "src/c.py"]


def test_the_same_input_gives_the_same_groups():
    parts = make_parts([entry("src/a.py", 10)], [entry("src/b.py", 10)])
    splits = [split(C1, ["src/a.py", "src/b.py"])]
    assert plan_followups(splits, parts) == plan_followups(splits, parts)


# ---- applying a follow-up and the note (D7, D8) -------------------------------------------------------------------


def merged_of(*answers, **over):
    return verdict(*answers, **over)


def test_a_follow_up_replaces_only_its_criteria():
    """SCN-VER-201."""
    merged = merged_of((C1, "insufficient_evidence", []), (C2, "insufficient_evidence", []), (C9, "pass", []))
    reply = verdict((C1, "pass", []), (C9, "fail", []))
    out = apply_followups(merged, [((C1, C2), reply)])
    assert [(c.id, c.verdict) for c in out.criteria] == [(C1, "pass"), (C2, "insufficient_evidence"), (C9, "pass")]


def test_a_follow_up_changes_only_its_own_group():
    merged = merged_of((C1, "insufficient_evidence", []), (C2, "pass", []))
    reply = verdict(
        (C1, "pass", []),
        test_adequacy=[
            {"test": "t::x", "criterion": "", "adequate": False, "reason": "no"},
            {"test": "t::y", "criterion": C2, "adequate": False, "reason": "no"},
            {"test": "t::z", "criterion": C1, "adequate": False, "reason": "weak"},
        ],
        findings=[
            {"severity": "minor", "criterion": "", "title": "stray", "detail": "d", "evidence": []},
            {"severity": "minor", "criterion": C2, "title": "other", "detail": "d", "evidence": []},
            {"severity": "minor", "criterion": C1, "title": "mine", "detail": "d", "evidence": []},
        ],
    )
    out = apply_followups(merged, [((C1,), reply)])
    assert [(a.test, a.criterion) for a in out.test_adequacy] == [("t::z", C1)]
    assert [f.title for f in out.findings] == ["mine"]
    assert {c.id: c.verdict for c in out.criteria} == {C1: "pass", C2: "pass"}


def test_adequacy_and_findings_merge_as_a_parts():
    merged = merged_of(
        (C1, "insufficient_evidence", []),
        test_adequacy=[{"test": "t::a", "criterion": C1, "adequate": True, "reason": "ok"}],
        findings=[{"severity": "minor", "criterion": C1, "title": "Same  title", "detail": "d", "evidence": []}],
        feedback=[{"id": "FB-001", "addressed": True, "evidence": "e"}],
    )
    reply = verdict(
        (C1, "pass", []),
        test_adequacy=[{"test": "t::a", "criterion": C1, "adequate": False, "reason": "reason of its own"}],
        findings=[{"severity": "minor", "criterion": C1, "title": "same title", "detail": "d2", "evidence": []}],
        feedback=[{"id": "FB-001", "addressed": False, "evidence": "other"}],
    )
    out = apply_followups(merged, [((C1,), reply)])
    (adequacy,) = out.test_adequacy
    assert adequacy.adequate is False and adequacy.reason == "reason of its own"
    assert len(out.findings) == 1
    assert out.feedback is not None and out.feedback[0].addressed is True and out.feedback[0].evidence == "e"
    assert out.riskiest_assumptions == merged.riskiest_assumptions


def record(outcome, **over):
    base = {
        "parts": [1, 2],
        "outcome": outcome,
        "followup": 1,
        "files": 3,
        "not_shown": [],
        "answer": None,
        "status": None,
    }
    return {**base, **over}


def test_the_note_of_each_outcome():
    head = "its evidence was split over parts 1 and 2 of the diff: "
    assert split_note(None) == "" and split_note({}) == ""
    assert split_note(record("answered", answer="pass")) == (
        head + "follow-up call 1 judged its 3 files of those parts together and answered pass"
    )
    shown = [("a.py", 1, 5), ("b.py", 2, 5), ("c.py", 2, 5)]
    assert split_note(record("answered", answer="insufficient_evidence", not_shown=shown[:2])).endswith(
        "answered insufficient_evidence (2 not shown: a.py, b.py)"
    )
    four = [*shown, ("d.py", 2, 5), ("e.py", 2, 5)]
    assert split_note(record("answered", answer="pass", not_shown=four)).endswith(
        "answered pass (5 not shown: a.py, b.py, c.py, +2 more)"
    )
    assert split_note(record("not_answered")) == (
        head + "follow-up call 1 judged its files of those parts together but gave no verdict for it, so the parts' "
        "verdict stands"
    )
    assert split_note(record("no_answer", status="schema_invalid")) == (
        head + "follow-up call 1 gave no usable answer (schema_invalid), so the parts' verdict stands"
    )
    assert split_note(record("no_answer", status="limit")).endswith("(limit), so the parts' verdict stands")
    assert split_note(record("no_fit", followup=None)) == (
        head + "no follow-up call was made, because its files of those parts do not fit in one part together"
    )
    assert split_note(record("no_call_left", followup=None, calls=2)) == (
        head + "no follow-up call was made, because the round's 2 follow-up calls were used"
    )
    assert split_note(record("answered", parts=[1, 2, 4], answer="pass")).startswith(
        "its evidence was split over parts 1, 2 and 4 of the diff: "
    )


def test_the_file_list_names_every_file_shown_first_and_capped():
    from l4.verifier.judge_followup import followup_rows

    many = [entry(f"src/f_{n:03d}.py", 10) for n in range(260)]
    parts = make_parts(many[:130], many[130:])
    groups, _ = plan_followups([split(C1, ["src/f_250.py", "src/f_005.py"])], parts)
    rows, more = followup_rows(parts, groups[0])
    assert [r[0] for r in rows[:2]] == ["src/f_005.py", "src/f_250.py"] and all(r[3] for r in rows[:2])
    assert rows[0][1:] == (1, 10, True) and rows[1][1:] == (2, 10, True)
    assert len(rows) == 200 and more == 60 and not any(r[3] for r in rows[2:])
    assert [r[0] for r in rows[2:5]] == ["src/f_000.py", "src/f_001.py", "src/f_002.py"]
    tight = make_parts([entry("src/a.py", 10)], [entry("src/b.py", 10)], unseen=[("data/z.json", 99)])
    (group,), _ = plan_followups([split(C1, ["src/a.py", "src/b.py"])], tight)
    rows, more = followup_rows(tight, group)
    assert rows[-1] == ("data/z.json", 0, 99, False) and more == 0
