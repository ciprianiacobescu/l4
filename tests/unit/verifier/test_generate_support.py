"""detect-test-tamper 5.1 (L4-VER-035): a generated UI test's head run uses the unit's support files at their base."""

from types import SimpleNamespace

from l4.config.schema import L4Config
from l4.verifier.support_base import SupportPlan
from l4.verifier.types import IntegrityCheck, IntegrityReport

from ..implementer.conftest import make_bench  # noqa: F401
from .test_generate import GOOD, WRONG, Writer, code, run_one
from .test_generate import web as web  # noqa: F401  (the fixture)

LIAR = (
    "import urllib.request\n\nimport pytest\n\n\nclass _Page:\n    def read(self):\n"
    "        return b'<p class=\"item-count\">9 items</p>'\n\n\n"
    "@pytest.fixture(autouse=True)\ndef _page(monkeypatch):\n"
    "    monkeypatch.setattr(urllib.request, 'urlopen', lambda *a, **k: _Page())\n"
)
HARMLESS = "import pytest\n\n\n@pytest.fixture\ndef nothing():\n    return 1\n"


def commit_conftest(web, raw, text):
    bench, base = web
    root = bench.wb.worktree
    (root / "e2e/conftest.py").write_text(text)
    raw(root, "add", "e2e/conftest.py")
    raw(root, "commit", "-q", "-m", "unit conftest")
    return SupportPlan((("e2e/conftest.py", "A"),), True, "", base)


def test_the_head_run_does_not_use_the_units_own_conftest(web, raw):  # SCN-VER-119
    plan = commit_conftest(web, raw, LIAR)
    bench, _ = web
    done = run_one(web, Writer(code(WRONG), code(WRONG)), support=plan)
    assert done.status == "fails_at_head" and done.support == "base"
    assert (bench.wb.worktree / "e2e/conftest.py").read_text() == LIAR  # back after the run


def test_without_the_plan_the_liar_conftest_makes_the_test_pass(web, raw):  # SCN-VER-119 (the hole)
    commit_conftest(web, raw, LIAR)
    done = run_one(web, Writer(code(WRONG)), support=SupportPlan())
    assert done.status == "accepted" and done.support == "unchanged"


def test_an_honest_units_generated_test_is_accepted_with_the_base_support_files(web, raw):  # SCN-VER-122
    plan = commit_conftest(web, raw, HARMLESS)
    done = run_one(web, Writer(code(GOOD)), support=plan)
    assert done.accepted and done.support == "base"


WB = SimpleNamespace(cfg=L4Config())


def fake_head(monkeypatch, traced):
    """`_head_run` with the e2e runner and the support revert replaced: which runs were made, how the tests came out."""
    from contextlib import contextmanager

    from l4.verifier import generate

    runs, answers = [], iter(traced)

    @contextmanager
    def no_revert(*args):
        runs.append("revert")
        yield []
        runs.append("restore")

    monkeypatch.setattr(generate, "support_at_base", no_revert)
    monkeypatch.setattr(
        generate, "run_e2e", lambda wb, *a, name, **k: runs.append(name) or SimpleNamespace(report=None)
    )
    monkeypatch.setattr(generate, "_traced", lambda *a: next(answers))
    return generate, runs


def test_a_test_that_errors_at_the_base_support_runs_with_it_only_after_a_clean_scan(monkeypatch):  # SCN-VER-119
    generate, runs = fake_head(monkeypatch, [{"t": "error"}, {"t": "passed"}])
    plan = SupportPlan((("e2e/conftest.py", "A"),), True, "", "base")
    _, found, how, why = generate._head_run(WB, None, 1, plan, "e2e/test_l4_c_x.py")
    assert (how, why, found) == ("head", "", {"t": "passed"})
    assert runs == ["revert", "e2e-head", "restore", "e2e-head-support"]


def test_without_a_clean_scan_that_test_is_uncollectable_with_the_reason(monkeypatch):  # SCN-VER-119
    generate, runs = fake_head(monkeypatch, [{"t": "error"}])
    plan = SupportPlan((("e2e/conftest.py", "A"),), False, "step 1's content scan did not read them: no", "base")
    _, _, how, why = generate._head_run(WB, None, 1, plan, "e2e/test_l4_c_x.py")
    assert how == "" and runs == ["revert", "e2e-head", "restore"]
    assert why.startswith("it does not run with the unit's support files at the base (a test of the file errored)")
    assert why.endswith("step 1's content scan did not read them: no")


# --- the amendment (design D16): app data stays, a server that does not start takes the fallback rule ----------


def with_app(web, raw, edit):
    """Commit a change of the head app (and files) on top of the staged head."""
    bench, base = web
    root = bench.wb.worktree
    edit(root)
    raw(root, "add", "-A")
    raw(root, "commit", "-q", "-m", "head: the app changes")
    return bench, base


def test_added_app_data_under_fixtures_stays_for_the_head_run(web, raw):  # SCN-VER-134
    from l4.verifier.support_base import unit_test_plan

    def edit(root):
        app = (root / "app.py").read_text()
        app = app.replace(
            'body = PAGE.encode() if self.path == "/" else b"not found"',
            'body = (open("fixtures/cart.html").read().encode()) if self.path == "/" else b"not found"',
        )
        (root / "app.py").write_text(app)
        (root / "fixtures").mkdir()
        (root / "fixtures/cart.html").write_text('<p data-testid="item-count">4 items</p>\n')

    bench, base = with_app(web, raw, edit)
    ok = IntegrityReport(checks=[IntegrityCheck("content scan", "ok", "clean")])
    plan = unit_test_plan(bench.wb.git, bench.wb.cfg, base, "HEAD", ok)
    assert "fixtures/cart.html" not in dict(plan.changes)
    done = run_one(web, Writer(code(GOOD), code(GOOD), code(GOOD)), support=plan)
    assert done.accepted
    assert (bench.wb.worktree / "fixtures/cart.html").exists()


def needs_the_units_conftest(root):
    app = (root / "app.py").read_text()
    guard = "import os, sys\n\nif not os.path.exists('e2e/conftest.py'):\n    sys.exit(3)\n"
    (root / "app.py").write_text(guard + app)
    (root / "e2e/conftest.py").write_text("import pytest\n")


def test_a_server_that_needs_the_units_runner_support_takes_the_fallback_rule(web, raw):  # SCN-VER-135
    from l4.verifier.support_base import unit_test_plan

    bench, base = with_app(web, raw, needs_the_units_conftest)
    bench.wb.cfg.gates.e2e.serve.timeout = "3s"
    ok = IntegrityReport(checks=[IntegrityCheck("content scan", "ok", "clean")])
    plan = unit_test_plan(bench.wb.git, bench.wb.cfg, base, "HEAD", ok)
    done = run_one(web, Writer(code(GOOD), code(GOOD), code(GOOD)), support=plan)
    assert done.accepted and done.support == "head"
    skipped = IntegrityReport(checks=[IntegrityCheck("content scan", "skipped", "not checked: python only")])
    plan = unit_test_plan(bench.wb.git, bench.wb.cfg, base, "HEAD", skipped)
    done = run_one(web, Writer(code(GOOD), code(GOOD), code(GOOD)), support=plan)
    assert done.status == "uncollectable"
    assert done.reason.startswith("the app does not start with the unit's support files at the base")
    assert "step 1's content scan did not read them" in done.reason
