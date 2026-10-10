import hashlib
from pathlib import Path

import pytest

from l4.agents.base import RunResult, Usage
from l4.exitcodes import ExitCode, L4Exit
from l4.implementer.tdd import RoleLimit
from l4.llm.agent_judge import StructuredResult
from l4.memory.curate import UI_GAP_TITLE
from l4.specs.base import Criterion, Framework
from l4.verifier.generate import MAX_ATTEMPTS, generate_ui_test, generate_ui_tests, ui_gap_finding
from l4.verifier.playwright import base_checkout
from l4.verifier.testwriter import test_path

from .._web_bench import stage_base_and_head, web_bench
from ..implementer.conftest import make_bench  # noqa: F401

CID = "C-de7f2d3f"
CRITERION = Criterion(CID, "web › Cart › Count", Framework.OPENSPEC, "web", "Cart", "Count",
                      "WHEN the cart page opens THEN it shows 4 items", "spec.md", 3)  # fmt: skip
READ = (
    "import os, urllib.request\n\n\ndef page():\n"
    "    return urllib.request.urlopen(os.environ['L4_E2E_BASE_URL'] + '/').read().decode()\n"
)
GOOD = READ + "\n\ndef test_shows_four_items():\n    assert 'item-count\">4 items<' in page()\n"
VACUOUS = READ + "\n\ndef test_page_is_served():\n    assert page()\n"
WRONG = READ + "\n\ndef test_shows_nine_items():\n    assert '9 items' in page()\n"
ERRORS = "def test_x(a_fixture_nobody_defined):\n    pass\n"
BROKEN = "import module_that_does_not_exist\n\n\ndef test_x():\n    pass\n"


class Writer:
    """A scripted tool-less judge: each call pops one structured reply (a dict, or a `StructuredResult`)."""

    def __init__(self, *replies) -> None:
        self.replies, self.prompts = list(replies), []

    def complete_structured(self, system, messages, json_schema, *, effort, max_tokens, timeout_s):
        self.prompts.append(messages[0].content)
        reply = self.replies.pop(0)
        if isinstance(reply, StructuredResult):
            return reply
        return StructuredResult("ok", reply, "writer-1", Usage(cost_usd=0.01))


def code(text: str) -> dict:
    return {"criterion": CID, "code": text}


@pytest.fixture
def web(make_bench, raw):  # noqa: F811
    bench = web_bench(make_bench)
    base = stage_base_and_head(bench, raw)
    bench.wb.cfg.verifier.independence = "none"
    return bench, base


def run_one(web, writer, **kw):
    bench, base = web
    with base_checkout(bench.wb, base) as tree:
        return generate_ui_test(bench.wb, writer, CRITERION, tree, ui_diff="+ four", snapshot="<p>4 items</p>", **kw)


def test_generated_test_accepted_when_discriminating(web):
    bench, _ = web
    done = run_one(web, Writer(code(GOOD)))
    assert done.accepted and done.attempts == 1 and done.path == test_path("e2e", CID) == "e2e/test_l4_c_de7f2d3f.py"
    assert GOOD in (bench.wb.worktree / done.path).read_text()  # kept at the head, for the per-round commit
    assert done.cost_usd == 0.01 and done.model == "writer-1"
    names = [e["name"] for e in bench.events("gate.finished")]
    assert names.count("e2e-base") == 1 and names.count("e2e-head") == 1


def test_first_attempt_passing_at_baseline_is_rejected_then_retry_accepted(web):
    bench, _ = web
    writer = Writer(code(VACUOUS), code(GOOD))
    done = run_one(web, writer)
    assert done.accepted and done.attempts == 2
    assert "passes at the merge base" in writer.prompts[1] and "passes at the merge base" not in writer.prompts[0]
    assert GOOD in (bench.wb.worktree / done.path).read_text()  # the retry overwrote the file of the first try


def test_two_non_discriminating_attempts_leave_criterion_uncovered(web):
    bench, _ = web
    done = run_one(web, Writer(code(VACUOUS), code(VACUOUS)))
    assert done.status == "non_discriminating" and done.attempts == MAX_ATTEMPTS and not done.accepted
    assert done.code == VACUOUS and not (bench.wb.worktree / done.path).exists()  # evidence only, never committed


def test_test_that_fails_at_head_is_evidence_not_a_commit(web):
    bench, _ = web
    done = run_one(web, Writer(code(WRONG), code(WRONG)))
    assert done.status == "fails_at_head" and "fails at the head" in done.reason and done.code == WRONG
    assert not (bench.wb.worktree / done.path).exists()


def test_not_testable_and_uncollectable_stop_at_once(web):
    done = run_one(web, Writer({"criterion": CID, "not_testable": "needs a real payment provider"}))
    assert done.status == "not_testable" and done.attempts == 1 and done.path is None
    assert "payment provider" in done.reason
    writer = Writer(code(BROKEN), code(GOOD))
    done = run_one(web, writer)
    assert done.status == "uncollectable" and done.attempts == 1 and len(writer.replies) == 1  # no retry


def test_invalid_reply_is_retried_and_a_limit_is_not_swallowed(web):
    writer = Writer(StructuredResult("schema_invalid", None, detail="criterion: missing"), code(GOOD))
    done = run_one(web, writer)
    assert done.accepted and done.attempts == 2 and "criterion: missing" in writer.prompts[1]
    with pytest.raises(RoleLimit):
        run_one(web, Writer(StructuredResult("limit", None, detail="quota", run=RunResult("quota", Path("x")))))
    failed = run_one(web, Writer(StructuredResult("timeout", None, detail="no answer")))
    assert failed.status == "writer_failed" and failed.attempts == 1


def test_lint_runs_on_the_head_and_a_rejected_file_is_never_run(web):
    bench, _ = web
    bench.wb.cfg.gates.lint = ["python3 -c 'raise SystemExit(1)'"]
    done = run_one(web, Writer(code(GOOD), code(GOOD)))
    assert done.status == "lint_failed" and "failed" in done.reason
    assert not [e for e in bench.events("gate.finished") if e["name"].startswith("e2e-")]


def test_an_existing_test_file_is_never_overwritten(web):
    bench, _ = web
    existing = bench.wb.worktree / test_path("e2e", CID)
    existing.write_text("def test_mine():\n    pass\n")
    done = run_one(web, Writer(code(GOOD)))
    assert done.status == "writer_failed" and "already exists" in done.reason
    assert existing.read_text() == "def test_mine():\n    pass\n"


@pytest.mark.parametrize("second", [GOOD, WRONG])
def test_an_implementer_file_survives_a_retry(web, second):
    bench, _ = web
    mine = "@pytest.mark.skip\ndef test_mine():\n    pass\n"
    existing = bench.wb.worktree / test_path("e2e", CID)
    existing.write_text(mine)
    writer = Writer(StructuredResult("schema_invalid", None, detail="criterion: missing"), code(second))
    done = run_one(web, writer)
    assert done.status == "writer_failed" and "already exists" in done.reason and done.attempts == 2
    assert existing.read_text() == mine  # neither overwritten on the retry nor deleted afterwards


def test_prompt_carries_scenario_diff_and_snapshot_as_data(web):
    writer = Writer(code(GOOD))
    run_one(web, writer)
    prompt = writer.prompts[0]
    assert prompt.count('<l4:data source="scenario">') == 1 and 'source="ui diff"' in prompt
    assert 'source="page snapshot"' in prompt and "WHEN the cart page opens" in prompt


def test_generate_ui_tests_returns_paths_and_removes_the_base_checkout(web):
    bench, base = web
    wb = bench.wb
    result = generate_ui_tests(wb, Writer(code(GOOD)), [CRITERION], base_sha=base, ui_diff="d", snapshot="s")
    assert result.paths == ["e2e/test_l4_c_de7f2d3f.py"] and result.uncovered == []
    assert not (wb.unit_cache / "e2e-base").exists()
    assert "e2e-base" not in wb.git.run("worktree", "list").stdout
    (event,) = bench.events("verify.generated")  # the live protocol's shape
    assert (event["status"], event["test"], event["base"], event["head"], event["attempts"]) == (
        "accepted",
        "e2e/test_l4_c_de7f2d3f.py",
        "fail",
        "pass",
        1,
    )
    (done,) = result.outcomes  # what a later round needs to recognise the test as ours
    assert len(done.tests) == 1 and done.tests[0].endswith("test_shows_four_items")
    assert event["tests"] == list(done.tests) and event["sha256"] == done.sha256
    assert done.sha256 == hashlib.sha256((wb.worktree / done.path).read_bytes()).hexdigest()
    nothing = generate_ui_tests(wb, Writer(), [], base_sha=base, ui_diff="d", snapshot="s")
    assert nothing.paths == [] and nothing.outcomes == []


def test_a_server_that_is_never_ready_is_an_internal_error_and_cleans_up(web):
    bench, base = web
    wb = bench.wb
    wb.cfg.gates.e2e.serve.command = "python3 -c 'import time; time.sleep(120)'"
    wb.cfg.gates.e2e.serve.timeout = "1s"
    with pytest.raises(L4Exit) as err:
        generate_ui_tests(wb, Writer(code(GOOD)), [CRITERION], base_sha=base, ui_diff="d", snapshot="s")
    assert err.value.code == ExitCode.INTERNAL_ERROR
    assert not (wb.unit_cache / "e2e-base").exists() and not (wb.worktree / test_path("e2e", CID)).exists()


def test_the_ui_gap_finding_is_the_one_the_lesson_rule_matches():
    finding = ui_gap_finding(CRITERION)
    assert finding.title == UI_GAP_TITLE and finding.source == "deterministic" and finding.criterion == CID
    assert not finding.blocking


def test_a_test_that_errors_at_the_base_is_never_accepted(web):
    bench, _ = web
    done = run_one(web, Writer(code(ERRORS), code(ERRORS)))
    assert done.status == "base_error" and done.base == "error" and "merge base" in done.reason
    assert not done.accepted and not (bench.wb.worktree / done.path).exists()
    assert not [e for e in bench.events("gate.finished") if e["name"] == "e2e-head"]  # the head was not even run


def test_a_base_that_cannot_be_served_is_about_the_unit_not_exit_1(web):
    bench, base = web
    with base_checkout(bench.wb, base) as tree:
        (tree / "app.py").unlink()  # the unit introduces the app
        done = generate_ui_test(
            bench.wb, Writer(code(GOOD)), CRITERION, tree, ui_diff="+ four", snapshot="<p>4 items</p>"
        )
    assert done.status == "base_unservable" and done.attempts == 1 and not done.accepted
    assert not (bench.wb.worktree / done.path).exists()


def test_an_error_only_at_the_base_does_not_pass_for_a_failure(web):
    bench, _ = web
    (bench.wb.worktree / "head_only.txt").write_text("x")
    setup_error_at_base = (
        "import os\n\nimport pytest\n\n\n@pytest.fixture\ndef gate():\n    assert os.path.exists('head_only.txt')\n\n\n"
        "def test_x(gate):\n    pass\n"
    )
    done = run_one(web, Writer(code(setup_error_at_base), code(setup_error_at_base)))
    assert done.status == "base_error" and done.head is None and not done.accepted


def test_a_skipped_generated_test_is_uncollectable_without_a_retry(web):
    skipped = "import pytest\n\n\n@pytest.mark.skip\ndef test_x():\n    pass\n"
    writer = Writer(code(skipped), code(GOOD))
    done = run_one(web, writer)
    assert done.status == "uncollectable" and done.attempts == 1 and len(writer.replies) == 1


def test_a_generated_test_that_rewrites_its_own_file_is_committed_as_the_harness_wrote_it(web):
    bench, _ = web
    evil = (
        "from pathlib import Path\n\n\n"
        "def test_shows_four_items():\n"
        "    Path(__file__).write_text('# fo' + 'rged\\n')\n"
        "    assert 'item-count\">4 items<' in page()\n"
    )
    done = run_one(web, Writer(code(READ + "\n\n" + evil)))
    assert done.accepted
    text = (bench.wb.worktree / done.path).read_text()
    assert "# fo" "rged" not in text and "def test_shows_four_items" in text
    assert done.sha256 == hashlib.sha256(text.encode()).hexdigest()
