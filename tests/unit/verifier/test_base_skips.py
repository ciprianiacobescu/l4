"""Where step 3 gets the base report's statuses (skipped-test-hold D1, rework 7): step 1's record carries a `skipped`
list only when it saw the whole base report, and `SkipLookup` asks (i) step 1's reference of this round, (ii) the newest
earlier record that has the key, (iii) one run in a base worktree, kept so that no round runs it twice."""

import json
from contextlib import contextmanager
from types import SimpleNamespace

from l4.evidence.skippred import EARLIER_SOURCE, STEP1_SOURCE, WORKTREE_SOURCE
from l4.gates.junit import TestCase, TestReport
from l4.implementer.workbench import BaseRun
from l4.verifier.base_tests import SkipLookup, check_base_tests

from ._integrity_helpers import UNIT, new_repo
from ._integrity_helpers import task as make_task
from .test_base_tests import ScriptedWb, passing_report

A, B, C = "tests.test_a::test_a", "tests.test_a::test_b", "tests.test_a::test_c"
FAILING = passing_report(**{"tests.test_a__test_a": "failed"})


def report(**statuses: str) -> TestReport:
    return TestReport({i.replace("__", "::"): TestCase(i.replace("__", "::"), s) for i, s in statuses.items()})


BASE_FULL = TestReport({A: TestCase(A, "passed"), B: TestCase(B, "skipped"), C: TestCase(C, "skipped")})


class Setup:
    """A unit that changed a test file, a workbench with scripted gate runs and a fake base worktree run."""

    def __init__(self, tmp_path, git_environ, monkeypatch, reports, base_run=BASE_FULL, rounds=None):
        repo, self.base = new_repo(tmp_path, git_environ, {"tests/test_a.py": "def test_a():\n    assert 1\n"})
        repo.write({"tests/test_a.py": "def test_a():\n    assert 2\n"})
        head = repo.commit("work", task="1.1", tdd="red")
        self.unit_dir = tmp_path / "unit"
        for number, data in (rounds or {}).items():
            folder = self.unit_dir / ".l4" / "evidence" / f"round-{number}"
            folder.mkdir(parents=True)
            record = {"base_sha": self.base, "command": "pytest", "passed": [A], "collection_errors": []} | data
            (folder / "verdict.json").write_text(
                json.dumps({"schema": "l4/verdict@1", "integrity": {"base_tests": record}})
            )
        self.repo, self.git_environ = repo, git_environ
        self.wb = ScriptedWb(repo, git_environ, reports, self.unit_dir)
        self.runs: list[str] = []
        self.ctx = repo.context(self.base, head, tasks=[(UNIT, make_task("1.1"))])

        @contextmanager
        def checkout(wb, sha):
            self.runs.append(f"checkout {sha[:7]}")
            yield tmp_path

        monkeypatch.setattr("l4.verifier.base_tests.base_checkout", checkout)
        monkeypatch.setattr(
            "l4.verifier.base_tests.run_gate_at",
            lambda wb, tree, spec, network: (
                self.runs.append("run") or SimpleNamespace(report=base_run, reason="FAKE: the gate could not start")
            ),
        )

    def fresh(self) -> ScriptedWb:
        """A workbench as the verifier builds one for each round: nothing is kept on it."""
        return ScriptedWb(self.repo, self.git_environ, [], self.unit_dir)

    def lookup(self, round_no=1, step1=None) -> SkipLookup:
        return SkipLookup(self.wb, self.base, round_no, step1)


# --- step 1's record ----------------------------------------------------------------------------------------------


def test_a_cached_baseline_is_a_full_report_and_step_1_records_its_skipped_ids(tmp_path, git_environ, monkeypatch):
    s = Setup(tmp_path, git_environ, monkeypatch, [FAILING, FAILING])
    s.wb.baselines[s.base] = BASE_FULL
    out = check_base_tests(s.wb, s.ctx, prior=[], round_no=1)
    assert s.wb.events[0][1]["base_source"] == "baseline"
    assert out.base_tests is not None and out.base_tests["skipped"] == [B, C]
    assert out.base_tests["passed"] == [A]
    assert out.base_report is BASE_FULL
    assert s.wb.baselines[s.base] is BASE_FULL  # the implementer's baseline is not touched
    assert s.runs == []


def test_a_base_worktree_run_is_a_full_report_and_step_1_records_its_skipped_ids(tmp_path, git_environ, monkeypatch):
    s = Setup(tmp_path, git_environ, monkeypatch, [FAILING, FAILING])
    out = check_base_tests(s.wb, s.ctx, prior=[], round_no=1)
    assert s.wb.events[0][1]["base_source"] == "base worktree" and s.runs == [f"checkout {s.base[:7]}", "run"]
    assert out.base_tests is not None and out.base_tests["skipped"] == [B, C] and out.base_report is BASE_FULL
    assert s.wb.baselines == {}


def test_the_base_worktree_run_of_step_1_is_kept_so_that_step_3_does_not_run_it_again(
    tmp_path, git_environ, monkeypatch
):
    s = Setup(tmp_path, git_environ, monkeypatch, [FAILING, FAILING])
    check_base_tests(s.wb, s.ctx, prior=[], round_no=1)
    assert s.runs == [f"checkout {s.base[:7]}", "run"] and s.wb.base_runs == {(s.base, "pytest"): BaseRun(BASE_FULL)}
    found = s.lookup(1)()  # step 1 handed nothing over (as when it ended before judging): the kept run is read
    assert (found.skipped, found.source) == (frozenset({B, C}), WORKTREE_SOURCE)
    assert s.runs == [f"checkout {s.base[:7]}", "run"]  # one gate run for the round, step 1 and step 3 together


def test_a_reference_rebuilt_from_an_earlier_rounds_passed_ids_records_no_skipped_key(
    tmp_path, git_environ, monkeypatch
):
    s = Setup(tmp_path, git_environ, monkeypatch, [FAILING, FAILING], rounds={1: {}})
    out = check_base_tests(s.wb, s.ctx, prior=[], round_no=2)
    assert s.wb.events[0][1]["base_source"] == "evidence" and s.runs == []
    assert out.base_tests is not None and "skipped" not in out.base_tests  # absent: not observed, never "none"
    assert out.base_report is None


def test_an_all_green_run_needs_no_reference_and_records_no_skipped_key(tmp_path, git_environ, monkeypatch):
    green = report(**{"tests.test_a__test_a": "passed", "tests.test_a__test_b": "passed"})
    s = Setup(tmp_path, git_environ, monkeypatch, [green])
    out = check_base_tests(s.wb, s.ctx, prior=[], round_no=1)
    assert s.wb.events[0][1]["base_source"] == "not needed"  # R0 is R1: the base's test files on the unit's code
    assert out.base_tests is not None and "skipped" not in out.base_tests and out.base_report is None


# --- the lookup -----------------------------------------------------------------------------------------------------


def test_i_step_1s_full_reference_of_this_round_comes_first(tmp_path, git_environ, monkeypatch):
    s = Setup(tmp_path, git_environ, monkeypatch, [], rounds={1: {"skipped": [A]}})
    found = s.lookup(2, step1=BASE_FULL)()
    assert (found.skipped, found.source) == (frozenset({B, C}), STEP1_SOURCE) and s.runs == []


def test_ii_the_newest_earlier_record_with_a_skipped_key_is_read_walking_past_records_without_one(
    tmp_path, git_environ, monkeypatch
):
    rounds = {1: {"skipped": [B]}, 2: {"skipped": [B, C]}, 3: {}}  # round 3 was rebuilt from passed ids: no key
    s = Setup(tmp_path, git_environ, monkeypatch, [], rounds=rounds)
    found = s.lookup(4)()
    assert (found.skipped, found.source) == (frozenset({B, C}), EARLIER_SOURCE) and s.runs == []
    assert s.lookup(3)().skipped == frozenset({B, C})  # round 2 is the newest below round 3
    assert s.lookup(2)().skipped == frozenset({B})


def test_ii_an_empty_skipped_list_is_a_report_that_saw_nothing_skipped(tmp_path, git_environ, monkeypatch):
    s = Setup(tmp_path, git_environ, monkeypatch, [], rounds={1: {"skipped": []}})
    assert (s.lookup(2)().skipped, s.runs) == (frozenset(), [])


def test_ii_a_record_of_another_base_or_command_is_not_read(tmp_path, git_environ, monkeypatch):
    for number, other in enumerate(({"base_sha": "0" * 40, "skipped": [B]}, {"command": "make test", "skipped": [B]})):
        (tmp_path / str(number)).mkdir()
        s = Setup(tmp_path / str(number), git_environ, monkeypatch, [], rounds={1: other})
        found = s.lookup(2)()
        assert found.source == WORKTREE_SOURCE and s.runs  # fell through to a run


def test_iii_a_base_worktree_run_is_made_once_and_kept_on_its_own_workbench_attribute(
    tmp_path, git_environ, monkeypatch
):
    s = Setup(tmp_path, git_environ, monkeypatch, [], rounds={1: {}})  # an older harness's record: no key
    first = s.lookup(2)()
    assert (first.skipped, first.source) == (frozenset({B, C}), WORKTREE_SOURCE)
    assert s.runs == [f"checkout {s.base[:7]}", "run"]
    assert s.wb.base_runs == {(s.base, "pytest"): BaseRun(BASE_FULL)} and s.wb.baselines == {}
    s.lookup(2)()  # a second lookup object of the same round: the workbench's copy
    assert s.runs == [f"checkout {s.base[:7]}", "run"]
    lookup = s.lookup(2)
    assert lookup() is lookup()  # the same object answers twice


def test_a_failed_run_fails_closed_with_the_reason_and_is_not_repeated_in_the_round(tmp_path, git_environ, monkeypatch):
    s = Setup(tmp_path, git_environ, monkeypatch, [], base_run=None)
    lookup = s.lookup(1)
    found = lookup()
    assert found.skipped is None and found.source == ""
    assert (
        found.why
        == "no base report with statuses: the base's test gate gave no report (FAKE: the gate could not start)"
    )
    lookup()
    assert s.runs == [f"checkout {s.base[:7]}", "run"]  # one gate run in the round, not two
    assert s.wb.base_runs == {
        (s.base, "pytest"): BaseRun(None, found.why.removeprefix("no base report with statuses: "))
    }


# --- review G2: the base worktree run is written into the round's record, so that the next round reads it -------------


def test_g2_a_lookup_that_ran_the_base_gate_writes_skipped_into_the_record_of_the_round(
    tmp_path, git_environ, monkeypatch
):
    s = Setup(tmp_path, git_environ, monkeypatch, [], rounds={1: {}})
    lookup = s.lookup(2)
    lookup()
    whole = lookup.record(None)  # step 1 wrote no record this round (it was all green, or it ended early)
    assert whole == {
        "base_sha": s.base, "command": "pytest", "passed": [A], "collection_errors": [], "skipped": [B, C],
    }  # fmt: skip
    own = {"base_sha": s.base, "command": "pytest", "passed": [A, B], "collection_errors": ["E"]}
    assert lookup.record(own) == {**own, "skipped": [B, C]}  # a record without the key gets it, and keeps the rest
    assert "skipped" not in own  # the record of step 1 is not changed in place


def test_g2_nothing_is_written_when_the_record_has_the_key_or_the_report_was_not_a_worktree_run(
    tmp_path, git_environ, monkeypatch
):
    s = Setup(tmp_path, git_environ, monkeypatch, [], rounds={1: {"skipped": [B]}})
    from_step1 = s.lookup(3, step1=BASE_FULL)
    from_step1()
    assert from_step1.record(None) is None  # step 1's own record carries the key when its reference was full
    earlier = s.lookup(3)
    assert earlier().source == EARLIER_SOURCE and earlier.record(None) is None  # an earlier round holds it already
    never_asked = s.lookup(3)
    assert never_asked.record(None) is None  # no lookup was made: nothing was learned
    (tmp_path / "b").mkdir()
    s2 = Setup(tmp_path / "b", git_environ, monkeypatch, [], rounds={1: {}})
    ran = s2.lookup(2)
    ran()
    keyed = {"base_sha": s2.base, "command": "pytest", "passed": [A], "collection_errors": [], "skipped": [B]}
    assert ran.record(keyed) is None  # the record already has `skipped`: not replaced
    other = {k: v for k, v in keyed.items() if k != "skipped"} | {"base_sha": "0" * 40}
    assert ran.record(other) is None  # nor one of another base


def test_g2_a_failed_run_writes_nothing(tmp_path, git_environ, monkeypatch):
    s = Setup(tmp_path, git_environ, monkeypatch, [], base_run=None)
    lookup = s.lookup(1)
    lookup()
    assert lookup.record(None) is None  # never a `skipped` from anything that is not a full report


def test_g2_one_base_worktree_run_serves_rounds_3_to_6_each_on_a_fresh_workbench(tmp_path, git_environ, monkeypatch):
    """The verifier builds a fresh workbench every round. Rounds 1 and 2 were written without the key (an older
    harness, or a step 1 that took its reference from passed ids). The record of round 3 is written by the real writer
    with the key, and rounds 4 to 6 read it from the ledger of the unit: one run of the base gate in all."""
    from l4.redact import Redactor
    from l4.verifier.integrity import IntegrityReport
    from l4.verifier.report import write_round_evidence
    from l4.verifier.types import Verdict, VerifyResult

    s = Setup(tmp_path, git_environ, monkeypatch, [], rounds={1: {}, 2: {}})
    seen = []
    for number in (3, 4, 5, 6):
        lookup = SkipLookup(s.fresh(), s.base, number)
        found = lookup()
        seen.append(found.source)
        result = VerifyResult(UNIT, number, Verdict.FAIL, s.base, "h" * 40)
        result.integrity = IntegrityReport()
        result.integrity.base_tests = lookup.record(result.integrity.base_tests)
        write_round_evidence(s.unit_dir, number, result, Redactor({}))
    assert seen == [WORKTREE_SOURCE, EARLIER_SOURCE, EARLIER_SOURCE, EARLIER_SOURCE]
    assert s.runs.count("run") == 1
    data = json.loads((s.unit_dir / ".l4" / "evidence" / "round-3" / "verdict.json").read_text())
    assert data["integrity"]["base_tests"]["skipped"] == [B, C]


# --- review G4: a failed base run is remembered for the round, and an exit's reason is kept ---------------------------


def test_g4_a_run_that_failed_in_step_1_is_not_run_again_by_the_lookup(tmp_path, git_environ, monkeypatch):
    s = Setup(tmp_path, git_environ, monkeypatch, [FAILING, FAILING], base_run=None)
    out = check_base_tests(s.wb, s.ctx, prior=[], round_no=1)
    assert out.skipped and out.note.startswith("no base reference: the base's test gate gave no report")
    assert s.runs == [f"checkout {s.base[:7]}", "run"]
    found = s.lookup(1)()
    assert found.skipped is None and "the base's test gate gave no report" in found.why
    assert s.runs == [f"checkout {s.base[:7]}", "run"]  # step 3 asked, and the gate did not run a second time


def test_g4_the_message_of_an_exit_from_the_base_checkout_is_kept_in_the_note(tmp_path, git_environ, monkeypatch):
    from l4.exitcodes import ExitCode, L4Exit

    s = Setup(tmp_path, git_environ, monkeypatch, [])

    @contextmanager
    def failing(wb, sha):
        s.runs.append("checkout")
        raise L4Exit(ExitCode.INTERNAL_ERROR, "gates.setup failed at the merge base: no network\nsecond line")
        yield  # pragma: no cover

    monkeypatch.setattr("l4.verifier.base_tests.base_checkout", failing)
    lookup = s.lookup(1)
    found = lookup()
    assert found.skipped is None
    assert found.why == "no base report with statuses: gates.setup failed at the merge base: no network"
    lookup()
    s.lookup(1)()  # another lookup object of the round
    assert s.runs == ["checkout"]  # one attempt in the round
