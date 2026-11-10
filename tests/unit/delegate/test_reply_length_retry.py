"""A reply over a length limit: an escalation is cut and kept, any other decision is refused and asked again
(delegate-length-retry; L4-DLG-029, L4-DLG-005; SCN-DLG-144 to SCN-DLG-152). Every case is at the `check_reply`
level."""

import pytest

from l4.delegate.prompt import batch_schema, delegate_schema
from l4.delegate.reply import Discarded, Kept
from l4.redact import Redactor
from l4.schemacheck import validate
from l4.specs.questions import QuestionKind

from .test_reply import check, cite, reply

MARK = " … [cut at 1000 of {n} characters]"
LENGTH_KEYS = ("maxLength", "maxItems")


def entries(count: int) -> list[dict]:
    return [cite(f"src/pkg/store.py:{n}") for n in range(1, count + 1)]


def escalation(**over) -> dict:
    return reply(decision="escalate", text="", **over)


def refused(got, reason: str) -> None:
    assert isinstance(got, Discarded), got
    assert got.reason == reason and got.retryable is True and got.status == "discarded"


# -- the reason, the entries and their fields (SCN-DLG-144, SCN-DLG-145) ---------------------------------------------


def test_a_reason_over_the_limit_is_refused_and_may_be_asked_again(tmp_path):  # SCN-DLG-144
    got = check(tmp_path, reply(reason="r" * 1001))
    refused(got, "the reason has 1001 characters: the limit is 1000")
    assert got.decision == "answer"
    assert isinstance(check(tmp_path, reply(reason="r" * 1000)), Kept)


def test_every_length_rule_a_reply_breaks_is_named_at_once(tmp_path):  # SCN-DLG-145
    many = [*entries(21), {**cite(), "quote": "q" * 812}, {**cite(), "claim": "c" * 640}]
    got = check(tmp_path, reply(checked=many))
    refused(
        got,
        "the reply has 23 checked entries: the limit is 20; a checked quote has 812 characters: the limit is 600; "
        "a checked claim has 640 characters: the limit is 600",
    )
    assert got.checked == ()  # the entries that break the limits are not recorded
    reasoned = check(tmp_path, reply(reason="r" * 1028, checked=many))
    assert isinstance(reasoned, Discarded) and reasoned.reason.startswith("the reason has 1028 characters")
    assert reasoned.reason.count("; ") == 3


def test_the_longest_value_of_a_field_is_named(tmp_path):  # SCN-DLG-145
    two = [{**cite(), "quote": "q" * 700}, {**cite(), "quote": "q" * 812}]
    refused(check(tmp_path, reply(checked=two)), "a checked quote has 812 characters: the limit is 600")
    reversed_ = [{**cite(), "claim": "c" * 900}, {**cite(), "claim": "c" * 640}]
    refused(check(tmp_path, reply(checked=reversed_)), "a checked claim has 900 characters: the limit is 600")


def test_a_ref_over_the_limit_is_refused_word_for_word(tmp_path):  # SCN-DLG-145
    got = check(tmp_path, reply(checked=[{**cite(), "ref": "r" * 301}]))
    refused(got, "a checked ref has 301 characters: the limit is 300")


@pytest.mark.parametrize(
    ("kind", "body", "decision"),
    [
        (QuestionKind.TECHNICAL, {"decision": "answer"}, "answer"),
        (QuestionKind.TECHNICAL, {"decision": "accept", "text": ""}, "accept"),
        (QuestionKind.VERDICT, {"decision": "reject", "text": "the test does not cover it"}, "reject"),
        (QuestionKind.VERDICT, {"decision": "accept", "text": "the test covers it"}, "accept"),
        (QuestionKind.HARNESS, {"decision": "retry", "text": "run it again"}, "retry"),
    ],
)
def test_every_decision_but_escalate_is_refused_over_a_limit(tmp_path, kind, body, decision):  # SCN-DLG-147
    tasks = () if kind is QuestionKind.VERDICT else ("3.1",)
    suggestion = "Use bcrypt, cost 12." if decision == "accept" and kind is QuestionKind.TECHNICAL else ""
    for over in ({"reason": "r" * 1028}, {"checked": entries(21)}):
        got = check(tmp_path, reply(**body, **over), kind=kind, tasks=tasks, suggestion=suggestion)
        assert isinstance(got, Discarded) and got.retryable is True and got.decision == decision, (over, got)
        assert got.status == "discarded"


# -- an escalation is kept, cut to the limits (SCN-DLG-146, SCN-DLG-148) ----------------------------------------------


def test_an_escalation_over_the_reason_limit_is_cut_and_marked(tmp_path):  # SCN-DLG-146
    reason = "".join(str(n % 10) for n in range(1028))
    got = check(tmp_path, escalation(reason=reason))
    assert isinstance(got, Kept) and got.escalates and got.decision == "escalate"
    assert got.reason == reason[:1000] + MARK.format(n=1028) and got.cut == ("reason",)
    assert got.form is None and got.text is None and got.checked == ({"ref": "spec:design.md#D3"},)
    exact = check(tmp_path, escalation(reason="r" * 1000))
    assert isinstance(exact, Kept) and exact.reason == "r" * 1000 and exact.cut == ()


def test_an_escalation_over_the_entry_limits_drops_those_entries(tmp_path):  # SCN-DLG-148
    many = entries(23)
    many[1] = {**many[1], "ref": "x" * 340}
    many[4] = {**many[4], "quote": "q" * 900, "claim": "c" * 900}
    got = check(tmp_path, escalation(checked=many))
    kept_refs = [e["ref"] for i, e in enumerate(many) if i != 1][:20]
    assert isinstance(got, Kept) and got.cut == ("checked",)
    assert got.checked == tuple({"ref": ref} for ref in kept_refs) and many[4]["ref"] in kept_refs
    both = check(tmp_path, escalation(checked=many, reason="r" * 1028))
    assert isinstance(both, Kept) and both.cut == ("reason", "checked") and len(both.checked) == 20


def test_an_escalation_over_a_quote_or_claim_only_is_kept_whole(tmp_path):  # SCN-DLG-148
    every = [{**cite(f"src/pkg/store.py:{n}"), "quote": "q" * 900, "claim": "c" * 900} for n in range(1, 4)]
    got = check(tmp_path, escalation(checked=every))
    assert isinstance(got, Kept) and got.cut == ()
    assert got.checked == tuple({"ref": f"src/pkg/store.py:{n}"} for n in range(1, 4))


def test_an_escalation_within_every_limit_is_kept_as_before(tmp_path):  # SCN-DLG-146
    got = check(tmp_path, escalation(reason="no document decides", checked=entries(20)))
    assert isinstance(got, Kept) and got.escalates and got.cut == ()
    assert got.reason == "no document decides" and len(got.checked) == 20


def test_a_ref_over_the_limit_is_dropped_not_cut(tmp_path):  # SCN-DLG-148
    got = check(tmp_path, escalation(checked=[{**cite(), "ref": "r" * 301}, cite()]))
    assert isinstance(got, Kept) and got.cut == ("checked",) and got.checked == ({"ref": "spec:design.md#D3"},)


# -- a rule before the length rules is not asked again and not cut (SCN-DLG-151) --------------------------------------


def test_a_decision_that_does_not_fit_wins_over_a_long_reason(tmp_path):  # SCN-DLG-151
    got = check(
        tmp_path,
        reply(reason="r" * 1028, decision="answer"),
        kind=QuestionKind.VERDICT,
        tasks=(),
    )
    assert isinstance(got, Discarded) and got.retryable is False
    assert got.reason == "the decision answer does not fit a verdict question"


def test_a_wrong_question_id_wins_over_a_long_escalation(tmp_path):  # SCN-DLG-151
    got = check(tmp_path, escalation(question="Q-002", reason="r" * 1028))
    assert isinstance(got, Discarded) and got.retryable is False and got.decision == "escalate"
    assert got.reason == "the reply answers Q-002, not Q-001"


def test_a_schema_break_is_not_cut_either(tmp_path):  # SCN-DLG-151
    got = check(tmp_path, escalation(reason="r" * 1028, extra=1))
    assert isinstance(got, Discarded) and got.retryable is False
    assert got.reason.startswith("not an l4/delegate-result@1 document")


# -- the reason is redacted whole before it is cut (SCN-DLG-152) ------------------------------------------------------


def test_a_reason_is_redacted_whole_before_it_is_cut(tmp_path):  # SCN-DLG-152
    token = "FAKEK2mV7pL4nB8wR3tY6uH1cJ5dF0gS4aE7iO2k"
    assert len(token) == 40
    reason = ("lorem ipsum " * 83)[:990] + token + "x" * 70
    assert len(reason) == 1100 and reason[990:1030] == token
    got = check(tmp_path, escalation(reason=reason), redactor=Redactor({"TOKEN": token}))
    assert isinstance(got, Kept) and got.cut == ("reason",)
    redacted = len(reason) - 40 + len("[REDACTED:TOKEN]")
    assert got.reason.endswith(MARK.format(n=redacted)) and "[REDACTED:" in got.reason
    for size in range(4, 41):
        assert token[:size] not in got.reason, size


# -- the result schemas carry no length limit (SCN-DLG-150) -----------------------------------------------------------


def limits_under(schema: dict) -> list[str]:
    """The paths of a `maxLength` or a `maxItems` anywhere in `schema` (a guard: a later change must not add one)."""
    found: list[str] = []

    def walk(node, path: str) -> None:
        if isinstance(node, dict):
            found.extend(f"{path}.{key}" for key in LENGTH_KEYS if key in node)
            for key, value in node.items():
                walk(value, f"{path}.{key}")
        elif isinstance(node, list):
            for n, value in enumerate(node):
                walk(value, f"{path}[{n}]")

    walk(schema, "$")
    return found


def test_the_result_schema_has_no_length_limit():  # SCN-DLG-150
    assert limits_under(delegate_schema()) == []
    assert limits_under(batch_schema(5)) == ["$.properties.results.maxItems"]  # the count of results: not a field


def test_the_batch_schema_keeps_the_count_of_results():  # SCN-DLG-150
    schema = batch_schema(5)
    assert schema["properties"]["results"]["maxItems"] == 5
    item = schema["properties"]["results"]["items"]
    for name in ("reason", "checked"):
        assert not set(LENGTH_KEYS) & set(item["properties"][name])
    for name in ("ref", "quote", "claim"):
        assert not set(LENGTH_KEYS) & set(item["properties"]["checked"]["items"]["properties"][name])
    for name in ("ref", "quote", "claim"):
        assert not set(LENGTH_KEYS) & set(delegate_schema()["properties"]["checked"]["items"]["properties"][name])


def test_a_long_reason_passes_the_schemas_and_is_judged_by_the_length_rules(tmp_path):  # SCN-DLG-150
    long = reply(reason="r" * 1028)
    assert validate(long, delegate_schema()) == []
    assert validate({"results": [long]}, batch_schema(1)) == []
    refused(check(tmp_path, long), "the reason has 1028 characters: the limit is 1000")
    got = check(tmp_path, escalation(reason="r" * 1028))
    assert isinstance(got, Kept) and got.cut == ("reason",)
