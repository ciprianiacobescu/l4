"""L4-OPS-015, design D14 "Stale tests": a criterion whose text changed after the unit passed leaves tests written for
the old text. The reopened task's red step may replace them (delete, or rewrite under a new name for the new id); the
red verdict, green and the verifier's integrity check do not count that as a regression. Every other test stays
protected. Found live: `kiro:pick-priority`, criterion 1.3 `none` -> `ok`."""

from l4.agents.fake import Step
from l4.implementer.reopen import pending_stale
from l4.state.ledger import read_ledger

from .test_spec_edit_reopen import (
    BASE,
    BRANCH,
    LONG,
    REQUIREMENTS,
    SPEC,
    boxes,
    ids_of,
    ledger,
    push_requirements,
    shout_test,
    start,
    step,
)

LOWER_TEXT = "THE Shop SHALL\n   return it in lower case."
LOWER = BASE + '\n\ndef shout(name):\n    return name.lower() or "-"\n'
DASH = BASE + '\n\ndef shout(name):\n    return name.upper() or "-"\n'


def reworded() -> str:
    text = REQUIREMENTS.replace("THE Shop SHALL\n   return it in capitals.", LOWER_TEXT)
    assert text != REQUIREMENTS
    return text


def lower_script(ids: dict[str, str], *, deletes: tuple[str, ...] = ("tests/test_long.py",)) -> list[Step]:
    """Red replaces the stale `test_long` (upper case, old id) with `test_lower` (lower case, new id); green follows."""
    new_test = shout_test("lower", ids["Req 2.3"], LONG.upper(), LONG)
    return [
        Step(
            writes={**new_test, "src/pytdd/pricing.py": DASH}, deletes=deletes,
            structured=step("red", "2.1", {}, tests_added=["tests/test_lower.py::test_lower"],
                            criteria_ids=[ids["Req 2.3"]]).structured,
        ),
        step("green", "2.1", {"src/pytdd/pricing.py": LOWER}),
    ]  # fmt: skip


def test_the_reopen_records_the_old_id_of_the_changed_criterion(run_l4, tdd_repo, raw):
    old = start(run_l4, tdd_repo, raw)
    new_text = reworded()
    push_requirements(tdd_repo, raw, new_text, "reword")
    new = ids_of(new_text)
    second = run_l4(lower_script(new), "--unit", "kiro:discounts", unit=False)
    assert second.code == 0
    [reopened] = [e for e in ledger(raw, tdd_repo) if e["type"] == "tasks.reopened"]
    assert reopened["stale_criteria"] == [old["Req 2.3"]] and old["Req 2.3"] != new["Req 2.3"]
    [change] = reopened["changes"]
    assert (change["requirement"], change["old_id"], change["new_id"]) == ("2.3", old["Req 2.3"], new["Req 2.3"])
    assert "capitals" in change["old_text"] and "lower case" in change["new_text"]


def test_a_stale_test_replaced_in_the_reopened_red_step_passes_red_green_and_is_recorded(run_l4, tdd_repo, raw):
    """(a) The live case end to end: red deletes the stale test and adds one for the new id."""
    start(run_l4, tdd_repo, raw)
    new_text = reworded()
    push_requirements(tdd_repo, raw, new_text, "reword")
    second = run_l4(lower_script(ids_of(new_text)), "--unit", "kiro:discounts", unit=False)

    assert second.code == 0
    assert boxes(raw(tdd_repo.origin, "show", f"{BRANCH}:{SPEC}/tasks.md")) == ["- [x]"] * 3
    log = ledger(raw, tdd_repo)
    [superseded] = [e for e in log if e["type"] == "tests.superseded"]
    assert superseded["task"] == "2.1" and len(superseded["tests"]) == 1
    assert superseded["tests"][0].endswith("::test_long") and len(superseded["criteria"]) == 1
    kinds = [e["type"] for e in log]
    last_red = len(kinds) - 1 - kinds[::-1].index("task.red_ok")
    assert kinds.index("tests.superseded") == last_red - 1  # written just before the red proof, inside its commit
    assert [e["type"] for e in log if e["type"] in ("task.red_ok", "task.done")][-2:] == ["task.red_ok", "task.done"]
    assert "tests/test_long.py" not in raw(tdd_repo.origin, "ls-tree", "-r", "--name-only", BRANCH)


def test_the_red_prompt_names_the_stale_test_and_the_changed_criterion(run_l4, tdd_repo, raw):
    """(b)"""
    old = start(run_l4, tdd_repo, raw)
    new_text = reworded()
    push_requirements(tdd_repo, raw, new_text, "reword")
    new = ids_of(new_text)
    second = run_l4(lower_script(new), "--unit", "kiro:discounts", unit=False)
    red_prompt, green_prompt = (r.prompt for r in second.adapter.requests)
    assert "# Stale tests" in red_prompt and "test_long" in red_prompt
    assert old["Req 2.3"] in red_prompt and new["Req 2.3"] in red_prompt
    assert "return it in capitals." in red_prompt and "return it in lower case." in red_prompt
    assert "replaced" in red_prompt.lower()
    assert "# Stale tests" not in green_prompt


def test_a_test_that_is_not_stale_deleted_in_the_same_step_is_still_a_red_failure(run_l4, tdd_repo, raw):
    """(c) `test_empty` traces criterion 2.2, which did not change: it stays protected."""
    start(run_l4, tdd_repo, raw)
    new_text = reworded()
    push_requirements(tdd_repo, raw, new_text, "reword")
    script = lower_script(ids_of(new_text), deletes=("tests/test_long.py", "tests/test_empty.py"))
    second = run_l4(script, "--unit", "kiro:discounts", unit=False, implementer={"max_task_attempts": 1})
    assert second.code != 0
    assert "tests.superseded" not in [e["type"] for e in ledger(raw, tdd_repo)]
    failed = [e for e in ledger(raw, tdd_repo) if e["type"].startswith("task.") and "reason" in e]
    assert any("red broke existing tests" in str(e["reason"]) and "test_empty" in str(e["reason"]) for e in failed)
    assert not any("test_long" in str(e["reason"]) for e in failed)


def test_an_openspec_unit_has_no_stale_criteria(tdd_repo):
    """(d) Nothing reopens an OpenSpec unit, so the ledger holds no pending stale entry."""
    assert pending_stale(read_ledger(tdd_repo.repo).events, "1.1") == []


def test_a_stale_test_rewritten_in_place_under_the_same_name_is_fine_when_a_new_test_fails(run_l4, tdd_repo, raw):
    """The stale `test_long` is rewritten for lower case under its own name; the new test for the new id fails."""
    start(run_l4, tdd_repo, raw)
    new_text = reworded()
    push_requirements(tdd_repo, raw, new_text, "reword")
    new = ids_of(new_text)
    script = lower_script(new, deletes=())
    script[0].writes = {**script[0].writes, **shout_test("long", new["Req 2.3"], "ABC", "abc")}
    second = run_l4(script, "--unit", "kiro:discounts", unit=False)
    assert second.code == 0
    [superseded] = [e for e in ledger(raw, tdd_repo) if e["type"] == "tests.superseded"]
    assert superseded["tests"][0].endswith("::test_long")  # it failed in red on purpose; green made it pass


def test_the_stale_allowance_does_not_cover_another_test_of_the_same_step(run_l4, tdd_repo, raw):
    """SCN-IMP-271 (L4-IMP-048): the reopened red may replace the stale `test_long`, but rewriting another
    pre-existing test in the same step still fails the attempt, naming only that test."""
    start(run_l4, tdd_repo, raw)
    new_text = reworded()
    push_requirements(tdd_repo, raw, new_text, "reword")
    script = lower_script(ids_of(new_text))
    script[0].writes = {
        **script[0].writes,
        "tests/test_pricing.py": "from pytdd import total\n\n\ndef test_total_adds_prices():\n    assert True\n\n\n"
        "def test_total_of_nothing_is_zero():\n    assert total([]) == 0\n",
    }
    second = run_l4(script, "--unit", "kiro:discounts", unit=False, implementer={"max_task_attempts": 1})
    assert second.code != 0
    failed = [str(e["reason"]) for e in ledger(raw, tdd_repo) if e["type"] == "task.attempt_failed"]
    [reason] = [r for r in failed if r.startswith("red changed tests that existed before this step")]
    assert "test_total_adds_prices" in reason and "test_long" not in reason
