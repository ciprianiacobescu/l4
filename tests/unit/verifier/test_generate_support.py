"""detect-test-tamper 5.1 (L4-VER-035): a generated UI test's head run uses the unit's support files at their base."""

from l4.verifier.support_base import SupportPlan

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


def fake_head(monkeypatch, traced):
    """`_head_run` with the e2e runner and the support revert replaced: which runs were made, how the tests came out."""
    from contextlib import contextmanager
    from types import SimpleNamespace

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
    _, found, how, why = generate._head_run(None, None, 1, plan)
    assert (how, why, found) == ("head", "", {"t": "passed"})
    assert runs == ["revert", "e2e-head", "restore", "e2e-head-support"]


def test_without_a_clean_scan_that_test_is_uncollectable_with_the_reason(monkeypatch):  # SCN-VER-119
    generate, runs = fake_head(monkeypatch, [{"t": "error"}])
    plan = SupportPlan((("e2e/conftest.py", "A"),), False, "step 1's content scan did not read them: no", "base")
    _, _, how, why = generate._head_run(None, None, 1, plan)
    assert how == "" and runs == ["revert", "e2e-head", "restore"]
    assert why.startswith("it does not run with the unit's support files at the base (a test of the file errored)")
    assert why.endswith("step 1's content scan did not read them: no")
