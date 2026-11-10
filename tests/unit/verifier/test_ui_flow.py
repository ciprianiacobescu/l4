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
