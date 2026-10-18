"""detect-test-tamper 5.1 (L4-VER-035): a generated UI test's head run uses the unit's support files at their base."""

from types import SimpleNamespace

from l4.config.schema import L4Config
from l4.verifier.support_base import SupportPlan
from l4.verifier.types import IntegrityCheck, IntegrityReport

from ..implementer.conftest import make_bench  # noqa: F401,F811
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


WB = SimpleNamespace(cfg=L4Config(), git=None)


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


def test_a_test_that_errors_without_the_units_runner_support_is_held_whatever_the_scan_says(monkeypatch):  # SCN-VER-135
    generate, runs = fake_head(monkeypatch, [{"t": "error"}, {"t": "error"}])
    for fallback in (True, False):
        runs.clear()
        plan = SupportPlan((("e2e/conftest.py", "A"),), fallback, "step 1's content scan did not read them: no", "base")
        _, _, how, why = generate._head_run(WB, None, 1, plan, "e2e/test_l4_c_x.py")
        assert how == "" and runs == ["revert", "e2e-head", "restore"]  # never a run with the unit's files in place
        assert why.startswith("it does not run without the unit's test and support files (e2e/conftest.py)")
        assert "a test of the file errored" in why


# --- the amendment (design D16): app data stays, a server that does not start holds the criterion ---------------


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


def test_a_server_that_needs_the_units_runner_support_holds_the_criterion(web, raw):  # SCN-VER-135
    from l4.verifier.support_base import unit_test_plan

    bench, base = with_app(web, raw, needs_the_units_conftest)
    bench.wb.cfg.gates.e2e.serve.timeout = "3s"
    for status, note in (("ok", "clean"), ("skipped", "not checked: python only")):
        report = IntegrityReport(checks=[IntegrityCheck("content scan", status, note)])
        plan = unit_test_plan(bench.wb.git, bench.wb.cfg, base, "HEAD", report)
        done = run_one(web, Writer(code(GOOD), code(GOOD), code(GOOD)), support=plan)
        assert done.status == "uncollectable"  # held in both cases: there is no run with the unit's files in place
        assert done.reason.startswith("the app does not start without the unit's test and support files")
        assert "e2e/conftest.py" in done.reason


# --- second review M1, M2: the reproductions of rt2/test_rv_step5.py, with the fixed behaviour ------------

from pathlib import Path  # noqa: E402

from l4.verifier.playwright import base_checkout  # noqa: E402

from .._web_bench import web_bench  # noqa: E402
from .._web_helpers import stage  # noqa: E402
from .test_generate import CRITERION  # noqa: E402

OK_SCAN = IntegrityReport(checks=[IntegrityCheck("content scan", "ok", "clean")])


def commit_all(raw, root, message):
    raw(root, "add", "-A")
    raw(root, "commit", "-q", "-m", message)
    return raw(root, "rev-parse", "HEAD").strip()


def staged(bench, raw, base_extra):
    root: Path = bench.wb.worktree
    stage(root)
    (root / ".gitignore").write_text(".venv/\n.l4-out/\n__pycache__/\ntest-results/\n")
    for rel, text in base_extra.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    base = commit_all(raw, root, "base: the cart app")
    (root / "app.py").write_text((root / "app.py").read_text().replace("3 items", "4 items"))
    commit_all(raw, root, "head: four items")
    return root, base


def judge_wrong(bench, base, plan, test_code=WRONG):
    from l4.verifier.generate import generate_ui_test

    with base_checkout(bench.wb, base) as tree:
        return generate_ui_test(
            bench.wb, Writer(code(test_code), code(test_code), code(test_code)), CRITERION, tree,
            ui_diff="+ four", snapshot="<p>4 items</p>", support=plan,
        )  # fmt: skip


def test_an_app_that_imports_a_reverted_code_file_holds_the_criterion(make_bench, raw):  # noqa: F811  SCN-VER-135, review M2
    from l4.verifier.support_base import unit_test_plan

    bench = web_bench(make_bench)
    bench.wb.cfg.verifier.independence = "none"
    bench.wb.cfg.gates.e2e.serve.timeout = "3s"
    root, base = staged(bench, raw, {})
    (root / "fixtures").mkdir()
    (root / "fixtures/seed.py").write_text("COUNT = 4\n")
    (root / "app.py").write_text("import fixtures.seed  # noqa: F401\n" + (root / "app.py").read_text())
    (root / "e2e/conftest.py").write_text(LIAR)
    commit_all(raw, root, "unit: seed module and a conftest")
    plan = unit_test_plan(bench.wb.git, bench.wb.cfg, base, "HEAD", OK_SCAN)
    done = judge_wrong(bench, base, plan)
    assert done.status == "uncollectable" and done.support == ""  # not accepted through the liar conftest
    assert "fixtures/seed.py" in done.reason and "app.py" in done.reason
    assert (root / "e2e/conftest.py").read_text() == LIAR  # restored


UTILS = (
    "import os\nimport urllib.request\n\n\ndef fetch(path):\n"
    "    return urllib.request.urlopen(os.environ['L4_E2E_BASE_URL'] + path).read().decode()\n"
)
UTILS_LIAR = "def fetch(path):\n    return '<p data-testid=\"item-count\">9 items</p>'\n"
CONFTEST_PAGE = (
    "import pytest\nfrom test_utils import fetch\n\n\n@pytest.fixture\ndef page_text():\n    return fetch('/')\n"
)
WRONG_FIXTURE = "def test_shows_nine_items(page_text):\n    assert '9 items' in page_text\n"


def test_a_helper_named_like_a_test_module_is_reverted(make_bench, raw):  # noqa: F811  SCN-VER-119, review M1
    from l4.verifier.support_base import unit_test_plan

    bench = web_bench(make_bench)
    bench.wb.cfg.verifier.independence = "none"
    root, base = staged(bench, raw, {"e2e/test_utils.py": UTILS, "e2e/conftest.py": CONFTEST_PAGE})
    (root / "e2e/test_utils.py").write_text(UTILS_LIAR)
    commit_all(raw, root, "unit: the helper")
    plan = unit_test_plan(bench.wb.git, bench.wb.cfg, base, "HEAD", OK_SCAN)
    done = judge_wrong(bench, base, plan, WRONG_FIXTURE)
    assert done.status == "fails_at_head" and done.support == "base"
