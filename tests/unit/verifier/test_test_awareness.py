"""detect-test-tamper (second review N1, N2; L4-VER-039): production code that looks for the verifier's test run."""

import pytest

from l4.config.schema import L4Config
from l4.verifier.integrity import check_test_awareness, run_integrity

from ..implementer.conftest import IMPL, green_step, red_step
from ..orchestrator.conftest import new_origin_main
from ._integrity_helpers import new_repo
from .test_base_tests import CONFTEST_FIX, CONFTEST_FIX_WEAK, FIXTURE_PRICING, UNIT_DIR, failed_at_step_1
from .test_ladder import judge_step
from .test_ladder_tamper import BROKEN_TOTAL

AWARE_TITLE = "production code reacts to the test run"
BASE = {
    "src/pytdd/pricing.py": "def total(p):\n    return sum(p)\n",
    "tests/test_a.py": "def test_a():\n    assert 1\n",
}


def scan(tmp_path, git_environ, source, *, path="src/pytdd/pricing.py", human=False, cfg=None):
    repo, base = new_repo(tmp_path, git_environ, BASE)
    repo.write({path: source})
    head = repo.commit_as_human("a person's change") if human else repo.commit("work", task="1.1", tdd="green")
    return check_test_awareness(repo.context(base, head, cfg=cfg))


@pytest.mark.parametrize(
    "line",
    [
        'OUT = ".l4-out/junit.xml"',
        'import os\nX = os.environ["L4_E2E_BASE_URL"]',
        'import os\nX = os.environ.get("PYTEST_ADDOPTS", "")',
        'import os\nX = os.environ.get("PYTEST_CURRENT_TEST")',
    ],
)
def test_a_production_line_that_names_the_runs_environment_or_output_is_a_blocker(tmp_path, git_environ, line):
    out = scan(tmp_path, git_environ, f"def total(p):\n    return sum(p)\n\n\n{line}\n")
    [finding] = out.findings
    assert finding.title == AWARE_TITLE and "src/pytdd/pricing.py:" in finding.detail


def test_the_configured_report_path_is_a_blocker_too(tmp_path, git_environ):
    cfg = L4Config(gates={"test": {"command": "pytest", "reports": ["build/report.xml"]}})
    out = scan(tmp_path, git_environ, 'REPORT = "build/report.xml"\n', cfg=cfg)
    assert [f.title for f in out.findings] == [AWARE_TITLE]


@pytest.mark.parametrize(
    "line",
    [
        'import sys\nX = "pytest" in sys.modules',
        "import pytest",
        "import _pytest",
        "import atexit\natexit.register(print)",
        'import sys\nX = any("pytest" in a for a in sys.argv)',
    ],
)
def test_other_signs_of_a_test_run_are_listed_for_the_judge_not_blocked(tmp_path, git_environ, line):
    out = scan(tmp_path, git_environ, f"{line}\n")
    assert out.findings == [] and len(out.listed) == 1 and "src/pytdd/pricing.py:" in out.listed[0]


@pytest.mark.parametrize("path", ["tests/test_a.py", "tests/conftest.py", f"{UNIT_DIR}/design.md"])
def test_test_files_support_files_and_spec_folders_are_not_scanned(tmp_path, git_environ, path):
    out = scan(tmp_path, git_environ, 'X = ".l4-out/junit.xml"\n', path=path)
    assert out.findings == [] and out.listed == []


def test_a_persons_edit_is_listed_not_blocked(tmp_path, git_environ):
    out = scan(tmp_path, git_environ, 'X = ".l4-out/junit.xml"\n', human=True)
    assert out.findings == [] and len(out.human_scan) == 1 and ".l4-out" in out.human_scan[0]


def test_the_row_and_the_listing_reach_the_report(tmp_path, git_environ):
    repo, base = new_repo(tmp_path, git_environ, BASE)
    repo.write({"src/pytdd/pricing.py": "import atexit\natexit.register(print)\n"})
    report = run_integrity(repo.context(base, repo.commit("work", task="1.1", tdd="green")))
    assert "test awareness" in [c.name for c in report.checks]
    assert len(report.test_awareness) == 1


# --- the reviewer's N1 and N2 scripts, end to end: both must end FAIL ------

ENV_DETECT = IMPL.replace(
    "def total(prices: list[float]) -> float:\n    return round(sum(prices), 2)",
    "def total(prices: list[float]) -> float:\n    import os\n\n"
    "    if '--continue-on-collection-errors' in os.environ.get('PYTEST_ADDOPTS', ''):\n"
    "        return round(sum(prices), 2)\n"
    "    return 0 if not prices else 999.0",
)
FORGE = """

import atexit as _atexit
import os as _os
import re as _re


def _l4_forge():
    path = _os.path.join(".l4-out", "junit.xml")
    try:
        with open(path) as handle:
            text = handle.read()
    except OSError:
        return
    text = _re.sub(r"<failure\\b.*?</failure>", "", text, flags=_re.S)
    text = _re.sub(r'failures="\\d+"', 'failures="0"', text)
    with open(path, "w") as handle:
        handle.write(text)
    _os._exit(0)


_atexit.register(_l4_forge)
"""


def test_n1_production_code_that_recognises_the_base_tests_run_fails_step_1(run_l4, valid_spec, tdd_repo, raw):
    assert ENV_DETECT != IMPL
    new_origin_main(tdd_repo, raw, {"tests/conftest.py": CONFTEST_FIX, "tests/test_pricing.py": FIXTURE_PRICING})
    red = red_step()
    red.writes = {**red.writes, "tests/conftest.py": CONFTEST_FIX_WEAK}
    green = green_step()
    green.writes = {"src/pytdd/pricing.py": ENV_DETECT}
    run = run_l4([red, green, judge_step()])
    text = failed_at_step_1(run, AWARE_TITLE, row="| test awareness |")
    assert "src/pytdd/pricing.py:" in text and "PYTEST_ADDOPTS" in text


def test_n2_production_code_that_forges_the_junit_report_fails_step_1(run_l4, valid_spec):
    green = green_step()
    green.writes = {"src/pytdd/pricing.py": BROKEN_TOTAL + FORGE}
    run = run_l4([red_step(), green, judge_step()])
    text = failed_at_step_1(run, AWARE_TITLE, row="| test awareness |")
    assert ".l4-out" in text
