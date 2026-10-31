"""own-test-repair (L4-VER-073): the verifier accepts a repair of the repaired tests only, and only the edit a person
accepted: the question's raise recorded the blob of each file before and after, a person's answer follows it, and the
replay used the same patch."""

import pytest

from l4.state.ledger import LedgerEvent
from l4.verifier.integrity import (
    check_freeze,
    check_tdd_history,
    check_test_paths,
    check_tests,
    run_integrity,
)
from l4.verifier.types import Severity

from ._integrity_helpers import STAMP, UNIT, UNIT_DIR, event, new_repo, task


def exempt(seq: int, **data: object) -> LedgerEvent:
    """`task.tdd_exempt` (its `kind` is a data key, which `event` cannot take)."""
    return LedgerEvent(STAMP, "r-20261004T0000Z-aaaa", UNIT, seq, "task.tdd_exempt", {"kind": "harness", **data})


FIX = "add-thing-fix-1"
FIX_UNIT = f"openspec:{FIX}"
A = "def test_x():\n    assert helper(1)\n"
A_REPAIRED = "def test_x():\n    assert helper()\n"
B = "def test_y():\n    assert True\n"
B_CHANGED = "def test_y():\n    assert 1\n"


PATCH = "a" * 64
ACCEPTED = "differs from the edit a person accepted"


def chain(
    seq: int,
    *,
    step: str,
    b0: str,
    b1: str,
    task_key: str = "1.1",
    path: str = "e2e/test_a.py",
    over=None,
    skip=(),
    order=None,
) -> list[LedgerEvent]:
    """The question chain of an accepted repair, from `seq`: its raise (with the digest and the blobs), a person's
    answer, the replay, and the `task.repaired` that names them. `over` maps an event type to the keys it changes;
    `skip` leaves events out, `order` puts the types in another order."""
    over = over or {}
    base = {"task": task_key, "fix_unit": FIX}
    data = {
        "question.raised": {
            "id": "Q-001",
            "kind": "harness",
            "check": "repair",
            "patch_sha256": PATCH,
            "saved": True,
            "repair_blobs": {path: [b0, b1]},
            **base,
        },
        "question.answered": {"id": "Q-001", "by": "human", "answer_sha256": "d" * 64, "fix_unit": FIX},
        "held.replayed": {"question": "Q-001", "check": "repair", "patch_sha256": PATCH, **base},
        "task.repaired": {
            "files": [path],
            "tests": [f"{path}::test_x"],
            "question": "Q-001",
            "patch_sha256": PATCH,
            **base,
        },
    }
    events = []
    for kind in order or ["question.raised", "question.answered", "held.replayed", "task.repaired"]:
        if kind not in skip:
            merged = {**data[kind], **over.get(kind, {})}
            events.append(LedgerEvent(STAMP, "r-20261004T0000Z-aaaa", UNIT, seq + len(events), kind, merged))
    return events


def repair_history(
    tmp_path,
    git_environ,
    *,
    events=None,
    extra=None,
    tdd="exempt",
    unit=FIX_UNIT,
    task_key="1.1",
    text=A_REPAIRED,
    over=None,
    skip=(),
    order=None,
):
    """Base; the unit's red commit adds `e2e/test_a.py` and `e2e/test_b.py`; its green commit; then a fix unit's step
    commit that repairs `e2e/test_a.py` (and `extra`). `events` default: what an accepted repair writes (the raise with
    the blobs of the commit, a person's answer, the replay, `task.repaired`); `over`, `skip`, `order`: see `chain`."""
    repo, base = new_repo(tmp_path, git_environ, {"README.md": "x\n"})
    repo.write({"e2e/test_a.py": A, "e2e/test_b.py": B})
    red = repo.commit("red", task="1.1", tdd="red")
    repo.write({"src/app.py": "x = 1\n"})
    green = repo.commit("green", task="1.1", tdd="green")
    repo.write({"e2e/test_a.py": text, **(extra or {})})
    step = repo.commit("repair", task=task_key, tdd=tdd, unit=unit)
    b0 = repo.git("rev-parse", f"{step}^:e2e/test_a.py").strip()
    b1 = repo.git("rev-parse", f"{step}:e2e/test_a.py").strip()
    repo.events = events or [
        event(
            "task.red_ok",
            1,
            task="1.1",
            sha=red,
            frozen=["e2e/test_a.py", "e2e/test_b.py"],
            tests=["e2e.test_a::test_x"],
        ),
        event("task.done", 2, task="1.1", sha=green, tdd="green"),
        *chain(3, step=step, b0=b0, b1=b1, task_key=task_key, over=over, skip=skip, order=order),
        exempt(7, task=task_key, fix_unit=FIX, sha=step, finding="F-1", findings=["F-1"]),
        event("task.done", 8, task=task_key, fix_unit=FIX, sha=step, tdd="exempt"),
    ]
    return repo, base, step


def paths_of(out) -> str:
    return " ".join(f.detail for f in out.findings)


def test_an_exempt_commit_may_change_the_files_its_repaired_event_names_and_nothing_else(
    tmp_path, git_environ
):  # SCN-VER-278
    repo, base, step = repair_history(tmp_path, git_environ, extra={"e2e/test_b.py": B_CHANGED})
    ctx = repo.context(base, step, tasks=[(UNIT, task("1.1")), (FIX_UNIT, task("1.1"))])
    out = check_test_paths(ctx)
    [finding] = out.findings
    assert (
        finding.severity is Severity.BLOCKER
        and finding.title == "a test file changed in a step that may not change tests"
    )
    assert "e2e/test_b.py" in finding.detail and "e2e/test_a.py" not in finding.detail


def test_a_repair_commit_that_changes_only_the_repaired_file_is_accepted(tmp_path, git_environ):
    repo, base, step = repair_history(tmp_path, git_environ)
    assert check_test_paths(repo.context(base, step)).findings == []


def test_a_plain_exempt_commit_that_changes_the_same_file_is_still_a_blocker(
    tmp_path, git_environ
):  # SCN-IMP-461 (verifier)
    events = [
        exempt(1, task="1.1", fix_unit=FIX, finding="F-1", findings=["F-1"]),
        event("task.done", 2, task="1.1", fix_unit=FIX, tdd="exempt"),
    ]
    repo, base, step = repair_history(tmp_path, git_environ, events=events)
    assert "e2e/test_a.py" in paths_of(check_test_paths(repo.context(base, step)))


def test_a_repaired_event_of_another_task_unit_or_a_green_commit_does_not_allow_the_change(tmp_path, git_environ):
    named = lambda **over: [  # noqa: E731
        event("task.repaired", 1, **{"task": "1.1", "fix_unit": FIX, "files": ["e2e/test_a.py"], **over}),
        event("task.done", 2, task="1.1", fix_unit=FIX, tdd="exempt"),
    ]
    cases = [
        (named(task="2.1"), {}),  # another task
        (named(fix_unit="add-thing-fix-2"), {}),  # another fix unit
        (named(), {"tdd": "green"}),  # a green commit: only an exempt one has the exception
    ]
    for n, (events, over) in enumerate(cases):
        folder = tmp_path / str(n)
        folder.mkdir()
        repo, base, step = repair_history(folder, git_environ, events=events, **over)
        assert "e2e/test_a.py" in paths_of(check_test_paths(repo.context(base, step))), (n, events)


def test_the_other_checks_do_not_see_a_repair_commit_of_the_units_own_test(tmp_path, git_environ):
    """The red-freeze check compares red and green of one task; the pre-existing-test check compares the base's tests; a
    repair commit is neither, so only the test-path check needs the exception (SCN-VER-278 asks for both)."""
    repo, base, step = repair_history(tmp_path, git_environ)
    ctx = repo.context(base, step, tasks=[(UNIT, task("1.1")), (FIX_UNIT, task("1.1"))])
    for check in (check_freeze, check_tests, check_test_paths, check_tdd_history):
        assert check(ctx).findings == [], check.__name__
    report = run_integrity(ctx)
    assert not report.blocked, [(c.name, c.status) for c in report.checks]
    assert UNIT_DIR  # the unit directory of the helper


def test_a_repair_commit_that_breaks_the_structural_rules_is_a_blocker_even_when_its_event_names_the_file(
    tmp_path, git_environ
):
    cases = {
        "an assert removed": "def test_x():\n    helper()\n",
        "a vacuous assert": "def test_x():\n    assert helper() or 1 == 1\n",
        "an early return": "def test_x():\n    return\n    assert helper()\n",
        "another test added": A_REPAIRED + "\n\ndef test_z():\n    assert True\n",
    }
    for n, (label, text) in enumerate(cases.items()):
        folder = tmp_path / str(n)
        folder.mkdir()
        repo, base, step = repair_history(folder, git_environ, text=text)
        out = check_test_paths(repo.context(base, step))
        [finding] = out.findings
        assert (
            finding.severity is Severity.BLOCKER and "repair" in finding.title and "e2e/test_a.py" in finding.detail
        ), label


def test_a_repair_commit_whose_file_declares_another_encoding_is_a_blocker(tmp_path, git_environ):
    repo, base, step = repair_history(tmp_path, git_environ, text="# coding: utf-7\n" + A_REPAIRED)
    [finding] = check_test_paths(repo.context(base, step)).findings
    assert "encoding" in finding.detail and "utf-7" in finding.detail


def test_a_repaired_event_that_names_a_file_but_no_test_of_it_allows_no_change(tmp_path, git_environ):
    events = [
        event("task.repaired", 1, task="1.1", fix_unit=FIX, files=["e2e/test_a.py"], tests=[]),
        event("task.done", 2, task="1.1", fix_unit=FIX, tdd="exempt"),
    ]
    repo, base, step = repair_history(tmp_path, git_environ, events=events)
    assert check_test_paths(repo.context(base, step)).findings  # nothing to check the file against: refused


def test_a_file_a_repair_adds_is_a_blocker(tmp_path, git_environ):
    repo, base = new_repo(tmp_path, git_environ, {"README.md": "x\n"})
    repo.write({"e2e/test_a.py": A})
    repo.commit("red", task="1.1", tdd="red")
    start = repo.git("rev-parse", "HEAD").strip()
    repo.write({"e2e/test_new.py": A})
    step = repo.commit("repair", task="1.1", tdd="exempt", unit=FIX_UNIT)
    repo.events = [
        event(
            "task.repaired", 1, task="1.1", fix_unit=FIX, files=["e2e/test_new.py"], tests=["e2e/test_new.py::test_x"]
        ),
    ]
    assert start and check_test_paths(repo.context(base, step)).findings  # no parent blob: no repair


# --- the verifier accepts exactly the edit a person accepted (D6) ---------------------------------------------------

RAISED, ANSWERED, REPLAYED, REPAIRED = "question.raised", "question.answered", "held.replayed", "task.repaired"


def differs(out) -> str:
    """The one blocker of an edit that is not the accepted one: its detail."""
    [finding] = out.findings
    assert finding.severity is Severity.BLOCKER and finding.title == f"a repaired test {ACCEPTED}", finding
    return finding.detail


def blocked_by(tmp_path, git_environ, **changes) -> str:
    repo, base, step = repair_history(tmp_path, git_environ, **changes)
    detail = differs(check_test_paths(repo.context(base, step)))
    assert "e2e/test_a.py" in detail and "task 1.1" in detail and step[:10] in detail
    return detail


def test_a_commit_that_is_exactly_the_accepted_edit_is_accepted(tmp_path, git_environ):  # SCN-VER-281
    repo, base, step = repair_history(tmp_path, git_environ)
    assert check_test_paths(repo.context(base, step)).findings == []


# condition 1: the event names a question and a patch_sha256
@pytest.mark.parametrize(
    ("key", "words"),
    [("question", "names no question"), ("patch_sha256", "names no patch_sha256")],
)
def test_a_repaired_event_without_a_question_or_a_digest_is_a_blocker(tmp_path, git_environ, key, words):
    # SCN-VER-282
    assert words in blocked_by(tmp_path, git_environ, over={REPAIRED: {key: None}})


def test_a_repaired_event_of_the_first_design_with_no_question_is_a_blocker(tmp_path, git_environ):  # SCN-VER-282
    events = [
        event("task.repaired", 1, task="1.1", fix_unit=FIX, files=["e2e/test_a.py"], tests=["e2e/test_a.py::test_x"]),
        exempt(2, task="1.1", fix_unit=FIX, finding="F-1", findings=["F-1"]),
        event("task.done", 3, task="1.1", fix_unit=FIX, tdd="exempt"),
    ]
    assert "names no question" in blocked_by(tmp_path, git_environ, events=events)


# condition 2: the raise of the unit's ledger
@pytest.mark.parametrize(
    ("changes", "label"),
    [
        ({"skip": (RAISED,)}, "no raise"),
        ({"over": {RAISED: {"check": "tests"}}}, "a raise of another check"),
        ({"over": {RAISED: {"check": None}}}, "a raise with no check"),
        ({"over": {RAISED: {"kind": "technical"}}}, "a raise of another kind"),
        ({"over": {RAISED: {"task": "2.1"}}}, "a raise of another task"),
        ({"over": {RAISED: {"id": "Q-002"}}}, "a raise of another question"),
        ({"over": {RAISED: {"fix_unit": "add-thing-fix-2"}}}, "a raise of another fix unit"),
        ({"over": {RAISED: {"patch_sha256": "b" * 64}}}, "a raise with another digest"),
        ({"over": {RAISED: {"patch_sha256": None}}}, "a raise with no digest"),
        ({"over": {RAISED: {"repair_blobs": None}}}, "a raise with no blobs"),
        ({"over": {RAISED: {"repair_blobs": {"e2e/test_b.py": ["1" * 40, "2" * 40]}}}}, "blobs of another file"),
    ],
)
def test_a_repair_with_no_matching_raise_of_check_repair_is_a_blocker(tmp_path, git_environ, changes, label):
    # SCN-VER-282
    assert "question.raised" in blocked_by(tmp_path, git_environ, **changes), label


# condition 3: a person's answer after the raise
@pytest.mark.parametrize("by", ["agent", "delegate", "clarifier"])
def test_a_repair_whose_only_answer_is_not_a_persons_is_a_blocker(tmp_path, git_environ, by):  # SCN-VER-282
    detail = blocked_by(tmp_path, git_environ, over={ANSWERED: {"by": by}})
    assert "no answer by a person" in detail


def test_a_repair_with_no_answer_is_a_blocker(tmp_path, git_environ):
    assert "no answer by a person" in blocked_by(tmp_path, git_environ, skip=(ANSWERED,))


def test_an_answer_that_came_before_the_raise_does_not_count(tmp_path, git_environ):
    order = [ANSWERED, RAISED, REPLAYED, REPAIRED]
    assert "no answer by a person" in blocked_by(tmp_path, git_environ, order=order)


@pytest.mark.parametrize("over", [{"id": "Q-002"}, {"fix_unit": "add-thing-fix-2"}])
def test_an_answer_of_another_question_or_fix_unit_does_not_count(tmp_path, git_environ, over):
    assert "no answer by a person" in blocked_by(tmp_path, git_environ, over={ANSWERED: over})


def test_a_person_s_answer_counts_when_an_agent_s_precedes_it(tmp_path, git_environ):
    repo, base, step = repair_history(tmp_path, git_environ)
    first = [e for e in repo.events if e.type == RAISED][0]
    repo.events.insert(
        repo.events.index(first) + 1, event(ANSWERED, 90, id="Q-001", by="agent", fix_unit=FIX, answer_sha256="e" * 64)
    )
    assert check_test_paths(repo.context(base, step)).findings == []


# condition 4: the replay used the same patch
def test_a_repair_with_no_replay_of_its_question_is_a_blocker(tmp_path, git_environ):
    assert "held.replayed" in blocked_by(tmp_path, git_environ, skip=(REPLAYED,))


@pytest.mark.parametrize(
    "over",
    [{"patch_sha256": "b" * 64}, {"patch_sha256": None}, {"question": "Q-002"}, {"fix_unit": "add-thing-fix-2"}],
)
def test_a_replay_of_another_patch_or_question_is_a_blocker(tmp_path, git_environ, over):  # SCN-VER-281
    assert "held.replayed" in blocked_by(tmp_path, git_environ, over={REPLAYED: over})


# condition 5: the blobs of the commit are those the proposal recorded
def test_a_blob_that_is_not_the_accepted_one_is_a_blocker(tmp_path, git_environ):  # SCN-VER-281
    detail = blocked_by(tmp_path, git_environ, over={RAISED: {"repair_blobs": {"e2e/test_a.py": ["f" * 40, "f" * 40]}}})
    assert "parent blob" in detail or "blob of the commit" in detail


def test_the_parent_blob_and_the_blob_are_each_compared(tmp_path, git_environ):  # SCN-VER-281
    (tmp_path / "probe").mkdir()
    repo, base, step = repair_history(tmp_path / "probe", git_environ)
    before, after = [e for e in repo.events if e.type == RAISED][0].data["repair_blobs"]["e2e/test_a.py"]
    for name, pair, words in (
        ("parent", ["f" * 40, after], "parent blob"),
        ("blob", [before, "f" * 40], "blob of the commit"),
    ):
        (tmp_path / name).mkdir()
        got = blocked_by(tmp_path / name, git_environ, over={RAISED: {"repair_blobs": {"e2e/test_a.py": pair}}})
        assert words in got, name


def test_a_commit_edited_after_the_replay_is_a_blocker(tmp_path, git_environ):
    """The accepted edit was replayed, then the file was changed again before the commit: another blob."""
    repo, base, step = repair_history(tmp_path, git_environ, text=A_REPAIRED)
    repo.write({"e2e/test_a.py": A_REPAIRED + "\n# one more line\n"})
    later = repo.commit("repair again", task="1.1", tdd="exempt", unit=FIX_UNIT)
    out = check_test_paths(repo.context(base, later))
    assert any("e2e/test_a.py" in f.detail and ACCEPTED in f.title for f in out.findings)
