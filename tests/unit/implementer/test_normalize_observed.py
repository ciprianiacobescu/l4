"""result-contract 1.3, SCN-IMP-193 at function level: the observed failing objects are accepted with exactly their
expected fixes. The entries are in tests/fixtures/results/observed.json (eight objects of docs/live as the agents
wrote them, six synthetic ones built from the result failures of one model on a public consumer repository)."""

import json
from pathlib import Path
from typing import Any

import pytest

from l4.implementer.normalize import Found, StepFacts, normalize
from l4.implementer.result import ResultInvalid, parse_result

DATA = json.loads((Path(__file__).parents[2] / "fixtures" / "results" / "observed.json").read_text(encoding="utf-8"))
ENTRIES: list[dict[str, Any]] = DATA["entries"]
IDS = [entry["id"] for entry in ENTRIES]


def test_the_fixture_holds_the_eight_observed_and_the_six_synthetic_entries():
    assert len(ENTRIES) == 14 and len(set(IDS)) == 14
    assert [e["synthetic"] for e in ENTRIES] == [False] * 8 + [True] * 6
    assert [e["id"] for e in ENTRIES if not e["delivered"]] == ["magnitude-earlier-red-3"]
    for entry in ENTRIES:
        assert set(entry) >= {"id", "source", "model", "phase", "task", "object", "last_message", "expected_fixes"}


@pytest.mark.parametrize("entry", ENTRIES, ids=IDS)
def test_each_object_fails_before_and_passes_after_with_exactly_its_fixes(entry):
    with pytest.raises(ResultInvalid):
        parse_result(entry["object"])
    facts = StepFacts(entry["phase"], entry["task"], entry["changed_files"], entry["last_message"])
    done = normalize(Found(entry["object"], "result"), facts)
    parsed = parse_result(done.obj)
    assert [fix.as_event() for fix in done.fixes] == entry["expected_fixes"]
    assert parsed.phase == entry["phase"] and parsed.task_ids == [entry["task"]]
    assert parsed.files_changed == entry["changed_files"] and parsed.tests_added == []


@pytest.mark.parametrize("entry", ENTRIES, ids=IDS)
def test_no_fix_holds_text_of_the_agent(entry):
    facts = StepFacts(entry["phase"], entry["task"], entry["changed_files"], entry["last_message"])
    events = json.dumps([fix.as_event() for fix in normalize(Found(entry["object"], "result"), facts).fixes])
    assert entry["last_message"][:20] not in events
    for key in ("summary", "notes", "notes_for_verifier"):
        text = entry["object"].get(key)
        assert not isinstance(text, str) or text[:20] not in events


def test_the_normalization_judges_nothing_about_the_work():
    """A repaired object claims what the agent claimed: the done status, the criteria and the exemption stay."""
    entry = next(e for e in ENTRIES if e["id"] == "nemotron-red-3")
    facts = StepFacts(entry["phase"], entry["task"], entry["changed_files"], entry["last_message"])
    done = normalize(Found(entry["object"], "result"), facts)
    assert done.obj["status"] == "done" and done.obj["tdd_exemption"] == entry["object"]["tdd_exemption"]
    assert done.obj["criteria_ids"] == entry["object"]["criteria_ids"]
    failed = next(e for e in ENTRIES if e["id"] == "nemotron-red-1")
    facts = StepFacts(failed["phase"], failed["task"], failed["changed_files"], failed["last_message"])
    assert normalize(Found(failed["object"], "result"), facts).obj["status"] == "failed"  # kept, not made done
