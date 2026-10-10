"""Step 2 runs the reproduced failing step of the project's CI job (M1.10 line 8; decisions 4 and 5; L4-VER-002)."""

import sys

from l4.ci.failing_step import active_ci_steps
from l4.state.ledger import read_ledger
from l4.verifier.gates import run_build_gates
from l4.verifier.types import Severity, finding_id

H1, H2 = "a" * 40, "b" * 40
FAILS = f"{sys.executable} -c \"print('E501 Line too long'); raise SystemExit(1)\""
PASSES = f"{sys.executable} -c \"print('fine')\""


def edge(writer, head: str = H1, trigger: str = "repository_ci_failed") -> None:
    jobs = [{"name": "test", "stage": "test", "url": "", "tail": "boom", "step": "x"}]
    writer.append("phase.changed", **{"from": "in_review", "to": "verifying"}, trigger=trigger, head=head, jobs=jobs)


def ci_step(writer, status: str, command: str = PASSES, head: str = H1) -> None:
    writer.append(
        "ci.step", job="test", head=head, step=command, command=command, status=status, reason=None, source="s"
    )


def active(bench):
    return active_ci_steps(read_ledger(bench.wb.ref.path).events)


def test_the_round_after_the_chore_runs_the_reproduced_step(make_bench):
    bench = make_bench([])
    edge(bench.writer)
    ci_step(bench.writer, "derived")
    ci_step(bench.writer, "reproduced")
    bench.writer.append("verify.verdict", round=1, verdict="FAIL", findings=1)  # the round that failed at step 0
    (step,) = active(bench)
    assert (step.job, step.command, step.status) == ("test", PASSES, "reproduced")
    out = run_build_gates(bench.wb, [step])
    assert out.ok and [(g.name, g.status) for g in out.gates] == [("setup", "pass"), ("repository-ci:test", "pass")]
    assert out.gates[1].command == PASSES


def test_a_failing_step_is_the_same_finding_id(make_bench):
    bench = make_bench([], lint=["echo lint"])
    edge(bench.writer)
    ci_step(bench.writer, "reproduced", FAILS)
    (step,) = active(bench)
    out = run_build_gates(bench.wb, [step])
    (finding,) = out.findings
    assert (finding.severity, finding.source, finding.title) == (
        Severity.BLOCKER, "deterministic", "repository CI failed: test",
    )  # fmt: skip
    assert finding.id == finding_id(
        "repository CI failed: test"
    )  # the id step 0 gave it: the next chore finds its step
    assert "E501 Line too long" in (bench.wb.out_dir.parent / finding.log).read_text()
    assert [(g.name, g.status) for g in out.gates] == [
        ("setup", "pass"),
        ("lint", "pass"),
        ("repository-ci:test", "fail"),
    ]


def test_the_window_ends_at_a_pass_or_another_review_edge(make_bench):
    bench = make_bench([])
    assert active(bench) == []
    edge(bench.writer)
    ci_step(bench.writer, "reproduced")
    assert len(active(bench)) == 1
    bench.writer.append("verify.verdict", round=1, verdict="FAIL", findings=1)
    bench.writer.append("verify.verdict", round=2, verdict="NEEDS_HUMAN", findings=0)
    assert len(active(bench)) == 1  # only a PASS ends it
    bench.writer.append("verify.verdict", round=3, verdict="PASS", findings=0)
    assert active(bench) == []
    edge(bench.writer, H2)
    ci_step(bench.writer, "reproduced", head=H2)
    assert [s.head for s in active(bench)] == [H2]
    edge(bench.writer, H2, trigger="commit_after_handoff")  # a person's commit after H: a new review, not the CI's
    assert active(bench) == []
    edge(bench.writer, H2, trigger="spec_edit_after_handoff")
    assert active(bench) == []


def test_derived_or_skipped_steps_do_not_run(make_bench):
    bench = make_bench([])
    edge(bench.writer)
    ci_step(bench.writer, "derived", FAILS)
    assert active(bench) == []
    ci_step(bench.writer, "skipped", FAILS)  # the last event of (head, job) wins
    assert active(bench) == []
    out = run_build_gates(bench.wb, active(bench))
    assert out.ok and [g.name for g in out.gates] == ["setup"]
