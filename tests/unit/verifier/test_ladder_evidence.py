"""Join lines 13 and 14: the ladder runs Stage A. Real git, a real pytest with the `l4_cov` plugin through the gate, a
scripted fake agent for the implementer and for the judge, on the `py_multi` fixture (cart-totals is the unit; the
four units before it are in the history)."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest
import yaml

from l4.agents.factory import ADAPTERS
from l4.agents.fake import FakeAdapter, Step
from l4.cli import main
from l4.specs.criteria import openspec_criteria
from l4.vcs.git import Git

from ..conftest import TddRepo
from ..evidence._multi import FIXTURE, build_repo
from ..implementer.conftest import result
from ..orchestrator import conftest as oc
from .conftest import judge_reply

UNIT = "openspec:cart-totals"
UNIT_DIR = "openspec/changes/cart-totals"
SPEC = FIXTURE / "units" / "05-cart-totals" / "spec" / UNIT_DIR
CID = openspec_criteria(SPEC)[0].id
TESTS = f'''import pytest

from shop.cart import cart_total


@pytest.mark.l4("{CID}")
def test_total_with_discount_and_tax():
    assert cart_total([(100, 2), (50, 4)], "SAVE10", 1000) == 396


@pytest.mark.l4("{CID}")
def test_total_without_code():
    assert cart_total([(100, 1)], None, 0) == 100
'''
SKIPPING = TESTS.replace("import pytest\n", "import sys\n\nimport pytest\n").replace(
    "    assert cart_total([(100, 1)], None, 0) == 100\n",
    '    if "l4_" + "cov" in sys.modules:\n        getattr(pytest, "sk" + "ip")("skipped only where the verifier")\n'
    "    assert cart_total([(100, 1)], None, 0) == 100\n",
)  # passes in the implementer's gates and is skipped in the verifier's run (the coverage plugin is loaded there);
# written without a literal skip marker or plugin name, which the integrity scan of step 1 already catches
STUB = "def cart_total(lines, code, rate_bp):\n    raise NotImplementedError\n"
GREEN = (FIXTURE / "units" / "05-cart-totals" / "green" / "src" / "shop" / "cart.py").read_text()
EXTRA_FUNCTION = (
    "\n\ndef describe(lines):\n    parts = []\n    for base, qty in lines:\n        parts.append(f'{qty} x {base}')\n"
    "    text = ', '.join(parts)\n    return text or 'empty'\n"
)
STOCK = {  # unit 4's version of the file, one covered line changed: the edit belongs to module `inventory`
    "src/inventory/stock.py": (FIXTURE / "units/04-low-stock-alerts/green/src/inventory/stock.py")
    .read_text()
    .replace("self._levels.get(sku, 0) + qty", "self.on_hand(sku) + qty")
}


def red(tests: str = TESTS) -> Step:
    return Step(
        writes={"tests/test_cart.py": tests, "src/shop/cart.py": STUB},
        structured=result("red", tests_added=["tests/test_cart.py::test_total_without_code"], criteria_ids=[CID]),
    )


def green(extra: dict[str, str] | None = None) -> Step:
    return Step(writes={"src/shop/cart.py": GREEN, **(extra or {})}, structured=result("green"))


def judge() -> Step:
    return Step(structured=judge_reply([CID]))


@pytest.fixture
def multi(tmp_path: Path, git_environ: dict[str, str], raw: Callable[..., str]) -> TddRepo:
    """Units 1 to 4 done on `main`, the cart-totals spec committed, a bare `origin`."""
    repo = tmp_path / "repo"
    _, units = build_repo(repo, git=Git(repo, environ=git_environ), units=5)
    raw(repo, "reset", "-q", "--hard", units[4].base)
    raw(repo, "rm", "-q", "--cached", ".l4/config.yaml")  # the test writes the config, untracked like py_tdd's
    raw(repo, "commit", "-q", "-m", "untrack the fixture config")
    bare = tmp_path / "origin.git"
    raw(tmp_path, "init", "-q", "--bare", str(bare))
    raw(repo, "remote", "add", "origin", str(bare))
    raw(repo, "push", "-q", "origin", "main")
    raw(repo, "fetch", "-q", "origin")
    script = tmp_path / "mkvenv.py"
    from ..conftest import MKVENV

    script.write_text(MKVENV)
    environ = {**git_environ, "L4_CACHE": str(tmp_path / "cache"), "L4_HOME": str(tmp_path / "l4home")}
    return TddRepo(repo, environ, tmp_path / "cache", script, bare)


@pytest.fixture
def run_multi(multi: TddRepo, raw, monkeypatch, valid_spec):
    """`l4 run --unit openspec:cart-totals` with a scripted agent; `Run`'s accessors point at this unit."""
    monkeypatch.setattr(oc, "BRANCH", "l4/openspec/cart-totals")
    monkeypatch.setattr(oc, "LOCK_REF", "refs/l4/locks/openspec/cart-totals")
    monkeypatch.setattr(oc, "UNIT_DIR", UNIT_DIR)
    monkeypatch.setattr(oc, "UNIT", UNIT)

    def run(script: list[Step], *, scope: str = "warn", coverage: str = "warn", edit=None) -> oc.Run:
        body = yaml.safe_load(multi.config())
        body["sdd"] = {"scope_check": scope}
        body["verifier"] = {"evidence": {"diff_coverage": {"mode": coverage}}}
        if edit is not None:
            edit(body)
        (multi.repo / ".l4").mkdir(exist_ok=True)
        (multi.repo / ".l4" / "config.yaml").write_text(yaml.safe_dump(body))
        adapter = FakeAdapter(script)
        monkeypatch.setitem(ADAPTERS, "fake", lambda: adapter)
        argv = ["run", "--unit", UNIT, "--repo", str(multi.repo)]
        return oc.Run(main(argv, environ=multi.environ), adapter, multi, raw)

    return run


def evidence(run: oc.Run, round_no: int = 1) -> dict:
    return json.loads(run.pushed(f"{UNIT_DIR}/.l4/evidence/round-{round_no}/evidence.json"))


def report(run: oc.Run) -> str:
    return run.pushed(f"{UNIT_DIR}/verification.md")


def steps(run: oc.Run) -> dict[str, str]:
    return {e["step"]: e["status"] for e in run.events("verify.step")}


def test_iv_a_clean_unit_passes_with_every_evidence_row_green(run_multi):
    run = run_multi([red(), green(), judge()])
    assert run.code == 0 and run.outcome["units"][0]["verdict"] == "PASS"
    assert steps(run)["6"] == "ok" and steps(run)["1"] == "ok"
    text = report(run)
    assert "## Evidence" in text and "Nothing needs attention." in text
    assert text.index("## Traceability") < text.index("## Evidence")
    ev = evidence(run)
    assert ev["schema"] == "l4/evidence@1" and ev["holds"] == []
    assert {f["label"] for f in ev["scope"]["files"]} - {None} == {"relevant"}  # the unit's own files carry none
    assert ev["diff_coverage"]["status"] == "ok" and ev["tests_ran"]["tests_ok"] is True
    assert {f["status"] for f in ev["diff_coverage"]["functions"]} == {"covered"}
    assert json.loads(run.pushed(f"{UNIT_DIR}/.l4/evidence/round-1/verdict.json"))["evidence"] == ev


def test_i_an_edit_in_another_module_is_a_hold_with_a_verdict_question_under_warn(run_multi):
    edit = STOCK
    run = run_multi([red(), green(edit), judge()])
    assert run.code == 11 and run.outcome["units"][0]["verdict"] == "NEEDS_HUMAN"
    ev = evidence(run)
    [hold] = ev["holds"]
    assert hold["kind"] == "scope" and hold["subjects"] == ["src/inventory/stock.py"]
    assert {f["path"]: f["label"] for f in ev["scope"]["files"]}["src/inventory/stock.py"] == "out_of_scope"
    assert hold["text"] in report(run)
    questions = run.pushed(f"{UNIT_DIR}/questions.md")
    assert hold["id"] in questions and "src/inventory/stock.py" in questions


def test_i_the_same_edit_is_a_deterministic_major_finding_under_fail(run_multi):
    edit = STOCK
    run = run_multi([red(), green(edit), judge()], scope="fail")
    assert run.code == 10 and run.outcome["units"][0]["verdict"] == "FAIL"
    assert "change outside the feature: src/inventory/stock.py" in report(run)
    assert evidence(run)["holds"] == []


def test_ii_an_untested_added_function_is_uncovered_and_held(run_multi):
    run = run_multi([red(), green({"src/shop/cart.py": GREEN + EXTRA_FUNCTION}), judge()])
    assert run.code == 11
    ev = evidence(run)
    status = {f["qualname"]: f["status"] for f in ev["diff_coverage"]["functions"]}
    assert status["describe"] == "uncovered" and status["cart_total"] == "covered"
    [hold] = ev["holds"]
    assert hold["kind"] == "coverage" and hold["subjects"] == ["src/shop/cart.py::describe"]
    assert "changed code not run by tests: `src/shop/cart.py::describe`" in report(run)


def test_ii_the_same_gap_is_a_major_finding_under_fail(run_multi):
    run = run_multi([red(), green({"src/shop/cart.py": GREEN + EXTRA_FUNCTION}), judge()], coverage="fail")
    assert run.code == 10 and "changed code is not covered by tests" in report(run)


def test_iii_a_new_test_that_is_skipped_fails_the_unit(run_multi):
    run = run_multi([red(SKIPPING), green()])
    assert run.code == 10 and run.outcome["units"][0]["verdict"] == "FAIL"
    text = report(run)
    assert "| 3 | tests | failed |" in text and "| 9 | judge | not_run |" in text  # no judge call: it fails already
    assert "[blocker, deterministic] new tests were skipped" in text
    assert evidence(run)["tests_ran"]["tests_ok"] is False


def test_the_shadow_and_off_modes_do_not_change_the_verdict(run_multi):
    run = run_multi([red(), green(), judge()], coverage="off", scope="off")
    assert run.code == 0
    ev = evidence(run)
    assert ev["diff_coverage"] is None and ev["holds"] == []


# -- join line 29: a human's verdict on a hold becomes a label the export reads


def _shadow_profile(body: dict) -> None:
    body["profiles"]["s1"] = {"backend": "system-one", "engine": "remote", "base_url": "http://s1.test"}
    body["verifier"]["s1"] = {"shadow": ["s1"]}


def _answer_holds(multi: TddRepo, raw, run: oc.Run, text: str) -> None:
    from ..orchestrator.conftest import edit_questions_on_origin

    edit_questions_on_origin(multi, raw, status="answered", answer=text)
    raw(multi.repo, "fetch", "-q", "origin")


def _labels(run: oc.Run) -> list[dict]:
    path = run.tdd.cache / "s1-calibration.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    return [r for r in rows if r.get("kind") == "label"]


def test_reject_on_scope_hold_appends_out_of_scope_label(run_multi, multi, raw, monkeypatch):
    from l4.s1 import export
    from l4.s1.shadow import ShadowRun
    from l4.verifier import ladder

    monkeypatch.setattr(ladder, "run_shadow", lambda cfg, items, **kw: ShadowRun(list(items), [], [], []))
    first = run_multi([red(), green(STOCK), judge()], edit=_shadow_profile)
    assert first.code == 11
    [hold] = evidence(first)["holds"]
    assert _labels(first) == []  # nothing is a label before a human has answered
    _answer_holds(multi, raw, first, "reject: inventory is not part of this unit")
    second = run_multi([], edit=_shadow_profile)
    assert second.events("human.verdict")
    [label] = _labels(second)
    key = evidence(first)["items"]["l4/file-relevant@1|src/inventory/stock.py"]
    assert (label["item_key"], label["label"], label["truth"]) == (key, "out_of_scope", {"relevant": False})
    assert label["source"] == "human:verdict" and export.source_allowed(label["source"])
    out = second.tdd.repo / ".l4-out" / "s1"
    artefact = [json.loads(ln) for f in out.glob("*.jsonl") for ln in f.read_text().splitlines()]
    assert label in [r for r in artefact if r.get("kind") == "label"]  # also in the job's artefact, for the live read
    rows = export.ground_truth_rows([second.tdd.cache / "s1-calibration.jsonl"]).rows
    [row] = [r for r in rows if f"item:{key}" in r.tags]
    assert "label_source:human:verdict" in row.tags and row.expected["relevant"] is False
    third = run_multi([], edit=_shadow_profile)  # the same answer, seen again, is not labelled twice
    assert len(_labels(third)) == 1
    assert hold["subjects"] == ["src/inventory/stock.py"]


def test_the_label_is_written_even_when_no_judge_is_left_for_the_round(run_multi, multi, raw, monkeypatch):
    """`consume_verdicts` consumes an answer once (`human.verdict` keeps its hash), so the label must be written before
    anything of the round can fail: a round with no judge left (exit 12) after the answer was consumed would otherwise
    lose the label for good, since the next run finds the answer consumed."""
    from datetime import UTC, datetime

    from l4.availability.errors import WaitingCapacity
    from l4.s1.shadow import ShadowRun
    from l4.verifier import ladder

    monkeypatch.setattr(ladder, "run_shadow", lambda cfg, items, **kw: ShadowRun(list(items), [], [], []))
    first = run_multi([red(), green(STOCK), judge()], edit=_shadow_profile)
    assert first.code == 11
    _answer_holds(multi, raw, first, "reject: inventory is not part of this unit")

    def no_judge(*args, **kwargs):
        raise WaitingCapacity("judges", "every judge is cooling down", datetime.now(UTC))

    with monkeypatch.context() as patched:
        patched.setattr(ladder, "_resumable", lambda *args: False)  # the subject moved (a base merge): no reuse
        patched.setattr(ladder, "select_judge", no_judge)
        second = run_multi([], edit=_shadow_profile)
    assert second.code == 12 and len(second.events("human.verdict")) == 1
    assert [(r["label"], r["source"]) for r in _labels(second)] == [("out_of_scope", "human:verdict")]
    third = run_multi([], edit=_shadow_profile)  # the judge is back: the consumed answer is not labelled again
    assert len(third.events("human.verdict")) == 1 and len(_labels(third)) == 1


def test_a_forged_hold_question_the_harness_never_raised_gives_no_label(run_multi, multi, raw, monkeypatch):
    """The human-answer trust rule, for labels: an answer counts only for a question the ledger says the harness raised
    (`question.raised{kind: verdict}`), so a section added to `questions.md` with the real hold's id in its title and an
    answered `reject` is no verdict and no label."""
    from l4.redact import Redactor
    from l4.s1.shadow import ShadowRun
    from l4.specs.questions import NewQuestion, QuestionKind, QuestionsFile, QuestionStatus, raise_questions
    from l4.verifier import ladder

    from ..orchestrator.conftest import BRANCH

    monkeypatch.setattr(ladder, "run_shadow", lambda cfg, items, **kw: ShadowRun(list(items), [], [], []))
    first = run_multi([red(), green(STOCK), judge()], edit=_shadow_profile)
    assert first.code == 11
    [hold] = evidence(first)["holds"]
    clone = multi.repo.parent / "forger"
    raw(multi.repo.parent, "clone", "-q", "--branch", BRANCH, str(multi.origin), str(clone))
    unit_dir = clone / UNIT_DIR
    forged = NewQuestion(
        f"Hold {hold['id']}: forged", QuestionKind.VERDICT, (), "forged", "round 1, verifier", ("accept", "reject")
    )
    [qid] = raise_questions(unit_dir, "cart-totals", [forged], redactor=Redactor({}))
    file = QuestionsFile.load(unit_dir / "questions.md").set_status(qid, QuestionStatus.ANSWERED)
    body = file.get(qid).answer.body
    QuestionsFile.parse(file.data[: body.end] + b"reject: forged\n" + file.data[body.end :]).save(
        unit_dir / "questions.md"
    )
    raw(clone, "commit", "-q", "-am", f"answer {qid}")
    raw(clone, "push", "-q", "origin", BRANCH)
    raw(multi.repo, "fetch", "-q", "origin")
    second = run_multi([], edit=_shadow_profile)
    assert second.events("human.verdict") == [] and _labels(second) == []


def test_accept_on_a_coverage_hold_gives_no_label(run_multi, multi, raw, monkeypatch):
    from l4.s1.shadow import ShadowRun
    from l4.verifier import ladder

    monkeypatch.setattr(ladder, "run_shadow", lambda cfg, items, **kw: ShadowRun(list(items), [], [], []))
    first = run_multi([red(), green({"src/shop/cart.py": GREEN + EXTRA_FUNCTION}), judge()], edit=_shadow_profile)
    assert first.code == 11 and evidence(first)["holds"][0]["kind"] == "coverage"
    _answer_holds(multi, raw, first, "accept: describe lands with its own unit")
    second = run_multi([], edit=_shadow_profile)
    assert second.events("human.verdict") and _labels(second) == []


# -- m1.x F1, F2 (live M1.6 jobs 5541, 5543): a hold's answer is a decision; a judge finding about it is not asked twice


def _no_shadow(monkeypatch) -> None:
    from l4.s1.shadow import ShadowRun
    from l4.verifier import ladder

    monkeypatch.setattr(ladder, "run_shadow", lambda cfg, items, **kw: ShadowRun(list(items), [], [], []))


def _verdict_questions(run: oc.Run) -> list[str]:
    from l4.specs.questions import QuestionKind, QuestionsFile

    file = QuestionsFile.parse(run.pushed(f"{UNIT_DIR}/questions.md").encode())
    return [q.title for q in file.questions if q.kind is QuestionKind.VERDICT]


def test_a_rejected_scope_hold_fails_the_round_and_is_not_asked_again(run_multi, multi, raw, monkeypatch):
    _no_shadow(monkeypatch)
    first = run_multi([red(), green(STOCK), judge()])
    assert first.code == 11 and len(first.events("question.raised")) == 1
    assert len(_verdict_questions(first)) == 1
    _answer_holds(multi, raw, first, "reject: inventory is not part of this unit")
    second = run_multi([])
    assert second.code == 10  # a FAIL with a fix unit written (the verifier suite has no fix hook)
    assert [e["verdict"] for e in second.events("verify.verdict")] == ["NEEDS_HUMAN", "FAIL"]
    [spawned] = second.events("fix.spawned")
    assert spawned["consumed"] == ["Q-001"] and spawned["parent"] == UNIT
    assert len(second.events("question.raised")) == 1  # the one of round 1: the rejected hold is not asked again
    assert len(_verdict_questions(second)) == 1  # questions.md still holds the one question, answered
    tasks = second.pushed(f"{UNIT_DIR}-fix-1/tasks.md")
    proposal = second.pushed(f"{UNIT_DIR}-fix-1/proposal.md")
    assert "src/inventory/stock.py" in tasks and tasks.count("- [ ]") == 1
    assert "Decided by human in Q-001: inventory is not part of this unit. " in proposal  # the decision comes first
    assert "Remove or relocate" in proposal


def _stock_judge() -> Step:
    finding = {
        "severity": "major",
        "title": "Unrelated change to LOW_STOCK_THRESHOLD",
        "detail": "The change edits src/inventory/stock.py, which no part of the proposal mentions.",
        "suggested_fix": "Revert the change to src/inventory/stock.py",
        "evidence": [],
    }
    return Step(structured=judge_reply([CID], findings=[finding]))


def test_a_judge_finding_on_the_file_of_a_hold_is_asked_once_and_one_answer_settles_both(
    run_multi, multi, raw, monkeypatch
):
    _no_shadow(monkeypatch)
    first = run_multi([red(), green(STOCK), _stock_judge()])
    assert first.code == 11
    asked = _verdict_questions(first)
    assert len(asked) == 1 and asked[0].startswith("Hold H-")  # two questions before: the hold and the finding
    text = first.pushed(f"{UNIT_DIR}/questions.md")
    assert "Unrelated change to LOW_STOCK_THRESHOLD" in text and "One answer settles both" in text
    _answer_holds(multi, raw, first, "accept: the threshold change is intended")
    second = run_multi([])
    assert second.code == 0 and second.outcome["units"][0]["verdict"] == "PASS"
    assert len(second.events("question.raised")) == 1


def test_a_rejected_hold_with_a_judge_finding_is_one_fix_task_that_quotes_the_finding(
    run_multi, multi, raw, monkeypatch
):
    _no_shadow(monkeypatch)
    first = run_multi([red(), green(STOCK), _stock_judge()])
    assert first.code == 11 and len(_verdict_questions(first)) == 1
    _answer_holds(multi, raw, first, "reject: inventory is not part of this unit")
    second = run_multi([])
    assert second.code == 10 and len(second.events("question.raised")) == 1
    [spawned] = second.events("fix.spawned")
    assert spawned["consumed"] == ["Q-001"] and len(spawned["findings"]) == 1  # one task, not two
    tasks = second.pushed(f"{UNIT_DIR}-fix-1/tasks.md")
    proposal = second.pushed(f"{UNIT_DIR}-fix-1/proposal.md")
    assert tasks.count("- [ ]") == 1 and "Decided by human in Q-001" in proposal


def test_a_reject_with_no_reason_is_the_unusable_answer_and_never_loops(run_multi, multi, raw, monkeypatch):
    """No actionable text: the human's finding is a FAIL, the planner lists it as not converted and the round
    escalates (exit 13, no fix unit); the next run asks nothing and spawns nothing."""
    _no_shadow(monkeypatch)
    first = run_multi([red(), green(STOCK), judge()])
    assert first.code == 11
    _answer_holds(multi, raw, first, "reject")
    second = run_multi([])
    assert [e["verdict"] for e in second.events("verify.verdict")] == ["NEEDS_HUMAN", "FAIL"]
    assert second.events("fix.spawned") == [] and len(second.events("question.raised")) == 1
    assert second.code == 13 and second.triggers()[-1] == "verify_fail_exhausted"
    third = run_multi([])
    assert len(third.events("question.raised")) == 1 and third.events("fix.spawned") == []
    assert third.code == second.code


def _human_commit(multi: TddRepo, raw, path: str, line: str) -> None:
    """A human pushes a change to the unit branch: the next round has a new subject and is judged afresh."""
    clone = multi.repo.parent / "human-change"
    raw(multi.repo.parent, "clone", "-q", "--branch", oc.BRANCH, str(multi.origin), str(clone))
    target = clone / path
    target.write_text(target.read_text() + line)
    raw(clone, "add", "-A")
    raw(clone, "commit", "-q", "-m", "human change")
    raw(clone, "push", "-q", "origin", oc.BRANCH)
    raw(multi.repo, "fetch", "-q", "origin")


def test_an_accepted_hold_does_not_settle_a_judge_finding_it_never_showed(run_multi, multi, raw, monkeypatch):
    """Review of F2: the accept of a hold stays in force while its text is stable. A finding about the hold's file that
    a later, freshly judged round raises was never in the hold's question: it is asked on its own, not waived."""
    _no_shadow(monkeypatch)
    first = run_multi([red(), green(STOCK), judge()])
    assert first.code == 11 and len(_verdict_questions(first)) == 1  # the hold alone: the judge found nothing
    _answer_holds(multi, raw, first, "accept: the stock change is intended")
    _human_commit(multi, raw, "src/inventory/stock.py", "# reviewed\n")
    second = run_multi([_stock_judge()])
    assert [e["verdict"] for e in second.events("verify.verdict")] == ["NEEDS_HUMAN", "NEEDS_HUMAN"]
    assert second.code == 11
    asked = _verdict_questions(second)
    assert len(asked) == 2 and asked[1].startswith("Finding F-") and "LOW_STOCK_THRESHOLD" in asked[1]


def test_a_rejected_hold_with_no_fix_rounds_left_escalates_and_spawns_nothing(run_multi, multi, raw, monkeypatch):
    """Review of F1: a rejected hold's FAIL takes the general fix-unit path, so `verifier.max_fix_rounds` bounds it."""
    _no_shadow(monkeypatch)

    def no_rounds(body: dict) -> None:
        body["verifier"]["max_fix_rounds"] = 0

    first = run_multi([red(), green(STOCK), judge()], edit=no_rounds)
    assert first.code == 11
    _answer_holds(multi, raw, first, "reject: inventory is not part of this unit")
    second = run_multi([], edit=no_rounds)
    assert [e["verdict"] for e in second.events("verify.verdict")] == ["NEEDS_HUMAN", "FAIL"]
    assert second.code == 13 and second.triggers()[-1] == "verify_fail_exhausted"
    assert second.events("fix.spawned") == [] and len(second.events("question.raised")) == 1
    assert "fix rounds used 0/0" in report(second)


# -- M1.11 W6 (live PR-2, MF-1): tests that people or a test chore wrote count when they discriminate ----------------


def _human_adds(multi: TddRepo, raw, path: str, text: str) -> None:
    """A person pushes a new test file to the unit branch: its only commit is theirs."""
    clone = multi.repo.parent / "owner-change"
    if not clone.exists():
        raw(multi.repo.parent, "clone", "-q", "--branch", oc.BRANCH, str(multi.origin), str(clone))
    else:
        raw(clone, "pull", "-q", "origin", oc.BRANCH)
    (clone / path).parent.mkdir(parents=True, exist_ok=True)
    (clone / path).write_text(text)
    raw(clone, "add", "-A")
    raw(clone, "commit", "-q", "-m", f"owner: {path}")
    raw(clone, "push", "-q", "origin", oc.BRANCH)
    raw(multi.repo, "fetch", "-q", "origin")


OWNER_HEADER = "import pytest\n\nfrom shop.pricing import unit_price\n\n\n"


def owner_test(name: str, body: str, header: str = OWNER_HEADER) -> str:
    return f'{header}@pytest.mark.l4("{CID}")\ndef test_{name}():\n    {body}\n'


def _first_round_with_a_pricing_change(run_multi, multi, raw, monkeypatch):
    """Round 1: the unit changes `shop.pricing` (a bulk price) and leaves one function untested, so a hold waits."""
    _no_shadow(monkeypatch)
    pricing = (multi.repo / "src/shop/pricing.py").read_text()
    changed = pricing.replace(
        "    return base_cents * qty",
        "    if qty >= 10:\n        return base_cents * qty * 9 // 10\n    return base_cents * qty",
    )
    assert changed != pricing
    first = run_multi(
        [red(), green({"src/shop/cart.py": GREEN + EXTRA_FUNCTION, "src/shop/pricing.py": changed}), judge()]
    )
    assert first.code == 11 and evidence(first)["holds"][0]["kind"] == "coverage"
    _answer_holds(multi, raw, first, "accept: describe lands with its own unit")
    return first


def _accept(multi: TddRepo, raw, qid: str) -> None:
    """What a person does with a verdict question: answer `accept` on the unit branch (one clone per question)."""
    from l4.specs.questions import QuestionsFile, QuestionStatus

    clone = multi.repo.parent / f"human-{qid}"
    raw(multi.repo.parent, "clone", "-q", "--branch", oc.BRANCH, str(multi.origin), str(clone))
    path = clone / UNIT_DIR / "questions.md"
    file = QuestionsFile.load(path)
    assert file is not None
    file = file.set_status(qid, QuestionStatus("answered"))
    body = file.get(qid).answer.body  # type: ignore[union-attr]
    file = QuestionsFile.parse(file.data[: body.end] + b"accept: intended\n" + file.data[body.end :])
    file.save(path)
    raw(clone, "add", "-A")
    raw(clone, "commit", "-q", "-m", f"answer {qid}")
    raw(clone, "push", "-q", "origin", oc.BRANCH)


def _gates(run, name: str) -> list[dict]:
    return [e for e in run.events("gate.finished") if e["name"] == name]


def _traced(run, round_no: int) -> dict[str, list[list[str]]]:
    return {row["criterion"]: [[t["id"], t["proof"]] for t in row["tests"]] for row in evidence_rows(run, round_no)}


def evidence_rows(run, round_no: int) -> list[dict]:
    return json.loads(run.pushed(f"{UNIT_DIR}/.l4/evidence/round-{round_no}/verdict.json"))["trace"]


def test_an_owner_regression_test_that_fails_on_the_base_is_evidence(run_multi, multi, raw, monkeypatch):
    _first_round_with_a_pricing_change(run_multi, multi, raw, monkeypatch)
    # passes on the zero values (`!= 1000` is true of 0) and fails on the base's pricing, where the answer is 1000
    _human_adds(multi, raw, "tests/test_owner.py", owner_test("bulk_is_cheaper", "assert unit_price(100, 10) != 1000"))
    second = run_multi([judge()])
    [proof] = second.events("verify.extra_proof")
    assert (proof["criterion"], proof["source"], proof["via"]) == (CID, "human", "base")
    assert proof["tests"] == ["tests.test_owner::test_bulk_is_cheaper"] and list(proof["files"]) == [
        "tests/test_owner.py"
    ]
    assert len(proof["files"]["tests/test_owner.py"]) == 10
    assert ["tests.test_owner::test_bulk_is_cheaper", "human"] in _traced(second, 2)[CID]
    assert "a test is ignored as evidence" not in report(second)
    assert len(_gates(second, "test-extra-zero")) == 1 and len(_gates(second, "test-extra-base")) == 1


def test_an_owner_test_that_fails_on_zero_values_is_evidence(run_multi, multi, raw, monkeypatch):
    _first_round_with_a_pricing_change(run_multi, multi, raw, monkeypatch)
    _human_adds(multi, raw, "tests/test_owner.py", owner_test("bulk_price", "assert unit_price(100, 10) == 900"))
    second = run_multi([judge()])
    [proof] = second.events("verify.extra_proof")
    assert (proof["source"], proof["via"]) == ("human", "zero_value")
    assert _gates(second, "test-extra-base") == []  # decided by the first run: one gate run
    assert ["tests.test_owner::test_bulk_price", "human"] in _traced(second, 2)[CID]


def test_an_owner_test_that_passes_both_stays_ignored_with_the_reason(run_multi, multi, raw, monkeypatch):
    _first_round_with_a_pricing_change(run_multi, multi, raw, monkeypatch)
    _human_adds(multi, raw, "tests/test_owner.py", owner_test("is_something", "assert unit_price(100, 1) is not None"))
    second = run_multi([judge()])
    assert second.events("verify.extra_proof") == []
    assert "passes against the zero values and on the base" in report(second)
    assert "tests.test_owner::test_is_something" not in [t for t, _ in _traced(second, 2)[CID]]


def test_a_test_whose_module_does_not_exist_at_the_base_is_no_proof(run_multi, multi, raw, monkeypatch):
    _first_round_with_a_pricing_change(run_multi, multi, raw, monkeypatch)
    header = (
        "import pytest\n\nfrom shop.cart import cart_total\n\n\n"  # `shop.cart` is the unit's own: absent at the base
    )
    text = owner_test("cart_is_not_that", "assert cart_total([(100, 1)], None, 0) != 12345", header)
    _human_adds(multi, raw, "tests/test_owner.py", text)
    second = run_multi([judge()])
    assert second.events("verify.extra_proof") == []  # it cannot import at the base: a collection error is no proof
    assert "passes against the zero values and on the base" in report(second)


def test_a_test_that_only_reaches_the_units_new_code_is_no_proof(run_multi, multi, raw, monkeypatch):
    """m1.11(fix): on the base the unit's new module is gone, so a test that merely imports it inside its body fails
    there with ModuleNotFoundError, whatever it asserts. Like the zero-value run, the base run takes a failure by
    assertion only: an error shows that the test touched the new code, not that it checked the answer."""
    _first_round_with_a_pricing_change(run_multi, multi, raw, monkeypatch)
    body = "from shop.cart import cart_total; assert cart_total is not None"  # true of the zero value's function too
    _human_adds(multi, raw, "tests/test_owner.py", owner_test("cart_exists", body, "import pytest\n\n\n"))
    second = run_multi([judge()])
    assert len(_gates(second, "test-extra-base")) == 1  # it reached the base run, and failed there with an error
    assert second.events("verify.extra_proof") == []
    assert "tests.test_owner::test_cart_exists" not in [t for t, _ in _traced(second, 2)[CID]]
    assert "fails on the base only with an error, not by assertion" in report(second)


def test_an_accepted_proof_is_not_rerun_and_a_rejection_is_rerun_at_a_new_head(run_multi, multi, raw, monkeypatch):
    _first_round_with_a_pricing_change(run_multi, multi, raw, monkeypatch)
    _human_adds(multi, raw, "tests/test_owner.py", owner_test("bulk_price", "assert unit_price(100, 10) == 900"))
    _human_adds(multi, raw, "tests/test_owner2.py", owner_test("is_something", "assert unit_price(100, 1) is not None"))
    finding = {"severity": "major", "title": "An empty cart", "detail": "Nothing says what an empty cart costs.",
               "suggested_fix": "", "evidence": []}  # fmt: skip
    second = run_multi([Step(structured=judge_reply([CID], findings=[finding]))])  # a question: a third round follows
    assert second.code == 11 and len(second.events("verify.extra_proof")) == 1
    assert len(_gates(second, "test-extra-zero")) == 1
    for qid in ("Q-002", "Q-003"):  # the judge's finding, and the hold that round 2's smaller text made a new one
        _accept(multi, raw, qid)
    _human_commit(multi, raw, "tests/test_owner2.py", "# reviewed\n")  # a new head; test_owner.py is as it was
    third = run_multi([judge()])
    assert len(third.events("verify.extra_proof")) == 1  # the accepted one is not decided again
    assert ["tests.test_owner::test_bulk_price", "human"] in _traced(third, 3)[CID]
    # the rejected one is run again at the new head: a second zero-value run, for it alone
    assert len(_gates(third, "test-extra-zero")) == 2
