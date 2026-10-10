"""Live wave D, W-D2: an audit test that cannot be collected goes back to the writer once with the error; one that still
cannot is a minor finding, never a held criterion or a human question."""

from ..implementer.conftest import green_step, red_step
from .test_audit_lint import audit_path
from .test_ladder_depth import (  # noqa: F401  (the fixtures and scripted steps of the audit end-to-end tests)
    AUDIT_KNOWN,
    JUDGE,
    audited_criterion,
    writer_step,
)

# a module that exists nowhere: the file passes every static check and fails at collection with an ImportError
BROKEN = "import widget_tools_that_do_not_exist\n" + AUDIT_KNOWN


def run_with(run_l4, with_verifier, replies):
    cid = audited_criterion()
    config = with_verifier(audit_sample_ratio=0.5)
    return cid, run_l4([red_step(), green_step(), *[writer_step(cid, c) for c in replies], JUDGE], **config)


def test_the_writer_gets_the_collection_error_once_and_the_fixed_test_is_accepted(run_l4, valid_spec, with_verifier):
    cid, run = run_with(run_l4, with_verifier, [BROKEN, AUDIT_KNOWN])
    assert run.code == 0
    retry = run.adapter.requests[3].prompt  # red, green, writer, writer again
    assert "## Your previous attempt was rejected" in retry and "could not be collected" in retry
    assert "widget_tools_that_do_not_exist" in retry
    [audit] = run.events("verify.audit")
    assert audit["status"] == "accepted" and audit["path"] == audit_path(cid)
    assert "widget_tools_that_do_not_exist" not in run.pushed(audit_path(cid))
    assert len(run.adapter.requests) == 5  # one extra writer call, never a third


def test_a_test_that_still_cannot_be_collected_is_a_minor_finding_not_a_hold(run_l4, valid_spec, with_verifier):
    cid, run = run_with(run_l4, with_verifier, [BROKEN, BROKEN])
    assert run.code == 0, "a rejected audit test must not turn a supported PASS into needs_human"
    [audit] = run.events("verify.audit")
    assert audit["status"] == "rejected" and "collected" in audit["reason"]
    assert [e["verdict"] for e in run.events("verify.verdict")] == ["PASS"]
    tree = run.raw(run.tdd.origin, "ls-tree", "-r", "--name-only", "HEAD").split()
    assert not [p for p in tree if "test_l4_audit" in p]
    assert len(run.adapter.requests) == 5


def test_a_writer_that_gives_up_on_the_retry_is_rejected_the_same_way(run_l4, valid_spec, with_verifier):
    cid = audited_criterion()
    config = with_verifier(audit_sample_ratio=0.5)
    nothing = {"criterion": cid, "not_testable": "cannot"}
    from l4.agents.fake import Step

    run = run_l4([red_step(), green_step(), writer_step(cid, BROKEN), Step(structured=nothing), JUDGE], **config)
    assert run.code == 0
    [audit] = run.events("verify.audit")
    assert audit["status"] == "rejected" and "not_testable" in audit["reason"]


def test_a_good_file_that_pytest_never_ran_because_of_another_files_collection_error_is_run_again(
    tmp_path, monkeypatch
):
    """pytest stops at a collection error unless told otherwise: the good file has no result in that run, and must not
    be rejected for it (the broken one is removed, the others run again)."""
    from types import SimpleNamespace as NS

    from l4.verifier import audit

    bad, good = "C-0000000a", "C-0000000b"
    stem = lambda cid: f"tests/test_l4_audit_c_{cid.removeprefix('C-')}_r1.py"  # noqa: E731
    paths = {bad: stem(bad), good: stem(good)}
    (tmp_path / "tests").mkdir()
    for rel in paths.values():
        (tmp_path / rel).write_text("x = 1\n")
    log = tmp_path / "gate.log"
    log.write_text("E   ModuleNotFoundError: No module named 'nothing_here'\n")
    runs = []

    def run_gate(name, command, **kw):
        present = sorted(cid for cid, rel in paths.items() if (tmp_path / rel).exists())
        runs.append(present)
        if bad in present:
            report = NS(tests={}, collection_errors=[f"tests.test_l4_audit_c_{bad[2:]}_r1"])
        else:
            tests = {f"tests.test_l4_audit_c_{c[2:]}_r1::test_x": NS(status="passed") for c in present}
            report = NS(tests=tests, collection_errors=[])
        return NS(report=report, reason="", log_path=log)

    wb = NS(
        worktree=tmp_path, run_gate=run_gate,
        cfg=NS(gates=NS(test=NS(command="pytest", reports=[]))),
    )  # fmt: skip
    monkeypatch.setattr(audit, "confirm_pre_satisfied", lambda wb, candidates: NS(confirmed=set(candidates), reason=""))
    out, collected = audit.AuditOutcome(), {}
    audit._judge_written(wb, paths, 1, out, collected)
    assert runs == [[bad, good], [good]]
    assert list(collected) == [bad] and "ModuleNotFoundError" in collected[bad][0]
    assert [(r.criterion, r.status) for r in out.records] == [(good, "accepted")]
    assert out.findings == []


def test_the_collection_error_shown_to_the_writer_is_the_one_of_its_own_file(tmp_path):
    """Two audit files that fail to import: each writer is shown its own file's error, not the other's."""
    from l4.verifier import audit

    log = tmp_path / "gate.log"
    log.write_text(
        "==================================== ERRORS ====================================\n"
        "_______ ERROR collecting tests/test_l4_audit_c_0000000a_r1.py _______\n"
        "ImportError while importing test module '/w/tests/test_l4_audit_c_0000000a_r1.py'.\n"
        "E   ModuleNotFoundError: No module named 'nothing_here'\n"
        "_______ ERROR collecting tests/test_l4_audit_c_0000000b_r1.py _______\n"
        "tests/test_l4_audit_c_0000000b_r1.py:3: in <module>\n"
        "E   NameError: name 'threading' is not defined\n"
        "=========================== short test summary info ============================\n"
        "ERROR tests/test_l4_audit_c_0000000a_r1.py\n"
        "ERROR tests/test_l4_audit_c_0000000b_r1.py\n"
    )
    a = audit._collection_error(log, "test_l4_audit_c_0000000a_r1")
    b = audit._collection_error(log, "test_l4_audit_c_0000000b_r1")
    assert "nothing_here" in a and "threading" not in a
    assert "threading" in b and "nothing_here" not in b
    other = audit._collection_error(log, "test_l4_audit_c_0000000c_r1")  # no section of its own: all of them
    assert "nothing_here" in other and "threading" in other
