"""`kg.report`: the markdown report of the index (L4-KG-006, L4-KG-008, L4-KG-009, L4-KG-011; SCN-KG-09 report part,
SCN-KG-12, SCN-KG-13, SCN-KG-14 hotspot part, SCN-KG-16, SCN-KG-17, SCN-KG-18)."""

import random
import re
from pathlib import Path

from l4.kg.normalise import failure_class
from l4.kg.report import DEFAULT_MIN_UNITS, SECTIONS, render
from l4.kg.sources import FETCH_ATTEMPTS
from l4.memory.curate import UI_GAP_KEY, UI_GAP_TITLE
from l4.redact import Redactor

from ._readers import assert_snapshot, digit_lines_without_n, index, section

SNAPSHOTS = Path(__file__).parent / "snapshots"
RED_REASON = "new tests fail with an error that is neither an assertion nor NotImplementedError: tests.test_a::t"
TRACE_REASON = "no new test traces C-e25f06d8: tag your test with the criterion id"
LESSON_ID = "L-09421538"  # lesson_id(UI_GAP_KEY)


def report(kg_repo, **kw) -> str:
    idx = index(kg_repo)
    return render(idx.nodes, idx.edges, **{**idx.context(), **kw})


def failed(task="1.1", phase="red", attempt=1, reason=TRACE_REASON):
    return ("task.attempt_failed", {"task": task, "phase": phase, "attempt": attempt, "reason": reason})


def prompt(task="1.1", role="red", lessons=(LESSON_ID,)):
    return ("prompt.rendered", {"role": role, "task": task, "lessons": list(lessons)})


def stop(code, detail="", to="escalated"):
    return ("phase.changed", {"from": "implementing", "to": to, "reason": code, "detail": detail})


def finding_verdicts(kg_repo, title=UI_GAP_TITLE, alias="cart › Cart › Shows count", *, verdict="FAIL", **kw):
    crit = kg_repo.criterion(alias)
    found = kg_repo.finding(title, criterion=crit.id, **kw)
    return [kg_repo.verdict(1, verdict, findings=[found], criteria=[crit], implementer_profiles=["impl-a"])]


def lines_of(text: str, title: str) -> list[str]:
    return [line for line in section(text, title).splitlines() if line.startswith("- ")]


# --- the shape: order, n on every number, none (n = 0), determinism -----------------------------------------


def scn06(kg_repo):
    """An archived unit with a ledger and two verdicts, and an open unit whose ledger is only on its branch."""
    kg_repo.lessons(kg_repo.lesson("UI criteria need an end-to-end test", UI_GAP_KEY, scope=["src/web/**"]))
    crit = kg_repo.criterion("cart › Cart › Shows count")
    first = kg_repo.verdict(
        1, "FAIL", findings=[kg_repo.finding(UI_GAP_TITLE, criterion=crit.id)],
        criteria=[crit], gates=[kg_repo.gate("lint")],
        judge_profile="judge-a", implementer_profiles=["impl-a"],
    )  # fmt: skip
    second = kg_repo.verdict(2, "PASS", judge_profile="judge-a", implementer_profiles=["impl-a"])
    kg_repo.unit(
        "openspec:a", where="archive", verdicts=[first, second],
        runs=[kg_repo.run(
            ("availability.selected", {"role": "implementer", "selected": "impl-a"}),
            prompt(), failed(reason=RED_REASON), prompt(), prompt(role="green"),
        )],
    )  # fmt: skip
    kg_repo.unit(
        "openspec:b", where="branch",
        runs=[kg_repo.run(
            ("availability.selected", {"role": "implementer", "selected": "impl-b"}),
            ("question.raised", {"id": "Q-001", "kind": "ambiguous", "source": "intake", "title": "Which one?"}),
            stop("baseline_failed", "the base is red", to="halted"),
        )],
    )  # fmt: skip


def test_the_sections_come_in_the_order_of_design_d8(kg_repo):
    scn06(kg_repo)
    text = report(kg_repo)
    headings = [line[3:].split(" (")[0] for line in text.splitlines() if line.startswith("## ")]
    assert headings == list(SECTIONS)
    assert SECTIONS[0] == "Coverage" and SECTIONS[-1] == "Stops"


def test_scn_kg_18_snapshot_and_every_number_names_its_n(kg_repo):
    scn06(kg_repo)
    text = report(kg_repo, base_sha="0123456789abcdef0123456789abcdef01234567", base_date="2026-10-01T08:00:00+00:00")
    assert digit_lines_without_n(text) == []
    assert_snapshot(SNAPSHOTS / "report_scn_kg_06.md", text)


def test_an_empty_index_says_none_in_every_section():
    text = render([], [], base_ref="HEAD", base_sha=None, base_date=None, skipped={})
    for title in SECTIONS[1:]:
        assert "none (n = 0)" in section(text, title), title
    assert digit_lines_without_n(text) == []


def test_equal_inputs_give_equal_text_whatever_the_order(kg_repo):
    scn06(kg_repo)
    idx = index(kg_repo)
    base = render(idx.nodes, idx.edges, **idx.context())
    nodes, edges = list(idx.nodes), list(idx.edges)
    random.Random(7).shuffle(nodes)
    random.Random(8).shuffle(edges)
    assert render(nodes, edges, **idx.context()) == base


def test_every_key_based_section_says_approximate(kg_repo):
    text = report(kg_repo)
    for title in ("Lessons", "Recurring attempt failures", "Recurring findings", "Gate candidates"):
        heading = next(line for line in text.splitlines() if line.startswith(f"## {title}"))
        assert "approximate" in heading, heading


def test_a_redaction_rule_added_after_the_build_still_applies(kg_repo):
    kg_repo.lessons(kg_repo.lesson("Use token SECRETVALUE123 never", "k1"))
    idx = index(kg_repo)
    text = render(idx.nodes, idx.edges, **idx.context(), redactor=Redactor({"TOKEN": "SECRETVALUE123"}))
    assert "SECRETVALUE123" not in text


# --- coverage -----------------------------------------------------------------------------------------------


def test_coverage_counts_units_by_place_runs_rounds_and_skips(kg_repo):
    scn06(kg_repo)
    kg_repo.unit(
        "openspec:c",
        where="base",
        files={f"{kg_repo.unit_path('openspec:c')}/.l4/ledger/r-20261001T0001Z-0001.jsonl": "{not json\n"},
    )
    text = report(kg_repo, base_sha="0123456789abcdef", base_date="2026-10-01T08:00:00+00:00")
    cover = section(text, "Coverage")
    assert "n = 3 units" in cover
    assert re.search(r"archive n = 1", cover) and re.search(r"branch n = 1", cover)
    assert "n = 2 runs" in cover and "n = 2 rounds" in cover
    assert "ledger_corrupt: n = 1" in cover
    assert "0123456789" in cover and "2026-10-01" in cover


def test_scn_kg_09_an_attempt_that_is_not_local_is_named_with_the_fetch_command(kg_repo):
    kg_repo.unit("openspec:a", where="branch", runs=[kg_repo.run(kg_repo.restart_event("openspec:a", 1))])
    text = report(kg_repo)
    cover = section(text, "Coverage")
    assert "attempt_not_local: n = 1" in cover
    assert FETCH_ATTEMPTS in cover
    assert FETCH_ATTEMPTS not in section(report(kg_repo, skipped={}), "Coverage")  # only when something is missing
    assert "fetch" not in kg_repo.recording_git().subcommands


# --- recurring findings: SCN-KG-12, SCN-KG-13 ---------------------------------------------------------------


def two_units(kg_repo, scenario_a="Shows count", scenario_b="Shows count", **kw):
    for unit, capability, scenario in (("a", "cart", scenario_a), ("b", "basket", scenario_b)):
        verdicts = finding_verdicts(kg_repo, alias=f"{capability} › Cart › {scenario}", **kw)
        kg_repo.unit(f"openspec:{unit}", where="base", verdicts=verdicts, capability=capability)


def test_scn_kg_12_one_mistake_in_two_units_is_one_line(kg_repo):
    two_units(kg_repo)
    (line,) = lines_of(report(kg_repo, min_units=2), "Recurring findings")
    assert "n = 2 units" in line
    assert "openspec:a" in line and "openspec:b" in line
    assert line.startswith("- ui criterion without an end-to-end test | cart › shows count:")
    assert "severity major n = 2" in line and "source deterministic n = 2" in line and "blame agent n = 2" in line


def test_scn_kg_13_the_same_title_on_other_scenarios_is_not_merged(kg_repo):
    two_units(kg_repo, scenario_b="Clears")
    assert section(report(kg_repo, min_units=2), "Recurring findings") != ""
    assert lines_of(report(kg_repo, min_units=2), "Recurring findings") == []
    assert "none (n = 0)" in section(report(kg_repo, min_units=2), "Recurring findings")


def test_min_units_sets_the_floor_and_defaults_to_two(kg_repo):
    two_units(kg_repo, scenario_b="Clears")
    assert DEFAULT_MIN_UNITS == 2
    assert len(lines_of(report(kg_repo, min_units=1), "Recurring findings")) == 2
    assert lines_of(report(kg_repo), "Recurring findings") == []


def test_a_kiro_finding_has_no_scenario_part_and_two_kiro_units_meet(kg_repo):
    for name in ("k1", "k2"):
        crit = kg_repo.criterion("Req 1.1")
        found = kg_repo.finding("Missing test", criterion=crit.id)
        kg_repo.unit(f"kiro:{name}", where="base", verdicts=[kg_repo.verdict(1, findings=[found], criteria=[crit])])
    (line,) = lines_of(report(kg_repo), "Recurring findings")
    assert line.startswith("- missing test: n = 2 units")


# --- recurring attempt failures and gate candidates ---------------------------------------------------------


def failing_units(kg_repo, count, *, phase="red"):
    for i in range(count):
        kg_repo.unit(
            f"openspec:u{i}", where="base", capability=f"cap{i}",
            runs=[kg_repo.run(failed(phase=phase), failed(phase=phase, attempt=2))],
        )  # fmt: skip


def test_recurring_attempt_failures_by_class_with_phase_and_blame(kg_repo):
    failing_units(kg_repo, 2)
    kg_repo.unit("openspec:g", where="base", runs=[kg_repo.run(failed(phase="green"))])
    (line,) = lines_of(report(kg_repo), "Recurring attempt failures")
    assert line == (
        "- no new test traces <criterion>: n = 3 units, n = 5 attempts; phase red n = 4, green n = 1; blame agent n = 5"
    )


def test_a_failure_in_one_unit_is_below_the_floor(kg_repo):
    failing_units(kg_repo, 1)
    assert lines_of(report(kg_repo), "Recurring attempt failures") == []


def test_gate_candidates_need_at_least_three_units(kg_repo):
    failing_units(kg_repo, 2)
    two_units(kg_repo)
    assert lines_of(report(kg_repo), "Gate candidates") == []
    failing_units_c = kg_repo
    failing_units_c.unit("openspec:u9", where="base", runs=[kg_repo.run(failed())])
    kg_repo.unit(
        "openspec:c",
        where="base",
        capability="cap",
        verdicts=finding_verdicts(kg_repo, alias="cap › Cart › Shows count"),
    )
    lines = lines_of(report(kg_repo), "Gate candidates")
    assert [line.split(":")[0] for line in lines] == [
        "- failure class no new test traces <criterion>",
        "- finding ui criterion without an end-to-end test | cart › shows count",
    ]
    assert all("n = 3 units" in line for line in lines)


def test_gate_candidates_use_the_greater_of_n_and_three(kg_repo):
    failing_units(kg_repo, 4)
    assert lines_of(report(kg_repo, min_units=4), "Gate candidates")
    assert not lines_of(report(kg_repo, min_units=5), "Gate candidates")


def test_a_judge_finding_is_a_recurring_finding_but_not_a_gate_candidate(kg_repo):
    for i in range(3):
        v = finding_verdicts(kg_repo, "Edge case not handled", alias=f"cap{i} › R › S", source="judge")
        kg_repo.unit(f"openspec:j{i}", where="base", capability=f"cap{i}", verdicts=v)
    text = report(kg_repo)
    assert any("edge case not handled" in line for line in lines_of(text, "Recurring findings"))
    assert lines_of(text, "Gate candidates") == []


# --- lessons: SCN-KG-16, SCN-KG-17 --------------------------------------------------------------------------


def lesson_repo(kg_repo):
    kg_repo.lessons(kg_repo.lesson("UI criteria need an end-to-end test", UI_GAP_KEY))


def test_scn_kg_16_the_live_case_is_injected_and_followed_by_one_failure(kg_repo):
    lesson_repo(kg_repo)
    events = [prompt(), failed(reason=RED_REASON), prompt(), prompt(role="green")]
    kg_repo.unit("openspec:a", where="branch", runs=[kg_repo.run(*events)])
    (line,) = lines_of(report(kg_repo), "Lessons")
    # the class is cut at 80 characters (L4-KG-006), so the text of SCN-KG-16 loses its last letter: see the report
    assert f"injected 1 unit / 1 task / 3 prompts, followed by 1 failure (red: {failure_class(RED_REASON)})" in line
    assert line.startswith(f'- {LESSON_ID} "UI criteria need an end-to-end test" (n = 3 prompts)')
    assert "n = " in line


def test_scn_kg_17_an_earlier_failure_or_another_units_is_not_counted(kg_repo):
    lesson_repo(kg_repo)
    kg_repo.unit("openspec:a", where="branch", runs=[kg_repo.run(failed(), prompt(), prompt(role="green"))])
    kg_repo.unit("openspec:b", where="branch", runs=[kg_repo.run(failed(task="1.1", reason=RED_REASON))])
    (line,) = lines_of(report(kg_repo), "Lessons")
    assert "injected, nothing followed (1 unit / 1 task / " in line


def test_a_failure_of_another_task_in_the_same_run_is_not_counted(kg_repo):
    lesson_repo(kg_repo)
    kg_repo.unit("openspec:a", where="branch", runs=[kg_repo.run(prompt(task="1.1"), failed(task="2.1"))])
    (line,) = lines_of(report(kg_repo), "Lessons")
    assert "injected, nothing followed (1 unit / 1 task / " in line


def test_a_lesson_never_injected_says_so(kg_repo):
    lesson_repo(kg_repo)
    kg_repo.unit("openspec:a", where="branch", runs=[kg_repo.run(failed())])
    (line,) = lines_of(report(kg_repo), "Lessons")
    assert line.endswith("never injected") and "(n = 0 prompts)" in line


def test_a_later_finding_with_the_linked_key_follows_the_lesson(kg_repo):
    lesson_repo(kg_repo)
    kg_repo.unit(
        "openspec:a", where="branch",
        runs=[kg_repo.run(prompt(), ("verify.verdict", {"round": 1, "verdict": "FAIL"}))],
        verdicts=finding_verdicts(kg_repo),
    )  # fmt: skip
    (line,) = lines_of(report(kg_repo), "Lessons")
    assert "followed by 1 failure (finding: ui criterion without an end-to-end test | cart › shows count)" in line


def test_a_finding_before_the_injection_does_not_follow_it(kg_repo):
    lesson_repo(kg_repo)
    kg_repo.unit(
        "openspec:a", where="branch",
        runs=[kg_repo.run(("verify.verdict", {"round": 1, "verdict": "FAIL"}), prompt())],
        verdicts=finding_verdicts(kg_repo),
    )  # fmt: skip
    (line,) = lines_of(report(kg_repo), "Lessons")
    assert "injected, nothing followed (1 unit / 1 task / " in line


def test_a_lesson_seen_only_in_events_is_listed(kg_repo):
    kg_repo.unit("openspec:a", where="branch", runs=[kg_repo.run(prompt(lessons=["L-0000aaaa"]))])
    (line,) = lines_of(report(kg_repo), "Lessons")
    assert line.startswith("- L-0000aaaa (seen only in events) (n = 1 prompt): injected, nothing followed")


def test_the_lessons_section_says_followed_not_caused(kg_repo):
    assert "not what the lesson caused" in section(report(kg_repo), "Lessons")


# --- spec-gap hotspots: SCN-KG-14 ---------------------------------------------------------------------------


def test_scn_kg_14_a_spec_gap_is_listed_under_its_capability(kg_repo):
    crit = kg_repo.criterion("cart › Cart › Shows count")
    gap = kg_repo.finding("Unclear behaviour", criterion=crit.id, spec_gap=True, source="judge")
    kg_repo.unit("openspec:a", where="base", verdicts=[kg_repo.verdict(1, "FAIL", findings=[gap], criteria=[crit])])
    (line,) = lines_of(report(kg_repo), "Spec-gap hotspots")
    expected = (
        "- cart: n = 1 unit; spec-blame findings n = 1; product or ambiguous questions n = 0; NEEDS_HUMAN rounds n = 0"
    )
    assert line == expected


def test_questions_and_needs_human_rounds_count_for_the_capabilities_of_their_unit(kg_repo):
    crit = kg_repo.criterion("cart › Cart › Shows count")
    kg_repo.unit(
        "openspec:a", where="base",
        verdicts=[kg_repo.verdict(1, "NEEDS_HUMAN", criteria=[crit])],
        runs=[kg_repo.run(
            ("question.raised", {"id": "Q-001", "kind": "ambiguous", "source": "x", "title": "t"}),
            ("question.raised", {"id": "Q-002", "kind": "product", "source": "x", "title": "t"}),
            ("question.raised", {"id": "Q-003", "kind": "technical", "source": "x", "title": "t"}),
        )],
    )  # fmt: skip
    (line,) = lines_of(report(kg_repo), "Spec-gap hotspots")
    expected = (
        "- cart: n = 1 unit; spec-blame findings n = 0; product or ambiguous questions n = 2; NEEDS_HUMAN rounds n = 1"
    )
    assert line == expected


def test_a_kiro_capability_is_its_unit(kg_repo):
    crit = kg_repo.criterion("Req 1.1")
    gap = kg_repo.finding("Unclear", criterion=crit.id, spec_gap=True, source="judge")
    kg_repo.unit("kiro:k", where="base", verdicts=[kg_repo.verdict(1, findings=[gap], criteria=[crit])])
    section_text = section(report(kg_repo), "Spec-gap hotspots")
    assert section_text.startswith("Kiro capabilities are units")
    assert "- k: n = 1 unit;" in section_text


# --- profiles and stops (5.3) -------------------------------------------------------------------------------


def profiles_and_stops(kg_repo):
    pass_v = [kg_repo.verdict(1, "PASS", implementer_profiles=["impl-a"])]
    fail_v = [kg_repo.verdict(1, "FAIL", implementer_profiles=["impl-b"])]
    select_a = ("availability.selected", {"role": "implementer", "selected": "impl-a"})
    select_b = ("availability.selected", {"role": "implementer", "selected": "impl-b"})
    judge = ("availability.selected", {"role": "judge", "selected": "judge-a"})
    kg_repo.unit(
        "openspec:p", where="archive", verdicts=pass_v, runs=[kg_repo.run(select_a, judge, failed(), failed(attempt=2))]
    )
    kg_repo.unit("openspec:q", where="branch", verdicts=fail_v, runs=[kg_repo.run(select_b, failed(task="2.1"))])
    kg_repo.unit(  # a stop that a retry answered, and one still standing
        "openspec:s", where="branch",
        runs=[
            kg_repo.run(stop("same_failure", "x")),
            kg_repo.run(("unit.retried", {"reason": "spec edited", "by": "push"}), stop("same_failure", "y")),
        ],
    )  # fmt: skip
    kg_repo.unit(
        "openspec:r", where="branch",
        runs=[kg_repo.run(stop("verifier_errors", to="halted")), kg_repo.run(kg_repo.restart_event("openspec:r", 1))],
    )  # fmt: skip
    kg_repo.unit("openspec:m", where="archive", runs=[kg_repo.run(stop("verifier_errors", to="halted"))])


def test_profiles_by_role_and_stops_by_code_snapshot(kg_repo):
    profiles_and_stops(kg_repo)
    text = report(kg_repo)
    got = "## Profiles by role\n" + section(text, "Profiles by role") + "\n\n## Stops\n" + section(text, "Stops") + "\n"
    assert_snapshot(SNAPSHOTS / "profiles_stops.md", got)


def test_a_profile_line_counts_runs_failures_and_first_round_passes(kg_repo):
    profiles_and_stops(kg_repo)
    lines = lines_of(report(kg_repo), "Profiles by role")
    impl_a = next(line for line in lines if line.startswith("- implementer / impl-a:"))
    assert "n = 1 run" in impl_a and "n = 1 task with a failed attempt" in impl_a and "n = 2 failed attempts" in impl_a
    assert "first-round PASS n = 1 of n = 1 (100%)" in impl_a
    impl_b = next(line for line in lines if line.startswith("- implementer / impl-b:"))
    assert "first-round PASS n = 0 of n = 1 (0%)" in impl_b


def test_the_profiles_section_says_what_the_index_cannot_tell(kg_repo):
    note = section(report(kg_repo), "Profiles by role")
    assert "first attempt" in note and "no record" in note


def test_a_stop_is_counted_by_how_it_ended(kg_repo):
    profiles_and_stops(kg_repo)
    lines = {line.split(":")[0]: line for line in lines_of(report(kg_repo), "Stops")}
    assert "retried n = 1" in lines["- same_failure"] and "still stopped n = 1" in lines["- same_failure"]
    assert "n = 1 unit, n = 2 stops" in lines["- same_failure"]
    assert "restarted n = 1" in lines["- verifier_errors"] and "merged n = 1" in lines["- verifier_errors"]
    assert "n = 2 units" in lines["- verifier_errors"]
