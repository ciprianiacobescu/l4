"""The carry-over rule of L4-VER-072 (SCN-VER-273 to -276) at the function level.

`decide` is pure: R's stored verdict, the criteria, this round's trace, the changed paths and the answers it is given.
Every condition of D2 has a test in which it is the only one that fails, so dropping that condition from the rule fails
exactly that test. `carry_over` reads those answers through `Git` and `read_verdict` from a real repository."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from l4.specs.base import Criterion, Framework
from l4.vcs.git import Git
from l4.verifier.carryover import Decision, apply_carried, carried_verdicts, carry_over, decide
from l4.verifier.report import VERDICT_SCHEMA_ID
from l4.verifier.types import CriterionEvidence, TracingTest

A, B, C = "C-0000000a", "C-0000000b", "C-0000000c"
H1 = "a" * 40
UNIT = "openspec/changes/add-x"
DIRS = [UNIT, "openspec/changes/add-x-fix-1"]
TEST_GLOBS = ["**/tests/**", "**/test_*.*", "**/conftest.py"]
SUPPORT_GLOBS = ["**/conftest.py", "**/fixtures/**"]
T_A, T_B, T_C, T_NEW = (
    "tests.test_a::test_a",
    "tests.test_b::test_b",
    "tests.test_c::test_c",
    "tests.test_new::test_new",
)
FILES = {
    T_A: "tests/test_a.py", T_B: "tests/test_b.py", T_C: "tests/test_c.py", T_NEW: "tests/test_new.py",
    "tests.test_old::test_old": "tests/test_old.py", "tests.test_other::test_other": "tests/test_other.py",
}  # fmt: skip


def criterion(cid: str) -> Criterion:
    return Criterion(cid, f"x > {cid}", Framework.OPENSPEC, "x", "r", cid, "WHEN a THEN b", "specs/x/spec.md", 1)


def row(cid: str, verdict: str = "pass") -> dict[str, Any]:
    return {"id": cid, "verdict": verdict, "evidence": [{"kind": "log", "ref": "gate report"}]}


def stored_test(tid: str, status: str = "passed") -> dict[str, Any]:
    return {"id": tid, "status": status, "proof": "red_assertion", "adequate": True, "note": "", "over_cap": 0}


def stored_trace(cid: str, tests: tuple[str, ...], capped: tuple[str, ...] = ()) -> dict[str, Any]:
    return {
        "criterion": cid, "alias": "x", "state": "covered", "tests": [stored_test(t) for t in tests],
        "ignored": [], "held": "", "capped": [stored_test(t) for t in capped],
    }  # fmt: skip


def stored(verdicts: dict[str, str] | None = None, traces: dict[str, tuple[str, ...]] | None = None, **over) -> dict:
    """R's `verdict.json` as far as the rule reads it: three passed criteria, each traced by its own test."""
    verdicts = verdicts or {A: "pass", B: "pass", C: "pass"}
    traces = traces or {A: (T_A,), B: (T_B,), C: (T_C,)}
    base = {
        "schema": VERDICT_SCHEMA_ID, "round": 1, "head_sha": H1,
        "judge_verdict": {"criteria": [row(c, v) for c, v in verdicts.items()], "test_adequacy": []},
        "trace": [stored_trace(c, t) for c, t in traces.items()],
    }  # fmt: skip
    return {**base, **over}


def now(cid: str, tests: tuple[str, ...], *, failing: tuple[str, ...] = (), capped: tuple[str, ...] = ()):
    made = tuple(TracingTest(t, "failed" if t in failing else "passed", "red_assertion") for t in tests)
    return CriterionEvidence(
        cid, "x", "covered", made, capped=tuple(TracingTest(t, "passed", "red_assertion", over_cap=5) for t in capped)
    )  # fmt: skip


TRACE_NOW = {A: (T_A,), B: (T_B,), C: (T_C,)}


def ask(prev: dict | None = None, *, trace: dict[str, tuple[str, ...]] | None = None, changed=("tests/test_new.py",),
        same: dict[str, bool] | None = None, files: dict[str, str | None] | None = None, failing=(), capped=None,
        ) -> Decision:  # fmt: skip
    """The rule over A, B and C, which all qualify unless the arguments say otherwise."""
    prev = stored() if prev is None else prev
    trace = TRACE_NOW if trace is None else trace
    capped = capped or {}
    return decide(
        prev, [criterion(c) for c in (A, B, C)],
        [now(c, t, failing=failing, capped=capped.get(c, ())) for c, t in trace.items()], list(changed),
        unit_dirs=DIRS, test_globs=TEST_GLOBS, support_globs=SUPPORT_GLOBS,
        same_source={A: True, B: True, C: True, **(same or {})}, file_of={**FILES, **(files or {})},
    )  # fmt: skip


def only_c_is_dropped(found: Decision) -> None:
    assert sorted(found.carried) == [A, B], found


# --- SCN-VER-273: what is carried -------------------------------------------------------------------------------------


def test_scn_ver_273_a_new_test_file_that_traces_one_criterion_drops_only_that_criterion():
    found = ask(trace={**TRACE_NOW, C: (T_C, T_NEW)})
    only_c_is_dropped(found)
    assert found.from_round == 1 and found.from_head == H1 and found.reason == ""
    assert found.carried[A] == {"round": 1, "head": H1, "verdict": row(A), "adequacy": []}


def test_every_criterion_that_qualifies_is_carried():
    found = ask()
    assert sorted(found.carried) == [A, B, C] and found.reason == ""


def test_paths_of_the_unit_family_and_test_files_are_allowed_and_the_rest_are_not():
    allowed = [f"{UNIT}/.l4/evidence/round-2/verdict.json", f"{UNIT}/questions.md",
               "openspec/changes/add-x-fix-1/tasks.md",
               "tests/test_new.py", "pkg/tests/test_deep.py", "pkg/test_x.py"]  # fmt: skip
    assert sorted(ask(changed=allowed).carried) == [A, B, C]
    for path in (
        "src/app/export.py",
        "openspec/changes/other/tasks.md",
        "openspec/changes/add-xy/tasks.md",
        "README.md",
    ):
        assert ask(changed=["tests/test_new.py", path]).carried == {}


def test_the_harness_memory_is_allowed_and_a_path_that_only_looks_like_it_is_not():
    """The harness's own memory (`evidence.HARNESS_MEMORY`, written by `l4 lessons promote`, protected from agent
    steps) changes no product behaviour, so a lessons commit between the two heads carries as before."""
    assert sorted(ask(changed=["tests/test_new.py", ".serena/memories/harness/lessons.md"]).carried) == [A, B, C]
    for path in (".serena/memories/other.md", ".serena/memories/harnessx/a.md", "x/.serena/memories/harness/a.md"):
        assert ask(changed=["tests/test_new.py", path]).carried == {}


# --- SCN-VER-274: a non-test file carries nothing --------------------------------------------------------------------


def test_scn_ver_274_a_production_change_carries_nothing_and_names_the_first_five_paths():
    changed = ["tests/test_new.py", *(f"src/app/m{n}.py" for n in range(7))]
    found = ask(changed=changed)
    assert found.carried == {} and found.reason == "a non-test file changed"
    assert found.paths == tuple(f"src/app/m{n}.py" for n in range(5))
    assert found.from_round == 1


def test_scn_ver_274_a_support_file_is_not_a_test_path():
    found = ask(changed=["tests/conftest.py"])  # matches a test glob and a support glob
    assert found.carried == {} and found.reason == "a non-test file changed" and found.paths == ("tests/conftest.py",)
    assert ask(changed=["tests/fixtures/data.json"]).carried == {}


# --- SCN-VER-275: a criterion that changed, a tracing test that changed, a new tracing test ---------------------------


def test_scn_ver_275_condition_2_a_criterion_whose_source_file_changed_is_asked():
    only_c_is_dropped(ask(same={C: False}))


def test_a_source_file_with_no_answer_is_not_the_same():
    prev = stored()
    found = decide(
        prev, [criterion(c) for c in (A, B, C)], [now(c, t) for c, t in TRACE_NOW.items()], ["tests/test_new.py"],
        unit_dirs=DIRS, test_globs=TEST_GLOBS, support_globs=SUPPORT_GLOBS, same_source={A: True, B: True},
        file_of=FILES,
    )  # fmt: skip
    only_c_is_dropped(found)


def test_scn_ver_275_condition_4_a_changed_file_of_a_test_that_traced_it_then_is_asked():
    # C's test is in the changed file; the tests that trace C are the same ones, so condition 5 holds
    only_c_is_dropped(ask(changed=["tests/test_c.py"]))


def test_scn_ver_275_condition_4_a_changed_file_of_a_test_that_traced_it_only_then_is_asked():
    prev = stored(traces={A: (T_A,), B: (T_B,), C: (T_C, "tests.test_old::test_old")})
    # the old test no longer traces C (condition 5 holds: now is a subset), but its file changed
    only_c_is_dropped(ask(prev, changed=["tests/test_old.py"]))


def test_scn_ver_275_condition_4_a_changed_file_of_a_candidate_that_traces_it_now_is_asked():
    prev = stored(traces={A: (T_A,), B: (T_B,), C: (T_C,)})
    # a test over the cap traces C now (in `capped`, not a tracing test): the judge could have it counted
    found = ask(prev, changed=["tests/test_new.py"], capped={C: (T_NEW,)})
    only_c_is_dropped(found)
    assert sorted(ask(prev, changed=["tests/test_other.py"], capped={C: (T_NEW,)}).carried) == [A, B, C]


def test_scn_ver_275_condition_5_a_new_tracing_test_in_an_unchanged_file_is_asked():
    # tests/test_other.py did not change, so condition 4 holds: only the subset rule drops C
    other = "tests.test_other::test_other"
    only_c_is_dropped(ask(trace={**TRACE_NOW, C: (T_C, other)}, changed=["tests/test_new.py"]))


def test_scn_ver_276_condition_5_a_tracing_test_that_does_not_pass_now_is_asked():
    only_c_is_dropped(ask(failing=(T_C,)))


def test_a_tracing_test_whose_file_is_not_found_is_asked():
    only_c_is_dropped(ask(files={T_C: None}))


# --- SCN-VER-276: only a pass is carried -----------------------------------------------------------------------------


@pytest.mark.parametrize("word", ["fail", "insufficient_evidence", "not_verifiable"])
def test_scn_ver_276_condition_1_only_a_pass_is_carried(word):
    only_c_is_dropped(ask(stored({A: "pass", B: "pass", C: word})))


def test_scn_ver_276_condition_1_a_criterion_the_earlier_judge_did_not_answer_is_asked():
    only_c_is_dropped(ask(stored({A: "pass", B: "pass"}, {A: (T_A,), B: (T_B,), C: (T_C,)})))


def test_a_criterion_the_judge_listed_twice_takes_its_worst_answer():
    prev = stored()
    prev["judge_verdict"]["criteria"].append(row(C, "fail"))
    only_c_is_dropped(ask(prev))


def test_a_row_of_the_judge_that_does_not_parse_blocks_its_criterion_and_only_that_one():
    prev = stored()
    prev["judge_verdict"]["criteria"].append({"id": C, "verdict": "pass"})  # no evidence: not a verdict row
    only_c_is_dropped(ask(prev))


def test_a_stored_trace_that_cannot_be_read_carries_nothing():
    found = ask(stored(trace="not a list"))
    assert found.carried == {} and found.reason and found.from_round == 1


# --- the adequacy entries ---------------------------------------------------------------------------------------------


def adequacy(test: str, criterion: str, adequate: bool = True, reason: str = "ok") -> dict[str, Any]:
    return {"test": test, "criterion": criterion, "adequate": adequate, "reason": reason}


def test_the_adequacy_rows_of_the_criterion_go_with_it():
    prev = stored()
    prev["judge_verdict"]["test_adequacy"] = [
        adequacy(T_A, A), adequacy(T_B, B, False, "weak"), adequacy(T_B, "", False, "weak everywhere"),
        adequacy("tests.test_other::test_other", "", False, "not a test of any carried criterion"),
    ]  # fmt: skip
    found = ask(prev)
    assert found.carried[A]["adequacy"] == [adequacy(T_A, A)]
    # a row of no criterion about a test that traced the criterion applies to it
    assert found.carried[B]["adequacy"] == [
        adequacy(T_B, B, False, "weak"),
        adequacy(T_B, "", False, "weak everywhere"),
    ]
    assert found.carried[C]["adequacy"] == []


def test_an_adequacy_row_that_does_not_parse_blocks_every_criterion():
    prev = stored()
    prev["judge_verdict"]["test_adequacy"] = [{"test": T_A, "criterion": A}]  # no `adequate`: whose row is it?
    assert ask(prev).carried == {}


def test_apply_carried_marks_inadequate_tests_for_the_criterion_only_and_rescues_a_named_candidate():
    carried = {
        A: {"round": 1, "head": H1, "verdict": row(A), "adequacy": [adequacy(T_A, "", False, "weak")]},
        C: {"round": 1, "head": H1, "verdict": row(C), "adequacy": [adequacy(T_NEW, C)]},
    }  # fmt: skip
    trace = [now(A, (T_A,)), now(B, (T_A,)), now(C, (), capped=(T_NEW,))]
    trace[2] = CriterionEvidence(
        C, "x", "uncovered", (), capped=(TracingTest(T_NEW, "passed", "red_assertion", over_cap=1),)
    )
    out = {e.criterion: e for e in apply_carried(trace, carried, cap=3)}
    assert [t.adequate for t in out[A].tests] == [False]  # the row of no criterion became A's
    assert [t.adequate for t in out[B].tests] == [True]  # B was not carried: the same test stays adequate for it
    assert out[C].state == "covered" and [t.id for t in out[C].tests] == [T_NEW]  # count_named, as the judge's rows do
    assert apply_carried(trace, {}, cap=3) == trace


def test_a_candidate_named_by_a_part_that_never_saw_it_is_not_rescued():
    carried = {
        C: {"round": 1, "head": H1, "verdict": row(C), "adequacy": [adequacy(T_NEW, C, True, "Not in this part")]}
    }
    trace = [
        CriterionEvidence(C, "x", "uncovered", (), capped=(TracingTest(T_NEW, "passed", "red_assertion", over_cap=1),))
    ]
    assert apply_carried(trace, carried, cap=3)[0].state == "uncovered"


def test_carried_verdicts_parses_the_stored_rows_and_skips_what_is_not_a_pass():
    stored_rows = {
        A: {"round": 1, "head": H1, "verdict": row(A), "adequacy": []},
        B: {"round": 1, "head": H1, "verdict": row(B, "fail"), "adequacy": []},
        C: {"round": 1, "head": H1, "verdict": {"id": C}, "adequacy": []},
    }  # fmt: skip
    got = carried_verdicts(stored_rows)
    assert list(got) == [A] and got[A][1:] == (1, H1) and got[A][0].verdict == "pass"
    assert carried_verdicts({}) == {} and carried_verdicts({A: "junk"}) == {}  # type: ignore[dict-item]


# --- carry_over: the facts through Git and read_verdict ---------------------------------------------------------------


@pytest.fixture
def repo(tmp_path: Path, raw: Callable[..., str]) -> Path:
    path = tmp_path / "carry"
    path.mkdir()
    raw(path, "init", "-q")
    return path


def write(repo: Path, rel: str, text: str) -> None:
    (repo / rel).parent.mkdir(parents=True, exist_ok=True)
    (repo / rel).write_text(text)


def commit(repo: Path, raw: Callable[..., str]) -> str:
    raw(repo, "add", "-A")
    raw(repo, "commit", "-q", "-m", "c")
    return raw(repo, "rev-parse", "HEAD").strip()


def store(repo: Path, n: int, prev: dict | None) -> None:
    write(repo, f"{UNIT}/.l4/evidence/round-{n}/verdict.json", json.dumps(prev))


class World:
    """R at H1 (`tests/test_a.py` ... `tests/test_c.py`, the spec) and a head that adds `tests/test_new.py`."""

    def __init__(self, repo: Path, raw: Callable[..., str], git: Git) -> None:
        self.repo, self.raw, self.git = repo, raw, git
        self.sources = {c: f"{UNIT}/specs/x/spec.md" for c in (A, B, C)}
        write(repo, f"{UNIT}/specs/x/spec.md", "### Requirement: r\n")
        for name in ("a", "b", "c"):
            write(repo, f"tests/test_{name}.py", f"def test_{name}(): pass\n")
        write(repo, "src/app.py", "x = 1\n")
        self.h1 = commit(repo, raw)
        self.prev = stored(head_sha=self.h1)
        store(repo, 1, self.prev)

    def ask(self, *, round_no: int = 3, trace: dict | None = None) -> Decision:
        head = self.raw(self.repo, "rev-parse", "HEAD").strip()
        trace = TRACE_NOW if trace is None else trace
        return carry_over(
            self.git, unit_dir=self.repo / UNIT, unit_rel=UNIT, unit_dirs=DIRS, round_no=round_no, head=head,
            criteria=[criterion(c) for c in (A, B, C)], trace=[now(c, t) for c, t in trace.items()],
            test_globs=TEST_GLOBS, support_globs=SUPPORT_GLOBS,
        )  # fmt: skip


@pytest.fixture
def world(repo: Path, raw: Callable[..., str], git_for: Callable[[Path], Git]) -> World:
    return World(repo, raw, git_for(repo))


def test_scn_ver_273_carry_over_reads_a_real_repository_and_drops_the_criterion_a_new_test_traces(world):
    write(world.repo, "tests/test_new.py", "def test_new(): pass\n")
    write(world.repo, f"{UNIT}/.l4/evidence/round-2/verdict.json", json.dumps({"schema": "x"}))  # bookkeeping
    commit(world.repo, world.raw)
    found = world.ask(trace={**TRACE_NOW, C: (T_C, T_NEW)})
    only_c_is_dropped(found)
    assert found.from_round == 1 and found.from_head == world.h1 and found.carried[A]["head"] == world.h1


def test_scn_ver_274_carry_over_sees_a_production_change(world):
    write(world.repo, "src/app.py", "x = 2\n")
    write(world.repo, "tests/test_new.py", "def test_new(): pass\n")
    commit(world.repo, world.raw)
    found = world.ask()
    assert found.carried == {} and found.reason == "a non-test file changed" and found.paths == ("src/app.py",)


def test_carry_over_sees_a_changed_test_file_of_a_tracing_test_and_a_changed_source_file(world):
    write(world.repo, "tests/test_c.py", "def test_c(): assert True\n")
    commit(world.repo, world.raw)
    only_c_is_dropped(world.ask())
    write(world.repo, f"{UNIT}/specs/x/spec.md", "### Requirement: r2\n")
    commit(world.repo, world.raw)
    assert world.ask().carried == {}  # the source file of every criterion is this one


def test_carry_over_takes_the_newest_earlier_round_that_has_a_judge_verdict(world):
    world.prev["round"] = 2
    store(world.repo, 2, {**world.prev, "judge_verdict": None})  # round 2's judge gave no verdict
    store(world.repo, 4, world.prev)  # not below round 3
    write(world.repo, "tests/test_new.py", "def test_new(): pass\n")
    commit(world.repo, world.raw)
    assert world.ask().from_round == 1
    store(world.repo, 2, {**world.prev, "judge_verdict": {"criteria": [], "test_adequacy": []}})  # empty: skipped too
    assert world.ask().from_round == 1
    store(world.repo, 2, {**world.prev, "head_sha": world.h1})  # now it has one
    assert world.ask().from_round == 2


@pytest.mark.parametrize(
    "why",
    [
        "no round",
        "unreadable",
        "not a verdict",
        "head not hex",
        "head not a commit",
        "head option",
        "head not a commit id",
    ],
)
def test_a_failure_to_read_the_earlier_round_or_the_diff_carries_nothing_and_says_why(world, why):
    write(world.repo, "tests/test_new.py", "def test_new(): pass\n")
    commit(world.repo, world.raw)
    path = world.repo / UNIT / ".l4" / "evidence" / "round-1" / "verdict.json"
    if why == "no round":
        path.unlink()
    elif why == "unreadable":
        path.write_text("{not json")
    elif why == "not a verdict":
        store(world.repo, 1, {"schema": "something-else"})
    else:
        bad = {
            "head not hex": "zz" * 20, "head not a commit": "b" * 40, "head option": "--output=/tmp/x",
            "head not a commit id": 7,
        }[why]  # fmt: skip
        store(world.repo, 1, {**world.prev, "head_sha": bad})
    found = world.ask()
    assert found.carried == {} and found.reason and "\n" not in found.reason
    assert (found.from_round is None) == (why in ("no round", "unreadable", "not a verdict"))


def test_a_round_one_has_no_earlier_round(world):
    found = world.ask(round_no=1)
    assert found.carried == {} and found.from_round is None and found.reason
