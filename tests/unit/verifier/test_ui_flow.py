"""Plan lines 33-36 end to end: `l4 run` on a unit that changes the fixture web app. Step 3 runs the e2e gate, step 4
finds both criteria untraced in the e2e report, step 5 has the verifier agent write a Playwright-shaped test for each
that fails at the merge base and passes at head, the tests are committed once, the unit passes, and the round's
deterministic finding becomes a lesson in its own `chore(memory)` commit before the hand-off."""

import dataclasses

import pytest
import yaml

from l4.agents.fake import Step

from .._web_helpers import WEB, e2e_config, free_port, stage
from ..conftest import TEST_COMMAND, TddRepo
from ..implementer.conftest import IMPL, KNOWN, UNKNOWN, green_step, red_step
from ..orchestrator.conftest import BRANCH, UNIT_DIR
from .conftest import judge_reply

HEAD_APP = (
    (WEB / "app.py")
    .read_text()
    .replace('<p data-testid="subtotal">', '<p data-testid="coupon">SAVE10</p>\n<p data-testid="subtotal">')
)  # the smoke test (3 items) still passes at head
READ = (
    "import os\nimport urllib.request\n\nimport pytest\n\n\ndef page():\n"
    "    return urllib.request.urlopen(os.environ['L4_E2E_BASE_URL'] + '/').read().decode()\n"
)
JUDGE = Step(structured=judge_reply([KNOWN, UNKNOWN]))


def ui_test(cid: str, needle: str, name: str) -> Step:
    code = READ + f'\n\n@pytest.mark.l4("{cid}")\ndef test_{name}():\n    assert {needle!r} in page()\n'
    return Step(structured={"criterion": cid, "code": code})


def no_test(cid: str) -> Step:
    """A reply that is a file with no test: the fixture has no lint gate, so it ends `uncollectable` at once."""
    return Step(structured={"criterion": cid, "code": "import pytest\n"})


def web_green() -> Step:
    return Step(writes={"src/pytdd/pricing.py": IMPL, "app.py": HEAD_APP}, structured=green_step().structured)


@pytest.fixture
def web_repo(tdd_repo: TddRepo, raw, monkeypatch):
    """The cart app on `main` (it shows 3 items), and a config with the e2e gate, Playwright on `app.py`, a verifier
    agent of a third vendor and no audit sample."""
    stage(tdd_repo.repo)
    ignore = tdd_repo.repo / ".gitignore"
    ignore.write_text(ignore.read_text() + "test-results/\n")
    raw(tdd_repo.repo, "add", "-A")
    raw(tdd_repo.repo, "commit", "-q", "-m", "the cart app")
    raw(tdd_repo.repo, "push", "-q", "origin", "main")
    raw(tdd_repo.repo, "fetch", "-q", "origin")
    original = TddRepo.config

    def config(self, **kw):
        body = yaml.safe_load(original(self, **kw))
        body["verifier"] = {"audit_sample_ratio": 0, "playwright": {"ui_paths": ["app.py"]}}
        return yaml.safe_dump(body)

    monkeypatch.setattr(TddRepo, "config", config)
    return {
        "e2e": e2e_config(free_port()),
        "test": {"command": TEST_COMMAND + " tests"},
        "profiles": {"writer": {"adapter": "fake", "vendor": "thirdco"}},
        "roles": {"verifier_agent": ["writer"]},
    }


def test_a_ui_unit_gets_generated_tests_and_one_test_commit_before_the_evidence_commit(run_l4, valid_spec, web_repo):
    script = [
        red_step(), web_green(), ui_test(KNOWN, 'data-testid="coupon"', "slot"), ui_test(UNKNOWN, "SAVE10", "code"),
        JUDGE,
    ]  # fmt: skip
    run = run_l4(script, **web_repo)
    assert run.code == 0, run.outcome
    steps = {e["step"]: e["status"] for e in run.events("verify.step")}
    assert steps["3"] == "ok" and steps["4"] == "ok" and steps["5"] == "ok" and "8" not in steps  # no s1_judge role
    made = run.events("verify.generated")
    assert [(e["criterion"], e["status"], e["base"], e["head"]) for e in made] == [
        (KNOWN, "accepted", "fail", "pass"), (UNKNOWN, "accepted", "fail", "pass"),
    ]  # fmt: skip
    subjects = run.subjects()
    tests = subjects.index("test(add-discount-codes): verifier round 1 [skip ci]")
    assert tests < subjects.index("docs(add-discount-codes): verification round 1 [skip ci]")
    assert subjects.count(subjects[tests]) == 1
    listing = run.raw(run.tdd.origin, "ls-tree", "--name-only", BRANCH, "e2e/").split()
    assert all(f"e2e/test_l4_c_{c.removeprefix('C-')}.py" in listing for c in (KNOWN, UNKNOWN))
    text = run.pushed(f"{UNIT_DIR}/verification.md")
    assert "## Generated UI tests" in text and "generated, base fail, head pass" in text


def steps_of(run) -> dict[str, str]:
    return {e["step"]: e["status"] for e in run.events("verify.step")}


def test_a_covered_criterion_the_writer_calls_not_testable_is_a_note_and_the_unit_passes(
    run_l4, valid_spec, web_repo
):  # SCN-VER-298
    refuse = Step(structured={"criterion": UNKNOWN, "not_testable": "it is about a refused code"})
    run = run_l4([red_step(), web_green(), ui_test(KNOWN, 'data-testid="coupon"', "slot"), refuse, JUDGE], **web_repo)
    assert run.code == 0, run.outcome
    made = {e["criterion"]: e for e in run.events("verify.generated")}
    assert {c: e["status"] for c, e in made.items()} == {KNOWN: "accepted", UNKNOWN: "not_testable"}
    assert made[UNKNOWN]["covered_by"] == ["tests.test_discount::test_unknown_code"] and "covered_by" not in made[KNOWN]
    text = run.pushed(f"{UNIT_DIR}/verification.md")
    row = next(line for line in text.splitlines() if line.startswith(f"| {UNKNOWN} | not_testable |"))
    assert "covered by step 4: tests.test_discount::test_unknown_code; a note, not a hold (L4-VER-067)" in row
    assert f"UI criterion {UNKNOWN} has no end-to-end test; see" not in text and "## Needs a human" not in text
    step5 = next(line for line in text.splitlines() if line.startswith("| 5 | ui test generation |"))
    assert "1 not_testable covered by step 4: notes, no hold (L4-VER-067)" in step5
    assert "e2e support files shown" not in step5
    assert "verifier round 1 [skip ci]" in " ".join(run.subjects())  # the accepted test is committed all the same


def test_step_5_says_how_many_e2e_support_files_the_writer_was_shown(
    run_l4, valid_spec, web_repo, tdd_repo, raw
):  # SCN-VER-304
    (tdd_repo.repo / "e2e").mkdir(exist_ok=True)
    (tdd_repo.repo / "e2e" / "conftest.py").write_text("def login(page):\n    page.goto('/')\n")
    raw(tdd_repo.repo, "add", "e2e/conftest.py")
    raw(tdd_repo.repo, "commit", "-q", "-m", "the suite's conftest")
    raw(tdd_repo.repo, "push", "-q", "origin", "main")
    raw(tdd_repo.repo, "fetch", "-q", "origin")
    script = [
        red_step(), web_green(), ui_test(KNOWN, 'data-testid="coupon"', "slot"), ui_test(UNKNOWN, "SAVE10", "code"),
        JUDGE,
    ]  # fmt: skip
    run = run_l4(script, **web_repo)
    assert run.code == 0, run.outcome
    text = run.pushed(f"{UNIT_DIR}/verification.md")
    step5 = next(line for line in text.splitlines() if line.startswith("| 5 | ui test generation |"))
    assert "e2e support files shown to the writer: 1" in step5 and "not shown" not in step5


def test_a_covered_criterion_whose_generation_failed_in_another_way_keeps_its_hold(
    run_l4, valid_spec, web_repo
):  # SCN-VER-300
    run = run_l4(
        [red_step(), web_green(), ui_test(KNOWN, 'data-testid="coupon"', "slot"), no_test(UNKNOWN), JUDGE], **web_repo
    )
    assert run.code == 11
    made = {e["criterion"]: e for e in run.events("verify.generated")}
    assert made[UNKNOWN]["status"] == "uncollectable" and "covered_by" not in made[UNKNOWN]
    text = run.pushed(f"{UNIT_DIR}/verification.md")
    assert f"UI criterion {UNKNOWN} has no end-to-end test; see" in text and "## Needs a human" in text


def test_a_reused_round_keeps_the_note_and_raises_no_hold(run_l4, valid_spec, web_repo, tdd_repo, raw):  # SCN-VER-301
    import json

    from ..orchestrator.conftest import edit_questions_on_origin

    noted = Step(structured={"criterion": UNKNOWN, "not_testable": "it is about a refused code"})
    first = run_l4([red_step(), web_green(), no_test(KNOWN), noted, JUDGE], **web_repo)
    assert first.code == 11
    assert len(first.events("question.raised")) == 1  # KNOWN's UI hold; UNKNOWN is a note
    edit_questions_on_origin(tdd_repo, raw, status="answered", answer="accept: a unit test covers it")
    second = run_l4([], **web_repo)  # no step at all: no writer is called
    assert second.code == 0, second.outcome
    assert second.adapter.requests == [] and len(second.events("question.raised")) == 1
    reused = {e["step"]: e["status"] for e in second.events("verify.step") if e["round"] == 2}
    assert reused["5"] == "reused" and reused["4"] == "reused"
    text = second.pushed(f"{UNIT_DIR}/verification.md")
    assert "reused (round 1)" in text and "covered by step 4: tests.test_discount::test_unknown_code" in text
    assert f"UI criterion {UNKNOWN} has no end-to-end test" not in text
    body = json.loads(second.pushed(f"{UNIT_DIR}/.l4/evidence/round-2/verdict.json"))
    generated = {g["criterion"]: g for g in body["generated"]}
    assert generated[UNKNOWN]["covered_by"] == ["tests.test_discount::test_unknown_code"]
    assert not any(UNKNOWN in hold for hold in body["holds"])


def test_a_note_does_not_pass_the_criterion_the_judge_calls_inadequate(run_l4, valid_spec, web_repo):  # SCN-VER-303
    refuse = Step(structured={"criterion": UNKNOWN, "not_testable": "it is about a refused code"})
    inadequate = Step(
        structured=judge_reply(
            [KNOWN, UNKNOWN],
            test_adequacy=[
                {
                    "test": "tests.test_discount::test_unknown_code",
                    "criterion": UNKNOWN,
                    "adequate": False,
                    "reason": "it does not open the page",
                }
            ],
        )
    )
    run = run_l4(
        [red_step(), web_green(), ui_test(KNOWN, 'data-testid="coupon"', "slot"), refuse, inadequate], **web_repo
    )
    assert run.code == 11, run.outcome
    text = run.pushed(f"{UNIT_DIR}/verification.md")
    row = next(line for line in text.splitlines() if line.startswith(f"| {UNKNOWN} |") and "needs_human" in line)
    assert "uncovered: the tests that trace it are inadequate or did not pass" in row
    asked = run.events("question.raised")
    assert len(asked) == 1 and asked[0]["kind"] == "verdict" and asked[0].get("criterion", UNKNOWN) == UNKNOWN
    assert f"UI criterion {UNKNOWN} has no end-to-end test" not in text


@pytest.mark.parametrize(
    "other",
    [("pass_to_pass", ""), ("zero_value", "not applicable: no project code")],
    ids=["pass-to-pass", "unproved-red-record"],
)
def test_a_note_whose_covering_test_the_judge_rejects_comes_back_as_a_ui_hold(
    run_l4, valid_spec, web_repo, monkeypatch, other
):  # SCN-VER-307
    import json

    from l4.verifier import ladder
    from l4.verifier.types import TracingTest

    real = ladder.trace_criteria

    def with_second_test(*args, **kwargs):  # UNKNOWN's second tracing test: a base test, or a red record no run proved
        proof, note = other
        extra = TracingTest("tests.test_base::test_old", "passed", proof, note=note)
        return [
            dataclasses.replace(e, tests=(*e.tests, extra)) if e.criterion == UNKNOWN else e
            for e in real(*args, **kwargs)
        ]

    monkeypatch.setattr(ladder, "trace_criteria", with_second_test)
    refuse = Step(structured={"criterion": UNKNOWN, "not_testable": "it is about a refused code"})
    inadequate = Step(
        structured=judge_reply(
            [KNOWN, UNKNOWN],
            test_adequacy=[
                {
                    "test": "tests.test_discount::test_unknown_code",
                    "criterion": UNKNOWN,
                    "adequate": False,
                    "reason": "it does not open the page",
                }
            ],
        )
    )
    run = run_l4(
        [red_step(), web_green(), ui_test(KNOWN, 'data-testid="coupon"', "slot"), refuse, inadequate], **web_repo
    )
    assert run.code == 11, run.outcome  # the criterion does not pass on the other test alone
    made = {e["criterion"]: e for e in run.events("verify.generated")}
    assert made[UNKNOWN]["covered_by"] == ["tests.test_discount::test_unknown_code"]  # the note was taken in step 5
    text = run.pushed(f"{UNIT_DIR}/verification.md")
    assert f"UI criterion {UNKNOWN} has no end-to-end test; see" in text and "## Needs a human" in text
    body = json.loads(run.pushed(f"{UNIT_DIR}/.l4/evidence/round-1/verdict.json"))
    assert [h for h in body["holds"] if UNKNOWN in h] == [
        f"UI criterion {UNKNOWN} has no end-to-end test; see the generated UI tests table"
    ]
    asked = run.events("question.raised")
    assert len(asked) == 1 and asked[0]["criterion"] == UNKNOWN and "UI criterion" in asked[0]["title"]


def test_an_e2e_test_that_fails_at_head_fails_step_3_and_no_judge_is_called(run_l4, valid_spec, web_repo):
    broken = Step(writes={"src/pytdd/pricing.py": IMPL, "app.py": HEAD_APP.replace("3 items", "9 items")},
                  structured=green_step().structured)  # fmt: skip
    run = run_l4([red_step(), broken], **web_repo)
    assert run.code == 10 and len(run.adapter.requests) == 2
    assert steps_of(run) == {"0": "ok", "1": "ok", "2": "ok", "3": "failed", "10": "ok"}
    text = run.pushed(f"{UNIT_DIR}/verification.md")
    assert "[blocker, deterministic] e2e gate failed" in text and "| e2e | fail |" in text
    assert run.events("verify.generated") == []


def s1_config(web_repo):
    config = {**web_repo, "profiles": {**web_repo["profiles"], "s1": {
        "backend": "system-one", "engine": "remote", "base_url": "http://s1.test"}}}  # fmt: skip
    config["roles"] = {**web_repo["roles"], "s1_judge": ["s1"]}
    return config


def mock_s1(monkeypatch, status: int = 200):
    import httpx

    from l4.llm.system_one import SystemOneBackend
    from l4.redact import Redactor
    from l4.verifier import ladder

    def handler(request: httpx.Request) -> httpx.Response:
        if status != 200:
            return httpx.Response(status)
        body = {"model": "laya-served", "answers": {"p": {"type": "noul", "noul": 0.81}}}
        return httpx.Response(200, json=body)

    def open_(*args, **kwargs):
        return SystemOneBackend(
            "remote", model="typed-decisions", base_url="http://s1.test", transport=httpx.MockTransport(handler),
            redactor=Redactor({}),
        )  # fmt: skip

    monkeypatch.setattr(ladder, "open_s1_backend", open_)


def test_step_8_records_p_and_calibration_rows_and_changes_no_verdict(
    run_l4, valid_spec, web_repo, tdd_repo, monkeypatch
):
    import json

    mock_s1(monkeypatch)
    script = [
        red_step(), web_green(), ui_test(KNOWN, 'data-testid="coupon"', "slot"), ui_test(UNKNOWN, "SAVE10", "code"),
        JUDGE,
    ]  # fmt: skip
    run = run_l4(script, **s1_config(web_repo))
    assert run.code == 0 and steps_of(run)["8"] == "ok"
    asked = run.events("verify.s1")
    assert sorted(e["criterion"] for e in asked) == sorted([KNOWN, UNKNOWN]) and {e["p"] for e in asked} == {0.81}
    assert {(e["model"], e["checkpoint"]) for e in asked} == {("laya-served", "typed-decisions")}
    rows = [json.loads(line) for line in (tdd_repo.cache / "s1-calibration.jsonl").read_text().splitlines()]
    assert {r["criterion"] for r in rows} == {KNOWN, UNKNOWN}
    assert {(r["engine"], r["served_model"], r["deterministic"], r["judge"]) for r in rows} == {
        ("remote", "laya-served", "covered", "pass")
    }
    [copy] = (tdd_repo.repo / ".l4-out" / "s1").glob("*.jsonl")
    assert len(copy.read_text().splitlines()) == 2
    text = run.pushed(f"{UNIT_DIR}/verification.md")
    assert "## S1 (recorded for calibration, never decides)" in text and "0.81" in text


def test_calibration_rows_are_flushed_even_when_the_judge_step_raises(
    run_l4, valid_spec, web_repo, tdd_repo, monkeypatch
):
    import json

    from l4.verifier import ladder

    mock_s1(monkeypatch)

    def boom(*args, **kwargs):
        raise RuntimeError("judge step crashed")

    monkeypatch.setattr(ladder, "_judge_step", boom)
    script = [
        red_step(),
        web_green(),
        ui_test(KNOWN, 'data-testid="coupon"', "slot"),
        ui_test(UNKNOWN, "SAVE10", "code"),
    ]
    run = run_l4(script, **s1_config(web_repo))
    assert run.code != 0
    rows = [json.loads(line) for line in (tdd_repo.cache / "s1-calibration.jsonl").read_text().splitlines()]
    assert {r["criterion"] for r in rows} == {KNOWN, UNKNOWN} and {r["judge"] for r in rows} == {None}
    assert {r["model"] for r in rows} == {"typed-decisions"}


def test_a_down_s1_server_makes_step_8_unavailable_and_the_unit_still_passes(
    run_l4, valid_spec, web_repo, tdd_repo, monkeypatch
):
    mock_s1(monkeypatch, status=500)
    script = [
        red_step(), web_green(), ui_test(KNOWN, 'data-testid="coupon"', "slot"), ui_test(UNKNOWN, "SAVE10", "code"),
        JUDGE,
    ]  # fmt: skip
    run = run_l4(script, **s1_config(web_repo))
    assert run.code == 0 and steps_of(run)["8"] == "unavailable"
    assert not (tdd_repo.cache / "s1-calibration.jsonl").exists()
    assert "| 8 | s1 judge | unavailable |" in run.pushed(f"{UNIT_DIR}/verification.md")


def test_a_generated_test_and_an_accepted_hold_of_an_earlier_round_are_not_run_or_asked_again(
    run_l4, valid_spec, web_repo, tdd_repo, raw
):
    from ..orchestrator.conftest import edit_questions_on_origin

    first = run_l4(
        [red_step(), web_green(), ui_test(KNOWN, 'data-testid="coupon"', "slot"), no_test(UNKNOWN), JUDGE], **web_repo
    )
    assert first.code == 11
    asked = first.events("question.raised")
    edit_questions_on_origin(tdd_repo, raw, status="answered", answer="accept: a unit test covers it")
    clone = tdd_repo.repo.parent / "human-answered"  # the human also touches the app, so the round cannot be reused
    (clone / "app.py").write_text((clone / "app.py").read_text() + "\n# touched\n")
    raw(clone, "commit", "-q", "-am", "touch the app")
    raw(clone, "push", "-q", "origin", BRANCH)
    second = run_l4([JUDGE], **web_repo)  # no writer call: UNKNOWN is waived by the accepted hold (L4-VER-067)
    assert second.code == 0, second.outcome
    made = [(e["criterion"], e["status"]) for e in second.events("verify.generated")]
    assert made == [(KNOWN, "accepted"), (UNKNOWN, "uncollectable"), (UNKNOWN, "waived")]  # KNOWN not asked again
    [waived] = [e for e in second.events("verify.generated") if e["status"] == "waived"]
    assert waived["by"] == "Q-001" and waived["attempts"] == 0 and not waived.get("test")
    assert len(second.adapter.requests) == 1 and second.events("question.raised") == asked
    text = second.pushed(f"{UNIT_DIR}/verification.md")
    row = next(line for line in text.splitlines() if line.startswith(f"| {KNOWN} |") and "generated" in line)
    assert "(passed, generated)" in row  # recognised from the ledger: same file, same digest
    assert f"| {UNKNOWN} | waived |" in text and "waived by Q-001" in text and "## Needs a human" not in text
    assert steps_of(second)["5"] == "ok"


def test_an_implementer_written_e2e_test_that_was_never_proved_does_not_close_the_gap(run_l4, valid_spec, web_repo):
    """Live M1.5 P3 (job 5528): Codex wrote the browser test for the criterion itself. The red gate runs `gates.test`
    only, so nothing proved that it fails without the change; it was `ignored as evidence`, and yet step 5 generated
    nothing for the criterion because the e2e report traced it (m1.x fix F6)."""
    own = READ + f'\n\n@pytest.mark.l4("{KNOWN}")\ndef test_slot():\n    assert \'data-testid="coupon"\' in page()\n'
    red = red_step()
    red.writes = {**red.writes, "e2e/test_cart_page.py": own}
    script = [
        red, web_green(), ui_test(KNOWN, 'data-testid="coupon"', "slot"), ui_test(UNKNOWN, "SAVE10", "code"), JUDGE,
    ]  # fmt: skip
    run = run_l4(script, **web_repo)
    assert run.code == 0, run.outcome
    made = {e["criterion"]: (e["status"], e["base"], e["head"]) for e in run.events("verify.generated")}
    assert made == {KNOWN: ("accepted", "fail", "pass"), UNKNOWN: ("accepted", "fail", "pass")}
    text = run.pushed(f"{UNIT_DIR}/verification.md")
    assert "e2e.test_cart_page" in text and "never proved" in text  # the finding says why step 5 still generated one


def test_an_unproved_test_at_the_harness_s_own_path_is_never_overwritten_and_the_criterion_is_a_hold(
    run_l4, valid_spec, web_repo
):
    """The live shape (job 5528): the implementer's browser test had the name the generator would give it,
    `e2e/test_l4_c_<hex>.py`. L4-VER-002a: a test the harness did not write is never overwritten."""
    path = f"e2e/test_l4_c_{KNOWN.removeprefix('C-')}.py"
    own = READ + f'\n\n@pytest.mark.l4("{KNOWN}")\ndef test_slot():\n    assert \'data-testid="coupon"\' in page()\n'
    red = red_step()
    red.writes = {**red.writes, path: own}
    script = [
        red, web_green(), ui_test(KNOWN, 'data-testid="coupon"', "slot"), ui_test(UNKNOWN, "SAVE10", "code"), JUDGE,
    ]  # fmt: skip
    run = run_l4(script, **web_repo)
    assert run.code == 11, run.outcome
    made = {e["criterion"]: e["status"] for e in run.events("verify.generated")}
    assert made == {KNOWN: "writer_failed", UNKNOWN: "accepted"}
    [refused] = [e for e in run.events("verify.generated") if e["criterion"] == KNOWN]
    assert "never overwrites" in refused["reason"] and "never proved discriminating" in refused["reason"]
    text = run.pushed(f"{UNIT_DIR}/verification.md")
    assert f"UI criterion {KNOWN} has no end-to-end test; see" in text and "## Needs a human" in text
    assert run.pushed(path) == own  # the implementer's file is on the branch, byte for byte


def test_the_verdict_of_a_failed_e2e_gate_records_the_failing_test_with_its_gate(run_l4, valid_spec, web_repo):
    """L4-VER-069 end to end: the smoke test fails by assertion in the e2e gate and its record is in verdict.json."""
    import json

    broken = Step(writes={"src/pytdd/pricing.py": IMPL, "app.py": HEAD_APP.replace("3 items", "9 items")},
                  structured=green_step().structured)  # fmt: skip
    run = run_l4([red_step(), broken], **web_repo)
    assert run.code == 10
    verdict = json.loads(run.pushed(f"{UNIT_DIR}/.l4/evidence/round-1/verdict.json"))
    (test_id,) = [i for i, c in verdict["failures"].items() if c["gate"] == "e2e"]
    assert test_id.endswith("test_the_cart_page_shows_the_item_count") and verdict["tests"][test_id] == "failed"
    assert verdict["failures"][test_id]["kind"] == "assertion" and test_id in verdict["e2e_tests"]
    assert (
        verdict["failures"][test_id]["message"].startswith("assert ")
        and "\n" not in verdict["failures"][test_id]["message"]
    )
    # L4-VER-078 through the real ladder: the record also holds the lines the retry prompt would show, bounded
    excerpt = verdict["failures"][test_id]["excerpt"]
    assert "assert" in excerpt and len(excerpt.splitlines()) <= 8 and len(excerpt) <= 600
    assert str(run.tdd.cache) not in excerpt  # paths are relative to the worktree


def test_the_verdict_records_the_excerpt_of_a_module_the_e2e_gate_could_not_collect(run_l4, valid_spec, web_repo):
    """L4-VER-078 through the real ladder (the `collection_excerpt` argument of `failure_records`): a module of the e2e
    gate that fails to import is a `collection` record whose excerpt holds the `E` lines of its error. The module holds
    no test function, so it is no browser test of the task and the green step's own e2e run does not meet it."""
    import json

    red = red_step()
    red.writes = {**red.writes, "e2e/test_unimportable.py": "import no_such_module_for_the_excerpt\n"}
    run = run_l4([red, web_green()], **web_repo)
    verdict = json.loads(run.pushed(f"{UNIT_DIR}/.l4/evidence/round-1/verdict.json"))
    records = {i: r for i, r in verdict["failures"].items() if r["kind"] == "collection" and r["gate"] == "e2e"}
    assert records, verdict["failures"]
    [excerpt] = [r["excerpt"] for r in records.values()]
    assert "no_such_module_for_the_excerpt" in excerpt and len(excerpt.splitlines()) <= 8 and len(excerpt) <= 600


def test_scn_ver_342_a_round_that_asked_a_ui_hold_before_the_upgrade_is_fixed_under_its_criterion(
    run_l4, valid_spec, web_repo, tdd_repo, raw
):
    """The reject of a UI hold, answered after the round was written, settles through `_hold_finding` when the round
    is reused: the verdict is FAIL, the finding keeps the hold's id and now cites the criterion, and the fix unit's
    scenario is under the criterion's requirement, never under `Rejected hold: ... — finding H-...`."""
    import json

    from ..orchestrator.conftest import edit_questions_on_origin

    noted = Step(structured={"criterion": UNKNOWN, "not_testable": "it is about a refused code"})
    first = run_l4([red_step(), web_green(), no_test(KNOWN), noted, JUDGE], **web_repo)
    assert first.code == 11 and len(first.events("question.raised")) == 1
    answer = "reject: the badge is missing. WHEN the cart shows a coupon THEN it names the code SAVE10"
    edit_questions_on_origin(tdd_repo, raw, status="answered", answer=answer)
    second = run_l4([], **web_repo)  # the stored NEEDS_HUMAN round is reused: no writer, no judge
    assert second.code == 10, second.outcome
    assert [e["verdict"] for e in second.events("verify.verdict")] == ["NEEDS_HUMAN", "FAIL"]
    body = json.loads(second.pushed(f"{UNIT_DIR}/.l4/evidence/round-2/verdict.json"))
    [hold] = [f for f in body["findings"] if f["id"].startswith("H-")]
    assert hold["criterion"] == KNOWN and hold["source"] == "deterministic"
    assert hold["title"].startswith("Rejected hold")
    [spawned] = second.events("fix.spawned")
    assert hold["id"] in spawned["findings"] and spawned["consumed"] == ["Q-001"]
    delta = second.pushed(f"{UNIT_DIR}-fix-1/specs/pricing/spec.md")
    assert "### Requirement: Discount codes \N{EM DASH} regression 1" in delta and "#### Scenario: Known code" in delta
    assert "finding H-" not in delta and "Rejected hold" not in delta
    tasks = second.pushed(f"{UNIT_DIR}-fix-1/tasks.md")
    assert len([line for line in tasks.splitlines() if line.startswith("- [ ]")]) == 1 and hold["id"] in tasks


# -- ui-carry-unchanged (L4-VER-086): an unchanged UI criterion with the base's passing tests is carried

BASE_SPEC = (
    "# pricing Specification\n\n## Purpose\nDiscount codes for the pytdd pricing module.\n\n## Requirements\n\n"
    "### Requirement: Discount codes\nThe `apply_discount(amount, code)` function SHALL return `amount` reduced by "
    "the percentage of a known code, rounded to two decimals, and SHALL raise `ValueError` for a code that is not in "
    "the table. The table holds `SAVE10` (10 %).\n\n"
    '#### Scenario: Known code\n- **WHEN** `apply_discount(50.0, "SAVE10")` is called\n'
    "- **THEN** it returns `45.0`\n\n"
    '#### Scenario: Unknown code\n- **WHEN** `apply_discount(50.0, "NOPE")` is called\n'
    "- **THEN** it raises `ValueError`\n"
)  # the unit's two scenarios, word for word: the archived specs at the base hold them
BASE_OF = {KNOWN: "tests.test_base::test_known_old", UNKNOWN: "tests.test_base::test_unknown_old"}
WRITER_PROMPT = "Write the e2e test for criterion"


@pytest.fixture
def carry_repo(web_repo, tdd_repo, raw, monkeypatch):
    """The base holds the archived spec with both scenarios, and the criteria in `carry_of` are traced only by a
    passing base test (the proof `pass_to_pass`) in `tests/test_base.py`, a file the unit does not change."""
    from l4.verifier import ladder
    from l4.verifier.types import TracingTest

    spec = tdd_repo.repo / "openspec/specs/pricing/spec.md"
    spec.parent.mkdir(parents=True)
    spec.write_text(BASE_SPEC)
    raw(tdd_repo.repo, "add", "-A")
    raw(tdd_repo.repo, "commit", "-q", "-m", "the archived pricing spec")
    raw(tdd_repo.repo, "push", "-q", "origin", "main")
    raw(tdd_repo.repo, "fetch", "-q", "origin")
    # `file` holds the base tests (their ids are its dotted module's, unless `ids` names others); `tree` is the work
    # tree the ids are looked up in (FAKE: the unit's own tree is the web fixture's), `walk` what the dotted-module
    # walk of `file_of_test` finds for them (None: `file`; "": no module)
    state = {"carry": (KNOWN,), "file": "tests/test_base.py", "proof": "pass_to_pass", "ids": None, "tree": None,
             "walk": None}  # fmt: skip
    real_trace, real_file = ladder.trace_criteria, ladder.file_of_test

    def ids() -> dict[str, str]:
        module = state["file"].removesuffix(".py").replace("/", ".")
        return state["ids"] or {c: t.replace("tests.test_base", module) for c, t in BASE_OF.items()}

    def base_tests(*args, **kwargs):
        def only_base_test(e):
            test = TracingTest(ids()[e.criterion], "passed", state["proof"])
            return dataclasses.replace(e, state="covered", tests=(test,), ignored=(), capped=())

        return [only_base_test(e) if e.criterion in state["carry"] else e for e in real_trace(*args, **kwargs)]

    monkeypatch.setattr(ladder, "trace_criteria", base_tests)

    def file_of(wb, test):
        if test not in ids().values():
            return real_file(wb, test)
        return state["file"] if state["walk"] is None else (state["walk"] or None)  # "": the walk finds no module

    monkeypatch.setattr(ladder, "file_of_test", file_of)
    real_tree = ladder.worktree_files
    monkeypatch.setattr(
        ladder, "worktree_files", lambda wb: state["tree"] or [state["file"], *real_tree(wb)]
    )  # FAKE tree: the base tests' file next to the real files
    return state


def writer_requests(run) -> list[str]:
    return [r.prompt for r in run.adapter.requests if WRITER_PROMPT in r.prompt]


def test_scn_ver_343_an_unchanged_criterion_is_carried_and_only_the_other_gap_goes_to_the_writer(
    run_l4, valid_spec, web_repo, carry_repo
):
    import json

    run = run_l4([red_step(), web_green(), ui_test(UNKNOWN, 'data-testid="coupon"', "slot"), JUDGE], **web_repo)
    assert run.code == 0, run.outcome
    [asked] = writer_requests(run)
    assert UNKNOWN in asked and KNOWN not in asked  # only the other gap is written for
    made = {e["criterion"]: e for e in run.events("verify.generated")}
    assert made[KNOWN]["status"] == "carried" and made[KNOWN]["covered_by"] == [BASE_OF[KNOWN]]
    assert made[KNOWN]["attempts"] == 0 and made[UNKNOWN]["status"] == "accepted"
    text = run.pushed(f"{UNIT_DIR}/verification.md")
    row = next(line for line in text.splitlines() if line.startswith(f"| {KNOWN} | carried"))
    assert "carried from the base" in row and BASE_OF[KNOWN] in row
    assert f"UI criterion {KNOWN} has no end-to-end test" not in text and "## Needs a human" not in text
    gap = next(line for line in text.splitlines() if "No end-to-end test traces criterion" in line and KNOWN in line)
    assert "unchanged on the base" in gap
    body = json.loads(run.pushed(f"{UNIT_DIR}/.l4/evidence/round-1/verdict.json"))
    assert not [h for h in body["holds"] if KNOWN in h]
    assert steps_of(run)["5"] == "ok" and run.events("question.raised") == []


def test_scn_ver_343_with_every_gap_carried_nothing_is_checked_out_and_no_writer_is_needed(
    run_l4, valid_spec, web_repo, carry_repo, monkeypatch
):
    from l4.verifier import ladder

    carry_repo["carry"] = (KNOWN, UNKNOWN)

    def never(*args, **kwargs):
        raise AssertionError("the writer step ran although every gap was carried")

    monkeypatch.setattr(ladder, "generate_ui_tests", never)
    real = ladder.VerifyContext
    # no writer is opened (the config refuses an empty `roles.verifier_agent`): the carry needs none
    monkeypatch.setattr(ladder, "VerifyContext", lambda *args, **kw: real(*args, **{**kw, "ui_writer": None}))
    run = run_l4([red_step(), web_green(), JUDGE], **web_repo)
    assert run.code == 0, run.outcome
    assert writer_requests(run) == []
    made = {e["criterion"]: e["status"] for e in run.events("verify.generated")}
    assert made == {KNOWN: "carried", UNKNOWN: "carried"}
    assert "2 carried from the base (L4-VER-086)" in run.pushed(f"{UNIT_DIR}/verification.md")  # step 5's note


def test_scn_ver_345_a_test_file_the_unit_changed_keeps_the_writer_and_the_hold(
    run_l4, valid_spec, web_repo, carry_repo
):
    carry_repo["file"] = "tests/test_discount.py"  # the unit's own test file: changed since the merge base
    run = run_l4(
        [red_step(), web_green(), ui_test(KNOWN, 'data-testid="coupon"', "slot"), no_test(UNKNOWN), JUDGE], **web_repo
    )
    assert run.code == 11, run.outcome
    made = {e["criterion"]: e["status"] for e in run.events("verify.generated")}
    assert made == {KNOWN: "accepted", UNKNOWN: "uncollectable"}  # nothing carried
    assert len(writer_requests(run)) == 2


def test_scn_ver_346_a_red_proof_keeps_the_writer(run_l4, valid_spec, web_repo, carry_repo):
    carry_repo["proof"] = "red_assertion"
    run = run_l4(
        [red_step(), web_green(), ui_test(KNOWN, 'data-testid="coupon"', "slot"), no_test(UNKNOWN), JUDGE], **web_repo
    )
    assert run.code == 11, run.outcome
    assert "carried" not in {e["status"] for e in run.events("verify.generated")}


@pytest.mark.parametrize(
    ("tree", "walk", "known"),
    [
        # a Python module of the test's stem beside it: the module walk reads the test id as that module
        (["src/pricing/total.py", "src/pricing/total.test.ts"], "src/pricing/total.py", "src.pricing.total.test.ts::x"),
        # a module of the same name under two roots: which of the two ran is not known
        (["tests/test_a.py", "pkg/tests/test_a.py"], "tests/test_a.py", "tests.test_a::x"),
        # a test that is not Python, with two files that could hold it
        (["src/pricing/total.test.ts", "lib/src/pricing/total.test.ts"], "", "src.pricing.total.test.ts::x"),
    ],
    ids=["same-stem-module", "two-roots", "two-typescript-files"],
)
def test_scn_ver_351_a_test_whose_file_is_in_doubt_keeps_the_writer_and_the_hold(
    run_l4, valid_spec, web_repo, carry_repo, tree, walk, known
):
    carry_repo.update(tree=tree, walk=walk, ids={KNOWN: known, UNKNOWN: known.replace("::x", "::y")}, file=tree[0])
    run = run_l4(
        [red_step(), web_green(), ui_test(KNOWN, 'data-testid="coupon"', "slot"), no_test(UNKNOWN), JUDGE], **web_repo
    )
    assert run.code == 11, run.outcome
    made = {e["criterion"]: e["status"] for e in run.events("verify.generated")}
    assert made == {KNOWN: "accepted", UNKNOWN: "uncollectable"}  # nothing carried
    assert len(writer_requests(run)) == 2


def test_scn_ver_351_the_plain_case_is_carried_with_its_file_found_by_both_readings(
    run_l4, valid_spec, web_repo, carry_repo
):
    carry_repo.update(tree=["tests/test_base.py", "tests/test_other.py", "src/pricing/total.py"])
    run = run_l4([red_step(), web_green(), ui_test(UNKNOWN, 'data-testid="coupon"', "slot"), JUDGE], **web_repo)
    assert run.code == 0, run.outcome
    assert {e["criterion"]: e["status"] for e in run.events("verify.generated")}[KNOWN] == "carried"


def test_scn_ver_351_a_typescript_only_criterion_is_carried_when_the_walk_finds_no_module(
    run_l4, valid_spec, web_repo, carry_repo
):
    ids = {KNOWN: "src.pricing.total.test.ts::x", UNKNOWN: "src.pricing.total.test.ts::y"}
    carry_repo.update(tree=["src/pricing/total.test.ts", "src/pricing/total.ts"], walk="", ids=ids)
    run = run_l4([red_step(), web_green(), ui_test(UNKNOWN, 'data-testid="coupon"', "slot"), JUDGE], **web_repo)
    assert run.code == 0, run.outcome
    assert {e["criterion"]: e["status"] for e in run.events("verify.generated")}[KNOWN] == "carried"


def test_scn_ver_348_a_carry_does_not_pass_the_criterion_the_judge_calls_inadequate(
    run_l4, valid_spec, web_repo, carry_repo
):
    inadequate = Step(
        structured=judge_reply(
            [KNOWN, UNKNOWN],
            test_adequacy=[
                {"test": BASE_OF[KNOWN], "criterion": KNOWN, "adequate": False, "reason": "it does not open the page"}
            ],
        )
    )
    run = run_l4([red_step(), web_green(), ui_test(UNKNOWN, 'data-testid="coupon"', "slot"), inadequate], **web_repo)
    assert run.code == 11, run.outcome
    assert {e["criterion"]: e["status"] for e in run.events("verify.generated")}[KNOWN] == "carried"
    text = run.pushed(f"{UNIT_DIR}/verification.md")
    row = next(line for line in text.splitlines() if line.startswith(f"| {KNOWN} |") and "needs_human" in line)
    assert "uncovered" in row
    asked = run.events("question.raised")
    assert len(asked) == 1 and asked[0].get("criterion", KNOWN) == KNOWN and "UI criterion" not in asked[0]["title"]
    assert f"UI criterion {KNOWN} has no end-to-end test" not in text


def answer_on_origin(tdd_repo, raw, answers: dict[str, str]) -> None:
    """What a person does with several questions: one clone, each question answered, one push."""
    from l4.specs.questions import QuestionsFile, QuestionStatus

    from ..orchestrator.conftest import BRANCH

    clone = tdd_repo.repo.parent / "human-several"
    raw(tdd_repo.repo.parent, "clone", "-q", "--branch", BRANCH, str(tdd_repo.origin), str(clone))
    path = clone / UNIT_DIR / "questions.md"
    file = QuestionsFile.load(path)
    assert file is not None
    for qid, answer in answers.items():
        file = file.set_status(qid, QuestionStatus("answered"))
        body = file.get(qid).answer.body  # type: ignore[union-attr]
        file = QuestionsFile.parse(file.data[: body.end] + answer.encode() + b"\n" + file.data[body.end :])
    file.save(path)
    raw(clone, "add", "-A")
    raw(clone, "commit", "-q", "-m", "answer " + ", ".join(answers))
    raw(clone, "push", "-q", "origin", BRANCH)


def test_scn_ver_347_a_reject_in_the_ledger_is_never_passed_by_a_carry(
    run_l4, valid_spec, web_repo, carry_repo, tdd_repo, raw
):
    from ..orchestrator.conftest import BRANCH

    carry_repo["carry"] = ()  # round 1: nothing is carried; the writer fails for KNOWN, so its UI hold is asked
    first = run_l4(
        [red_step(), web_green(), no_test(KNOWN), ui_test(UNKNOWN, 'data-testid="coupon"', "slot"), JUDGE], **web_repo
    )
    assert first.code == 11, first.outcome
    [asked] = first.events("question.raised")
    assert asked["criterion"] == KNOWN
    answer_on_origin(tdd_repo, raw, {"Q-001": "reject: the badge is missing. WHEN the cart opens THEN it shows SAVE10"})
    clone = tdd_repo.repo.parent / "human-several"  # the person also touches the app: the round is not reused
    (clone / "app.py").write_text((clone / "app.py").read_text() + "\n# touched\n")
    raw(clone, "commit", "-q", "-am", "touch the app")
    raw(clone, "push", "-q", "origin", BRANCH)
    carry_repo["carry"] = (KNOWN,)  # round 2 would carry it, but the reject stands
    second = run_l4([no_test(KNOWN), JUDGE], **web_repo)
    assert second.code == 10, second.outcome  # the rejected hold is a finding of a FAIL round: the fix unit is written
    assert "carried" not in {e["status"] for e in second.events("verify.generated")}
    assert len(writer_requests(second)) == 1 and KNOWN in writer_requests(second)[0]  # the writer was asked again
    assert [e["verdict"] for e in second.events("verify.verdict")] == ["NEEDS_HUMAN", "FAIL"]


def test_scn_ver_349_a_reused_round_keeps_the_carry_and_asks_nobody_again(
    run_l4, valid_spec, web_repo, carry_repo, tdd_repo, raw
):
    import json

    from ..orchestrator.conftest import edit_questions_on_origin

    first = run_l4([red_step(), web_green(), no_test(UNKNOWN), JUDGE], **web_repo)  # KNOWN carried, UNKNOWN held
    assert first.code == 11, first.outcome
    [asked] = first.events("question.raised")
    assert asked["criterion"] == UNKNOWN
    edit_questions_on_origin(tdd_repo, raw, status="answered", answer="accept: a unit test covers it")
    second = run_l4([], **web_repo)  # the stored round is reused: no writer, no judge
    assert second.code == 0, second.outcome
    assert second.adapter.requests == [] and len(second.events("question.raised")) == 1
    carried = [e for e in second.events("verify.generated") if e["status"] == "carried"]
    assert [e["criterion"] for e in carried] == [KNOWN]  # recorded once, by round 1
    body = json.loads(second.pushed(f"{UNIT_DIR}/.l4/evidence/round-2/verdict.json"))
    made = {g["criterion"]: g for g in body["generated"]}
    assert made[KNOWN]["status"] == "carried" and made[KNOWN]["covered_by"] == [BASE_OF[KNOWN]]
    assert not any(KNOWN in hold for hold in body["holds"])
    text = second.pushed(f"{UNIT_DIR}/verification.md")
    assert "reused (round 1)" in text and "carried from the base" in text


def test_scn_ver_342_a_criterion_and_its_ui_hold_rejected_after_a_needs_human_round_are_one_task(
    run_l4, valid_spec, web_repo, tdd_repo, raw
):
    """The round that asked both questions is reused once they are answered, so the rejects settle through this
    harness's `_hold_finding`: FAIL, the hold's finding cites the criterion, and the fix unit has one task."""
    import json

    skipped = Step(structured=judge_reply([UNKNOWN]))  # a criterion the judge skipped is `needs_human`
    first = run_l4(
        [red_step(), web_green(), no_test(KNOWN), ui_test(UNKNOWN, 'data-testid="coupon"', "slot"), skipped], **web_repo
    )
    assert first.code == 11, first.outcome
    asked = {e["target"]: e["id"] for e in first.events("question.raised")}
    hold = next(t for t in asked if t.startswith("H-"))
    assert set(asked) == {KNOWN, hold}
    then = "WHEN the cart opens THEN it shows SAVE10"
    answer_on_origin(
        tdd_repo, raw,
        {asked[KNOWN]: f"reject: the badge is missing. {then}", asked[hold]: f"reject: same. {then}"},
    )  # fmt: skip
    second = run_l4([], **web_repo)
    assert second.code == 10, second.outcome
    assert [e["verdict"] for e in second.events("verify.verdict")] == ["NEEDS_HUMAN", "FAIL"]
    body = json.loads(second.pushed(f"{UNIT_DIR}/.l4/evidence/round-2/verdict.json"))
    [finding] = [f for f in body["findings"] if f["id"] == hold]
    assert finding["criterion"] == KNOWN and finding["severity"] == "major"
    [spawned] = second.events("fix.spawned")
    assert sorted(spawned["consumed"]) == sorted(asked.values())
    tasks = second.pushed(f"{UNIT_DIR}-fix-1/tasks.md")
    assert len([line for line in tasks.splitlines() if line.startswith("- [ ]")]) == 1 and hold in tasks
    delta = second.pushed(f"{UNIT_DIR}-fix-1/specs/pricing/spec.md")
    assert delta.count("#### Scenario:") == 1 and "finding H-" not in delta  # the same text is pinned once


# -- ui-carry-followup (L4-VER-097, L4-VER-098): a changed test file that the unit only added tests to

PRICING = "tests/test_pricing.py"  # the fixture's own test file: the base holds it, the unit appends one test to it
OLD_PRICING = {
    KNOWN: "tests.test_pricing::test_total_adds_prices",
    UNKNOWN: "tests.test_pricing::test_total_of_nothing_is_zero",
}
NEW_TEST = (
    "def test_total_of_one_price_and_a_discount():\n"
    "    from pytdd.pricing import apply_discount\n\n"
    "    assert apply_discount(total([10.0]), 'SAVE10') == 9.0\n"
)


def appending_red(*, test: str = NEW_TEST) -> Step:
    """The red step of the unit, which also appends one new test to the base's `tests/test_pricing.py`."""
    from ..conftest import FIXTURE

    base = (FIXTURE / PRICING).read_text()
    red = red_step()
    return Step(
        writes={**red.writes, PRICING: base + "\n\n" + test}, structured=red.structured,
    )  # fmt: skip


@pytest.fixture
def appended_repo(carry_repo):
    """`carry_repo` whose base tests are the real ones of `tests/test_pricing.py`, a file the unit appends to."""
    carry_repo.update(file=PRICING, ids=dict(OLD_PRICING), tree=None)
    return carry_repo


def test_scn_ver_416_a_test_file_the_unit_only_appended_to_carries_its_criteria_through_the_real_ladder(
    run_l4, valid_spec, web_repo, appended_repo
):
    import json

    run = run_l4([appending_red(), web_green(), ui_test(UNKNOWN, 'data-testid="coupon"', "slot"), JUDGE], **web_repo)
    assert run.code == 0, run.outcome
    assert PRICING in run.raw(run.tdd.origin, "diff", "--name-only", "main", BRANCH).split()  # the file is changed
    made = {e["criterion"]: e for e in run.events("verify.generated")}
    assert made[KNOWN]["status"] == "carried" and made[KNOWN]["appended"] == [PRICING]
    assert made[KNOWN]["covered_by"] == [OLD_PRICING[KNOWN]] and made[KNOWN]["attempts"] == 0
    assert made[UNKNOWN]["status"] == "accepted" and "appended" not in made[UNKNOWN]  # the writer's own test
    [asked] = writer_requests(run)
    assert UNKNOWN in asked and KNOWN not in asked  # only the other gap goes to the writer
    text = run.pushed(f"{UNIT_DIR}/verification.md")
    row = next(line for line in text.splitlines() if line.startswith(f"| {KNOWN} | carried"))
    assert f"the unit only added tests to {PRICING}; a note, not a hold (L4-VER-086)" in row
    body = json.loads(run.pushed(f"{UNIT_DIR}/.l4/evidence/round-1/verdict.json"))
    assert {g["criterion"]: g.get("appended") for g in body["generated"]}[KNOWN] == [PRICING]
    assert not [h for h in body["holds"] if KNOWN in h] and run.events("question.raised") == []


def test_scn_ver_421_step_1s_record_of_the_round_decides_through_outcome_into_the_carry(
    run_l4, valid_spec, web_repo, appended_repo, monkeypatch
):
    from l4.verifier import base_tests
    from l4.verifier.carry_appended import Step1Run

    seen: list[Step1Run | None] = []
    real = base_tests.check_base_tests

    def checked(*args, **kwargs):
        outcome = real(*args, **kwargs)
        seen.append(outcome.base_run)
        outcome.base_run = None
        return outcome

    monkeypatch.setattr(base_tests, "check_base_tests", checked)
    refused = [appending_red(), web_green(), ui_test(KNOWN, 'data-testid="coupon"', "slot"), no_test(UNKNOWN), JUDGE]
    run = run_l4(refused, **web_repo)  # step 1's record is gone: the file is not known to have run at its base version
    assert run.code == 11, run.outcome
    made = {e["criterion"]: e["status"] for e in run.events("verify.generated")}
    assert made == {KNOWN: "accepted", UNKNOWN: "uncollectable"}  # nothing carried, as in 0.4.60
    [record] = seen
    assert record is not None and PRICING in record.reverted  # the real record lists the file `reverted`
    assert not (record.failing or record.not_run or record.flaky)


@pytest.mark.parametrize("field", ["failing", "not_run", "flaky"])
def test_scn_ver_421_a_tracing_test_among_failing_not_run_or_flaky_at_step_1_keeps_the_hold(
    run_l4, valid_spec, web_repo, appended_repo, monkeypatch, field
):
    import dataclasses as dc

    from l4.verifier import base_tests

    real = base_tests.check_base_tests

    def checked(*args, **kwargs):
        outcome = real(*args, **kwargs)
        outcome.base_run = dc.replace(outcome.base_run, **{field: (OLD_PRICING[KNOWN],)})
        return outcome

    monkeypatch.setattr(base_tests, "check_base_tests", checked)
    run = run_l4(
        [appending_red(), web_green(), ui_test(KNOWN, 'data-testid="coupon"', "slot"), no_test(UNKNOWN), JUDGE],
        **web_repo,
    )
    assert run.code == 11, run.outcome
    assert {e["criterion"]: e["status"] for e in run.events("verify.generated")} == {
        KNOWN: "accepted", UNKNOWN: "uncollectable",
    }  # fmt: skip


@pytest.mark.parametrize(
    "variant",
    ["an import", "a tracing test"],
    ids=["import", "new-test-traces-a-criterion"],
)
def test_scn_ver_419_an_appended_test_that_is_not_a_plain_test_keeps_the_hold_through_the_real_ladder(
    run_l4, valid_spec, web_repo, appended_repo, variant
):
    """Each variant is refused by one rule of the pure function alone: a line outside the tests, a new test of the file
    that traces a criterion (so not every tracing test of the file is an old one). A decorator, a hook or a `vi.mock` is
    a case of the pure function's own tests."""
    red = appending_red(test={
        "an import": NEW_TEST,
        "a tracing test": NEW_TEST.replace("test_total_of", f"test_{UNKNOWN.replace('-', '_')}_total_of"),
    }[variant])  # fmt: skip
    if variant == "an import":
        red.writes[PRICING] = "import os\n" + red.writes[PRICING]
    run = run_l4(
        [red, web_green(), ui_test(KNOWN, 'data-testid="coupon"', "slot"), no_test(UNKNOWN), JUDGE], **web_repo
    )
    assert run.code == 11, run.outcome
    assert {e["criterion"]: e["status"] for e in run.events("verify.generated")}[KNOWN] == "accepted"  # not carried


def test_scn_ver_426_a_reused_round_keeps_the_carry_and_the_row_still_names_the_file(
    run_l4, valid_spec, web_repo, appended_repo, tdd_repo, raw
):
    import json

    from ..orchestrator.conftest import edit_questions_on_origin

    first = run_l4([appending_red(), web_green(), no_test(UNKNOWN), JUDGE], **web_repo)  # KNOWN carried, UNKNOWN held
    assert first.code == 11, first.outcome
    edit_questions_on_origin(tdd_repo, raw, status="answered", answer="accept: a unit test covers it")
    second = run_l4([], **web_repo)  # the stored round is reused: nothing is decided again
    assert second.code == 0, second.outcome
    assert second.adapter.requests == []
    carried = [e for e in second.events("verify.generated") if e["status"] == "carried"]
    assert [e["criterion"] for e in carried] == [KNOWN]  # recorded once, by round 1
    body = json.loads(second.pushed(f"{UNIT_DIR}/.l4/evidence/round-2/verdict.json"))
    assert {g["criterion"]: g.get("appended") for g in body["generated"]}[KNOWN] == [PRICING]
    text = second.pushed(f"{UNIT_DIR}/verification.md")
    row = next(line for line in text.splitlines() if line.startswith(f"| {KNOWN} | carried"))
    assert (
        f"carried from the base: {OLD_PRICING[KNOWN]} (" in row and f"the unit only added tests to {PRICING}; " in row
    )
    assert "reused (round 1)" in text
