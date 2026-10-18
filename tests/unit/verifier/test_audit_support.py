"""detect-test-tamper 4.2 (L4-VER-033, L4-VER-034): which way each audit test ran, and the fallback."""

from l4.config.schema import L4Config
from l4.verifier.audit import BASE_RUN_ENV, AuditOutcome, _judge_written
from l4.verifier.support_base import SupportPlan

from ..implementer.conftest import KNOWN, UNKNOWN_TEST, green_step, red_step
from .test_ladder_depth import JUDGE, audited_criterion, writer_step  # noqa: F401

BUILDERS = "CODE = 'SAVE10'\n"
USES_BUILDERS = (
    "import pytest\n\nfrom helpers.builders import CODE\nfrom pytdd.pricing import apply_discount\n\n\n"
    f'@pytest.mark.l4("{KNOWN}")\ndef test_known_code():\n    assert apply_discount(50.0, CODE) == 45.0\n\n\n'
    + UNKNOWN_TEST
)
CONFTEST_CODES = "import pytest\n\n\n@pytest.fixture\ndef codes():\n    return ['SAVE10']\n"
AUDIT_NEEDS_CODES = (
    'import pytest\nfrom pytdd.pricing import apply_discount\n\n\n@pytest.mark.l4("{cid}")\n'
    "def test_audit_known_code(codes):\n    assert apply_discount(100.0, codes[0]) == 90.0\n"
)
UNIT_DIR = "openspec/changes/add-discount-codes"


def run_with(run_l4, with_verifier, red_writes, audit_code):
    cid = audited_criterion()
    config = with_verifier(audit_sample_ratio=0.5)
    red = red_step()
    red.writes = {**red.writes, **red_writes}
    return cid, run_l4([red, green_step(), writer_step(cid, audit_code), JUDGE], **config)


def test_a_unit_test_that_needs_the_units_helper_does_not_stop_the_audit_run(
    run_l4, valid_spec, with_verifier
):  # SCN-VER-115
    from .test_ladder_depth import AUDIT_KNOWN

    writes = {"tests/helpers/builders.py": BUILDERS, "tests/test_discount.py": USES_BUILDERS}
    cid, run = run_with(run_l4, with_verifier, writes, AUDIT_KNOWN)
    [audit] = run.events("verify.audit")
    assert (audit["criterion"], audit["status"], audit["support"]) == (cid, "accepted", "base")
    assert {"tests/helpers/builders.py", "tests/test_discount.py"} <= set(audit["support_files"])


def test_an_audit_test_that_needs_a_fixture_only_the_unit_defines_is_held(
    run_l4, valid_spec, with_verifier
):  # SCN-VER-116
    cid, run = run_with(run_l4, with_verifier, {"tests/conftest.py": CONFTEST_CODES}, AUDIT_NEEDS_CODES)
    [audit] = run.events("verify.audit")
    assert (audit["status"], audit["support"]) == ("failed", "base") and "tests/conftest.py" in audit["support_files"]
    assert "fixture 'codes' not found" not in audit["reason"] or audit["reason"]
    assert run.outcome["units"][0]["verdict"] != "PASS"
    assert all("audit-head" not in str(e.get("name")) for e in run.events("gate.finished"))  # no run with the conftest


def test_an_audit_test_whose_own_import_fails_twice_is_a_minor_rejection_with_a_support_label(
    run_l4, valid_spec, with_verifier
):  # SCN-VER-117
    from .test_audit_collect_retry import BROKEN

    writes = {"tests/conftest.py": CONFTEST_CODES, "tests/helpers/setup.ts": "export const x = 1;\n"}
    cid = audited_criterion()
    config = with_verifier(audit_sample_ratio=0.5)
    red = red_step()
    red.writes = {**red.writes, **writes}
    run = run_l4([red, green_step(), writer_step(cid, BROKEN), writer_step(cid, BROKEN), JUDGE], **config)
    [audit] = run.events("verify.audit")
    assert audit["status"] == "rejected" and audit["support"] == "base" and "collected" in audit["reason"]
    assert "## Your previous attempt was rejected" in run.adapter.requests[3].prompt
    assert run.outcome["units"][0]["verdict"] == "PASS"  # a minor finding, never a hold


def test_the_writers_collection_retry_is_kept_and_no_label_is_empty(run_l4, valid_spec, with_verifier):  # SCN-VER-136
    from .test_audit_collect_retry import BROKEN
    from .test_ladder_depth import AUDIT_KNOWN

    writes = {"tests/conftest.py": "import pytest\n", "tests/helpers/setup.ts": "export const x = 1;\n"}
    cid = audited_criterion()
    config = with_verifier(audit_sample_ratio=0.5)
    red = red_step()
    red.writes = {**red.writes, **writes}
    run = run_l4([red, green_step(), writer_step(cid, BROKEN), writer_step(cid, AUDIT_KNOWN), JUDGE], **config)
    retry = run.adapter.requests[3].prompt
    assert "## Your previous attempt was rejected" in retry and "widget_tools_that_do_not_exist" in retry
    [audit] = run.events("verify.audit")
    assert audit["status"] == "accepted" and audit["support"] == "base"
    assert all(e.get("support") for e in run.events("verify.audit"))


def test_the_zero_value_run_uses_the_same_support_files_as_the_head_run(make_bench, monkeypatch):  # SCN-VER-118
    bench = make_bench([])
    wb = bench.wb
    base = wb.head()
    (wb.worktree / "tests").mkdir(exist_ok=True)
    (wb.worktree / "tests/conftest.py").write_text("import pytest\n")
    wb.git.run("add", "tests/conftest.py")
    wb.git.run("-c", "user.name=a", "-c", "user.email=a@b.invalid", "commit", "-q", "-m", "unit conftest")
    cid = "C-0a1b2c3d"
    rel = f"tests/test_l4_audit_c_{cid.removeprefix('C-')}_r1.py"
    (wb.worktree / rel).write_text(
        f'import pytest\nfrom pytdd.pricing import total\n\n\n@pytest.mark.l4("{cid}")\n'
        "def test_audit_total():\n    assert total([1.0]) == 1.0\n"
    )
    seen = []
    gates = []

    def gate(name, command, *, reports=(), extra_env=None, **kw):
        from types import SimpleNamespace

        from l4.gates.junit import TestCase, TestReport

        gates.append((name, (wb.worktree / "tests/conftest.py").exists(), dict(extra_env or {})))
        stem = f"test_l4_audit_c_{cid.removeprefix('C-')}_r1"
        report = TestReport({f"tests.{stem}::test_audit_total": TestCase(f"tests.{stem}::test_audit_total", "passed")})
        return SimpleNamespace(report=report, log_path=wb.worktree / "none.log", reason="")

    monkeypatch.setattr(wb, "run_gate", gate)

    def recorder(wb_, candidates, *, real=None, extra_env=None):
        from l4.implementer.discrimination import PreSatisfied

        seen.append(((wb_.worktree / "tests/conftest.py").exists(), dict(extra_env or {})))
        return PreSatisfied({c: tuple(t) for c, t in candidates.items()}, {})

    monkeypatch.setattr("l4.verifier.audit.confirm_pre_satisfied", recorder)
    out = AuditOutcome()
    plan = SupportPlan((("tests/conftest.py", "A"),), True, "", base)
    _judge_written(wb, {cid: rel}, 1, out, support=plan)
    assert [(r.status, r.support, r.reason) for r in out.records] == [("accepted", "base", "")]
    env = {**BASE_RUN_ENV, "L4_COLLECT_ONLY": rel}  # only the audit file is collected
    assert gates == [("audit-base-support", False, env)]  # the head run: the conftest is set aside
    assert seen == [(False, env)]  # and so is the zero-value run's
    assert (wb.worktree / "tests/conftest.py").read_text() == "import pytest\n"  # back after the run


# --- import_failure on real pytest output (design D15) ----------------------------------------------------------------

STEM = "test_l4_audit_c_aaaaaaaa_r1"


def collection_log(tmp_path, git_environ, audit_source, **files):
    import subprocess
    import sys
    from types import SimpleNamespace

    from l4.vcs.git import Git

    from ._integrity_helpers import new_repo

    base = {"src/pkg/__init__.py": "", f"tests/{STEM}.py": audit_source, **files}
    repo, _ = new_repo(tmp_path, git_environ, base)
    done = subprocess.run(
        [sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q"],
        cwd=repo.path, env={"PATH": "/usr/bin:/bin", "PYTHONPATH": str(repo.path / "src")},
        capture_output=True, text=True,
    )  # fmt: skip
    return done.stdout, SimpleNamespace(worktree=repo.path, git=Git(repo.path, environ=git_environ), cfg=L4Config())


def test_a_failure_in_a_production_module_is_told_with_its_file_and_line(tmp_path, git_environ):
    from l4.verifier.audit import import_failure

    log, wb = collection_log(
        tmp_path, git_environ, "from pkg.prod import X\n\n\ndef test_a():\n    assert X\n",
        **{"src/pkg/prod.py": "import os\n\nX = os.environ['L4_NOPE']\n"},
    )  # fmt: skip
    kind, detail = import_failure(log, STEM, wb)
    assert kind == "production" and detail.startswith("src/pkg/prod.py: ") and "KeyError" in detail


def test_a_failure_in_the_audit_file_alone_is_its_own(tmp_path, git_environ):
    from l4.verifier.audit import import_failure

    log, wb = collection_log(tmp_path, git_environ, "import widget_that_does_not_exist\n\n\ndef test_a():\n    pass\n")
    assert "ImportError while importing test module" in log
    assert import_failure(log, STEM, wb) == ("own", "")


def test_a_failure_in_a_helper_under_tests_is_not_production(tmp_path, git_environ):
    from l4.verifier.audit import import_failure

    log, wb = collection_log(
        tmp_path, git_environ, "from helpers import broken\n\n\ndef test_a():\n    pass\n",
        **{"tests/helpers.py": "raise RuntimeError('x')\n"},
    )  # fmt: skip
    assert import_failure(log, STEM, wb)[0] == "own"


def test_a_log_that_names_no_frame_is_unknown(tmp_path, git_environ):
    from l4.verifier.audit import import_failure

    _, wb = collection_log(tmp_path, git_environ, "def test_a():\n    pass\n")
    assert import_failure("no collection section here\n", STEM, wb) == ("unknown", "")
    section = f"__ ERROR collecting tests/{STEM}.py __\nE   something odd\n"
    assert import_failure(section, STEM, wb) == ("unknown", "")


# --- second review M3: the audit file goes where the test command collects ----------------


def test_an_honest_unit_with_a_narrowed_test_command_gets_its_audit_test_collected(
    run_l4, valid_spec, with_verifier, tdd_repo, raw
):  # SCN-VER-115, review M3 (rt2/test_rv_audit_scope.py)
    from l4.agents.fake import Step

    from ..conftest import FIXTURE, TEST_COMMAND
    from ..implementer.conftest import STUB, TESTS, UNKNOWN, result
    from ..orchestrator.conftest import new_origin_main
    from .test_ladder_depth import AUDIT_KNOWN

    (tdd_repo.repo / "tests/unit").mkdir(parents=True)
    (tdd_repo.repo / "tests/test_pricing.py").unlink()
    new_origin_main(tdd_repo, raw, {"tests/unit/test_pricing.py": (FIXTURE / "tests/test_pricing.py").read_text()})
    red = Step(
        writes={"tests/unit/test_discount.py": TESTS, "src/pytdd/pricing.py": STUB},
        structured=result(
            "red", tests_added=["tests/unit/test_discount.py::test_known_code"], criteria_ids=[KNOWN, UNKNOWN]
        ),
    )
    cid = audited_criterion()
    config = with_verifier(audit_sample_ratio=0.5)
    run = run_l4(
        [red, green_step(), writer_step(cid, AUDIT_KNOWN), JUDGE],
        test={"command": TEST_COMMAND + " tests/unit"},
        **config,
    )
    [audit] = run.events("verify.audit")
    assert audit["status"] == "accepted" and audit["path"].startswith("tests/unit/test_l4_audit_c_")
    assert run.outcome["units"][0]["verdict"] == "PASS"


def test_the_audit_directory_follows_the_test_command(tmp_path):  # SCN-VER-115
    from types import SimpleNamespace

    from l4.verifier.audit import audit_directory

    (tmp_path / "tests/unit").mkdir(parents=True)
    (tmp_path / "spec").mkdir()
    (tmp_path / "spec/test_x.py").write_text("")

    def wb(command):
        return SimpleNamespace(
            worktree=tmp_path, cfg=SimpleNamespace(gates=SimpleNamespace(test=SimpleNamespace(command=command)))
        )

    assert audit_directory(wb("python -m pytest -q -p no:cacheprovider tests/unit")) == "tests/unit"
    assert audit_directory(wb("pytest -k slow -m 'not x' tests/unit/ -q")) == "tests/unit"
    assert audit_directory(wb("pytest spec/test_x.py")) == "spec"
    assert audit_directory(wb("pytest tests/missing")) == "tests"
    assert audit_directory(wb("pytest")) == "tests"
    assert audit_directory(wb("pytest ../outside")) == "tests"
    assert audit_directory(wb("make test")) == "tests"


def test_an_audit_file_the_test_command_does_not_collect_is_a_configuration_rejection_not_a_hold(
    tmp_path, monkeypatch
):  # SCN-VER-115
    from types import SimpleNamespace

    from l4.config.schema import L4Config
    from l4.gates.junit import TestReport
    from l4.verifier.audit import AuditOutcome, _judge_written

    cid = "C-0a1b2c3d"
    rel = f"src/other/test_l4_audit_c_{cid.removeprefix('C-')}_r1.py"
    (tmp_path / "src/other").mkdir(parents=True)
    (tmp_path / rel).write_text("def test_x():\n    pass\n")
    cfg = L4Config(gates={"test": {"command": "pytest tests/unit", "reports": ["junit.xml"]}})
    wb = SimpleNamespace(
        worktree=tmp_path, cfg=cfg,
        run_gate=lambda *a, **k: SimpleNamespace(report=TestReport(), log_path=tmp_path / "none.log", reason=""),
    )  # fmt: skip
    out = AuditOutcome()
    _judge_written(wb, {cid: rel}, 1, out)  # no support change: one plain run that never saw the file
    [record] = out.records
    assert record.status == "rejected" and "`pytest tests/unit`" in record.reason and rel in record.reason
    assert not (tmp_path / rel).exists() and [f.title for f in out.findings] == ["an audit test was rejected"]


# --- third review, item 1: the audit file goes next to the unit's own red test file ----------------------------------

from ..implementer.conftest import HEADER, UNKNOWN  # noqa: E402

WEAK_TESTS = (
    HEADER
    + f'@pytest.mark.l4("{KNOWN}")\ndef test_known_code():\n    assert apply_discount(50.0, "SAVE10") == 50.0\n\n\n'
    + f'@pytest.mark.l4("{UNKNOWN}")\ndef test_unknown_code():\n    assert apply_discount(50.0, "NOPE") == 50.0\n'
)


def broken_audit_run(run_l4, with_verifier, command_tail, plant=None, tdd_repo=None, raw=None):
    import json

    from l4.agents.fake import Step

    from ..conftest import TEST_COMMAND
    from ..implementer.conftest import STUB, result
    from ..orchestrator.conftest import new_origin_main
    from .test_ladder_depth import AUDIT_KNOWN
    from .test_ladder_tamper import BROKEN_IMPL

    if tdd_repo is not None:
        (tdd_repo.repo / "tests/legacy").mkdir(parents=True)
        new_origin_main(tdd_repo, raw, {"tests/legacy/test_old.py": "def test_old():\n    assert 1\n"})
    red = Step(
        writes={"tests/test_discount.py": WEAK_TESTS, "src/pytdd/pricing.py": STUB},
        structured=result(
            "red", tests_added=["tests/test_discount.py::test_known_code"], criteria_ids=[KNOWN, UNKNOWN]
        ),
    )
    green = green_step()
    green.writes = {"src/pytdd/pricing.py": BROKEN_IMPL, **plant}
    cid = audited_criterion()
    config = with_verifier(audit_sample_ratio=0.5)
    run = run_l4(
        [red, green, writer_step(cid, AUDIT_KNOWN), JUDGE], test={"command": TEST_COMMAND + command_tail}, **config
    )
    return run, json


def test_an_ignore_option_does_not_send_the_audit_file_into_the_ignored_directory(
    run_l4, valid_spec, with_verifier, tdd_repo, raw
):  # SCN-VER-115 (third review, rt3/test_rv3_ignore.py)
    run, _ = broken_audit_run(run_l4, with_verifier, " --ignore tests/legacy tests", {}, tdd_repo, raw)
    [audit] = run.events("verify.audit")
    assert audit["path"].startswith("tests/test_l4_audit_c_") and audit["status"] == "failed"
    assert run.outcome["units"][0]["verdict"] != "PASS"  # the broken code is held, not passed by a rejection


def test_a_directory_the_unit_plants_under_an_option_values_name_is_not_the_audit_directory(
    run_l4, valid_spec, with_verifier
):  # SCN-VER-115 (third review, rt3/test_rv3_auditdir.py)
    run, _ = broken_audit_run(run_l4, with_verifier, " --tb short tests", {"short/notes.txt": "x\n"})
    [audit] = run.events("verify.audit")
    assert audit["path"].startswith("tests/test_l4_audit_c_") and audit["status"] == "failed"
    assert run.outcome["units"][0]["verdict"] != "PASS"


def test_the_audit_directory_is_the_one_of_the_units_own_red_test_file(tmp_path, git_environ):  # SCN-VER-115
    from types import SimpleNamespace

    from l4.config.schema import L4Config
    from l4.vcs.git import Git
    from l4.verifier.audit import red_test_directory

    from ._integrity_helpers import new_repo

    repo, base = new_repo(
        tmp_path, git_environ, {"README.md": "x\n", "tests/legacy/test_old.py": "def test_o():\n    pass\n"}
    )
    repo.write(
        {
            "tests/unit/test_new.py": "def test_n():\n    assert 1\n",
            "tests/unit/conftest.py": "",
            "tests/helpers/builders.py": "X = 1\n",  # no test: not a place for the audit file
            "src/code.py": "X = 1\n",
        }
    )
    head = repo.commit("work", task="1.1", tdd="red")
    wb = SimpleNamespace(git=Git(repo.path, environ=git_environ), cfg=L4Config(), worktree=repo.path)
    assert red_test_directory(wb, base, head) == "tests/unit"
    nothing = repo.commit("more", task="1.2", tdd="green")
    assert red_test_directory(wb, head, nothing) is None


def test_without_a_red_test_file_the_command_directory_is_confirmed_by_a_collect_only_run(tmp_path):  # SCN-VER-115
    from types import SimpleNamespace

    from l4.config.schema import L4Config
    from l4.verifier.audit import confirm_collected

    (tmp_path / "x.log").write_text("tests/unit/test_l4_audit_c_0a1b2c3d_r1.py::test_audit\n")
    calls = []

    def gate(name, command, **kw):
        calls.append((name, kw["extra_env"]))
        return SimpleNamespace(log_path=tmp_path / "x.log", report=None)

    cfg = L4Config(gates={"test": {"command": "pytest tests/unit", "reports": ["junit.xml"]}})
    wb = SimpleNamespace(cfg=cfg, worktree=tmp_path, run_gate=gate)
    assert confirm_collected(wb, "tests/unit/test_l4_audit_c_0a1b2c3d_r1.py") is True
    assert calls[0][0] == "audit-collect-check" and "--collect-only" in calls[0][1]["PYTEST_ADDOPTS"]
    assert confirm_collected(wb, "elsewhere/test_l4_audit_c_0a1b2c3d_r1.py") is False
