"""Live job 5482 seq 66: a codex step saw the run ledger as modified in `git status` and reset it to HEAD. The prompt
now names the ledger and says the modification is expected (SPEC L4-IMP-004, SCN-IMP-47)."""

import pytest

from l4.agents.fake import Step

from ..implementer.conftest import IMPL, red_step, result
from ..orchestrator.conftest import UNIT_DIR
from .conftest import judge_reply
from .test_ladder_fix import CRITERIA, noqa_green


@pytest.fixture(autouse=True)
def no_fix_loop() -> None:
    """The fix loop is on, as in `test_ladder_fix`."""


def test_every_implementer_prompt_names_the_run_ledger_including_the_fix_units_step(run_l4, valid_spec):
    run = run_l4(
        [red_step(), noqa_green(), Step(writes={"src/pytdd/pricing.py": IMPL}, structured=result("single")),
         Step(structured=judge_reply(CRITERIA))]
    )  # fmt: skip
    run_id = run.ledger()[0]["run_id"]
    ledger = f"{UNIT_DIR}/.l4/ledger/{run_id}.jsonl"
    for index in (0, 1, 2):  # red, green, and the fix unit's step: the parent's ledger
        prompt = run.adapter.requests[index].prompt
        assert ledger in prompt, index
        assert "`git status` shows it as modified" in prompt and "any `.l4/` directory at any depth" in prompt
