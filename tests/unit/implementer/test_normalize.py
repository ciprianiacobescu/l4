"""result-contract 1.2: the normalization rules of design D4, one test per rule, and a property test."""

import copy
import json
import random
import re
from typing import Any

import pytest

from l4.implementer.normalize import CUT_MARKER, NO_SUMMARY, Fix, Found, StepFacts, normalize
from l4.implementer.result import RESULT_SCHEMA, parse_result

CHANGED = ("src/pricing/split.py", "tests/test_split.py")
CRITERION = "C-0a1b2c3d"
QUESTION = {"title": "Which rounding?", "context": "The spec is silent.", "kind": "product"}
SUMMARY_MAX = RESULT_SCHEMA["properties"]["summary"]["maxLength"]
NOTES_MAX = RESULT_SCHEMA["properties"]["notes_for_verifier"]["maxLength"]
REASON_MAX = RESULT_SCHEMA["properties"]["suppressions"]["items"]["properties"]["reason"]["maxLength"]


def facts(phase: str = "red", last: str | None = None, changed: tuple[str, ...] = CHANGED) -> StepFacts:
    return StepFacts(phase, "1.1", changed, last)


def valid(**over: Any) -> dict[str, Any]:
    base = {"status": "done", "phase": "red", "task_ids": ["1.1"], "summary": "added two tests"}
    return {**base, **over}


def run(obj: dict[str, Any], f: StepFacts | None = None, source: str = "result", text: str | None = None):
    found = Found(obj, source, text)  # type: ignore[arg-type]
    done = normalize(found, f or facts())
    parse_result(done.obj)  # whatever the rule did, the canonical schema holds afterwards
    return done


def test_a_valid_object_gets_no_fix_and_the_harness_fields():
    done = run({"status": "done", "summary": "s", "criteria_ids": [CRITERION]})
    assert done.fixes == []
    assert done.obj["phase"] == "red" and done.obj["task_ids"] == ["1.1"]
    assert done.obj["files_changed"] == list(CHANGED) and done.obj["tests_added"] == []
    assert done.obj["criteria_ids"] == [CRITERION]


def test_the_input_object_is_not_changed():
    obj = valid(notes="n", files_changed=[{"p": 1}], questions=[dict(QUESTION), {"title": 1}], status="red")
    before = copy.deepcopy(obj)
    run(obj)
    assert obj == before


def test_null_means_absent():
    done = run(valid(questions=None, suppressions=None, notes_for_verifier=None, tdd_exemption=None, phase=None))
    assert done.fixes == [] and "questions" not in done.obj and done.obj["phase"] == "red"


# rule 1: aliases
def test_rule_1_notes_becomes_notes_for_verifier():
    done = run(valid(notes="look at the stub"))
    assert done.fixes == [Fix("notes_for_verifier", "renamed", from_="notes")]
    assert done.obj["notes_for_verifier"] == "look at the stub" and "notes" not in done.obj


def test_rule_1_the_alias_is_dropped_when_the_real_key_is_there():
    done = run(valid(notes="alias", notes_for_verifier="real"))
    assert done.fixes == [Fix("notes", "dropped")]
    assert done.obj["notes_for_verifier"] == "real" and "notes" not in done.obj


def test_rule_1_suppressions_list_becomes_suppressions():
    sup = {"file": "a.py", "line": 3, "rule": "E501", "reason": "long url"}
    done = run(valid(suppressions_list=[sup]))
    assert done.fixes == [Fix("suppressions", "renamed", from_="suppressions_list")]
    assert done.obj["suppressions"] == [sup] and "suppressions_list" not in done.obj
    done = run(valid(suppressions_list=[sup], suppressions=[]))
    assert done.fixes == [Fix("suppressions_list", "dropped")] and done.obj["suppressions"] == []


def test_rule_1_other_unknown_keys_stay():
    assert run(valid(extra={"a": 1})).obj["extra"] == {"a": 1}


# rules 2 and 3: phase and task_ids
def test_rule_2_phase_is_the_steps_phase_replaced_only_when_the_agent_gave_another():
    done = run(valid(phase="green"))
    assert done.obj["phase"] == "red" and done.fixes == [Fix("phase", "replaced")]
    assert run(valid(phase=7)).fixes == [Fix("phase", "replaced")]
    obj = valid()
    del obj["phase"]
    assert run(obj).fixes == []
    assert run(valid(phase="single"), facts("single")).fixes == []


def test_rule_3_task_ids_is_the_task_key():
    done = run(valid(task_ids=["9.9", "1.1"]))
    assert done.obj["task_ids"] == ["1.1"] and done.fixes == [Fix("task_ids", "replaced")]
    assert run(valid(task_ids="1.1")).fixes == [Fix("task_ids", "replaced")]
    obj = valid()
    del obj["task_ids"]
    assert run(obj).fixes == []


def test_rule_3_with_no_task_key_the_agents_valid_list_stays_and_the_schema_holds():
    no_task = StepFacts("red", None, CHANGED, None)
    assert run(valid(task_ids=["2.1"]), no_task).obj["task_ids"] == ["2.1"]
    assert run(valid(task_ids=[]), no_task).obj["task_ids"] == ["unknown"]


# rules 4 and 5: files_changed and tests_added
def test_rule_4_files_changed_comes_from_git_and_a_wrong_type_is_a_fix():
    objects = [{"path": "tests/test_split.py", "kind": "test"}]
    done = run(valid(files_changed=objects))
    assert done.obj["files_changed"] == list(CHANGED) and done.fixes == [Fix("files_changed", "replaced")]
    done = run(valid(files_changed=["only/this.py"]))  # a valid list is replaced without a fix
    assert done.obj["files_changed"] == list(CHANGED) and done.fixes == []


def test_rule_5_tests_added_is_empty_and_dotted_ids_are_not_a_fix():
    done = run(valid(tests_added=["tests/test_split.py::test_a", "pkg.mod.test_b"]))
    assert done.obj["tests_added"] == [] and done.fixes == []
    done = run(valid(tests_added=[{"id": "x"}]))
    assert done.obj["tests_added"] == [] and done.fixes == [Fix("tests_added", "dropped")]


# rule 6: questions (SCN-IMP-192, SCN-IMP-197)
def test_rule_6_a_malformed_question_is_dropped_and_blocked_stays_blocked():
    no_kind = {"title": "t", "context": "c"}
    done = run(valid(status="blocked", questions=[no_kind, dict(QUESTION)]))
    assert done.obj["status"] == "blocked" and done.obj["questions"] == [QUESTION]
    assert done.fixes == [Fix("questions", "dropped", count=1)]


def test_rule_6_a_done_result_with_a_question_stays_done():
    done = run(valid(questions=[dict(QUESTION)]))
    assert done.obj["status"] == "done" and done.fixes == []


def test_rule_6_every_malformed_shape_is_dropped():
    bad = [
        "text", 3, None, ["x"], {"title": "t", "context": "c", "kind": "weird"},
        {"title": 1, "context": "c", "kind": "product"}, {"title": "t", "context": ["c"], "kind": "product"},
        {"title": "t", "context": "c", "kind": ["product"]},
    ]  # fmt: skip
    done = run(valid(status="blocked", questions=[*bad, dict(QUESTION)]))
    assert done.obj["questions"] == [QUESTION] and done.fixes == [Fix("questions", "dropped", count=len(bad))]


def test_rule_6_questions_that_is_not_a_list_is_dropped():
    done = run(valid(status="blocked", questions={"title": "t"}))
    assert done.obj["status"] == "blocked" and done.obj.get("questions", []) == []
    assert done.fixes == [Fix("questions", "dropped")]


def test_rule_6_bad_options_and_blocking_tasks_are_removed_from_the_item():
    q = {**QUESTION, "options": ["a", 2], "blocking_tasks": "1.2"}
    good = {**QUESTION, "options": ["a", "b"], "blocking_tasks": ["1.2"]}
    done = run(valid(status="blocked", questions=[q, good]))
    assert done.obj["questions"] == [QUESTION, good]
    assert done.fixes == [
        Fix("questions.options", "dropped", count=1),
        Fix("questions.blocking_tasks", "dropped", count=1),
    ]


def test_rule_6_after_three_the_rest_are_cut_in_order():
    qs = [{**QUESTION, "title": f"q{i}"} for i in range(5)]
    done = run(valid(status="blocked", questions=qs))
    assert [q["title"] for q in done.obj["questions"]] == ["q0", "q1", "q2"]
    assert done.fixes == [Fix("questions", "cut", count=2)]
    mixed = run(valid(status="blocked", questions=[{"title": "bad"}, *qs]))  # a dropped one does not take a place
    assert [q["title"] for q in mixed.obj["questions"]] == ["q0", "q1", "q2"]
    assert mixed.fixes == [Fix("questions", "dropped", count=1), Fix("questions", "cut", count=2)]


# rule 7: status (SCN-IMP-188, SCN-IMP-197)
def test_rule_7_a_phase_name_status_becomes_done():
    done = run(valid(status="red"))
    assert done.obj["status"] == "done" and done.fixes == [Fix("status", "set", to="done", was="red")]
    done = run(valid(status=" Green ", phase="green"), facts("green"))
    assert done.fixes == [Fix("status", "set", to="done", was="green")]
    assert run(valid(status="single")).fixes == [Fix("status", "set", to="done", was="single")]


def test_rule_7_the_form_of_an_allowed_status_is_fixed_and_the_value_kept():
    for given, want in [("Done", "done"), (" failed\n", "failed"), ("PARTIAL", "partial"), ("BLOCKED", "blocked")]:
        done = run(valid(status=given))
        assert done.obj["status"] == want and done.fixes == [Fix("status", "replaced")], given


def test_rule_7_blocked_with_no_question_stays_blocked_and_no_question_is_made():
    for given in ("blocked", "BLOCKED", " Blocked "):
        done = run(valid(status=given, summary="needs a database URL"))
        assert done.obj["status"] == "blocked" and not done.obj.get("questions"), given


def test_rule_7_a_missing_status_with_a_question_is_blocked():
    obj = valid(questions=[dict(QUESTION)])
    del obj["status"]
    done = run(obj)
    assert done.obj["status"] == "blocked" and done.obj["questions"] == [QUESTION]
    assert done.fixes == [Fix("status", "set", to="blocked")]


def test_rule_7_an_unknown_status_with_no_question_becomes_done():
    for given in ("great", "", 5, True, ["done"], {"a": 1}):
        done = run(valid(status=given))
        assert done.obj["status"] == "done" and done.fixes == [Fix("status", "set", to="done")], repr(given)
    obj = valid()
    del obj["status"]
    assert run(obj).fixes == [Fix("status", "set", to="done")]


def test_rule_7_the_questions_left_by_rule_6_decide():
    done = run(valid(status="great", questions=[{"title": "no kind"}]))
    assert done.obj["status"] == "done"
    done = run(valid(status="red", questions=[dict(QUESTION)]))
    assert done.fixes == [Fix("status", "set", to="blocked", was="red")]


# rule 8: summary
def test_rule_8_a_missing_summary_is_the_final_message_trimmed():
    obj = valid()
    del obj["summary"]
    done = run(obj, facts(last="\n  Added two tests; they fail as expected.  \n"))
    assert done.obj["summary"] == "Added two tests; they fail as expected."
    assert done.fixes == [Fix("summary", "set", from_="final_message")]


def test_rule_8_the_objects_own_json_text_is_taken_out_of_the_final_message():
    obj = {"status": "done"}
    text = json.dumps(obj)
    done = run(obj, facts(last=f"Added the tests.\n```json\n{text}\n```"), "final_message", text)
    assert "{" not in done.obj["summary"] and done.obj["summary"].startswith("Added the tests.")
    done = run(obj, facts(last=text), "final_message", text)  # only the object: nothing is left
    assert done.obj["summary"] == NO_SUMMARY
    assert done.fixes == [Fix("summary", "set", from_="none")]


@pytest.mark.parametrize("bad", ["", "   \n", 7, None, ["s"], {"a": 1}])
def test_rule_8_a_summary_that_is_not_a_non_empty_string_is_replaced(bad):
    done = run(valid(summary=bad), facts(last="what I did"))
    assert done.obj["summary"] == "what I did" and done.fixes == [Fix("summary", "set", from_="final_message")]


def test_rule_8_notes_come_next_and_then_the_fixed_text():
    done = run(valid(summary="", notes_for_verifier="the notes"), facts(last="  "))
    assert done.obj["summary"] == "the notes" and done.fixes == [Fix("summary", "set", from_="notes_for_verifier")]
    done = run(valid(summary=""), facts(last=None))
    assert done.obj["summary"] == NO_SUMMARY and done.fixes == [Fix("summary", "set", from_="none")]
    done = run(valid(summary="", notes="renamed first"), facts(last=None))  # rule 1 runs before rule 8
    assert done.obj["summary"] == "renamed first"


def test_rule_8_a_present_summary_is_not_touched_by_the_final_message():
    done = run(valid(summary="mine"), facts(last="the final message"))
    assert done.obj["summary"] == "mine" and done.fixes == []


# rules 9 to 12: drops
def test_rule_9_notes_for_verifier_that_is_not_a_string_is_dropped():
    done = run(valid(notes_for_verifier=["a"]))
    assert "notes_for_verifier" not in done.obj and done.fixes == [Fix("notes_for_verifier", "dropped")]


def test_rule_10_criteria_ids_keeps_matching_strings_only():
    ids = [CRITERION, "C-short", 5, "c-0a1b2c3d", "C-0a1b2c3dX", "C-ffffffff"]
    done = run(valid(criteria_ids=ids))
    assert done.obj["criteria_ids"] == [CRITERION, "C-ffffffff"]
    assert done.fixes == [Fix("criteria_ids", "dropped", count=4)]
    done = run(valid(criteria_ids="C-0a1b2c3d"))
    assert "criteria_ids" not in done.obj and done.fixes == [Fix("criteria_ids", "dropped")]


def test_rule_11_a_suppression_with_a_missing_or_wrong_part_is_dropped_never_repaired():
    good = {"file": "a.py", "line": 3, "rule": "E501", "reason": "long url"}
    bad = [
        {k: v for k, v in good.items() if k != "line"}, {**good, "line": "3"}, {**good, "line": 3.5},
        {**good, "line": True}, {**good, "file": 1}, {**good, "rule": None}, {**good, "reason": 5}, "a.py:3", [],
    ]  # fmt: skip
    done = run(valid(suppressions=[*bad, good]))
    assert done.obj["suppressions"] == [good] and done.fixes == [Fix("suppressions", "dropped", count=len(bad))]
    done = run(valid(suppressions={"file": "a.py"}))
    assert "suppressions" not in done.obj and done.fixes == [Fix("suppressions", "dropped")]


def test_scn_imp_192_a_suppression_without_a_line_is_not_declared():
    done = run(valid(suppressions=[{"file": "a.py", "rule": "E501", "reason": "x"}]))
    assert done.obj["suppressions"] == []


def test_rule_12_a_wrong_shaped_exemption_or_lesson_list_is_dropped():
    done = run(valid(tdd_exemption="because", lesson_proposals="a lesson"))
    assert "tdd_exemption" not in done.obj and "lesson_proposals" not in done.obj
    assert done.fixes == [Fix("tdd_exemption", "dropped"), Fix("lesson_proposals", "dropped")]
    assert run(valid(tdd_exemption={"reason": 3})).fixes == [Fix("tdd_exemption", "dropped")]
    assert run(valid(lesson_proposals=[{"text": 1}])).fixes == [Fix("lesson_proposals", "dropped")]
    assert run(valid(lesson_proposals=["x"])).fixes == [Fix("lesson_proposals", "dropped")]
    ok = run(valid(tdd_exemption={"reason": "r"}, lesson_proposals=[{"text": "t", "scope": "s"}]))
    assert ok.fixes == [] and ok.obj["tdd_exemption"] == {"reason": "r"}


# rule 13: cuts (SCN-IMP-190)
def cut_ok(out: str, original: str, limit: int) -> None:
    assert len(out) <= limit
    match = re.search(r"\[cut by L4: (\d+) characters removed\]$", out)
    assert match, out[-60:]
    kept = out[: match.start()]
    assert original.startswith(kept) and int(match.group(1)) == len(original) - len(kept)
    assert len(out) == limit  # the most it can keep


def test_rule_13_a_long_notes_text_keeps_its_start_and_ends_with_the_marker():
    text = "n" * 2417
    done = run(valid(notes_for_verifier=text))
    assert done.fixes == [Fix("notes_for_verifier", "cut", length=2417)]
    cut_ok(done.obj["notes_for_verifier"], text, NOTES_MAX)


def test_rule_13_a_long_suppression_reason_is_cut_and_the_suppression_stays():
    sup = {"file": "a.py", "line": 3, "rule": "E501", "reason": "r" * 350}
    done = run(valid(suppressions=[sup]))
    assert done.fixes == [Fix("suppressions.reason", "cut", length=350)]
    assert len(done.obj["suppressions"]) == 1
    cut_ok(done.obj["suppressions"][0]["reason"], sup["reason"], REASON_MAX)
    assert {k: v for k, v in done.obj["suppressions"][0].items() if k != "reason"} == {
        "file": "a.py", "line": 3, "rule": "E501",
    }  # fmt: skip


def test_rule_13_a_long_summary_and_one_at_the_limit():
    text = "s" * 9000
    done = run(valid(summary=text))
    assert done.fixes == [Fix("summary", "cut", length=9000)]
    cut_ok(done.obj["summary"], text, SUMMARY_MAX)
    exact = "e" * SUMMARY_MAX
    done = run(valid(summary=exact))
    assert done.obj["summary"] == exact and done.fixes == []
    done = run(valid(summary=exact + "x"))  # one over: cut
    cut_ok(done.obj["summary"], exact + "x", SUMMARY_MAX)


def test_rule_13_a_summary_taken_from_a_long_final_message_is_set_then_cut():
    obj = valid()
    del obj["summary"]
    done = run(obj, facts(last="m" * 3000))
    assert done.fixes == [Fix("summary", "set", from_="final_message"), Fix("summary", "cut", length=3000)]
    cut_ok(done.obj["summary"], "m" * 3000, SUMMARY_MAX)


def test_the_cut_marker_is_the_constant():
    assert CUT_MARKER.format(n=12) == "[cut by L4: 12 characters removed]"


# the record holds no text of the agent
def test_the_events_hold_no_text_of_the_agent():
    secret = "SECRET-TEXT-9d1c"
    obj = {
        "status": f"{secret}-red", "phase": secret, "task_ids": [secret], "summary": 3,
        "notes": secret * 700, "files_changed": [{"path": secret}], "tests_added": [secret, {secret: 1}],
        "questions": [{"title": secret}, {**QUESTION, "title": secret, "options": [1]}] * 3,
        "criteria_ids": [secret],
        "suppressions": [{"file": secret}, {"file": secret, "line": 1, "rule": secret, "reason": secret * 200}],
        "tdd_exemption": secret, "lesson_proposals": secret, "suppressions_list": [secret], secret: secret,
    }  # fmt: skip
    done = normalize(Found(obj, "result"), facts(last=secret))
    events = [f.as_event() for f in done.fixes]
    assert events and secret not in json.dumps(events)
    assert secret not in json.dumps([vars(f) for f in done.fixes])
    for event in events:
        assert set(event) <= {"field", "fix", "from", "to", "was", "count", "length"}
        assert event["fix"] in {"set", "replaced", "renamed", "dropped", "cut"}


# the property test
def random_value(rng: random.Random, depth: int = 0) -> Any:
    kinds = ["none", "bool", "int", "float", "str", "long", "list", "dict"]
    kind = rng.choice(kinds if depth < 2 else kinds[:6])
    if kind == "none":
        return None
    if kind == "bool":
        return rng.random() < 0.5
    if kind == "int":
        return rng.randint(-3, 99999)
    if kind == "float":
        return rng.random() * 10
    if kind == "str":
        return rng.choice(["", " ", "done", "red", "BLOCKED", "x", "C-0a1b2c3d", "technical", "blocked "])
    if kind == "long":
        return "L" * rng.randint(250, 4500)
    if kind == "list":
        return [random_value(rng, depth + 1) for _ in range(rng.randint(0, 4))]
    return {
        rng.choice(["title", "context", "kind", "a", "file"]): random_value(rng, depth + 1)
        for _ in range(rng.randint(0, 3))
    }


def random_question(rng: random.Random) -> Any:
    if rng.random() < 0.3:
        return random_value(rng)
    q: dict[str, Any] = {
        "title": f"t{rng.randint(0, 99)}",
        "context": "c",
        "kind": rng.choice(["technical", "product", "ambiguous", "x"]),
    }
    for key in rng.sample(["title", "context", "kind"], rng.randint(0, 1)):
        q.pop(key)
    if rng.random() < 0.3:
        q["options"] = rng.choice([["a", "b"], "a", [1], None])
    return q


def random_suppression(rng: random.Random) -> Any:
    if rng.random() < 0.2:
        return random_value(rng)
    s: dict[str, Any] = {
        "file": "a.py",
        "line": rng.choice([1, 2, "3", None, True]),
        "rule": "E1",
        "reason": "r" * rng.choice([5, 301, 900]),
    }
    if rng.random() < 0.2:
        s.pop(rng.choice(list(s)))
    return s


def random_object(rng: random.Random) -> dict[str, Any]:
    obj: dict[str, Any] = {
        "status": rng.choice(["done", "blocked", "failed", "partial", "red", "BLOCKED", " Done", "x", None, 3]),
        "phase": rng.choice(["red", "green", "single", "other", 4]),
        "task_ids": rng.choice([["1.1"], ["2"], [], "1.1", [1]]),
        "summary": rng.choice(["ok", "", "L" * 2500, None, 5, ["x"]]),
        "criteria_ids": [rng.choice(["C-0a1b2c3d", "C-bad", 7, "C-ffffffff"]) for _ in range(rng.randint(0, 4))],
        "questions": [random_question(rng) for _ in range(rng.randint(0, 6))],
        "suppressions": [random_suppression(rng) for _ in range(rng.randint(0, 3))],
        "notes_for_verifier": rng.choice(["n", "N" * 2600, 4, None]),
        "files_changed": rng.choice([["a"], [{"p": 1}], "a", None]),
        "tests_added": rng.choice([["t::a"], ["dotted.id"], [1], None, "x"]),
        "tdd_exemption": rng.choice([None, {"reason": "r"}, "x", {"reason": 3}]),
        "lesson_proposals": rng.choice([None, [{"text": "t"}], "x", [1]]),
        "notes": rng.choice(["alias", None, 5]),
        "suppressions_list": rng.choice([None, [], "x"]),
    }
    for key in rng.sample(sorted(obj), rng.randint(0, 5)):  # random keys removed
        del obj[key]
    for _ in range(rng.randint(0, 3)):  # random keys of random types, over a real one or new
        obj[rng.choice(["extra", "summary", "status", "questions", "reason", "tdd_exemption"])] = random_value(rng)
    return obj


def well_formed(question: Any) -> bool:
    return (
        isinstance(question, dict)
        and isinstance(question.get("title"), str)
        and isinstance(question.get("context"), str)
        and question.get("kind") in ("technical", "product", "ambiguous")
    )


def triple(question: dict[str, Any]) -> tuple[str, str, str]:
    return (question["title"], question["context"], question["kind"])


def test_property_normalized_random_broken_objects_always_validate():
    rng = random.Random(20261016)
    for _ in range(600):
        obj = random_object(rng)
        given = copy.deepcopy(obj)
        last = rng.choice([None, "", "  ", "a final message", "F" * 3000])
        done = normalize(Found(obj, "result"), facts(rng.choice(["red", "green", "single"]), last))
        assert obj == given  # the input stays as it was
        parsed = parse_result(done.obj)  # never raises
        old_questions = (
            [q for q in given.get("questions") or [] if well_formed(q)]
            if isinstance(given.get("questions"), list)
            else []
        )
        assert [triple(q) for q in done.obj.get("questions", [])] == [triple(q) for q in old_questions][:3]
        old_ids = given.get("criteria_ids") if isinstance(given.get("criteria_ids"), list) else []
        assert set(done.obj.get("criteria_ids", [])) <= set(old_ids)
        old_sup = (
            given.get("suppressions") if isinstance(given.get("suppressions"), list) else given.get("suppressions_list")
        )
        old_sup = old_sup if isinstance(old_sup, list) else []
        old_keys = [(o.get("file"), o.get("line"), o.get("rule")) for o in old_sup if isinstance(o, dict)]
        assert all((s["file"], s["line"], s["rule"]) in old_keys for s in done.obj.get("suppressions", []))
        assert len(done.obj.get("suppressions", [])) <= len(old_sup)
        assert parsed.summary and len(parsed.summary) <= SUMMARY_MAX
        if isinstance(given.get("status"), str) and given["status"].strip().lower() in (
            "blocked",
            "done",
            "failed",
            "partial",
        ):
            assert done.obj["status"] == given["status"].strip().lower()  # a present allowed status is never changed
        for fix in done.fixes:
            assert set(fix.as_event()) <= {"field", "fix", "from", "to", "was", "count", "length"}


def test_property_a_valid_blocked_input_stays_blocked_with_its_questions():
    rng = random.Random(7)
    for _ in range(200):
        questions = [dict(QUESTION, title=f"q{i}") for i in range(rng.randint(0, 3))]
        obj = {"status": "blocked", "phase": "red", "task_ids": ["1.1"], "summary": "s", "questions": questions}
        done = run(obj, facts(rng.choice(["red", "green"])))
        assert done.obj["status"] == "blocked" and done.obj.get("questions", []) == questions
