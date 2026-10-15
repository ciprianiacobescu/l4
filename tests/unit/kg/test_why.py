"""`kg.why`: the history of one record (L4-KG-010; SCN-KG-20, SCN-KG-21)."""

import pytest

from l4.exitcodes import ExitCode, L4Exit
from l4.kg.view import event_seq
from l4.kg.why import ACCEPTED_FORMS, explain
from l4.memory.curate import UI_GAP_KEY, UI_GAP_TITLE
from l4.redact import Redactor

from ._readers import index


def why(kg_repo, target, **kw) -> str:
    idx = index(kg_repo)
    return explain(idx.nodes, idx.edges, target, **kw)


def stop(code, detail, to="escalated"):
    return ("phase.changed", {"from": "implementing", "to": to, "reason": code, "detail": detail})


def restarted_unit(kg_repo):
    """SCN-KG-20: attempt 1 escalated twice with `same_failure`, was restarted; attempt 2 has one FAIL round."""
    kg_repo.unit(
        "openspec:a", where="attempt:1",
        runs=[
            kg_repo.run(stop("same_failure", "lint failed the same way")),
            kg_repo.run(("unit.retried", {"reason": "retry", "by": "operator"}), stop("same_failure", "lint again")),
        ],
    )  # fmt: skip
    crit = kg_repo.criterion("cart › Cart › Shows count")
    found = kg_repo.finding("Edge case not handled", source="judge", criterion=crit.id)
    kg_repo.unit(
        "openspec:a", where="branch",
        runs=[kg_repo.run(
            kg_repo.restart_event("openspec:a", 1, reason="stuck on lint"),
            ("verify.verdict", {"round": 1, "verdict": "FAIL"}),
        )],
        verdicts=[kg_repo.verdict(1, "FAIL", findings=[found], criteria=[crit], gates=[kg_repo.gate("lint")])],
    )  # fmt: skip


def test_scn_kg_20_the_history_of_a_restarted_unit(kg_repo):
    restarted_unit(kg_repo)
    text = why(kg_repo, "openspec:a")
    lines = text.splitlines()
    assert lines[-1] == "stops: same_failure ×2; spec edited since the last stop: no; attempt 2"
    assert "lint failed the same way" in text and "lint again" in text  # both escalations, with their detail
    assert "restarted: stuck on lint" in text
    assert text.index("Attempt 1") < text.index("lint failed the same way") < text.index("Attempt 2")
    attempt2 = text[text.index("Attempt 2") :]
    assert "round 1: FAIL" in attempt2 and "failed gates: lint" in attempt2 and "unknown n = 1" in attempt2
    assert "`l4 status --unit openspec:a`" in text


def test_every_timeline_line_ends_with_its_src(kg_repo):
    restarted_unit(kg_repo)
    body = [line for line in why(kg_repo, "openspec:a").splitlines() if line.startswith("  ")]
    assert body
    for line in body:
        assert line.endswith("]") and "[src " in line, line


def test_a_unit_without_stops_or_restarts_is_attempt_one(kg_repo):
    kg_repo.unit("openspec:a", where="base", runs=[kg_repo.run(("x.y", {}))])
    last = why(kg_repo, "openspec:a").splitlines()[-1]
    assert last == "stops: none (n = 0); spec edited since the last stop: no stop; attempt 1"


def test_a_spec_edit_after_the_last_stop_is_reported(kg_repo):
    kg_repo.unit(
        "openspec:a", where="branch",
        runs=[
            kg_repo.run(stop("baseline_failed", "red base", to="halted")),
            kg_repo.run(("unit.retried", {"reason": "spec edited", "by": "push", "signal": "spec_edit:abc"})),
        ],
    )  # fmt: skip
    text = why(kg_repo, "openspec:a")
    assert text.splitlines()[-1] == "stops: baseline_failed ×1; spec edited since the last stop: yes; attempt 1"
    assert "retried: spec edited" in text


def test_a_spec_edit_before_the_last_stop_is_not_reported(kg_repo):
    kg_repo.unit(
        "openspec:a", where="branch",
        runs=[
            kg_repo.run(("unit.retried", {"reason": "spec edited", "by": "push"})),
            kg_repo.run(stop("baseline_failed", "red base", to="halted")),
        ],
    )  # fmt: skip
    assert "spec edited since the last stop: no;" in why(kg_repo, "openspec:a").splitlines()[-1]


def test_stops_are_listed_by_count_then_code(kg_repo):
    kg_repo.unit(
        "openspec:a", where="branch",
        runs=[kg_repo.run(stop("b_code", "x"), stop("a_code", "y"), stop("a_code", "z"), stop("c_code", "w"))],
    )  # fmt: skip
    assert why(kg_repo, "openspec:a").splitlines()[-1].startswith("stops: a_code ×2, b_code ×1, c_code ×1;")


def test_a_kept_attempt_that_is_not_local_says_so(kg_repo):
    kg_repo.unit("openspec:a", where="branch", runs=[kg_repo.run(kg_repo.restart_event("openspec:a", 1))])
    text = why(kg_repo, "openspec:a")
    assert "Attempt 1: no records in the index (the ref is not local)" in text
    assert text.splitlines()[-1].endswith("attempt 2")


def test_a_question_and_its_answer_are_on_the_timeline(kg_repo):
    kg_repo.unit(
        "openspec:a", where="branch",
        runs=[kg_repo.run(
            ("question.raised", {"id": "Q-001", "kind": "product", "source": "intake", "title": "Which one?"}),
            ("question.answered", {"id": "Q-001", "by": "human"}),
        )],
    )  # fmt: skip
    text = why(kg_repo, "openspec:a")
    assert "question Q-001: product, answered by human" in text
    assert "Which one?" not in text  # the index holds no question text


# --- the 1-hop view -----------------------------------------------------------------------------------------


def graph_repo(kg_repo):
    kg_repo.lessons(kg_repo.lesson("UI criteria need an end-to-end test", UI_GAP_KEY))
    crit = kg_repo.criterion("cart › Cart › Shows count")
    found = kg_repo.finding(UI_GAP_TITLE, criterion=crit.id)
    kg_repo.unit(
        "openspec:a", where="branch",
        runs=[kg_repo.run(
            ("prompt.rendered", {"role": "red", "task": "1.1", "lessons": ["L-09421538"]}),
            ("question.raised", {"id": "Q-001", "kind": "ambiguous", "source": "intake", "title": "t"}),
        )],
        verdicts=[kg_repo.verdict(1, "FAIL", findings=[found], criteria=[crit])],
    )  # fmt: skip
    return found


def test_a_finding_shows_its_edges_with_src(kg_repo):
    found = graph_repo(kg_repo)
    text = why(kg_repo, found.id)
    assert text.splitlines()[0].startswith(f"finding {found.id}")
    assert "RAISED: openspec:a@0#round-1 (round) -> " + found.id in text
    assert "KEYED: " + found.id + " (finding) -> recurrence:ui criterion without an end-to-end test | cart" in text
    edge_lines = [line for line in text.splitlines() if line.startswith("- ")]
    assert len(edge_lines) >= 4 and all("[src " in line for line in edge_lines)


def test_a_lesson_shows_where_it_was_injected_and_what_it_is_keyed_to(kg_repo):
    graph_repo(kg_repo)
    text = why(kg_repo, "L-09421538")
    assert text.splitlines()[0].startswith("lesson L-09421538")
    assert "INJECTED: r-" in text and "-> L-09421538 (lesson)" in text
    assert "KEYED: L-09421538 (lesson) -> recurrence:ui criterion without an end-to-end test" in text


def test_a_run_and_a_question_have_a_view(kg_repo):
    graph_repo(kg_repo)
    idx = index(kg_repo)
    run = next(n.id for n in idx.nodes if n.type == "run")
    assert why(kg_repo, run).splitlines()[0].startswith(f"run {run}")
    assert "HAS_RUN: openspec:a@0 (attempt) -> " + run in why(kg_repo, run)
    question = why(kg_repo, "openspec:a#Q-001")
    assert question.splitlines()[0].startswith("question openspec:a#Q-001")
    assert "ASKED: " in question and "CLASSIFIED: openspec:a#Q-001 (question) -> blame:spec" in question


def test_a_view_longer_than_the_cap_says_how_many_were_left_out(kg_repo):
    runs = [
        kg_repo.run(("prompt.rendered", {"role": "red", "task": f"{i}.1", "lessons": ["L-0000aaaa"]})) for i in range(5)
    ]
    kg_repo.unit("openspec:a", where="branch", runs=runs)
    from l4.kg import why as why_module

    old = why_module.MAX_EDGES
    why_module.MAX_EDGES = 2
    try:
        text = why(kg_repo, "L-0000aaaa")
    finally:
        why_module.MAX_EDGES = old
    assert "n = 3 more edges are not shown" in text


# --- SCN-KG-21 and redaction --------------------------------------------------------------------------------


@pytest.mark.parametrize("target", ["X-1", "", "openspec:", "F-1234", "F-deadbeef", "openspec:zzz", "r-nothing"])
def test_scn_kg_21_an_unknown_id_exits_2_and_lists_the_forms(kg_repo, target):
    graph_repo(kg_repo)
    with pytest.raises(L4Exit) as caught:
        why(kg_repo, target)
    assert caught.value.code == ExitCode.USAGE_ERROR
    message = str(caught.value)
    assert ACCEPTED_FORMS in message
    for form in ("openspec:<name>", "kiro:<name>", "F-<8 hex>", "L-<8 hex>", "r-<run id>", "<unit>#Q-<n>"):
        assert form in message


def test_a_redaction_rule_added_after_the_build_still_applies(kg_repo):
    kg_repo.unit("openspec:a", where="branch", runs=[kg_repo.run(stop("same_failure", "token SECRETVALUE123 leaked"))])
    assert "SECRETVALUE123" not in why(kg_repo, "openspec:a", redactor=Redactor({"T": "SECRETVALUE123"}))


def test_the_event_seq_of_a_src_is_the_number_after_the_hash():
    assert event_seq("0123456789:a/b.jsonl#12") == 12
    assert event_seq("0123456789:a/verdict.json#/findings/0") is None
