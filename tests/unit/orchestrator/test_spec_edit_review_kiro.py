# ruff: noqa: F811
"""L4-OPS-015, SCN-OPS-27: a Kiro unit in `in_review` whose requirement was reworded by a person re-enters through
`spec_edit_after_handoff`, and the task that cites the criterion is `[ ]` again in the harness's reopening commit
(`_review` -> `_before_first_foreign` -> `_reopen`)."""

import pytest

from l4.agents.fake import Step

from ..archive.conftest import forge_env, gitlab, use_fake_gitlab  # noqa: F401  (a fake GitLab for the hand-off)
from ..implementer.conftest import result
from ..verifier.conftest import judge_reply
from .test_kiro_unit import (
    BRANCH,
    DISCOUNT_DONE,
    DISCOUNT_ID,
    REQUIREMENTS,
    SPEC,
    TASKS,
    _events,
    _write_unit,
    script,
)
from .test_spec_edit_reopen import ids_of, push_requirements

TRIMMED = DISCOUNT_DONE.replace("return name.upper()", "return name.strip().upper()")
REWORDED = REQUIREMENTS.replace(
    "THE Shop SHALL return it in capitals.", "THE Shop SHALL return it in capitals, without the spaces around it."
)


@pytest.fixture(autouse=True)
def no_verifier() -> None:
    """The real verifier is on: the hand-off needs its PASS (overrides the orchestrator suite's)."""


@pytest.fixture(autouse=True)
def no_fix_loop() -> None:
    """The fix loop is on."""


def test_a_reworded_criterion_after_the_handoff_reopens_its_task_on_a_kiro_unit(
    run_l4, tdd_repo, raw, forge_env, use_fake_gitlab
):
    _write_unit(tdd_repo, raw, TASKS)
    ids = ids_of(REQUIREMENTS)
    first = run_l4(
        [*script(), Step(structured=judge_reply([ids["Req 1.1"], ids["Req 2.1"]]))],
        "--unit",
        "kiro:discounts",
        unit=False,
    )
    assert first.code == 0 and first.outcome["units"][0]["phase_after"] == "in_review", first.outcome
    assert "- [x] 2.1" in raw(tdd_repo.origin, "show", f"{BRANCH}:{SPEC}/tasks.md")

    push_requirements(tdd_repo, raw, REWORDED, "reword")
    raw(tdd_repo.repo, "fetch", "-q", "origin")
    new = ids_of(REWORDED)["Req 2.1"]
    assert new != ids["Req 2.1"]
    trim_test = (
        f'import pytest\n\nfrom pytdd.pricing import shout\n\n\n@pytest.mark.l4("{new}")\ndef test_trim():\n'
        '    assert shout(" ada ") == "ADA"\n'
    )
    red = Step(
        writes={"tests/test_trim.py": trim_test},
        structured=result("red", task_ids=["2.1"], tests_added=["tests/test_trim.py::test_trim"], criteria_ids=[new]),
    )
    green = Step(writes={"src/pytdd/pricing.py": TRIMMED}, structured=result("green", task_ids=["2.1"]))
    second = run_l4(
        [red, green, Step(structured=judge_reply([DISCOUNT_ID, new]))], "--unit", "kiro:discounts", unit=False
    )

    assert second.code == 0, second.adapter.requests[-1].prompt[-600:] if second.adapter.requests else second.outcome
    log = sorted(_events(raw, tdd_repo), key=lambda e: (e["ts"], e["run_id"], e["seq"]))
    changes = [(e["from"], e["to"], e["trigger"]) for e in log if e["type"] == "phase.changed"]
    at = changes.index(("in_review", "implementing", "spec_edit_after_handoff"))
    assert changes[at + 1][2] == "all_leaves_done"
    [reopened] = [e for e in log if e["type"] == "tasks.reopened"]
    assert (reopened["tasks"], reopened["requirements"]) == (["2", "2.1"], ["2.1"])
    subjects = raw(tdd_repo.origin, "log", "--format=%s", f"main..{BRANCH}").splitlines()
    reopen = "chore(discounts): reopen tasks 2, 2.1 for changed requirements 2.1 [skip ci]"
    assert subjects.count(reopen) == 1
    sha = raw(tdd_repo.origin, "log", "--format=%H", f"--grep=^{reopen[:40]}", BRANCH).split()[0]
    assert "- [ ] 2.1" in raw(tdd_repo.origin, "show", f"{sha}:{SPEC}/tasks.md")
    assert "- [x] 2.1" in raw(tdd_repo.origin, "show", f"{BRANCH}:{SPEC}/tasks.md")  # and it ran again
    assert [e["task"] for e in log if e["type"] == "task.started"][-1] == "2.1"
